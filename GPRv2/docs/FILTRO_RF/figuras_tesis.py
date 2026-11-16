"""
Figuras del capitulo "Filtro de RF para los armonicos del VCO" de la tesis.
Todo sale de los resultados guardados (diseno_hong.json, openems/resultados, meep/resultados,
openems/pruebas_criterio_fin). Escribe PDF en redaccion/figuras/filtro_rf/ y al final imprime
los numeros que usa el texto.

Uso:  C:/Users/tinch/venvs/openems/Scripts/python.exe figuras_tesis.py
"""
import os, sys, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

AQUI = os.path.dirname(os.path.abspath(__file__))
OE = os.path.join(AQUI, "openems")
sys.path.insert(0, OE)
sys.argv = ["x"]
import dashboard as dsh                      # prototipo(), leer_modelo(), figuras del modelo

SALIDA = os.path.join(AQUI, "..", "..", "..", "redaccion", "figuras", "filtro_rf")
os.makedirs(SALIDA, exist_ok=True)
DIS = json.load(open(os.path.join(AQUI, "diseno_hong.json"), encoding="utf-8"))

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.grid": True, "grid.alpha": 0.3,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "text.color": "black", "axes.labelcolor": "black", "axes.titlecolor": "black",
    "xtick.color": "black", "ytick.color": "black", "xtick.labelcolor": "black", "ytick.labelcolor": "black",
    "axes.edgecolor": "#555555", "axes.formatter.use_locale": False,
})
AZ, RO, GR = "#2a78d6", "#e34948", "#7a7974"
ANCHO = 6.3                                   # pulgadas, ~ ancho de texto


def db(x):
    return 20 * np.log10(np.abs(x) + 1e-12)


def cargar(ruta):
    d = np.load(ruta if ruta.endswith(".npz") else os.path.join(ruta, "s.npz"))
    return d["f"], d["s21"], d["s11"]


def res(tag):
    return os.path.join(OE, "resultados", tag)


def meep(tag):
    return os.path.join(AQUI, "meep", "resultados", tag)


def bandas(ax, rotulos=False):
    ax.axvspan(0.983, 1.999, color=AZ, alpha=0.08, lw=0)
    ax.axvspan(1.966, 4.0, color=RO, alpha=0.06, lw=0)
    if rotulos:
        y = ax.get_ylim()[0] + 3
        ax.text(1.49, y, "banda del VCO", ha="center", fontsize=7.5, color=AZ)
        ax.text(2.98, y, "2.º armónico", ha="center", fontsize=7.5, color=RO)


def coma(ax):
    """decimales con coma en los ejes"""
    from matplotlib.ticker import FuncFormatter
    f = FuncFormatter(lambda v, p: f"{v:g}".replace(".", ",").replace("-", "−"))
    ax.xaxis.set_major_formatter(f)
    ax.yaxis.set_major_formatter(f)


def guardar(fig, nombre):
    fig.savefig(os.path.join(SALIDA, nombre), bbox_inches="tight")
    plt.close(fig)
    print("  ", nombre)


F0 = np.linspace(0.02e9, 7e9, 2000)


# ---------------------------------------------------------------- 1. lo buscado
def fig_buscado():
    fig, ax = plt.subplots(figsize=(ANCHO, 2.9))
    f = F0 / 1e9
    ax.plot([0, 2.0, 2.0, 7], [0, 0, -80, -80], color="black", lw=1.2, label="ideal: corte abrupto en 2 GHz")
    ax.add_patch(Rectangle((2.15, -80), 7 - 2.15, 58, fc="none", ec=RO, hatch="///", lw=0, alpha=0.5))
    ax.plot([2.15, 7], [-22, -22], color=RO, lw=1)
    ax.text(4.6, -19.5, "requisito: ≥ 22 dB desde 2,15 GHz", color=RO, fontsize=8, ha="center")
    p = db(dsh.prototipo(F0, DIS["A_n5"]))
    ax.plot(f, p, color=AZ, lw=1.8, label="prototipo elíptico n = 5 (Hong, Tabla 3.3)")
    for s in DIS["A_n5"]["stubs"]:
        ax.annotate(f"polo\n{s['fp_GHz']:.2f} GHz".replace(".", ","), (s["fp_GHz"], -62),
                    xytext=(s["fp_GHz"] + 0.35, -50), fontsize=7.5, color=AZ, arrowprops=dict(arrowstyle="->", color=AZ, lw=0.8))
    ax.set_xlim(0, 7); ax.set_ylim(-70, 3)
    bandas(ax)
    ax.set_xlabel("frecuencia [GHz]"); ax.set_ylabel("$|S_{21}|$ [dB]")
    ax.legend(loc="lower left", fontsize=8)
    coma(ax)
    guardar(fig, "buscado.pdf")


# ---------------------------------------------------------------- 2. escalera del prototipo
def fig_escalera():
    fig, ax = plt.subplots(figsize=(ANCHO, 1.9))
    ax.axis("off"); ax.grid(False)
    y1, y0 = 1.0, 0.0

    def L(x0, x1, y, txt):
        ax.add_patch(Rectangle((x0, y - 0.07), x1 - x0, 0.14, fc="white", ec="black", lw=1))
        ax.text((x0 + x1) / 2, y + 0.13, txt, ha="center", va="bottom", fontsize=8)

    ax.plot([0, 9.6], [y0, y0], color="black", lw=1)
    xs = [0.3, 1.0, 2.0, 3.0, 4.6, 5.6, 6.6, 7.6, 8.6, 9.3]
    ax.plot([0, 0.6], [y1, y1], "k", lw=1)
    L(0.6, 1.6, y1, "$g_1$")
    ax.plot([1.6, 3.4], [y1, y1], "k", lw=1)
    L(3.4, 4.4, y1, "$g_3$")
    ax.plot([4.4, 6.2], [y1, y1], "k", lw=1)
    L(6.2, 7.2, y1, "$g_5$")
    ax.plot([7.2, 9.6], [y1, y1], "k", lw=1)
    for xr, gl, gc in ((2.5, "$g_2'$", "$g_2$"), (5.3, "$g_4'$", "$g_4$")):
        ax.plot([xr, xr], [y1, 0.78], "k", lw=1)
        ax.add_patch(Rectangle((xr - 0.07, 0.56), 0.14, 0.22, fc="white", ec="black", lw=1))
        ax.text(xr + 0.15, 0.67, gl + " (L)", va="center", fontsize=8)
        ax.plot([xr, xr], [0.56, 0.36], "k", lw=1)
        ax.plot([xr - 0.12, xr + 0.12], [0.36, 0.36], "k", lw=1.6)
        ax.plot([xr - 0.12, xr + 0.12], [0.30, 0.30], "k", lw=1.6)
        ax.text(xr + 0.15, 0.33, gc + " (C)", va="center", fontsize=8)
        ax.plot([xr, xr], [0.30, y0], "k", lw=1)
        ax.plot(xr, y1, "ko", ms=3)
    for x, t in ((0, "$g_0 = 1$\n(fuente)"), (9.6, "$g_6 = 1$\n(carga)")):
        ax.text(x, -0.12, t, ha="center", va="top", fontsize=7.5)
    ax.text(3.9, 1.42, "L en serie = tramos finos de alta impedancia", fontsize=7.5, color=GR, ha="center")
    ax.text(6.6, 0.55, "L–C a masa: stubs\n(cada uno pone un polo)", fontsize=7.5, color=GR)
    ax.set_xlim(-0.6, 10.2); ax.set_ylim(-0.45, 1.6)
    guardar(fig, "escalera.pdf")


# ---------------------------------------------------------------- 3. topologias (geometria del libro)
def fig_topologias():
    runs = [r for r in dsh.cargar_todo() if r["prog"] == "openEMS" and r["m"]["metal"] == "pec" and r["m"]["N"] == 20
            and r["var"] in ("A", "B")]
    import matplotlib.figure as mf
    orig = mf.Figure.savefig

    def sv(self, f, **k):
        if k.get("format") == "svg":
            for ax in self.axes:
                ax.set_title(ax.get_title(loc="left").split("  ·  ")[0], loc="left", fontsize=9)
                ax.grid(False)
            self.set_size_inches(ANCHO, 2.9 * len(self.axes))
            orig(self, os.path.join(SALIDA, "topologias.pdf"), bbox_inches="tight")
            print("   topologias.pdf")
        return orig(self, f, **k)

    mf.Figure.savefig = sv
    try:
        dsh.fig_topologias(runs)
    finally:
        mf.Figure.savefig = orig


# ---------------------------------------------------------------- 4. el modelo en openEMS
def fig_modelo():
    M = dsh.leer_modelo(os.path.join(res("A_n5_pec_er4.4_N20"), "modelo.xml"))
    original = dsh.png
    salida = {}

    def png(fig):
        for ax in fig.axes:
            ax.set_title("", loc="left")
        fig.savefig(salida["ruta"], bbox_inches="tight")
        plt.close(fig)
        print("  ", os.path.basename(salida["ruta"]))
        return dict(uri="", titulo="")

    dsh.png = png
    try:
        salida["ruta"] = os.path.join(SALIDA, "modelo_topologia.pdf"); dsh.fig_topologia(M)
        salida["ruta"] = os.path.join(SALIDA, "modelo_malla.pdf"); dsh.fig_malla_xy(M)
        salida["ruta"] = os.path.join(SALIDA, "modelo_corte.pdf"); dsh.fig_corte_xz(M)
    finally:
        dsh.png = original


# ---------------------------------------------------------------- 5. curvas
def panel(ax, curvas, ylim=(-70, 3), xlim=(0, 7), proto=None, rot=False, loc="lower right"):
    if proto:
        ax.plot(F0 / 1e9, db(dsh.prototipo(F0, DIS[proto])), ":", color=GR, lw=1.3, label="prototipo ideal (libro)")
    for lab, ruta, col, ls in curvas:
        f, s21, _ = cargar(ruta)
        ax.plot(f / 1e9, db(s21), ls, color=col, lw=1.6, label=lab)
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    bandas(ax, rot)
    ax.set_ylabel("$|S_{21}|$ [dB]")
    ax.legend(fontsize=7.5, loc=loc)
    coma(ax)


def fig_convergencia():
    fig, (a, b) = plt.subplots(1, 2, figsize=(ANCHO, 2.7), gridspec_kw=dict(width_ratios=[1.6, 1]))
    cur = [(f"malla λ/{n}", res(f"A_n5_pec_er4.4_N{n}"), c, "-") for n, c in ((20, AZ), (30, "#1baf7a"), (40, "#eb6834"))]
    panel(a, cur)
    panel(b, cur, xlim=(2.2, 4.0), ylim=(-70, -10))
    b.get_legend().remove(); b.set_ylabel("")
    for x in (a, b):
        x.set_xlabel("frecuencia [GHz]")
    guardar(fig, "convergencia.pdf")


def fig_pec():
    fig, (a, b) = plt.subplots(2, 1, figsize=(ANCHO, 4.6), sharex=True)
    panel(a, [("diseño A (n = 5), openEMS", res("A_n5_pec_er4.4_N20"), AZ, "-")], proto="A_n5")
    panel(b, [("diseño B (n = 7), openEMS", res("B_n7_pec_er4.4_N20"), RO, "-")], proto="B_n7")
    b.set_xlabel("frecuencia [GHz]")
    guardar(fig, "pec_contra_prototipo.pdf")


def fig_recorte():
    fig, (a, b) = plt.subplots(1, 2, figsize=(ANCHO, 2.7), gridspec_kw=dict(width_ratios=[1.6, 1]))
    cur = [("B del libro", res("B_n7_pec_er4.4_N20"), "#c49a9a", "-"),
           ("B con stubs ×0,935", res("B_n7_pec_er4.4_N20_rec0.935"), RO, "-")]
    panel(a, cur)
    panel(b, cur, xlim=(1.5, 2.6), ylim=(-40, 1))
    b.get_legend().remove(); b.set_ylabel("")
    for x in (a, b):
        x.set_xlabel("frecuencia [GHz]")
    guardar(fig, "recorte_B.pdf")


def fig_conductor():
    fig, axs = plt.subplots(2, 2, figsize=(ANCHO, 4.6), gridspec_kw=dict(width_ratios=[1.6, 1]), sharex="col")
    for fila, (v, tag, col) in enumerate((("A", "A_n5_{}_er4.4_N20", AZ), ("B rec.", "B_n7_{}_er4.4_N20_rec0.935", RO))):
        cur = [(f"{v}, PEC sin pérdidas", res(tag.format("pec")), col, ":"),
               (f"{v}, cobre en lámina + FR4", res(tag.format("sheet")), col, "--"),
               (f"{v}, cobre 72 µm en bloque + FR4", res(tag.format("thick")), col, "-")]
        panel(axs[fila][0], cur)
        panel(axs[fila][1], cur, xlim=(0.9, 2.2), ylim=(-6, 0.5))
        axs[fila][1].get_legend().remove(); axs[fila][1].set_ylabel("")
    for x in axs[1]:
        x.set_xlabel("frecuencia [GHz]")
    guardar(fig, "conductor.pdf")


def fig_meep():
    fig, (a, b) = plt.subplots(2, 1, figsize=(ANCHO, 4.6), sharex=True)
    panel(a, [("A, openEMS (PEC)", res("A_n5_pec_er4.4_N20"), AZ, "-"),
              ("A, openEMS con metal de 0,125 mm", res("A_n5_pec125_er4.4_N20"), "#14a3a3", "-"),
              ("A, MEEP (8 px/mm)", meep("A_n5_res8"), "#6250d6", "--")], xlim=(0.8, 7))
    panel(b, [("B rec., openEMS (PEC)", res("B_n7_pec_er4.4_N20_rec0.935"), RO, "-"),
              ("B rec., MEEP (8 px/mm)", meep("B_n7_res8_rec0.935"), "#eda100", "--")], xlim=(0.8, 7))
    b.set_xlabel("frecuencia [GHz]")
    guardar(fig, "meep.pdf")


def fig_obtenido():
    fig, ax = plt.subplots(figsize=(ANCHO, 3.0))
    ax.plot([0, 2.0, 2.0, 7], [0, 0, -80, -80], color="black", lw=1.1, label="ideal: corte en 2 GHz")
    ax.add_patch(Rectangle((2.15, -80), 7 - 2.15, 58, fc="none", ec=RO, hatch="///", lw=0, alpha=0.45))
    ax.plot([2.15, 7], [-22, -22], color=RO, lw=1)
    for lab, tag, col, ls in (("A, cobre 72 µm + FR4 (a fabricar)", "A_n5_thick_er4.4_N20", AZ, "-"),
                              ("B rec., cobre 72 µm + FR4", "B_n7_thick_er4.4_N20_rec0.935", RO, "--")):
        f, s21, _ = cargar(res(tag))
        ax.plot(f / 1e9, db(s21), ls, color=col, lw=1.7, label=lab)
    ax.set_xlim(0, 7); ax.set_ylim(-70, 3)
    bandas(ax)
    ax.set_xlabel("frecuencia [GHz]"); ax.set_ylabel("$|S_{21}|$ [dB]")
    ax.legend(fontsize=8, loc="lower left")
    coma(ax)
    guardar(fig, "obtenido.pdf")


def fig_criterio_fin():
    P = os.path.join(OE, "pruebas_criterio_fin")
    fig, (a, b) = plt.subplots(2, 1, figsize=(ANCHO, 4.2), sharex=True)
    ref = cargar(os.path.join(P, "A_fin50_pulso1.npz"))
    for lab, arch, col, ls, lw in (("fin a −50 dB, pulso 1–7,5 GHz", "A_fin50_pulso1.npz", "black", "-", 2.2),
                                   ("fin a −50 dB, pulso 0,5–7,5 GHz", "A_fin50_pulso05.npz", "#1baf7a", "--", 1.4),
                                   ("fin a −40 dB, pulso 0,5–7,5 GHz", "A_fin40_pulso05.npz", "#eb6834", "-", 1.2)):
        f, s21, s11 = cargar(os.path.join(P, arch))
        a.plot(f / 1e9, db(s11), ls, color=col, lw=lw, label=lab)
        b.plot(f / 1e9, db(s21) - db(ref[1]), ls, color=col, lw=lw, label=lab)
    a.set_ylim(-60, 0); a.set_ylabel("$|S_{11}|$ [dB]"); a.legend(fontsize=7.5, loc="lower right")
    b.set_ylim(-0.8, 0.8); b.set_ylabel("$|S_{21}|$ − referencia [dB]"); b.set_xlabel("frecuencia [GHz]")
    b.set_xlim(0, 2.2)
    for x in (a, b):
        coma(x)
    guardar(fig, "criterio_fin.pdf")


# ---------------------------------------------------------------- numeros para el texto
def numeros():
    print("\nnumeros para el texto")
    filas = [("A PEC", res("A_n5_pec_er4.4_N20")), ("A lamina", res("A_n5_sheet_er4.4_N20")),
             ("A bloque", res("A_n5_thick_er4.4_N20")), ("Brec PEC", res("B_n7_pec_er4.4_N20_rec0.935")),
             ("Brec lamina", res("B_n7_sheet_er4.4_N20_rec0.935")), ("Brec bloque", res("B_n7_thick_er4.4_N20_rec0.935"))]
    for lab, ruta in filas:
        f, s21, s11 = cargar(ruta)
        d, r = db(s21), db(s11)
        vco = (f >= 0.983e9) & (f <= 1.999e9)
        i = np.where((f >= 2e9) & (d <= -22))[0]
        f22 = f[i[0]] / 1e9 if len(i) else float("nan")
        sigue = bool(len(i)) and np.all(d[(f >= f[i[0]]) & (f <= 4e9)] <= -22) if len(i) else False
        print(f"  {lab:12s} perdida VCO {-d[vco].max():.2f}..{-d[vco].min():.2f} dB | S11 max VCO {r[vco].max():.1f} | "
              f"S21 2,15 {np.interp(2.15e9, f, d):.1f} | primer -22 dB en {f22:.3f} (se mantiene hasta 4 GHz: {sigue}) | "
              f"min 2,36-4 {-d[(f >= 2.36e9) & (f <= 4e9)].max():.1f} | S21 4/5/6 {np.interp(4e9, f, d):.1f}/{np.interp(5e9, f, d):.1f}/{np.interp(6e9, f, d):.1f}")


if __name__ == "__main__":
    print("figuras en", os.path.abspath(SALIDA))
    fig_buscado(); fig_escalera(); fig_topologias(); fig_modelo(); fig_convergencia(); fig_pec()
    fig_recorte(); fig_conductor(); fig_meep(); fig_obtenido(); fig_criterio_fin()
    numeros()
