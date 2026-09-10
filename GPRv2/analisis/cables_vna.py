"""
GPRv2 - Caracterización de los cables coaxiles con el VNA
=========================================================

Lee los barridos del analizador (Agilent N9923A, 500-2500 MHz, 801 puntos,
en GPRv2/docs/CABLES/) y genera las figuras del capítulo de cables de la
tesis, más una tabla resumen por consola.

Qué cables son
--------------
El juego viejo son dos RG-58 (2,6 y 3 m, uno por antena); el nuevo es un
RG-213 de 1 m. De los dos RG-213 que se armaron solo se midió uno.

Los seis CSV se llaman ``RG213_*`` por un renombre, pero cuatro de ellos son
de los RG-58 viejos. Los nombres NO dicen el tipo: el tipo lo dice
MEDICIONES, acá abajo.

El retardo sale del rizado de S11, no de la fase
------------------------------------------------
El VNA exportó solo magnitud en dB: sin fase no hay retardo de grupo. Pero
el retardo se puede sacar igual del RIZADO de |S11|. El eco del extremo del
cable interfiere con el del conector de entrada, y esa interferencia ondula
|S11| con un período en frecuencia de 1/(2*tau). Una FFT sobre el eje de
frecuencia lo convierte en un pico en 2*tau -- es lo mismo que hace el modo
"dominio del tiempo" de un VNA, con la limitación de que sin fase se pierde
el signo de la reflexión (no se distingue un abierto de un corto).

Que el método mide lo que dice se ve en el cable de 3 m: el pico está en
28,53 ns y el segundo rebote en 57,05 ns, exactamente al doble. Es el eco
del extremo, no un artefacto.

La resolución en tiempo la fija el ancho barrido: 1/BW = 0,5 ns de ida y
vuelta con 2 GHz de span, o sea ~0,25 ns sobre tau. En un cable de 3 m eso
es 1,8 % del retardo; en uno de 1 m, 5 %. Los cables cortos se miden mal por
este camino: para el RG-213 conviene repetir la medición exportando fase.

Para los cálculos de diseño (offset, alcance) se usa el VF NOMINAL de
catálogo, no el despejado de acá: ver VF_NOMINAL.

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
DIR_CSV = os.path.join(AQUI, "..", "docs", "CABLES")
DIR_FIG = os.path.join(AQUI, "..", "..", "redaccion", "figuras", "cables")

C = 299792458.0

# Banda que barre el VCO del radar (medida, ver capítulo del VCO).
F_LO, F_HI = 943e6, 1982e6
F_CENTRO = 0.5 * (F_LO + F_HI)

# VF de catálogo. RG-58 y RG-213 comparten dieléctrico de polietileno
# sólido, así que comparten VF nominal. TODOS los cálculos de diseño usan
# estos valores, no los despejados del retardo medido.
VF_NOMINAL = {"RG-58": 0.66, "RG-213": 0.66}

# El juego viejo (los dos RG-58) contra el nuevo (RG-213).
MEDICIONES = [
    dict(tag="1m",   largo=1.00, tipo="RG-213", juego="nuevo",
         etiqueta="RG-213 nuevo, 1 m",   color="#1f77b4", ls="-"),
    dict(tag="3m",   largo=3.00, tipo="RG-58",  juego="viejo",
         etiqueta="RG-58 viejo, 3 m",    color="#d62728", ls="-"),
    dict(tag="2.6m", largo=2.60, tipo="RG-58",  juego="viejo",
         etiqueta="RG-58 viejo, 2,6 m",  color="#ff7f0e", ls="--"),
]

# El de 2,6 m pierde 65 % más por metro que su gemelo de 3 m y tiene el peor
# S11 de los tres. Se lo trata como cable con un conector en mal estado: se
# grafica, pero no se lo usa para caracterizar al RG-58.
TAG_SOSPECHOSO = "2.6m"


def leer_vna(ruta):
    """Devuelve (frecuencia [Hz], magnitud [dB]) de un CSV del N9923A.

    El archivo trae un encabezado de líneas '!' y los datos entre BEGIN y
    END. El campo '! DATA Freq,Return Loss' dice Return Loss aunque el
    barrido sea de transmisión: es la etiqueta por defecto del equipo, no
    describe la medición. Cuál es cuál lo dice el nombre del archivo.
    """
    f, db = [], []
    dentro = False
    with open(ruta, encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            linea = linea.strip()
            if linea == "BEGIN":
                dentro = True
                continue
            if linea == "END":
                break
            if dentro and linea:
                a, b = linea.split(",")
                f.append(float(a))
                db.append(float(b))
    return np.array(f), np.array(db)


def cargar(tag, param):
    return leer_vna(os.path.join(DIR_CSV, "RG213_%s_%s.csv" % (param, tag)))


def perfil_tiempo(f, s11_db, n_fft=1 << 18):
    """Pasa |S11(f)| al dominio del tiempo por FFT sobre el eje de frecuencia.

    Devuelve (t, perfil normalizado a 1). El pico cae en 2*tau: el ida y
    vuelta hasta el extremo del cable.

    Se le resta la media antes de transformar porque la reflexión media (el
    desadaptado de entrada, que no depende de la frecuencia) es la que
    genera la componente en t=0, y es órdenes de magnitud más grande que el
    rizado que interesa. La ventana de Hann baja los lóbulos laterales de
    esa componente residual, que si no tapan el eco.
    """
    lineal = 10 ** (s11_db / 20.0)
    x = (lineal - lineal.mean()) * np.hanning(len(lineal))
    espectro = np.abs(np.fft.rfft(x, n_fft))
    t = np.fft.rfftfreq(n_fft, f[1] - f[0])
    return t, espectro / espectro.max()


def medir_retardo(f, s11_db, t_min=2e-9):
    """Retardo de una vía [s] a partir del rizado de |S11|.

    Ignora todo lo anterior a t_min: ahí vive el residuo de la componente de
    continua y los rebotes internos del propio conector de entrada, no el
    eco del extremo.

    El pico se refina con una parábola sobre los tres puntos de alrededor;
    sin eso el resultado quedaría cuantizado al paso de la grilla de la FFT.
    """
    t, perfil = perfil_tiempo(f, s11_db)
    valido = t > t_min
    i = int(np.argmax(perfil[valido])) + int(np.flatnonzero(valido)[0])
    y0, y1, y2 = perfil[i - 1], perfil[i], perfil[i + 1]
    denom = y0 - 2 * y1 + y2
    corr = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    t_pico = t[i] + corr * (t[1] - t[0])
    return t_pico / 2.0


def ajuste_perdida(f, s12_db):
    """Ajusta la pérdida |S12| [dB] al modelo a*sqrt(f_GHz), por el origen.

    La pérdida por efecto pelicular del conductor crece con la raíz de la
    frecuencia y vale cero en continua, así que la recta tiene que pasar por
    el origen. Devuelve (a, b) con b el término constante del ajuste libre,
    solo para reportarlo.

    Por qué NO se usa el ajuste libre. Se probó primero con
    a*sqrt(f_GHz) + b, pensando en que b se quedara con lo que no depende
    del largo -- los dos conectores y el desadaptado. Con 500 a 2500 MHz de
    barrido, sqrt(f) y la constante están demasiado correlacionadas para
    separarse: b salió NEGATIVO en los tres cables (-0,17, -0,49 y -3,22 dB),
    que como pérdida de conector no existe. Lo que hacía era absorber la
    desviación respecto de la raíz e inflarle 'a' al cable.

    Forzado por el origen, en cambio, los números caen encima del catálogo:
    0,29 dB/m para el RG-213 (catálogo 0,28) y 0,52 para el RG-58 de 3 m
    (catálogo 0,53).

    Queda dicho lo que esto NO hace: la pérdida de los dos conectores sigue
    adentro del número, repartida en el largo del cable. Para separarla hay
    que medir DOS largos del MISMO cable y restar. Se tienen dos RG-58, pero
    el de 2,6 m es el del conector sospechado, así que esa resta no se puede
    hacer todavía.
    """
    raiz = np.sqrt(f / 1e9)
    perdida = -s12_db
    # Ajuste por el origen: a = <raiz, perdida> / <raiz, raiz>.
    a = float(raiz @ perdida / (raiz @ raiz))
    # El ajuste libre, solo para poder informar cuánto da b.
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
        ax1.plot(d["f"] / 1e6, d["s12"], color=d["color"], ls=d["ls"],
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
    """Pérdida de retorno: adaptación, y el rizado del que sale el retardo."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2),
                                   gridspec_kw=dict(width_ratios=[1.5, 1]))

    for d in datos:
        ax1.plot(d["f"] / 1e6, d["s11"], color=d["color"], ls=d["ls"],
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

    # El zoom es lo que hace visible el método: a cable más largo, rizado más
    # apretado. El período vale 1/(2*tau) exacto.
    lo, hi = 1400e6, 1600e6
    for d in datos:
        m = (d["f"] >= lo) & (d["f"] <= hi)
        paso = 1 / (2 * d["tau"]) / 1e6
        ax2.plot(d["f"][m] / 1e6, d["s11"][m], color=d["color"], ls=d["ls"],
                 lw=1.4,
                 label="%s\n$\\Delta f$ = %s MHz" % (d["etiqueta"], coma(paso, 1)))
    ax2.set_xlabel("Frecuencia [MHz]")
    ax2.set_ylabel(r"$|S_{11}|$ [dB]")
    ax2.set_title("Zoom: el rizado del eco\n"
                  r"período $\Delta f = 1/(2\tau)$")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7.5, loc="lower right")

    fig.tight_layout()
    return fig


def figura_tiempo(datos):
    """Dominio del tiempo: el eco del extremo, de donde sale el retardo."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    for d in datos:
        t, perfil = perfil_tiempo(d["f"], d["s11"])
        db = 20 * np.log10(np.maximum(perfil, 1e-6))
        ax1.plot(t * 1e9, db, color=d["color"], ls=d["ls"], lw=1.2,
                 label="%s\n$2\\tau$ = %s ns" % (d["etiqueta"],
                                                 coma(2e9 * d["tau"])))
        ax1.plot(2 * d["tau"] * 1e9, 0, "o", color=d["color"], ms=6)
    ax1.set_xlim(0, 70)
    ax1.set_ylim(-40, 6)
    ax1.set_xlabel("Tiempo de ida y vuelta [ns]")
    ax1.set_ylabel("Amplitud normalizada [dB]")
    ax1.set_title(r"Respuesta al impulso desde $|S_{11}|$"
                  "\n" r"el círculo marca el eco del extremo, en $2\tau$")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=7.5, loc="lower left", ncol=3, columnspacing=0.8,
               handlelength=1.2)

    # El segundo rebote del cable de 3 m: está exactamente al doble, y es la
    # prueba de que el pico es el extremo del cable y no un artefacto.
    d3 = [d for d in datos if d["tag"] == "3m"][0]
    ax1.annotate(r"2º rebote, en $4\tau$", xy=(4 * d3["tau"] * 1e9, -16),
                 xytext=(40, -5), fontsize=8.5, color="#d62728", ha="right",
                 arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.2))

    # Retardo contra largo, con la recta del VF nominal de fábrica.
    L_ref = np.linspace(0, 3.4, 50)
    ax2.plot(L_ref, L_ref / (0.66 * C) * 1e9, "k--", lw=1.3,
             label="VF = 0,66 de catálogo\n(5,05 ns/m)")
    for d in datos:
        marca = "s" if d["tag"] == TAG_SOSPECHOSO else "o"
        ax2.plot(d["largo"], d["tau"] * 1e9, marca, color=d["color"], ms=10,
                 label="%s\nVF = %s" % (d["etiqueta"],
                                        coma(d["largo"] / (d["tau"] * C), 3)))
    ax2.set_xlabel("Largo físico del cable [m]")
    ax2.set_ylabel(r"Retardo de una vía $\tau$ [ns]")
    ax2.set_title("Retardo medido contra el de catálogo\n"
                  "debajo de la recta = más rápido que el nominal")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=7.5, loc="upper left")
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

    # Los dos juegos reales, con el mismo cable al LO (0,5 m) en los dos:
    # D = L_TX + L_RX - L_LO.
    # (D neto, texto, color, dónde va el texto)
    escenarios = [
        (5.1, "juego viejo\nRG-58 de 3 y 2,6 m", "#d62728", (3.30, 4.75)),
        (1.5, "juego nuevo\ndos RG-213 de 1 m",  "#1f77b4", (2.60, 1.05)),
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
        if d["tag"] == TAG_SOSPECHOSO:
            etiq = "el de 2,6 m: %s dB/m\n(conector sospechado)" % coma(alfa, 3)
            estilo = dict(ls="--", lw=1.5)
        else:
            etiq = "%s: %s dB/m" % (d["tipo"], coma(alfa, 3))
            estilo = dict(ls="-", lw=1.8)
        ax2.plot(L, 2 * alfa * L, color=d["color"], label=etiq, **estilo)
    ax2.set_xlabel("Largo de cada cable de antena [m]")
    ax2.set_ylabel("Pérdida de los dos cables (TX + RX) [dB]")
    ax2.set_title("Atenuación del cableado a %d MHz\n"
                  "la del cable de RX empeora la figura de ruido"
                  % round(F_CENTRO / 1e6))
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8.5, loc="upper left")
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
        f, s11 = cargar(m["tag"], "S11")
        _, s12 = cargar(m["tag"], "S12")
        a, b = ajuste_perdida(f, s12)
        d.update(f=f, s11=s11, s12=s12, ajuste_a=a, ajuste_b=b,
                 tau=medir_retardo(f, s11),
                 alfa=lambda fr, a=a, L=m["largo"]: a * np.sqrt(fr / 1e9) / L)
        datos.append(d)
    return datos


def resumen(datos):
    print("=" * 74)
    print("CARACTERIZACIÓN DE CABLES CON EL VNA  (%.0f-%.0f MHz, 801 puntos)"
          % (500, 2500))
    print("=" * 74)

    print("\nRETARDO (del rizado de S11; VF de catálogo = 0,66 para los dos tipos)")
    print("-" * 74)
    print("%-22s %8s %8s %9s | %9s %9s" %
          ("cable", "2tau[ns]", "tau[ns]", "ns/m", "L@VF0,66", "VF@L nom"))
    for d in datos:
        vf_nom = VF_NOMINAL[d["tipo"]]
        largo_electrico = d["tau"] * vf_nom * C
        vf_despejado = d["largo"] / (d["tau"] * C)
        print("%-22s %8.3f %8.3f %9.3f | %8.3f m %9.3f" %
              (d["etiqueta"], 2e9 * d["tau"], 1e9 * d["tau"],
               1e9 * d["tau"] / d["largo"], largo_electrico, vf_despejado))
    print("\n  La resolución del método es 1/BW = 0,50 ns sobre 2*tau, o sea")
    print("  +-0,25 ns sobre tau: 1,8 % en el cable de 3 m y 5,1 % en el de 1 m.")

    print("\nPÉRDIDA DE INSERCIÓN  (ajuste |S12| = a*sqrt(f_GHz) + b)")
    print("-" * 74)
    print("%-22s %9s %9s %11s %11s" %
          ("cable", "a[dB]", "b libre", "alfa@1GHz", "alfa@%.2fGHz" % (F_CENTRO / 1e9)))
    for d in datos:
        a1 = d["alfa"](np.array([1e9]))[0]
        ac = d["alfa"](np.array([F_CENTRO]))[0]
        print("%-22s %9.3f %9.3f %8.3f dB/m %8.3f dB/m" %
              (d["etiqueta"], d["ajuste_a"], d["ajuste_b"], a1, ac))
    print("\n  b es lo que no depende del largo: los dos conectores y el")
    print("  desadaptado. alfa es el cable solo, ya sin ese término.")

    print("\nADAPTACIÓN")
    print("-" * 74)
    for d in datos:
        m = en_banda(d["f"])
        peor = d["s11"][m].max()
        vswr = (1 + 10 ** (peor / 20.0)) / (1 - 10 ** (peor / 20.0))
        print("%-22s peor |S11| en banda = %6.2f dB  (VSWR %.2f)" %
              (d["etiqueta"], peor, vswr))

    print("\nOFFSET DE DISTANCIA CON VF NOMINAL 0,66  (%.3f m por metro de coaxil)"
          % (1 / (2 * 0.66)))
    print("-" * 74)
    for D, txt in [(5.1, "juego viejo: RG-58 de 3 + 2,6 m, LO de 0,5"),
                   (1.5, "juego nuevo: dos RG-213 de 1 m, LO de 0,5")]:
        print("  D = %4.2f m -> offset %5.2f m   (%s)" % (D, D / (2 * 0.66), txt))
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
