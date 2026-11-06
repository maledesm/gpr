"""
GPRv2 - Capturas del generador de triangular con el Tektronix TBS1102B
=======================================================================

Lee cada carpeta ALL000x (F000xCH1.CSV = triangular, F000xCH2.CSV = sync) y arma una
figura por captura: la captura entera, el periodo plegado contra una triangular ideal,
el desvio de cada rampa respecto de una recta y el espectro contra el de la ideal.
En modo scan el Tek rellena con ~-1,3 V lo que no grabo: se usa el tramo continuo mas largo.

Genera ALL000x_analisis.png y ALL000x_pantalla.png en la carpeta.

Uso:  python analizar_tektronix.py [carpeta]
"""
import sys, os, glob, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, sys.argv[1] if len(sys.argv) > 1 else "2026-11-06-tektronix_triangular")
SC = BASE                        # las figuras van a la carpeta de la medicion
AZ, GR, SUP, GRID = "#2a78d6", "#8a8984", "#fcfcfb", "#e4e2dc"

def leer(d):
    t, a = np.genfromtxt(glob.glob(d + "/*CH1.CSV")[0], delimiter=",", usecols=(3, 4)).T
    b = np.genfromtxt(glob.glob(d + "/*CH2.CSV")[0], delimiter=",", usecols=(4,))
    ok = (a > -1.3) | (b > -1.25)               # el relleno del modo scan viene en ~-1,3 V
    # el tramo continuo mas largo sin relleno (en scan puede haber relleno en el medio)
    bordes = np.flatnonzero(np.diff(np.r_[0, ok.astype(int), 0]))
    i0, i1 = max(zip(bordes[::2], bordes[1::2]), key=lambda p: p[1] - p[0])
    return t[i0:i1], a[i0:i1], b[i0:i1]

def ideal(ph, vmin, vmax):
    return vmax - (vmax - vmin) * (1 - np.abs(2 * (ph % 1) - 1))   # fase 0 = subida del sync = vertice de arriba

resumen = []
for d in sorted(glob.glob(BASE + "/ALL*")):
    nom = os.path.basename(d)
    Image.open(glob.glob(d + "/*.BMP")[0]).save(f"{SC}/{nom}_pantalla.png")
    t, a, b = leer(d)
    dt = np.median(np.diff(t))
    s = b > 1.4
    up = np.flatnonzero(~s[:-1] & s[1:]) + 1; dn = np.flatnonzero(s[:-1] & ~s[1:]) + 1
    n_per = len(up) - 1
    T = (t[up[-1]] - t[up[0]]) / n_per if n_per >= 1 else np.nan
    vmin, vmax = np.percentile(a, 0.5), np.percentile(a, 99.5); pp = vmax - vmin
    alto = [t[dn[dn > u][0]] - t[u] for u in up[:-1] if np.any(dn > u)]
    duty = np.median(alto) / T if alto else np.nan
    # saltos en los flancos (huecos del registro)
    k = max(2, int(0.5e-3 / dt))
    saltos = [(t[i], a[i+1:i+k+1].mean() - a[i-k-1:i-1].mean()) for i in sorted(list(up) + list(dn))
              if k + 1 < i < len(a) - k - 2]
    saltos = [x for x in saltos if abs(x[1]) > max(0.1 * pp, 3 * 0.02 + 59 * pp / 3 * 0 + abs(2 * pp / T * (k + 1) * dt))]
    # rampas: recta y residuo
    bordes = sorted([(i, "u") for i in up] + [(i, "d") for i in dn]); res = {"sube": [], "baja": []}; pend = {"sube": [], "baja": []}
    for (j0, k0), (j1, _) in zip(bordes[:-1], bordes[1:]):
        n = j1 - j0
        if n < 20: continue
        c0, c1 = j0 + int(.05 * n), j0 + int(.95 * n); tt, yy = t[c0:c1], a[c0:c1]
        p = np.polyfit(tt, yy, 1); tipo = "baja" if k0 == "u" else "sube"
        res[tipo].append(np.interp(np.linspace(0, 1, 80), (tt - tt[0]) / (tt[-1] - tt[0]), yy - np.polyval(p, tt))); pend[tipo].append(p[0])
    # FFT sobre los periodos enteros entre subidas del sync, contra la ideal
    m = (t >= t[up[0]]) & (t < t[up[-1]])
    tu = t[up[0]] + np.arange(n_per * 1000) * T / 1000
    xu = np.interp(tu, t[m], a[m]); xi = ideal((tu - tu[0]) / T, vmin, vmax)
    X = lambda x: np.abs(np.fft.rfft(x - x.mean())) / len(x) * 2
    Xm, Xi = X(xu), X(xi); kk = np.arange(1, 16) * n_per
    resumen.append((nom, dt, T, n_per, vmin, vmax, duty, pend, res, saltos, Xm, Xi))

    fig, ax = plt.subplots(1, 4, figsize=(21, 4.8), facecolor=SUP, gridspec_kw={"width_ratios": [1.5, 1, 1, 1.2]})
    x = ax[0]; x.plot(t, a, color=AZ, lw=1, label="triangular (CH1)"); x.plot(t, b, color=GR, lw=1, label="sync (CH2)")
    for ts, _ in saltos: x.axvline(ts, color="#d64545", lw=1)
    x.set_title(f"{nom}: {n_per} períodos de {T*1e3:.2f} ms, muestra cada {dt*1e6:.0f} µs", loc="left"); x.set_xlabel("t [s]"); x.legend(fontsize=8, loc="upper right")
    x = ax[1]; ph = ((t[m] - t[up[0]]) / T) % 1
    x.plot(ph, a[m], ".", ms=2, color=AZ, alpha=.5, label="muestras"); pi = np.linspace(0, 1, 500); x.plot(pi, ideal(pi, vmin, vmax), "--", color=GR, label="ideal")
    x.set_title(f"plegado: {vmin:.2f} – {vmax:.2f} V, sync alto {100*duty:.1f} %", loc="left"); x.set_xlabel("fracción del período"); x.legend(fontsize=8)
    x = ax[2]
    for tipo, ls in (("sube", "-"), ("baja", "--")):
        if not res[tipo]: continue
        y = np.mean(res[tipo], axis=0) * 1e3; ys = np.convolve(np.pad(y, 2, mode="edge"), np.ones(5) / 5, mode="valid")
        v = np.linspace(vmin, vmax, len(y)) if tipo == "sube" else np.linspace(vmax, vmin, len(y))
        x.plot(v, ys, color=AZ, ls=ls, lw=1.8, label=f"{tipo} ({len(res[tipo])} rampas, máx {np.abs(ys).max()/pp/10:.2f} % pp)")
    x.axhspan(-10, 10, color="#eeede9", zorder=0); x.set_ylim(-40, 40)
    x.set_title("desvío de la recta [mV]", loc="left"); x.set_xlabel("tensión [V]"); x.legend(fontsize=8)
    x = ax[3]; fr = np.arange(len(Xm)) / n_per / T; lim = 16 * n_per
    x.plot(fr[1:lim], 20 * np.log10(np.maximum(Xm[1:lim], 1e-9) / Xm[n_per]), color=AZ, lw=1, label="medida")
    ko = np.arange(1, 16, 2) * n_per; x.plot(fr[ko], 20 * np.log10(Xi[ko] / Xi[n_per]), "o", mfc="none", mec="#52514e", label="ideal")
    x.set_ylim(-80, 5); x.set_title("espectro rel. a la fundamental [dB]", loc="left"); x.set_xlabel("Hz"); x.legend(fontsize=8)
    for x in ax: x.grid(color=GRID); x.set_facecolor(SUP)
    fig.tight_layout(); fig.savefig(f"{SC}/{nom}_analisis.png", dpi=110)
    plt.close(fig)

for nom, dt, T, n_per, vmin, vmax, duty, pend, res, saltos, Xm, Xi in resumen:
    ps, pb = np.median(pend["sube"]) if pend["sube"] else np.nan, np.median(pend["baja"]) if pend["baja"] else np.nan
    nl = max(np.abs(np.mean(v, axis=0)).max() for v in res.values() if v) / (vmax - vmin)
    arm = 20 * np.log10(Xm[np.arange(1, 9) * n_per] / Xm[n_per])
    print(f"{nom}: dt {dt*1e6:.0f} us, {n_per} periodos de {T*1e3:.2f} ms, tri {vmin:.2f}..{vmax:.2f} V, sync alto {100*duty:.1f} %, "
          f"pend {ps:.1f}/{pb:.1f} V/s (dif {100*(abs(pb)/ps-1):.1f} %), no lin {100*nl:.2f} %, saltos {len(saltos)}")
    print("    armonicos 1-8 [dBc]:", np.round(arm, 1), " ideal 3,5,7:", np.round(20*np.log10(Xi[np.array([3,5,7])*n_per]/Xi[n_per]), 1))
