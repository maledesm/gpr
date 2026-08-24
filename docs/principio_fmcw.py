"""
Principio de funcionamiento del FMCW, SIN efecto Doppler.

    python principio_fmcw.py   ->   principio_fmcw.png

Tres graficos alineados verticalmente en el tiempo:

    (a) frecuencia transmitida y recibida
    (b) diferencia entre ambas
    (c) tension a la salida del mezclador

Es la version para blancos ESTATICOS, que es nuestro caso: el GPR no se mueve
respecto del suelo. La diferencia con las figuras que se ven en la bibliografia
de radar automotriz es que sin Doppler la frecuencia de beat de la rampa de
subida y la de bajada son IGUALES. Con Doppler el corrimiento se suma en una y
se resta en la otra, y de esa asimetria se despeja la velocidad; aca no hay nada
que despejar, con lo cual una sola rampa alcanza para medir distancia.

Todo es generico y adimensional: no hay frecuencias ni tiempos concretos, solo
f_min, f_max, B, tau y T_m.
"""

import numpy as np
from scipy.integrate import cumulative_trapezoid

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

# --- Parametros del dibujo ---------------------------------------------------
# Valores elegidos para que la figura se lea bien, no para representar el
# sistema real. En el radar de verdad tau/T_m es MUCHISIMO mas chico (un blanco
# a 1 m con T_m de 50 ms da tau/T_m del orden de 1e-7): dibujado a escala, la
# senal recibida taparia por completo a la transmitida.
F_MIN, F_MAX = 1.0, 2.0
B  = F_MAX - F_MIN
TM = 1.0                      # periodo de la triangular
TAU = 0.09                    # retardo de ida y vuelta
S = 2.0 * B / TM              # pendiente de la rampa
F_BEAT = S * TAU

# La frecuencia de beat real es varios ordenes por debajo de la portadora, asi
# que el panel (c) va con un factor de escala: si se dibujara a escala, en la
# ventana entera entraria menos de un ciclo.
ESCALA_C = 133.0

AZUL   = "#1560BD"
ROJO   = "#D62728"
VERDE  = "#2E9E45"
VIOLETA = "#7B3FA0"
GRIS   = "#9A9A9A"


def triangulo(t):
    """Triangular periodica entre F_MIN y F_MAX, subiendo primero."""
    u = np.mod(t, TM)
    return np.where(u <= TM / 2, F_MIN + S * u, F_MAX - S * (u - TM / 2))


t = np.linspace(0, 2 * TM, 40000)
tx = triangulo(t)
rx = triangulo(t - TAU)               # misma rampa, retrasada. Sin Doppler no
                                      # hay corrimiento vertical, solo temporal.
dif = np.abs(tx - rx)

# Salida del mezclador: se integra la frecuencia instantanea para obtener la
# fase. Asi los tramos donde la diferencia cae a cero aparecen solos como un
# estiramiento de la senal, sin tener que dibujarlos aparte.
fase = 2 * np.pi * ESCALA_C * cumulative_trapezoid(dif, t, initial=0.0)
u_mezcla = np.cos(fase)

# ===========================================================================

fig, (ax1, ax2, ax3) = plt.subplots(
    3, 1, figsize=(11, 9), sharex=True,
    gridspec_kw={"height_ratios": [3.0, 1.5, 1.5], "hspace": 0.16})

# Lineas guia verticales: son las que hacen visible que los tres graficos
# comparten el eje de tiempo.
for ax in (ax1, ax2, ax3):
    for k in (0.5, 1.0, 1.5, 2.0):
        ax.axvline(k * TM, color=GRIS, ls=":", lw=1.3, zorder=1)
    ax.tick_params(labelsize=12)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)

# --- (a) frecuencia transmitida y recibida ---------------------------------
ax1.plot(t, tx, "-",  color=AZUL, lw=3.0, zorder=3, label="Señal transmitida")
ax1.plot(t, rx, "--", color=ROJO, lw=3.0, zorder=3, label="Señal recibida")

ax1.set_ylim(F_MIN - 0.30 * B, F_MAX + 0.22 * B)
ax1.set_yticks([F_MIN, F_MAX])
ax1.set_yticklabels([r"$f_{min}$", r"$f_{max}$"], fontsize=15)
ax1.set_ylabel("frecuencia", fontsize=14, fontweight="bold")
ax1.legend(loc="lower right", fontsize=12, framealpha=0.95, ncol=2)

# Ancho de banda B
ax1.add_patch(FancyArrowPatch((0.035, F_MIN), (0.035, F_MAX),
                              arrowstyle="<->", mutation_scale=16,
                              color="black", lw=1.6, zorder=5))
ax1.text(0.055, (F_MIN + F_MAX) / 2, r"$B$", fontsize=16, va="center")

# Retardo tau, medido entre las dos rampas a una misma altura. Va abajo a la
# izquierda para no chocar con la flecha de f_beat.
niv = F_MIN + 0.28 * B
t_tx = (niv - F_MIN) / S
ax1.add_patch(FancyArrowPatch((t_tx, niv), (t_tx + TAU, niv),
                              arrowstyle="<->", mutation_scale=14,
                              color="black", lw=1.6, zorder=5))
ax1.text(t_tx + TAU / 2, niv - 0.055 * B, r"$\tau$", fontsize=16,
         ha="center", va="top")

# Frecuencia de beat, medida en vertical sobre un tramo estable de la subida
t_b = 0.44 * TM
ax1.add_patch(FancyArrowPatch((t_b, triangulo(t_b - TAU)), (t_b, triangulo(t_b)),
                              arrowstyle="<->", mutation_scale=14,
                              color="black", lw=1.6, zorder=5))
ax1.annotate(r"$f_{beat}$", xy=(t_b, triangulo(t_b) - F_BEAT / 2),
             xytext=(t_b + 0.16 * TM, F_MIN + 0.42 * B), fontsize=15,
             arrowprops=dict(arrowstyle="->", color="black", lw=1.5))

# --- (b) diferencia de frecuencias -----------------------------------------
ax2.plot(t, dif, "-", color=VERDE, lw=3.0, zorder=3)
ax2.axhline(F_BEAT, color=GRIS, ls="--", lw=1.5, zorder=2)
ax2.set_ylim(-0.12 * F_BEAT, 1.75 * F_BEAT)
ax2.set_yticks([0, F_BEAT])
ax2.set_yticklabels(["0", r"$f_{beat}$"], fontsize=15)
ax2.set_ylabel("diferencia", fontsize=14, fontweight="bold")

# Sin Doppler los dos tramos valen lo mismo: conviene decirlo explicito.
ax2.text(0.25 * TM, F_BEAT * 1.22, r"$f_{dif\ subida}$", fontsize=13,
         ha="center", color=VERDE, fontweight="bold")
ax2.text(0.78 * TM, F_BEAT * 1.22, r"$f_{dif\ bajada}$", fontsize=13,
         ha="center", color=VERDE, fontweight="bold")
ax2.annotate("", xy=(0.40 * TM, F_BEAT * 1.13), xytext=(0.63 * TM, F_BEAT * 1.13),
             arrowprops=dict(arrowstyle="<->", color=VERDE, lw=1.6))
ax2.text(0.515 * TM, F_BEAT * 1.30, "iguales", fontsize=12, ha="center",
         color=VERDE, style="italic")

# --- (c) salida del mezclador ----------------------------------------------
ax3.plot(t, u_mezcla, "-", color=VIOLETA, lw=1.6, zorder=3)
ax3.set_ylim(-1.6, 1.6)
ax3.set_yticks([])
ax3.set_ylabel("U", fontsize=15, fontweight="bold", rotation=0, labelpad=18,
               va="center")
ax3.set_xlabel("tiempo", fontsize=14, fontweight="bold")

ax3.set_xlim(0, 2 * TM)
ax3.set_xticks([0.5 * TM, TM, 1.5 * TM, 2 * TM])
ax3.set_xticklabels([r"$T_m/2$", r"$T_m$", r"$3T_m/2$", r"$2T_m$"], fontsize=15)

# --- Etiquetas (a) (b) (c) --------------------------------------------------
# Adentro del panel y no al costado: afuera chocaban con el titulo del eje.
for ax, etq in ((ax1, "(a)"), (ax2, "(b)"), (ax3, "(c)")):
    ax.text(0.012, 0.95, etq, transform=ax.transAxes, fontsize=16,
            fontweight="bold", ha="left", va="top")

fig.suptitle("Principio del radar FMCW — blancos estáticos, sin efecto Doppler",
             fontsize=16, fontweight="bold", y=0.97)
# subplots_adjust y no tight_layout: las flechas son FancyArrowPatch y
# tight_layout no las sabe medir, avisa que el resultado puede salir mal.
fig.subplots_adjust(left=0.135, right=0.975, top=0.905, bottom=0.085, hspace=0.16)
plt.savefig("principio_fmcw.png", dpi=170)

print("Generado: principio_fmcw.png")
print(f"  tau/T_m = {TAU/TM:.3f}   f_beat/B = {F_BEAT/B:.3f}")
print(f"  ancho de cada muesca en (b) = tau = {TAU:.3f}  (arranca en el vertice)")
