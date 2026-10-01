"""
GPRv2 - Curva distancia -> frecuencia de batido: banco contra simulacion
========================================================================

    (en Windows, despues de correr el barrido de MEEP con las MISMAS
    distancias que se midieron)
    set GPR_SIM_NOMBRE=mediciones_2026-09-28
    set GPR_SIM_BARRIDO=0.70 0.80 0.90 1.00 1.20
    python relevar.py ../datos/capturas/placa_*cm_*.csv

Toma las capturas de `vivo_rapido.py` (tecla 's') de la placa a varias
distancias, saca el pico principal de cada una y lo pone al lado del pico de
la simulacion a la MISMA distancia. La distancia real sale del nombre del
archivo (placa_<cm>cm_...). Con eso ajusta, para cada serie,

    f_pico = m * d_real + f0        [Hz]

`m` tiene que dar cerca de 4B/(c*Tprf) = 138,6 Hz/m y `f0` es el offset de
cables + electronica + bocinas. Escribe en la carpeta de la corrida:

    relevamiento.png        f contra d, las rectas y los residuos
    relevamiento_curvas.png el espectro medido y simulado de cada distancia
    relevamiento.csv        la tabla de picos
    resumen_relevamiento.txt

Que se compara con que (igual que comparar.py): una captura con
`fondo = sin medir` va contra la escena completa (placa, con acoplamiento y
pared); una con `fondo = congelado` va contra placa - vacio.
"""

import os
import re
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import parametros as P                                            # noqa: E402
import radar as R                                                 # noqa: E402
from comparar import leer_csv, pico_hz, db, DESDE_HZ              # noqa: E402

RELLENO = 8
SERIES = {  # clave: (etiqueta, color, marcador)
    "med_sin":  ("medido, fondo sin medir (cf)",   "C0", "o"),
    "med_cong": ("medido, fondo congelado (sf)",   "C3", "s"),
    "sim_placa": ("simulado, escena completa",     "C0", "x"),
    "sim_solo":  ("simulado, placa - vacio",       "C3", "+"),
}


def distancia_de(ruta):
    m = re.search(r"placa_(\d+(?:[.,]\d+)?)cm", os.path.basename(ruta))
    if not m:
        raise SystemExit(f"{ruta}: no saco la distancia del nombre "
                         f"(se espera placa_<cm>cm_...)")
    return float(m.group(1).replace(",", ".")) / 100


def ajuste(d, f):
    """(pendiente, ordenada, residuos, incerteza 1 sigma de la pendiente)."""
    m, f0 = np.polyfit(d, f, 1)
    res = f - (m * d + f0)
    sm = np.nan
    if len(d) > 2:
        sxx = np.sum((d - d.mean()) ** 2)
        sm = np.sqrt(np.sum(res ** 2) / (len(d) - 2) / sxx)
    return m, f0, res, sm


def main():
    rutas = sorted(sys.argv[1:], key=distancia_de)
    if not rutas:
        raise SystemExit(__doc__)

    curva = R.cargar_curva_vco(P.VCO_CSV)
    f_sim, H_vacio = R.cargar("vacio_barrido")
    _t, _b, _th, alpha0 = R.sintetizar(f_sim, H_vacio, curva=curva)
    hz_por_m = 2 * alpha0 / R.C

    sim = {}           # d -> {"placa": (hz, ee), "solo": (hz, ee)}
    filas = []         # (archivo, d, fondo, f_med, f_sim, cual)
    for ruta in rutas:
        d = distancia_de(ruta)
        if d not in sim:
            etiqueta = f"placa_{d:.2f}".replace(".", "p")
            if not os.path.exists(os.path.join(P.SALIDAS, f"H_{etiqueta}.npz")):
                raise SystemExit(
                    f"no hay simulacion a {d:.2f} m en {P.SALIDAS}.\n"
                    f"Correr el barrido de MEEP con esa distancia en "
                    f"GPR_SIM_BARRIDO.")
            _, H = R.cargar(etiqueta)
            sim[d] = {}
            # El offset armado de a un pedazo, sobre la escena completa:
            # solo aire (bocinas + camino hasta la placa), + cables, + interno
            sim[d]["etapas"] = [
                pico_hz(rr * hz_por_m, ee) for rr, ee in (
                    R.perfil(f_sim, R.aplicar_cadena(f_sim, H, modo, tau),
                             relleno=RELLENO, curva=curva)
                    for modo, tau in (("ninguno", 0.0), (P.MODO_CABLE, 0.0),
                                      (P.MODO_CABLE, P.TAU_INTERNO)))]
            for cual, HH in (("placa", H), ("solo", H - H_vacio)):
                rr, ee = R.perfil(f_sim, R.aplicar_cadena(f_sim, HH, P.MODO_CABLE),
                                  relleno=RELLENO, curva=curva)
                sim[d][cual] = (rr * hz_por_m, ee)
        cab, f_med, mag = leer_csv(ruta)
        a_banco = float(cab.get("alpha0_hz_s", alpha0))
        if abs(a_banco - alpha0) / alpha0 > 0.01:
            print(f"  [!] {os.path.basename(ruta)}: alpha0 del banco distinto "
                  f"del de la simulacion ({100*(a_banco/alpha0-1):+.1f} %)")
        fondo = cab.get("fondo", "?")
        cual = "placa" if fondo.startswith("sin") else "solo"
        hz_s, ee_s = sim[d][cual]
        filas.append(dict(archivo=os.path.basename(ruta), d=d, fondo=fondo,
                          cual=cual, f_med=pico_hz(f_med, mag),
                          f_sim=pico_hz(hz_s, ee_s), curva=(f_med, mag),
                          sat=cab.get("triangular_saturada_pct", "-")))

    # --- tabla y ajustes -----------------------------------------------------
    series = {}
    for cual, k_med, k_sim in (("placa", "med_sin", "sim_placa"),
                               ("solo", "med_cong", "sim_solo")):
        sel = [r for r in filas if r["cual"] == cual]
        if not sel:
            continue
        d = np.array([r["d"] for r in sel])
        series[k_med] = (d, np.array([r["f_med"] for r in sel]))
        series[k_sim] = (d, np.array([r["f_sim"] for r in sel]))
    ajustes = {k: ajuste(*v) for k, v in series.items() if len(v[0]) >= 2}

    csv = os.path.join(P.SALIDAS, "relevamiento.csv")
    with open(csv, "w", encoding="utf-8") as fh:
        fh.write("archivo,d_real_m,fondo,f_medido_hz,f_simulado_hz,"
                 "dif_hz,dif_cm,d_aparente_medida_m,d_aparente_simulada_m\n")
        for r in filas:
            dif = r["f_med"] - r["f_sim"]
            fh.write(f"{r['archivo']},{r['d']:.3f},{r['fondo']},"
                     f"{r['f_med']:.2f},{r['f_sim']:.2f},{dif:+.2f},"
                     f"{dif/hz_por_m*100:+.2f},{r['f_med']/hz_por_m:.4f},"
                     f"{r['f_sim']/hz_por_m:.4f}\n")

    with R.copiar_consola("resumen_relevamiento.txt"):
        print("=" * 78)
        print("Relevamiento distancia -> frecuencia: banco contra simulacion")
        print("=" * 78)
        print(f"  {'captura':22s} {'d real':>7s} {'fondo':10s} {'medido':>8s} "
              f"{'simulado':>9s} {'dif':>8s} {'dif':>7s} {'sat%':>5s}")
        print("  " + "-" * 76)
        for r in filas:
            dif = r["f_med"] - r["f_sim"]
            print(f"  {r['archivo']:22s} {r['d']:6.2f}m {r['fondo']:10s} "
                  f"{r['f_med']:7.1f}Hz {r['f_sim']:8.1f}Hz {dif:+7.1f}Hz "
                  f"{dif/hz_por_m*100:+6.1f}cm {r['sat']:>5s}")
        print()
        print(f"  Recta f = m*d + f0   (ideal: m = 4B/(c*Tprf) = "
              f"{hz_por_m:.1f} Hz/m)")
        for k, (m, f0, res, sm) in ajustes.items():
            err = f" +- {sm:.1f}" if np.isfinite(sm) else ""
            print(f"  {SERIES[k][0]:34s} m = {m:6.1f}{err} Hz/m "
                  f"({m/hz_por_m:.3f} del ideal)  f0 = {f0:6.1f} Hz "
                  f"({f0/hz_por_m:.3f} m)  rms {np.sqrt(np.mean(res**2)):.1f} Hz")
        # De donde sale el offset: f = hz_por_m * (d + offset). Cada etapa se
        # mide como corrimiento del pico, promediado sobre las distancias.
        ds = np.array(sorted(sim))
        et = np.array([sim[d]["etapas"] for d in ds])        # Hz, 3 etapas
        off = {"aire": (et[:, 0] - ds * hz_por_m).mean(),
               "cables": (et[:, 1] - et[:, 0]).mean(),
               "interno": (et[:, 2] - et[:, 1]).mean()}
        # Del offset solo los cables estan medidos por separado (VNA). Las
        # bocinas las pone MEEP y el retardo interno se AJUSTO despues contra
        # el banco, asi que cualquier error del modelo de la bocina lo absorbe
        # el ajuste: lo unico que la medicion fija es la SUMA de los dos.
        resto = off["aire"] + off["interno"]
        tot = off["cables"] + resto
        print()
        print("  De donde sale el offset (simulado, promedio sobre las "
              "distancias):")
        print(f"    {'cables RG-213 (VNA)':32s} {off['cables']:6.1f} Hz = "
              f"{off['cables']/hz_por_m:5.3f} m   (tau "
              f"{P.tau_cables()*1e9:.2f} ns, medido)")
        print(f"    {'bocinas + electronica':32s} {resto:6.1f} Hz = "
              f"{resto/hz_por_m:5.3f} m   (no se separan: MEEP da "
              f"{off['aire']:.0f} Hz de bocinas y el interno de "
              f"{P.TAU_INTERNO*1e9:g} ns, {off['interno']:.0f} Hz, se ajusto "
              f"encima)")
        print(f"    {'total simulado':32s} {tot:6.1f} Hz = {tot/hz_por_m:5.3f} m")
        if "med_sin" in ajustes:
            m_, f0_ = ajustes["med_sin"][:2]
            print(f"    {'medido (f0 de la recta cf)':32s} {f0_:6.1f} Hz = "
                  f"{f0_/hz_por_m:5.3f} m   -> bocinas + electronica medido "
                  f"{f0_ - off['cables']:.0f} Hz = "
                  f"{(f0_ - off['cables'])/hz_por_m:.3f} m")
        if P.MURO_DIST > 0:
            # el eco de la pared es el pico mas fuerte de la escena vacia
            rr, ee = R.perfil(f_sim, R.aplicar_cadena(f_sim, H_vacio,
                                                      P.MODO_CABLE),
                              relleno=RELLENO, curva=curva)
            f_muro = pico_hz(rr * hz_por_m, ee, desde=400.0)
            bin_cm = R.C / (2 * alpha0 * R.T_SWEEP) * 100
            print(f"\n  pared a {P.MURO_DIST:.2f} m: en la escena vacia su eco "
                  f"cae en {f_muro:.0f} Hz. Una placa a menos de ~{bin_cm:.0f} "
                  f"cm (c/2BW) de la pared da un pico que no se separa del de "
                  f"la pared.")
        print(f"\n  tabla -> {csv}")

    # --- figura 1: f contra d, armada de a un paso ---------------------------
    # 1) el radar ideal (recta por el origen), 2-4) se le suma cada retardo,
    # que la corre para arriba sin cambiarle la pendiente, 5) las mediciones.
    fig = plt.figure(figsize=(14, 9.5))
    gs = fig.add_gridspec(2, 2, width_ratios=[2.3, 1], height_ratios=[2.4, 1],
                          hspace=0.36, wspace=0.22, left=0.06, right=0.97,
                          top=0.90, bottom=0.07)
    ax = fig.add_subplot(gs[0, 0])
    x = np.linspace(0, max(ds) + 0.1, 50)
    pasos = [
        ("① radar ideal: f = 4B/(c·Tprf)·d", 0.0, "0.55", ":"),
        ("② + cables RG-213 (medidos con el VNA)", off["cables"], "C1", "--"),
        ("③ + bocinas y electrónica (sin separar) = SIMULACIÓN", tot, "k",
         "-"),
    ]
    for i, (eti, o, col, ls) in enumerate(pasos):
        ax.plot(x, hz_por_m * x + o, color=col, ls=ls,
                lw=1.6 if i == len(pasos) - 1 else 1.2, label=eti)
    ax.plot(ds, et[:, 2], "o", color="k", ms=4)
    # flechas de cada salto, en una distancia chica donde no hay datos
    xa = 0.15
    for (e0, o0, *_), (e1, o1, col, _ls) in zip(pasos[:-1], pasos[1:]):
        ax.annotate("", xy=(xa, hz_por_m * xa + o1),
                    xytext=(xa, hz_por_m * xa + o0),
                    arrowprops=dict(arrowstyle="->", color=col, lw=1.4))
        ax.text(xa + 0.02, hz_por_m * xa + (o0 + o1) / 2,
                f"+{o1 - o0:.0f} Hz", color=col, fontsize=8.5, va="center")
    for k in ("med_sin", "med_cong"):
        if k in series:
            eti, col, mk = SERIES[k]
            ax.plot(*series[k], mk, color=col, ms=8,
                    mfc=col if k == "med_sin" else "none", mew=1.6,
                    label=f"④ {eti}")
    if P.MURO_DIST > 0:
        ax.axvline(P.MURO_DIST, color="0.6", lw=0.8)
        ax.text(P.MURO_DIST, 20, " pared", color="0.4", fontsize=8,
                rotation=90, va="bottom", ha="right")
    ax.set_xlim(0, max(ds) + 0.1)
    ax.set_ylim(0, 1.12 * max(et[:, 2].max(), max(r["f_med"] for r in filas)))
    ax.set_xlabel("distancia real, de la boca de las bocinas a la placa [m]")
    ax.set_ylabel("frecuencia de batido del pico [Hz]")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8.3, loc="upper left")
    ax.set_title(f"Todas las rectas tienen la misma pendiente, {hz_por_m:.1f} "
                 "Hz/m: cada retardo solo las sube", fontsize=10)

    # el offset como barra apilada, simulado contra medido. Los cables son
    # el mismo numero en las dos (medido con el VNA); lo que se compara es
    # el resto, bocinas + electronica, que no se puede partir.
    axb = fig.add_subplot(gs[0, 1])
    bloques = [(0, off["cables"], resto, "simulado")]
    if "med_sin" in ajustes:
        f0_ = ajustes["med_sin"][1]
        bloques.append((1, off["cables"], f0_ - off["cables"], "medido"))
    for xb, cab_hz, rest_hz, nombre in bloques:
        axb.bar(xb, cab_hz, color="C1", alpha=0.75, width=0.6)
        axb.text(xb, cab_hz / 2, f"cables\n(VNA, medido)\n{cab_hz:.0f} Hz = "
                 f"{cab_hz/hz_por_m*100:.0f} cm", ha="center", va="center",
                 fontsize=8.5)
        col = "0.25" if nombre == "simulado" else "C0"
        axb.bar(xb, rest_hz, bottom=cab_hz, color=col, alpha=0.8, width=0.6)
        axb.text(xb, cab_hz + rest_hz / 2,
                 f"bocinas +\nelectrónica\n{rest_hz:.0f} Hz = "
                 f"{rest_hz/hz_por_m*100:.0f} cm", ha="center", va="center",
                 fontsize=8.5, color="w")
        axb.text(xb, cab_hz + rest_hz + 5,
                 f"{nombre} {cab_hz + rest_hz:.0f} Hz", ha="center",
                 va="bottom", fontsize=9, fontweight="bold")
    axb.text(0.5, -0.13, "simulado: bocinas de MEEP + interno "
             f"{P.TAU_INTERNO*1e9:g} ns ajustado\n"
             "medido: ordenada de la recta cf − cables",
             transform=axb.transAxes, ha="center", va="top", fontsize=7.5,
             color="0.3")
    axb.set_xticks([0, 1], ["simulado", "medido"])
    axb.set_xlim(-0.5, 1.5)
    axb.set_ylim(0, 1.15 * tot)
    axb.set_ylabel("offset: frecuencia con la placa en d = 0 [Hz]")
    axb.set_title("El offset: lo medido y lo que no se separa", fontsize=10)
    axb.grid(alpha=0.3, axis="y")

    # lo que interesa de verdad: cuanto se equivoca la simulacion
    axr = fig.add_subplot(gs[1, :])
    for k_med, cual in (("med_sin", "placa"), ("med_cong", "solo")):
        sel = [r for r in filas if r["cual"] == cual]
        if not sel:
            continue
        eti, col, mk = SERIES[k_med]
        dd = np.array([r["d"] for r in sel])
        dif = np.array([r["f_med"] - r["f_sim"] for r in sel])
        axr.plot(dd, dif, mk + "-", color=col, ms=7, lw=0.9,
                 mfc=col if k_med == "med_sin" else "none", label=eti)
    axr.axhline(0, color="k", lw=0.7)
    bin_hz = hz_por_m * R.C / (2 * alpha0 * R.T_SWEEP)
    axr.axhspan(-bin_hz / 2, bin_hz / 2, color="0.93", zorder=0,
                label=f"± medio bin de la FFT (c/2BW = "
                      f"{bin_hz/hz_por_m*100:.1f} cm)")
    if P.MURO_DIST > 0:
        axr.axvline(P.MURO_DIST, color="0.6", lw=0.8)
    axr.set_xlim(min(ds) - 0.05, max(ds) + 0.1)
    axr.set_xlabel("distancia real [m]")
    axr.set_ylabel("medido − simulado [Hz]")
    der = axr.secondary_yaxis("right", functions=(lambda h: h / hz_por_m * 100,
                                                  lambda c: c * hz_por_m / 100))
    der.set_ylabel("[cm]")
    axr.grid(alpha=0.3)
    axr.legend(fontsize=8, loc="lower left")
    axr.set_title("Cuánto se aparta la medición de la simulación en cada "
                  "distancia", fontsize=10)

    fig.suptitle("Placa metálica: frecuencia de batido contra distancia — "
                 f"banco (28-09-2026) y MEEP.  Pared a {P.MURO_DIST:.2f} m, "
                 f"rampa {R.T_SWEEP*1e3:g} ms, B = "
                 f"{alpha0*R.T_SWEEP/1e6:.0f} MHz", fontsize=11.5)
    d1 = R.guardar_figura(fig, os.path.join(P.SALIDAS, "relevamiento.png"))
    plt.close(fig)

    # --- figura 2: espectros por distancia -----------------------------------
    dists = sorted(sim)
    fig, axs = plt.subplots(len(dists), 2, figsize=(13, 2.3 * len(dists)),
                            sharex=True, sharey=True, squeeze=False)
    for i, d in enumerate(dists):
        for j, cual in enumerate(("placa", "solo")):
            a = axs[i, j]
            col = "C0" if cual == "placa" else "C3"
            p_med = None
            for r in filas:
                if r["d"] == d and r["cual"] == cual:
                    fm_, mg = r["curva"]
                    a.plot(fm_, db(mg, f=fm_), col, lw=1.5, label="medido")
                    a.axvline(r["f_med"], color="k", lw=0.6)
                    p_med = r["f_med"]
            hz_s, ee_s = sim[d][cual]
            p_sim = pico_hz(hz_s, ee_s)
            a.plot(hz_s, db(ee_s, f=hz_s), "0.35", lw=1.0, ls="--",
                   label="simulado")
            a.axvline(p_sim, color="0.35", lw=0.6, ls="--")
            txt = f"pico simulado  {p_sim:5.1f} Hz"
            if p_med is not None:
                dif = p_med - p_sim
                txt = (f"pico medido    {p_med:5.1f} Hz\n{txt}\n"
                       f"diferencia  {dif:+5.1f} Hz = {dif/hz_por_m*100:+.1f} cm")
            # a la derecha del pico, debajo de la leyenda
            a.text(0.985, 0.66, txt, transform=a.transAxes, ha="right",
                   va="top", fontsize=8, family="monospace", linespacing=1.3,
                   bbox=dict(fc="w", ec="0.7", alpha=0.9,
                             boxstyle="round,pad=0.35"))
            a.text(0.01, 0.9, f"{d*100:.0f} cm", transform=a.transAxes,
                   fontsize=9, fontweight="bold", va="top")
            a.grid(alpha=0.3)
            if i == 0:
                a.set_title("fondo sin medir (cf)  vs  escena completa"
                            if cual == "placa" else
                            "fondo congelado (sf)  vs  placa − vacío",
                            fontsize=9.5)
                a.legend(fontsize=7.5, loc="upper right")
    axs[0, 0].set_xlim(DESDE_HZ, 900)
    axs[0, 0].set_ylim(-45, 5)
    for a in axs[-1]:
        a.set_xlabel("frecuencia de batido [Hz]")
    for a in axs[:, 0]:
        a.set_ylabel("dB (pico = 0)", fontsize=8)
    fig.tight_layout()
    d2 = R.guardar_figura(fig, os.path.join(P.SALIDAS,
                                            "relevamiento_curvas.png"))
    plt.close(fig)
    print(f"\n  figuras -> {d1}\n             {d2}")
    R.anotar_para_abrir(d1)
    R.anotar_para_abrir(d2)


if __name__ == "__main__":
    main()
