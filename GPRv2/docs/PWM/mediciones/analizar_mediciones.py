"""
GPRv2 - Analisis de las mediciones del generador de triangular (osciloscopio)
=============================================================================

Lee las capturas del Siglent SDS1072CML+ (CH1 = triangular a la salida del generador,
CH2 = sync) de una carpeta de mediciones y para cada una calcula:
  - periodo, ciclo de trabajo del sync, rango, pendientes;
  - huecos en el registro: flancos del sync en los que la triangular salta. Parecian
    conmutaciones antes de tiempo, pero la triangular sigue exactamente como si se hubieran
    cortado unos milisegundos de senal, y los flancos siguientes llegan adelantados justo
    ese tiempo: el osciloscopio perdio muestras (pasa a 100 ms/div y mas lento, en roll);
  - no linealidad sistematica: residuo contra una recta, promediado sobre todas las rampas;
  - FFT sobre un numero entero de periodos regulares, contra una triangular ideal del mismo
    periodo y la misma amplitud, con el piso de ruido medido entre armonicos.

Generador con LM324, 680k en paralelo con R5 y 2 x 680k en paralelo con R2, 12 V.
Cada carpeta tiene su propia asignacion archivo -> posicion del pote (CARPETAS, abajo).

Genera en cada carpeta fft_medida_vs_ideal.png, forma_y_linealidad.png,
huecos_registro.png (si el registro tiene huecos) y mediciones_triangular.json.

Uso:  python analizar_mediciones.py                  todas las carpetas de CARPETAS
      python analizar_mediciones.py 2026-11-02_tanda2
"""
import os, sys, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
# carpeta -> [(archivo, posicion del pote)], de periodo corto a largo
CARPETAS = {
    "2026-11-02_tanda1": [("SDS00001.CSV", "pote al mínimo"), ("SDS00002.CSV", "~100 ms"), ("SDS00003.CSV", "pote al máximo")],
    "2026-11-02_tanda2": [("SDS00002.CSV", "pote al mínimo"), ("SDS00001.CSV", "~100 ms"), ("SDS00003.CSV", "pote al máximo")],
}
N_ARM = 15
M_PER = 2000        # muestras por periodo al remuestrear
ESCALON_V = 0.95    # salto estatico visto en todas las capturas (osciloscopio o salida del LM324)
AZUL, GRIS, TINTA, TINTA2, SUP, GRID = "#2a78d6", "#8a8984", "#0b0b0b", "#52514e", "#fcfcfb", "#e4e2dc"


def leer(ruta):
    d = np.genfromtxt(ruta, delimiter=",", usecols=(3, 4, 5), invalid_raise=False)
    d = d[~np.isnan(d).any(axis=1)]
    return d.T

def flancos(t, x):
    nivel = 0.5 * (np.percentile(x, 5) + np.percentile(x, 95))
    s = x > nivel
    def limpiar(ix):
        out = []
        for i in ix:
            if not out or t[i] - t[out[-1]] > 2e-3:
                out.append(i)
        return np.array(out, int)
    return limpiar(np.flatnonzero(~s[:-1] & s[1:]) + 1), limpiar(np.flatnonzero(s[:-1] & ~s[1:]) + 1)

def despicar(x, ancho=7):
    """Mediana movil: saca los picos de una o dos muestras sin tocar la rampa."""
    pad = ancho // 2
    xp = np.pad(x, pad, mode="edge")
    v = np.lib.stride_tricks.sliding_window_view(xp, ancho)
    return np.median(v, axis=1)

def ideal(fase, vmin, vmax):
    return vmin + (vmax - vmin) * (1 - np.abs(2 * (fase % 1.0) - 1))

def fft(x):
    return np.fft.rfft(x - x.mean()) / len(x) * 2


def analizar(carpeta, capturas):
    res = {}
    for f, nombre in capturas:
        t, tri, syn = leer(os.path.join(carpeta, f))
        trid = despicar(tri)
        paso = float(np.median(np.diff(np.unique(tri))))        # escalon del ADC del osciloscopio
        up, dn = flancos(t, syn)
        Tc = np.diff(t[up])
        T = np.median(Tc)
        regular = np.abs(Tc / T - 1) < 0.02
        anom = [dict(t=float(t[up[i]]), T=float(Tc[i])) for i in np.flatnonzero(~regular)]
        # tramo mas largo de ciclos regulares consecutivos
        mejor, ini, run = (0, 0), None, 0
        for i, ok in enumerate(regular):
            if ok:
                ini = i if run == 0 else ini; run += 1
                if run > mejor[1]: mejor = (ini, run)
            else:
                run = 0
        i0, n_per = mejor
        a, b = up[i0], up[i0 + n_per]
        tu = t[a] + np.arange(n_per * M_PER) * (t[b] - t[a]) / (n_per * M_PER)
        Treg = (t[b] - t[a]) / n_per
        xr = np.interp(tu, t, tri)                     # crudo
        xd = np.interp(tu, t, trid)                    # sin picos
        picos = int(np.sum(np.abs(tri - trid) > 0.15))
        # duty en los ciclos regulares
        altos = [t[dn[dn > u][0]] - t[u] for u in up[i0:i0 + n_per] if np.any(dn > u)]
        duty = float(np.median(altos) / Treg)
        vmax = float(np.median([np.percentile(xd[k*M_PER:(k+1)*M_PER], 99.5) for k in range(n_per)]))
        vmin = float(np.median([np.percentile(xd[k*M_PER:(k+1)*M_PER], 0.5) for k in range(n_per)]))
        pp = vmax - vmin
        # huecos del registro: en un flanco normal la triangular esta en su vertice y no salta;
        # si salta, faltan muestras (el osciloscopio perdio un pedazo) y se estima cuanto tiempo
        # por el camino que la triangular habria recorrido pasando por el vertice
        s_sube, s_baja = pp / (duty * Treg), pp / ((1 - duty) * Treg)
        k = max(2, int(0.5e-3 / np.median(np.diff(t))))
        eventos = []
        for i, arriba in [(i, True) for i in up] + [(i, False) for i in dn]:
            if i < k + 1 or i > len(t) - k - 2:
                continue
            antes, despues = float(np.median(tri[i-k-1:i-1])), float(np.median(tri[i+1:i+k+1]))
            esperado = vmax if arriba else vmin
            if abs(despues - antes) > max(3 * paso, 0.1 * pp) or abs(antes - esperado) > 0.15 * pp:
                falta = ((vmax - antes) / s_sube + (vmax - despues) / s_baja if arriba else
                         (antes - vmin) / s_baja + (despues - vmin) / s_sube)
                eventos.append(dict(t=float(t[i]), antes=antes, despues=despues, esperado=esperado,
                                    falta=float(falta), al_inicio=bool(t[i] - t[0] < T)))
        eventos.sort(key=lambda e: e["t"])
        # rampas: entre flancos del sync (subida del sync = empieza la bajada de la triangular)
        rampas = {"sube": [], "baja": []}
        pend = {"sube": [], "baja": []}
        bordes = sorted([(i, "u") for i in up] + [(i, "d") for i in dn])
        for (j0, k0), (j1, k1) in zip(bordes[:-1], bordes[1:]):
            if not (a <= j0 and j1 <= b) or j1 - j0 < 100:
                continue
            tipo = "baja" if k0 == "u" else "sube"
            n = j1 - j0; c0, c1 = j0 + int(0.05 * n), j0 + int(0.95 * n)
            tt, xx = t[c0:c1], trid[c0:c1]
            p = np.polyfit(tt, xx, 1)
            pos = (tt - tt[0]) / (tt[-1] - tt[0])
            rampas[tipo].append(np.interp(np.linspace(0, 1, 200), pos, xx - np.polyval(p, tt)))
            pend[tipo].append(p[0])
        prom = {k: np.mean(v, axis=0) for k, v in rampas.items()}
        nl = {k: float(np.abs(v).max() / pp) for k, v in prom.items()}
        # FFT: magnitud de cada armonico (amplitud pico) y piso de ruido entre armonicos
        Xr, Xd = fft(xr), fft(xd)
        # ideal: mismo periodo y amplitud, fase alineada (minimo error cuadratico)
        fases = np.linspace(0, 1, 2000, endpoint=False)
        base = (tu - tu[0]) / Treg
        err = [np.mean((xd - ideal(base - s, vmin, vmax)) ** 2) for s in fases[::10]]
        s0 = fases[::10][int(np.argmin(err))]
        xi = ideal(base - s0, vmin, vmax)
        Xi = fft(xi)
        k_arm = np.arange(1, N_ARM + 1) * n_per
        no_arm = np.setdiff1d(np.arange(1, (N_ARM + 1) * n_per), np.arange(0, (N_ARM + 2) * n_per, n_per))
        piso_r = float(np.median(np.abs(Xr[no_arm]))); piso_d = float(np.median(np.abs(Xd[no_arm])))
        res[f] = dict(nombre=nombre, T=float(Treg), n_per=int(n_per), ciclos_total=int(len(Tc)), anom=anom,
                      eventos=eventos, picos=picos, paso=paso, dt=float(np.median(np.diff(t))),
                      duty=duty, vmin=vmin, vmax=vmax, pend_sube=float(np.median(pend["sube"])),
                      pend_baja=float(np.median(pend["baja"])), nl=nl, n_rampas={k: len(v) for k, v in rampas.items()},
                      arm_r=np.abs(Xr[k_arm]).tolist(), arm_d=np.abs(Xd[k_arm]).tolist(), arm_i=np.abs(Xi[k_arm]).tolist(),
                      piso_r=piso_r, piso_d=piso_d, prom={k: v.tolist() for k, v in prom.items()},
                      esp_d=np.abs(Xd[:(N_ARM + 1) * n_per + 1]).tolist(), esp_i=np.abs(Xi[:(N_ARM + 1) * n_per + 1]).tolist(),
                      periodo_m=xd[:M_PER].tolist(), periodo_i=xi[:M_PER].tolist())
        # para la figura: cada hueco con su entorno
        for e in eventos:
            m = (t > e["t"] - 1.2 * T) & (t < e["t"] + 0.8 * T)
            e["tramo"] = dict(t=t[m].tolist(), tri=tri[m].tolist(), syn=syn[m].tolist())
    return res


def informe(res):
    for f, r in res.items():
        print(f"== {f} ({r['nombre']}): T {r['T']*1e3:.2f} ms, {r['n_per']} periodos regulares de {r['ciclos_total']}, "
              f"muestreo {r['dt']*1e6:.0f} us, escalon {r['paso']*1e3:.0f} mV, picos {r['picos']}")
        for e in r["eventos"]:
            print(f"   hueco en t = {e['t']*1e3:.1f} ms{' (primer periodo)' if e['al_inicio'] else ''}: "
                  f"{e['antes']:.2f} -> {e['despues']:.2f} V, faltan ~{e['falta']*1e3:.1f} ms")
        print(f"   sync alto {100*r['duty']:.1f} %, tri {r['vmin']:.3f}..{r['vmax']:.3f} V ({r['vmax']-r['vmin']:.3f} Vpp), "
              f"pendientes sube {r['pend_sube']:.2f} / baja {r['pend_baja']:.2f} V/s (dif {100*(abs(r['pend_baja'])/r['pend_sube']-1):.1f} %)")
        print(f"   no linealidad sistematica (promedio de {r['n_rampas']}): sube {100*r['nl']['sube']:.2f} %, baja {100*r['nl']['baja']:.2f} % del pp")
        print(f"   piso de ruido FFT: crudo {r['piso_r']*1e3:.2f} mV, sin picos {r['piso_d']*1e3:.2f} mV")
        print("    n   ideal   crudo   s/picos  [mV]  dif(s/picos) dB   rel. fund. medido / ideal [dB]")
        f1m, f1i = r['arm_d'][0], r['arm_i'][0]
        for k in range(N_ARM):
            i_, c_, d_ = r['arm_i'][k] * 1e3, r['arm_r'][k] * 1e3, r['arm_d'][k] * 1e3
            dif = 20 * np.log10(d_ / i_) if i_ > 0.01 else float('nan')
            print(f"   {k+1:2d} {i_:7.2f} {c_:7.2f} {d_:7.2f}   {dif:7.2f}       {20*np.log10(r['arm_d'][k]/f1m):7.1f} / "
                  f"{(20*np.log10(r['arm_i'][k]/f1i) if r['arm_i'][k] > 1e-5 else float('-inf')):7.1f}")


def estilo(a):
    a.set_facecolor(SUP); a.grid(color=GRID); a.set_axisbelow(True)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)


def figuras(r, orden, S):
    plt.rcParams.update({"font.size": 10.5, "axes.edgecolor": "#b4b2a9", "axes.labelcolor": TINTA2,
                         "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.titlecolor": TINTA})
    etq = {f: f"{r[f]['nombre']} · T = {r[f]['T']*1e3:.1f} ms" for f in orden}

    # ------------------------------------------------------------ 1. FFT medida contra ideal
    fig, ax = plt.subplots(1, 3, figsize=(16.5, 5.6), facecolor=SUP, sharey=True)
    for a, f in zip(ax, orden):
        np_, f0 = r[f]["n_per"], 1 / r[f]["T"]
        em, ei = np.array(r[f]["esp_d"]), np.array(r[f]["esp_i"])
        ref = em[np_]                                     # fundamental medida = 0 dB
        fr = np.arange(len(em)) / np_ * f0                # Hz
        a.plot(fr[1:], 20 * np.log10(np.maximum(em[1:], 1e-9) / ref), color=AZUL, lw=1.1, label="medida", zorder=3)
        k = np.arange(1, N_ARM + 1, 2) * np_              # la ideal solo tiene impares
        a.plot(fr[k], 20 * np.log10(ei[k] / ei[np_]), "o", ms=6, mfc="none", mec=TINTA2, mew=1.4,
               label="triangular ideal", zorder=4)
        piso = 20 * np.log10(r[f]["piso_d"] / ref)
        a.axhline(piso, color=TINTA2, lw=1, ls=":", zorder=2)
        a.text(fr[-1], piso + 1.5, "piso de ruido", ha="right", fontsize=9, color=TINTA2)
        a.set_xlim(0, fr[-1]); a.set_ylim(-80, 5)
        sec = a.secondary_xaxis("top", functions=(lambda x, f0=f0: x / f0, lambda n, f0=f0: n * f0))
        sec.set_xticks(range(1, N_ARM + 1, 2)); sec.tick_params(colors=TINTA2, labelsize=8.5)
        sec.set_xlabel("armónico", fontsize=9, color=TINTA2)
        estilo(a); a.spines["top"].set_visible(True)
        a.set_title(etq[f], fontsize=12, loc="left")
        a.set_xlabel("frecuencia [Hz]")
    ax[0].set_ylabel("amplitud relativa a la fundamental [dB]")
    ax[0].legend(loc="upper right", frameon=True, facecolor=SUP, edgecolor="none")
    fig.suptitle("Espectro de la triangular medida contra una triangular ideal del mismo período y la misma amplitud",
                 x=0.01, ha="left", fontsize=14, fontweight="bold", color=TINTA)
    fig.text(0.01, 0.015, "Los armónicos pares de la ideal son cero. Medido con Siglent SDS1072CML+, "
             "FFT sobre un número entero de períodos regulares (sin ventana: cada armónico cae justo en un bin).",
             fontsize=9.5, color=TINTA2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(os.path.join(S, "fft_medida_vs_ideal.png"), dpi=170, facecolor=SUP)
    plt.close(fig)

    # ------------------------------------------------------------ 2. forma y linealidad
    fig, ax = plt.subplots(2, 3, figsize=(16.5, 8.4), facecolor=SUP, gridspec_kw={"height_ratios": [1.15, 1]})
    for c, f in enumerate(orden):
        a = ax[0, c]
        x = np.linspace(0, 1, len(r[f]["periodo_m"]), endpoint=False)
        a.plot(x, r[f]["periodo_i"], color=GRIS, lw=2, ls="--", label="ideal")
        a.plot(x, r[f]["periodo_m"], color=AZUL, lw=1.6, label="medida")
        a.set_title(etq[f], fontsize=12, loc="left"); a.set_xlabel("fracción del período"); a.set_ylabel("V" if c == 0 else "")
        a.text(0.5, 0.97, f"{r[f]['vmin']:.2f} – {r[f]['vmax']:.2f} V\nsync en alto {100*r[f]['duty']:.1f} %",
               transform=a.transAxes, va="top", ha="center", fontsize=9.5, color=TINTA2)
        if c == 0:
            a.legend(loc="lower right", frameon=False)
        a = ax[1, c]
        pp = r[f]["vmax"] - r[f]["vmin"]
        for tipo, ls in (("sube", "-"), ("baja", "--")):
            y = np.array(r[f]["prom"][tipo]) * 1e3
            ys = np.convolve(np.pad(y, 7, mode="edge"), np.ones(15) / 15, mode="valid")
            # eje: tension de la triangular en cada punto de la rampa
            v = np.linspace(r[f]["vmin"], r[f]["vmax"], len(y)) if tipo == "sube" else np.linspace(r[f]["vmax"], r[f]["vmin"], len(y))
            a.plot(v, ys, color=AZUL, lw=1.8, ls=ls, label=f"rampa que {tipo} (máx {np.abs(ys).max()/pp/10:.2f} % pp)")
        q = r[f]["paso"] * 1e3 / 2
        a.axhspan(-q, q, color="#eeede9", zorder=0)
        a.text(r[f]["vmax"], -q + 2, "±1/2 escalón del osciloscopio", ha="right", fontsize=8.5, color=TINTA2)
        a.axvline(ESCALON_V, color=TINTA2, lw=0.8, ls=":")
        a.set_ylim(-40, 40); a.set_xlabel("tensión de la triangular [V]"); a.set_ylabel("desvío de la recta [mV]" if c == 0 else "")
        a.legend(loc="upper right", frameon=False, fontsize=9)
    for a in ax.flat:
        estilo(a)
    fig.suptitle("Forma de un período y desvío de cada rampa respecto de una recta (promedio de todas las rampas)",
                 x=0.01, ha="left", fontsize=14, fontweight="bold", color=TINTA)
    fig.text(0.01, 0.01, f"Abajo: residuo promediado y suavizado. El salto en ~{ESCALON_V:.2f} V (línea punteada) aparece en las "
             "tres capturas, en las dos rampas y a la misma tensión: es una no linealidad estática (osciloscopio o salida del LM324).",
             fontsize=9.5, color=TINTA2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(os.path.join(S, "forma_y_linealidad.png"), dpi=170, facecolor=SUP)
    plt.close(fig)

    # ------------------------------------------------------------ 3. huecos en el registro
    ev = [(f, e) for f in orden for e in r[f]["eventos"]]
    ruta = os.path.join(S, "huecos_registro.png")
    if not ev:
        if os.path.exists(ruta):
            print("  sin huecos en el registro; queda la huecos_registro.png anterior:", ruta)
        return
    fig, ax = plt.subplots(len(ev), 1, figsize=(12, 3.6 * len(ev)), facecolor=SUP, squeeze=False)
    for a, (f, e) in zip(ax[:, 0], ev):
        tr = e["tramo"]
        t = (np.array(tr["t"]) - e["t"]) * 1e3
        a.plot(t, tr["tri"], color=AZUL, lw=1.4, label="triangular (CH1)")
        a.plot(t, tr["syn"], color=GRIS, lw=1.2, label="sync (CH2)")
        a.axvline(0, color=TINTA2, lw=0.8, ls=":")
        a.annotate(f"salta de {e['antes']:.2f} a {e['despues']:.2f} V:\nfaltan ~{e['falta']*1e3:.0f} ms de registro",
                   xy=(0, 0.5 * (e["antes"] + e["despues"])), xytext=(0.12 * t[-1], 1.75), fontsize=10, color=TINTA,
                   arrowprops=dict(arrowstyle="->", color=TINTA2))
        estilo(a)
        a.set_ylabel("V"); a.legend(loc="upper left", frameon=False, fontsize=9)
        a.set_title(f"{etq[f]}" + (" · primer período de la captura" if e["al_inicio"] else ""),
                    loc="left", fontsize=12, color=TINTA)
    ax[-1, 0].set_xlabel("tiempo desde el hueco [ms]")
    fig.suptitle("Huecos en el registro del osciloscopio (no son conmutaciones del generador)",
                 x=0.01, ha="left", fontsize=13, fontweight="bold", color=TINTA)
    fig.tight_layout(rect=(0, 0, 1, 0.97)); fig.savefig(ruta, dpi=170, facecolor=SUP)
    plt.close(fig)


if __name__ == "__main__":
    for nombre in (sys.argv[1:] or list(CARPETAS)):
        carpeta = os.path.join(AQUI, nombre)
        capturas = CARPETAS[os.path.basename(os.path.normpath(nombre))]
        print(f"######## {nombre}")
        res = analizar(carpeta, capturas)
        informe(res)
        sin_tramo = {f: {**r, "eventos": [{k: v for k, v in e.items() if k != "tramo"} for e in r["eventos"]]}
                     for f, r in res.items()}
        json.dump(sin_tramo, open(os.path.join(carpeta, "mediciones_triangular.json"), "w"))
        figuras(res, [f for f, _ in capturas], carpeta)
    print("ok")
