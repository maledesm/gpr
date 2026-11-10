"""
GPRv2 - Paso 4.5 con MEEP: el mismo pasabajos que en ../openems/, para comparar
================================================================================

Mismas medidas (../diseno_hong.json) y el mismo planteo que openEMS, con lo que MEEP
permite (malla uniforme, sin puertos microstrip hechos):

  - unidad de longitud a = 1 mm; frecuencia en unidades de c/a (1 = 299,79 GHz)
  - masa: la pared de abajo de la celda (MEEP pone PEC en toda pared sin PML)
  - sustrato FR4 de 1,6 mm en toda la celda; PML en x, en y y arriba
  - pistas de metal perfecto (mp.metal) de 1 pixel de espesor (MEEP no tiene laminas de espesor cero)
  - excitacion: fuente Ez entre la linea de 50 ohm y la masa, a lo ancho de la pista (puerto 1)
  - parametros S por flujo de potencia, en dos corridas: una linea recta de 50 ohm de referencia
    (da la potencia incidente y permite restarla para medir la reflejada) y el filtro.
    |S21|^2 = P_trans(filtro) / P_inc ;  |S11|^2 = P_refl(filtro) / P_inc
    (solo modulos: el flujo no da fase)

Uso (en WSL):
  /opt/miniforge/envs/meep/bin/python simular_filtro_meep.py A --res 8
Resultados en resultados/<diseno>_res<r>/ (s.npz, metricas.json, cortes del modelo sacados de MEEP).
"""
import os, sys, json, time, argparse
import numpy as np
import meep as mp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
DISENO = os.path.join(AQUI, "..", "diseno_hong.json")
C_GHZ = 299.792458          # c/a en GHz con a = 1 mm
ER, H = 4.4, 1.6
L_FEED = 10.0
AIRE_Y, AIRE_Z, TPML = 6.0, 6.0, 3.0
FMAX = 7.0                  # GHz
LADOS = {"A_n5": [1, 1], "B_n7": [1, -1, 1]}


def geometria(r, recorte=1.0):
    """recorte: factor sobre el largo de los stubs (igual que en openems/simular_filtro.py)"""
    li = r["lineas"]
    wL, wC, w0 = li["W_L_mm"], li["W_C_mm"], li["W_0_mm"]
    rects, x, js = [], 0.0, []
    for i, l in enumerate(r["l_serie_mm"]):
        rects.append([x, x + l, -wL / 2, wL / 2])
        x += l
        if i < len(r["stubs"]):
            js.append(x)
    largo = x
    for xj, s, sg in zip(js, r["stubs"], LADOS[r["nombre"]]):
        lt, lp = s["lL_corregido_mm"] * recorte, s["lC_final_mm"] * recorte
        y1, y2, y3 = wL / 2, wL / 2 + lt, wL / 2 + lt + lp
        rects.append([xj - wL / 2, xj + wL / 2] + sorted([sg * y1, sg * y2]))
        rects.append([xj - wC / 2, xj + wC / 2] + sorted([sg * y2, sg * y3]))
    return rects, largo, w0


def armar(r, res, con_filtro, recorte=1.0):
    rects, largo, w0 = geometria(r, recorte)
    ymin = min(q[2] for q in rects) - AIRE_Y - TPML
    ymax = max(q[3] for q in rects) + AIRE_Y + TPML
    x0, x1 = -L_FEED - TPML, largo + L_FEED + TPML
    sx, sy, sz = x1 - x0, ymax - ymin, H + AIRE_Z + TPML
    cx, cy = (x0 + x1) / 2, (ymin + ymax) / 2
    z0 = -sz / 2                                   # pared de abajo = masa
    P = lambda x, y, z: mp.Vector3(x - cx, y - cy, z + z0)   # fisicas (z desde la masa) -> celda
    t_m = 1.0 / res
    geo = [mp.Block(center=P(cx, cy, H / 2), size=mp.Vector3(mp.inf, mp.inf, H), material=mp.Medium(epsilon=ER))]
    # lineas de 50 ohm (en la corrida de referencia, una sola linea recta de punta a punta)
    if con_filtro:
        tramos = [[x0, 0.0, -w0 / 2, w0 / 2], [largo, x1, -w0 / 2, w0 / 2]] + rects
    else:
        tramos = [[x0, x1, -w0 / 2, w0 / 2]]
    for a, b, c, d in tramos:
        geo.append(mp.Block(center=P((a + b) / 2, (c + d) / 2, H + t_m / 2), size=mp.Vector3(b - a, d - c, t_m),
                            material=mp.metal))
    fcen, df = (FMAX / 2) / C_GHZ, FMAX / C_GHZ
    x_src = -L_FEED + 1.5
    src = [mp.Source(mp.GaussianSource(fcen, fwidth=df), component=mp.Ez,
                     center=P(x_src, 0, H / 2), size=mp.Vector3(0, w0, H))]
    pml = [mp.PML(TPML, direction=mp.X), mp.PML(TPML, direction=mp.Y), mp.PML(TPML, direction=mp.Z, side=mp.High)]
    sim = mp.Simulation(cell_size=mp.Vector3(sx, sy, sz), geometry=geo, sources=src, boundary_layers=pml,
                        resolution=res, eps_averaging=False)
    nf = 351
    mon = dict(size=mp.Vector3(0, 6 * w0, 4 * H))
    x_ref, x_tr = -2.0, largo + 2.0
    fr = sim.add_flux(fcen, df, nf, mp.FluxRegion(center=P(x_ref, 0, 2 * H), **mon))
    ft = sim.add_flux(fcen, df, nf, mp.FluxRegion(center=P(x_tr, 0, 2 * H), **mon))
    info = dict(cx=cx, cy=cy, z0=z0, sx=sx, sy=sy, sz=sz, x_src=x_src, x_ref=x_ref, x_tr=x_tr, largo=largo,
                P=P, celdas_M=sx * sy * sz * res**3 / 1e6)
    return sim, fr, ft, info


def correr(sim, info, punto):
    sim.run(until_after_sources=mp.stop_when_fields_decayed(20, mp.Ez, punto, 1e-3))


def cortes(sim, info, ruta, r):
    """vistas del modelo sacadas de MEEP (epsilon y metal tal como estan en la grilla)"""
    P = info["P"]
    fig, ax = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw={"width_ratios": [1.4, 1]})
    sim.plot2D(ax=ax[0], output_plane=mp.Volume(center=P(info["cx"], info["cy"], H + 0.5 / sim.resolution),
                                                 size=mp.Vector3(info["sx"], info["sy"], 0)))
    ax[0].set_title("Corte xy en z = h (pistas, fuente, monitores, PML)", loc="left")
    sim.plot2D(ax=ax[1], output_plane=mp.Volume(center=P(info["cx"], 0, info["sz"] / 2),
                                                size=mp.Vector3(info["sx"], 0, info["sz"])))
    ax[1].set_title("Corte xz en y = 0", loc="left")
    fig.tight_layout()
    if mp.am_master():
        fig.savefig(ruta, dpi=110)
    plt.close(fig)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("diseno", choices=["A", "B"])
    a.add_argument("--res", type=int, default=8, help="pixeles por mm")
    a.add_argument("--recorte", type=float, default=1.0, help="factor sobre el largo de los stubs")
    x = a.parse_args()
    nombre = {"A": "A_n5", "B": "B_n7"}[x.diseno]
    r = json.load(open(DISENO, encoding="utf-8"))[nombre]
    tag = f"{nombre}_res{x.res}" + (f"_rec{x.recorte:g}" if x.recorte != 1 else "")
    out = os.path.join(AQUI, "resultados", tag)
    os.makedirs(out, exist_ok=True)
    t0 = time.time()

    # 1) referencia: linea recta de 50 ohm
    sim, fr, ft, info = armar(r, x.res, False, x.recorte)
    print(f"[{tag}] celda {info['sx']:.1f} x {info['sy']:.1f} x {info['sz']:.1f} mm, "
          f"{info['celdas_M']:.1f} M celdas", flush=True)
    correr(sim, info, info["P"](info["x_tr"], 0, H / 2))
    inc_r = mp.get_fluxes(fr)
    inc_t = np.array(mp.get_fluxes(ft))
    datos_ref = sim.get_flux_data(fr)
    f = np.array(mp.get_flux_freqs(fr)) * C_GHZ
    sim.reset_meep()

    # 2) filtro
    sim, fr, ft, info = armar(r, x.res, True, x.recorte)
    sim.load_minus_flux_data(fr, datos_ref)
    cortes(sim, info, os.path.join(out, "modelo_meep.png"), r)
    correr(sim, info, info["P"](info["x_tr"], 0, H / 2))
    refl = -np.array(mp.get_fluxes(fr))
    tran = np.array(mp.get_fluxes(ft))
    s21 = np.sqrt(np.clip(tran / inc_t, 0, None))
    s11 = np.sqrt(np.clip(refl / np.array(inc_r), 0, None))
    dur = time.time() - t0

    if not mp.am_master():
        return
    np.savez(os.path.join(out, "s.npz"), f=f * 1e9, s11=s11, s21=s21, inc_t=inc_t)
    d = 20 * np.log10(s21 + 1e-12)
    m = dict(diseno=nombre, res_px_mm=x.res, recorte=x.recorte, celdas_M=info["celdas_M"], minutos=dur / 60,
             procesos=mp.count_processors(),
             borde_1dB_GHz=float(f[np.argmax((f > 1) & (d < -1))]),
             atenuacion_min_2p36_4GHz_dB=float(-d[(f >= 2.36) & (f <= 4)].max()),
             espurio_max_4_7GHz_dB=float(d[(f >= 4) & (f <= 7)].max()),
             ceros_GHz=[float(f[i]) for i in range(1, len(f) - 1)
                        if d[i] < d[i - 1] and d[i] < d[i + 1] and d[i] < -25 and f[i] > 2])
    json.dump(m, open(os.path.join(out, "metricas.json"), "w"), indent=2)
    print(json.dumps(m, indent=1), flush=True)


if __name__ == "__main__":
    main()
