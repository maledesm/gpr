"""
GPRv2 - Parametros compartidos de las simulaciones MEEP (copia para ARMONICOS)
==============================================================================

COPIA de `simulaciones_meep/parametros.py` (version del 2026-10-01, la del
relevamiento con la pared), hecha el 2026-11-02 para simular los armonicos
del VCO. El original NO se toca: queda como historial de como se venia
simulando. Lo que cambia respecto de el:

  - BANDA: 0,90 a 6,25 GHz en vez de 0,90 a 2,05. Hace falta H(f) en f, 2f y
    3f a lo largo de todo el barrido (942 a 1991 MHz -> hasta 5,97 GHz).
  - RESOLUCION 50 (3 mm) en vez de 20: a 6,2 GHz la longitud de onda es
    4,8 cm, y con 7,5 mm de celda serian 6 celdas por lambda (dispersion
    numerica grosera). Con 3 mm son 16.
  - BARRIDO por defecto = las distancias medidas el 2026-09-28.
  - Rutas: este archivo vive un nivel mas abajo, y las salidas van a
    `armonicos/salidas/`.
  - Al final, los parametros del modelo del radar que no estan en el
    original (armonicos, mezclador, triangular, cadena de IF). Solo los usa
    el lado de Windows.

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

Las medidas de la bocina y de la placa son del croquis `GPRv2/mediciones/mediciones_antena.png`
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
#
# Para los armonicos la banda llega al 3o del tope del barrido: 3 x 1991 MHz
# (lo mas alto que se vio en el Max Hold) = 5,97 GHz, con margen hasta 6,25.
# La sintesis NO interpola esta tabla: calcula H a la frecuencia exacta de
# cada muestra con la DFT de la traza guardada (ver radar.H_en). La tabla
# queda para las figuras.
F_MIN = 0.90e9                   # Hz  (VCO arranca en 942,1 MHz)
F_MAX = 6.25e9                   # Hz  (3er armonico de 1991 MHz = 5,97 GHz)
N_FREQ = 2141                    # puntos de H(f): 2,5 MHz de paso

# --- Bocina ---------------------------------------------------------------
#
# Del croquis `GPRv2/mediciones/mediciones_antena.png`, con la lectura que confirmo el usuario el
# 2026-09-22. TODO se midio POR FUERA, y la bocina es de CHAPA fina:
#
#     18 cm    ancho de la guia de onda (el lado que entra en el plano 2D;
#              el otro lado, 9 cm, queda fuera del plano)
#     30,5 cm  boca, cuadrada de 30,5 x 30,5
#     52,5 cm  largo total, del fondo a la boca
#     33,5 cm  tramo RECTO de la guia, del fondo hasta donde se abre. El
#              flare es lo que queda: 52,5 - 33,5 = 19 cm
#     5,9 y 5,4 cm   a cuanto estan los conectores (las sondas) del fondo,
#              uno en cada bocina. No se sabe cual es cual: se toma 5,9 para
#              TX y 5,4 para RX. Medio cm de diferencia son 2,5 mm de
#              distancia aparente, muy abajo de la resolucion.
#
# Lo que NO se usa del croquis: el rectangulo de arriba (30,4 x 22,4 con
# cuatro agujeros, H = 13,5 cm) es la caja del radar; el "29,5 cm" es del
# fondo al conector del soporte de PVC, y el "3,5 cm" es el radio de ese
# soporte.
#
# Como se lleva a la simulacion: MEEP no resuelve una chapa de 1 mm con
# celdas de 7,5 mm, asi que las paredes se simulan de PARED = 1 cm, pero se
# ponen HACIA AFUERA de la superficie interior, que es la que ve la onda. La
# superficie interior es la medida exterior menos CHAPA:
#
#     guia por dentro   = 18   - 2*0,1 = 17,8 cm   (corte del modo: 842 MHz)
#     boca por dentro   = 30,5 - 2*0,1 = 30,3 cm
#     largo por dentro  = 52,5 - 0,1   = 52,4 cm   (del fondo a la boca)
#
# Antes del 2026-09-22 las paredes de 1 cm iban CENTRADAS en la cota, y la
# guia quedaba de 17 cm por dentro (corte en 882 MHz, muy cerca de los
# 942 MHz donde arranca el VCO). Y el tramo recto era de 29,5 cm (el soporte
# de PVC, mal leido): flare de 23 cm en vez de 19.

# Medidas tal como se toman en el banco: POR FUERA, en metros.
GUIA_ANCHO_EXT = 0.180           # m
APERTURA_EXT   = 0.305           # m, la boca (cuadrada)
LARGO_EXT      = 0.525           # m, del fondo a la boca
GUIA_LARGO_EXT = 0.335           # m, tramo recto, del fondo a donde abre
CONECTOR_TX    = 0.059           # m, conector de la bocina TX al fondo
CONECTOR_RX    = 0.054           # m, conector de la bocina RX al fondo
CHAPA          = 0.001           # m, espesor real de la chapa (a confirmar)
PARED          = 0.010           # m, espesor de las paredes EN LA SIMULACION
                                 #    (1,3 celdas a RESOLUCION 20; mas fino
                                 #     que esto la grilla lo pierde)

# Separacion entre las bocinas, como se mide en el banco: el HUECO entre
# los bordes de las dos bocas. En el banco estan a unos 10 cm (dato del
# usuario, 2026-09-21), medido por fuera. La simulacion usa la distancia
# entre CENTROS, que es una boca (por fuera) mas ese hueco: 30,5 + 10 =
# 40,5 cm. Se calcula mas abajo, despues de lo que pisa el .bat.
#
# (Antes se habia supuesto hueco 0, bocas pegadas, porque CLAUDE.md dice que
# el acoplamiento directo aparece "a 0,15 m" y eso cierra con 30,5 cm entre
# centros. Ese 0,15 m es de antes de los cables y de otro armado.)
SEPARACION_BOCAS = 0.10          # m, de borde a borde de las bocas

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
#   "corto"     la bocina del croquis tal cual, con el corto a SONDA_TX/RX
#               detras de la sonda y sin ninguna carga. Lo que habia antes
#               del 2026-09-21.
#
# La bocina real esta entre las dos: la sonda a 5,9 cm del corto es un cuarto
# de longitud de onda GUIADA a ~1,5 GHz (el centro de la banda), asi que
# adapta bien ahi y peor hacia los bordes. Las dos son los extremos que
# encierran al banco. Lo que cambia entre una y otra (placa a 1 m, medido el
# 2026-09-22):
#
#                               corto      adaptada
#   rebote adentro D           -4 dB       -30 dB     (respecto del eco B)
#   eco B, sin cables         1,662 m      1,593 m
#   offset de las bocinas     0,660 m      0,595 m    (barrido.py)
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

# --- La pared del laboratorio ---------------------------------------------
#
# Medido el 2026-09-28: de la boca de las antenas a la pared hay ~126 cm. La
# pared NO es un detalle: esta siempre en el espectro, es el blanco mas
# lejano que entra, y acota hasta donde se puede correr la placa. Simularla
# es lo que hace que el espectro simulado se parezca al de la pantalla.
#
# Se modela como un bloque dielectrico sin perdidas que arranca en MURO_DIST
# y sigue hasta adentro del PML: asi refleja en su cara de adelante y lo que
# entra no vuelve, que es lo que hace una pared gruesa de verdad. Sin
# perdidas es el caso PEOR (el eco mas fuerte que puede dar).
#
# eps 5 es hormigon/ladrillo tipico (4 a 6, mampostería seca). Con eps 5 el
# coeficiente de reflexion en incidencia normal es (1-sqrt(5))/(1+sqrt(5))
# = -0,38, o sea -8,4 dB respecto de la placa metalica.
MURO_DIST = 1.26                 # m, de la boca de las antenas. 0 = sin pared
MURO_EPS  = 5.0                  # permitividad relativa

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

# Retardo interno del radar: splitter, mezclador, LNA, conectores y todo
# latiguillo o adaptador que haya entre ellos y los cables. No esta medido
# directo.
#
# 4 ns AJUSTADOS contra la captura del banco (2026-09-22,
# datos/capturas/captura_1m_cf.png: cables RG-213 de 1 m, placa a 1 m). La
# simulacion sin retardo interno pone el eco en 423 Hz y la captura lo da en
# ~505 Hz: 82 Hz / 138,6 Hz/m = 0,59 m aparentes = 3,95 ns. Con SONDA =
# "corto" darian 3,5 ns, asi que el valor arrastra la incertidumbre del
# modelo de la bocina.
#
# Son ~80 cm de coaxil equivalentes: mas de lo que explican splitter,
# mezclador y LNA solos. Para medirlo sin depender de la bocina: unir los
# cables de TX y RX con un barrel y un atenuador, sin antenas; el batido que
# queda es cables + retardo interno. Referencia:
# `GPRv2/docs/refs/park2018_leakage_internal_delay.pdf`.
TAU_INTERNO = 4.0e-9             # s

# Los .s2p del VNA, para usar el S21 MEDIDO del cable (modulo y fase) en vez
# de un retardo ideal. Ver MODO_CABLE en radar.py.
AQUI    = os.path.dirname(os.path.abspath(__file__))
GPRV2   = os.path.join(AQUI, "..", "..")
S2P_TX  = os.path.join(GPRV2, "docs", "CABLES", "RG213_A_1m.s2p")
S2P_RX  = os.path.join(GPRV2, "docs", "CABLES", "RG213_B_1m.s2p")
VCO_CSV = os.path.join(GPRV2, "..", "VCO", "Caracteristica VCO.csv")
SALIDAS_RAIZ = os.path.join(AQUI, "salidas")   # cada corrida, en su carpeta:
                                               # ver SALIDAS mas abajo

# --- Malla y corrida ------------------------------------------------------
#
# RESOLUCION 20 -> celda de a/20 = 7,5 mm. A 2 GHz (lambda = 15 cm) son 20
# celdas por longitud de onda, y a 1 GHz, 40. Es el minimo razonable; subir
# a 30 cuesta el cuadrado en celdas y el doble en pasos de tiempo.
#
# Para los armonicos: 50 -> 3 mm, 16 celdas por lambda a 6,2 GHz. El error de
# velocidad de fase del FDTD va con (k*dx)^2/24: 0,6 % a 6,2 GHz, 0,3 % a
# 4 GHz. Sobre ~2 m aparentes de aire eso corre el fantasma del 3o unos 4 Hz,
# un quinto de bin. Cuesta (50/20)^3 = 16 veces la corrida de 20.
RESOLUCION = 50
DPML       = 1.0                 # u.MEEP
MARGEN     = 1.0                 # u.MEEP de aire entre la escena y el PML

# Cuanto tiempo se deja correr, en unidades MEEP (1 u = a/c = 0,5 ns).
# El ida y vuelta a la placa a 1 m son 2*1/0,15 = 13,3 u; el pulso gaussiano
# dura ~20 u; y hay rebotes placa<->bocina que suman otros 13,3 cada uno.
# 200 u = 100 ns deja lugar para tres rebotes completos.
T_CORRIDA = 200.0
# Para los armonicos (radar.H_en): la traza se baja con un coseno desde aca
# hasta el final, para que el corte a los 100 ns no meta un eco falso. Lo
# que pierde son caminos de mas de 70 ns en el aire (> 10 m aparentes).
TAPER_DESDE_NS = 70.0

# --- Que se simula ---------------------------------------------------------
MODO_CABLE = "medido"            # medido | ideal | ninguno (ver radar.py)
BARRIDO    = [0.70, 0.80, 0.90, 1.00, 1.20]   # m, las medidas el 2026-09-28

# Tprf del generador. 0 = el de `analisis/correccion_no_linealidad.py`
# (2*T_SWEEP), que es donde vive; esto es solo para probar otro desde el
# .bat. No toca el FDTD: lo usa radar.py al sintetizar el batido.
TPRF = 0.0                       # s

# Valores de referencia, antes de que los pise el .bat: el nombre automatico
# de la carpeta solo menciona lo que se aparte de estos.
_REF_CABLE, _REF_RESOLUCION, _REF_SONDA = MODO_CABLE, RESOLUCION, SONDA
_REF_TAU_INTERNO = TAU_INTERNO
_BOCINA = {                      # nombre en el .bat -> (variable, rotulo)
    "GUIA_ANCHO": ("GUIA_ANCHO_EXT", "guia"),
    "BOCA": ("APERTURA_EXT", "boca"),
    "LARGO": ("LARGO_EXT", "largo"),
    "GUIA_LARGO": ("GUIA_LARGO_EXT", "recta"),
    "CONECTOR_TX": ("CONECTOR_TX", "ctx"),
    "CONECTOR_RX": ("CONECTOR_RX", "crx"),
    "CHAPA": ("CHAPA", "chapa"),
}
_REF_BOCINA = {k: globals()[v] for k, (v, _) in _BOCINA.items()}


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
MURO_DIST    = _env("MURO_DIST", MURO_DIST)
MURO_EPS     = _env("MURO_EPS", MURO_EPS)
SEPARACION_BOCAS = _env("SEPARACION_BOCAS", SEPARACION_BOCAS)

# Las medidas de la bocina llegan del .bat EN CENTIMETROS, como el croquis.
for _k, (_v, _) in _BOCINA.items():
    globals()[_v] = _env("BOC_" + _k, globals()[_v] * 100) / 100

# Lo que ve la onda: la superficie INTERIOR (ver el bloque de la bocina).
GUIA_ANCHO  = GUIA_ANCHO_EXT - 2 * CHAPA     # m, por dentro
APERTURA    = APERTURA_EXT - 2 * CHAPA       # m, por dentro
LARGO_TOTAL = LARGO_EXT - CHAPA              # m, fondo (por dentro) -> boca
GUIA_LARGO  = GUIA_LARGO_EXT - CHAPA         # m, fondo (por dentro) -> flare
SONDA_TX    = CONECTOR_TX - CHAPA            # m, sonda TX desde el fondo
SONDA_RX    = CONECTOR_RX - CHAPA            # m, sonda RX desde el fondo
FLARE       = LARGO_TOTAL - GUIA_LARGO       # m, largo del flare
if not (0 < max(SONDA_TX, SONDA_RX) < GUIA_LARGO < LARGO_TOTAL):
    raise SystemExit(
        f"medidas de la bocina imposibles: conectores a {CONECTOR_TX*100:g} y "
        f"{CONECTOR_RX*100:g} cm, guia de {GUIA_LARGO_EXT*100:g} cm, largo "
        f"total {LARGO_EXT*100:g} cm (tiene que ser conector < guia < largo)")
if APERTURA < GUIA_ANCHO:
    raise SystemExit("la boca no puede ser mas angosta que la guia")
SEP_ANTENAS  = APERTURA_EXT + SEPARACION_BOCAS   # m, entre centros
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
    for k, (v, rot) in _BOCINA.items():
        if abs(globals()[v] - _REF_BOCINA[k]) > 1e-9:
            p.append(f"{rot}{cm(globals()[v])}")
    if SONDA != _REF_SONDA:
        p.append(f"sonda-{SONDA}")
    if MODO_CABLE != _REF_CABLE:
        p.append(f"cable-{MODO_CABLE}")
    if abs(TAU_INTERNO - _REF_TAU_INTERNO) > 1e-15:
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


def d_bocina():
    """Distancia aparente [m] que agregan las bocinas por su largo fisico.

    El eco hace sonda TX -> boca y boca -> sonda RX; la distancia aparente
    es la mitad del camino, o sea el promedio de los dos tramos.
    """
    return LARGO_TOTAL - (SONDA_TX + SONDA_RX) / 2.0


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
        f"bocina (fuera)  guia {GUIA_ANCHO_EXT*100:g} cm, boca "
        f"{APERTURA_EXT*100:g} cm, largo {LARGO_EXT*100:g} cm (recta "
        f"{GUIA_LARGO_EXT*100:g} + flare {FLARE*100:.1f}), conectores a "
        f"{CONECTOR_TX*100:g} (TX) y {CONECTOR_RX*100:g} (RX) cm del fondo",
        f"bocina (dentro) guia {GUIA_ANCHO*100:.1f} cm (corte "
        f"{C0/(2*GUIA_ANCHO)/1e6:.0f} MHz), boca {APERTURA*100:.1f} cm, "
        f"chapa {CHAPA*1000:g} mm",
        f"bocas           hueco {SEPARACION_BOCAS*100:.1f} cm "
        f"(centros a {SEP_ANTENAS*100:.1f} cm)",
        f"sonda           {SONDA}   "
        + ("(guia sin corto, al PML = carga de 50 ohm)" if SONDA == "adaptada"
           else "(con el corto, sin carga: cavidad cerrada)"),
        f"placa           {PLACA_ANCHO*100:.1f} cm a {DIST_PLACA*100:.0f} cm",
        (f"pared           a {MURO_DIST*100:.0f} cm, eps {MURO_EPS:.1f}"
         if MURO_DIST > 0 else "pared           sin pared"),
        f"cables          {MODO_CABLE}, tau {tau_cables()*1e9:.3f} ns",
        f"tau interno     {TAU_INTERNO*1e9:.3f} ns",
        f"Tprf            {tprf}",
        f"d_offset        {d_offset():.3f} m",
        f"placa + offset  {DIST_PLACA + d_offset():.3f} m aparentes",
        f"acopl. directo  {SEP_ANTENAS/2 + d_offset():.3f} m aparentes",
    ]


# =============================================================================
# MODELO DEL RADAR PARA LOS ARMONICOS (solo lo usa el lado de Windows)
# =============================================================================
#
# Lo decidio Martin el 2026-11-02 (las 19 preguntas del chat de armonicos). Lo
# que no esta medido dice SUPUESTO o HIPOTESIS.

# --- VCO -----------------------------------------------------------------
# La curva que barre el VCO "de verdad" en la simulacion, y la curva con la
# que corrige el software (la de vivo_rapido, que es la vieja). Son
# practicamente iguales (respuesta 6): el paso de la cascada que las separa
# deberia dar casi nada.
VCO_CSV_VERDAD = os.path.join(GPRV2, "..", "VCO", "Caracteristica VCO 2026-10-19.csv")
VCO_CSV_CORR = VCO_CSV

# Max Hold de la salida del VCO (antes del PA): de ahi salen la envolvente de
# la fundamental y el nivel del 2o armonico contra f.
MAXHOLD_DIR = os.path.join(GPRV2, "docs", "PWM", "mediciones", "2026-11-02_vco_maxhold")
# El span llegaba a 3 GHz: el 2o se lee solo para f <= 1500 MHz. Arriba se
# extrapola CONSTANTE con el promedio de 1400-1500 MHz (SUPUESTO). Debajo de
# 1005 MHz su 2f cae encima de la fundamental del tope y no se puede leer: se
# usa el de 1005.
A2_F_DESDE = 1005e6
A2_F_HASTA = 1500e6
A2_F_PROM = 1400e6               # promedio de A2_F_PROM a A2_F_HASTA
# 3er armonico: NO medido. Se barre (SUPUESTO). None = sin 3o.
A3_DBC = [None, -15.0, -25.0]
A3_DBC_CASCADA = -15.0           # el que entra en la cascada: el peor de los dos

# --- Mezclador -----------------------------------------------------------
# "multiplicador" (la base): IF = LO*RF. El fantasma n va con a_n^2 y no
# depende de fases. "conmutado" (sensibilidad): diodos con el LO fuerte, la
# IF es RF*sign(LO); depende de la fase PSI entre la fundamental y el 2o en
# el LO, que no se midio.
PSI_GRADOS = [0.0, 45.0, 90.0]

# --- La cadena de RF a 2f y 3f ---------------------------------------------
# SUPUESTO "cadena plana" (respuesta 8): el PA, el splitter ZAPD-2-272-S+, el
# LNA de CATV y el mezclador tratan a 2f y 3f igual que a f. Ademas, para que
# el FDTD 2D no meta su propia pendiente con la frecuencia (una sonda puntual
# en 2D no acopla igual a 2 GHz que a 5), H a n*f se reescala para que el eco
# de la placa a D_NORMALIZA tenga a n*f el mismo nivel medio que a f. De MEEP
# queda la estructura de caminos: donde cae cada eco y cuanto vale contra los
# demas. Los cables si entran con su perdida real a n*f.
D_NORMALIZA = 1.00

# --- Las triangulares ------------------------------------------------------
# A, "sesion 28-09" (respuesta 1): el SDG830, triangular ideal de 0 a 3 V.
# Tprf = el que midio vivo_rapido esa tarde (cabecera de las capturas).
TPRF_SDG = 99.9979e-3
V_SDG = (0.0, 3.00)
# B, "generador propio" (respuesta 3): la LM324 medida con el osciloscopio,
# tanda 2, pote en ~100 ms. Rango, periodo, ciclo util y el residuo promedio
# contra una recta de cada rampa salen del json de analizar_mediciones.py.
TRI_JSON = os.path.join(GPRV2, "docs", "PWM", "mediciones", "2026-11-02_tanda2",
                        "mediciones_triangular.json")
TRI_CAPTURA = "SDS00001.CSV"
RESIDUO_SUAVE = 11               # puntos (de 200 por rampa) de la media movil
                                 # sobre el residuo medido: ver sintesis.py
# La misma triangular segun LTspice (triangular3_LM324 con los paralelos que
# estan armados, 680k y 2x680k, y el pote en 0,318 para 100,97 ms): un
# periodo, como cota de la forma. Como se saco esta en la cabecera del csv.
# Se usa con el periodo y los extremos medidos; aporta la forma y la simetria
# (LTspice da 46,5 % de subida; el osciloscopio, 50,75 %).
TRI_LTSPICE = os.path.join(AQUI, "triangular_lm324_ltspice_100ms.csv")
# La banda que se vio en el Max Hold con la LM324 (respuesta 4). HIPOTESIS:
# un corrimiento de tension que lleva el minimo de la triangular a 988 MHz y
# un recorte en 1991 MHz (saturacion del amplificador x4,95). A confirmar
# midiendo la salida del amplificador.
F_PISO_B = 988e6
F_TOPE_B = 1991e6
# El software no esta actualizado para la LM324 (respuesta 5): se procesa
# "hoy" (0-3 V, como esta el codigo) y "actualizado" (los extremos medidos
# con el osciloscopio, rampa lineal).
V_SOFT_HOY = (0.0, 3.00)

# --- Cadena de IF y adquisicion --------------------------------------------
FS_ADC = 48000.0
DEC = 8
FS = FS_ADC / DEC
# Filtro post-mezclador, posicion G=1 (respuesta 14). Solo modulo medido.
FILTRO_IF_CSV = os.path.join(GPRV2, "..", "Filtro Pasabajos", "respuesta_filtro_procesado.csv")
PCM_HPF_HZ = 0.019 * FS_ADC / 1000   # pasaaltos digital del PCM1808 (0,91 Hz)
ACOPLE_HPF_HZ = 0.27                 # capacitor de acople: 10 uF contra 60 kohm
PCM_RETARDO = 17.4 / FS_ADC          # retardo de grupo del filtro del PCM1808
                                     # (hoja de datos, a confirmar)
BLOQUE_DMA = 256                     # tramas por bloque = una lectura de la triangular
RETARDO_FIRMWARE = 13                # muestras de salida que compensa el firmware
ADC_TRI_FONDO = 3.3                  # V de fondo del ADC del C3 (solo cuantiza)

# --- Lo que hace vivo_rapido -----------------------------------------------
RELLENO_FFT = 8
RAMPAS_EN_FILA = 8                   # el promedio que se guardo en las capturas
DURACION_S = 4.0                     # cuanto se sintetiza (asientan los pasaaltos)
DESCARTE_S = 1.5                     # lo que se tira del principio

# --- Ruido (solo la ultima corrida, respuesta 15) ----------------------------
# Blanco, con el nivel que da el piso medido entre RUIDO_BANDA (lejos de los
# picos y de los fantasmas, y debajo de la transicion del diezmado).
RUIDO_BANDA = (1800.0, 2300.0)

# --- Fuga interna (variante, respuesta 10) ----------------------------------
# Un camino que va del TX al RX sin pasar por las bocinas (aislacion del
# splitter y del mezclador, cables juntos). Un retardo y un nivel, AJUSTADOS
# contra las capturas cf: no es una medicion.
FUGA_D_AP = (2.2, 3.6)               # m aparentes donde se busca
FUGA_NIVEL_DB = (-30.0, 20.0)        # dB contra el eco de la placa a 1 m


if __name__ == "__main__":
    # --nombre: solo el nombre de la carpeta, para que simular.bat lo lea.
    if "--nombre" in sys.argv:
        print(NOMBRE)
    else:
        print("\n".join(resumen()))
