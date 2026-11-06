"""
GPRv2 - Zero span del VCO barrido por el generador de triangular (Siglent SSA3032X)
==================================================================================

Cada SSA_*.csv en zero span es una frecuencia fija, con disparo externo en el flanco de
bajada del sync (t = 0 en el vertice de abajo) y un barrido de ~1 periodo. Los pulsos
de cada traza son los instantes en que el chirp pasa por esa frecuencia (uno en la subida,
otro en la bajada). Con todas las frecuencias se arma f(t), df/dt, f(V) contra la curva
estatica del VCO y el desvio respecto de una recta (lo que corrige el remuestreo).

Arriba de 1950 MHz los pulsos cerca del vertice de abajo son el 2o armonico de f/2: dan
puntos extra en el borde de abajo de la banda.

Genera zerospan_resumen.png, zerospan_trazas.png y zerospan_puntos.csv en la carpeta.

Uso:  python analizar_zerospan.py [carpeta]
"""
import sys, glob, os, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
CARP = os.path.join(AQUI, sys.argv[1] if len(sys.argv) > 1 else "2026-11-06-siglent_vco+triangular")
VCO = os.path.join(AQUI, "..", "..", "..", "..", "VCO", "Caracteristica VCO 2026-10-19.csv")
SC = CARP                        # figuras y puntos van a la carpeta de la medicion
T = 99.95e-3                     # periodo medido con el Tek (ALL0000)
VMIN, VMAX = 0.12, 3.06          # triangular medida con el Tek
AZ, NAR, GR, ROJO, SUP, GRID = "#2a78d6", "#e08a2c", "#8a8984", "#d64545", "#fcfcfb", "#e4e2dc"

def leer(f):
    L = open(f, encoding="utf-8", errors="replace").read().splitlines(); i = L.index("Trace Data")
    h = dict(l.split(",", 1) for l in L[:i] if "," in l)
    p = np.array([float(l.split(",")[1]) for l in L[i+1:] if l.strip()])
    swt = float(h["Sweep Time(s)"].split(",")[0]); fc = float(h["Start Frequency"].split(",")[0])
    zero = fc == float(h["Stop Frequency"].split(",")[0])
    return fc, zero, np.arange(len(p)) * swt / (len(p) - 1), p

pts = []          # (f, t, nivel, archivo, es_armonico)
crudo = {}
for f in sorted(glob.glob(CARP + "/SSA_*.csv")):
    fc, zero, t, p = leer(f)
    if not zero: continue
    crudo.setdefault(fc, []).append((os.path.basename(f), t, p))
    piso = np.median(p); on = p > piso + 15
    idx = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
    for a, b in zip(idx[::2], idx[1::2]):
        nivel = p[a:b].max()
        if nivel < p.max() - 8: continue                       # espurios de un punto, 15 dB abajo
        w = 10 ** (p[a:b] / 10); tc = np.sum(t[a:b] * w) / np.sum(w) % T
        arm = fc >= 1.95e9 and abs(tc - T / 2) > 0.25 * T       # a ~2 GHz, cerca del vertice de abajo: 2o armonico de f/2
        pts.append((fc / 2 if arm else fc, tc, nivel, os.path.basename(f), arm))

# la medicion repetida de 1025 MHz reemplaza a la que disparo tarde
malos = {"SSA_261106174535.csv"}
pts = [x for x in pts if x[3] not in malos]
# duplicados por el barrido un poco mas largo que el periodo: mismo archivo, tiempos a < 0,5 ms (mod T)
lim = []
for x in pts:
    if any(y[3] == x[3] and y[4] == x[4] and min(abs(y[1] - x[1]), T - abs(y[1] - x[1])) < 0.5e-3 for y in lim): continue
    lim.append(x)
pts = lim
f = np.array([x[0] for x in pts]); t = np.array([x[1] for x in pts]); arm = np.array([x[4] for x in pts])
# t queda en [0, T): la subida arranca en el vertice de abajo (~0) y la bajada termina en ~T
# vertice de arriba: cruce de los ajustes de las dos rampas
# ajustes en ms y MHz (en s y Hz el polinomio de grado 5 queda mal condicionado)
class Pol:
    def __init__(s, x, y): s.c = np.polyfit(x * 1e3, y / 1e6, 5)
    def __call__(s, x): return np.polyval(s.c, np.asarray(x) * 1e3) * 1e6
    def d(s, x): return np.polyval(np.polyder(s.c), np.asarray(x) * 1e3) * 1e9      # Hz/s
sube0 = (t < 0.48 * T) & (f < 1.97e9); baja0 = (t >= 0.52 * T) & (f < 1.97e9)
ps = Pol(t[sube0], f[sube0]); pb = Pol(t[baja0], f[baja0])
tt = np.linspace(0.4 * T, 0.6 * T, 20001); t_top = tt[np.argmin(np.abs(ps(tt) - pb(tt)))]
# vertice de abajo: igual, con la bajada corrida un periodo
tb = np.linspace(-0.1 * T, 0.1 * T, 20001); t_bot = tb[np.argmin(np.abs(ps(tb) - pb(tb + T)))]
t = np.where(t >= T + t_bot, t - T, t)          # si el vertice de abajo cae en t < 0
sube = (t >= t_bot) & (t < t_top); baja = ~sube
ps = Pol(t[sube], f[sube]); pb = Pol(t[baja], f[baja])
f_max = ps(t_top); f_min = ps(t_bot)
d_sube, d_baja = t_top - t_bot, T - (t_top - t_bot)
print(f"{len(f)} puntos ({arm.sum()} del 2o armonico), {len(set(x[3] for x in pts))} archivos")
print(f"vertice de abajo t = {t_bot*1e3:.2f} ms, de arriba t = {t_top*1e3:.2f} ms -> subida {d_sube*1e3:.2f} ms, bajada {d_baja*1e3:.2f} ms")
print(f"f_min {f_min/1e6:.1f} MHz, f_max {f_max/1e6:.1f} MHz, BW {(f_max-f_min)/1e6:.1f} MHz")
for nom, p, a, b in (("subida", ps, t_bot, t_top), ("bajada", pb, t_top, t_bot + T)):
    m = sube if nom == "subida" else baja
    r = f[m] - p(t[m]); print(f"  {nom}: residuo del ajuste rms {np.std(r)/1e6:.2f} MHz, max {np.abs(r).max()/1e6:.2f} MHz")
    x = np.linspace(a, b, 400); d = p.d(x) / 1e9
    print(f"     df/dt de {abs(d).min():.1f} a {abs(d).max():.1f} MHz/ms (media {abs((p(b)-p(a))/(b-a))/1e9:.2f})")

# curva estatica del VCO
vv, fv = [], []
for l in open(VCO, encoding="utf-8").read().splitlines()[1:]:
    c = [x.strip('"').replace(",", ".") for x in l.split('","')]
    if len(c) >= 2 and c[0] and c[1]: vv.append(float(c[0])); fv.append(float(c[1]) * 1e6)
vv, fv = np.array(vv), np.array(fv)
def V(tq):   # triangular lineal con los vertices medidos
    return np.where((tq >= t_bot) & (tq < t_top), VMIN + (VMAX - VMIN) * (tq - t_bot) / d_sube,
                    VMAX - (VMAX - VMIN) * (np.where(tq < t_bot, tq + T, tq) - t_top) / d_baja)

fig, ax = plt.subplots(2, 2, figsize=(16, 10.5), facecolor=SUP)
# 1. f(t)
a = ax[0, 0]
xs = np.linspace(t_bot, t_top, 400); xb = np.linspace(t_top, t_bot + T, 400)
a.plot(xs * 1e3, ps(xs) / 1e6, color=AZ, lw=1.2, alpha=.6); a.plot(xb * 1e3, pb(xb) / 1e6, color=AZ, lw=1.2, alpha=.6)
tp = np.where(baja & (t < t_top), t + T, t)
a.plot(tp[~arm] * 1e3, f[~arm] / 1e6, "o", color=AZ, ms=5, label="fundamental (zero span)")
a.plot(tp[arm] * 1e3, f[arm] / 1e6, "s", color=NAR, ms=5, label="desde el 2º armónico (f/2)")
a.axvline(t_top * 1e3, color=GR, ls=":"); a.axhline(f_max / 1e6, color=GR, ls=":"); a.axhline(f_min / 1e6, color=GR, ls=":")
a.text(t_top * 1e3 + 1, f_max / 1e6 - 25, f"f_max {f_max/1e6:.0f} MHz", fontsize=9); a.text(1, f_min / 1e6 + 10, f"f_min {f_min/1e6:.0f} MHz", fontsize=9)
a.set_title(f"Frecuencia del VCO en un período: subida {d_sube*1e3:.1f} ms, bajada {d_baja*1e3:.1f} ms", loc="left")
a.set_xlabel("tiempo desde el flanco de bajada del sync [ms]"); a.set_ylabel("MHz"); a.legend(loc="lower center")
# 2. df/dt: pendiente local (recta sobre 5 puntos vecinos de la misma rampa); el polinomio global oscila
def rampa(m, x0, x1):
    tq = np.where(t < x0 - 1e-3, t + T, t)[m & ~arm]; fq = f[m & ~arm]
    o = np.argsort(tq); tq, fq = tq[o], fq[o]
    u = (tq - x0) / (x1 - x0) * 100
    pend = np.array([np.polyfit(tq[max(0, i-2):i+3], fq[max(0, i-2):i+3], 1)[0] for i in range(len(tq))])
    return u, tq, fq, pend
a = ax[0, 1]
for nom, m, x0, x1, ls, mk, sg in (("subida", sube, t_bot, t_top, "-", "o", 1), ("bajada", baja, t_top, t_bot + T, "--", "s", -1)):
    u, tq, fq, pend = rampa(m, x0, x1)
    a.plot(u, sg * pend / 1e9, ls=ls, marker=mk, ms=4, color=AZ, lw=1.6, label=nom + (" (con signo cambiado)" if sg < 0 else ""))
a.axhline((f_max - f_min) / d_sube / 1e9, color=GR, ls=":", lw=1); a.text(1, (f_max - f_min) / d_sube / 1e9 + .3, "si fuera lineal", fontsize=9, color=GR)
a.set_title("Velocidad del barrido df/dt (recta local sobre 5 frecuencias)", loc="left"); a.set_xlabel("% de la rampa"); a.set_ylabel("MHz/ms"); a.legend()
# 3. f(V) contra la curva estatica
a = ax[1, 0]
a.plot(vv, fv / 1e6, color=GR, lw=2, label="curva estática (2026-10-19)")
a.plot(V(t[sube & ~arm]), f[sube & ~arm] / 1e6, "o", color=AZ, ms=5, label="subida")
a.plot(V(t[baja & ~arm]), f[baja & ~arm] / 1e6, "o", mfc="none", mec=AZ, ms=6, label="bajada")
a.plot(V(t[arm]), f[arm] / 1e6, "s", color=NAR, ms=5, label="desde el 2º armónico")
a.set_title(f"f contra la tensión de la triangular (tomada lineal, {VMIN}–{VMAX} V del Tek)", loc="left")
a.set_xlabel("V triangular [V]"); a.set_ylabel("MHz"); a.legend(loc="lower right"); a.set_xlim(-0.05, 3.4)
# 4. desvio respecto de la recta entre vertices
a = ax[1, 1]
for nom, m, x0, x1, ls, mk in (("subida", sube, t_bot, t_top, "-", "o"), ("bajada", baja, t_top, t_bot + T, "--", "s")):
    u, tq, fq, _ = rampa(m, x0, x1)
    f0, f1 = (f_min, f_max) if nom == "subida" else (f_max, f_min)
    dv = (fq - (f0 + (f1 - f0) * (tq - x0) / (x1 - x0))) / 1e6
    a.plot(u, dv, ls=ls, marker=mk, ms=4, color=AZ, lw=1.6, label=f"{nom} (máx {np.abs(dv).max():.0f} MHz)")
a.axhline(0, color=GR, lw=1)
a.set_title("Desvío de f(t) respecto de una recta entre vértices (lo que corrige el remuestreo)", loc="left")
a.set_xlabel("% de la rampa"); a.set_ylabel("MHz"); a.legend()
for a in ax.flat: a.grid(color=GRID); a.set_facecolor(SUP)
fig.suptitle("VCO barrido por el generador de triangular: zero span con el SSA3032X (2026-11-06)", x=0.01, ha="left", fontweight="bold", fontsize=14)
fig.tight_layout(rect=(0, 0, 1, 0.96)); fig.savefig(SC + "/zerospan_resumen.png", dpi=120)

# trazas crudas apiladas
fig, a = plt.subplots(figsize=(14, 9), facecolor=SUP)
for fc in sorted(crudo):
    nom, tr, p = crudo[fc][-1]
    if nom in malos and len(crudo[fc]) == 1: continue
    sel = [c for c in crudo[fc] if c[0] not in malos][-1]
    a.plot(sel[1] * 1e3, fc / 1e6 + (sel[2] - np.median(sel[2])) * 0.7, color=AZ, lw=0.7)
a.set_xlabel("tiempo desde el flanco de bajada del sync [ms]"); a.set_ylabel("frecuencia de la traza [MHz] (+ potencia, 0,7 MHz/dB)")
a.set_title("Trazas en zero span, una por frecuencia (arriba, a los costados, el 2º armónico del vértice de abajo)", loc="left")
a.grid(color=GRID); a.set_facecolor(SUP); fig.tight_layout(); fig.savefig(SC + "/zerospan_trazas.png", dpi=110)
np.savetxt(SC + "/zerospan_puntos.csv", np.c_[f / 1e6, t * 1e3, arm, sube], delimiter=",", header="f_MHz,t_ms,de_armonico,subida", fmt="%.3f")
print("ok")
