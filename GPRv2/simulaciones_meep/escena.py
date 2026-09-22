"""
GPRv2 - Escena FDTD: dos bocinas mirando a una placa metalica
==============================================================

Corre en WSL, en el env conda `meep`:

    wsl -d Ubuntu -- bash -lc 'source ~/miniconda3/etc/profile.d/conda.sh \\
        && conda activate meep \\
        && cd /mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep \\
        && python escena.py'

(o directamente `correr_meep.sh`, que hace eso mismo).


Por que banda ancha y no un chirp
---------------------------------

Las simulaciones viejas (`~/meep/Simulaciones/Simulaciones chirp/chirp_v7.py`)
metian el chirp como fuente de MEEP y despues mezclaban en software. Eso
obliga a que el barrido dure MUCHO mas que el retardo que se quiere medir, y
en este banco no da: el ida y vuelta a la placa mas los cables son ~16 ns, y
el chirp de chirp_v7 duraba 40 u.MEEP = 20 ns. El retardo era el 80 % del
barrido y la aproximacion de batido se rompe.

Aca se hace al reves. La escena es lineal e invariante en el tiempo (un radar
FMCW sobre un blanco quieto, como dice el capitulo de arquitectura de la
tesis: sin Doppler), asi que queda completamente descripta por su funcion de
transferencia H(f) entre la sonda de la bocina TX y la de la RX. Se la mide
con UN pulso de banda ancha y despues `radar.py` sintetiza el batido para el
Tprf que sea. Ventajas:

  - El resultado no depende del barrido: cambiar de 100 ms a otra cosa NO
    obliga a volver a correr el FDTD.
  - Se puede usar el Tprf REAL de 100 ms, con sus 300 muestras por rampa y
    la no linealidad real del VCO, cosa que con un chirp de MEEP es
    imposible por varios ordenes de magnitud.
  - Es 100 veces mas barato: una corrida de 8000 pasos en vez de una por
    cada configuracion.

La aproximacion que se usa al sintetizar (cuasi-estatica, "stretch") esta
documentada en radar.py, y es MUCHISIMO mejor aca que en un chirp de MEEP:
el error va con alpha*tau^2, y con la rampa real de 50 ms eso es ~5e-9.


Que se guarda
-------------

Un .npz por escena en la carpeta de la corrida (`salidas/<NOMBRE>/`,
ver parametros.py), con:

    f_hz     frecuencias [Hz], N_FREQ puntos entre F_MIN y F_MAX
    H        funcion de transferencia compleja TX->RX (solo el aire)
    ez, t    la traza cruda en la sonda RX, por si hace falta rehacer algo
    meta     los parametros con los que se corrio

H NO incluye cables ni el retardo interno: eso lo agrega radar.py, que es
donde estan los .s2p medidos. Asi una sola corrida de MEEP sirve para
comparar juegos de cables distintos.
"""

import os
import sys
import time

import numpy as np
import meep as mp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parametros as P                                        # noqa: E402

# 0 = meep no imprime nada propio. Con 1 volcaba las coordenadas de cada una
# de las 11 paredes en cada escena (~70 lineas por escena) y tapaba lo que
# importa. Lo nuestro (celda, tiempo de FDTD, destino) sale con print().
mp.verbosity(0)

# --- Pulso de la fuente ----------------------------------------------------
#
# Gaussiana modulada, definida aca y no con mp.GaussianSource para poder
# calcularle la DFT con EXACTAMENTE el mismo codigo que a la traza de Rx: asi
# cualquier sesgo del muestreo se cancela en el cociente H = Rx/fuente, y no
# hay que depender de como define meep su envolvente.
#
# FC en el centro de la banda, y ANCHO tal que la gaussiana llegue a los
# bordes con amplitud suficiente: sigma_f = 1/(2*pi*ANCHO). Con ANCHO 0,6 son
# 0,265 u.MEEP = 530 MHz, y los bordes de la banda (+-575 MHz del centro)
# quedan a 1,08 sigma, o sea al 56 % del pico. El cociente H = Rx/fuente es
# exacto sea cual sea la forma del pulso; lo unico que hace falta es que la
# fuente tenga energia en toda la banda para que el cociente no amplifique
# ruido numerico.
FC     = (P.f_meep(P.F_MIN) + P.f_meep(P.F_MAX)) / 2.0
ANCHO  = 0.6                                                # u.MEEP de tiempo
T0     = 5.0 * ANCHO                                        # arranque del pulso
DT_REC = 0.05                                               # muestreo de la traza


def pulso(t):
    """Gaussiana modulada, real. t en unidades MEEP."""
    env = np.exp(-((t - T0) ** 2) / (2.0 * ANCHO ** 2))
    return float(env * np.cos(2.0 * np.pi * FC * (t - T0)))


# --- Geometria -------------------------------------------------------------

def _pared_afuera(p1, p2, espesor, afuera):
    """Pared metalica cuya cara INTERIOR es el segmento p1-p2.

    El espesor se agrega entero hacia el lado de `afuera` (un punto
    cualquiera de ese lado), asi la superficie que ve la onda queda
    exactamente donde dice la medida, sea cual sea el espesor simulado.
    """
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    largo = np.hypot(dx, dy)
    nx, ny = -dy / largo, dx / largo
    ax, ay = afuera
    if (ax - x1) * nx + (ay - y1) * ny < 0:
        nx, ny = -nx, -ny
    v = [mp.Vector3(x1, y1), mp.Vector3(x2, y2),
         mp.Vector3(x2 + nx * espesor, y2 + ny * espesor),
         mp.Vector3(x1 + nx * espesor, y1 + ny * espesor)]
    return mp.Prism(v, height=mp.inf, material=mp.metal)


def bocina(xc, y_fondo, y_carga=None):
    """Bocina piramidal 2D apuntando a +y, centrada en xc.

    `y_fondo` es la cara INTERIOR del fondo. Tres tramos, con las medidas de
    parametros.py (las interiores: la exterior menos la chapa):
      - el corto del fondo,
      - las dos paredes de la guia, de GUIA_LARGO desde el fondo,
      - las dos paredes del flare, que abren de GUIA_ANCHO a APERTURA y
        terminan en la boca, a LARGO_TOTAL del fondo.

    Las paredes se simulan de PARED (1 cm) porque la grilla no resuelve la
    chapa real, pero se engordan HACIA AFUERA: la cara interior queda donde
    corresponde, que es lo que ve la onda.

    Con `y_carga` (SONDA = "adaptada") NO hay corto: las paredes de la guia
    siguen derecho hacia abajo hasta y_carga, que se elige afuera de la
    celda, o sea que la guia atraviesa el PML del borde. El PML absorbe el
    modo guiado sin reflejarlo: es la carga de 50 ohm de la sonda. Ver
    SONDA en parametros.py.
    """
    g  = P.a_meep(P.GUIA_ANCHO) / 2.0        # media guia, por dentro
    ap = P.a_meep(P.APERTURA) / 2.0          # media boca, por dentro
    lg = P.a_meep(P.GUIA_LARGO)
    lt = P.a_meep(P.LARGO_TOTAL)
    e  = P.a_meep(P.PARED)

    if y_carga is None:
        # corto: de lado a lado, tapando tambien el espesor de las paredes
        piezas = [_pared_afuera((xc - g - e, y_fondo), (xc + g + e, y_fondo),
                                e, (xc, y_fondo - 1.0))]
        y_ini = y_fondo - e
    else:
        piezas = []
        y_ini = y_carga
    for s in (-1, +1):
        lejos = (xc + s * 10.0, y_fondo)     # un punto del lado de afuera
        piezas.append(_pared_afuera((xc + s * g, y_ini),
                                    (xc + s * g, y_fondo + lg), e, lejos))
        piezas.append(_pared_afuera((xc + s * g, y_fondo + lg),
                                    (xc + s * ap, y_fondo + lt), e, lejos))
    return piezas


def construir(con_placa, dist_placa=None, dist_celda=None):
    """Devuelve (geometria, cell, dy, tx, rx) en unidades MEEP.

    `dist_placa` es la distancia del plano de apertura a la placa [m]; por
    defecto, la de parametros.py. `dist_celda` es la distancia con la que se
    DIMENSIONA la celda, que puede ser mayor: al barrer la distancia de la
    placa conviene que todas las corridas compartan la grilla y la posicion
    del PML, para que las diferencias entre ellas sean la placa y nada mas.

    Se construye con el fondo de las bocinas en y=0 y despues se corre todo
    en `dy` para que la celda quede centrada en el origen, que es lo que
    espera meep. El corrimiento se aplica a mano al armar cada pieza en vez
    de con .shift(), que segun la version de meep devuelve el objeto o lo
    muta en el lugar.
    """
    if dist_placa is None:
        dist_placa = P.DIST_PLACA
    if dist_celda is None:
        dist_celda = dist_placa

    lt  = P.a_meep(P.LARGO_TOTAL)
    ap  = P.a_meep(P.APERTURA) / 2.0
    e   = P.a_meep(P.PARED)
    sep = P.a_meep(P.SEP_ANTENAS)

    y_placa = lt + P.a_meep(dist_placa)
    y_fin   = lt + P.a_meep(dist_celda) + P.a_meep(P.PLACA_ESPESOR)

    # Extension util antes de agregar margen y PML.
    #
    # La celda NO depende de con_placa: las dos escenas tienen que correr en
    # la MISMA grilla, con el mismo PML a la misma distancia, para que la
    # resta H_placa - H_vacio sea exactamente el eco de la placa y no ademas
    # la diferencia entre dos discretizaciones distintas.
    y_lo = 0.0 - e
    y_hi = y_fin
    # Lo mas ancho entre las bocinas y la placa: una placa de 70 cm (+-35 cm)
    # es mas ancha que las dos bocinas juntas (+-31,5 cm), y si la celda solo
    # mirara las bocinas los bordes de la placa quedarian dentro del PML.
    x_ext = max(sep / 2.0 + ap + e, P.a_meep(P.PLACA_ANCHO) / 2.0 + e)

    borde = P.MARGEN + P.DPML
    # Redondeado para arriba a un numero entero de celdas: si no, meep lo
    # redondea solo y avisa con un "Warning" que asusta y no significa nada.
    # Se divide por la resolucion en vez de multiplicar por 1/resolucion:
    # 164 * 0.05 da 8.200000000000001, que meep ya no considera entero.
    def _entero(u):
        return float(np.ceil(u * P.RESOLUCION - 1e-6)) / P.RESOLUCION
    cell = mp.Vector3(_entero(2 * (x_ext + borde)),
                      _entero((y_hi - y_lo) + 2 * borde), 0)
    dy = -(y_lo + y_hi) / 2.0          # corrimiento para centrar la celda

    x_tx, x_rx = -sep / 2.0, +sep / 2.0
    # Sonda adaptada: la guia sigue hasta medio u.MEEP por DEBAJO del borde
    # de la celda, asi cruza entero el PML de abajo. La celda no cambia: la
    # guia pasa por el MARGEN de aire que ya habia debajo de las bocinas.
    y_carga = -cell.y / 2.0 - 0.5 if P.SONDA == "adaptada" else None
    geom = bocina(x_tx, dy, y_carga) + bocina(x_rx, dy, y_carga)

    if con_placa:
        geom.append(mp.Block(
            size=mp.Vector3(P.a_meep(P.PLACA_ANCHO),
                            P.a_meep(P.PLACA_ESPESOR), mp.inf),
            center=mp.Vector3(0.0, y_placa + P.a_meep(P.PLACA_ESPESOR) / 2.0 + dy),
            material=mp.metal))

    # Sondas, adentro de la guia, cada una a su distancia del fondo
    tx = mp.Vector3(x_tx, P.a_meep(P.SONDA_TX) + dy)
    rx = mp.Vector3(x_rx, P.a_meep(P.SONDA_RX) + dy)
    return geom, cell, dy, tx, rx


# --- Corrida ---------------------------------------------------------------

def correr(con_placa, etiqueta, dist_placa=None, dist_celda=None):
    if dist_placa is None:
        dist_placa = P.DIST_PLACA
    geom, cell, dy, tx, rx = construir(con_placa, dist_placa, dist_celda)

    fuente = mp.Source(
        src=mp.CustomSource(src_func=pulso, start_time=0.0,
                            end_time=2.0 * T0,
                            center_frequency=FC,
                            fwidth=P.f_meep(P.F_MAX - P.F_MIN)),
        component=mp.Ez,
        center=tx)

    sim = mp.Simulation(cell_size=cell,
                        boundary_layers=[mp.PML(P.DPML)],
                        geometry=geom,
                        sources=[fuente],
                        resolution=P.RESOLUCION,
                        force_complex_fields=False)

    muestras = []
    def _rec(s):
        muestras.append(s.get_field_point(mp.Ez, rx).real)

    print(f"\n=== escena '{etiqueta}' ===")
    print(f"  celda {cell.x:.2f} x {cell.y:.2f} u.MEEP = "
          f"{P.a_metros(cell.x):.2f} x {P.a_metros(cell.y):.2f} m")
    print(f"  {int(cell.x*P.RESOLUCION)} x {int(cell.y*P.RESOLUCION)} celdas, "
          f"{int(P.T_CORRIDA/(0.5/P.RESOLUCION))} pasos")

    # Tres fotos del campo Ez para la figura: el pulso saliendo, llegando a
    # la placa y volviendo. Los tiempos salen de la geometria (en unidades
    # MEEP la luz recorre 1 u por unidad de tiempo): el pulso esta centrado
    # en T0, recorre la bocina (sonda -> boca) y despues el aire.
    d_boc = P.a_meep(P.LARGO_TOTAL - P.SONDA_TX)
    d_aire = P.a_meep(dist_placa)
    t_fotos = {"sale":   T0 + d_boc + 0.35 * d_aire,
               "placa":  T0 + d_boc + 1.00 * d_aire,
               "vuelve": T0 + d_boc + 1.65 * d_aire}
    fotos = {}
    def _foto(nombre):
        def f(s):
            fotos[nombre] = s.get_array(component=mp.Ez, center=mp.Vector3(),
                                        size=cell).astype(np.float32)
        return f

    t0 = time.time()
    sim.run(mp.at_every(DT_REC, _rec),
            *[mp.at_time(tt, _foto(k)) for k, tt in t_fotos.items()],
            until=P.T_CORRIDA)
    print(f"  FDTD: {time.time()-t0:.1f} s")
    eps = sim.get_array(component=mp.Dielectric, center=mp.Vector3(),
                        size=cell).astype(np.float32)
    # Extension de las fotos en METROS, con el origen en el plano de la boca
    # de las bocinas (y = 0) y la placa en y = dist_placa. En la construccion
    # el fondo de las bocinas esta en y_u = dy y la boca en dy + largo total.
    lt = P.a_meep(P.LARGO_TOTAL)
    extent_m = np.array([-cell.x / 2, cell.x / 2,
                         -cell.y / 2 - dy - lt, cell.y / 2 - dy - lt]) * P.A_MEEP

    ez = np.array(muestras)
    t  = np.arange(len(ez)) * DT_REC
    src = np.array([pulso(tt) for tt in t])

    # DFT directa a las frecuencias que se piden, no una FFT: asi el paso en
    # frecuencia no lo ata el largo de la corrida, y la misma cuenta se le
    # aplica a la traza y a la fuente (cualquier sesgo se cancela).
    f_meep = np.linspace(P.f_meep(P.F_MIN), P.f_meep(P.F_MAX), P.N_FREQ)
    fase = np.exp(-2j * np.pi * np.outer(f_meep, t))
    H = (fase @ ez) / (fase @ src)

    f_hz = np.linspace(P.F_MIN, P.F_MAX, P.N_FREQ)
    os.makedirs(P.SALIDAS, exist_ok=True)
    destino = os.path.join(P.SALIDAS, f"H_{etiqueta}.npz")
    np.savez_compressed(
        destino, f_hz=f_hz, H=H, ez=ez, t=t, src=src,
        fotos=np.array([fotos[k] for k in ("sale", "placa", "vuelve")]),
        fotos_t=np.array([t_fotos[k] for k in ("sale", "placa", "vuelve")]),
        eps=eps, extent_m=extent_m, dpml_m=P.DPML * P.A_MEEP,
        dist_placa=dist_placa, sonda=P.SONDA,
        meta=np.array([
            f"corrida={P.NOMBRE}",
            f"escena={etiqueta}", f"con_placa={con_placa}",
            f"a_meep={P.A_MEEP}", f"resolucion={P.RESOLUCION}",
            f"T_corrida={P.T_CORRIDA}", f"dt_rec={DT_REC}",
            f"dist_placa={dist_placa}",
            f"sep_antenas={P.SEP_ANTENAS}",
            f"apertura={P.APERTURA}", f"placa_ancho={P.PLACA_ANCHO}",
            f"sonda={P.SONDA}",
            f"bocina_ext=guia {P.GUIA_ANCHO_EXT} boca {P.APERTURA_EXT} "
            f"largo {P.LARGO_EXT} recta {P.GUIA_LARGO_EXT} "
            f"conectores {P.CONECTOR_TX}/{P.CONECTOR_RX} chapa {P.CHAPA}",
        ]))
    print(f"  |H| medio {20*np.log10(np.abs(H).mean()):.1f} dB  ->  {destino}")
    return destino


def main():
    """Escenas por linea de comandos.

        python escena.py                    placa a DIST_PLACA, y vacio
        python escena.py vacio              solo el acoplamiento directo
        python escena.py barrido            placa a cada distancia de P.BARRIDO
                                            mas el vacio, TODAS en la misma
                                            grilla (celda dimensionada para
                                            la distancia mayor)
    """
    args = sys.argv[1:] or ["placa", "vacio"]

    if args == ["barrido"]:
        distancias = list(P.BARRIDO)
        celda = max(distancias)
        for d in distancias:
            correr(True, f"placa_{d:.2f}".replace(".", "p"),
                   dist_placa=d, dist_celda=celda)
        correr(False, "vacio_barrido", dist_placa=celda, dist_celda=celda)
        return

    for e in args:
        if e not in ("placa", "vacio"):
            raise SystemExit(f"escena desconocida: {e} (placa | vacio | barrido)")
        correr(con_placa=(e == "placa"), etiqueta=e)


if __name__ == "__main__":
    main()
