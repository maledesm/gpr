"""
GPRv2 - Paso 4.5 (Hong 5.1.3): verificacion EM de onda completa del pasabajos eliptico
=====================================================================================

Arma el filtro con las medidas de ../diseno_hong.json y lo simula en openEMS (FDTD,
dominio del tiempo, pulso gaussiano 1-7,5 GHz), como un Transient solver de CST:

  - masa: borde PEC en z = 0 (plano infinito ideal)
  - sustrato FR4 de 1,6 mm que llena toda la celda; aire arriba y a los costados
  - bordes: PML en las puntas de las lineas (x), MUR en y y arriba
  - puertos microstrip de 50 ohm de 10 mm, con el plano de referencia en el borde del filtro
  - malla: lambda/N a 7 GHz (N = --malla), con refinamiento en los bordes de las pistas
    y al menos 4 celdas a lo ancho de la linea fina y 4 en el espesor del sustrato

Modelos de conductor (--metal):
  pec    PEC de espesor cero, sustrato sin perdidas (el caso ideal)
  sheet  lamina conductora de cobre (sigma 5,8e7, t = 72 um) + FR4 con perdidas
  thick  bloque 3D de cobre de 72 um + FR4 con perdidas (lento: la celda vertical es chica)

FR4 con perdidas = "FR-4 (lossy)" de CST: tan d = 0,025. openEMS lo modela como una
conductividad fija, asi que tan d se clava en F_TAND (2,05 GHz) y varia como 1/f.

Uso (con el venv de openEMS):
  C:/Users/tinch/venvs/openems/Scripts/python.exe simular_filtro.py A --metal pec --malla 20
Resultados en resultados/<diseno>_<metal>_er<er>_N<malla>/ (s.npz, metricas.json, s21.png).
Los datos crudos de la simulacion van a D:/sim_filtro (fuera del repo).
"""
import os, sys, json, time, argparse
os.environ["CSXCAD_INSTALL_PATH"] = r"D:\openEMS"
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0, EPS0

AQUI = os.path.dirname(os.path.abspath(__file__))
DISENO = os.path.join(AQUI, "..", "diseno_hong.json")
SIM_RAIZ = r"D:\sim_filtro"

FMAX = 7e9
# pulso de 1 a 7,5 GHz (a -20 dB; a 500 MHz sigue a -26 dB y a 100 MHz a -32 dB).
# La continua del pulso es exp(-(1,5*f0/fc)^2) respecto del pico y se queda atrapada en el
# sustrato: con centro = ancho = 3,5 GHz (-20 dB) la B se estancaba en -30 dB de energia y
# con 0,5-7,5 GHz (-25,5 dB) en -37 dB. Con 4,25/3,25 GHz queda a -33 dB y termina sola.
F0_EXC, FC_EXC = 4.25e9, 3.25e9
H = 1.6                 # mm
T_CU = 0.072            # mm
SIGMA_CU = 5.8e7        # S/m (Copper annealed de CST)
TAND, F_TAND = 0.025, 2.05e9
L_FEED = 10.0           # mm de linea de 50 ohm a cada lado (es el puerto)
AIRE_Y, AIRE_Z = 15.0, 15.0
LADOS = {"A_n5": [1, 1], "B_n7": [1, -1, 1]}      # el B alterna: sus parches de 11 mm no entran del mismo lado


def geometria(r, recorte=1.0):
    """rectangulos de metal [x0, x1, y0, y1] en mm; x = 0 en el borde izquierdo del filtro.
    recorte: factor sobre el largo de cada stub (tramo fino y parche); 1 = el diseno del libro.
    Es el ajuste posterior a la simulacion EM (fuera del libro): en la B el primer cero cayo
    en 2,229 GHz contra 2,385 de diseno, asi que sus stubs se acortan x0,935 (2,229/2,385)."""
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
    return rects, largo, w0, wL


def lineas_ancho(a, b, n=4):
    """lineas de malla para resolver un ancho [a, b] con n celdas"""
    return list(np.linspace(a, b, n + 1))


Q_MALLA = 1.5           # salto maximo entre celdas vecinas


def suavizar(lineas, dmax, juntar):
    """junta lineas a menos de `juntar` mm y despues parte en partes iguales cada celda que sea
    mayor que dmax o que salte mas de Q_MALLA respecto de su vecina mas chica, en el minimo
    numero de partes que lo arregla (asi las celdas crecen de a poco desde las chicas)."""
    l = []
    for v in sorted(lineas):
        if l and v - l[-1] < juntar:
            l[-1] = (l[-1] + v) / 2
        else:
            l.append(v)
    l = np.array(l)
    for _ in range(20000):
        d = np.diff(l)
        izq = np.r_[np.inf, d[:-1]]
        der = np.r_[d[1:], np.inf]
        tope = np.minimum(dmax, Q_MALLA * np.minimum(izq, der))
        k = np.argmax(d / tope)                     # la peor celda primero, de a una
        if d[k] <= tope[k] * 1.0001:
            return l
        if d[k] > 2 * tope[k] and tope[k] < dmax:
            # hueco grande al lado de una celda chica: se corta una sola celda de Q*vecina
            # del lado de la chica, y el resto se vuelve a mirar (crecimiento geometrico)
            nueva = l[k] + tope[k] if izq[k] <= der[k] else l[k + 1] - tope[k]
        else:
            n = int(np.ceil(d[k] / tope[k] - 1e-9))
            nueva = l[k] + d[k] * np.arange(1, n) / n
        l = np.sort(np.concatenate([l, np.atleast_1d(nueva)]))
    sys.exit("la malla no converge")


def salto_max(l):
    d = np.diff(l)
    return float(np.max(np.maximum(d[1:] / d[:-1], d[:-1] / d[1:])))


def simular(nombre, metal, er, N, malla_metal=None, solo_modelo=False, recorte=1.0):
    r = json.load(open(DISENO, encoding="utf-8"))[nombre]
    rects, largo, w0, wL = geometria(r, recorte)
    tag = f"{nombre}_{metal}_er{er:g}_N{N}" + (f"_rec{recorte:g}" if recorte != 1 else "")
    sim_path = os.path.join(SIM_RAIZ, tag)
    out = os.path.join(AQUI, "resultados", tag)
    os.makedirs(out, exist_ok=True)
    os.makedirs(sim_path, exist_ok=True)

    # -50 dB de energia: cortando en -40 dB la A daba errores de 0,2-0,4 dB en S21 y ondas
    # falsas en S11 por debajo de 2 GHz (con -50 dB los dos pulsos probados coinciden en
    # 0,04 dB). Si la energia se estanca antes, cola.py corta la corrida con el archivo ABORT.
    FDTD = openEMS(EndCriteria=1e-5)
    FDTD.SetGaussExcite(F0_EXC, FC_EXC)
    FDTD.SetBoundaryCond(["PML_8", "PML_8", "MUR", "MUR", "PEC", "MUR"])
    CSX = ContinuousStructure()
    FDTD.SetCSX(CSX)
    mesh = CSX.GetGrid()
    mesh.SetDeltaUnit(1e-3)

    res = C0 / (FMAX * np.sqrt(er)) / 1e-3 / N      # mm
    fino = min(res / 4, wL / 4)
    tm = np.array([2 * fino / 3, -fino / 3])        # regla de los tercios en los bordes
    ymin = min(q[2] for q in rects) - AIRE_Y
    ymax = max(q[3] for q in rects) + AIRE_Y
    x0, x1 = -L_FEED, largo + L_FEED

    # malla: bordes de todas las pistas (con tercios) y 4 celdas en los anchos finos
    xs, ys = set([x0, x1]), set([ymin, ymax, 0.0])
    for a, b, c, d in rects + [[x0, x1, -w0 / 2, w0 / 2]]:
        for v, s in ((a, -1), (b, 1)):
            xs.update(v + s * tm)
        for v, s in ((c, -1), (d, 1)):
            ys.update(v + s * tm)
        if b - a <= wL * 1.01:
            xs.update(lineas_ancho(a, b))
        if d - c <= wL * 1.01:
            ys.update(lineas_ancho(c, d))
    # (antes se usaba SmoothMeshLines, que solo rellena huecos mayores que res y dejaba
    #  saltos de x19 entre celdas vecinas: la corrida B divergio. Ahora se suaviza a mano.)
    lx = suavizar(xs, res, fino / 4)
    ly = suavizar(ys, res, fino / 4)
    zs = list(np.linspace(0, H, 5)) + [H + AIRE_Z]
    if metal == "thick":
        dz = malla_metal or T_CU / 2
        zs += list(np.arange(H, H + T_CU + 1e-9, dz)) + [H + T_CU]
    lz = suavizar(zs, res, 0.005)
    saltos = {e: salto_max(l) for e, l in zip("xyz", (lx, ly, lz))}
    print(f"[{tag}] salto maximo entre celdas: " + ", ".join(f"{e} {s:.2f}" for e, s in saltos.items())
          + f"; celda minima {min(np.diff(lx).min(), np.diff(ly).min()):.4f} mm", flush=True)
    if max(saltos.values()) > Q_MALLA + 0.01:
        sys.exit(f"malla con saltos mayores que {Q_MALLA}: no se corre")
    mesh.AddLine("x", lx)
    mesh.AddLine("y", ly)
    mesh.AddLine("z", lz)

    # materiales
    kappa = 0.0 if metal == "pec" else 2 * np.pi * F_TAND * EPS0 * er * TAND
    fr4 = CSX.AddMaterial("FR4", epsilon=er, kappa=kappa)
    fr4.AddBox([x0, ymin, 0], [x1, ymax, H])
    if metal == "pec":
        cond = CSX.AddMetal("cobre")
        z0, z1 = H, H
    elif metal == "sheet":
        cond = CSX.AddConductingSheet("cobre", conductivity=SIGMA_CU, thickness=T_CU * 1e-3)
        z0, z1 = H, H
    else:
        cond = CSX.AddMaterial("cobre", kappa=SIGMA_CU)
        z0, z1 = H, H + T_CU
    for a, b, c, d in rects:
        cond.AddBox([a, c, z0], [b, d, z1], priority=10)

    # puertos microstrip (las lineas de 50 ohm son parte del puerto, PEC)
    pec = CSX.AddMetal("PEC_puertos")
    feed = 10 * res if 10 * res < L_FEED / 2 else L_FEED / 3
    # Feed_R = 50: cada linea termina en 50 ohm. Sin eso la continua del pulso deja carga
    # atrapada en las pistas (la PML no absorbe campos estaticos) y la B se clavaba en -30 dB.
    p1 = FDTD.AddMSLPort(1, pec, [x0, -w0 / 2, H], [0, w0 / 2, 0], "x", "z",
                         excite=-1, FeedShift=feed, MeasPlaneShift=L_FEED, Feed_R=50, priority=10)
    p2 = FDTD.AddMSLPort(2, pec, [x1, -w0 / 2, H], [largo, w0 / 2, 0], "x", "z",
                         FeedShift=feed, MeasPlaneShift=L_FEED, Feed_R=50, priority=10)

    ncel = len(mesh.GetLines("x")) * len(mesh.GetLines("y")) * len(mesh.GetLines("z"))
    print(f"[{tag}] celdas {ncel/1e6:.2f} M, res {res:.3f} mm, fino {fino:.3f} mm", flush=True)
    # el XML es exactamente lo que recibe el motor: el dashboard se arma leyendo este archivo
    # (el C++ no escribe en rutas con "ñ": se escribe en D:/sim_filtro y se copia)
    import shutil
    xml_tmp = os.path.join(sim_path, "modelo.xml")
    FDTD.Write2XML(xml_tmp)
    shutil.copy(xml_tmp, os.path.join(out, "modelo.xml"))
    if solo_modelo:
        return None
    t0 = time.time()
    FDTD.Run(sim_path, verbose=0, cleanup=True)
    dur = time.time() - t0
    # senales temporales de los puertos (tension e corriente incidente), para el dashboard
    import shutil
    for nom in os.listdir(sim_path):
        if nom.startswith("port_"):
            shutil.copy(os.path.join(sim_path, nom), os.path.join(out, nom + ".txt"))

    f = np.linspace(0.05e9, FMAX, 1401)
    for p in (p1, p2):
        p.CalcPort(sim_path, f, ref_impedance=50)
    s11 = p1.uf_ref / p1.uf_inc
    s21 = p2.uf_ref / p1.uf_inc
    m = metricas(f, s11, s21)
    m.update(diseno=nombre, metal=metal, er=er, N=N, recorte=recorte, celdas_M=ncel / 1e6, minutos=dur / 60)
    np.savez(os.path.join(out, "s.npz"), f=f, s11=s11, s21=s21)
    json.dump(m, open(os.path.join(out, "metricas.json"), "w"), indent=2)
    graficar(f, s11, s21, r, tag, os.path.join(out, "s21.png"))
    print(json.dumps(m, indent=1), flush=True)
    return m


def prototipo(f, r):
    """S21 del prototipo de L y C ideales (Tabla 3.3 escalada) para comparar"""
    s = 1j * 2 * np.pi * f
    o = np.ones_like(s)
    M = [o, 0 * o, 0 * o, o]
    mul = lambda a, b: [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3], a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3]]
    for i, L in enumerate(r["L_serie_nH"]):
        M = mul(M, [o, s * L * 1e-9, 0 * o, o])
        if i < len(r["stubs"]):
            st = r["stubs"][i]
            Y = 1 / (s * st["L_nH"] * 1e-9 + 1 / (s * st["C_pF"] * 1e-12))
            M = mul(M, [o, 0 * o, Y, o])
    A, B, C, D = M
    return 2 / (A + B / 50 + C * 50 + D)


def metricas(f, s11, s21):
    d = 20 * np.log10(np.abs(s21) + 1e-12)
    r11 = 20 * np.log10(np.abs(s11) + 1e-12)
    cruce = lambda nivel: float(f[np.argmax((f > 1e9) & (d < nivel))] / 1e9)
    # un cero es un minimo que se despega >= 6 dB de lo que lo rodea (no cada ondita del rechazo)
    from scipy.signal import find_peaks
    ip, _ = find_peaks(-d, height=25, prominence=6)
    ceros = [float(f[i] / 1e9) for i in ip if f[i] > 2e9]
    return dict(
        borde_0p1dB_GHz=cruce(-0.1), borde_1dB_GHz=cruce(-1.0),
        perdida_max_hasta_2GHz_dB=float(-d[f <= 2e9].min()),
        S11_max_hasta_2GHz_dB=float(r11[f <= 2e9].max()),
        ceros_GHz=ceros,
        atenuacion_min_2p36_4GHz_dB=float(-d[(f >= 2.36e9) & (f <= 4e9)].max()),
        espurio_max_4_7GHz_dB=float(d[(f >= 4e9) & (f <= 7e9)].max()),
        f_espurio_GHz=float(f[(f >= 4e9) & (f <= 7e9)][np.argmax(d[(f >= 4e9) & (f <= 7e9)])] / 1e9),
    )


def graficar(f, s11, s21, r, tag, ruta):
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(f / 1e9, 20 * np.log10(np.abs(prototipo(f, r))), color="#8a8984", ls="--", lw=1.5,
            label="prototipo L-C ideal (Tabla 3.3)")
    ax.plot(f / 1e9, 20 * np.log10(np.abs(s21)), color="#2a78d6", lw=2, label="S21 openEMS")
    ax.plot(f / 1e9, 20 * np.log10(np.abs(s11)), color="#eb6834", lw=1.2, label="S11 openEMS")
    ax.axvspan(0.983, 1.999, color="#2a78d6", alpha=0.07, label="banda del VCO")
    ax.axvspan(1.966, 4.0, color="#e34948", alpha=0.07, label="2.º armónico")
    ax.set_ylim(-70, 3); ax.set_xlim(0, 7); ax.grid(alpha=0.3)
    ax.set_xlabel("frecuencia [GHz]"); ax.set_ylabel("dB"); ax.set_title(tag, loc="left")
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout(); fig.savefig(ruta, dpi=130); plt.close(fig)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("diseno", choices=["A", "B"])
    a.add_argument("--metal", default="pec", choices=["pec", "sheet", "thick"])
    a.add_argument("--er", type=float, default=4.4)
    a.add_argument("--malla", type=int, default=20)
    a.add_argument("--dz-metal", type=float, default=None, help="celda vertical en el cobre (thick), mm")
    a.add_argument("--solo-modelo", action="store_true", help="escribe modelo.xml y no simula")
    a.add_argument("--recorte", type=float, default=1.0, help="factor sobre el largo de los stubs")
    x = a.parse_args()
    simular({"A": "A_n5", "B": "B_n7"}[x.diseno], x.metal, x.er, x.malla, x.dz_metal, x.solo_modelo, x.recorte)
