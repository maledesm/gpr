"""
Grafico de la curva de sintonia del VCO: frecuencia de salida vs tension de
entrada, con la sensibilidad dF/dV en el eje derecho.

    python grafico_vco.py   ->   vco_frecuencia_vs_tension.png
"""

import csv
import os

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.signal import savgol_filter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.chdir(os.path.dirname(os.path.abspath(__file__)))

V_MAX_USO = 3.000          # tope de tension que se le permite al DAC

AZUL   = "#1560BD"
NARANJA = "#E8710A"
VERDE  = "#2E9E45"


def num(s):
    s = (s or "").strip()
    return float(s.replace(",", ".")) if s else np.nan


V, F = [], []
with open("Caracteristica VCO.csv", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        V.append(num(r["Vin"]))
        F.append(num(r["Freq"]))
V, F = np.array(V), np.array(F)

f_de_v = PchipInterpolator(V, F)
vv = np.linspace(V.min(), V.max(), 800)
ff = f_de_v(vv)

# Sensibilidad dF/dV.
#
# La derivada cruda arrastra la cuantizacion de la medicion: la frecuencia esta
# redondeada a 1 MHz y los pasos son de 100 mV, asi que cada punto tiene +-10
# MHz/V de incertidumbre en la pendiente. PCHIP pasa exactamente por todos los
# puntos, con lo cual su derivada NO limpia ese ruido -- lo amplifica. Sin
# suavizar, el grafico muestra ondulaciones que son del instrumento y no del
# VCO, y exagera el rango de sensibilidad.
#
# Savitzky-Golay sobre una ventana de ~0.4 V: promedia localmente con un
# polinomio de grado 2, asi que atenua el ruido sin achatar la tendencia.
dfdv_crudo = np.gradient(ff, vv)
ventana = int(0.4 / (vv[1] - vv[0])) | 1          # impar, como pide savgol
dfdv = savgol_filter(dfdv_crudo, ventana, 2)

v1 = min(V.max(), V_MAX_USO)
f0, f1 = float(f_de_v(V.min())), float(f_de_v(v1))
bw = f1 - f0

fig, ax = plt.subplots(figsize=(12, 7))

ax.axvspan(V.min(), v1, color=VERDE, alpha=0.09, zorder=0)
ax.text((V.min() + v1) / 2, F.min() + 30,
        f"Rango utilizado:  {V.min():.2f} – {v1:.2f} V\n"
        f"{f0:.0f} – {f1:.0f} MHz   (BW {bw:.0f} MHz)",
        ha="center", va="bottom", fontsize=11, color="#1a6b2a", fontweight="bold")

ax.plot(vv, ff, "-", color=AZUL, lw=3.5, zorder=3, label="Curva de sintonía (PCHIP)")
ax.plot(V, F, "o", ms=8, color=AZUL, mec="white", mew=1.6, zorder=4,
        label=f"Medido — {len(V)} puntos cada 100 mV")

ax.set_xlabel("Tensión de entrada del VCO  [V]", fontsize=14, fontweight="bold")
ax.set_ylabel("Frecuencia de salida  [MHz]", fontsize=14, fontweight="bold",
              color=AZUL)
ax.tick_params(axis="y", labelcolor=AZUL, labelsize=12)
ax.tick_params(axis="x", labelsize=12)
ax.grid(True, alpha=0.3, lw=1)
ax.set_xlim(V.min() - 0.05, V.max() + 0.05)

# Sensibilidad en el eje derecho: es lo que explica por que hace falta
# predistorsionar la rampa.
ax2 = ax.twinx()
ax2.plot(vv, dfdv, "--", color=NARANJA, lw=3, alpha=0.9,
         label="Sensibilidad  dF/dV  (suavizada)")
ax2.set_ylabel("Sensibilidad  dF/dV  [MHz/V]", fontsize=14, fontweight="bold",
               color=NARANJA)
ax2.tick_params(axis="y", labelcolor=NARANJA, labelsize=12)
ax2.set_ylim(0, max(dfdv) * 1.35)

ax.set_title("Curva de sintonía del VCO\n"
             f"Sensibilidad entre {dfdv.min():.0f} y {dfdv.max():.0f} MHz/V "
             f"— varía {dfdv.max()/dfdv.min():.1f} a 1",
             fontsize=15, fontweight="bold", pad=14)

h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=11, framealpha=0.95)

ax.annotate(f"{F.min():.0f} MHz", xy=(V.min(), F.min()), xytext=(0.25, F.min() + 15),
            fontsize=11, color=AZUL, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=AZUL, lw=1.8))
ax.annotate(f"{F.max():.0f} MHz", xy=(V.max(), F.max()), xytext=(2.55, F.max() - 90),
            fontsize=11, color=AZUL, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=AZUL, lw=1.8))

plt.tight_layout()
plt.savefig("vco_frecuencia_vs_tension.png", dpi=160)

print(f"Puntos            : {len(V)}  ({V.min():.3f} a {V.max():.3f} V)")
print(f"Frecuencia        : {F.min():.0f} a {F.max():.0f} MHz")
print(f"Sensibilidad      : {dfdv.min():.0f} a {dfdv.max():.0f} MHz/V "
      f"({dfdv.max()/dfdv.min():.2f} a 1)")
print(f"Rango usado       : {V.min():.3f} a {v1:.3f} V -> BW {bw:.0f} MHz")
print(f"Resolucion radar  : {3e10/(2*bw*1e6):.1f} cm")
print("\nGenerado: vco_frecuencia_vs_tension.png")
