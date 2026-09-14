"""
GPRv2 - Caracterización de los cables coaxiles con el VNA
=========================================================

Lee los barridos de dos puertos del analizador (Keysight/Agilent N9923A
FieldFox, 500-2500 MHz, 801 puntos, archivos .s2p en GPRv2/docs/CABLES/) y
genera las figuras del capítulo de cables de la tesis, más una tabla resumen
por consola.

Qué cables son
--------------
El juego viejo son dos RG-58 (3 m y 2,6 m, uno por antena); el nuevo son dos
RG-213 de 1 m (A y B). Los largos de MEDICIONES son los nominales.

Cómo se midió (2026-09-14)
--------------------------
QuickCal de 2 puertos completa, con las cuatro trazas en pantalla antes de
calibrar: el .s2p rellena con ceros los S-parámetros que no están corregidos
ni mostrados. IF BW 1 kHz, 4 promedios, potencia High. Los encabezados dicen
S11(ON Q)S21(ON Q)S12(ON Q)S22(ON Q): los cuatro corregidos por QuickCal.

La medición anterior (2026-09-10, los CSV RG213_S11_* / RG213_S12_* de la
misma carpeta) se exportó en CSV y trajo solo magnitud. Esos archivos se
conservan como registro, pero este script ya no los usa.

El retardo sale de la pendiente de la fase de S21
-------------------------------------------------
tau = -d(fase)/d(omega), ajustando una recta a la fase desenrollada sobre los
2 GHz de barrido. Con 801 puntos la resolución es de picosegundos, contra los
+-250 ps del método que había que usar sin fase (el rizado de |S11|, que
queda calculado en retardo_rizado() para compararlos).

El desenrollado es seguro: el cable más largo gira 13 grados de fase entre
puntos, lejos de los 180 donde np.unwrap se confunde.

Para los cálculos de diseño (offset, alcance) se sigue usando el VF NOMINAL
de catálogo (VF_NOMINAL): el VF medido depende del largo físico, que hay que
medir con cinta.

Uso
---
    python cables_vna.py
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Rutas relativas a ESTE archivo, no al directorio actual.
AQUI = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(AQUI, "..", "docs", "CABLES")
DIR_FIG = os.path.join(AQUI, "..", "..", "redaccion", "figuras", "cables")

C = 299792458.0

# Banda que barre el VCO del radar (medida, ver capítulo del VCO).
F_LO, F_HI = 943e6, 1982e6
F_CENTRO = 0.5 * (F_LO + F_HI)

# VF de catálogo. RG-58 y RG-213 comparten dieléctrico de polietileno
# sólido, así que comparten VF nominal. TODOS los cálculos de diseño usan
# estos valores.
VF_NOMINAL = {"RG-58": 0.66, "RG-213": 0.66}

# El splitter y el mezclador se conectan directamente, sin cable: el camino
# del LO son los ~5 cm de la unión. Aporta 0,25 ns = 3,8 cm de offset, muy
# por debajo de la resolución de 14,4 cm, así que D es en la práctica
# L_TX + L_RX. Se lo deja explícito igual, para que se vea que se consideró.
L_LO = 0.05

# largo: NOMINAL, no medido con cinta. El VF despejado depende de este número
# uno a uno: 2 cm de error en un cable de 1 m son 2 % de VF.
MEDICIONES = [
    dict(archivo="RG213_A_1m.s2p", largo=1.00, tipo="RG-213", juego="nuevo",
         etiqueta="RG-213 A, 1 m",      color="#1f77b4", ls="-"),
    dict(archivo="RG213_B_1m.s2p", largo=1.00, tipo="RG-213", juego="nuevo",
         etiqueta="RG-213 B, 1 m",      color="#17becf", ls="-."),
    dict(archivo="RG58_3m.s2p",    largo=3.00, tipo="RG-58",  juego="viejo",
         etiqueta="RG-58 viejo, 3 m",   color="#d62728", ls="-"),
    dict(archivo="RG58_2m6.s2p",   largo=2.60, tipo="RG-58",  juego="viejo",
         etiqueta="RG-58 viejo, 2,6 m", color="#ff7f0e", ls="--"),
]

# El de 2,6 m atenúa el doble por metro que su gemelo de 3 m y es el peor
# adaptado. Se lo grafica, pero no se lo usa para caracterizar al RG-58.
ARCHIVO_SOSPECHOSO = "RG58_2m6.s2p"


def leer_s2p(ruta):
    """Devuelve (f [Hz], dict con S11, S21, S12, S22 complejos) de un .s2p.

    Touchstone de dos puertos: cada fila es f y los cuatro parámetros en el
    orden S11 S21 S12 S22. El FieldFox los guarda en dB/ángulo ('# Hz S DB
    R 50') salvo que la traza esté en Smith o Polar, que los guarda en
    real/imaginario. Se aceptan los tres formatos de Touchstone para no
    depender de en qué formato quedó la pantalla al guardar.
    """
    formato = None
    filas = []
    with open(ruta, encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("!"):
                continue
            if linea.startswith("#"):
                partes = linea[1:].upper().split()
                formato = next(p for p in partes if p in ("DB", "MA", "RI"))
                unidad = partes[0]
                continue
            filas.append([float(x) for x in linea.split()])
    d = np.array(filas)
    f = d[:, 0] * {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}[unidad]

    s = {}
    for k, nombre in enumerate(("S11", "S21", "S12", "S22")):
        a, b = d[:, 1 + 2 * k], d[:, 2 + 2 * k]
        if formato == "DB":
            s[nombre] = 10 ** (a / 20.0) * np.exp(1j * np.deg2rad(b))
        elif formato == "MA":
            s[nombre] = a * np.exp(1j * np.deg2rad(b))
        else:
            s[nombre] = a + 1j * b
    return f, s


def db(x):
    return 20 * np.log10(np.abs(x))


def retardo_fase(f, s21):
    """Retardo de una vía [s] de la pendiente de la fase de S21.

    Ajusta una recta a la fase desenrollada contra omega; el retardo es menos
    la pendiente. Devuelve (tau, residuo rms en grados): el residuo mide
    cuánto se aparta la fase de un retardo puro, o sea la dispersión del
    cable más el ruido de la medición.
    """
    omega = 2 * np.pi * f
    fase = np.unwrap(np.angle(s21))
    p = np.polyfit(omega, fase, 1)
    residuo = np.rad2deg(np.std(fase - np.polyval(p, omega)))
    return -p[0], residuo


def perfil_tiempo(f, s11, n_fft=1 << 16):
    """Respuesta al impulso de S11 complejo: (t [s], amplitud en dB, 0 dB = pico).

    Con fase esto sí es la respuesta al impulso (de banda pasante, 500 a
    2500 MHz): cada discontinuidad del cable aparece como un pico en su
    tiempo de ida y vuelta. Va con ifft y no con fft porque el retardo en
    frecuencia es e^(-j*omega*t): con fft los ecos caen en tiempos negativos.
    """
    x = np.fft.ifft(s11 * np.hanning(len(s11)), n_fft)
    t = np.fft.fftfreq(n_fft, f[1] - f[0])
    m = t >= 0
    a = np.abs(x[m])
    return t[m], 20 * np.log10(a / a.max() + 1e-12)


def retardo_rizado(f, s11, t_min=2e-9):
    """Retardo de una vía [s] del rizado de |S11|, el método de cuando no había fase.

    El eco del extremo interfiere con el del conector de entrada y ondula
    |S11| con período 1/(2*tau); la FFT de esa ondulación da un pico en
    2*tau. Se conserva para comparar contra retardo_fase(): su resolución es
    1/BW = 0,5 ns sobre 2*tau.
    """
    lineal = np.abs(s11)
    x = (lineal - lineal.mean()) * np.hanning(len(lineal))
    n_fft = 1 << 18
    espectro = np.abs(np.fft.rfft(x, n_fft))
    t = np.fft.rfftfreq(n_fft, f[1] - f[0])
    valido = t > t_min
    i = int(np.argmax(espectro[valido])) + int(np.flatnonzero(valido)[0])
    y0, y1, y2 = espectro[i - 1], espectro[i], espectro[i + 1]
    denom = y0 - 2 * y1 + y2
    corr = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    return (t[i] + corr * (t[1] - t[0])) / 2.0


def ajuste_perdida(f, s21_db):
    """Ajusta la pérdida |S21| [dB] al modelo a*sqrt(f_GHz), por el origen.

    La pérdida por efecto pelicular del conductor crece con la raíz de la
    frecuencia y vale cero en continua, así que la recta tiene que pasar por
    el origen. Devuelve (a, b) con b el término constante del ajuste libre,
    solo para reportarlo.

    Por qué NO se usa el ajuste libre: con 500 a 2500 MHz de barrido, sqrt(f)
    y la constante están demasiado correlacionadas para separarse, y b sale
    negativo, que como pérdida de conector no existe. Forzado por el origen,
    los números caen sobre el catálogo.

    La pérdida de los dos conectores sigue adentro del número, repartida en
    el largo del cable.
    """
    raiz = np.sqrt(f / 1e9)
    perdida = -s21_db
    a = float(raiz @ perdida / (raiz @ raiz))
    A = np.column_stack([raiz, np.ones_like(raiz)])
    (_, b), *_ = np.linalg.lstsq(A, perdida, rcond=None)
    return a, b


def en_banda(f):
    return (f >= F_LO) & (f <= F_HI)


def marcar_banda(ax):
    ax.axvspan(F_LO / 1e6, F_HI / 1e6, color="0.85", zorder=0)
    ax.text(F_CENTRO / 1e6, ax.get_ylim()[1], " banda del radar ",
            ha="center", va="top", fontsize=8, color="0.35")


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------

def coma(x, dec=2):
    """Número con coma decimal, que es como se escribe en la tesis."""
    return ("%.*f" % (dec, x)).replace(".", ",")


def figura_insercion(datos):
    """Pérdida de inserción: total como se mide, y normalizada por metro."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    for d in datos:
        ax1.plot(d["f"] / 1e6, d["s21_db"], color=d["color"], ls=d["ls"],
                 lw=1.3, label=d["etiqueta"])
    ax1.set_xlabel("Frecuencia [MHz]")
    ax1.set_ylabel(r"$|S_{21}|$ [dB]")
    ax1.set_title("Pérdida de inserción total\n(cable + los dos conectores)")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8, loc="lower left")
    ax1.set_ylim(-6, 0.3)
    marcar_banda(ax1)

    f_ref = np.linspace(500e6, 2500e6, 200)
    for d in datos:
        ax2.plot(d["f"] / 1e6, d["alfa"](d["f"]), color=d["color"], ls=d["ls"],
                 lw=1.4, label=d["etiqueta"])
    # Catálogo, como k*sqrt(f_GHz) anclado al valor a 1 GHz.
    for k, tipo, col in [(0.53, "RG-58", "#d62728"), (0.28, "RG-213", "#1f77b4")]:
        ax2.plot(f_ref / 1e6, k * np.sqrt(f_ref / 1e9), color=col, ls=":",
                 lw=2.0, label="%s de catálogo" % tipo)
    ax2.set_xlabel("Frecuencia [MHz]")
    ax2.set_ylabel(r"$\alpha$ [dB/m]")
    ax2.set_title("Atenuación por metro\n"
                  r"(ajuste $a\sqrt{f}$ por el origen; incluye conectores)")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8, loc="upper left")
    ax2.set_ylim(0, 1.8)
    marcar_banda(ax2)

    fig.tight_layout()
    return fig


def figura_retorno(datos):
    """Pérdida de retorno: adaptación, y el rizado que dejan los dos conectores."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2),
                                   gridspec_kw=dict(width_ratios=[1.5, 1]))

    for d in datos:
        ax1.plot(d["f"] / 1e6, d["s11_db"], color=d["color"], ls=d["ls"],
                 lw=0.8, label=d["etiqueta"])
    ax1.set_xlabel("Frecuencia [MHz]")
    ax1.set_ylabel(r"$|S_{11}|$ [dB]")
    ax1.set_title("Pérdida de retorno, barrido completo")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8, loc="lower right")
    ax1.set_ylim(-70, 0)
    marcar_banda(ax1)

    # Eje derecho en VSWR: son los mismos datos, leídos como los lee la hoja
    # de datos de un cable.
    der = ax1.twinx()
    der.set_ylim(ax1.get_ylim())
    ticks = [-70, -30, -20, -14, -10]
    der.set_yticks(ticks)
    der.set_yticklabels([coma((1 + 10 ** (t / 20.0)) / (1 - 10 ** (t / 20.0)))
                         for t in ticks])
    der.set_ylabel("VSWR")

    # A cable más largo, rizado más apretado: el período vale 1/(2*tau), con
    # el tau de la pendiente de fase.
    lo, hi = 1400e6, 1600e6
    for d in datos:
        m = (d["f"] >= lo) & (d["f"] <= hi)
        paso = 1 / (2 * d["tau"]) / 1e6
        ax2.plot(d["f"][m] / 1e6, d["s11_db"][m], color=d["color"], ls=d["ls"],
                 lw=1.4,
                 label="%s\n$\\Delta f$ = %s MHz" % (d["etiqueta"], coma(paso, 1)))
    ax2.set_xlabel("Frecuencia [MHz]")
    ax2.set_ylabel(r"$|S_{11}|$ [dB]")
    ax2.set_title("Zoom: el rizado de los dos conectores\n"
                  r"período $\Delta f = 1/(2\tau)$")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7, loc="lower right")

    fig.tight_layout()
    return fig


def figura_tiempo(datos):
    """Dominio del tiempo y retardo: el eco del extremo, y tau contra el largo."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    for d in datos:
        t, perfil = perfil_tiempo(d["f"], d["s11"])
        ax1.plot(t * 1e9, perfil, color=d["color"], ls=d["ls"], lw=1.1,
                 label="%s\n$2\\tau$ = %s ns" % (d["etiqueta"],
                                                 coma(2e9 * d["tau"])))
        ax1.plot(2 * d["tau"] * 1e9, 3, "v", color=d["color"], ms=7)
    ax1.set_xlim(0, 35)
    ax1.set_ylim(-40, 6)
    ax1.set_xlabel("Tiempo de ida y vuelta [ns]")
    ax1.set_ylabel("Amplitud normalizada [dB]")
    ax1.set_title(r"Respuesta al impulso de $S_{11}$ (con fase)"
                  "\n" r"el triángulo marca $2\tau$ de la pendiente de fase de $S_{21}$")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=7, loc="lower left", ncol=2, columnspacing=0.8,
               handlelength=1.4)

    # Retardo contra largo: el de la fase (lleno) y el del rizado de |S11|
    # (hueco), contra la recta del VF nominal de fábrica.
    L_ref = np.linspace(0, 3.4, 50)
    ax2.plot(L_ref, L_ref / (0.66 * C) * 1e9, "k--", lw=1.3,
             label="VF = 0,66 de catálogo (5,05 ns/m)")
    for d in datos:
        marca = "s" if d["archivo"] == ARCHIVO_SOSPECHOSO else "o"
        ax2.plot(d["largo"], d["tau"] * 1e9, marca, color=d["color"], ms=9,
                 label="%s: VF = %s" % (d["etiqueta"],
                                        coma(d["largo"] / (d["tau"] * C), 3)))
        ax2.plot(d["largo"], d["tau_rizado"] * 1e9, marca, ms=13, mfc="none",
                 mec=d["color"], mew=1.2)
    ax2.plot([], [], "o", ms=9, color="0.4", label="lleno: pendiente de fase")
    ax2.plot([], [], "o", ms=13, mfc="none", mec="0.4",
             label=r"hueco: rizado de $|S_{11}|$ (sin fase)")
    ax2.set_xlabel("Largo nominal del cable [m]")
    ax2.set_ylabel(r"Retardo de una vía $\tau$ [ns]")
    ax2.set_title("Retardo medido contra el de catálogo\n"
                  "VF despejado con el largo nominal")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7, loc="upper left")
    ax2.set_xlim(0, 3.4)
    ax2.set_ylim(0, 19)

    fig.tight_layout()
    return fig


def figura_impacto(datos):
    """Lo que los cables le cuestan al radar: offset de distancia y atenuación."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    vf = VF_NOMINAL["RG-213"]
    D = np.linspace(0, 7, 100)
    ax1.plot(D, D / (2 * vf), "k-", lw=1.8, zorder=2,
             label=r"$d_{off} = D/(2\,VF)$, VF = 0,66")
    ax1.axhline(0.144, color="0.55", ls=":", lw=1.3, zorder=1)
    ax1.text(6.9, 0.22, "resolución del radar, 14,4 cm",
             fontsize=8, color="0.4", ha="right")

    # Los dos juegos reales. D = L_TX + L_RX - L_LO, con el mismo L_LO en los
    # dos porque el splitter y el mezclador van conectados directamente.
    # (D neto, texto, color, dónde va el texto)
    escenarios = [
        (3.0 + 2.6 - L_LO, "juego viejo\nRG-58 de 3 y 2,6 m", "#d62728", (3.30, 4.55)),
        (1.0 + 1.0 - L_LO, "juego nuevo\ndos RG-213 de 1 m",  "#1f77b4", (3.05, 1.35)),
    ]
    for d_neto, txt, col, (tx, ty) in escenarios:
        y = d_neto / (2 * vf)
        ax1.plot(d_neto, y, "o", color=col, ms=10, zorder=3)
        ax1.annotate("%s\n%s m" % (txt, coma(y)), xy=(d_neto, y),
                     xytext=(tx, ty), fontsize=8.5, color=col,
                     arrowprops=dict(arrowstyle="->", color=col, lw=1.2))
    ax1.set_xlabel(r"Coaxil neto $D = L_{TX} + L_{RX} - L_{LO}$ [m]")
    ax1.set_ylabel("Offset de distancia [m]")
    ax1.set_title("El retardo se lee como distancia\n"
                  "0,76 m de error por cada metro de coaxil")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8.5, loc="upper left")
    ax1.set_xlim(0, 7)
    ax1.set_ylim(0, 5.8)

    # Atenuación de ida y vuelta: el cable de TX y el de RX, en el centro de
    # la banda. Es lo que el cableado le saca a la SNR.
    L = np.linspace(0, 3.5, 100)
    for d in datos:
        alfa = d["alfa"](np.array([F_CENTRO]))[0]
        if d["archivo"] == ARCHIVO_SOSPECHOSO:
            etiq = "RG-58 de 2,6 m: %s dB/m\n(conector sospechado)" % coma(alfa, 3)
            estilo = dict(ls="--", lw=1.5)
        else:
            etiq = "%s: %s dB/m" % (d["etiqueta"], coma(alfa, 3))
            estilo = dict(ls=d["ls"], lw=1.8)
        ax2.plot(L, 2 * alfa * L, color=d["color"], label=etiq, **estilo)
    ax2.set_xlabel("Largo de cada cable de antena [m]")
    ax2.set_ylabel("Pérdida de los dos cables (TX + RX) [dB]")
    ax2.set_title("Atenuación del cableado a %d MHz\n"
                  "la del cable de RX empeora la figura de ruido"
                  % round(F_CENTRO / 1e6))
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8, loc="upper left")
    ax2.set_xlim(0, 3.5)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def cargar_todo():
    datos = []
    for m in MEDICIONES:
        d = dict(m)
        f, s = leer_s2p(os.path.join(DIR_DATOS, m["archivo"]))
        tau, residuo = retardo_fase(f, s["S21"])
        s21_db = db(s["S21"])
        a, b = ajuste_perdida(f, s21_db)
        d.update(f=f, s11=s["S11"], s21=s["S21"],
                 s11_db=db(s["S11"]), s21_db=s21_db,
                 reciprocidad_db=float(np.max(np.abs(s21_db - db(s["S12"])))),
                 tau=tau, residuo_fase=residuo,
                 tau_rizado=retardo_rizado(f, s["S11"]),
                 ajuste_a=a, ajuste_b=b,
                 alfa=lambda fr, a=a, L=m["largo"]: a * np.sqrt(fr / 1e9) / L)
        datos.append(d)
    return datos


def resumen(datos):
    print("=" * 78)
    print("CARACTERIZACIÓN DE CABLES CON EL VNA  (%.0f-%.0f MHz, %d puntos, .s2p)"
          % (datos[0]["f"][0] / 1e6, datos[0]["f"][-1] / 1e6, len(datos[0]["f"])))
    print("=" * 78)

    print("\nRETARDO  (largo NOMINAL; VF de catálogo = 0,66)")
    print("-" * 78)
    print("%-20s %9s %9s %8s | %9s %9s | %8s" %
          ("cable", "tau fase", "tau riz.", "ns/m", "VF fase", "VF riz.", "res.fase"))
    for d in datos:
        print("%-20s %7.3f ns %7.3f ns %8.3f | %9.4f %9.4f | %5.2f deg" %
              (d["etiqueta"], 1e9 * d["tau"], 1e9 * d["tau_rizado"],
               1e9 * d["tau"] / d["largo"],
               d["largo"] / (d["tau"] * C), d["largo"] / (d["tau_rizado"] * C),
               d["residuo_fase"]))

    print("\nPÉRDIDA DE INSERCIÓN  (ajuste |S21| = a*sqrt(f_GHz), por el origen)")
    print("-" * 78)
    print("%-20s %9s %9s %11s %13s %9s" %
          ("cable", "a[dB]", "b libre", "alfa@1GHz", "alfa@%.2fGHz" % (F_CENTRO / 1e9),
           "|S21-S12|"))
    for d in datos:
        a1 = d["alfa"](np.array([1e9]))[0]
        ac = d["alfa"](np.array([F_CENTRO]))[0]
        print("%-20s %9.3f %9.3f %6.3f dB/m %8.3f dB/m %6.3f dB" %
              (d["etiqueta"], d["ajuste_a"], d["ajuste_b"], a1, ac,
               d["reciprocidad_db"]))

    print("\nADAPTACIÓN")
    print("-" * 78)
    for d in datos:
        m = en_banda(d["f"])
        peor = d["s11_db"][m].max()
        vswr = (1 + 10 ** (peor / 20.0)) / (1 - 10 ** (peor / 20.0))
        print("%-20s peor |S11| en banda = %6.2f dB  (VSWR %.2f)" %
              (d["etiqueta"], peor, vswr))

    print("\nOFFSET DE DISTANCIA")
    print("-" * 78)
    por_archivo = {d["archivo"]: d for d in datos}
    for archivos, L_nom, txt in [
            (("RG58_3m.s2p", "RG58_2m6.s2p"), 3.0 + 2.6, "juego viejo: RG-58 de 3 + 2,6 m"),
            (("RG213_A_1m.s2p", "RG213_B_1m.s2p"), 2.0, "juego nuevo: RG-213 A + B")]:
        tau_lo = L_LO / (0.66 * C)
        tau_med = sum(por_archivo[a]["tau"] for a in archivos) - tau_lo
        D = L_nom - L_LO
        print("  %-34s teórico %5.2f m | medido %5.2f m" %
              (txt, D / (2 * 0.66), C * tau_med / 2))
    print()


def main():
    os.makedirs(DIR_FIG, exist_ok=True)
    datos = cargar_todo()
    resumen(datos)

    figuras = [
        ("cables_insercion.png", figura_insercion),
        ("cables_retorno.png",   figura_retorno),
        ("cables_tiempo.png",    figura_tiempo),
        ("cables_impacto.png",   figura_impacto),
    ]
    for nombre, hacer in figuras:
        fig = hacer(datos)
        ruta = os.path.join(DIR_FIG, nombre)
        fig.savefig(ruta, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print("guardado: %s" % os.path.normpath(ruta))


if __name__ == "__main__":
    main()
