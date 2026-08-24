"""
Diagrama en bloques del GPR FMCW.

    python diagrama_bloques.py   ->   diagrama_bloques.png

Borde lleno    = ya funciona en el banco
Borde punteado = en diseño o pendiente

Es la version de UN canal, que es el alcance de la tesis. El mixer IQ queda
como ampliacion posible al final: el PCM1808 es estereo, asi que el camino
para el segundo canal ya existe en el hardware.

El ESP32-C3 va como un solo bloque alto a la izquierda para que se vea que
atiende las DOS puntas de la cadena: genera la rampa por I2C y digitaliza el
beat por I2S. Esa doble funcion es la que obliga al sincronismo entre el
barrido y el reloj de muestreo.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

DIGITAL = "#1560BD"      # control y datos
RF      = "#D95F02"      # radiofrecuencia
BANDA   = "#2E9E45"      # banda base analogica
TIERRA  = "#8C6239"
GRIS    = "#5A5A5A"
ROJO    = "#B0182C"

W, H = 1.85, 0.95

# nombre -> (x, y, ancho, alto, titulo, subtitulo, color, ya_funciona)
CAJAS = {
    "esp":   (1.45, 4.85, 2.00, 6.30, "ESP32-C3", "I²C + I²S", DIGITAL, True),
    "pc":    (1.45, 0.75, 2.00, 0.95, "PC", "Python", DIGITAL, True),

    "dac":   (4.30, 7.45, W, H, "MCP4725", "DAC 12 bit", DIGITAL, True),
    "amp":   (6.55, 7.45, 1.45, H, "AMP", "×5", RF, True),
    "vco":   (8.65, 7.45, W, H, "VCO", "1 – 2 GHz", RF, True),
    "att":   (10.70, 7.45, 1.40, H, "−3 dB", "aislación", RF, False),
    "split": (12.60, 7.45, W, H, "Splitter", "", RF, False),
    "antx":  (14.95, 7.45, W, H, "Antena TX", "", RF, False),

    "suelo": (14.95, 4.85, W, 1.15, "Suelo", "blanco enterrado", TIERRA, False),

    "anrx":  (14.95, 2.35, W, H, "Antena RX", "", RF, False),
    "lna":   (12.15, 2.35, 1.55, H, "LNA", "", RF, False),
    "mix":   (9.70, 2.35, W, H, "Mixer", "", RF, False),
    "lpf":   (7.25, 2.35, 1.55, H, "LPF", "antialias", BANDA, False),
    "pcm":   (4.60, 2.35, W, 1.10, "PCM1808", "ADC 24 bit", BANDA, True),
}


def borde(n, lado):
    x, y, w, h = CAJAS[n][:4]
    return {"der": (x + w / 2, y), "izq": (x - w / 2, y),
            "arr": (x, y + h / 2), "aba": (x, y - h / 2)}[lado]


def ruta(ax, puntos, texto="", texto_xy=None, color=GRIS, ls="-"):
    """Flecha en angulo recto: una diagonal larga cruzando el dibujo se lee
    peor que dos tramos ortogonales."""
    ax.plot([p[0] for p in puntos[:-1]], [p[1] for p in puntos[:-1]],
            color=color, lw=2.1, ls=ls, zorder=2, solid_capstyle="round")
    ax.add_patch(FancyArrowPatch(puntos[-2], puntos[-1], arrowstyle="-|>",
                                 mutation_scale=17, color=color, lw=2.1,
                                 linestyle=ls, shrinkA=0, shrinkB=2, zorder=2))
    if texto:
        ax.text(*texto_xy, texto, fontsize=9.5, color=color, style="italic",
                ha="center", va="center")


def flecha(ax, p1, p2, texto="", dx=0.0, dy=0.20, color=GRIS, ls="-", fs=9.5):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=17,
                                 color=color, lw=2.1, linestyle=ls,
                                 shrinkA=2, shrinkB=2, zorder=2))
    if texto:
        ax.text((p1[0] + p2[0]) / 2 + dx, (p1[1] + p2[1]) / 2 + dy, texto,
                fontsize=fs, ha="center", va="bottom", color=GRIS, style="italic")


fig, ax = plt.subplots(figsize=(16.5, 9.4))

# --- Cajas -------------------------------------------------------------------
for x, y, w, h, titulo, sub, color, hecho in CAJAS.values():
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=2.6, edgecolor=color, linestyle="-" if hecho else (0, (4, 2.5)),
        facecolor=color, alpha=0.13, zorder=3))
    ax.text(x, y + (0.15 if sub else 0.0), titulo, fontsize=12.5,
            fontweight="bold", ha="center", va="center", color=color, zorder=4)
    if sub:
        ax.text(x, y - 0.25, sub, fontsize=9, ha="center", va="center",
                color=GRIS, zorder=4)

# --- Generación del barrido y transmisión ------------------------------------
ax.text(3.40, 8.12, "GENERACIÓN DEL BARRIDO  ·  TRANSMISIÓN", fontsize=11,
        fontweight="bold", color=RF, ha="left")

flecha(ax, (borde("esp", "der")[0], 7.45), borde("dac", "izq"), "I²C")
flecha(ax, borde("dac", "der"), borde("amp", "izq"), "rampa\n0 – 3 V", dy=0.14)
flecha(ax, borde("amp", "der"), borde("vco", "izq"), "sintonía")
flecha(ax, borde("vco", "der"), borde("att", "izq"), "1 – 2 GHz")
flecha(ax, borde("att", "der"), borde("split", "izq"))
flecha(ax, borde("split", "der"), borde("antx", "izq"))

# --- Oscilador local ---------------------------------------------------------
ruta(ax, [borde("split", "aba"), (12.60, 5.45), (9.70, 5.45), borde("mix", "arr")],
     "LO", (11.15, 5.68), color=RF)

# --- Propagación -------------------------------------------------------------
flecha(ax, borde("antx", "aba"), borde("suelo", "arr"), color=TIERRA,
       ls=(0, (5, 3)))
flecha(ax, borde("suelo", "aba"), borde("anrx", "arr"), "eco", dx=0.60, dy=-0.10,
       color=TIERRA, ls=(0, (5, 3)))

# --- Recepción y digitalización ----------------------------------------------
ax.text(5.90, 1.28, "RECEPCIÓN  ·  DIGITALIZACIÓN", fontsize=11,
        fontweight="bold", color=BANDA, ha="left")

flecha(ax, borde("anrx", "izq"), borde("lna", "der"))
flecha(ax, borde("lna", "izq"), borde("mix", "der"), "RF")
flecha(ax, borde("mix", "izq"), borde("lpf", "der"), "$f_{beat}$")
flecha(ax, borde("lpf", "izq"), borde("pcm", "der"))
flecha(ax, borde("pcm", "izq"), (borde("esp", "der")[0], 2.35), "I²S")
flecha(ax, borde("esp", "aba"), borde("pc", "arr"), "USB · trama\nbinaria + CRC",
       dx=1.85, dy=-0.32)

# --- Sincronismo -------------------------------------------------------------
ax.add_patch(FancyArrowPatch((2.72, 6.90), (2.72, 2.95), arrowstyle="<->",
                             mutation_scale=14, color=ROJO, lw=1.8,
                             linestyle=(0, (3, 2)), zorder=5))
ax.text(2.92, 4.90, "sincronismo\nbarrido ↔ muestreo\n(pendiente)", fontsize=8.8,
        color=ROJO, va="center", ha="left", style="italic")

# --- Leyenda -----------------------------------------------------------------
for i, (txt, ls) in enumerate([("ya funciona en el banco", "-"),
                               ("en diseño o pendiente", (0, (4, 2.5)))]):
    ax.add_patch(FancyBboxPatch((7.55 + i * 4.30, 8.62), 0.52, 0.30,
                                boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=2.4, edgecolor=GRIS, linestyle=ls,
                                facecolor="none"))
    ax.text(8.22 + i * 4.30, 8.77, txt, fontsize=10, va="center", color=GRIS)

ax.text(16.35, 0.15,
        "Ampliación posible: mixer IQ sobre el 2º canal del PCM1808, que ya es estéreo.",
        fontsize=9, color=GRIS, style="italic", ha="right")

ax.set_xlim(0, 16.5)
ax.set_ylim(-0.05, 9.25)
ax.axis("off")
ax.set_title("GPR FMCW — diagrama en bloques", fontsize=17, fontweight="bold",
             pad=2)

plt.tight_layout()
plt.savefig("diagrama_bloques.png", dpi=160)
print("Generado: diagrama_bloques.png")
