"""
GPRv2 - Ruido de entrada de los operacionales candidatos
========================================================

Mide la densidad de ruido de entrada de cada modelo con un .noise de LTspice,
sobre un seguidor de ganancia 1 alimentado con los mismos 12 V del circuito.
Con ganancia 1 el inoise que devuelve LTspice ES el ruido de entrada.

Sirve para no tener que creerle a la hoja de datos: el numero que va a la
tesis sale del mismo modelo con el que se simula el circuito.

Se compara contra el ruido termico de las resistencias del lazo, que es lo
que en este circuito manda: sqrt(4kTR) con R = 100k son 40,7 nV/sqrt(Hz).

Uso
---
    py ruido_opamp.py
"""

import os
import subprocess
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
LTSPICE = r"C:\Program Files\LTC\LTspice.exe"
DEST = os.path.join(AQUI, "zener")        # al lado de las otras corridas

MODELOS = ["TLC2272", "TLC2262"]
FRECUENCIAS = [10, 50, 100, 1000, 10000]
K, T_ABS = 1.380649e-23, 300.0

PLANTILLA = """\
* Ruido de entrada del {m}: seguidor de ganancia 1, alimentado con 12 V.
XU in out vp vm out {m}
V1 vp 0 6
V2 vm 0 -6
Vin in 0 AC 1
.noise V(out) Vin dec 50 1 100k
.lib ../{m}.lib
.end
"""


def leer_inoise(raw):
    crudo = open(raw, "rb").read()
    marca = "Binary:\n".encode("utf-16-le")
    i = crudo.find(marca)
    cab = crudo[:i].decode("utf-16-le")
    datos = crudo[i + len(marca):]
    n_var = int([l for l in cab.splitlines() if l.startswith("No. Variables:")][0].split(":")[1])
    n_pts = int([l for l in cab.splitlines() if l.startswith("No. Points:")][0].split(":")[1])
    nombres = [l.split("\t")[2] for l in cab.splitlines() if l.startswith("\t")]
    # como en graficar_zener.py: el eje va en doble precision y el resto en
    # simple, salvo que el .raw sea todo de 8 bytes
    por_punto = len(datos) // n_pts
    if por_punto == 8 + 4 * (n_var - 1):
        dt = np.dtype([("f", "<f8"), ("v", "<f4", (n_var - 1,))])
        reg = np.frombuffer(datos, dtype=dt, count=n_pts)
        f, v = np.abs(reg["f"]), reg["v"].astype(np.float64)
    elif por_punto == 8 * n_var:
        todo = np.frombuffer(datos, dtype=np.float64).reshape(n_pts, n_var)
        f, v = np.abs(todo[:, 0]), todo[:, 1:]
    else:
        sys.exit(f"{raw}: formato inesperado, {por_punto} bytes por punto")
    j = [k for k, n in enumerate(nombres) if "inoise" in n.lower()]
    if not j:
        sys.exit(f"{raw}: no encuentro inoise. Variables: {nombres}")
    return f, v[:, j[0] - 1]


def main():
    if not os.path.exists(LTSPICE):
        sys.exit(f"no encuentro LTspice en {LTSPICE}")
    os.makedirs(DEST, exist_ok=True)

    print("Ruido de entrada [nV/sqrt(Hz)], del modelo SPICE de cada operacional:")
    print("  f [Hz] " + "".join(f"{m:>12s}" for m in MODELOS))
    curvas = {}
    for m in MODELOS:
        cir = os.path.join(DEST, f"ruido_{m}.cir")
        open(cir, "w", encoding="ascii", newline="\r\n").write(PLANTILLA.format(m=m))
        subprocess.run([LTSPICE, "-b", cir], cwd=DEST,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        curvas[m] = leer_inoise(os.path.join(DEST, f"ruido_{m}.raw"))
    for fq in FRECUENCIAS:
        fila = "".join(f"{np.interp(fq, *curvas[m])*1e9:12.2f}" for m in MODELOS)
        print(f"  {fq:6d} {fila}")

    print("\nContra el ruido termico de las resistencias del lazo:")
    for R in (100e3, 115e3, 300e3, 768.8e3):
        print(f"  sqrt(4kTR), R = {R/1e3:6.1f}k : {1e9*(4*K*T_ABS*R)**0.5:6.1f} nV/sqrt(Hz)")


if __name__ == "__main__":
    main()
