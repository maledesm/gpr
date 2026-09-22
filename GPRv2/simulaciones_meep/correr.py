"""
GPRv2 - Placa metalica: simulacion contra modelo
=================================================

    python correr.py          (o GPRv2/simular.bat, que ademas corre MEEP)

Junta las dos piezas:

  1. `escena.py` (WSL, env meep) simulo el AIRE: las dos bocinas y la placa,
     y dejo H(f) y tres fotos del campo en la carpeta de la corrida.
  2. `radar.py` le agrega los cables y el retardo interno, sintetiza el
     batido con el Tprf real y lo pasa por el pipeline de `analisis/`.

Escribe en la carpeta de la corrida (salidas/<NOMBRE>/, ver parametros.py):

    escena.png          el campo Ez en tres instantes
    espectro.png        la FFT en Hz, con cada pico explicado
    resumen_placa.txt   lo mismo que la consola, con los parametros usados


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


Que es cada pico (letras de la figura)
--------------------------------------

Identificados moviendo la placa en `barrido.py`: cada camino se corre con la
distancia de una forma distinta, y eso los delata. Un camino que va N veces
a la placa se corre N veces lo que se mueve la placa. Medido el 2026-09-21,
corriendo la placa de 0,75 a 1,50 m de a 0,25, con las dos sondas:

  A   acoplamiento directo, TX -> aire -> RX. No se mueve con la placa.
  B   eco de la placa, TX -> placa -> RX. Se corre 1x. El que se calibra.
  C   un rebote en la BOCA de las bocinas (el metal de alrededor de la
      apertura): TX -> placa -> boca -> placa -> RX. Se corre 2x.
  D   un rebote ADENTRO de una bocina: el eco entra, vuelve a salir y hace
      otro viaje a la placa. Se corre 2x. Con el corto cae en 2 veces B
      (rebota en el fondo); con la sonda adaptada, ~15 cm antes (lo que
      queda son las paredes, antes de llegar a la sonda).
  C2  dos rebotes en la boca: cae en B + 2*(C - B). Se corre 3x.
  CD  un rebote en la boca y otro adentro: cae en C + D - B. Se corre 3x.
  E   dos rebotes adentro (tercer viaje completo): 3 veces B. Se corre 3x.

Todos los rebotes de "adentro" (D, CD, E) dependen de la carga de la sonda
(SONDA en parametros.py), porque es la sonda la que se los lleva:

                    D        C2       CD       E       (dB respecto de B,
    corto         -4 dB    -20 dB   -12 dB   -12 dB     placa a 1 m)
    adaptada     -30 dB    -26 dB    --      -37 dB

Con el corto la bocina es una cavidad cerrada, sin la carga de 50 ohm, y
devuelve todo: D sale casi tan alto como el eco. Con la sonda adaptada lo
que llega a la sonda se absorbe. El banco esta entre los dos. A, B, C y C2
no rebotan adentro de las bocinas: sus niveles casi no cambian, pero se
corren ~6 cm porque sin corto cambia el centro de fase de la bocina.
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
    for x, y_s, txt, col in (
            (-P.SEP_ANTENAS / 2, P.SONDA_TX - P.LARGO_TOTAL, "TX", "#d62728"),
            (+P.SEP_ANTENAS / 2, P.SONDA_RX - P.LARGO_TOTAL, "RX", "#2ca02c")):
        ax.plot(x, y_s, "o", ms=5, color=col, mec="white", mew=0.8)
        ax.text(x, y_s + 0.03, txt, color=col, ha="center", va="bottom",
                fontsize=8, fontweight="bold")
        # Sonda adaptada: la guia no tiene corto y sigue hasta el PML, que
        # hace de carga de 50 ohm. Se marca para que no parezca un error.
        if cotas and P.SONDA == "adaptada":
            ax.annotate("", xy=(x, y_s - 0.15), xytext=(x, y_s - 0.03),
                        arrowprops=dict(arrowstyle="->", color="0.25",
                                        lw=0.9))
            ax.text(x + 0.012, y_s - 0.10, "a la\ncarga\n50 Ω", fontsize=6.5,
                    va="center", color="0.25", linespacing=1.0)

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

RELEVANTE_DB = -40.0   # los rebotes mas debiles que esto no se rotulan


def buscar_picos(rr, placa, solo, vacio, d_off):
    """Ubica los picos con nombre. Devuelve {letra: (distancia, dB en 'placa')}.

    B se busca donde lo pone el modelo, con margen. Los rebotes se buscan
    donde los ponen los anteriores, trabajando en el AIRE (restando el offset
    de cables + interno, que se recorre una sola vez por camino, sin importar
    cuantas veces se vaya a la placa):

        C   B + distancia + ~0,1          (un rebote en la boca)
        D   2 veces B                     (un rebote adentro, con el corto)
        C2  B + 2*(C - B)                 (dos rebotes en la boca)
        CD  C + D - B                     (uno y uno)
        E   3 veces B                     (dos rebotes adentro)

    Solo cuenta un maximo LOCAL de verdad: si lo mas alto de la ventana cae
    en su borde, es la falda de otro pico y no se rotula. Y los rebotes mas
    debajo de RELEVANTE_DB tampoco, para no ponerle nombre al piso.
    """
    ref = placa.max()
    d_boc = P.d_bocina()
    D = P.DIST_PLACA

    def en(curva, centro, ancho):
        # El maximo LOCAL mas alto de la ventana, no el maximo a secas: al
        # lado de un pico grande (D con el corto, a -4 dB) la falda de ese
        # pico puede ser mas alta que el rebote que se busca, y el maximo a
        # secas caeria en el borde de la ventana.
        m = np.flatnonzero((rr >= centro - ancho) & (rr <= centro + ancho))
        m = m[(m > 0) & (m < len(curva) - 1)]
        locales = [i for i in m
                   if curva[i] > curva[i - 1] and curva[i] >= curva[i + 1]]
        if not locales:
            return None
        i = max(locales, key=lambda k: curva[k])
        d = R.pico(rr, curva, desde=rr[i - 1], hasta=rr[i + 1])[0]
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
    if picos["C"]:
        c_aire = picos["C"][0] - d_off
        picos["C2"] = en(solo, 2 * c_aire - b_aire + d_off, 0.2)
        if picos["D"]:
            d_aire = picos["D"][0] - d_off
            picos["CD"] = en(solo, c_aire + d_aire - b_aire + d_off, 0.2)
    # A se rotula siempre que exista: es chico en MEEP, pero es el que en el
    # banco domina la pantalla, y hay que poder señalarlo.
    return {k: v for k, v in picos.items()
            if v is not None and (k in "AB" or v[1] > RELEVANTE_DB)}


EXPLICACION = {
    "A": ("Acoplamiento directo",
          "TX → aire → RX, sin tocar la placa. No se mueve\n"
          "con la placa. En el banco es MUCHO más fuerte:\n"
          "domina la fuga interna, que MEEP no simula."),
    "B": ("Eco de la placa",
          "TX → placa → RX. Es el pico que se calibra.\n"
          "Se corre 1 a 1 con la placa."),
    "C": ("Rebote en la boca de las bocinas",
          "TX → placa → boca → placa → RX.\n"
          "Se corre el doble que la placa."),
    "D": ("Rebote adentro de una bocina",
          "Entra, rebota en el corto del fondo y sale a\n"
          "hacer otro viaje. Se corre el doble. EXAGERADO:\n"
          "sin la carga de 50 Ω la bocina devuelve todo."),
    "C2": ("Dos rebotes en la boca",
           "placa → boca → placa → boca → placa.\n"
           "Se corre el triple que la placa."),
    "CD": ("Un rebote en la boca y uno adentro",
           "C y D en el mismo camino (C + D − B).\n"
           "Se corre el triple que la placa."),
    "E": ("Dos rebotes adentro",
          "Tercer viaje completo, 3 veces B.\n"
          "Se corre el triple que la placa."),
}
# Con la sonda adaptada lo que llega a la sonda se lo lleva la carga: D cae
# de -4 a -30 dB y E de -12 a -37 (placa a 1 m, 2026-09-21), y lo que queda
# de D es lo que las paredes reflejan ANTES de la sonda.
if P.SONDA == "adaptada":
    EXPLICACION["D"] = (
        "Rebote adentro de una bocina",
        "Entra y vuelve a salir a hacer otro viaje. Con la\n"
        "carga de 50 Ω solo vuelve lo que reflejan las\n"
        "paredes antes de la sonda. Se corre el doble.")
    EXPLICACION["E"] = (
        "Dos rebotes adentro",
        "Tercer viaje completo, 3 veces B. Con la carga\n"
        "casi no queda.")


def figura_escena(dp):
    """escena.png: el campo Ez en tres instantes, con el metal encima."""
    fig, axs = plt.subplots(1, 3, figsize=(13, 7.4), sharey=True,
                            gridspec_kw=dict(wspace=0.06, left=0.06,
                                             right=0.99, top=0.88,
                                             bottom=0.10))
    t_ns = dp["fotos_t"] * NS_POR_U
    titulos = [f"t = {t_ns[0]:.1f} ns: el pulso sale de TX",
               f"t = {t_ns[1]:.1f} ns: llega a la placa",
               f"t = {t_ns[2]:.1f} ns: vuelve el eco"]
    for k, ax in enumerate(axs):
        dibujar_foto(ax, dp, k, titulos[k], cotas=(k == 0))
    fig.text(0.5, 0.025,
             "Rojo y azul: signo del campo Ez (la escala se ajusta afuera de "
             "las bocinas).  Negro: metal.  El origen de y es la boca de las "
             "bocinas.", ha="center", fontsize=8.5, color="0.3")
    fig.suptitle(
        f"Escena MEEP 2D — placa de {P.PLACA_ANCHO*100:g} cm a "
        f"{P.DIST_PLACA:.2f} m, bocas separadas {P.SEPARACION_BOCAS*100:g} cm "
        f"(sonda {P.SONDA}, resolución {P.RESOLUCION})", fontsize=12)
    return fig


def figura_espectro(hz, placa, vacio, solo, picos, hz_por_m):
    """espectro.png: la FFT en Hz, como vivo_rapido, y que es cada pico."""
    ref = placa.max()
    fig = plt.figure(figsize=(15, 7.4))
    gs = fig.add_gridspec(1, 3, wspace=0.10, left=0.055, right=0.985,
                          top=0.86, bottom=0.09)

    ax = fig.add_subplot(gs[0, 0:2])
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

    # Panel de texto, con los picos en el orden en que aparecen en el eje.
    # Los saltos se cuentan en PUNTOS y se pasan a fraccion del eje, asi el
    # texto no se superpone ni se sale aunque cambie la cantidad de picos o
    # el tamaño de la figura.
    axt = fig.add_subplot(gs[0, 2])
    axt.axis("off")
    alto_pt = axt.get_position().height * fig.get_figheight() * 72

    def baja(pt):
        return pt / alto_pt

    y = 1.0
    axt.text(0, y, "Qué es cada pico", fontsize=11, fontweight="bold",
             va="top", transform=axt.transAxes)
    y -= baja(19)
    for letra in sorted(picos, key=lambda k: picos[k][0]):
        d, nivel = picos[letra]
        tit, cuerpo = EXPLICACION[letra]
        axt.text(0, y, f"{letra}  {tit}", fontsize=8.6, fontweight="bold",
                 va="top", transform=axt.transAxes)
        axt.text(1.0, y, f"{d*hz_por_m:.0f} Hz  {nivel:+.0f} dB",
                 fontsize=8.2, va="top", ha="right", family="monospace",
                 transform=axt.transAxes)
        y -= baja(12.5)
        axt.text(0.05, y, cuerpo, fontsize=7.4, va="top", linespacing=1.25,
                 transform=axt.transAxes)
        y -= baja(7.4 * 1.25 * 1.2 * (cuerpo.count("\n") + 1) + 7)
    axt.text(0, y, "Las tres curvas usan la misma referencia de dB.\n"
                   "Simulación 2D: las POSICIONES valen, los niveles\n"
                   "no se comparan directo con el banco.",
             fontsize=7.3, va="top", style="italic", color="0.3",
             transform=axt.transAxes)

    fig.suptitle(
        f"Espectro de batido — placa a {P.DIST_PLACA:.2f} m, MEEP 2D + cadena "
        f"de RF del banco\nrampa {R.T_SWEEP*1e3:g} ms (Tprf "
        f"{2*R.T_SWEEP*1e3:g} ms), {hz_por_m:.1f} Hz por metro, cables "
        f"{P.MODO_CABLE}, sonda {P.SONDA}, τ interno "
        f"{P.TAU_INTERNO*1e9:.1f} ns", fontsize=11.5)
    return fig


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
    # Los .npz de antes de que existiera SONDA son todos con el corto.
    sonda_npz = str(dp["sonda"]) if "sonda" in dp.files else "corto"
    if sonda_npz != P.SONDA:
        raise SystemExit(
            f"H_placa.npz se simulo con SONDA={sonda_npz} y el pedido es "
            f"SONDA={P.SONDA}: volver a correr MEEP.")

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
    d_boc = P.d_bocina()
    d_int = P.C0 * P.TAU_INTERNO / 2
    d_cab = 0.0 if P.MODO_CABLE == "ninguno" else P.C0 * P.tau_cables() / 2
    d_off = d_cab + d_int

    rr, placa = perfiles[("placa", P.MODO_CABLE)]
    _, vacio = perfiles[("vacio", P.MODO_CABLE)]
    _, solo = perfiles[("solo", P.MODO_CABLE)]
    picos = buscar_picos(rr, placa, solo, vacio, d_off)

    # --- consola (y resumen_placa.txt): modelo contra simulado -------------
    pred = {
        "acoplamiento, sin cables": P.SEP_ANTENAS / 2 + d_boc + d_int,
        "acoplamiento, con cables": P.SEP_ANTENAS / 2 + d_boc + d_off,
        "placa, sin cables":        P.DIST_PLACA + d_boc + d_int,
        "placa, con cables":        P.DIST_PLACA + d_boc + d_off,
    }
    with R.copiar_consola("resumen_placa.txt"):
        print("=" * 72)
        print(f"Placa metalica a {P.DIST_PLACA:.2f} m del plano de apertura")
        print("=" * 72)
        print(f"  rampa            {R.T_SWEEP*1e3:g} ms (Tprf "
              f"{2*R.T_SWEEP*1e3:g} ms), {n} muestras a {R.FS:.0f} sps")
        print(f"  alpha0           {alpha0/1e9:.2f} GHz/s = {hz_por_m:.1f} Hz "
              f"por metro = 4B/(c*Tprf)")
        print(f"  BW del VCO       {bw/1e6:.1f} MHz -> resolucion c/(2BW) = "
              f"{R.C/(2*bw)*100:.1f} cm")
        print(f"  bocina           agrega {d_boc:.3f} m de distancia aparente "
              f"(largo fisico)")
        print(f"  cables ({P.MODO_CABLE})  {d_cab:.3f} m   |   tau interno "
              f"{P.TAU_INTERNO*1e9:.2f} ns = {d_int:.3f} m")
        print()
        print(f"  {'pico':28s} {'modelo':>9s} {'simulado':>9s} {'error':>8s} "
              f"{'Hz':>8s}")
        print("  " + "-" * 66)
        casos = [
            ("acoplamiento, sin cables", ("vacio", "ninguno")),
            ("acoplamiento, con cables", ("vacio", P.MODO_CABLE)),
            ("placa, sin cables", ("solo", "ninguno")),
            ("placa, con cables", ("solo", P.MODO_CABLE)),
        ]
        for etiqueta, clave in casos:
            r2, ee = perfiles[clave]
            m = pred[etiqueta]
            d, _ = R.pico(r2, ee, desde=m - 0.3, hasta=m + 0.5)
            print(f"  {etiqueta:28s} {m:8.3f}m {d:8.3f}m {d-m:+7.3f}m "
                  f"{d*hz_por_m:7.1f}")
        print("  (el 'error' de la placa es lo que agrega la bocina por encima "
              "de su")
        print("   largo fisico; ver barrido.py)")
        print()
        print("  picos de la figura (con cables):")
        for letra in sorted(picos, key=lambda k: picos[k][0]):
            d, nivel = picos[letra]
            print(f"    {letra:3s} {EXPLICACION[letra][0]:34s} "
                  f"{d*hz_por_m:6.0f} Hz  {d:6.3f} m  {nivel:+5.1f} dB")

    # --- las dos figuras -----------------------------------------------------
    print()
    for archivo, fig in (
            ("escena.png", figura_escena(dp)),
            ("espectro.png", figura_espectro(rr * hz_por_m, placa, vacio,
                                             solo, picos, hz_por_m))):
        destino = R.guardar_figura(fig, os.path.join(P.SALIDAS, archivo))
        plt.close(fig)
        print(f"  figura -> {destino}")
        R.anotar_para_abrir(destino)


if __name__ == "__main__":
    main()
