"""
GPRv2 - Armonicos del VCO: donde caen en RF y donde caen a la salida del mezclador
=================================================================================

Figura para la seccion "Distorsion armonica del VCO" de la tesis
(redaccion/figuras/vco/armonicos_fantasmas.png).

(a) Frecuencia instantanea de la fundamental y de los armonicos 2 y 3 a lo largo de un
    periodo de la triangular (Tprf 100 ms), con la banda medida en Max Hold
    (988-1991 MHz). Es esquematica: el barrido se dibuja lineal entre los extremos
    medidos (el VCO real no es lineal, pero los extremos son los que importan para el
    filtro).
(b) Lo que llega a banda base: el batido de la placa a 1 m (medido el 2026-09-28) y sus
    fantasmas en n*f_b. Niveles de la simulacion de simulaciones_meep/armonicos
    (blanco puntual, mezclador multiplicador, 2o armonico del Max Hold, 3o supuesto a
    -15 dBc).

Ademas imprime los numeros que usa la seccion (fraccion de rampa contaminada y peso
de la ventana de Hann).

Uso:  python armonicos_mezclador.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "..", "..", "redaccion", "figuras", "vco", "armonicos_fantasmas.png")

F_MIN, F_MAX = 988e6, 1991e6        # Max Hold 2026-11-02, captura mas llena
T_PRF = 100e-3                      # periodo de la triangular
HZ_POR_M = 138.5                    # 2*B/(c*T_r), B ~ 1039 MHz, T_r = 50 ms
F_PLACA = 509.0                     # placa a 1 m, 2026-09-28 (Hz)
NIVEL = {1: 0.0, 2: -23.0, 3: -33.5}  # dB respecto del batido (simulacion, blanco puntual)
F_LIMPIA = 2400.0                   # banda limpia del diezmado del firmware

AZUL, ROJO, VIOLETA = "#2a78d6", "#d64545", "#7a4fb8"
TINTA, TINTA2, GRIS, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e2dc"
COLOR = {1: AZUL, 2: ROJO, 3: VIOLETA}


def frac_hann(x):
    """Fraccion de la amplitud coherente de un tono que aporta el tramo [0, x] de una
    ventana de Hann (x en fraccion de rampa)."""
    return x - np.sin(2 * np.pi * x) / (2 * np.pi)


def numeros():
    B = F_MAX - F_MIN
    print(f"banda medida {F_MIN/1e6:.0f}-{F_MAX/1e6:.0f} MHz, B = {B/1e6:.0f} MHz")
    print(f"2*f_min = {2*F_MIN/1e6:.0f} MHz  ->  banda de transicion f_max..2f_min = "
          f"{(2*F_MIN - F_MAX)/1e6:+.0f} MHz")
    x0 = (F_MAX / 2 - F_MIN) / B
    print(f"fraccion de rampa con 2f(t) < f_max: {100*x0:.2f} %  "
          f"(Hann: {20*np.log10(frac_hann(x0)):.0f} dB)")
    for fs in (2.1e9, 2.2e9, 2.3e9, 2.5e9):
        x = (fs / 2 - F_MIN) / B
        print(f"  filtro que llega a su atenuacion en {fs/1e9:.1f} GHz: tramo sin atenuar "
              f"{100*x:5.1f} % de la rampa, peso Hann {20*np.log10(frac_hann(x)):6.1f} dB")
    for fmin in (1050e6, 1100e6):
        b = F_MAX - fmin
        print(f"  f_min = {fmin/1e6:.0f} MHz: transicion {F_MAX/1e6:.0f}-{2*fmin/1e6:.0f} MHz, "
              f"B = {b/1e6:.0f} MHz, resolucion {3e8/(2*b)*100:.1f} cm "
              f"(contra {3e8/(2*B)*100:.1f} cm)")
    for n in (1, 2, 3):
        print(f"  n={n}: {n*F_PLACA:6.0f} Hz = {n*F_PLACA/HZ_POR_M:5.2f} m aparentes, "
              f"{NIVEL[n]:+.1f} dB")


def figura():
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRIS, "axes.labelcolor": TINTA2,
                         "xtick.color": TINTA2, "ytick.color": TINTA2})
    fig, (a, b) = plt.subplots(2, 1, figsize=(9, 7.6), gridspec_kw={"height_ratios": [1.25, 1]})

    # (a) frecuencia instantanea
    t = np.linspace(0, T_PRF, 2001)
    tri = 1 - np.abs(2 * t / T_PRF - 1)          # 0 -> 1 -> 0
    f = F_MIN + (F_MAX - F_MIN) * tri
    a.axhspan(F_MIN / 1e9, F_MAX / 1e9, color=AZUL, alpha=0.07, lw=0)
    for n in (1, 2, 3):
        a.plot(t * 1e3, n * f / 1e9, color=COLOR[n], lw=2)
    def rotulo(n, txt, tt=72):
        y = n * (F_MIN + (F_MAX - F_MIN) * (1 - abs(2 * tt / 100 - 1))) / 1e9
        a.text(tt + 1, y + 0.12, txt, color=TINTA, ha="left", va="bottom")
    rotulo(1, "fundamental $f(t)$", tt=24)
    rotulo(2, "2.º armónico $2f(t)$")
    rotulo(3, "3.er armónico $3f(t)$")
    a.axhline(2.0, color=TINTA2, ls="--", lw=1.2)
    a.text(20, 2.06, "corte del filtro de RF, ~2 GHz", color=TINTA2, ha="left", va="bottom",
           fontsize=9)
    a.text(1.5, (F_MIN + F_MAX) / 2e9, f"banda útil\n{F_MIN/1e6:.0f}–{F_MAX/1e6:.0f} MHz",
           color=AZUL, ha="left", va="center", fontsize=9)
    # tramo donde 2f(t) cae dentro de la banda util (cerca de los vertices de abajo)
    sol = 2 * f < F_MAX
    for lado in (t < T_PRF / 2, t > T_PRF / 2):
        m = sol & lado
        a.plot(t[m] * 1e3, 2 * f[m] / 1e9, color=ROJO, lw=6, alpha=0.5, solid_capstyle="butt")
    pct = f"{100*(F_MAX/2 - F_MIN)/(F_MAX - F_MIN):.1f}".replace(".", ",")
    a.annotate(f"$2f_{{\\min}}$ = {2*F_MIN/1e6:.0f} MHz < $f_{{\\max}}$: el 2.º armónico cae\n"
               f"en la banda útil durante el {pct} % de cada rampa",
               xy=(99.6, 2 * F_MIN / 1e9), xytext=(40, 1.02), color=ROJO, fontsize=9,
               arrowprops=dict(arrowstyle="->", color=ROJO, lw=1))
    a.set_xlim(0, 100)
    a.set_ylim(0.8, 6.2)
    a.set_xlabel("tiempo [ms]  (un período de la triangular)")
    a.set_ylabel("frecuencia instantánea [GHz]")
    a.set_title("(a) Lo que sale del VCO: cada armónico es otro chirp, $n$ veces más alto y más empinado",
                loc="left", fontsize=10, color=TINTA)
    a.grid(color=GRID, lw=0.6)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)

    # (b) banda base
    b.axvspan(0, F_LIMPIA, color=GRIS, alpha=0.08, lw=0)
    b.text(F_LIMPIA - 30, 2, "banda limpia del firmware (0–2400 Hz)", color=TINTA2,
           ha="right", va="bottom", fontsize=9)
    piso = -50
    for n in (1, 2, 3):
        x = n * F_PLACA
        b.plot([x, x], [piso, NIVEL[n]], color=COLOR[n], lw=2, solid_capstyle="round")
        b.plot(x, NIVEL[n], "o", ms=8, color=COLOR[n], mec="white", mew=2)
        rot = {1: "batido $f_b$\n(placa a 1 m)", 2: "fantasma $2f_b$", 3: "fantasma $3f_b$\n(3.º supuesto)"}[n]
        b.text(x + 40, NIVEL[n] + 1, f"{rot}\n{x:.0f} Hz, " + (f"{NIVEL[n]:.0f}".replace("-", "−") if n > 1 else "0") + " dB", color=TINTA,
               fontsize=9, va="bottom")
    b.set_xlim(0, 3000)
    b.set_ylim(piso, 12)
    b.set_xlabel("frecuencia de batido [Hz]")
    b.set_ylabel("nivel respecto del batido [dB]")
    b.set_title("(b) Lo que sale del mezclador: el armónico $n$ del LO bate con el $n$ del eco, en $n f_b$",
                loc="left", fontsize=10, color=TINTA)
    sec = b.secondary_xaxis("top", functions=(lambda h: h / HZ_POR_M, lambda m: m * HZ_POR_M))
    sec.set_xlabel("distancia aparente, sin calibrar [m]", color=TINTA2)
    sec.tick_params(colors=TINTA2)
    b.grid(color=GRID, lw=0.6)
    b.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(SALIDA, dpi=200, facecolor="white")
    print("figura:", os.path.normpath(SALIDA))


if __name__ == "__main__":
    numeros()
    figura()
