"""
Croquis de topologia del mixer IQ con baluns Marchand y diodos Schottky.

    python mixer_iq.py   ->   mixer_iq.png

OJO: es un croquis de TOPOLOGIA, no un diseno. No estan calculadas las
dimensiones de las lineas acopladas, ni las redes de adaptacion, ni las
terminaciones de IF. El balun va dibujado como bloque a proposito: su
estructura interna sale del diseno de las lineas acopladas, y ponerla aca
sugeriria una precision que este dibujo no tiene.

Topologia representada: mixer SIMPLEMENTE balanceado por canal, que es la
que corresponde a UN balun por mixer (dos en total). El LO entra por el
puerto no balanceado del balun y la RF por la toma central, que es un punto
de tension nula para el LO diferencial. La FI sale del nodo comun de los
diodos.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle

LW = 1.6
NEGRO = "black"


def caja(ax, x, y, w, h, titulo, sub="", fs=10):
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, linewidth=1.8,
                           edgecolor=NEGRO, facecolor="white", zorder=3))
    ax.text(x, y + (0.14 if sub else 0.0), titulo, fontsize=fs,
            fontweight="bold", ha="center", va="center", zorder=4)
    if sub:
        ax.text(x, y - 0.20, sub, fontsize=7.5, ha="center", va="center",
                color="#333333", zorder=4)


def cable(ax, puntos):
    ax.plot([p[0] for p in puntos], [p[1] for p in puntos], color=NEGRO,
            lw=LW, zorder=2, solid_capstyle="round")


def nodo(ax, x, y):
    ax.add_patch(Circle((x, y), 0.055, facecolor=NEGRO, edgecolor=NEGRO,
                        zorder=5))


def puerto(ax, x, y, texto, lado="izq"):
    ax.add_patch(Circle((x, y), 0.085, facecolor="white", edgecolor=NEGRO,
                        lw=1.6, zorder=5))
    dx, ha = (-0.20, "right") if lado == "izq" else (0.20, "left")
    ax.text(x + dx, y, texto, fontsize=9, fontweight="bold", ha=ha,
            va="center", zorder=5)


def diodo(ax, x0, y, largo=0.62):
    """Diodo apuntando a la derecha: anodo a la izquierda, catodo a la derecha."""
    h = 0.17
    xt = x0 + largo * 0.70
    ax.add_patch(Polygon([[x0, y - h], [x0, y + h], [xt, y]], closed=True,
                         facecolor=NEGRO, edgecolor=NEGRO, zorder=4))
    ax.plot([xt, xt], [y - h, y + h], color=NEGRO, lw=2.4, zorder=4)


# ===========================================================================

fig, ax = plt.subplots(figsize=(13.5, 8.6))

Y_I, Y_Q = 6.55, 3.05          # centro de cada canal
XB, WB, HB = 6.25, 3.10, 1.60  # balun: centro x, ancho, alto

# --- Entradas ----------------------------------------------------------------
puerto(ax, 0.55, 8.35, "RF")
ax.text(0.55, 8.02, "de la antena RX", fontsize=7.5, ha="center", color="#333333")
caja(ax, 2.45, 8.35, 2.00, 0.90, "Divisor", "en fase (Wilkinson)")

puerto(ax, 0.55, 0.85, "LO")
ax.text(0.55, 0.52, "del splitter", fontsize=7.5, ha="center", color="#333333")
caja(ax, 2.45, 0.85, 2.00, 0.90, "Híbrido 90°", "")

cable(ax, [(0.64, 8.35), (1.45, 8.35)])
cable(ax, [(0.64, 0.85), (1.45, 0.85)])

# --- Reparto de RF (por arriba) y de LO (por izquierda) ----------------------
cable(ax, [(3.45, 8.55), (XB, 8.55), (XB, Y_I + HB / 2)])                # RF -> I
cable(ax, [(3.45, 8.15), (3.90, 8.15), (3.90, 4.35), (XB, 4.35),
           (XB, Y_Q + HB / 2)])                                          # RF -> Q
cable(ax, [(3.45, 1.05), (4.15, 1.05), (4.15, Y_I), (XB - WB / 2, Y_I)])  # LO 0°
cable(ax, [(3.45, 0.65), (4.55, 0.65), (4.55, Y_Q), (XB - WB / 2, Y_Q)])  # LO 90°

ax.text(3.62, 1.20, "0°", fontsize=9, ha="left", va="bottom", style="italic")
ax.text(3.62, 0.32, "90°", fontsize=9, ha="left", va="bottom", style="italic")

# --- Un canal ----------------------------------------------------------------
for y0, nombre in ((Y_I, "I"), (Y_Q, "Q")):
    caja(ax, XB, y0, WB, HB, "Balun Marchand", "2 × λ/4 acopladas", fs=10)
    ax.text(XB - WB / 2 + 0.10, y0 + 0.16, "LO", fontsize=8, ha="left",
            va="bottom", style="italic", zorder=6)
    ax.text(XB + 0.12, y0 + HB / 2 - 0.16, "RF  (toma central)", fontsize=8,
            ha="left", va="top", style="italic", zorder=6)

    xd = XB + WB / 2
    for signo, etq in ((+1, "+"), (-1, "−")):
        yb = y0 + signo * 0.45
        cable(ax, [(xd, yb), (xd + 0.45, yb)])
        diodo(ax, xd + 0.45, yb)
        cable(ax, [(xd + 1.07, yb), (xd + 1.75, yb), (xd + 1.75, y0)])
        ax.text(xd + 0.16, yb + 0.13, etq, fontsize=10, fontweight="bold",
                ha="center", va="bottom")

    nodo(ax, xd + 1.75, y0)
    cable(ax, [(xd + 1.75, y0), (xd + 2.30, y0)])
    caja(ax, xd + 3.05, y0, 1.50, 0.85, "LPF", "saca RF y LO")
    cable(ax, [(xd + 3.80, y0), (xd + 4.45, y0)])
    puerto(ax, xd + 4.45, y0, f"FI {nombre}", lado="der")

    ax.text(xd + 1.75, y0 - 0.64, "nodo común", fontsize=7.5, ha="center",
            va="top", color="#333333", style="italic")

ax.text(0.25, 6.35,
        "El LO llega en contrafase a los dos\n"
        "diodos y se cancela en el nodo común;\n"
        "la RF llega en fase por la toma\n"
        "central y es la que mezcla.",
        fontsize=8.5, ha="left", va="top", style="italic", color="#333333")

ax.text(13.35, 0.10,
        "Croquis de topología. No están calculadas las líneas acopladas, "
        "las redes de adaptación ni las terminaciones de FI.",
        fontsize=8, color="#333333", style="italic", ha="right")

ax.set_xlim(0, 13.5)
ax.set_ylim(0, 9.3)
ax.axis("off")
ax.set_title("Mixer IQ — baluns Marchand y diodos Schottky BAT15-099R",
             fontsize=13.5, fontweight="bold", pad=2)

plt.tight_layout()
plt.savefig("mixer_iq.png", dpi=200)
print("Generado: mixer_iq.png")
