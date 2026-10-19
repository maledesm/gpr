"""
Repetibilidad del VCO: la curva nueva (2026-10-19) contra la vieja.

    python comparar_vco.py   ->   comparar_vco.png

La vieja tiene Vin medido con multimetro y la frecuencia redondeada a 1 MHz.
La nueva (2026-10-19, 15 °C de ambiente) tiene la frecuencia del contador,
a 10 kHz, y Vin medido con multimetro en todos los puntos. De 0,9 a 2,0 V la
frecuencia es la de una repeticion del mismo dia (dio 0,2 a 1,5 MHz por
encima de la primera pasada). La vieja no tiene temperatura anotada. Para
comparar en los mismos Vin, la vieja se interpola con PCHIP en los Vin de la
nueva. Diferencias menores a ~0,5 MHz estan dentro del redondeo de la vieja.

Lo que importa para la correccion de no linealidad no es la diferencia cruda:
un corrimiento constante se cancela (theta usa f - f(0)) y una pendiente
distinta solo escala el BW. Por eso el tercer panel le saca a la diferencia
su recta de ajuste: lo que queda es el cambio de FORMA.
"""

import csv
import os

import numpy as np
from scipy.interpolate import PchipInterpolator

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.chdir(os.path.dirname(os.path.abspath(__file__)))

VIEJA = "Caracteristica VCO.csv"
NUEVA = "Caracteristica VCO 2026-10-19.csv"
V_MAX_USO = 3.000          # rango que usa el radar

AZUL = "#1560BD"
NARANJA = "#E8710A"
VERDE = "#2E9E45"


def num(s):
    s = (s or "").strip()
    return float(s.replace(",", ".")) if s else np.nan


def leer(path):
    V, F = [], []
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            V.append(num(r["Vin"]))
            F.append(num(r["Freq"]))
    return np.array(V), np.array(F)


Vv, Fv = leer(VIEJA)
Vn, Fn = leer(NUEVA)

vieja_en_vn = PchipInterpolator(Vv, Fv, extrapolate=True)(Vn)
dif = Fn - vieja_en_vn

uso = Vn <= V_MAX_USO + 1e-9
a, b = np.polyfit(Vn[uso], dif[uso], 1)
forma = dif - (a * Vn + b)

bw_v = float(PchipInterpolator(Vv, Fv)(V_MAX_USO) - PchipInterpolator(Vv, Fv)(0.0))
bw_n = float(np.interp(V_MAX_USO, Vn, Fn) - np.interp(0.0, Vn, Fn))

print(f"BW 0-3 V:   vieja {bw_v:7.1f} MHz   nueva {bw_n:7.1f} MHz   "
      f"({bw_n - bw_v:+.1f} MHz, {100 * (bw_n / bw_v - 1):+.2f} %)")
print(f"Diferencia cruda (0-3 V): media {dif[uso].mean():+.2f} MHz, "
      f"min {dif[uso].min():+.2f}, max {dif[uso].max():+.2f}")
print(f"Recta de la diferencia: {b:+.2f} MHz + {a:+.2f} MHz/V")
print(f"Cambio de forma (0-3 V): rms {np.sqrt(np.mean(forma[uso] ** 2)):.2f} MHz, "
      f"pico {np.abs(forma[uso]).max():.2f} MHz")
for v, d, s in zip(Vn, dif, forma):
    print(f"  {v:4.1f} V   dif {d:+6.2f}   forma {s:+6.2f} MHz")

fig, ax = plt.subplots(3, 1, figsize=(9, 10), sharex=True,
                       gridspec_kw={"height_ratios": [2, 1, 1]})

ax[0].plot(Vv, Fv, "o-", color=AZUL, ms=4, lw=1.2, label="2026-08, temp. sin anotar (Vin medido, f a 1 MHz)")
ax[0].plot(Vn, Fn, "s--", color=NARANJA, ms=4, lw=1.2, label="2026-10-19, 15 °C (Vin medido, f a 10 kHz)")
ax[0].axvspan(0, V_MAX_USO, color="gray", alpha=0.08, label="rango usado (0-3 V)")
ax[0].set_ylabel("f VCO [MHz]")
ax[0].set_title("Repetibilidad del VCO")
ax[0].grid(alpha=0.3)
ax[0].legend(loc="upper left")

ax[1].axhspan(-0.5, 0.5, color="gray", alpha=0.15, label="$\\pm$0,5 MHz (redondeo de la vieja)")
ax[1].plot(Vn, dif, "o-", color=VERDE, ms=4, lw=1.2, label="nueva $-$ vieja")
ax[1].plot(Vn, a * Vn + b, ":", color="k", lw=1,
           label=f"recta: {b:+.1f} MHz {a:+.1f} MHz/V")
ax[1].set_ylabel("diferencia [MHz]")
ax[1].grid(alpha=0.3)
ax[1].legend(loc="best", fontsize=8)

ax[2].axhspan(-0.5, 0.5, color="gray", alpha=0.15)
ax[2].plot(Vn, forma, "o-", color=VERDE, ms=4, lw=1.2)
ax[2].axhline(0, color="k", lw=0.8)
ax[2].set_ylabel("cambio de forma [MHz]\n(diferencia $-$ recta)")
ax[2].set_xlabel("Vin [V]")
ax[2].grid(alpha=0.3)

plt.tight_layout()
plt.savefig("comparar_vco.png", dpi=150)
print("-> comparar_vco.png")
