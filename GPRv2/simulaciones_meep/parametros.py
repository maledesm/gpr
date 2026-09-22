"""
GPRv2 - Parametros compartidos de las simulaciones MEEP
========================================================

Este archivo lo importan LOS DOS LADOS de la simulacion, que corren en
interpretes distintos:

  - `escena.py`   corre en WSL, en el env conda `meep`. Solo tiene meep y
                  numpy: NO tiene pandas, asi que no puede importar
                  `analisis/correccion_no_linealidad.py`.
  - `radar.py`    corre en el Python de Windows, el mismo que usa el banco,
                  y SI importa `analisis/` para procesar con el mismo
                  pipeline que `vivo_rapido.py`.

Por eso aca no hay NADA que dependa del barrido (T_SWEEP, alpha0, fs). La
corrida de MEEP es de BANDA ANCHA y entrega H(f) para toda la banda de una
vez, asi que el mismo resultado sirve para cualquier Tprf: cambiar la rampa
no obliga a volver a correr el FDTD. El T_SWEEP sale de
`analisis/correccion_no_linealidad.py`, que sigue siendo el unico lugar donde
vive.

TODAS las longitudes de este archivo estan en METROS. La conversion a
unidades MEEP se hace con `a_meep()` / `a_metros()`.


De donde salen los numeros
--------------------------

Las medidas de la bocina y de la placa son del croquis `GPRv2/medidas.png`
(commit cc84473, "croquis con las medidas de la placa y de la antena"). El
croquis no esta acotado del todo, asi que lo que se interpreto de cada cota
esta anotado abajo, cota por cota, para poder corregirlo sin releer el dibujo.

Los retardos de los cables son los medidos con el VNA (FieldFox N9923A, fase
de S21, 500-2500 MHz), tabla `tab:cables_retardo` de la tesis y seccion "Los
cables, medidos con el VNA" de GPRv2/CLAUDE.md.
"""

import os
import re
import sys
import time

# --- Escala de MEEP -------------------------------------------------------
#
# a = 0.15 m es el largo de onda en aire a 2 GHz. Con eso la banda cae en
# numeros comodos en unidades MEEP (f_meep = f_real * a / c):
#
#     1 GHz -> 0.5      1.5 GHz -> 0.75      2 GHz -> 1.0
#
# Es la misma escala que usaba chirp_v7.py en las simulaciones viejas, asi
# que las geometrias de aquellas se pueden traer sin reescalar.
A_MEEP = 0.15                    # m por unidad MEEP
C0     = 299_792_458.0           # m/s

# --- Banda del radar ------------------------------------------------------
#
# ⚠️ NO es "1 a 2 GHz". La curva medida del VCO (VCO/Caracteristica VCO.csv)
# con la rampa de V_MIN=0 a V_MAX=3,00 V barre de 942,1 a 1981,7 MHz, o sea
# BW = 1039,6 MHz. Eso es lo que hay que cubrir: si H(f) arrancara en 1 GHz,
# los primeros 58 MHz del barrido caerian fuera de la tabla y radar.py
# tendria que extrapolar justo en el borde, que es donde peor se porta.
#
# Se deja margen de ~40 MHz de cada lado. La banda de MEEP es mas ancha que
# la del radar a proposito: sobra barato, y faltar obliga a rehacer el FDTD.
F_MIN = 0.90e9                   # Hz  (VCO arranca en 942,1 MHz)
F_MAX = 2.05e9                   # Hz  (VCO termina en 1981,7 MHz)
N_FREQ = 401                     # puntos de H(f): 2,9 MHz de paso

# --- Bocina ---------------------------------------------------------------
#
# Del croquis, la bocina de abajo. Lectura de cada cota:
#
#     18 cm    ancho de la seccion de guia de onda
#     29.5 cm  largo de la seccion de guia
#     30.5 cm  apertura (el croquis la da cuadrada, 30.5 x 30.5)
#     52.5 cm  largo total, del fondo de la guia al plano de apertura
#     5.9 cm   sonda de alimentacion, medida desde el fondo (corto) de la
#              guia. El croquis dice "dist al conector: 5,9 cm y 5,4 cm",
#              que parecen las dos coordenadas de la sonda dentro de la
#              cara. Se toma 5,9 como la distancia al corto, que es la que
#              importa: a 1,5 GHz un cuarto de onda son 5,0 cm, asi que el
#              numero cierra con una sonda puesta donde corresponde.
#
# ⚠️ A CONFIRMAR con el banco: si alguna de estas lecturas esta mal, el
# unico efecto es sobre la FORMA del diagrama y la adaptacion; la posicion
# del pico en distancia no depende de la bocina.
GUIA_ANCHO   = 0.180             # m
GUIA_LARGO   = 0.295             # m
APERTURA     = 0.305             # m
LARGO_TOTAL  = 0.525             # m
SONDA_FONDO  = 0.059             # m, desde el corto del fondo
PARED        = 0.010             # m, espesor de las paredes metalicas
                                 #    (10 mm = 3,3 celdas a RESOLUCION 20;
                                 #     mas fino que esto no lo resuelve
                                 #     bien la grilla)

# Separacion entre las bocinas, como se mide en el banco: el HUECO entre
# los bordes de las dos bocas. En el banco estan a unos 10 cm (dato del
# usuario, 2026-09-21). La simulacion usa la distancia entre CENTROS, que es
# una apertura mas ese hueco: 30,5 + 10 = 40,5 cm.
#
# (Antes se habia supuesto hueco 0, bocas pegadas, porque CLAUDE.md dice que
# el acoplamiento directo aparece "a 0,15 m" y eso cierra con 30,5 cm entre
# centros. Ese 0,15 m es de antes de los cables y de otro armado.)
SEPARACION_BOCAS = 0.10          # m, de borde a borde de las bocas
SEP_ANTENAS = APERTURA + SEPARACION_BOCAS   # m, entre centros

# La carga de la sonda. En el banco cada sonda esta conectada a 50 ohm: la
# de RX al receptor, la de TX a la salida del VCO/amplificador. Lo que vuelve
# a entrar a una bocina baja por la guia, la sonda se lo entrega a esa carga
# y NO vuelve a salir. MEEP no sabe nada de 50 ohm: con el corto del fondo y
# una sonda que solo mide (RX) o solo inyecta corriente (TX), cada bocina es
# una cavidad metalica cerrada que devuelve TODO lo que le entra. Eso infla
# los rebotes que hacen un segundo viaje a la placa (picos D y E de correr.py).
#
#   "adaptada"  sin corto: la guia sigue derecho detras de la sonda hasta
#               cruzar el PML del borde de la celda, que absorbe el modo
#               guiado sin reflejarlo. Es una transicion PERFECTAMENTE
#               adaptada en toda la banda.
#   "corto"     la bocina del croquis tal cual, con el corto a SONDA_FONDO
#               detras de la sonda y sin ninguna carga. Lo que habia antes
#               del 2026-09-21.
#
# La bocina real esta entre las dos: la sonda a 5,9 cm del corto es un cuarto
# de longitud de onda GUIADA a ~1,5 GHz (el centro de la banda), asi que
# adapta bien ahi y peor hacia los bordes. Las dos son los extremos que
# encierran al banco. Lo que cambia entre una y otra (placa a 1 m, medido el
# 2026-09-21):
#
#                               corto      adaptada
#   rebote adentro D           -4 dB       -30 dB     (respecto del eco B)
#   eco B, sin cables         1,648 m      1,586 m
#   offset de las bocinas     0,658 m      0,588 m    (barrido.py)
#
# O sea: los NIVELES de los rebotes de adentro cambian muchisimo, y el eco
# se corre ~6 cm porque sin corto no esta la parte de la senal que va y
# vuelve al fondo, y el centro de fase de la bocina se adelanta. La captura
# real de la placa va a decir cual de los dos offsets se parece mas.
SONDA = "adaptada"

# --- Blanco: la placa metalica --------------------------------------------
#
# La placa del banco mide ~70 cm de ancho (dato del usuario, 2026-09-21).
# En 2D entra el lado que esta en el plano de la simulacion.
#
# Al principio se habia tomado el rectangulo de arriba del croquis
# (30,4 x 22,4 cm, con cuatro agujeros y "H = 13,5 cm"), pero NO es la placa:
# la placa es mas grande. Ese rectangulo queda sin identificar.
PLACA_ANCHO   = 0.70             # m, el lado que entra en el plano 2D
PLACA_ESPESOR = 0.010            # m
DIST_PLACA    = 1.000            # m, del plano de apertura a la cara de la placa

# --- Retardos que NO estan en el FDTD -------------------------------------
#
# MEEP simula SOLO el aire: de la sonda de la bocina TX a la sonda de la RX.
# Todo lo que esta antes y despues (cables, splitter, mezclador, LNA) es un
# retardo que se suma al camino de RF y que el mezclador no puede distinguir
# del retardo del blanco. Ver el capitulo `ch:cables` de la tesis.
#
# Juego NUEVO, el que esta en el banco: dos RG-213 de 1 m.
#   tau_TX + tau_RX = 4,983 + 4,975 = 9,958 ns   (pendiente de fase de S21)
#   camino del LO   = 5 cm de union directa      = 0,25 ns, y RESTA
#   ------------------------------------------------------------------
#   tau_cables neto = 9,708 ns  ->  d_offset = c*tau/2 = 1,456 m
TAU_TX      = 4.983e-9           # s, RG-213 A de 1 m
TAU_RX      = 4.975e-9           # s, RG-213 B de 1 m
TAU_LO      = 0.25e-9            # s, los 5 cm de splitter a mezclador

# Retardo interno del radar: splitter, mezclador, LNA, conectores y las
# bocinas mismas. NO ESTA MEDIDO en ningun lado del proyecto - ni en la
# tesis ni en CLAUDE.md, que solo cuantifican los 5 cm del LO.
#
# Queda en 0 a proposito. Cuando haya una captura real de la placa a 1 m, la
# diferencia entre el `b` de la calibracion de `vivo_rapido.py` y el offset
# de cables de aca ES el retardo interno, medido sin suponer nada - el mismo
# argumento con el que la tesis midio los cables. El paper de referencia es
# `GPRv2/docs/refs/park2018_leakage_internal_delay.pdf`.
TAU_INTERNO = 0.0                # s

# Los .s2p del VNA, para usar el S21 MEDIDO del cable (modulo y fase) en vez
# de un retardo ideal. Ver MODO_CABLE en radar.py.
AQUI    = os.path.dirname(os.path.abspath(__file__))
S2P_TX  = os.path.join(AQUI, "..", "docs", "CABLES", "RG213_A_1m.s2p")
S2P_RX  = os.path.join(AQUI, "..", "docs", "CABLES", "RG213_B_1m.s2p")
VCO_CSV = os.path.join(AQUI, "..", "..", "VCO", "Caracteristica VCO.csv")
SALIDAS_RAIZ = os.path.join(AQUI, "salidas")   # cada corrida, en su carpeta:
                                               # ver SALIDAS mas abajo

# --- Malla y corrida ------------------------------------------------------
#
# RESOLUCION 20 -> celda de a/20 = 7,5 mm. A 2 GHz (lambda = 15 cm) son 20
# celdas por longitud de onda, y a 1 GHz, 40. Es el minimo razonable; subir
# a 30 cuesta el cuadrado en celdas y el doble en pasos de tiempo.
RESOLUCION = 20
DPML       = 1.0                 # u.MEEP
MARGEN     = 1.0                 # u.MEEP de aire entre la escena y el PML

# Cuanto tiempo se deja correr, en unidades MEEP (1 u = a/c = 0,5 ns).
# El ida y vuelta a la placa a 1 m son 2*1/0,15 = 13,3 u; el pulso gaussiano
# dura ~20 u; y hay rebotes placa<->bocina que suman otros 13,3 cada uno.
# 200 u = 100 ns deja lugar para tres rebotes completos.
T_CORRIDA = 200.0

# --- Que se simula ---------------------------------------------------------
MODO_CABLE = "medido"            # medido | ideal | ninguno (ver radar.py)
BARRIDO    = [0.75, 1.00, 1.25, 1.50]   # m, distancias de `escena.py barrido`

# Tprf del generador. 0 = el de `analisis/correccion_no_linealidad.py`
# (2*T_SWEEP), que es donde vive; esto es solo para probar otro desde el
# .bat. No toca el FDTD: lo usa radar.py al sintetizar el batido.
TPRF = 0.0                       # s

# Valores de referencia, antes de que los pise el .bat: el nombre automatico
# de la carpeta solo menciona lo que se aparte de estos.
_REF_CABLE, _REF_RESOLUCION, _REF_SONDA = MODO_CABLE, RESOLUCION, SONDA


# --- Lo que pisa GPRv2/simular.bat ------------------------------------------
#
# El .bat NO edita este archivo: exporta variables de entorno GPR_SIM_* y
# aca se leen. Asi los valores de arriba siguen siendo los de referencia
# (los del croquis y del VNA) y el .bat es solo "lo que quiero probar hoy".
# Llegan a WSL porque el .bat los agrega a WSLENV.
#
# Se acepta coma decimal ("1,25"), que es lo que sale natural al tipear.

def _env(nombre, defecto, tipo=float):
    v = os.environ.get("GPR_SIM_" + nombre, "").strip()
    if not v:
        return defecto
    try:
        return tipo(v.replace(",", ".")) if tipo is float else tipo(v)
    except ValueError:
        raise SystemExit(f"GPR_SIM_{nombre}={v!r} no es un numero valido")


DIST_PLACA   = _env("DIST_PLACA", DIST_PLACA)
SEPARACION_BOCAS = _env("SEPARACION_BOCAS", SEPARACION_BOCAS)
SEP_ANTENAS  = APERTURA + SEPARACION_BOCAS
PLACA_ANCHO  = _env("PLACA_ANCHO", PLACA_ANCHO)
TAU_INTERNO  = _env("TAU_INTERNO_NS", TAU_INTERNO * 1e9) * 1e-9
RESOLUCION   = int(_env("RESOLUCION", RESOLUCION))
MODO_CABLE   = _env("CABLE", MODO_CABLE, str).lower()
if MODO_CABLE not in ("medido", "ideal", "ninguno"):
    raise SystemExit(f"CABLE={MODO_CABLE!r}: tiene que ser medido, ideal o ninguno")
SONDA        = _env("SONDA", SONDA, str).lower()
if SONDA not in ("adaptada", "corto"):
    raise SystemExit(f"SONDA={SONDA!r}: tiene que ser adaptada o corto")
_b = os.environ.get("GPR_SIM_BARRIDO", "").split()
if _b:
    BARRIDO = [float(x.replace(",", ".")) for x in _b]
TPRF         = _env("TPRF_MS", TPRF * 1e3) * 1e-3
QUE          = _env("QUE", "todo", str).lower()


# --- Donde queda cada corrida -----------------------------------------------
#
# Todo lo de una corrida va a su propia carpeta, salidas/<NOMBRE>/: los H(f)
# de MEEP, las figuras y los resumen_*.txt con los parametros usados. Dos
# corridas con parametros distintos no se pisan, y la misma corrida repetida
# si (es el mismo resultado).
#
# NOMBRE lo pone simular.bat. Vacio, sale de nombre_auto(). Los dos lados
# (WSL y Windows) lo calculan con las mismas variables GPR_SIM_*, pero el
# .bat igual les pasa el ya resuelto, asi no dependen de coincidir.

def nombre_auto():
    """Nombre de carpeta con lo que distingue a la corrida.

    Siempre la geometria (distancia de la placa o del barrido, hueco entre
    las bocas, ancho de la placa). El resto solo si se aparta de la
    referencia, para que el caso de siempre tenga un nombre corto:

        placa1.00m_hueco10cm_ancho70cm
        barrido0.75-1.50m_hueco10cm_ancho70cm_cable-ideal_tau1.5ns
    """
    def cm(m):
        return f"{m * 100:g}cm"
    if QUE == "barrido":
        p = [f"barrido{min(BARRIDO):.2f}-{max(BARRIDO):.2f}m"]
    else:
        p = [f"placa{DIST_PLACA:.2f}m"]
    p += [f"hueco{cm(SEPARACION_BOCAS)}", f"ancho{cm(PLACA_ANCHO)}"]
    if SONDA != _REF_SONDA:
        p.append(f"sonda-{SONDA}")
    if MODO_CABLE != _REF_CABLE:
        p.append(f"cable-{MODO_CABLE}")
    if TAU_INTERNO:
        p.append(f"tau{TAU_INTERNO * 1e9:g}ns")
    if RESOLUCION != _REF_RESOLUCION:
        p.append(f"res{RESOLUCION}")
    if TPRF:
        p.append(f"tprf{TPRF * 1e3:g}ms")
    return "_".join(p)


def _limpiar(nombre):
    """Lo que Windows no acepta en un nombre de carpeta, y espacios, a '_'."""
    return re.sub(r'[<>:"/\\|?*\s]+', "_", nombre).strip("._ ")


NOMBRE  = _limpiar(os.environ.get("GPR_SIM_NOMBRE", "")) or nombre_auto()
SALIDAS = os.path.join(SALIDAS_RAIZ, NOMBRE)


def a_meep(metros):
    """Metros -> unidades MEEP."""
    return metros / A_MEEP


def a_metros(u):
    """Unidades MEEP -> metros."""
    return u * A_MEEP


def f_meep(hz):
    """Hz -> frecuencia en unidades MEEP (f*a/c)."""
    return hz * A_MEEP / C0


def tau_cables():
    """Retardo neto del cableado [s]: RF menos LO. Ver el capitulo de cables."""
    return TAU_TX + TAU_RX - TAU_LO


def tau_extra():
    """Todo el retardo que no simula MEEP: cables + interno [s]."""
    return tau_cables() + TAU_INTERNO


def d_offset():
    """Distancia aparente [m] que agrega tau_extra(): c*tau/2."""
    return C0 * tau_extra() / 2.0


def resumen():
    """Los parametros de la corrida, como lineas de texto.

    Lo imprime simular.bat al arrancar y encabeza cada resumen_*.txt, asi
    los numeros de una carpeta siempre dicen con que se sacaron.
    """
    tprf = f"{TPRF*1e3:g} ms" if TPRF else "el de analisis/ (2*T_SWEEP)"
    return [
        f"corrida         {NOMBRE}   ({time.strftime('%Y-%m-%d %H:%M')})",
        f"carpeta         {os.path.relpath(SALIDAS, os.path.join(AQUI, '..'))}",
        f"que             {QUE}   (barrido: "
        f"{' '.join(f'{d:.2f}' for d in BARRIDO)} m)",
        f"escala          a = {A_MEEP} m/u.MEEP",
        f"banda           {F_MIN/1e9:.2f} a {F_MAX/1e9:.2f} GHz "
        f"= {f_meep(F_MIN):.3f} a {f_meep(F_MAX):.3f} u.MEEP",
        f"resolucion      {RESOLUCION} celdas/u = {A_MEEP/RESOLUCION*1e3:.1f} mm",
        f"bocina          apertura {APERTURA*100:.1f} cm, largo "
        f"{LARGO_TOTAL*100:.1f} cm, bocas a {SEPARACION_BOCAS*100:.1f} cm "
        f"(centros a {SEP_ANTENAS*100:.1f} cm)",
        f"sonda           {SONDA}   "
        + ("(guia sin corto, al PML = carga de 50 ohm)" if SONDA == "adaptada"
           else "(con el corto, sin carga: cavidad cerrada)"),
        f"placa           {PLACA_ANCHO*100:.1f} cm a {DIST_PLACA*100:.0f} cm",
        f"cables          {MODO_CABLE}, tau {tau_cables()*1e9:.3f} ns",
        f"tau interno     {TAU_INTERNO*1e9:.3f} ns",
        f"Tprf            {tprf}",
        f"d_offset        {d_offset():.3f} m",
        f"placa + offset  {DIST_PLACA + d_offset():.3f} m aparentes",
        f"acopl. directo  {SEP_ANTENAS/2 + d_offset():.3f} m aparentes",
    ]


if __name__ == "__main__":
    # --nombre: solo el nombre de la carpeta, para que simular.bat lo lea.
    if "--nombre" in sys.argv:
        print(NOMBRE)
    else:
        print("\n".join(resumen()))
