"""
Diagrama en bloques del GPR FMCW.

    python diagrama_bloques.py   ->   diagrama_bloques.png

Estilo sobrio para informe y presentacion: cajas blancas, borde negro, esquinas
vivas. Sin codigo de colores ni marcas de estado, para que se pueda imprimir en
blanco y negro y proyectar sin depender del color.

Es la version de UN canal, que es el alcance de la tesis. El mixer IQ queda
como ampliacion posible: el PCM1808 es estereo, asi que el camino para el
segundo canal ya existe en el hardware.

El ESP32-C3 va como un solo bloque alto a la izquierda para que se vea que
atiende las DOS puntas de la cadena: genera la rampa por I2C y digitaliza el
beat por I2S. Esa doble funcion es la que obliga al sincronismo entre el
barrido y el reloj de muestreo.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

LW_CAJA = 1.8
LW_LINEA = 1.6

# nombre -> (x, y, ancho, alto, titulo, subtitulo)
CAJAS = {
    "esp":   (1.35, 3.30, 1.80, 4.30, "ESP32-C3", "I²C + I²S"),
    "pc":    (1.35, 0.40, 1.80, 0.75, "PC", "Python"),

    "dac":   (4.15, 5.00, 1.70, 0.90, "MCP4725", "DAC 12 bit"),
    "amp":   (6.30, 5.00, 1.30, 0.90, "AMP", "×5"),
    "vco":   (8.45, 5.00, 1.70, 0.90, "VCO", "1 – 2 GHz"),
    "att":   (10.55, 5.00, 1.30, 0.90, "−3 dB", ""),
    "split": (12.55, 5.00, 1.70, 0.90, "Splitter", ""),
    "antx":  (14.85, 5.00, 1.70, 0.90, "Antena TX", ""),

    "suelo": (14.85, 3.30, 1.70, 0.95, "Suelo", "blanco enterrado"),

    "anrx":  (14.85, 1.55, 1.70, 0.90, "Antena RX", ""),
    "lna":   (12.60, 1.55, 1.40, 0.90, "LNA", ""),
    "mix":   (10.40, 1.55, 1.70, 0.90, "Mixer", ""),
    "lpf":   (8.30, 1.55, 1.40, 0.90, "LPF", "antialias"),
    "pcm":   (5.90, 1.55, 1.85, 0.90, "PCM1808", "ADC 24 bit"),
}


def borde(n, lado):
    x, y, w, h = CAJAS[n][:4]
    return {"der": (x + w / 2, y), "izq": (x - w / 2, y),
            "arr": (x, y + h / 2), "aba": (x, y - h / 2)}[lado]


def flecha(ax, p1, p2, texto="", dx=0.0, dy=0.09, ls="-"):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=13,
                                 color="black", lw=LW_LINEA, linestyle=ls,
                                 shrinkA=2, shrinkB=2, zorder=2))
    if texto:
        ax.text((p1[0] + p2[0]) / 2 + dx, (p1[1] + p2[1]) / 2 + dy, texto,
                fontsize=8.5, ha="center", va="bottom", color="black",
                style="italic")


def ruta(ax, puntos, texto="", texto_xy=None):
    """Flecha en angulo recto: una diagonal larga cruzando el dibujo se lee
    peor que dos tramos ortogonales."""
    ax.plot([p[0] for p in puntos[:-1]], [p[1] for p in puntos[:-1]],
            color="black", lw=LW_LINEA, zorder=2, solid_capstyle="round")
    ax.add_patch(FancyArrowPatch(puntos[-2], puntos[-1], arrowstyle="-|>",
                                 mutation_scale=13, color="black", lw=LW_LINEA,
                                 shrinkA=0, shrinkB=2, zorder=2))
    if texto:
        ax.text(*texto_xy, texto, fontsize=8.5, color="black", style="italic",
                ha="center", va="bottom")


fig, ax = plt.subplots(figsize=(15.5, 6.2))

# --- Cajas -------------------------------------------------------------------
for x, y, w, h, titulo, sub in CAJAS.values():
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, linewidth=LW_CAJA,
                           edgecolor="black", facecolor="white", zorder=3))
    ax.text(x, y + (0.13 if sub else 0.0), titulo, fontsize=11,
            fontweight="bold", ha="center", va="center", zorder=4)
    if sub:
        ax.text(x, y - 0.21, sub, fontsize=8, ha="center", va="center",
                color="#333333", zorder=4)

# --- Generación del barrido y transmisión ------------------------------------
ax.text(3.30, 5.68, "GENERACIÓN DEL BARRIDO  ·  TRANSMISIÓN", fontsize=10,
        fontweight="bold", ha="left")

flecha(ax, (borde("esp", "der")[0], 5.00), borde("dac", "izq"), "I²C")
flecha(ax, borde("dac", "der"), borde("amp", "izq"), "0 – 3 V")
flecha(ax, borde("amp", "der"), borde("vco", "izq"))
flecha(ax, borde("vco", "der"), borde("att", "izq"))   # la banda ya está en la caja
flecha(ax, borde("att", "der"), borde("split", "izq"))
flecha(ax, borde("split", "der"), borde("antx", "izq"))

# --- Oscilador local ---------------------------------------------------------
ruta(ax, [borde("split", "aba"), (12.55, 3.30), (10.40, 3.30),
          borde("mix", "arr")], "LO", (11.48, 3.40))

# --- Propagación -------------------------------------------------------------
flecha(ax, borde("antx", "aba"), borde("suelo", "arr"), ls=(0, (4, 2.5)))
flecha(ax, borde("suelo", "aba"), borde("anrx", "arr"), "eco", dx=0.42, dy=-0.06,
       ls=(0, (4, 2.5)))

# --- Recepción y digitalización ----------------------------------------------
ax.text(5.90, 0.72, "RECEPCIÓN  ·  DIGITALIZACIÓN", fontsize=10,
        fontweight="bold", ha="left")

flecha(ax, borde("anrx", "izq"), borde("lna", "der"))
flecha(ax, borde("lna", "izq"), borde("mix", "der"), "RF")
flecha(ax, borde("mix", "izq"), borde("lpf", "der"), "$f_{beat}$")
flecha(ax, borde("lpf", "izq"), borde("pcm", "der"))
flecha(ax, borde("pcm", "izq"), (borde("esp", "der")[0], 1.55), "I²S")
flecha(ax, borde("esp", "aba"), borde("pc", "arr"), "USB", dx=0.85, dy=-0.12)

# --- Sincronismo -------------------------------------------------------------
ax.add_patch(FancyArrowPatch((2.60, 4.60), (2.60, 1.95), arrowstyle="<->",
                             mutation_scale=11, color="black", lw=1.2,
                             linestyle=(0, (3, 2)), zorder=5))
ax.text(2.78, 3.30, "sincronismo\nbarrido ↔ muestreo", fontsize=8,
        va="center", ha="left", style="italic")

ax.text(16.05, 0.03,
        "Ampliación posible: mixer IQ sobre el 2º canal del PCM1808, que ya es estéreo.",
        fontsize=8, color="#333333", style="italic", ha="right")

ax.set_xlim(0, 16.1)
ax.set_ylim(-0.05, 6.15)
ax.axis("off")
ax.set_title("GPR FMCW — diagrama en bloques", fontsize=14, fontweight="bold",
             pad=2)

plt.tight_layout()
plt.savefig("diagrama_bloques.png", dpi=200)
print("Generado: diagrama_bloques.png")
