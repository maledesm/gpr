"""
Caracterizacion del filtro activo a partir del barrido con generador senoidal.

    python analisis_filtro.py

Entrada : caracterizacion_filtro_con_ganancia.csv
          (Freq, Vpp IN, Vpp OUT (G=1), Vpp OUT (G=2), Notas)
Salidas : respuesta_filtro.png
          respuesta_filtro_procesado.csv

El CSV usa COMA como separador decimal (configuracion regional argentina) y hay
celdas vacias: la curva G=1 se midio en menos puntos que la G=2.
"""

import csv
import os

import numpy as np
from scipy.interpolate import PchipInterpolator

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ENTRADA = "caracterizacion_filtro_con_ganancia.csv"

# El Vpp de una onda distorsionada NO es la amplitud de su fundamental, asi que
# un punto con distorsion visible no mide la funcion transferencia lineal.
VALIDEZ = {
    "sin distorision":      0, "sin distorsion":  0,
    "poca distorsion":      1, "hay distorsion":  2,
    "mucha distorsion":     3, "demasiada distorsion": 3,
    "ruido":                4,
}


def num(s):
    s = (s or "").strip()
    return float(s.replace(",", ".")) if s else np.nan


def cargar(ruta=ENTRADA):
    f, vi, g1, g2, nota, nivel = [], [], [], [], [], []
    with open(ruta, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            n = r["Notas"].strip()
            f.append(float(r["Freq"]))
            vi.append(num(r["Vpp IN"]))
            g1.append(num(r["Vpp OUT (G=1)"]))
            g2.append(num(r["Vpp OUT (G=2)"]))
            nota.append(n)
            nivel.append(VALIDEZ.get(n.lower(), 3))
    return (np.array(f), np.array(vi), np.array(g1), np.array(g2),
            np.array(nota), np.array(nivel))


def cruce_3db(f, db, ref, subiendo):
    """Cruce por ref-3 dB, interpolando en log(f).

    Se interpola en logaritmo porque los puntos estan espaciados
    logaritmicamente: hacerlo en escala lineal sesgaria el resultado hacia la
    frecuencia mas alta del par.
    """
    obj = ref - 3.0
    for i in range(len(f) - 1):
        a, b = db[i], db[i + 1]
        if np.isnan(a) or np.isnan(b):
            continue
        if (subiendo and a < obj <= b) or (not subiendo and a >= obj > b):
            t = (obj - a) / (b - a)
            return 10 ** (np.log10(f[i]) + t * (np.log10(f[i + 1]) - np.log10(f[i])))
    return np.nan


def spline_log(f, db, n=900):
    """Interpolacion suave en el plano (log f, dB).

    Se usa PCHIP y no un spline cubico natural a proposito: el cubico puede
    sobrepasar entre puntos separados, y con un flanco de -90 dB/decada medido
    en pocos puntos eso genera ondulaciones que NO estan en los datos. PCHIP
    preserva la forma (no inventa maximos ni minimos), que es lo que hace falta
    cuando la curva se va a leer como resultado de medicion.
    """
    m = ~np.isnan(db)
    lf = np.log10(f[m])
    sp = PchipInterpolator(lf, db[m])
    lfd = np.linspace(lf.min(), lf.max(), n)
    return 10 ** lfd, sp(lfd)


def trazar(ax, f, db, color, etiqueta, f_corte):
    """Dibuja la curva interpolada: continua mientras el dato es valido,
    punteada a partir de donde el operador reporto distorsion. Los dos tramos
    comparten el punto de corte para que no quede un hueco en el empalme."""
    fd, dd = spline_log(f, db)
    ok = fd <= f_corte
    ax.plot(fd[ok], dd[ok], "-", color=color, lw=2.0, label=etiqueta, zorder=3)
    ax.plot(fd[~ok], dd[~ok], "--", color=color, lw=2.0, alpha=0.85, zorder=3)
    return fd, dd


# ===========================================================================

f, vi, g1, g2, nota, nivel = cargar()
db1 = 20 * np.log10(g1 / vi)
db2 = 20 * np.log10(g2 / vi)
valido = nivel == 0
f_corte = f[valido].max()          # ultimo punto sin distorsion

banda = valido & (f >= 200) & (f <= 1750)
p1 = float(np.nanmedian(db1[banda]))
p2 = float(np.nanmedian(db2[banda]))

m1 = ~np.isnan(db1)   # G=1 se midio en menos puntos: hay que compactar antes
fl1 = cruce_3db(f[m1], db1[m1], p1, True)
fh1 = cruce_3db(f[m1], db1[m1], p1, False)
fl2 = cruce_3db(f, db2, p2, True)
fh2 = cruce_3db(f, db2, p2, False)

# Curvas normalizadas a su propia banda de paso: si el filtro fuese lineal, las
# dos tendrian que superponerse exactamente, porque el potenciometro solo
# escala la ganancia y no mueve los polos.
n1, n2 = db1 - p1, db2 - p2
comun = ~np.isnan(n1) & ~np.isnan(n2)
dif = n2 - n1

lineal = comun & (f <= 10000)
divergen = comun & (f >= 15000)

# --- Resumen --------------------------------------------------------------
L = "=" * 76
print(L)
print(" CARACTERIZACION DEL FILTRO ACTIVO")
print(L)
print(f" Excitacion Vpp IN  : {vi.mean():.3f} +- {vi.std():.3f} V "
      f"({100*vi.std()/vi.mean():.1f} %)")
print(f" Puntos             : {len(f)} para G=2, {np.sum(~np.isnan(g1))} para G=1")
print(f" Sin distorsion     : hasta {f_corte:.0f} Hz")
print()
print("                        G = 1            G = 2")
print(f" Banda de paso     {p1:+9.2f} dB   {p2:+9.2f} dB")
print(f"                    (x{10**(p1/20):.3f})        (x{10**(p2/20):.3f})")
print(f" Corte inferior    {fl1:9.1f} Hz   {fl2:9.1f} Hz")
print(f" Corte superior    {fh1/1000:9.1f} kHz  {fh2/1000:9.1f} kHz")
print()
print(f" Ganancia del potenciometro : {p2-p1:.2f} dB  (x{10**((p2-p1)/20):.3f})")
print()
print(" COMPARACION NORMALIZADA  (cada curva referida a SU banda de paso)")
print(f"   1 Hz a 10 kHz  : coinciden dentro de {np.nanmax(np.abs(dif[lineal])):.2f} dB")
print(f"   15 kHz en mas  : divergen hasta {np.nanmax(np.abs(dif[divergen])):.2f} dB")
print()
print("   Si el filtro fuese lineal las dos curvas normalizadas tendrian que")
print("   superponerse: el potenciometro escala la ganancia, no mueve los polos.")
print("   Que diverjan justo en el flanco superior demuestra que ESE FLANCO")
print("   DEPENDE DE LA AMPLITUD, o sea que no es la respuesta del filtro.")
print(f"   El ancho de banda real es MAYOR que los {fh1/1000:.0f} kHz de G=1,")
print("   que a su vez ya es una cota inferior.")
print(L)

# --- CSV procesado --------------------------------------------------------
with open("respuesta_filtro_procesado.csv", "w", newline="", encoding="utf-8") as fh_:
    w = csv.writer(fh_)
    w.writerow(["f_Hz", "Vpp_in_V", "Vpp_out_G1_V", "Vpp_out_G2_V",
                "H_G1_dB", "H_G2_dB", "H_G1_norm_dB", "H_G2_norm_dB",
                "diferencia_dB", "nota"])
    for i in range(len(f)):
        w.writerow([f"{f[i]:.0f}", f"{vi[i]:.3f}",
                    "" if np.isnan(g1[i]) else f"{g1[i]:.3f}",
                    "" if np.isnan(g2[i]) else f"{g2[i]:.3f}",
                    "" if np.isnan(db1[i]) else f"{db1[i]:.2f}", f"{db2[i]:.2f}",
                    "" if np.isnan(n1[i]) else f"{n1[i]:.2f}", f"{n2[i]:.2f}",
                    "" if np.isnan(dif[i]) else f"{dif[i]:.2f}", nota[i]])

# --- Figura ---------------------------------------------------------------
C1, C2 = "#1f77b4", "#e07b00"

fig, (ax, ax2) = plt.subplots(
    2, 1, figsize=(11, 9), sharex=True,
    gridspec_kw={"height_ratios": [2.6, 1.25], "hspace": 0.13})

for a in (ax, ax2):
    a.axvspan(f_corte, f.max() * 1.2, color="red", alpha=0.06, zorder=0)
    a.set_xscale("log")
    a.grid(True, which="both", alpha=0.25)
    a.set_xlim(0.85, 46000)

# ---- Panel 1: respuesta absoluta
ax.axhline(p2, color=C2, ls=":", lw=1, alpha=0.7)
ax.axhline(p2 - 3, color=C2, ls=":", lw=0.8, alpha=0.5)
ax.axhline(p1, color=C1, ls=":", lw=1, alpha=0.7)
ax.axhline(p1 - 3, color=C1, ls=":", lw=0.8, alpha=0.5)

trazar(ax, f, db2, C2, f"G = 2   ({p2:+.2f} dB,  x{10**(p2/20):.2f})", f_corte)
trazar(ax, f, db1, C1, f"G = 1   ({p1:+.2f} dB,  x{10**(p1/20):.2f})", f_corte)

# Las etiquetas de corte van a dos alturas distintas, una por curva, para que
# no se pisen entre si ni se salgan del recuadro.
for x, txt, col, y in ((fl2, f"{fl2:.1f} Hz", C2, -19.0),
                       (fl1, f"{fl1:.1f} Hz", C1, -24.0),
                       (fh2, f"{fh2/1000:.1f} kHz", C2, -19.0),
                       (fh1, f"{fh1/1000:.1f} kHz", C1, -24.0)):
    ax.axvline(x, color=col, lw=0.9, alpha=0.45)
    ax.annotate(txt, xy=(x, y), ha="center", va="center", fontsize=8.5, color=col,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=col, alpha=0.92))

ax.text(np.sqrt(f_corte * f.max()), 11.3, "zona con distorsion\n(trazo punteado)",
        ha="center", va="top", color="#a00000", fontsize=8.5, style="italic")
ax.set_ylabel("$|H(f)|$   [dB]", fontsize=11)
ax.set_ylim(-30, 12)
ax.set_title("Respuesta en frecuencia del filtro activo\n"
             f"Barrido senoidal, $V_{{in}}$ = {vi.mean():.2f} Vpp, "
             "dos posiciones del potenciometro de ganancia",
             fontsize=12, fontweight="bold")
ax.legend(loc="lower left", fontsize=9.5, framealpha=0.94)

# ---- Panel 2: normalizadas, para ver si la forma cambia con la amplitud
ax2.axhline(0, color="gray", lw=1, ls="--")
ax2.axhspan(-0.5, 0.5, color="green", alpha=0.10)
trazar(ax2, f[comun], dif[comun], "#8b008b", "G=2 menos G=1  (normalizadas)", f_corte)
ax2.set_ylabel("Diferencia\nnormalizada   [dB]", fontsize=10)
ax2.set_xlabel("Frecuencia   [Hz]", fontsize=11)
ax2.set_ylim(-8, 3)
ax2.legend(loc="lower left", fontsize=9)
ax2.annotate("coinciden: la respuesta no depende del nivel",
             xy=(30, 0.5), xytext=(30, 2.0), fontsize=8.5, color="#0a6b0a", ha="center")

plt.savefig("respuesta_filtro.png", dpi=160, bbox_inches="tight")
print("\nGenerado: respuesta_filtro.png")
print("Generado: respuesta_filtro_procesado.csv")
