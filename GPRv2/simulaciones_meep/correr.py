"""
GPRv2 - Placa metalica: simulacion contra modelo
=================================================

    python correr.py          (o GPRv2/simular.bat, que ademas corre MEEP)

Junta las dos piezas:

  1. `escena.py` (WSL, env meep) simulo el AIRE: las dos bocinas y la placa,
     y dejo H(f) y tres fotos del campo en salidas/.
  2. `radar.py` le agrega los cables y el retardo interno, sintetiza el
     batido con el Tprf real y lo pasa por el pipeline de `analisis/`.

Escribe salidas/placa_<distancia>m.png y un resumen por consola.


Que es cada curva
-----------------

  placa          la escena completa. Es LO QUE MIDE EL RADAR: el acoplamiento
                 directo y todos los ecos de la placa juntos.
  vacio          la misma escena sin la placa: solo el acoplamiento directo
                 entre las bocinas. Es lo que guarda el boton "medir fondo" de
                 vivo_rapido.py con la sala vacia.
  solo la placa  placa - vacio, restado en complejo. Deja solo lo que produce
                 la placa. Sirve para separar los picos, no se mide.

Las tres van en dB respecto del pico de "placa", o sea con la MISMA
referencia: la diferencia de altura entre curvas es real.


Que es cada pico (A a E en la figura)
-------------------------------------

Identificados moviendo la placa en `barrido.py`: cada camino se corre con la
distancia de una forma distinta, y eso los delata. Medido el 2026-09-21,
corriendo la placa de 0,75 a 1,50 m de a 0,25:

  A  acoplamiento directo, TX -> aire -> RX. No se mueve con la placa.
  B  eco de la placa, TX -> placa -> RX. Se mueve 1x. El que se calibra.
  C  rebote en la boca de las bocinas: TX -> placa -> boca -> placa -> RX.
     Se mueve 2x y cae en B + distancia + ~0,1 m.
  D  segundo viaje completo: el eco entra a la bocina, rebota adentro y
     vuelve a salir. Cae en exactamente 2 veces B (sin cables) y se mueve 2x.
  E  tercer viaje completo, 3 veces B. Se mueve 3x.

D y E estan EXAGERADOS en la simulacion: en MEEP las bocinas son cavidades
metalicas cerradas, sin la carga de 50 ohm de la sonda, asi que devuelven
todo lo que les entra. En el banco la sonda se lleva buena parte.
"""

import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402
from matplotlib.colors import ListedColormap                      # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import parametros as P                                            # noqa: E402
import radar as R                                                 # noqa: E402

RELLENO = 8                          # igual que vivo_rapido.py
NS_POR_U = P.A_MEEP / P.C0 * 1e9     # ns por unidad de tiempo MEEP (0,5 ns)
PISO_DB = -70.0


def db_ref(x, ref):
    return 20 * np.log10(np.maximum(x, 1e-30) / ref)


# --- La escena -------------------------------------------------------------

def dibujar_foto(ax, d, k, titulo, cotas):
    """Una foto del campo Ez con el metal encima, en metros.

    El origen es el plano de la boca de las bocinas (y = 0), y la placa esta
    en y = distancia. Rojo y azul son el signo del campo; la escala se ajusta
    con lo que hay AFUERA de las bocinas, porque adentro de la de TX el campo
    es cien veces mas fuerte y taparia todo lo demas.
    """
    E = d["fotos"][k]
    eps = d["eps"]
    x0, x1, y0, y1 = d["extent_m"]
    pml = float(d["dpml_m"])
    ys = np.linspace(y0, y1, E.shape[1])
    fuera = E[:, ys > 0.05]
    v = np.percentile(np.abs(fuera), 99.5) if fuera.size else np.abs(E).max()
    v = v if v > 0 else 1.0

    ax.imshow(E.T, origin="lower", extent=d["extent_m"], cmap="RdBu_r",
              vmin=-v, vmax=v, interpolation="bilinear")
    metal = (eps < 0) | (eps > 1.5)
    ax.imshow(np.ma.masked_where(~metal, metal).T, origin="lower",
              extent=d["extent_m"], cmap=ListedColormap(["black"]),
              interpolation="nearest")
    ax.set_xlim(x0 + pml, x1 - pml)
    ax.set_ylim(y0 + pml, y1 - pml)
    ax.set_aspect("equal")
    ax.set_title(titulo, fontsize=9.5)
    ax.tick_params(labelsize=7)
    ax.set_xlabel("x [m]", fontsize=8)

    # Sondas: donde entra y donde se mide la senal
    y_s = P.SONDA_FONDO - P.LARGO_TOTAL
    for x, txt, col in ((-P.SEP_ANTENAS / 2, "TX", "#d62728"),
                        (+P.SEP_ANTENAS / 2, "RX", "#2ca02c")):
        ax.plot(x, y_s, "o", ms=5, color=col, mec="white", mew=0.8)
        ax.text(x, y_s + 0.03, txt, color=col, ha="center", va="bottom",
                fontsize=8, fontweight="bold")

    if cotas:
        dist = float(d["dist_placa"])
        xc = P.PLACA_ANCHO / 2 + 0.06
        ax.annotate("", xy=(xc, dist), xytext=(xc, 0.0),
                    arrowprops=dict(arrowstyle="<->", color="k", lw=0.9))
        ax.text(xc + 0.03, dist / 2, f"{dist:.2f} m", rotation=90,
                va="center", fontsize=8)
        ax.axhline(0.0, color="k", ls=":", lw=0.7)
        ax.text(x0 + pml + 0.02, 0.02, "boca de las bocinas", fontsize=7,
                va="bottom")
        ax.text(0, dist + 0.03, f"placa {P.PLACA_ANCHO*100:.1f} cm",
                ha="center", va="bottom", fontsize=7.5)
        ax.set_ylabel("y [m]", fontsize=8)


# --- Los picos -------------------------------------------------------------

def buscar_picos(rr, placa, solo, vacio, d_off):
    """Ubica A..E. Devuelve {letra: (distancia aparente, dB en 'placa')}.

    B se busca donde lo pone el modelo, con margen. Los rebotes se buscan
    donde los pone B: se conoce B en el AIRE (restando el offset de cables +
    interno, que se recorre una sola vez) y los rebotes son multiplos de eso.
    """
    ref = placa.max()
    d_boc = P.LARGO_TOTAL - P.SONDA_FONDO
    D = P.DIST_PLACA

    def en(curva, centro, ancho):
        d, _ = R.pico(rr, curva, desde=centro - ancho, hasta=centro + ancho)
        if not np.isfinite(d):
            return None
        i = np.argmin(np.abs(rr - d))
        return d, float(db_ref(placa[i], ref))

    picos = {}
    b = en(solo, D + d_boc + d_off + 0.15, 0.35)
    if b is None:
        return picos
    picos["B"] = b
    b_aire = b[0] - d_off
    picos["A"] = en(vacio, P.SEP_ANTENAS / 2 + d_boc + d_off, 0.3)
    picos["C"] = en(solo, b_aire + D + 0.1 + d_off, 0.25)
    picos["D"] = en(solo, 2 * b_aire + d_off, 0.25)
    picos["E"] = en(solo, 3 * b_aire + d_off, 0.25)
    return {k: v for k, v in picos.items()
            if v is not None and v[1] > PISO_DB + 10}


EXPLICACION = {
    "A": ("Acoplamiento directo",
          "TX → aire → RX, sin tocar la placa. No se mueve\n"
          "si movés la placa. En el banco es MUCHO más fuerte:\n"
          "ahí domina la fuga interna (splitter, mezclador),\n"
          "que MEEP no simula."),
    "B": ("Eco de la placa",
          "TX → placa → RX. Es el pico que se calibra.\n"
          "Se corre 1 a 1 con la placa."),
    "C": ("Rebote en la boca de las bocinas",
          "TX → placa → boca → placa → RX.\n"
          "Se corre el doble que la placa."),
    "D": ("Segundo viaje completo",
          "El eco entra a la bocina, rebota adentro y sale\n"
          "otra vez. EXAGERADO: en MEEP la bocina no tiene la\n"
          "carga de 50 Ω de la sonda y devuelve todo."),
    "E": ("Tercer viaje completo",
          "Una vuelta más que D, por el mismo motivo."),
}


def main():
    dp = np.load(os.path.join(P.SALIDAS, "H_placa.npz"))
    dv = np.load(os.path.join(P.SALIDAS, "H_vacio.npz"))
    f, H_placa, H_vacio = dp["f_hz"], dp["H"], dv["H"]
    if not np.allclose(f, dv["f_hz"]):
        raise SystemExit("las dos escenas no comparten el eje de frecuencia")
    if "fotos" not in dp.files:
        raise SystemExit("H_placa.npz es de una version vieja de escena.py "
                         "(sin fotos del campo): volver a correr MEEP.")
    if abs(float(dp["dist_placa"]) - P.DIST_PLACA) > 1e-6:
        raise SystemExit(
            f"H_placa.npz se simulo con la placa a {float(dp['dist_placa']):.2f} m "
            f"y el pedido es {P.DIST_PLACA:.2f} m: volver a correr MEEP.")

    # La placa sola: restar la escena vacia saca el acoplamiento directo y
    # deja los ecos de la placa.
    H_solo = H_placa - H_vacio

    curva = R.cargar_curva_vco(P.VCO_CSV)
    n = int(round(R.T_SWEEP * R.FS))
    perfiles = {}
    for nombre, Haire in (("placa", H_placa), ("vacio", H_vacio),
                          ("solo", H_solo)):
        for modo in ("ninguno", P.MODO_CABLE):
            rr, esp = R.perfil(f, R.aplicar_cadena(f, Haire, modo),
                               relleno=RELLENO, curva=curva)
            perfiles[(nombre, modo)] = (rr, esp)

    _t, _b, _theta, alpha0 = R.sintetizar(f, H_placa, curva=curva)
    hz_por_m = 2 * alpha0 / R.C
    bw = alpha0 * R.T_SWEEP
    d_boc = P.LARGO_TOTAL - P.SONDA_FONDO
    d_int = P.C0 * P.TAU_INTERNO / 2
    d_cab = 0.0 if P.MODO_CABLE == "ninguno" else P.C0 * P.tau_cables() / 2
    d_off = d_cab + d_int

    # --- consola: modelo contra simulado -----------------------------------
    pred = {
        "acoplamiento, sin cables": P.SEP_ANTENAS / 2 + d_boc + d_int,
        "acoplamiento, con cables": P.SEP_ANTENAS / 2 + d_boc + d_off,
        "placa, sin cables":        P.DIST_PLACA + d_boc + d_int,
        "placa, con cables":        P.DIST_PLACA + d_boc + d_off,
    }
    print("=" * 72)
    print(f"Placa metalica a {P.DIST_PLACA:.2f} m del plano de apertura")
    print("=" * 72)
    print(f"  rampa            {R.T_SWEEP*1e3:.0f} ms (Tprf {2*R.T_SWEEP*1e3:.0f} ms), "
          f"{n} muestras a {R.FS:.0f} sps")
    print(f"  alpha0           {alpha0/1e9:.2f} GHz/s = {hz_por_m:.1f} Hz por metro")
    print(f"  BW del VCO       {bw/1e6:.1f} MHz -> resolucion c/(2BW) = "
          f"{R.C/(2*bw)*100:.1f} cm")
    print(f"  bocina           agrega {d_boc:.3f} m de distancia aparente (largo fisico)")
    print(f"  cables ({P.MODO_CABLE})  {d_cab:.3f} m   |   tau interno "
          f"{P.TAU_INTERNO*1e9:.2f} ns = {d_int:.3f} m")
    print()
    print(f"  {'pico':28s} {'modelo':>9s} {'simulado':>9s} {'error':>8s} {'Hz':>8s}")
    print("  " + "-" * 66)
    casos = [
        ("acoplamiento, sin cables", ("vacio", "ninguno")),
        ("acoplamiento, con cables", ("vacio", P.MODO_CABLE)),
        ("placa, sin cables", ("solo", "ninguno")),
        ("placa, con cables", ("solo", P.MODO_CABLE)),
    ]
    for etiqueta, clave in casos:
        rr, ee = perfiles[clave]
        m = pred[etiqueta]
        d, _ = R.pico(rr, ee, desde=m - 0.3, hasta=m + 0.5)
        print(f"  {etiqueta:28s} {m:8.3f}m {d:8.3f}m {d-m:+7.3f}m "
              f"{d*hz_por_m:7.1f}")
    print("  (el 'error' de la placa es lo que agrega la bocina por encima de su")
    print("   largo fisico; ver barrido.py)")

    # --- figura ------------------------------------------------------------
    rr, placa = perfiles[("placa", P.MODO_CABLE)]
    _, vacio = perfiles[("vacio", P.MODO_CABLE)]
    _, solo = perfiles[("solo", P.MODO_CABLE)]
    hz = rr * hz_por_m
    ref = placa.max()
    picos = buscar_picos(rr, placa, solo, vacio, d_off)

    fig = plt.figure(figsize=(15.5, 11))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.25, 1], hspace=0.30,
                          wspace=0.12, left=0.05, right=0.985, top=0.93,
                          bottom=0.06)

    # arriba: la escena en tres instantes
    t_ns = dp["fotos_t"] * NS_POR_U
    titulos = [f"t = {t_ns[0]:.1f} ns: el pulso sale de TX",
               f"t = {t_ns[1]:.1f} ns: llega a la placa",
               f"t = {t_ns[2]:.1f} ns: vuelve el eco"]
    for k in range(3):
        ax = fig.add_subplot(gs[0, k])
        dibujar_foto(ax, dp, k, titulos[k], cotas=(k == 0))
        if k:
            ax.set_yticklabels([])

    # abajo a la izquierda: el espectro en Hz, como vivo_rapido
    ax = fig.add_subplot(gs[1, 0:2])
    ax.plot(hz, db_ref(placa, ref), color="C0", lw=1.8,
            label="placa  (lo que mide el radar)")
    ax.plot(hz, db_ref(vacio, ref), color="C1", lw=1.2,
            label="vacío  (sin placa: solo el acoplamiento)")
    ax.plot(hz, db_ref(solo, ref), color="C2", lw=1.0, ls="--",
            label="solo la placa  (placa − vacío)")
    for letra, (d, nivel) in picos.items():
        h = d * hz_por_m
        ax.annotate(f"{letra}\n{h:.0f} Hz", xy=(h, nivel),
                    xytext=(h, nivel + 5), ha="center", va="bottom",
                    fontsize=9.5, fontweight="bold", linespacing=1.1,
                    arrowprops=dict(arrowstyle="-", lw=0.7, color="k"))
    h_max = max([d for d, _ in picos.values()] + [3.0]) * hz_por_m
    ax.set_xlim(0, min(h_max + 150, R.FS / 2))
    ax.set_ylim(PISO_DB, 18)          # lugar arriba para el rotulo de B
    ax.set_xlabel("frecuencia de batido [Hz]")
    ax.set_ylabel("dB respecto del pico de la placa")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    top = ax.secondary_xaxis("top", functions=(lambda h: h / hz_por_m,
                                               lambda m: m * hz_por_m))
    top.set_xlabel("distancia aparente, sin calibrar [m]", fontsize=8)
    top.tick_params(labelsize=7)
    ax.set_title(f"Espectro de batido con cables ({P.MODO_CABLE}) — "
                 f"{hz_por_m:.1f} Hz por metro", fontsize=10)

    # abajo a la derecha: que es cada pico
    axt = fig.add_subplot(gs[1, 2])
    axt.axis("off")
    y = 1.0
    axt.text(0, y, "Qué es cada pico", fontsize=11, fontweight="bold",
             va="top", transform=axt.transAxes)
    y -= 0.08
    for letra in "ABCDE":
        if letra not in picos:
            continue
        d, nivel = picos[letra]
        tit, cuerpo = EXPLICACION[letra]
        axt.text(0, y, f"{letra}  {tit}", fontsize=8.8, fontweight="bold",
                 va="top", transform=axt.transAxes)
        axt.text(1.0, y, f"{d*hz_por_m:.0f} Hz  {nivel:+.0f} dB",
                 fontsize=8.3, va="top", ha="right", family="monospace",
                 transform=axt.transAxes)
        y -= 0.05
        axt.text(0.05, y, cuerpo, fontsize=7.6, va="top", linespacing=1.3,
                 transform=axt.transAxes)
        y -= 0.043 * (cuerpo.count("\n") + 1) + 0.035
    axt.text(0, y, "Las tres curvas usan la misma referencia de dB.\n"
                   "Simulación 2D: las POSICIONES valen, los niveles\n"
                   "no se comparan directo con el banco.",
             fontsize=7.3, va="top", style="italic", color="0.3",
             transform=axt.transAxes)

    fig.suptitle(
        f"Placa metálica a {P.DIST_PLACA:.2f} m — MEEP 2D + cadena de RF del "
        f"banco  (rampa {R.T_SWEEP*1e3:.0f} ms, cables {P.MODO_CABLE}, "
        f"τ interno {P.TAU_INTERNO*1e9:.1f} ns)", fontsize=12)
    destino = R.guardar_figura(
        fig, os.path.join(P.SALIDAS, f"placa_{P.DIST_PLACA:.2f}m.png"))
    print(f"\n  figura -> {destino}")
    R.anotar_para_abrir(destino)


if __name__ == "__main__":
    main()
