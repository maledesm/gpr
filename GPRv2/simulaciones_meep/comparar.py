"""
GPRv2 - Superponer una medicion del banco con la simulacion
============================================================

    cd salidas/<corrida>
    python ../../comparar.py ../../../datos/capturas/placa_90cm_cf.csv ...

Lee los CSV que guarda `vivo_rapido.py` con la tecla 's' (junto al PNG) y
los dibuja encima de la simulacion de ESA corrida. Escribe comparacion.png
en la carpeta de la corrida.

Que se compara con que
----------------------

El CSV trae en la cabecera si el fondo estaba medido, y de eso depende con
cual curva de la simulacion hay que compararlo:

    fondo = sin medir   ->  curva `placa`         (la escena completa)
    fondo = congelado   ->  curva `solo la placa` (placa - vacio)

⚠️ No es exactamente la misma resta. El banco resta MAGNITUDES con piso en
cero (no hay cancelacion coherente posible: lo que guarda son modulos de
FFT). La simulacion resta H complejo, que si cancela. Donde el fondo y el
blanco se superponen, las dos restas dan cosas distintas.

El eje comun es la DISTANCIA CRUDA, sin calibrar (columna d_crudo_m), que es
lo unico que no depende de una calibracion guardada en el banco. De ahi a Hz
con el alpha0 de cada lado, que son el mismo si el Tprf coincide.

Cada curva se normaliza a SU propio pico: los dB del banco estan referidos a
algo que cambia (el maximo de la pantalla, o el pico del fondo) y la
simulacion 2D no tiene los niveles absolutos bien de todas formas. Lo que se
compara es DONDE caen los picos y la forma, no cuanto valen.
"""

import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import parametros as P                                            # noqa: E402
import radar as R                                                 # noqa: E402

RELLENO = 8
DESDE_HZ = 100.0          # por debajo no se busca pico: ahi vive la continua


def leer_csv(ruta):
    """(cabecera dict, f_hz, mag) de un CSV de vivo_rapido.py."""
    cab = {}
    filas = []
    with open(ruta, encoding="utf-8") as fh:
        columnas = None
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            if linea.startswith("#"):
                if "=" in linea:
                    k, v = linea[1:].split("=", 1)
                    cab[k.strip()] = v.strip()
                continue
            if columnas is None:
                columnas = linea.split(",")
                continue
            filas.append([float(x) for x in linea.split(",")])
    if not filas:
        raise SystemExit(f"{ruta}: no tiene datos")
    d = np.array(filas)
    col = {n: i for i, n in enumerate(columnas)}
    return cab, d[:, col["f_hz"]], d[:, col["mag"]]


def pico_hz(f, y, desde=DESDE_HZ):
    m = f >= desde
    i = np.flatnonzero(m)[np.argmax(y[m])]
    if 0 < i < len(y) - 1:                      # parabola sobre el log
        y0, y1, y2 = np.log(np.maximum(y[i - 1:i + 2], 1e-300))
        den = y0 - 2 * y1 + y2
        if den < 0:
            return f[i] + 0.5 * (y0 - y2) / den * (f[1] - f[0])
    return f[i]


def db(y, desde_f=None, f=None):
    ref = y[f >= DESDE_HZ].max() if f is not None else y.max()
    return 20 * np.log10(np.maximum(y, 1e-30) / ref)


def main():
    rutas = sys.argv[1:]
    if not rutas:
        raise SystemExit(__doc__)

    f_sim, H_placa = R.cargar("placa")
    _, H_vacio = R.cargar("vacio")
    curva = R.cargar_curva_vco(P.VCO_CSV)
    sim = {}
    for nombre, H in (("placa", H_placa), ("solo", H_placa - H_vacio)):
        rr, ee = R.perfil(f_sim, R.aplicar_cadena(f_sim, H, P.MODO_CABLE),
                          relleno=RELLENO, curva=curva)
        sim[nombre] = (rr, ee)
    _t, _b, _th, alpha0 = R.sintetizar(f_sim, H_placa, curva=curva)
    hz_por_m = 2 * alpha0 / R.C

    fig, ax = plt.subplots(figsize=(14, 7))
    colores = ["C0", "C3", "C2", "C4"]
    print("=" * 74)
    print(f"Medicion contra simulacion - placa a {P.DIST_PLACA:.2f} m")
    print("=" * 74)
    print(f"  {'captura':26s} {'fondo':11s} {'medido':>9s} {'simulado':>9s} "
          f"{'dif':>8s}")
    print("  " + "-" * 68)

    for k, ruta in enumerate(rutas):
        cab, f_med, mag = leer_csv(ruta)
        fondo = cab.get("fondo", "?")
        cual = "placa" if fondo.startswith("sin") else "solo"
        nombre = os.path.basename(ruta)

        # El alpha0 del banco viene en la cabecera; si difiere del de la
        # simulacion, los ejes en Hz no son comparables y hay que avisar.
        a_banco = float(cab.get("alpha0_hz_s", alpha0))
        if abs(a_banco - alpha0) / alpha0 > 0.01:
            print(f"  [!] {nombre}: alpha0 del banco {a_banco/1e9:.3f} GHz/s "
                  f"contra {alpha0/1e9:.3f} de la simulacion ({100*(a_banco/alpha0-1):+.1f} %). "
                  f"Las frecuencias NO son comparables directo.")

        rr, ee = sim[cual]
        f_s = rr * hz_por_m
        p_med, p_sim = pico_hz(f_med, mag), pico_hz(f_s, ee)
        print(f"  {nombre:26s} {fondo:11s} {p_med:8.1f}Hz {p_sim:8.1f}Hz "
              f"{p_med-p_sim:+7.1f}Hz")
        print(f"  {'':26s} {'':11s} {p_med/hz_por_m:8.3f}m {p_sim/hz_por_m:8.3f}m "
              f"{(p_med-p_sim)/hz_por_m*100:+6.1f}cm")

        col = colores[k % len(colores)]
        eti = "cruda" if cual == "placa" else "fondo restado"
        ax.plot(f_med, db(mag, f=f_med), col, lw=1.8,
                label=f"MEDIDO  {nombre}  ({eti})")
        ax.plot(f_s, db(ee, f=f_s), col, lw=1.2, ls="--",
                label=f"simulado  {'placa' if cual=='placa' else 'placa − vacío'}")
        for x, y, ls in ((p_med, 3, "-"), (p_sim, 3, "--")):
            ax.axvline(x, color=col, ls=ls, lw=0.7, alpha=0.5)

    ax.set_xlim(0, min(1.6 * max(p_med, p_sim), R.FS / 2))
    ax.set_ylim(-60, 8)
    ax.set_xlabel("frecuencia de batido [Hz]")
    ax.set_ylabel("dB respecto del pico de cada curva")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8.5, loc="upper right")
    top = ax.secondary_xaxis("top", functions=(lambda h: h / hz_por_m,
                                               lambda m: m * hz_por_m))
    top.set_xlabel("distancia aparente, sin calibrar [m]", fontsize=8)
    top.tick_params(labelsize=7)
    fig.suptitle(
        f"Banco contra simulación — placa a {P.DIST_PLACA:.2f} m, "
        f"pared a {P.MURO_DIST:.2f} m\n"
        f"rampa {R.T_SWEEP*1e3:g} ms, {hz_por_m:.1f} Hz/m — cada curva "
        f"normalizada a su propio pico", fontsize=11)
    fig.tight_layout()
    destino = R.guardar_figura(fig, os.path.join(P.SALIDAS, "comparacion.png"))
    print(f"\n  figura -> {destino}")
    R.anotar_para_abrir(destino)


if __name__ == "__main__":
    main()
