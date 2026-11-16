"""
GPRv3 - Mirar una grabacion .gpr3
=================================

    python analizar.py [archivo.gpr3] [--valle 0] [--cima 100]
                       [--alcance 5] [--rampas 8] [--guardar figura.png]

Sin archivo toma la grabacion mas nueva de datos/. Tres paneles: el batido
crudo de las primeras rampas con los flancos del sync marcados, el perfil
promedio (subidas, bajadas y todas) y el radargrama.
"""

import argparse
import glob
import os

import numpy as np

import config as cfg
from fuentes import leer_grabacion
from modelo import Radar
from proceso import cargar_curva


def main():
    ap = argparse.ArgumentParser(description="GPRv3 - analizar una grabacion")
    ap.add_argument("archivo", nargs="?")
    ap.add_argument("--valle", type=float, default=0.0,
                    help="porcentaje de la rampa que se descarta desde el valle")
    ap.add_argument("--cima", type=float, default=100.0,
                    help="porcentaje de la rampa hasta donde se usa")
    ap.add_argument("--alcance", type=float, default=cfg.ALCANCE_DEF)
    ap.add_argument("--rampas", type=int, default=cfg.N_DEFECTO,
                    help="rampas promediadas por fila")
    ap.add_argument("--guardar", help="guarda la figura en vez de mostrarla")
    args = ap.parse_args()

    ruta = args.archivo
    if not ruta:
        todas = sorted(glob.glob(os.path.join(cfg.DATOS, "*.gpr3")),
                       key=os.path.getmtime)
        if not todas:
            raise SystemExit(f"No hay ninguna grabacion en {cfg.DATOS}")
        ruta = todas[-1]
    ev = leer_grabacion(ruta)
    if ev.info is None or not ev.muestras:
        raise SystemExit(f"{ruta}: no tiene muestras")
    sps = ev.info["sps"]
    total = sum(len(v) for _, v in ev.muestras)
    print(f"{os.path.basename(ruta)}: {sps} sps, {total} muestras "
          f"({total / sps:.1f} s), {len(ev.flancos)} flancos")
    if ev.meta:
        print("  " + ", ".join(f"{k}={v}" for k, v in ev.meta.items()))

    radar = Radar(cargar_curva())
    radar.fijar_ventana(args.valle / 100.0, args.cima / 100.0)
    radar.n_rampas = args.rampas
    radar.alcance = args.alcance
    radar.ventana = 1e9
    radar.en_metros = True
    radar.alimentar(ev)
    r = radar.resumen()
    if not radar.n_perf:
        raise SystemExit("No salio ninguna rampa valida: revisar el sync.")
    print(f"  Tprf {r['tprf'] * 1e3:.3f} ms (subida {r['t_subida'] * 1e3:.3f}, "
          f"bajada {r['t_bajada'] * 1e3:.3f}), {r['validas']} rampas validas, "
          f"{r['repetidos'] + r['fuera_de_rango'] + r['incoherentes']} "
          f"descartadas, {r['huecos']} huecos")
    print(f"  BW usada {r['bw'] / 1e6:.1f} MHz, resolucion "
          f"{r['resolucion'] * 100:.1f} cm, {r['hz_por_m']:.1f} Hz/m")

    import matplotlib
    if args.guardar:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 10),
                                     height_ratios=[1, 1, 1.6])
    # 1. El crudo con los flancos.
    idx0 = ev.muestras[0][0]
    n = int(min(4.2 * r["tprf"] * sps, total))
    crudo = np.concatenate([v for _, v in ev.muestras])[:n]
    a1.plot(np.arange(n) / sps * 1e3, crudo / 8388608 * 100, lw=0.7)
    for pos, nivel, _ in ev.flancos:
        if idx0 <= pos <= idx0 + n:
            a1.axvline((pos - idx0) / sps * 1e3, lw=1.0,
                       color="tab:red" if nivel else "tab:green")
    a1.set_xlabel("t [ms]   (rojo: el sync sube; verde: el sync baja)")
    a1.set_ylabel("batido [% FS]")
    a1.set_title(f"{os.path.basename(ruta)} - batido crudo y flancos del sync",
                 fontsize=10)

    # 2. El perfil promedio, por sentido.
    i1 = radar._i_alcance()
    d = radar.eje_m[:i1]
    ref = None
    for sentido, color in (("ambas", "k"), ("subida", "tab:blue"),
                           ("bajada", "tab:orange")):
        radar.sentido = sentido
        idx = radar._indices(1e9)
        if not len(idx):
            continue
        p = radar._promedio(idx)[:i1]
        ref = ref or float(p.max())
        a2.plot(d, 10 * np.log10(p / ref + 1e-24), color=color,
                lw=1.4 if sentido == "ambas" else 0.9, label=sentido)
    radar.sentido = "ambas"
    a2.set_ylim(-70, 3)
    a2.set_xlim(0, d[-1])
    a2.set_ylabel("dB")
    a2.grid(alpha=0.3)
    a2.legend(fontsize=8)
    a2.set_title("Perfil promedio de toda la grabación", fontsize=10)

    # 3. El radargrama.
    m = radar.matriz()
    im = a3.imshow(m["db"], aspect="auto", origin="upper", cmap="viridis",
                   extent=(m["d0"], m["d1"], m["span"], 0), vmin=-50, vmax=0)
    a3.set_xlim(0, d[-1])
    a3.set_xlabel("Distancia cruda [m]")
    a3.set_ylabel("t [s]")
    a3.set_title(f"Radargrama - {radar.n_ef} rampas por fila", fontsize=10)
    fig.colorbar(im, ax=a3, label="dB")
    fig.tight_layout()
    if args.guardar:
        fig.savefig(args.guardar, dpi=150)
        print(f"  figura -> {args.guardar}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
