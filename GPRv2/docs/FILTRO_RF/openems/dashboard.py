"""
GPRv2 - Dashboard de las simulaciones openEMS del pasabajos
==========================================================

Recorre resultados/*/ y arma UN solo dashboard.html con una seccion por simulacion.
Todo lo que se dibuja sale de los archivos que escribio la propia corrida:

  modelo.xml        el XML que recibe el motor (FDTD.Write2XML justo antes de Run):
                    bordes, excitacion, malla, materiales, metales, sondas de los puertos
  s.npz             S11 y S21 calculados por openEMS
  metricas.json     metricas de la curva y datos de la corrida
  port_*.txt        senales temporales de las sondas de los puertos

Uso:  C:/Users/tinch/venvs/openems/Scripts/python.exe dashboard.py
"""
import os, io, glob, json, base64, html
import xml.etree.ElementTree as ET
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "dashboard.html")
EPS0 = 8.854187817e-12
F_TAND = 2.05e9
COL = dict(sustrato="#c9d8ee", metal="#c98a3c", puerto="#d9b45a", exc="#e34948",
           ut="#6250d6", it="#1baf7a", malla="#b4b2a9", pml="#f3d9d9", mur="#dfe9f6", pec="#3a3a3a")

# tema comun: los graficos usan el mismo fondo, tipografia y tintas que la pagina
FONDO, TINTA, TINTA2, TENUE, GRILLA, EJE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10,
    "figure.facecolor": FONDO, "axes.facecolor": FONDO, "savefig.facecolor": FONDO,
    "axes.edgecolor": EJE, "axes.labelcolor": TINTA2, "axes.titlecolor": TINTA,
    "xtick.color": TENUE, "ytick.color": TENUE, "xtick.labelcolor": TINTA2, "ytick.labelcolor": TINTA2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
    "grid.color": GRILLA, "grid.linewidth": 0.8, "legend.frameon": False, "legend.fontsize": 9,
    "legend.labelcolor": TINTA2, "svg.fonttype": "none", "text.color": TINTA2,
})


# ------------------------------------------------------------------ lectura del XML
def leer_modelo(ruta):
    root = ET.parse(ruta).getroot()
    fdtd = root.find("FDTD")
    exc = fdtd.find("Excitation")
    bc = fdtd.find("BoundaryCond").attrib
    grid = root.find("ContinuousStructure/RectilinearGrid")
    unidad = float(grid.get("DeltaUnit"))
    lineas = {ax: np.array([float(v) for v in grid.find(f"{ax.upper()}Lines").text.split(",")])
              for ax in "xyz"}
    props = []
    for p in root.find("ContinuousStructure/Properties"):
        cajas = []
        for b in p.iter("Box"):
            p1 = b.find("P1").attrib
            p2 = b.find("P2").attrib
            cajas.append((np.array([float(p1[k]) for k in "XYZ"]), np.array([float(p2[k]) for k in "XYZ"]),
                          int(b.get("Priority", 0))))
        props.append(dict(tipo=p.tag, nombre=p.get("Name"), attr=dict(p.attrib),
                          prop=(p.find("Property").attrib if p.find("Property") is not None else {}),
                          cajas=cajas))
    return dict(fdtd=dict(fdtd.attrib), exc=dict(exc.attrib), bc=bc, unidad=unidad, lineas=lineas, props=props)


def clase(p):
    if p["tipo"] == "Excitation":
        return "exc"
    if p["tipo"] == "ProbeBox":
        return "ut" if p["attr"].get("Type") == "0" else "it"
    if p["tipo"] == "Material":
        return "sustrato" if "epsilon" in p["nombre"].lower() or p["nombre"] == "FR4" else "metal"
    if p["nombre"] == "PEC_puertos":
        return "puerto"
    return "metal"


def png(fig):
    """SVG con el texto como texto (lo dibuja el navegador con la fuente de la pagina).
    El titulo del grafico se saca de la figura y se devuelve para ponerlo como encabezado HTML."""
    titulo = ""
    for ax in fig.axes:
        t = ax.get_title(loc="left")
        if t and not titulo:
            titulo = t
        ax.set_title("", loc="left")
    b = io.BytesIO()
    fig.savefig(b, format="svg", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return dict(uri="data:image/svg+xml;base64," + base64.b64encode(b.getvalue()).decode(), titulo=titulo)


# ------------------------------------------------------------------ figuras
def dibujar_bordes_xy(ax, M):
    x, y = M["lineas"]["x"], M["lineas"]["y"]
    bc = M["bc"]
    for lado, (ini, fin, eje) in dict(xmin=(0, 1, "x"), xmax=(-1, -2, "x"), ymin=(0, 1, "y"), ymax=(-1, -2, "y")).items():
        tipo = bc[lado]
        n = int(tipo.split("_")[1]) if tipo.startswith("PML") else 1
        L = M["lineas"][eje]
        a, b = (L[0], L[n]) if lado.endswith("min") else (L[-1 - n], L[-1])
        pml = tipo.startswith("PML")
        kw = dict(fc="#e34948" if pml else "none", alpha=0.25 if pml else 1, hatch=None if pml else "////",
                  ec="#e34948" if pml else "#2a78d6", lw=0.0 if pml else 0.0, zorder=7)
        if eje == "x":
            ax.add_patch(Rectangle((a, y[0]), b - a, y[-1] - y[0], **kw))
            ax.text((a + b) / 2, y[0] - 0.02 * (y[-1] - y[0]), f"{lado}\n{tipo}", va="top", ha="center",
                    fontsize=7, color="#a32d2d" if pml else "#185fa5")
        else:
            ax.plot([x[0], x[-1]], [L[0] if lado == "ymin" else L[-1]] * 2, color="#2a78d6", lw=3, zorder=7)
            ax.text((x[0] + x[-1]) / 2, (L[0] if lado == "ymin" else L[-1]), f" {lado}: {tipo} ",
                    va="bottom" if lado == "ymin" else "top", ha="center", fontsize=7, color="#185fa5", zorder=8,
                    bbox=dict(fc="white", ec="none", pad=0.5))


def caja_xy(ax, c, **kw):
    (p1, p2, _) = c
    x0, x1 = sorted([p1[0], p2[0]])
    y0, y1 = sorted([p1[1], p2[1]])
    ax.add_patch(Rectangle((x0, y0), max(x1 - x0, 0.05), max(y1 - y0, 0.05), **kw))


def fig_topologia(M):
    fig, ax = plt.subplots(figsize=(11, 6.2))
    dibujar_bordes_xy(ax, M)
    vistos = set()
    for p in M["props"]:
        k = clase(p)
        for c in p["cajas"]:
            if k == "sustrato":
                caja_xy(ax, c, fc=COL["sustrato"], ec="#7f97bd", lw=0.8, zorder=1,
                        label=None if "s" in vistos else f"sustrato {p['nombre']}")
                vistos.add("s")
            elif k in ("metal", "puerto"):
                caja_xy(ax, c, fc=COL[k], ec="k", lw=0.4, zorder=3,
                        label=None if k in vistos else ("pistas del filtro (" + p["nombre"] + ")" if k == "metal"
                                                       else "líneas de 50 Ω de los puertos"))
                vistos.add(k)
            else:
                (p1, p2, _) = c
                if k == "exc":
                    ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=COL["exc"], lw=3, zorder=5,
                            label=None if k in vistos else "plano de excitación (puerto 1)")
                    ax.annotate("excitación", (p1[0], p2[1]), xytext=(p1[0], p2[1] + 4), fontsize=8,
                                color=COL["exc"], ha="center", arrowprops=dict(arrowstyle="->", color=COL["exc"]))
                else:
                    if p1[0] == p2[0] and p1[1] == p2[1]:
                        ax.plot(p1[0], p1[1], "o", ms=3, color=COL[k], zorder=6,
                                label=None if k in vistos else "sondas de tensión (ut)")
                    else:
                        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=COL[k], lw=1.6, zorder=6,
                                label=None if k in vistos else "sondas de corriente (it)")
                vistos.add(k)
    # numero de puerto
    for p in M["props"]:
        if p["nombre"].startswith("port_ut_") and p["nombre"].endswith("B"):
            c = p["cajas"][0][0]
            ax.text(c[0], c[1] - 3, f"puerto {p['nombre'][8]}\n(plano de medición)", ha="center", va="top", fontsize=8)
    x, y = M["lineas"]["x"], M["lineas"]["y"]
    ax.set_xlim(x[0], x[-1]); ax.set_ylim(y[0], y[-1]); ax.set_aspect("equal")
    ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
    ax.set_title("Topología, puertos y bordes (vista superior, z = h)", loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, frameon=False)
    return png(fig)


def fig_malla_xy(M, zoom=None):
    fig, ax = plt.subplots(figsize=(11, 6.2) if zoom is None else (7, 5))
    for p in M["props"]:
        k = clase(p)
        if k in ("metal", "puerto"):
            for c in p["cajas"]:
                caja_xy(ax, c, fc=COL[k], ec="none", alpha=0.75, zorder=1)
    x, y = M["lineas"]["x"], M["lineas"]["y"]
    for v in x:
        ax.axvline(v, color=COL["malla"], lw=0.35, zorder=2)
    for v in y:
        ax.axhline(v, color=COL["malla"], lw=0.35, zorder=2)
    ax.set_aspect("equal")
    if zoom:
        ax.set_xlim(*zoom[0]); ax.set_ylim(*zoom[1])
        ax.set_title("Malla, zoom en la unión del primer stub", loc="left")
    else:
        ax.set_xlim(x[0], x[-1]); ax.set_ylim(y[0], y[-1])
        ax.set_title(f"Malla en el plano xy: {len(x)} líneas en x, {len(y)} en y", loc="left")
    ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
    return png(fig)


def fig_corte_xz(M):
    x, z = M["lineas"]["x"], M["lineas"]["z"]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    bc = M["bc"]
    for p in M["props"]:
        k = clase(p)
        for (p1, p2, _) in p["cajas"]:
            y0, y1 = sorted([p1[1], p2[1]])
            if not (y0 <= 0 <= y1):
                continue                                   # corte en y = 0 (eje de la linea)
            x0, x1 = sorted([p1[0], p2[0]]); z0, z1 = sorted([p1[2], p2[2]])
            if k == "sustrato":
                ax.add_patch(Rectangle((x0, z0), x1 - x0, z1 - z0, fc=COL["sustrato"], ec="#7f97bd", zorder=1))
            elif k in ("metal", "puerto"):
                # espesor cero (PEC / lamina): se dibuja con 0,15 mm solo para que se vea
                ax.add_patch(Rectangle((x0, z0), x1 - x0, max(z1 - z0, 0.15), fc=COL[k], ec="k", lw=0.4, zorder=3))
            elif k == "exc":
                ax.plot([x0, x1], [z0, z1], color=COL["exc"], lw=3, zorder=5)
    for v in x:
        ax.axvline(v, color=COL["malla"], lw=0.3, zorder=2)
    for v in z:
        ax.axhline(v, color=COL["malla"], lw=0.3, zorder=2)
    ax.axhline(z[0], color=COL["pec"], lw=3, zorder=4)
    for lado, L0 in (("xmin", 0), ("xmax", -1)):
        if bc[lado].startswith("PML"):
            n = int(bc[lado].split("_")[1])
            a, b = (x[0], x[n]) if lado == "xmin" else (x[-1 - n], x[-1])
            ax.add_patch(Rectangle((a, z[0]), b - a, z[-1] - z[0], fc="#e34948", alpha=0.25, lw=0, zorder=6))
            ax.text((a + b) / 2, z[-1] / 2, bc[lado], rotation=90, ha="center", va="center", fontsize=7, color="#a32d2d")
    ax.text(x[len(x) // 2], z[0] - 0.4, f"zmin: {bc['zmin']} (masa)", ha="center", va="top", fontsize=8)
    ax.text(x[len(x) // 2], z[-1], f"zmax: {bc['zmax']}", ha="center", va="bottom", fontsize=8)
    ax.set_xlim(x[0], x[-1]); ax.set_ylim(z[0] - 1.2, z[-1] + 0.8)
    ax.set_xlabel("x [mm]"); ax.set_ylabel("z [mm]")
    ax.set_title(f"Corte en y = 0 con la malla ({len(z)} líneas en z); sustrato de 0 a h, metal en z = h", loc="left")
    return png(fig)


def fig_corte_z_zoom(M):
    z = M["lineas"]["z"]
    fig, ax = plt.subplots(figsize=(5, 3.2))
    ax.add_patch(Rectangle((0, 0), 1, 1.6, fc=COL["sustrato"], ec="#7f97bd"))
    for v in z[z < 3]:
        ax.axhline(v, color=COL["malla"], lw=0.8)
    ax.axhline(0, color=COL["pec"], lw=3)
    ax.set_xlim(0, 1); ax.set_ylim(-0.1, 3); ax.set_xticks([])
    ax.set_ylabel("z [mm]"); ax.set_title("Malla en z cerca del sustrato", loc="left")
    return png(fig)


def fig_sparam(carpeta, met):
    d = np.load(os.path.join(carpeta, "s.npz"))
    f, s11, s21 = d["f"], d["s11"], d["s21"]
    proto = None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("sf", os.path.join(AQUI, "simular_filtro.py"))
    except Exception:
        spec = None
    fig, ax = plt.subplots(figsize=(11, 5))
    r = json.load(open(os.path.join(AQUI, "..", "diseno_hong.json"), encoding="utf-8"))[met["diseno"]]
    ax.plot(f / 1e9, 20 * np.log10(np.abs(prototipo(f, r))), "--", color="#8a8984", lw=1.4,
            label="prototipo L-C ideal (Tabla 3.3)")
    ax.plot(f / 1e9, 20 * np.log10(np.abs(s21)), color="#2a78d6", lw=2, label="S21")
    ax.plot(f / 1e9, 20 * np.log10(np.abs(s11)), color="#eb6834", lw=1.2, label="S11")
    ax.axvspan(0.983, 1.999, color="#2a78d6", alpha=0.07, label="banda del VCO")
    ax.axvspan(1.966, 4.0, color="#e34948", alpha=0.07, label="2.º armónico")
    for c in met["ceros_GHz"]:
        ax.axvline(c, color="#2a78d6", lw=0.6, ls=":")
    ax.set_xlim(0, 7); ax.set_ylim(-70, 3); ax.grid(True)
    ax.set_xlabel("frecuencia [GHz]"); ax.set_ylabel("dB"); ax.legend(fontsize=8, loc="lower left")
    ax.set_title("Parámetros S (referidos a 50 Ω, en el borde del filtro)", loc="left")
    return png(fig)


def prototipo(f, r):
    s = 1j * 2 * np.pi * f
    o = np.ones_like(s)
    M = [o, 0 * o, 0 * o, o]
    mul = lambda a, b: [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3], a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3]]
    for i, L in enumerate(r["L_serie_nH"]):
        M = mul(M, [o, s * L * 1e-9, 0 * o, o])
        if i < len(r["stubs"]):
            st = r["stubs"][i]
            M = mul(M, [o, 0 * o, 1 / (s * st["L_nH"] * 1e-9 + 1 / (s * st["C_pF"] * 1e-12)), o])
    A, B, C, D = M
    return 2 / (A + B / 50 + C * 50 + D)


def leer_senal(ruta):
    d = np.loadtxt(ruta, comments="%")
    return d[:, 0], d[:, 1]


def fig_temporal(carpeta):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    for nom, col, lab in (("port_ut_1A", "#e34948", "tensión puerto 1"), ("port_ut_2A", "#2a78d6", "tensión puerto 2")):
        ruta = os.path.join(carpeta, nom + ".txt")
        if not os.path.exists(ruta):
            continue
        t, v = leer_senal(ruta)
        a1.plot(t * 1e9, v, color=col, lw=0.8, label=lab)
        a2.semilogy(t * 1e9, np.abs(v) + 1e-12, color=col, lw=0.6, label=lab)
    a1.set_xlim(0, 3); a1.set_xlabel("t [ns]"); a1.set_ylabel("V"); a1.set_title("Pulso de excitación y respuesta (primeros 3 ns)", loc="left")
    a2.set_xlabel("t [ns]"); a2.set_title("Decaimiento hasta el criterio de fin", loc="left")
    for a in (a1, a2):
        a.grid(True)
        if a.get_legend_handles_labels()[0]:
            a.legend()
    return png(fig)


# ------------------------------------------------------------------ tablas
def tabla(filas):
    return "<table>" + "".join(f"<tr><th>{html.escape(str(a))}</th><td>{b}</td></tr>" for a, b in filas) + "</table>"


def info_modelo(M, met):
    x, y, z = (M["lineas"][k] for k in "xyz")
    dmin = lambda L: np.diff(L).min()
    dmax = lambda L: np.diff(L).max()
    exc = M["exc"]
    filas = [
        ("Solver", "openEMS FDTD (dominio del tiempo)"),
        ("Excitación", f"gaussiana, f0 = {float(exc['f0'])/1e9:g} GHz, fc = {float(exc['fc'])/1e9:g} GHz "
                       f"(cubre 0 a {(float(exc['f0'])+float(exc['fc']))/1e9:g} GHz)"),
        ("Criterio de fin", f"energía {10*np.log10(float(M['fdtd']['endCriteria'])):.0f} dB"),
        ("Bordes", ", ".join(f"{k} = {v}" for k, v in M["bc"].items())),
        ("Dominio", f"x {x[0]:.1f} a {x[-1]:.1f}, y {y[0]:.1f} a {y[-1]:.1f}, z {z[0]:.1f} a {z[-1]:.1f} mm"),
        ("Malla", f"{len(x)} × {len(y)} × {len(z)} = {len(x)*len(y)*len(z)/1e6:.2f} M celdas"),
        ("Celda mín / máx", f"x {dmin(x):.3f} / {dmax(x):.3f} mm; y {dmin(y):.3f} / {dmax(y):.3f} mm; "
                            f"z {dmin(z):.3f} / {dmax(z):.3f} mm"),
    ]
    for p in M["props"]:
        if p["tipo"] == "Material":
            er = float(p["prop"].get("Epsilon", "1").split(",")[0])
            k = float(p["prop"].get("Kappa", "0").split(",")[0])
            tand = k / (2 * np.pi * F_TAND * EPS0 * er) if er else 0
            filas.append((f"Material «{p['nombre']}»", f"εr = {er:g}, κ = {k:.3g} S/m"
                          + (f" (tan δ = {tand:.3f} en 2,05 GHz)" if k and k < 1e3 else "")))
        elif p["tipo"] in ("Metal",):
            filas.append((f"Metal «{p['nombre']}»", f"PEC, {len(p['cajas'])} cajas"))
        elif p["tipo"] == "ConductingSheet":
            filas.append((f"Lámina «{p['nombre']}»", f"σ = {float(p['attr']['Conductivity']):.3g} S/m, t = {float(p['attr']['Thickness'])*1e6:.0f} µm"))
    filas += [("Duración de la corrida", f"{met['minutos']:.1f} min")]
    return tabla(filas)


def info_metricas(met):
    return tabla([
        ("Borde −0,1 dB / −1 dB", f"{met['borde_0p1dB_GHz']:.3f} / {met['borde_1dB_GHz']:.3f} GHz"),
        ("Pérdida máxima hasta 2 GHz", f"{met['perdida_max_hasta_2GHz_dB']:.2f} dB"),
        ("S11 máximo hasta 2 GHz", f"{met['S11_max_hasta_2GHz_dB']:.1f} dB"),
        ("Ceros", ", ".join(f"{c:.3f}" for c in met["ceros_GHz"]) + " GHz"),
        ("Atenuación mínima 2,36–4 GHz", f"{met['atenuacion_min_2p36_4GHz_dB']:.1f} dB"),
        ("Máximo de S21 entre 4 y 7 GHz", f"{met['espurio_max_4_7GHz_dB']:.1f} dB en {met['f_espurio_GHz']:.2f} GHz"),
    ])


# ------------------------------------------------------------------ html
CSS = """
:root{--bg:#fcfcfb;--fg:#0b0b0b;--mut:#52514e;--ten:#898781;--bd:#e1e0d9;--tile:#f4f3ef;--ac:#2a78d6}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:"Segoe UI",system-ui,sans-serif;margin:0;line-height:1.5;
     font-variant-numeric:tabular-nums}
.pagina{max-width:1180px;margin:0 auto;padding:32px 28px 64px}
header h1{font-size:26px;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
header p{color:var(--mut);margin:0;font-size:14px}
nav{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--bd);padding:10px 0;margin:20px 0 8px;z-index:5;
    display:flex;flex-wrap:wrap;gap:8px}
nav a{font-size:13px;color:var(--fg);text-decoration:none;border:1px solid var(--bd);border-radius:999px;padding:3px 12px}
nav a:hover{border-color:var(--ac);color:var(--ac)}
section{padding-top:28px;margin-top:28px;border-top:1px solid var(--bd)}
section:first-of-type{border-top:none;margin-top:0}
h2{font-size:20px;font-weight:600;margin:0 0 6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 18px}
.chip{font-size:12px;color:var(--mut);background:var(--tile);border-radius:6px;padding:2px 9px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:22px}
.kpi{background:var(--tile);border-radius:10px;padding:12px 14px}
.kpi .l{font-size:12px;color:var(--mut)} .kpi .v{font-size:22px;font-weight:600;margin-top:2px}
.kpi .s{font-size:12px;color:var(--ten)}
h3{font-size:14px;font-weight:600;color:var(--fg);margin:22px 0 2px}
h3.gdet{font-size:15px;margin:22px 0 6px}
.cap{font-size:13px;color:var(--mut);margin:0 0 6px}
figure{margin:0} figure img{width:100%;display:block}
.dos{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:24px;align-items:start}
@media(max-width:860px){.dos{grid-template-columns:1fr}}
table{border-collapse:collapse;font-size:13px;width:100%}
th{text-align:left;font-weight:500;color:var(--mut);padding:5px 14px 5px 0;vertical-align:top;width:38%;border-bottom:1px solid var(--bd)}
td{padding:5px 0;border-bottom:1px solid var(--bd)}
code{font-size:12px;background:var(--tile);padding:1px 5px;border-radius:4px}
.pie{font-size:12px;color:var(--ten);margin-top:10px}
table.res th,table.res td{width:auto;padding:5px 10px 5px 0;font-size:12.5px}
"""


def figura(f, nota=""):
    return (f'<figure><h3>{html.escape(f["titulo"])}</h3>' + (f'<p class="cap">{nota}</p>' if nota else "")
            + f'<img src="{f["uri"]}" alt="{html.escape(f["titulo"])}"></figure>')


def kpi(lab, val, sub=""):
    return f'<div class="kpi"><div class="l">{lab}</div><div class="v">{val}</div><div class="s">{sub}</div></div>'


def seccion(carpeta):
    tag = os.path.basename(carpeta)
    M = leer_modelo(os.path.join(carpeta, "modelo.xml"))
    met = json.load(open(os.path.join(carpeta, "metricas.json"), encoding="utf-8"))
    cob = [c for p in M["props"] if clase(p) == "metal" for c in p["cajas"]]
    stub = min((c for c in cob if min(c[0][1], c[1][1]) > 0.01 or max(c[0][1], c[1][1]) < -0.01),
               key=lambda c: c[0][0])
    xc = (stub[0][0] + stub[1][0]) / 2
    zoom = ((xc - 4, xc + 4), (-2.5, 3.5))
    nombre = nombre_diseno(met)
    conductor = ETIQ_METAL.get(met["metal"], met["metal"])
    x, y, z = (M["lineas"][k] for k in "xyz")
    fin = met.get("energia_final_dB")
    chips = [conductor, f"εr = {met['er']:g}", f"malla λ/{met['N']}",
             f"{len(x)}×{len(y)}×{len(z)} = {met['celdas_M']:.2f} M celdas", f"{met['minutos']:.1f} min"]
    if fin is not None:
        chips.append(f"energía final {fin:.1f} dB" + (" (estancada)" if met.get("estancada") else ""))
    ceros = " · ".join(f"{c:.2f}" for c in met["ceros_GHz"])
    kpis = "".join([
        kpi("Borde −1 dB", f"{met['borde_1dB_GHz']:.3f} GHz", f"−0,1 dB en {met['borde_0p1dB_GHz']:.2f} GHz"),
        kpi("Ceros", f"{ceros}", "GHz"),
        kpi("Atenuación 2,36–4 GHz", f"{met['atenuacion_min_2p36_4GHz_dB']:.1f} dB", "mínima (2.º armónico)"),
        kpi("Máximo 4–7 GHz", f"{met['espurio_max_4_7GHz_dB']:.1f} dB", f"en {met['f_espurio_GHz']:.2f} GHz"),
        kpi("Banda de paso", f"{met['perdida_max_hasta_2GHz_dB']:.2f} dB", f"pérdida máx.; S11 ≤ {met['S11_max_hasta_2GHz_dB']:.1f} dB"),
    ])
    partes = [
        f'<details class="corrida" id="{tag}"><summary><span class="t">{nombre} · {html.escape(conductor)} · λ/{met["N"]}</span>'
        f'<span class="r">borde {met["borde_1dB_GHz"]:.3f} GHz · rechazo {met["atenuacion_min_2p36_4GHz_dB"]:.1f} dB · '
        f'{met["minutos"]:.1f} min</span></summary><div class="cuerpo">',
        '<div class="chips">' + "".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips) + "</div>",
        f'<div class="kpis">{kpis}</div>',
        figura(fig_sparam(carpeta, met), "Referidos a 50 Ω en el borde del filtro; en gris, el prototipo de L y C ideales."),
        figura(fig_topologia(M), "Geometría leída del XML: pistas, líneas de los puertos, plano de excitación, sondas y bordes (PML en rojo)."),
        figura(fig_malla_xy(M)),
        '<div class="dos">' + figura(fig_malla_xy(M, zoom)) + figura(fig_corte_z_zoom(M)) + "</div>",
        figura(fig_corte_xz(M)),
        figura(fig_temporal(carpeta)),
        '<div class="dos"><div><h3>Modelo</h3>' + info_modelo(M, met) + '</div><div><h3>Resultados</h3>'
        + info_metricas(met) + "</div></div>",
        f'<p class="pie">Fuente: <code>resultados/{tag}/</code> (modelo.xml, s.npz, metricas.json, port_*.txt)</p></div></details>',
    ]
    return tag, met, "\n".join(partes)


MEEP = os.path.join(AQUI, "..", "meep", "resultados")
DISENO = os.path.join(AQUI, "..", "diseno_hong.json")
ETIQ_METAL = {"pec": "PEC sin pérdidas", "sheet": "cobre en lámina + FR4 con pérdidas",
              "thick": "cobre 72 µm en bloque + FR4 con pérdidas"}
CORTO_METAL = {"pec": "PEC", "sheet": "lámina", "thick": "bloque 72 µm"}


def variante(m):
    """'A', 'B' o 'Brec' segun diseno y recorte"""
    if m["diseno"] == "A_n5":
        return "A"
    return "Brec" if abs(m.get("recorte", 1.0) - 1) > 1e-9 else "B"


VAR = {"A": dict(nombre="Diseño A · n = 5", corto="A"),
       "B": dict(nombre="Diseño B · n = 7 (original del libro)", corto="B orig."),
       "Brec": dict(nombre="Diseño B · n = 7, stubs recortados ×0,935", corto="B rec.")}
ORDEN_VAR = ["A", "Brec", "B"]


def nombre_diseno(m):
    return VAR[variante(m)]["nombre"]


# colores por corrida: familia de color por diseno, tono por modelo
COLORES = {("A", "pec", 20): "#2a78d6", ("A", "pec", 30): "#7fb3ea", ("A", "pec", 40): "#a9cdf2",
           ("A", "sheet", 20): "#1f5fae", ("A", "thick", 20): "#0f3d78",
           ("Brec", "pec", 20): "#e34948", ("Brec", "sheet", 20): "#f08a52", ("Brec", "thick", 20): "#a8261f",
           ("B", "pec", 20): "#c49a9a", ("B", "sheet", 20): "#d9b7a2",
           ("A", "meep"): "#6250d6", ("Brec", "meep"): "#eda100", ("B", "meep"): "#b8a14a"}


def cargar_todo():
    """todas las corridas terminadas: openEMS y MEEP, con su etiqueta y color"""
    runs = []
    for c in sorted(glob.glob(os.path.join(AQUI, "resultados", "*"))):
        if os.path.exists(os.path.join(c, "s.npz")) and os.path.exists(os.path.join(c, "metricas.json")):
            m = json.load(open(os.path.join(c, "metricas.json"), encoding="utf-8"))
            d = np.load(os.path.join(c, "s.npz"))
            v = variante(m)
            runs.append(dict(prog="openEMS", tag=os.path.basename(c), m=m, var=v, f=d["f"], s21=d["s21"], s11=d["s11"],
                             etiq=f"{VAR[v]['corto']} · {CORTO_METAL[m['metal']]} · λ/{m['N']}",
                             color=COLORES.get((v, m["metal"], m["N"]), "#898781"), carpeta=c))
    for c in sorted(glob.glob(os.path.join(MEEP, "*"))):
        if os.path.exists(os.path.join(c, "s.npz")) and os.path.exists(os.path.join(c, "metricas.json")):
            m = json.load(open(os.path.join(c, "metricas.json"), encoding="utf-8"))
            m.setdefault("metal", "pec")
            d = np.load(os.path.join(c, "s.npz"))
            v = variante(m)
            runs.append(dict(prog="MEEP", tag="meep_" + os.path.basename(c), m=m, var=v, f=d["f"], s21=d["s21"],
                             s11=d["s11"], etiq=f"{VAR[v]['corto']} · MEEP {m['res_px_mm']} px/mm",
                             color=COLORES.get((v, "meep"), "#898781"), carpeta=c))
    orden = lambda r: (ORDEN_VAR.index(r["var"]), r["prog"] != "openEMS",
                       ["pec", "sheet", "thick"].index(r["m"].get("metal", "pec")), r["m"].get("N", 0))
    return sorted(runs, key=orden)


def db(x):
    return 20 * np.log10(np.abs(x) + 1e-12)


def s21_en(r, F):
    return float(np.interp(F * 1e9, r["f"], db(r["s21"])))


# ------------------------------------------------------------------ topologias
def fig_topologias(runs):
    """las tres geometrias a la misma escala, leidas del modelo.xml de su corrida PEC lambda/20,
    con los largos del diseno (diseno_hong.json) por el recorte"""
    dis = json.load(open(DISENO, encoding="utf-8"))
    elegidas = []
    for v in ORDEN_VAR:
        cand = [r for r in runs if r["prog"] == "openEMS" and r["var"] == v and r["m"]["metal"] == "pec"
                and r["m"]["N"] == 20]
        if cand:
            elegidas.append(cand[0])
    fig, axs = plt.subplots(len(elegidas), 1, figsize=(11, 3.6 * len(elegidas)))
    axs = np.atleast_1d(axs)
    coma = lambda v, n=2: f"{v:.{n}f}".replace(".", ",")
    for ax, r in zip(axs, elegidas):
        M = leer_modelo(os.path.join(r["carpeta"], "modelo.xml"))
        rec = r["m"].get("recorte", 1.0)
        d = dis[r["m"]["diseno"]]
        cajas = [(clase(p), c) for p in M["props"] if clase(p) in ("metal", "puerto") for c in p["cajas"]]
        for k, c in cajas:
            caja_xy(ax, c, fc="#e7c9a3" if k == "puerto" else "#c98a3c", ec="#6b4a1f", lw=0.6, zorder=3)
        # series y stubs, desde el diseno
        wL, wC, w0 = d["lineas"]["W_L_mm"], d["lineas"]["W_C_mm"], d["lineas"]["W_0_mm"]
        ycota = min(min(c[0][1], c[1][1]) for _, c in cajas) - 1.2      # cotas por debajo de todo
        x, juntas = 0.0, []
        for i, l in enumerate(d["l_serie_mm"]):
            ax.annotate("", (x, ycota), (x + l, ycota), arrowprops=dict(arrowstyle="<->", color=TENUE, lw=0.8))
            ax.text(x + l / 2, ycota - 0.4, f"L{2*i+1} {coma(l)}", ha="center", va="top", fontsize=7.5, color=TINTA2)
            ax.plot([x, x], [ycota, -wL / 2], color=GRILLA, lw=0.6, zorder=0)
            x += l
            if i < len(d["stubs"]):
                juntas.append(x)
        largo = x
        ax.plot([x, x], [ycota, -wL / 2], color=GRILLA, lw=0.6, zorder=0)
        lados = {"A_n5": [1, 1], "B_n7": [1, -1, 1]}[r["m"]["diseno"]]
        for j, (xj, s, sg) in enumerate(zip(juntas, d["stubs"], lados)):
            lt, lp = s["lL_corregido_mm"] * rec, s["lC_final_mm"] * rec
            yfin = sg * (wL / 2 + lt + lp)
            ax.text(xj + wC / 2 + 0.6, sg * (wL / 2 + lt + lp / 2),
                    f"stub {j+1} · cero de diseño {coma(s['fp_GHz'])} GHz\nfino {coma(lt)} + parche {coma(lp)} mm",
                    fontsize=7.5, va="center", ha="left", color=TINTA, zorder=6,
                    bbox=dict(fc=FONDO, ec="none", pad=1, alpha=0.85))
        ax.axhline(0, color=GRILLA, lw=0.6, zorder=1)
        ax.set_aspect("equal")
        ax.set_xlim(-11, 46); ax.set_ylim(-11.5, 12.5)
        ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
        ax.set_title(f"{VAR[r['var']]['nombre']}  ·  filtro de {coma(largo, 1)} mm, parches de {coma(wC)} mm "
                     f"({d['lineas']['Z0C']:.0f} Ω)", loc="left", fontsize=10)
    fig.tight_layout()
    titulo_vacio = [a.get_title(loc="left") for a in axs]
    b = io.BytesIO()
    fig.savefig(b, format="svg", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return "data:image/svg+xml;base64," + base64.b64encode(b.getvalue()).decode()


# ------------------------------------------------------------------ comparador interactivo
def datos_js(runs):
    dis = json.load(open(DISENO, encoding="utf-8"))
    series = []
    for r in runs:
        f = r["f"] / 1e9
        paso = max(1, len(f) // 700)
        series.append(dict(id=r["tag"], etiq=r["etiq"], color=r["color"], var=r["var"], prog=r["prog"],
                           metal=r["m"].get("metal", "pec"), N=r["m"].get("N", 0),
                           f=np.round(f[::paso], 4).tolist(),
                           s21=np.round(db(r["s21"])[::paso], 2).tolist(),
                           s11=np.round(db(r["s11"])[::paso], 2).tolist()))
    f0 = np.linspace(0.05e9, 7e9, 700)
    for nom, v, col in (("A_n5", "A", "#2a78d6"), ("B_n7", "B", "#e34948")):
        series.append(dict(id="proto_" + v, etiq=f"{v} · prototipo ideal del libro", color=col, var="proto" + v,
                           prog="prototipo", metal="", N=0, f=np.round(f0 / 1e9, 4).tolist(),
                           s21=np.round(db(prototipo(f0, dis[nom])), 2).tolist(), s11=None))
    return json.dumps(series, separators=(",", ":"))


JS = r"""
const S = DATOS;
const svg = document.getElementById('graf'), W = 1000, H = 440, ml = 54, mr = 14, mt = 12, mb = 40;
let rango = [0, 7, -70, 3], param = 's21', visibles = new Set();
const NS = 'http://www.w3.org/2000/svg';
function el(t, a, p) { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }
const X = f => ml + (f - rango[0]) / (rango[1] - rango[0]) * (W - ml - mr);
const Y = v => mt + (rango[3] - v) / (rango[3] - rango[2]) * (H - mt - mb);
function ticks(a, b, n) { const p = Math.pow(10, Math.floor(Math.log10((b - a) / n))); const s = [1, 2, 5, 10].map(k => k * p).find(k => (b - a) / k <= n); const r = []; for (let v = Math.ceil(a / s) * s; v <= b + 1e-9; v += s) r.push(+v.toFixed(6)); return r; }
function dibujar() {
  svg.innerHTML = '';
  el('rect', {x: ml, y: mt, width: W - ml - mr, height: H - mt - mb, fill: 'none'}, svg);
  const bandas = [[0.983, 1.999, 'rgba(42,120,214,.08)'], [1.966, 4.0, 'rgba(227,73,72,.07)']];
  for (const [a, b, c] of bandas) { const x0 = X(Math.max(a, rango[0])), x1 = X(Math.min(b, rango[1])); if (x1 > x0) el('rect', {x: x0, y: mt, width: x1 - x0, height: H - mt - mb, fill: c}, svg); }
  for (const t of ticks(rango[0], rango[1], 10)) { el('line', {x1: X(t), x2: X(t), y1: mt, y2: H - mb, stroke: '#e1e0d9'}, svg); const tx = el('text', {x: X(t), y: H - mb + 16, 'text-anchor': 'middle', class: 'tk'}, svg); tx.textContent = t; }
  for (const t of ticks(rango[2], rango[3], 8)) { el('line', {x1: ml, x2: W - mr, y1: Y(t), y2: Y(t), stroke: t === -20 ? '#b4b2a9' : '#e1e0d9', 'stroke-dasharray': t === -20 ? '4 3' : ''}, svg); const tx = el('text', {x: ml - 6, y: Y(t) + 4, 'text-anchor': 'end', class: 'tk'}, svg); tx.textContent = t; }
  const lx = el('text', {x: (W + ml) / 2, y: H - 4, 'text-anchor': 'middle', class: 'lb'}, svg); lx.textContent = 'frecuencia [GHz]';
  const ly = el('text', {x: 14, y: (H - mb) / 2, transform: `rotate(-90 14 ${(H - mb) / 2})`, 'text-anchor': 'middle', class: 'lb'}, svg); ly.textContent = (param === 's21' ? 'S21' : 'S11') + ' [dB]';
  const clip = el('clipPath', {id: 'cl'}, el('defs', {}, svg)); el('rect', {x: ml, y: mt, width: W - ml - mr, height: H - mt - mb}, clip);
  const g = el('g', {'clip-path': 'url(#cl)'}, svg);
  for (const s of S) { if (!visibles.has(s.id) || !s[param]) continue;
    let d = ''; s.f.forEach((f, i) => { d += (i ? 'L' : 'M') + X(f).toFixed(1) + ' ' + Y(Math.max(s[param][i], rango[2] - 50)).toFixed(1); });
    el('path', {d, fill: 'none', stroke: s.color, 'stroke-width': s.prog === 'prototipo' ? 1.2 : 2, 'stroke-dasharray': s.prog === 'prototipo' ? '5 4' : (s.prog === 'MEEP' ? '7 3' : '')}, g); }
  const cur = el('line', {y1: mt, y2: H - mb, stroke: '#52514e', 'stroke-width': 0.8, visibility: 'hidden'}, svg);
  const caja = document.getElementById('lectura');
  svg.onmousemove = ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) / r.width * W; if (px < ml || px > W - mr) return;
    const f = rango[0] + (px - ml) / (W - ml - mr) * (rango[1] - rango[0]); cur.setAttribute('x1', px); cur.setAttribute('x2', px); cur.setAttribute('visibility', 'visible');
    let h = `<b>${f.toFixed(3)} GHz</b>`; for (const s of S) { if (!visibles.has(s.id) || !s[param]) continue; let i = s.f.findIndex(v => v >= f); if (i < 1) continue;
      const t = (f - s.f[i - 1]) / (s.f[i] - s.f[i - 1]), v = s[param][i - 1] + t * (s[param][i] - s[param][i - 1]);
      h += `<div><i style="background:${s.color}"></i>${s.etiq}<span>${v.toFixed(2)} dB</span></div>`; } caja.innerHTML = h; };
  svg.onmouseleave = () => { cur.setAttribute('visibility', 'hidden'); };
}
function marcar() { document.querySelectorAll('#series input').forEach(c => { c.checked = visibles.has(c.value); }); dibujar(); }
function preset(ids) { visibles = new Set(ids.filter(i => S.some(s => s.id === i))); marcar(); }
document.querySelectorAll('#series input').forEach(c => c.onchange = () => { c.checked ? visibles.add(c.value) : visibles.delete(c.value); dibujar(); });
document.querySelectorAll('[data-rango]').forEach(b => b.onclick = () => { rango = JSON.parse(b.dataset.rango); document.querySelectorAll('[data-rango]').forEach(x => x.classList.remove('on')); b.classList.add('on'); dibujar(); });
document.querySelectorAll('[data-param]').forEach(b => b.onclick = () => { param = b.dataset.param; document.querySelectorAll('[data-param]').forEach(x => x.classList.remove('on')); b.classList.add('on');
  if (param === 's11') { rango[2] = -45; rango[3] = 0; } dibujar(); });
document.querySelectorAll('[data-preset]').forEach(b => b.onclick = () => { preset(JSON.parse(b.dataset.preset)); document.querySelectorAll('[data-preset]').forEach(x => x.classList.remove('on')); b.classList.add('on'); });
document.querySelector('[data-preset]').click();
"""


def comparador(runs):
    por_id = {r["tag"]: r for r in runs}

    def ids(cond):
        return [r["tag"] for r in runs if cond(r)]

    def uno(v, metal, N=20, prog="openEMS"):
        return ids(lambda r: r["var"] == v and r["prog"] == prog and r["m"].get("metal") == metal and r["m"].get("N") == N)

    presets = [
        ("A contra B recortada · bloque 72 µm", uno("A", "thick") + uno("Brec", "thick")),
        ("A contra B recortada · PEC", uno("A", "pec") + uno("Brec", "pec") + ["proto_A", "proto_B"]),
        ("B original contra recortada", uno("B", "pec") + uno("Brec", "pec") + uno("B", "sheet") + uno("Brec", "sheet")),
        ("Modelos del conductor · A", uno("A", "pec") + uno("A", "sheet") + uno("A", "thick")),
        ("Modelos del conductor · B rec.", uno("Brec", "pec") + uno("Brec", "sheet") + uno("Brec", "thick")),
        ("Convergencia de malla · A", ids(lambda r: r["var"] == "A" and r["prog"] == "openEMS" and r["m"]["metal"] == "pec")),
        ("openEMS contra MEEP", uno("A", "pec") + uno("Brec", "pec") + ids(lambda r: r["prog"] == "MEEP")),
    ]
    hay_meep = any(r["prog"] == "MEEP" for r in runs)
    presets = [(n, l) for n, l in presets if len([i for i in l if i in por_id]) >= 2
               and (hay_meep or "MEEP" not in n)]
    botones_p = "".join(f"<button data-preset='{json.dumps(l)}'>{html.escape(n)}</button>" for n, l in presets)
    rangos = [("0–7 GHz", [0, 7, -70, 3]), ("banda de paso", [0.8, 2.3, -6, 0.5]),
              ("2.º armónico", [1.9, 4.2, -70, 0]), ("arriba de 4 GHz", [4, 7, -60, 0])]
    botones_r = "".join(f"<button data-rango='{json.dumps(v)}'{' class=on' if i == 0 else ''}>{n}</button>"
                        for i, (n, v) in enumerate(rangos))
    grupos = []
    for v in ORDEN_VAR:
        lst = [r for r in runs if r["var"] == v]
        if not lst:
            continue
        items = "".join(f"<label><input type='checkbox' value='{r['tag']}'><i style='background:{r['color']}'></i>"
                        f"{html.escape(r['etiq'])}</label>" for r in lst)
        grupos.append(f"<div class='grupo'><div class='gt'>{VAR[v]['corto']}</div>{items}</div>")
    grupos.append("<div class='grupo'><div class='gt'>Prototipos</div>"
                  "<label><input type='checkbox' value='proto_A'><i style='background:#2a78d6'></i>A · ideal del libro</label>"
                  "<label><input type='checkbox' value='proto_B'><i style='background:#e34948'></i>B · ideal del libro</label></div>")
    return (
        '<section id="comparador"><h2>Comparador</h2>'
        '<p class="cap">Elegí una comparación armada o marcá las corridas que quieras. Pasando el mouse por el gráfico '
        'se leen los valores. Celeste: banda del VCO. Rosa: 2.º armónico. Línea punteada horizontal: −20 dB. '
        'MEEP va en trazo cortado y los prototipos en punteado.</p>'
        f'<div class="barra"><span class="bt">Comparar</span>{botones_p}</div>'
        f'<div class="barra"><span class="bt">Zoom</span>{botones_r}<span class="sep"></span>'
        '<button data-param="s21" class="on">S21</button><button data-param="s11">S11</button></div>'
        '<div class="comp"><div><svg id="graf" viewBox="0 0 1000 440"></svg>'
        '<div id="lectura" class="lectura">Pasá el mouse por el gráfico.</div></div>'
        f'<div id="series">{"".join(grupos)}</div></div></section>')


# ------------------------------------------------------------------ tabla resumen
def tabla_resumen(runs):
    nan = float("nan")
    filas = []
    previo = None
    for r in runs:
        m = r["m"]
        if r["var"] != previo:
            filas.append(f"<tr class='gr'><td colspan='14'>{VAR[r['var']]['nombre']}</td></tr>")
            previo = r["var"]
        modelo = (CORTO_METAL[m["metal"]] + (" + pérdidas" if m["metal"] != "pec" else "")) if r["prog"] == "openEMS" \
            else "metal perfecto 1 px"
        malla = f"λ/{m['N']}" if r["prog"] == "openEMS" else f"{m['res_px_mm']} px/mm"
        fin = m.get("energia_final_dB")
        finx = "" if fin is None else f"{fin:.1f}" + ("*" if m.get("estancada") else "")
        celdas = [r["prog"], modelo, malla] + [f"{s21_en(r, F):.2f}" for F in (1.0, 1.5, 1.9, 2.0)] + [
            f"{m.get('borde_1dB_GHz', nan):.3f}", f"{s21_en(r, 2.2):.1f}", f"{s21_en(r, 2.3):.1f}",
            f"<b>{m.get('atenuacion_min_2p36_4GHz_dB', nan):.1f}</b>",
            f"{s21_en(r, 5.0):.1f} / {s21_en(r, 6.0):.1f}", finx, f"{m.get('minutos', 0):.1f}"]
        ancla = f"<a href='#{r['tag']}'>" if r["prog"] == "openEMS" else ""
        celdas[0] = f"{ancla}<i class='pt' style='background:{r['color']}'></i>{celdas[0]}{'</a>' if ancla else ''}"
        filas.append("<tr>" + "".join(f"<td>{c}</td>" for c in celdas) + "</tr>")
    cab = ("<tr><th rowspan=2>programa</th><th rowspan=2>conductor</th><th rowspan=2>malla</th>"
           "<th colspan=4>S21 en la banda del VCO [dB]</th><th rowspan=2>borde −1 dB [GHz]</th>"
           "<th colspan=2>S21 [dB]</th><th rowspan=2>rechazo mín. 2,36–4 GHz [dB]</th><th rowspan=2>S21 en 5 / 6 GHz [dB]</th>"
           "<th rowspan=2>energía final [dB]</th><th rowspan=2>min</th></tr>"
           "<tr><th>1,0 GHz</th><th>1,5</th><th>1,9</th><th>2,0</th><th>2,2 GHz</th><th>2,3</th></tr>")
    return ('<section id="tabla"><h2>Todas las corridas</h2>'
            '<p class="cap">Agrupadas por diseño. «*» en la energía final quiere decir que la corrida se estancó y la '
            'cola la cortó con lo que había (fin normal a −50 dB). El nombre lleva al detalle de esa corrida, más abajo.</p>'
            f"<div class='scroll'><table class='res'>{cab}{''.join(filas)}</table></div></section>")


def seccion_meep(r):
    m = r["m"]
    c = r["carpeta"]
    img = ""
    if os.path.exists(os.path.join(c, "modelo_meep.png")):
        b64 = base64.b64encode(open(os.path.join(c, "modelo_meep.png"), "rb").read()).decode()
        img = ('<figure><h3>Modelo tal como lo ve MEEP (plot2D de la propia simulación)</h3>'
               '<p class="cap">Rojo oscuro: metal; marrón: sustrato; rayado: PML; rojo: fuente; azul: monitores de flujo.</p>'
               f'<img src="data:image/png;base64,{b64}"></figure>')
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(r["f"] / 1e9, db(r["s21"]), color="#2a78d6", lw=2, label="|S21|")
    ax.plot(r["f"] / 1e9, db(r["s11"]), color="#eb6834", lw=1.2, label="|S11|")
    ax.axvspan(1.966, 4.0, color="#e34948", alpha=0.06)
    ax.set_xlim(0, 7); ax.set_ylim(-70, 3); ax.grid(True); ax.legend(loc="lower left")
    ax.set_xlabel("frecuencia [GHz]"); ax.set_ylabel("dB"); ax.set_title("Parámetros S (flujo de potencia)", loc="left")
    chips = [f"MEEP, {m['res_px_mm']} px/mm", f"{m['celdas_M']:.1f} M celdas", f"{m.get('procesos', 1)} procesos",
             f"{m['minutos']:.1f} min", "metal perfecto, 1 píxel", "FR4 sin pérdidas"]
    return (f'<details class="corrida" id="{r["tag"]}"><summary><span class="t">{VAR[r["var"]]["nombre"]} · MEEP '
            f'{m["res_px_mm"]} px/mm</span><span class="r">borde {m["borde_1dB_GHz"]:.3f} GHz · rechazo '
            f'{m["atenuacion_min_2p36_4GHz_dB"]:.1f} dB · {m["minutos"]:.1f} min</span></summary><div class="cuerpo">'
            '<div class="chips">' + "".join(f'<span class="chip">{html.escape(x)}</span>' for x in chips) + "</div>"
            + figura(png(fig)) + img + f'<p class="pie">Fuente: <code>meep/resultados/{os.path.basename(c)}/</code></p></div></details>')


CSS_EXTRA = """
.barra{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}
.barra .bt{font-size:12px;color:var(--ten);width:72px}
.barra .sep{width:14px}
button{font:inherit;font-size:12.5px;border:1px solid var(--bd);background:var(--bg);border-radius:999px;padding:3px 11px;cursor:pointer;color:var(--fg)}
button:hover{border-color:var(--ac)} button.on{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.comp{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:18px;margin-top:10px}
@media(max-width:900px){.comp{grid-template-columns:1fr}}
#graf{width:100%;display:block} #graf .tk{font-size:11px;fill:#52514e} #graf .lb{font-size:12px;fill:#52514e}
.lectura{font-size:12px;color:var(--mut);min-height:60px;margin-top:4px}
.lectura div{display:flex;gap:6px;align-items:center} .lectura span{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--fg)}
.lectura i,#series i,.pt{display:inline-block;width:14px;height:3px;border-radius:2px;flex:none}
#series .grupo{margin-bottom:12px} #series .gt{font-size:12px;font-weight:600;margin-bottom:2px}
#series label{display:flex;gap:6px;align-items:center;font-size:12.5px;cursor:pointer;padding:1px 0}
.scroll{overflow-x:auto}
table.res{font-size:12.5px} table.res th{width:auto;text-align:center;padding:4px 6px;border-bottom:1px solid var(--bd);font-weight:500}
table.res td{text-align:right;padding:4px 6px;white-space:nowrap} table.res td:nth-child(-n+3){text-align:left}
table.res tr.gr td{text-align:left;font-weight:600;padding-top:12px;color:var(--fg);border-bottom:1px solid var(--fg)}
table.res a{color:inherit;text-decoration:none} table.res a:hover{color:var(--ac)} .pt{margin-right:6px;vertical-align:middle}
details.corrida{border:1px solid var(--bd);border-radius:10px;margin:8px 0;background:var(--bg)}
details.corrida>summary{cursor:pointer;padding:10px 14px;display:flex;flex-wrap:wrap;gap:4px 14px;list-style:none}
details.corrida>summary::-webkit-details-marker{display:none}
details.corrida>summary .t{font-weight:600;font-size:14px} details.corrida>summary .r{font-size:12.5px;color:var(--mut);margin-left:auto}
details.corrida>summary:before{content:'▸';color:var(--ten);margin-right:2px} details.corrida[open]>summary:before{content:'▾'}
details.corrida .cuerpo{padding:4px 16px 16px}
.nota{background:var(--tile);border-radius:10px;padding:12px 16px;font-size:13.5px;color:var(--fg);margin:12px 0}
"""


def main():
    runs = cargar_todo()
    detalles = {}
    for r in runs:
        if r["prog"] == "openEMS" and os.path.exists(os.path.join(r["carpeta"], "modelo.xml")):
            detalles[r["tag"]] = seccion(r["carpeta"])[2]
        elif r["prog"] == "MEEP":
            detalles[r["tag"]] = seccion_meep(r)
    bloques_det = []
    for v in ORDEN_VAR:
        lst = [r for r in runs if r["var"] == v and r["tag"] in detalles]
        if lst:
            bloques_det.append(f"<h3 class='gdet'>{VAR[v]['nombre']}</h3>" + "".join(detalles[r["tag"]] for r in lst))
    topo = fig_topologias(runs)
    nav = "".join(f'<a href="#{i}">{n}</a>' for i, n in (("topologias", "Topologías"), ("comparador", "Comparador"),
                                                       ("tabla", "Tabla"), ("detalle", "Detalle de cada corrida")))
    doc = ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Filtro RF: simulaciones</title><style>{CSS}{CSS_EXTRA}</style></head><body><div class='pagina'>"
           "<header><h1>Pasabajos elíptico en microstrip · openEMS y MEEP</h1>"
           "<p>Paso 4.5 de Hong y Lancaster (5.1.3): verificación electromagnética. FR4 εr 4,4, h 1,6 mm. "
           "Cada gráfico se arma leyendo los archivos que escribió la propia corrida.</p></header>"
           f"<nav>{nav}</nav>"
           '<section id="topologias"><h2>Topologías</h2>'
           '<p class="cap">Las tres geometrías a la misma escala, vista superior. Cobre oscuro: el filtro. Cobre claro: '
           'las líneas de 50 Ω de los puertos. Los contornos salen del modelo.xml de cada corrida (PEC, λ/20) y los '
           'rótulos de diseno_hong.json (largos en mm, ya con el recorte en la B recortada). En las tres, los tramos '
           'finos miden 0,54 mm (110 Ω) y las líneas de 50 Ω, 3,07 mm. Los ceros son los de diseño; dónde caen en la '
           'simulación está en la tabla y en el comparador.</p>'
           '<div class="nota">Diseño elegido: <b>B recortado ×0,935</b> (n = 7). El A queda de respaldo.</div>'
           f'<figure><img src="{topo}" alt="Topologías"></figure></section>'
           + comparador(runs) + tabla_resumen(runs)
           + '<section id="detalle"><h2>Detalle de cada corrida</h2><p class="cap">Modelo, malla, bordes, puertos, '
           'parámetros S y señales, tal como los recibió el motor. Click para abrir.</p>' + "".join(bloques_det) + "</section>"
           + f"<script>const DATOS = {datos_js(runs)};{JS}</script>"
           "</div></body></html>")
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"{len(runs)} corridas -> {SALIDA} ({os.path.getsize(SALIDA)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
