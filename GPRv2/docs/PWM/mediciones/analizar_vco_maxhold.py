"""
GPRv2 - Salida del VCO barrido por el generador de triangular, en Max Hold (Siglent SSA3032X)
=============================================================================================

Lee las trazas en Max Hold de una carpeta de mediciones (SSA_*.csv) y saca:
  - la banda que barre el VCO (primer y ultimo punto con senal por debajo de 2,02 GHz);
  - la banda del 2o armonico y si se superpone con la fundamental (2*f_min < f_max);
  - el nivel del 2o armonico respecto de la fundamental;
  - la banda que predice la curva estatica del VCO para la triangular medida con el osciloscopio.

Ojo con el Max Hold: el analizador barre 2,2 GHz en 216 ms y el VCO 1 GHz en ~50 ms, asi
que cada barrido agarra el chirp solo donde se cruzan. La traza se llena de a poco (por eso
los peines) y un borde puede no haberse "pisado" todavia: manda la captura mas llena.

Genera vco_maxhold.png en la carpeta.

Uso:  python analizar_vco_maxhold.py [carpeta]      (por defecto 2026-11-02_vco_maxhold)
"""
import os, sys, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(AQUI, sys.argv[1] if len(sys.argv) > 1 else "2026-11-02_vco_maxhold")
CURVA_VCO = os.path.join(AQUI, "..", "..", "..", "..", "VCO", "Caracteristica VCO 2026-10-19.csv")
TRI_MIN, TRI_MAX = 0.36, 3.36     # triangular medida con el osciloscopio (2026-11-02_tanda2)
SOBRE_PISO = 8                    # dB sobre el piso para decir "hay senal"
CORTE = 2020e6                    # debajo de esto puede ser fundamental
NIVEL_FUND = 5                    # dB por debajo del nivel tipico de la fundamental que todavia cuentan como ella
AZUL, ROJO, GRIS, TINTA, TINTA2, SUP, GRID = "#2a78d6", "#d64545", "#8a8984", "#0b0b0b", "#52514e", "#fcfcfb", "#e4e2dc"


def leer(ruta):
    L = open(ruta, encoding="utf-8", errors="replace").read().splitlines()
    i = L.index("Trace Data")
    d = np.array([[float(x) for x in l.split(",")[:2]] for l in L[i + 1:] if l.strip()])
    cab = dict(l.split(",", 1) for l in L[:i] if "," in l)
    return d[:, 0], d[:, 1], cab


def curva_vco():
    v, f = [], []
    for l in open(CURVA_VCO, encoding="utf-8").read().splitlines()[1:]:
        c = [x.strip('"').replace(",", ".") for x in l.split('","')]
        if len(c) >= 2 and c[0] and c[1]:
            v.append(float(c[0])); f.append(float(c[1]) * 1e6)
    return np.array(v), np.array(f)


def bandas(fr, p):
    piso = np.median(p[fr < 950e6])
    hay = p > piso + SOBRE_PISO
    # cerca de 2 GHz se mezclan la fundamental y el 2o armonico: se separan por nivel
    ref = np.percentile(p[hay & (fr > 1100e6) & (fr < 1900e6)], 75)
    fund = hay & (fr < CORTE) & (p > ref - NIVEL_FUND)
    arm = hay & (fr >= CORTE)                         # solo para medir su nivel
    f_min, f_max = fr[fund][0], fr[fund][-1]
    llen = np.mean(hay[(fr > f_min) & (fr < f_max)])
    nivel_f = np.percentile(p[fund], 90)
    nivel_a = np.percentile(p[arm], 90) if arm.any() else np.nan
    return dict(piso=piso, f_min=f_min, f_max=f_max, llenado=llen, nivel_f=nivel_f, nivel_a=nivel_a)


archivos = sorted(glob.glob(os.path.join(CARPETA, "SSA_*.csv")))
datos = [(os.path.basename(a),) + leer(a) for a in archivos]
res = {n: bandas(fr, p) for n, fr, p, _ in datos}
mejor = max(res, key=lambda n: res[n]["llenado"])

v, fv = curva_vco()
pred = np.interp([TRI_MIN, TRI_MAX], v, fv, right=None)
if TRI_MAX > v[-1]:                                   # un poco afuera de la curva: extrapolar recto
    pred[1] = fv[-1] + (TRI_MAX - v[-1]) * (fv[-1] - fv[-2]) / (v[-1] - v[-2])
v_de_f = lambda f: np.interp(f, fv, v)

for n, _, _, cab in datos:
    r = res[n]
    sup = 2 * r["f_min"] < r["f_max"]
    print(f"== {n}: RBW {float(cab['RBW'].split(',')[0])/1e6:g} MHz, barrido {cab['Sweep Time(s)'].split(',')[0]} s, "
          f"atenuador {cab['Attenuation'].split(',')[0]} dB, piso {r['piso']:.1f} dBm, traza llena al {100*r['llenado']:.0f} %")
    print(f"   fundamental {r['f_min']/1e6:.0f} - {r['f_max']/1e6:.0f} MHz (BW {(r['f_max']-r['f_min'])/1e6:.0f} MHz), "
          f"nivel ~{r['nivel_f']:.1f} dBm; en la curva estatica eso es Vin {v_de_f(r['f_min']):.2f} - {v_de_f(r['f_max']):.2f} V")
    print(f"   2o armonico: nivel ~{r['nivel_a']:.1f} dBm = {r['nivel_a']-r['nivel_f']:.0f} dBc; "
          f"2*f_min = {2*r['f_min']/1e6:.0f} MHz -> " + (f"SE SUPERPONE {(r['f_max']-2*r['f_min'])/1e6:.0f} MHz con la fundamental"
                                                       if sup else f"queda {(2*r['f_min']-r['f_max'])/1e6:.0f} MHz arriba de f_max"))
print(f"curva estatica del VCO con la triangular {TRI_MIN}-{TRI_MAX} V: {pred[0]/1e6:.0f} - {pred[1]/1e6:.0f} MHz")
print(f"captura mas llena: {mejor}")

# ------------------------------------------------------------------ figura
plt.rcParams.update({"font.size": 10.5, "axes.edgecolor": "#b4b2a9", "axes.labelcolor": TINTA2,
                     "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.titlecolor": TINTA})
fig, a = plt.subplots(figsize=(15, 6.2), facecolor=SUP)
r = res[mejor]
for n, fr, p, _ in datos:
    if n != mejor:
        a.plot(fr / 1e6, p, color=GRIS, lw=0.6, alpha=0.6, zorder=2)
n, fr, p, _ = next(d for d in datos if d[0] == mejor)
a.plot(fr / 1e6, p, color=AZUL, lw=0.9, zorder=3, label=f"{mejor} (la más llena, {100*r['llenado']:.0f} %)")
a.plot([], [], color=GRIS, lw=0.8, label="las otras capturas")
a.axvspan(r["f_min"] / 1e6, r["f_max"] / 1e6, color=AZUL, alpha=0.07, zorder=1)
a.axvspan(2 * r["f_min"] / 1e6, min(2 * r["f_max"], fr[-1]) / 1e6, color=ROJO, alpha=0.06, zorder=1)
if 2 * r["f_min"] < r["f_max"]:
    a.axvspan(2 * r["f_min"] / 1e6, r["f_max"] / 1e6, color=ROJO, alpha=0.25, zorder=1)
    a.annotate(f"superposición\n{2*r['f_min']/1e6:.0f}–{r['f_max']/1e6:.0f} MHz", xy=(r["f_max"] / 1e6, -27),
               xytext=(r["f_max"] / 1e6 + 90, -33), fontsize=9.5, color=ROJO, arrowprops=dict(arrowstyle="->", color=ROJO))
for f in pred:
    a.axvline(f / 1e6, color=TINTA2, lw=1, ls="--", zorder=2)
a.text(pred[0] / 1e6 + 8, 4.2, f"curva estática\n{TRI_MIN} V", fontsize=8.5, color=TINTA2, va="top")
a.text(pred[1] / 1e6 + 8, 4.2, f"curva estática\n{TRI_MAX} V", fontsize=8.5, color=TINTA2, va="top")
a.text((r["f_min"] + r["f_max"]) / 2e6, 7.5, f"fundamental  {r['f_min']/1e6:.0f}–{r['f_max']/1e6:.0f} MHz",
       ha="center", fontsize=10.5, color=AZUL, fontweight="bold")
a.text(min(2 * r["f_min"] + 450e6, fr[-1] - 250e6) / 1e6, 7.5, f"2º armónico  desde {2*r['f_min']/1e6:.0f} MHz, "
       f"{r['nivel_a']-r['nivel_f']:.0f} dBc", ha="center", fontsize=10.5, color=ROJO, fontweight="bold")
a.set_xlim(fr[0] / 1e6, fr[-1] / 1e6); a.set_ylim(-36, 10)
a.set_xlabel("frecuencia [MHz]"); a.set_ylabel("dBm (Max Hold, RBW 1 MHz)")
a.set_facecolor(SUP); a.grid(color=GRID); a.set_axisbelow(True)
for s in ("top", "right"):
    a.spines[s].set_visible(False)
a.legend(loc="lower right", frameon=True, facecolor=SUP, edgecolor="none", fontsize=9)
fig.suptitle("Salida del VCO barrido por el generador de triangular (Siglent SSA3032X, Max Hold)",
             x=0.01, ha="left", fontsize=14, fontweight="bold", color=TINTA)
fig.text(0.01, 0.015, "Los peines son del Max Hold: el analizador barre más lento que el chirp y solo lo agarra donde se cruzan. "
         f"Piso de {r['piso']:.0f} dBm por el atenuador de 50 dB: lo que esté más abajo no se ve.", fontsize=9.5, color=TINTA2)
fig.tight_layout(rect=(0, 0.04, 1, 0.95))
fig.savefig(os.path.join(CARPETA, "vco_maxhold.png"), dpi=170, facecolor=SUP)
print("ok")
