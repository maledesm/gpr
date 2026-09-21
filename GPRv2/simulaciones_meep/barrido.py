"""
GPRv2 - Barrido de distancia de la placa: la pendiente tiene que dar 1
======================================================================

    wsl ... correr_meep.sh barrido     (una vez, deja salidas/H_placa_*.npz)
    python barrido.py

Es la version simulada de la verificacion de la seccion
`sec:cables_calibracion` de la tesis: con varios puntos a distancias
distintas se ajusta d_ap = a*d_real + b. Si a ~= 1, todo lo que no es aire
(cables, bocinas, retardo interno) es un OFFSET puro y alcanza con un punto
de calibracion. `b` es ese offset, y aca se lo puede partir en pedazos:

    b (sin cables)  = lo que agregan las bocinas y la geometria biestatica
    b (con cables)  - b (sin cables) = el offset de los cables

Resta la escena vacia (misma grilla) para quedarse con el eco de la placa.
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

DISTANCIAS = P.BARRIDO
RELLENO = 8


def main():
    curva = R.cargar_curva_vco(P.VCO_CSV)
    f, H_vacio = R.cargar("vacio_barrido")

    filas = []
    for d in DISTANCIAS:
        f2, H = R.cargar(f"placa_{d:.2f}".replace(".", "p"))
        H_solo = H - H_vacio
        fila = [d]
        for modo in ("ninguno", P.MODO_CABLE):
            rr, ee = R.perfil(f, R.aplicar_cadena(f, H_solo, modo),
                              relleno=RELLENO, curva=curva)
            pico, _ = R.pico(rr, ee, desde=0.3, hasta=6.0)
            fila.append(pico)
        filas.append(fila)
    tab = np.array(filas)

    d_bocina = P.LARGO_TOTAL - P.SONDA_FONDO
    print("=" * 70)
    print("Barrido de la placa: d_aparente = a * d_real + b")
    print("=" * 70)
    print(f"  {'d real':>7s} {'geom.':>7s} {'sin cables':>11s} {'con cables':>11s}")
    for d, s, c in tab:
        # camino geometrico biestatico: sonda->apertura + oblicuo a la placa
        geo = d_bocina + np.hypot(P.SEP_ANTENAS / 2, d)
        print(f"  {d:6.2f}m {geo:6.3f}m {s:10.3f}m {c:10.3f}m")

    print()
    ajustes = {}
    for k, nombre in ((1, "sin cables"), (2, "con cables")):
        a, b = np.polyfit(tab[:, 0], tab[:, k], 1)
        res = tab[:, k] - (a * tab[:, 0] + b)
        ajustes[nombre] = (a, b)
        print(f"  {nombre:11s}  a = {a:.4f}   b = {b:+.3f} m   "
              f"residuo rms {np.sqrt(np.mean(res**2))*1000:.1f} mm")

    b_cab = ajustes["con cables"][1] - ajustes["sin cables"][1]
    b_sin = ajustes["sin cables"][1]
    print()
    print(f"  offset de los cables (b con - b sin)  {b_cab:.3f} m   "
          f"(tesis, medido con VNA: {P.C0*P.tau_cables()/2:.3f} m)")
    print(f"  offset de bocinas + geometria         {b_sin:.3f} m   "
          f"(largo fisico sonda->apertura: {d_bocina:.3f} m)")
    print(f"    -> exceso sobre el largo fisico     {b_sin - d_bocina:+.3f} m "
          f"= {(b_sin - d_bocina)*2/P.C0*1e9:.2f} ns de ida y vuelta")

    # --- figura, en Hz como vivo_rapido -------------------------------------
    _t, _b, _th, alpha0 = R.sintetizar(f, H_vacio, curva=curva)
    hz_por_m = 2 * alpha0 / R.C
    print(f"\n  {hz_por_m:.1f} Hz por metro: la pendiente en Hz es "
          f"{ajustes['con cables'][0]*hz_por_m:.1f} Hz por metro de placa")

    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = np.linspace(min(DISTANCIAS) - 0.15, max(DISTANCIAS) + 0.1, 50)
    etiquetas = {"con cables": f"con cables ({P.MODO_CABLE}) — lo que mide el banco",
                 "sin cables": "sin cables (solo aire + bocinas)"}
    for k, nombre, col in ((2, "con cables", "C3"), (1, "sin cables", "C0")):
        a, b = ajustes[nombre]
        ax.plot(tab[:, 0], tab[:, k] * hz_por_m, "o", color=col, ms=7)
        ax.plot(x, (a * x + b) * hz_por_m, "-", color=col, lw=1,
                label=f"{etiquetas[nombre]}\n   {a*hz_por_m:.1f} Hz/m, "
                      f"arranca en {b*hz_por_m:.0f} Hz")
        for d, v in zip(tab[:, 0], tab[:, k]):
            ax.annotate(f"{v*hz_por_m:.0f} Hz", (d, v * hz_por_m),
                        textcoords="offset points", xytext=(6, -12),
                        fontsize=7.5, color=col)
    ax.plot(x, x * hz_por_m, "k:", lw=1,
            label="radar ideal: sin cables ni bocinas (4Bd/cT)")
    ax.set_xlabel("distancia real, de la boca de las bocinas a la placa [m]")
    ax.set_ylabel("frecuencia de batido del eco de la placa [Hz]")
    der = ax.secondary_yaxis("right", functions=(lambda h: h / hz_por_m,
                                                 lambda m: m * hz_por_m))
    der.set_ylabel("distancia aparente, sin calibrar [m]", fontsize=8)
    ax.set_ylim(0, None)
    ax.set_title(
        f"Moviendo la placa: el pico sube {ajustes['con cables'][0]*hz_por_m:.0f} "
        f"Hz por metro (pendiente ≈ 1)\n"
        "y todo lo demás —cables y bocinas— es un corrimiento fijo, que se "
        "saca calibrando con un punto", fontsize=9.5)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    destino = R.guardar_figura(
        fig, os.path.join(P.SALIDAS, "barrido_distancia.png"))
    print(f"\n  figura -> {destino}")
    R.anotar_para_abrir(destino)


if __name__ == "__main__":
    main()
