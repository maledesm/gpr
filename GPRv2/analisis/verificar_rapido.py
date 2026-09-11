"""
GPRv2 - Verificacion y medicion de `vivo_rapido.py` contra `vivo.py`
====================================================================

Corre sin hardware. Hace dos cosas:

  1. VERIFICA que la version rapida da LO MISMO que la original. No alcanza
     con que ande mas rapido: `vivo_rapido.py` toca el remuestreo, la FFT, el
     ajuste del periodo y el agrupado, o sea todo el camino de la medicion.
     Aca se comparan los dos pipelines completos alimentados con el MISMO
     stream sintetico, hasta la distancia que informa cada uno.

  2. MIDE cuanto se gano, pieza por pieza y de punta a punta.

Uso
---
    python verificar_rapido.py
"""

import os
import sys
import time

import matplotlib
matplotlib.use("Agg")              # sin ventana: esto corre en cualquier lado

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import vivo                         # noqa: E402  (el original, de referencia)
import vivo_rapido as vr            # noqa: E402
import proceso_rapido as pr         # noqa: E402
from correccion_no_linealidad import (  # noqa: E402
    cargar_curva_vco, eje_theta, remuestrear, ajustar_triangular, fs_theta,
    V_MIN, V_MAX, C,
)

FS = 6000.0
VCO_CSV = os.path.join(AQUI, "..", "..", "VCO", "Caracteristica VCO.csv")

OK, MAL = "  OK  ", " MAL  "
fallas = []


def juzgar(nombre, bien, detalle):
    print(f"[{OK if bien else MAL}] {nombre:<46s} {detalle}")
    if not bien:
        fallas.append(nombre)


# --- stream sintetico ------------------------------------------------------

def generar_stream(curva, T, t0, blancos, segundos, ruido=0.0, semilla=0):
    """Las lineas de texto que emitiria la placa, con blancos conocidos.

    La triangular hace subir y bajar la tension del VCO entre V_MIN y V_MAX, y
    la fase de batido de un blanco a distancia r es 2*pi*tau*(f(t)-f(0)) con
    tau = 2r/c: la misma construccion que usa el modo sintetico de
    `correccion_no_linealidad.py`, pero a lo largo de una triangular entera.
    """
    rng = np.random.default_rng(semilla)
    n = int(segundos * FS)
    t = np.arange(n) / FS
    u = ((t - t0) % T) / T
    # Fraccion recorrida de la rampa: sube en la primera mitad, baja en la
    # segunda. La bajada leida al reves es una subida, que es justo lo que
    # asume el troceo de los dos programas.
    x = np.where(u < 0.5, 2 * u, 2 * (1 - u))
    v = V_MIN + (V_MAX - V_MIN) * x
    f = curva(v)
    g = f - curva(V_MIN)

    beat = np.zeros(n)
    for r, amp_db in blancos:
        tau = 2.0 * r / C
        beat += 10 ** (amp_db / 20.0) * np.cos(2 * np.pi * tau * g
                                               + rng.uniform(0, 2 * np.pi))
    if ruido:
        beat += rng.normal(0, ruido, n)
    # Escala de cuentas del PCM1808 (24 bits) sobre una continua, como la real
    muestras = np.rint(beat * 2.0e5 + 3.0e5).astype(np.int64)

    # La triangular se muestrea una vez por bloque de DMA: 6000/32 = 187,5/s,
    # que es la tasa real de la placa. 12 bits con el divisor 4k7/4k7.
    adc = np.rint(x * 2450 + 40).astype(np.int64)

    lineas = []
    for i in range(n):
        lineas.append(f"{muestras[i]},-1")
        if i % 32 == 0:
            lineas.append(f"#v,{adc[i]},{i}")
    return "\n".join(lineas) + "\n"


class Archivo:
    """Un archivo de mentira, para no escribir nada a disco."""
    def write(self, _s):
        pass


class Puerto:
    """Un puerto de mentira que devuelve el stream de a bloques."""
    def __init__(self, texto, bloque=8192):
        self.datos = texto.encode("ascii")
        self.i = 0
        self.bloque = bloque

    def hay(self):
        return self.i < len(self.datos)

    def leer(self):
        trozo = self.datos[self.i:self.i + self.bloque]
        self.i += len(trozo)
        return trozo


# --- 1. remuestreo ---------------------------------------------------------

def probar_remuestreo(curva):
    print("\n--- 1. remuestreo: matriz precalculada vs interp1d cubico ---")
    n = 120
    t = np.linspace(0, n / FS, n, endpoint=False)
    _, theta, _ = eje_theta(curva, t)
    rng = np.random.default_rng(3)
    S = rng.normal(0, 1e5, (24, n))

    ref = np.array([remuestrear(theta, s, n)[1] for s in S])
    rem = pr.Remuestreador(theta, n)
    mio = rem.aplicar(S)
    err = np.abs(mio - ref).max() / np.abs(ref).max()
    juzgar("remuestreo identico a remuestrear()", err < 1e-5,
           f"error relativo maximo {err:.2e} (float32)")

    rem64 = pr.Remuestreador(theta, n, dtype=np.float64)
    err64 = np.abs(rem64.aplicar(S) - ref).max() / np.abs(ref).max()
    juzgar("  el mismo spline, en doble precision", err64 < 1e-12,
           f"error relativo maximo {err64:.2e}")

    # La ventana plegada adentro de la matriz tiene que dar lo mismo que
    # ventanear despues.
    w = np.hanning(n)
    remw = pr.Remuestreador(theta, n, w)
    err_w = np.abs(remw.aplicar_ventaneado(S) - ref * w).max() / \
        np.abs(ref * w).max()
    juzgar("  ventana plegada == ventanear despues", err_w < 1e-5,
           f"error relativo maximo {err_w:.2e}")

    # Y el espectro completo, que es lo que de verdad se dibuja.
    nfft = pr.largo_fft(n, 8)
    esp_ref = np.abs(np.fft.rfft(ref * w, n=nfft, axis=1))
    esp_mio = pr.espectros(remw.aplicar_ventaneado(S), nfft)
    err_e = np.abs(esp_mio - esp_ref).max() / esp_ref.max()
    juzgar("  |FFT| del lote identico", err_e < 1e-5,
           f"error relativo maximo {err_e:.2e}")

    t0 = time.perf_counter()
    for _ in range(200):
        [remuestrear(theta, s, n)[1] for s in S]
    t1 = time.perf_counter()
    viejo = (t1 - t0) / 200 / len(S) * 1e6
    t0 = time.perf_counter()
    for _ in range(200):
        pr.espectros(remw.aplicar_ventaneado(S), nfft)
    t1 = time.perf_counter()
    nuevo = (t1 - t0) / 200 / len(S) * 1e6
    print(f"        remuestreo por rampa: {viejo:7.1f} us -> "
          f"{nuevo:6.1f} us (con FFT incluida)  {viejo/nuevo:5.1f}x")


# --- 2. ajuste de la triangular --------------------------------------------

def probar_ajuste():
    print("\n--- 2. ajuste de periodo y fase de la triangular ---")
    rng = np.random.default_rng(7)
    casos = ((80e-3, 0.01), (80e-3, 0.10), (40e-3, 0.01),
             (20e-3, 0.10), (12.5e-3, 0.10))
    peor_T = peor_t0 = 0.0
    tv = tr = 0.0
    for T, span in casos:
        n_lec = int(187.5 * vr.VENTANA_AJUSTE_S)
        idx = np.arange(n_lec) * (FS / 187.5)
        t0v = 0.37 * T
        u = (((idx / FS) - t0v) % T) / T
        val = 40 + 2450 * np.where(u < 0.5, 2 * u, 2 * (1 - u))
        val = val + rng.normal(0, 20, n_lec)
        T_ini = T * 1.006          # como lo deja buscar_periodo()

        a = time.perf_counter(); T1, p1 = ajustar_triangular(idx, val, FS, T_ini, span); b = time.perf_counter()
        c = time.perf_counter(); T2, p2 = pr.ajustar_triangular_rapido(idx, val, FS, T_ini, span); d = time.perf_counter()
        tv += b - a
        tr += d - c
        peor_T = max(peor_T, abs(T2 - T1) / T1)
        peor_t0 = max(peor_t0, abs(p2 - p1))
        print(f"        T={T*1e3:6.2f} ms span={span:4.2f}: "
              f"orig {(b-a)*1e3:6.1f} ms / rapido {(d-c)*1e3:5.2f} ms   "
              f"dT={(T2-T1)/T1*1e6:+7.2f} ppm  dt0={(p2-p1)*1e6:+7.1f} us   "
              f"(error contra la verdad: {(T2-T)/T*1e6:+6.2f} ppm)")
    juzgar("el periodo coincide con el original", peor_T < 2e-5,
           f"peor desvio {peor_T*1e6:.2f} ppm")
    # Una muestra a 6000 sps son 167 us: el ajuste tiene que ubicar el vertice
    # mucho mejor que eso o los limites de rampa se corren.
    juzgar("la fase coincide con el original", peor_t0 < 40e-6,
           f"peor desvio {peor_t0*1e6:.1f} us (una muestra son 167 us)")
    print(f"        total: {tv*1e3:7.1f} ms -> {tr*1e3:6.1f} ms   "
          f"{tv/tr:5.1f}x")


# --- 3. pico sub-bin -------------------------------------------------------

def probar_pico_subbin():
    print("\n--- 3. pico sub-bin (parabola sobre los tres dB del maximo) ---")
    # Un tono puro con frecuencia entre dos bins: el argmax cae en el bin de
    # al lado y la parabola tiene que recuperar la fraccion.
    n, relleno = 120, 8
    nfft = n * relleno
    w = np.hanning(n)
    err_bin, err_par = [], []
    for frac in np.linspace(0, 0.5, 11):
        k = 17 + frac                      # bin verdadero, fraccionario
        x = np.cos(2 * np.pi * k * np.arange(n) / n)
        esp = np.abs(np.fft.rfft(x * w, n=nfft))
        i = int(np.argmax(esp))
        d = pr.pico_parabolico(esp, i)
        verdad = k * relleno               # bin verdadero en la grilla rellena
        err_bin.append(abs(i - verdad))
        err_par.append(abs(i + d - verdad))
    juzgar("la parabola mejora la posicion del pico",
           np.mean(err_par) < np.mean(err_bin) / 2,
           f"error medio {np.mean(err_bin):.3f} -> {np.mean(err_par):.3f} bins "
           f"({np.mean(err_bin)/max(np.mean(err_par),1e-9):.1f}x)")


# --- 4. lector -------------------------------------------------------------

def probar_lector(texto):
    print("\n--- 4. lector del puerto ---")
    p1, p2 = Puerto(texto), Puerto(texto)
    l1 = vivo.Lector(None, Archivo(), Archivo())
    l2 = vr.Lector(None, Archivo(), Archivo())

    t0 = time.perf_counter()
    resto = b""
    while p1.hay():
        trozos = (resto + p1.leer()).split(b"\n")
        resto = trozos.pop()
        l1.procesar(trozos)
    t1 = time.perf_counter()

    t2 = time.perf_counter()
    resto2 = ""
    while p2.hay():
        resto2 = l2.procesar(resto2 + p2.leer().decode("ascii", "ignore"))
    t3 = time.perf_counter()

    b1, tri1 = l1.tomar()
    b2, tri2 = l2.tomar()
    juzgar("mismas muestras de batido", b1 == b2,
           f"{len(b1)} muestras, {l1.descartadas} cortadas")
    juzgar("mismas lecturas de triangular", tri1 == tri2,
           f"{len(tri1)} lecturas")
    seg = len(b1) / FS
    print(f"        parseo: {(t1-t0)/seg*1e3:6.2f} ms -> "
          f"{(t3-t2)/seg*1e3:5.2f} ms por segundo de stream   "
          f"{(t1-t0)/(t3-t2):5.1f}x")


# --- 5. de punta a punta ---------------------------------------------------

def correr(modulo, curva, texto, cuadros_por_s=5.0, forzar=None):
    """Corre un programa entero contra el stream, sin ventana, y devuelve
    (distancia del pico, matriz de dB, ms de proceso, ms de dibujo, estado).

    El stream se entrega en trozos del tamano que le tocaria a un refresco,
    asi el troceo en rampas y los reajustes caen donde caerian de verdad.

    Con `forzar=(T, t0)` se le imponen los limites de rampa en vez de dejar
    que los ajuste, y no se reajusta nunca: sirve para comparar los dos
    pipelines sobre EXACTAMENTE las mismas rampas.
    """
    import matplotlib.pyplot as plt
    lec = modulo.Lector(None, Archivo(), Archivo())
    v = modulo.Vivo(lec, curva, modulo.Calibracion())
    v.armar_figura()
    es_rapido = hasattr(v, "_pintar")

    datos = texto.encode("ascii")
    n_muestras = texto.count(",-1")                  # una por linea de batido
    bytes_por_s = len(datos) / (n_muestras / FS)
    paso = max(1, int(bytes_por_s / cuadros_por_s))  # el bloque de un refresco

    t_proc = 0.0
    n_cuadros = 0
    db = None
    i, resto = 0, (b"" if not es_rapido else "")
    while i < len(datos):
        trozo = datos[i:i + paso]
        i += paso
        if es_rapido:
            resto = lec.procesar(resto + trozo.decode("ascii", "ignore"))
        else:
            trozos = (resto + trozo).split(b"\n")
            resto = trozos.pop()
            lec.procesar(trozos)
        a = time.perf_counter()
        if es_rapido:
            v._cache.clear()
            v._cuadro += 1
        v.drenar()
        ahora = v.n_total / FS
        if v.T is None:
            if ahora >= modulo.CALIBRACION_S:
                if forzar is None:
                    v.ajustar(primera_vez=True)
                else:
                    v.T, v.t0 = forzar
                    v.n = int(round(v.T * FS / 2))
                    v.k = 0
                    v._armar_ejes()
                v.txt.set_visible(False)
        elif forzar is None and ahora - v.t_ajuste > modulo.REAJUSTE_S:
            v.t_ajuste = ahora
            v.ajustar(primera_vez=False)
        if v.T is not None:
            v.procesar()
            db = v.matriz()[0]
        t_proc += time.perf_counter() - a
        n_cuadros += 1

    # El dibujo, medido aparte y con la pantalla ya llena.
    t_dib = 0.0
    if db is not None:
        for _ in range(3):                       # calentar
            _dibujar(v, es_rapido)
        a = time.perf_counter()
        for _ in range(8):
            _dibujar(v, es_rapido)
        t_dib = (time.perf_counter() - a) / 8
    if es_rapido:
        v._cache.clear()
    d = v.pico_crudo()
    estado = (v.T, v.t0, v.n, v.n_perf)
    plt.close(v.fig)
    return d, db, t_proc / n_cuadros * 1e3, t_dib * 1e3, estado


def _dibujar(v, es_rapido):
    """Un refresco de pantalla, igual al que hace cada programa."""
    if es_rapido:
        v._cache.clear()
        v._cuadro += 1
        db, span, x0, x1 = v.matriz()
        i1 = v._i_alcance()
        v.im.set_data(db)
        v.im.set_extent((x0, x1, 0, max(span, 1e-3)))
        v.ax.set_ylim(max(span, 1e-3), 0)
        v.linea.set_data(v._eje_x()[:i1], db[-1])
        v.traza.set_data(*v.traza_picos(db, max(span, 1e-3)))
        v._poner_estado()
        v._poner_info(v.n_total / vr.FS, db)
        v._pintar(True, True)
    else:
        db, span = v.matriz()
        v.im.set_data(db)
        v.im.set_extent((v._eje_x()[0], v._eje_x()[-1], 0, max(span, 1e-3)))
        v.ax.set_ylim(max(span, 1e-3), 0)
        v.linea.set_data(v._eje_x(), db[-1])
        v.traza.set_data(*v.traza_picos(db, max(span, 1e-3)))
        v._poner_estado(v.n_total / vivo.FS, db)
        v.fig.canvas.draw()


def probar_punta_a_punta(curva, texto, r_verdadero):
    print("\n--- 5. de punta a punta: el mismo stream por los dos programas ---")
    d1, db1, p1, g1, e1 = correr(vivo, curva, texto)
    d2, db2, p2, g2, e2 = correr(vr, curva, texto)

    T1, t01, n1, np1 = e1
    T2, t02, n2, np2 = e2
    print(f"        original: T={T1*1e3:.6f} ms  t0={t01*1e3:.4f} ms  "
          f"rampa {n1} muestras, {np1} perfiles")
    print(f"        rapido  : T={T2*1e3:.6f} ms  t0={t02*1e3:.4f} ms  "
          f"rampa {n2} muestras, {np2} perfiles")
    juzgar("mismo troceo en rampas", n1 == n2 and np1 == np2,
           f"{n1}/{n2} muestras por rampa, {np1}/{np2} perfiles")
    # Los dos ajustan el periodo con su propio ruido de estimacion. Lo que
    # importa es que el limite de rampa no se corra ni una muestra (167 us).
    juzgar("mismos limites de rampa (<1 muestra)", abs(t02 - t01) * FS < 1.0,
           f"los vertices difieren {abs(t02-t01)*1e6:.0f} us = "
           f"{abs(t02-t01)*FS:.2f} muestras, y T {abs(T2-T1)/T1*1e6:.1f} ppm")

    juzgar("los dos encuentran el blanco",
           d1 is not None and d2 is not None,
           f"original {d1}, rapido {d2}")
    if d1 is None or d2 is None:
        return
    juzgar("la distancia coincide", abs(d2 - d1) < 0.05,
           f"original {d1:.4f} m, rapido {d2:.4f} m, "
           f"diferencia {abs(d2-d1)*100:.2f} cm")
    juzgar("y las dos dan el blanco de verdad",
           abs(d1 - r_verdadero) < 0.25 and abs(d2 - r_verdadero) < 0.25,
           f"blanco en {r_verdadero:.3f} m -> {d1:.3f} / {d2:.3f} m "
           f"(el rapido interpola sub-bin)")

    # El radargrama. Dos cosas legitimas hacen que no sea identico celda a
    # celda y ninguna es un error:
    #
    #  - la referencia de 0 dB sin fondo medido es el maximo de LO QUE SE VE,
    #    y el rapido ya no arrastra las columnas de mas alla del alcance. Se
    #    normalizan los dos a su propio maximo antes de comparar.
    #  - los dos ajustan el periodo de la triangular por separado y difieren
    #    en una fraccion de muestra. Eso no mueve los picos pero SI mueve los
    #    nulos profundos de la FFT, que son celdas 40 dB debajo del pico y no
    #    se ven en ninguna escala de color usable.
    def comparar(dbA, dbB, umbral=-30.0):
        """Peor diferencia en dB, normalizando los dos a su propio maximo."""
        f = min(dbA.shape[0], dbB.shape[0])
        c = min(dbA.shape[1], dbB.shape[1])
        A = dbA[-f:, :c] - dbA[-f:, :c].max()
        B = dbB[-f:, :c] - dbB[-f:, :c].max()
        D = np.abs(A - B)
        visible = A > umbral
        return D[visible].max(), D[~visible].max() if (~visible).any() else 0.0, \
            int(visible.sum()), f, c

    # (a) La comparacion estricta: los MISMOS limites de rampa para los dos, o
    #     sea exactamente las mismas muestras entrando a cada FFT. Aca no
    #     queda ninguna excusa y tiene que dar igual hasta el fondo.
    _, dbA, _, _, _ = correr(vivo, curva, texto, forzar=(T1, t01))
    _, dbB, _, _, _ = correr(vr, curva, texto, forzar=(T1, t01))
    if dbA is not None and dbB is not None:
        f = min(dbA.shape[0], dbB.shape[0])
        c = min(dbA.shape[1], dbB.shape[1])
        A = dbA[-f:, :c] - dbA[-f:, :c].max()
        B = dbB[-f:, :c] - dbB[-f:, :c].max()
        peor = np.abs(A - B).max()
        juzgar("con los MISMOS limites de rampa, identico", peor < 0.05,
               f"peor diferencia {peor:.2e} dB sobre las {f}x{c} celdas, "
               f"sin excluir ninguna")

    # (b) Dejando que cada uno ajuste el periodo por su cuenta, difieren en
    #     0,35 muestra en el vertice. Eso no mueve los picos pero si los nulos
    #     profundos de la FFT. Para saber si esa diferencia es "del codigo
    #     nuevo" o es el ruido de estimacion que los dos tienen, se mide el
    #     CONTROL: el original contra si mismo, con el vertice del rapido.
    if db1 is not None and db2 is not None:
        vis, nulos, cuantas, f, c = comparar(db1, db2)
        _, dbC, _, _, _ = correr(vivo, curva, texto, forzar=(T1, t02))
        ctrl_vis, ctrl_nulos, _, _, _ = comparar(dbA, dbC)
        juzgar("la diferencia es el ruido del ajuste, no el codigo",
               vis <= ctrl_vis * 1.5 + 0.05,
               f"rapido vs original {vis:.3f} dB; original vs SI MISMO con el "
               f"mismo corrimiento de vertice {ctrl_vis:.3f} dB")
        print(f"        ({cuantas} celdas arriba de -30 dB de {f}x{c}; en los "
              f"nulos llega a {nulos:.1f} dB y el control a {ctrl_nulos:.1f} dB)")

    print(f"\n        proceso por cuadro : {p1:7.2f} ms -> {p2:6.2f} ms   "
          f"{p1/max(p2,1e-9):5.1f}x")
    print(f"        dibujo  por cuadro : {g1:7.2f} ms -> {g2:6.2f} ms   "
          f"{g1/max(g2,1e-9):5.1f}x")
    print(f"        TOTAL   por cuadro : {p1+g1:7.2f} ms -> {p2+g2:6.2f} ms   "
          f"{(p1+g1)/max(p2+g2,1e-9):5.1f}x   "
          f"(el presupuesto es {vr.REFRESCO_MS} ms)")


# --- 6. los archivos que quedan en disco -----------------------------------

def probar_archivos(texto, tmp):
    """Los CSV que escribe cada programa tienen que ser el MISMO archivo.

    El test 4 compara lo que el lector le pasa al grafico; esto compara lo que
    queda en disco, que es otra cosa y es la que importa despues: `vivo.py` y
    `vivo_rapido.py` sobrescriben los mismos datos/captura.csv y
    datos/triangular.csv, y de ahi comen graficar_captura.py y waterfall.py.
    Si el formato cambiara aunque sea en un byte, las capturas nuevas no se
    podrian reanalizar con los scripts de siempre.
    """
    print("\n--- 6. los archivos que quedan en disco ---")
    salidas = {}
    for etiqueta, modulo in (("orig", vivo), ("rapido", vr)):
        cap = os.path.join(tmp, f"captura_{etiqueta}.csv")
        tri = os.path.join(tmp, f"triangular_{etiqueta}.csv")
        with open(cap, "w", encoding="utf-8", newline="\n") as f_cap, \
             open(tri, "w", encoding="utf-8", newline="\n") as f_tri:
            lec = modulo.Lector(None, f_cap, f_tri)
            p = Puerto(texto)
            if modulo is vr:
                resto = ""
                while p.hay():
                    resto = lec.procesar(resto + p.leer().decode("ascii", "ignore"))
            else:
                resto = b""
                while p.hay():
                    trozos = (resto + p.leer()).split(b"\n")
                    resto = trozos.pop()
                    lec.procesar(trozos)
        salidas[etiqueta] = (cap, tri)

    for nombre, i in (("captura.csv", 0), ("triangular.csv", 1)):
        a = open(salidas["orig"][i], "rb").read()
        b = open(salidas["rapido"][i], "rb").read()
        juzgar(f"{nombre} byte a byte identico", a == b,
               f"{len(a)} vs {len(b)} bytes, {a.count(10)} lineas")
    return salidas["rapido"]


# --- 7. la cadena offline sobre una captura del programa nuevo -------------

def probar_cadena_offline(curva, archivos, r_verdadero):
    """Una captura escrita por vivo_rapido.py tiene que poder reanalizarse.

    Se corre la cadena vieja ENTERA —`rampas_desde_triangular()`,
    `remuestrear()`, `perfil_distancia()`, todas de
    correccion_no_linealidad.py, sin tocar— sobre el archivo que dejo el
    programa nuevo, y despues se llaman los dos scripts de analisis tal como
    estan. Es la prueba de que grabar con el programa nuevo no te deja una
    captura que despues no podes usar.
    """
    print("\n--- 7. reanalisis offline de una captura del programa nuevo ---")
    import io
    import contextlib
    import pandas as pd
    from correccion_no_linealidad import (
        rampas_desde_triangular, perfil_distancia, T_SWEEP,
    )
    cap, tri_path = archivos
    d = pd.read_csv(cap, header=None).to_numpy(dtype=float)
    beat = d[:, 0]
    tri = np.loadtxt(tri_path, delimiter=",", ndmin=2)
    juzgar("el CSV se lee con el mismo pandas de siempre",
           d.shape[1] == 2 and len(beat) > 1000,
           f"{d.shape[0]} filas x {d.shape[1]} columnas, "
           f"{len(tri)} lecturas de triangular")

    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        rampas, indices, n = rampas_desde_triangular(
            beat, tri[:, 1], tri[:, 0], FS, int(round(T_SWEEP * FS)))
    print("        " + salida.getvalue().strip())

    t = np.linspace(0, n / FS, n, endpoint=False)
    _, theta, alpha0 = eje_theta(curva, t)
    fs_th = fs_theta(theta, n)
    perfiles = []
    for cruda in rampas:
        bloque = cruda - cruda.mean()
        _, corregido = remuestrear(theta, bloque, n)
        rango, esp = perfil_distancia(corregido, fs_th, alpha0)
        perfiles.append(esp)
    medio = np.mean(perfiles, axis=0)
    util = rango > 0.3
    d_pico = float(rango[util][np.argmax(medio[util])])
    juzgar("la cadena vieja encuentra el blanco en el archivo nuevo",
           abs(d_pico - r_verdadero) < 0.25,
           f"blanco en {r_verdadero:.3f} m -> la cadena offline da "
           f"{d_pico:.3f} m sobre {len(rampas)} rampas")

    # Y los dos scripts tal como estan, con las rutas apuntadas al archivo
    # de prueba para no pisar datos/ del usuario.
    for nombre in ("waterfall", "graficar_captura"):
        mod = __import__(nombre)
        guardado = {}
        for attr, valor in (("CSV_ENTRADA", cap), ("CAPTURA", cap),
                            ("TRIANG", tri_path)):
            if hasattr(mod, attr):
                guardado[attr] = getattr(mod, attr)
                setattr(mod, attr, valor)
        # `waterfall.py` hereda de correccion_no_linealidad.py rutas relativas
        # al DIRECTORIO ACTUAL y no al archivo, asi que solo corre parado en
        # analisis/ (esta anotado en CLAUDE.md). No es algo que rompa
        # vivo_rapido.py, pero si esta prueba se corre desde otra carpeta el
        # script se cae buscando la curva del VCO. Se entra a analisis/ para
        # llamarlo, igual que haria uno a mano.
        antes = os.getcwd()
        try:
            os.chdir(AQUI)
            with contextlib.redirect_stdout(io.StringIO()):
                mod.main()
            ok, detalle = True, "corrio sin errores sobre la captura nueva"
        except SystemExit as e:
            ok, detalle = False, f"aborto: {e}"
        except Exception as e:
            ok, detalle = False, f"{type(e).__name__}: {e}"
        finally:
            os.chdir(antes)
            for attr, valor in guardado.items():
                setattr(mod, attr, valor)
            import matplotlib.pyplot as plt
            plt.close("all")
        juzgar(f"{nombre}.py", ok, detalle)


# --- 8. el boton de captura ------------------------------------------------

def probar_captura(curva, texto, tmp):
    """El boton de captura: nombres, colisiones, recorte y calidad."""
    print("\n--- 8. captura PNG para el informe ---")
    import glob
    import matplotlib.pyplot as plt
    lec = vr.Lector(None, Archivo(), Archivo())
    v = vr.Vivo(lec, curva, vr.Calibracion())
    v.armar_figura()
    datos = texto.encode("ascii")
    paso = max(1, len(datos) // 100)
    i, resto = 0, ""
    for _ in range(60):
        resto = lec.procesar(resto + datos[i:i + paso].decode("ascii", "ignore"))
        i += paso
        v.actualizar()

    # El cuadro de informacion no puede desbordarse del marco: es lo que se
    # lee en la captura seis meses despues. Se mide con fondo medido, que es
    # el caso de mas lineas.
    v.medir_fondo()
    v.actualizar()
    ren = v.fig.canvas.get_renderer()
    caja = v.info.get_window_extent(ren).transformed(v.axi.transAxes.inverted())
    n_lin = v.info.get_text().count("\n") + 1
    juzgar("el cuadro de informacion entra en su marco",
           caja.y0 > 0.0 and caja.y1 <= 1.0,
           f"{n_lin} lineas, ocupa de {caja.y0:.3f} a {caja.y1:.3f} del axes")

    # Los controles no pueden pisarse entre si ni salirse de la figura.
    cajas = ([c.ax.get_position() for c, _ in v.cajas.values()]
             + [v.caja_nombre.ax.get_position()]
             + [b.ax.get_position() for b in v.botones])
    choques = sum(1 for a in range(len(cajas)) for b in range(a + 1, len(cajas))
                  if (cajas[a].x0 < cajas[b].x1 and cajas[b].x0 < cajas[a].x1
                      and cajas[a].y0 < cajas[b].y1 and cajas[b].y0 < cajas[a].y1))
    est = v.axe.get_position()
    juzgar("los controles no se pisan ni tapan el estado",
           choques == 0 and min(c.y0 for c in cajas) > est.y1
           and max(c.y1 for c in cajas) < 1.0,
           f"{len(cajas)} controles, el mas bajo en y={min(c.y0 for c in cajas):.3f}, "
           f"el estado termina en y={est.y1:.3f}")

    salida = os.path.join(tmp, "capturas")
    guardado = vr.CAPTURAS
    vr.CAPTURAS = salida
    try:
        v.caja_nombre.set_val("placa 1 m")
        v.guardar_captura()
        v.guardar_captura()                      # misma vez: no debe pisar
        v.caja_nombre.set_val('con/prohibidos:*?  ')
        v.guardar_captura()
        v.caja_nombre.set_val("")
        v.guardar_captura()                      # vacio -> nombre por defecto
    finally:
        vr.CAPTURAS = guardado
        plt.close(v.fig)

    png = sorted(os.path.basename(p) for p in glob.glob(os.path.join(salida, "*.png")))
    juzgar("no sobrescribe y sanea el nombre", len(png) == 4,
           ", ".join(png))
    grandes = [p for p in glob.glob(os.path.join(salida, "*.png"))
               if os.path.getsize(p) > 50_000]
    juzgar("los PNG salen con calidad de informe", len(grandes) == len(png),
           f"{len(png)} archivos, el mas chico "
           f"{min(os.path.getsize(p) for p in glob.glob(os.path.join(salida,'*.png')))/1024:.0f} KB "
           f"a {vr.DPI_CAPTURA} dpi")


# --- main ------------------------------------------------------------------

def main():
    print("=" * 74)
    print("GPRv2 - vivo_rapido.py contra vivo.py")
    print("=" * 74)
    curva = cargar_curva_vco(VCO_CSV)
    T, t0, r = 80e-3, 0.013, 1.20
    texto = generar_stream(curva, T, t0, [(r, 0.0)], segundos=25.0, ruido=0.02)
    print(f"stream sintetico: {len(texto)/1e6:.2f} MB, 25 s, Tprf {T*1e3:.0f} ms, "
          f"blanco a {r:.2f} m")

    probar_remuestreo(curva)
    probar_ajuste()
    probar_pico_subbin()
    probar_lector(texto)
    probar_punta_a_punta(curva, texto, r)
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="gprv2_verif_")
    try:
        archivos = probar_archivos(texto, tmp)
        probar_cadena_offline(curva, archivos, r)
        probar_captura(curva, texto, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 74)
    if fallas:
        print(f"FALLARON {len(fallas)}: " + ", ".join(fallas))
        raise SystemExit(1)
    print("Todo bien: vivo_rapido.py mide lo mismo que vivo.py.")


if __name__ == "__main__":
    main()
