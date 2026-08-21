"""
Linealizacion del barrido del VCO.

    python analisis_vco.py

Entrada : Caracteristica VCO.csv   (Vin, Freq, Vosc)
Salidas : ../firmware/prueba_mcp4725/tabla_vco.h    tabla de predistorsion
          curva_vco.png                             verificacion

EL PROBLEMA
-----------
La curva de sintonia del VCO no es lineal: la pendiente dF/dV varia de 170 a
444 MHz/V. Con una rampa lineal en TENSION, la frecuencia barre rapido en unas
zonas y lento en otras.

En un FMCW la frecuencia de beat es proporcional a dF/dt, asi que el eco de UN
solo blanco se reparte sobre todo ese rango de pendientes y el pico de
distancia se ensancha en la misma proporcion. La resolucion deja de estar dada
por el ancho de banda y pasa a estar dada por la no linealidad.

LA SOLUCION
-----------
Se invierte la curva medida: en vez de recorrer la tension linealmente, se
recorre la FRECUENCIA linealmente y se pregunta que tension hace falta en cada
instante. Donde el VCO es "rapido" la tension avanza despacio y viceversa.

La tabla se calcula aca, offline y con scipy, y el firmware solo la indexa.
Asi el ESP32-C3 no tiene que interpolar ni hacer punto flotante (no tiene FPU).
"""

import csv
import os

import numpy as np
from scipy.interpolate import PchipInterpolator

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- Parametros -------------------------------------------------------------

ENTRADA   = "Caracteristica VCO.csv"
SALIDA_H  = os.path.join("..", "firmware", "prueba_mcp4725", "tabla_vco.h")

VDD       = 3.300     # tension de alimentacion REAL del MCP4725. Medila con el
                      # tester: la salida va de 0 a VDD, asi que un error aca
                      # escala todas las tensiones y corre todo el barrido.
V_MAX_USO = 3.000     # tope de tension que se le permite al DAC
TABLA_N   = 1024      # entradas de la tabla (2 KB de flash)


def num(s):
    s = (s or "").strip()
    return float(s.replace(",", ".")) if s else np.nan


def cargar(ruta=ENTRADA):
    v, f, vo = [], [], []
    with open(ruta, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            v.append(num(r["Vin"]))
            f.append(num(r["Freq"]))
            vo.append(num(r.get("Vosc", "")))
    return np.array(v), np.array(f), np.array(vo)


# ===========================================================================

V, F, VO = cargar()

if not np.all(np.diff(F) > 0):
    raise SystemExit("La curva no es monotona creciente: no se puede invertir.")

# Interpoladores. PCHIP y no spline cubico: preserva la forma y la monotonia,
# que es justo lo que hace falta para poder invertir sin que aparezcan
# oscilaciones inventadas entre puntos medidos.
f_de_v = PchipInterpolator(V, F)      # tension -> frecuencia
v_de_f = PchipInterpolator(F, V)      # frecuencia -> tension  (la inversa)

# Rango de frecuencia alcanzable dentro del tope de tension permitido
v0, v1 = max(V.min(), 0.0), min(V.max(), V_MAX_USO)
f0, f1 = float(f_de_v(v0)), float(f_de_v(v1))
bw = f1 - f0

# --- Construccion de la tabla ----------------------------------------------
# Frecuencia lineal en el tiempo -> se pregunta que tension hace falta.
f_obj  = np.linspace(f0, f1, TABLA_N)
v_obj  = v_de_f(f_obj)
codigos = np.clip(np.round(v_obj / VDD * 4095.0), 0, 4095).astype(int)

# --- Verificacion: que frecuencia da REALMENTE cada codigo -----------------
# El codigo esta cuantizado a 12 bits, asi que la tension no es exactamente la
# pedida. Se evalua la curva en la tension real para ver el error que queda.
v_real = codigos / 4095.0 * VDD
f_real = f_de_v(np.clip(v_real, V.min(), V.max()))
error  = f_real - f_obj

# Comparacion contra no hacer nada: rampa lineal en tension
v_lineal = np.linspace(v0, v1, TABLA_N)
f_lineal = f_de_v(v_lineal)

# Pendiente dF/dt, que es lo que fija la frecuencia de beat.
#
# Se mide sobre una VENTANA y no entre entradas adyacentes: a escala de una
# entrada domina la cuantizacion de 12 bits del DAC (el paso de la tabla es de
# 1 MHz y el del DAC de 0.27 MHz, asi que entradas vecinas caen a veces en el
# mismo codigo). Esa variacion es un artefacto numerico, no un ensanchamiento
# del pico de distancia. La ventana de 32 entradas es el 3 % del barrido, que
# si es la escala en la que un error de pendiente se traduce en error de rango.
VENTANA = 32


def pendiente(f, w=VENTANA):
    return (f[w:] - f[:-w]) / float(w)


d_pre = pendiente(f_real)
d_lin = pendiente(f_lineal)

L = "=" * 72
print(L)
print(" LINEALIZACION DEL BARRIDO DEL VCO")
print(L)
print(f" Puntos medidos     : {len(V)}  ({V.min():.3f} a {V.max():.3f} V)")
print(f" VDD del DAC        : {VDD:.3f} V     Tope permitido: {V_MAX_USO:.3f} V")
print()
print(f" Rango util         : {v0:.3f} a {v1:.3f} V")
print(f"                      {f0:.0f} a {f1:.0f} MHz")
print(f" Ancho de banda     : {bw:.0f} MHz  -> resolucion {3e10/(2*bw*1e6):.1f} cm")
print()
print(" SIN predistorsion (rampa lineal en tension)")
print(f"   dF/dt varia      : {d_lin.min()/d_lin.mean():.2f}x a {d_lin.max()/d_lin.mean():.2f}x")
print(f"   Un blanco a 1 m  : se desparrama entre "
      f"{d_lin.min()/d_lin.mean():.2f} y {d_lin.max()/d_lin.mean():.2f} m")
print()
print(" CON predistorsion")
print(f"   dF/dt varia      : {d_pre.min()/d_pre.mean():.3f}x a {d_pre.max()/d_pre.mean():.3f}x")
print(f"   Error de frecuencia: {np.abs(error).max():.2f} MHz pico, "
      f"{error.std():.2f} MHz rms")
print(f"   Equivale a       : {np.abs(error).max()/bw*100:.3f} % del barrido")
print()
print(f" Escalon del DAC    : {VDD/4095*1000:.3f} mV -> "
      f"{VDD/4095*np.gradient(F, V).mean():.2f} MHz tipico")
print(L)

# --- Header para el firmware ------------------------------------------------
with open(SALIDA_H, "w", encoding="utf-8", newline="\n") as h:
    h.write("// Tabla de predistorsion del VCO -- GENERADA, no editar a mano.\n")
    h.write("//\n")
    h.write(f"//   Origen : VCO/{ENTRADA} ({len(V)} puntos medidos)\n")
    h.write(f"//   Script : VCO/analisis_vco.py\n")
    h.write("//\n")
    h.write("// Recorriendo la tabla a paso constante, la FRECUENCIA del VCO avanza\n")
    h.write("// linealmente en el tiempo. La tension no: avanza despacio donde el VCO\n")
    h.write("// es sensible y rapido donde es sordo.\n")
    h.write("//\n")
    h.write(f"//   VDD asumida    : {VDD:.3f} V   (si tu riel real difiere, regenerar)\n")
    h.write(f"//   Tension        : {v0:.3f} a {v1:.3f} V\n")
    h.write(f"//   Frecuencia     : {f0:.0f} a {f1:.0f} MHz   (BW {bw:.0f} MHz)\n")
    h.write(f"//   Error residual : {np.abs(error).max():.2f} MHz pico\n")
    h.write("\n#pragma once\n#include <stdint.h>\n\n")
    h.write(f"#define TABLA_VCO_N        {TABLA_N}\n")
    h.write(f"#define TABLA_VCO_F0_MHZ   {f0:.1f}f\n")
    h.write(f"#define TABLA_VCO_F1_MHZ   {f1:.1f}f\n")
    h.write(f"#define TABLA_VCO_BW_MHZ   {bw:.1f}f\n\n")
    h.write("static const uint16_t TABLA_VCO[TABLA_VCO_N] = {\n")
    for i in range(0, TABLA_N, 12):
        h.write("  " + ", ".join(f"{c:4d}" for c in codigos[i:i + 12]) + ",\n")
    h.write("};\n")
print(f"Generado: {os.path.normpath(SALIDA_H)}")

# --- Figura -----------------------------------------------------------------
fig, ax = plt.subplots(2, 2, figsize=(13, 9))
t = np.linspace(0, 1, TABLA_N)

a = ax[0, 0]
a.plot(V, F, "o", ms=4, color="#1f77b4", label=f"Medido ({len(V)} puntos)")
vv = np.linspace(V.min(), V.max(), 600)
a.plot(vv, f_de_v(vv), "-", color="#1f77b4", lw=1.2, alpha=0.7, label="PCHIP")
a.axvspan(v0, v1, color="green", alpha=0.08, label="Rango usado")
a.set_xlabel("Tension de control [V]"); a.set_ylabel("Frecuencia [MHz]")
a.set_title("Curva de sintonia medida", fontweight="bold")
a.grid(alpha=0.3); a.legend(fontsize=8)

a = ax[0, 1]
a.plot(V[:-1] + np.diff(V) / 2, np.diff(F) / np.diff(V), "o-", ms=3,
       color="#d62728", lw=1)
a.set_xlabel("Tension de control [V]"); a.set_ylabel("dF/dV [MHz/V]")
a.set_title(f"Sensibilidad: varia {np.diff(F).max()/np.diff(V)[np.argmax(np.diff(F))]:.0f}"
            f" / {(np.diff(F)/np.diff(V)).min():.0f} MHz/V", fontweight="bold")
a.grid(alpha=0.3)

a = ax[1, 0]
a.plot(t, v_lineal, "--", color="#999999", lw=1.5, label="Rampa lineal en tension")
a.plot(t, v_real, "-", color="#2ca02c", lw=2, label="Predistorsionada")
a.set_xlabel("Tiempo normalizado dentro de la rampa"); a.set_ylabel("Tension [V]")
a.set_title("Lo que sale del DAC", fontweight="bold")
a.grid(alpha=0.3); a.legend(fontsize=8)

a = ax[1, 1]
a.plot(t, f_lineal, "--", color="#999999", lw=1.5, label="Sin predistorsion")
a.plot(t, f_real, "-", color="#2ca02c", lw=2, label="Con predistorsion")
a.plot(t, f_obj, ":", color="black", lw=1, label="Ideal (recta)")
a.set_xlabel("Tiempo normalizado dentro de la rampa"); a.set_ylabel("Frecuencia [MHz]")
a.set_title(f"Resultado: error {np.abs(error).max():.2f} MHz pico", fontweight="bold")
a.grid(alpha=0.3); a.legend(fontsize=8)

plt.tight_layout()
plt.savefig("curva_vco.png", dpi=150)
print("Generado: curva_vco.png")
