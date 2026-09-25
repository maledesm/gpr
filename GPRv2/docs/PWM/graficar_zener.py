"""
GPRv2 - Figuras del zener de proteccion del VCO
===============================================

Dos figuras, a partir de las corridas que deja simular_zener.py en zener/:

  zener_vertice.png   el vertice de arriba de la triangular con cada zener, y
                      la curva inversa de los dos modelos al lado.
  zener_falla.png     la falla de R9 abierta, con y sin zener.

Uso
---
    py graficar_zener.py [carpeta de salida]

Sin argumento las deja al lado de este script.
"""

import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "zener")
SALIDA = sys.argv[1] if len(sys.argv) > 1 else AQUI

AMP_G, AMP_OFF = 4.949, 0.055   # Vosc = 4,949*Vin + 0,055, medido (cap. del VCO)
VCO_MAX = 18.0                  # lo que aguanta el VCO
AMP_VCC = 20.0                  # con lo que se alimenta el amplificador x4,95
V_PICO = 3.09                   # el pico de la triangular, donde se compara

# Misma paleta que graficar_triangular3.py, mas un ambar para el tercer trazo.
C_SIN, C_4729, C_4728, C_LIM = "#4a3aa7", "#1baf7a", "#c2571a", "#8a8a85"


def leer_raw(path):
    """(nombres, [(t, datos) por paso]) de un .raw binario de LTspice.

    Igual que en graficar_triangular3.py: encabezado en UTF-16LE, tiempo en
    doble precision y el resto en simple.
    """
    crudo = open(path, "rb").read()
    marca = "Binary:\n".encode("utf-16-le")
    i = crudo.find(marca)
    if i < 0:
        raise SystemExit(f"{path}: no es un .raw binario de LTspice")
    cab = crudo[:i].decode("utf-16-le")
    datos = crudo[i + len(marca):]

    n_var = n_pts = None
    nombres, leyendo = [], False
    for linea in cab.splitlines():
        if linea.startswith("No. Variables:"):
            n_var = int(linea.split(":")[1])
        elif linea.startswith("No. Points:"):
            n_pts = int(linea.split(":")[1])
        elif linea.startswith("Variables:"):
            leyendo = True
        elif leyendo and linea.startswith("\t"):
            nombres.append(linea.split("\t")[2])

    por_punto = len(datos) // n_pts
    if por_punto == 8 + 4 * (n_var - 1):
        dt = np.dtype([("t", "<f8"), ("v", "<f4", (n_var - 1,))])
        reg = np.frombuffer(datos, dtype=dt, count=n_pts)
        t, v = reg["t"].astype(np.float64), reg["v"].astype(np.float64)
    elif por_punto == 8 * n_var:
        todo = np.frombuffer(datos, dtype=np.float64).reshape(n_pts, n_var)
        t, v = todo[:, 0].copy(), todo[:, 1:].copy()
    else:
        raise SystemExit(f"{path}: formato inesperado, {por_punto} bytes por punto")

    t = np.abs(t)
    cortes = np.flatnonzero(np.diff(t) < 0) + 1
    return nombres, [(t[a:b], v[a:b])
                     for a, b in zip(np.r_[0, cortes], np.r_[cortes, n_pts])]


def columna(nombre_raw, variable, desde=0.0):
    nombres, pasos = leer_raw(os.path.join(DATOS, nombre_raw))
    t, v = pasos[0][0], pasos[0][1][:, nombres.index(variable) - 1]
    m = t >= desde
    return t[m], v[m]


def vertice(t, v, ref):
    """(instante de un vertice superior, periodo), por la FASE del oscilador.

    No sirve buscar el maximo: con el 1N4728A el vertice es una meseta, y las
    corridas divergen unos microsegundos entre si a lo largo de los dieciseis
    periodos que se simulan.

    Se usa un cruce de subida por un nivel bajo, comun a las tres corridas y
    lejos del recorte, y de ahi se llega al vertice con la geometria de la
    rampa sin recortar (ref = vmin, vmax de la corrida sin zener). Tomar el
    valor medio de cada traza no sirve: el del 1N4728A esta falseado por el
    propio recorte y corre la estimacion casi 0,2 ms.
    """
    frac = 0.35
    nivel = ref[0] + frac * (ref[1] - ref[0])
    sube = np.flatnonzero((v[:-1] < nivel) & (v[1:] >= nivel))
    cr = t[sube] + (nivel - v[sube]) * (t[sube+1] - t[sube]) / (v[sube+1] - v[sube])
    T = float(np.polyfit(np.arange(len(cr)), cr, 1)[0])
    return cr[len(cr) // 2] + T / 2 * (1 - frac), T


# ------------------------------------------------------------------
# Figura 1: el vertice de arriba, y la curva inversa de los dos zeners
# ------------------------------------------------------------------
fig, (ax, axi) = plt.subplots(1, 2, figsize=(11, 4.0))

VENTANA = 0.8      # ms a cada lado del vertice (el periodo es de 18,6 ms)
DESDE = 0.6        # s: se descarta el arranque del oscilador

_, v_ref = columna("z_sin.raw", "V(salida)", DESDE)
REF = (v_ref.min(), v_ref.max())

for etq, arch, color, ls, lw in [("sin zener", "z_sin.raw", C_SIN, "-", 3.5),
                                 ("1N4729A (3,6 V)", "z_4729.raw", C_4729, "--", 2.0),
                                 ("1N4728A (3,3 V)", "z_4728.raw", C_4728, "-", 2.0)]:
    t, v = columna(arch, "V(salida)", DESDE)
    t_pico, T = vertice(t, v, REF)
    ms = (t - t_pico) * 1e3
    m = np.abs(ms) <= VENTANA
    ax.plot(ms[m], v[m], color=color, lw=lw, ls=ls, label=etq,
            zorder=3 if ls == "--" else 2)
    pico = v[m].max()
    ax.annotate(f"{pico:.3f} V", xy=(-VENTANA*0.96, pico),
                xytext=(0, 3 if lw > 2 else -11), textcoords="offset points",
                ha="left", fontsize=8.5, color=color,
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))
    # la meseta: cuanto se queda pegado al tope, contra el periodo
    alto = m & (v >= pico - 1e-3)
    dur = t[alto].max() - t[alto].min() if alto.sum() > 1 else 0.0
    if dur > 1e-5:
        ax.annotate(f"meseta de {dur*1e3:.2f} ms\n({100*dur/T:.1f} % del período)",
                    xy=(0, pico), xytext=(0, -34), textcoords="offset points",
                    ha="center", fontsize=8.5, color=color)
        print(f"{etq}: recorta {1e3*(REF[1]-pico):.1f} mV, meseta de {dur*1e3:.2f} ms "
              f"({100*dur/T:.2f} % del periodo)")

ax.set_xlim(-VENTANA, VENTANA)
ax.set_ylim(2.80, 3.12)
ax.set_xlabel("Tiempo alrededor del vértice [ms]")
ax.set_ylabel("Salida [V]")
ax.set_title("Vértice superior, potenciómetro en 0", fontsize=11)
ax.grid(alpha=0.25)
ax.legend(loc="lower center", fontsize=9, framealpha=0.9)

nombres, pasos = leer_raw(os.path.join(DATOS, "iv.raw"))
vsw = pasos[0][0]
for var, etq, color in [("I(Va)", "1N4728A (3,3 V)", C_4728),
                        ("I(Vb)", "1N4729A (3,6 V)", C_4729)]:
    cur = np.abs(pasos[0][1][:, nombres.index(var) - 1])
    axi.semilogy(vsw, cur*1e3, color=color, lw=2, label=etq)
    i_pico = float(np.interp(V_PICO, vsw, cur)) * 1e3
    axi.plot([V_PICO], [i_pico], "o", color=color, ms=5)
    axi.annotate(f"{i_pico:.2f} mA", xy=(V_PICO, i_pico), xytext=(6, 0),
                 textcoords="offset points", fontsize=8, color=color, va="center")
    print(f"{etq}: {i_pico:.3f} mA a {V_PICO} V")

axi.axvline(V_PICO, color=C_LIM, lw=1.2, ls="--")
axi.annotate(f"pico de la\ntriangular\n{V_PICO:.2f} V".replace(".", ","),
             xy=(V_PICO, 2e-4), xytext=(-8, 0), textcoords="offset points",
             fontsize=8, color=C_LIM, ha="right", va="center")
axi.set_xlim(2.4, 4.2)
axi.set_ylim(1e-5, 2e2)
axi.set_xlabel("Tensión inversa [V]")
axi.set_ylabel("Corriente [mA]")
axi.set_title("Curva inversa de los modelos", fontsize=11)
axi.grid(alpha=0.25, which="both")
axi.legend(loc="lower right", fontsize=9, framealpha=0.9)

fig.tight_layout()
fig.savefig(os.path.join(SALIDA, "zener_vertice.png"), dpi=150)
print("figura:", os.path.join(SALIDA, "zener_vertice.png"))

# ------------------------------------------------------------------
# Figura 2: la falla de R9 abierta
# ------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 4.4))

V_LIM = (VCO_MAX - AMP_OFF) / AMP_G     # 3,63 V: lo maximo que admite el VCO
V_SAT = (AMP_VCC - AMP_OFF) / AMP_G     # 4,03 V: arriba de aca el ampli satura

# remuestreo parejo: cada corrida trae pasos de tiempo muy distintos
ms = np.linspace(0, 60, 3000)
for etq, arch, color, ls in [("R9 abierta, sin zener", "f_sin.raw", C_SIN, "-"),
                             ("R9 abierta, con 1N4729A", "f_4729.raw", C_4729, "-"),
                             ("funcionamiento normal", "z_sin.raw", C_LIM, "--")]:
    t, v = columna(arch, "V(salida)", 0.55)
    ax.plot(ms, np.interp(DESDE + ms*1e-3, t, v), color=color, lw=2, ls=ls, label=etq)

ax.axhspan(V_LIM, 11, color="#b5442f", alpha=0.05, zorder=0)
for y, txt, col, dy, va, ha, x in (
        (V_LIM, f"máximo admisible por el VCO: {V_LIM:.2f} V "
                f"(= {VCO_MAX:.0f} V a su entrada)", "#b5442f", -4, "top", "left", 0.015),
        (V_SAT, f"arriba de {V_SAT:.2f} V el amplificador satura: "
                f"el VCO ve sus {AMP_VCC:.0f} V", "#8a6a2f", 4, "bottom", "right", 0.985)):
    ax.axhline(y, color=col, lw=1.3, ls=":")
    ax.annotate(txt.replace(".", ","), xy=(x, y), xycoords=("axes fraction", "data"),
                xytext=(0, dy), textcoords="offset points", ha=ha, va=va,
                fontsize=8.5, color=col,
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))

for arch, color, dy in (("f_sin.raw", C_SIN, 6), ("f_4729.raw", C_4729, -16)):
    _, v = columna(arch, "V(salida)", 0.55)
    pico = v.max()
    vco = min(AMP_G * pico + AMP_OFF, AMP_VCC)
    ax.annotate(f"{pico:.2f} V  →  VCO a {vco:.1f} V".replace(".", ","),
                xy=(57, pico), xytext=(0, dy), textcoords="offset points",
                ha="right", fontsize=9, color=color,
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5))
    print(f"{arch}: pico {pico:.4f} V -> VCO a {vco:.2f} V")

ax.set_xlim(0, 60)
ax.set_ylim(0, 11)
ax.set_xlabel("Tiempo [ms]")
ax.set_ylabel("Salida del generador [V]")
ax.grid(alpha=0.25)
ax.legend(loc="center left", fontsize=9, framealpha=0.9)

fig.tight_layout()
fig.savefig(os.path.join(SALIDA, "zener_falla.png"), dpi=150)
print("figura:", os.path.join(SALIDA, "zener_falla.png"))
