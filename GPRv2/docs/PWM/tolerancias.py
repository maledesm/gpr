"""
GPRv2 - Tolerancias del generador de triangular
===============================================

De donde salen los numeros del apendice de valores de componentes de la tesis.

Propaga la tolerancia de CADA resistencia fisica (las de las combinaciones en
serie van por separado, que es como estan en la placa) por las ecuaciones del
circuito, y mira los dos extremos de la salida. El operacional no interviene:
esto es el error que meten los resistores y nada mas.

    mid  = Vcc * R5/(R4+R5)                              referencia de 6 V (U2A)
    tri  de  mid - (R3/R2)*(Vcc-mid)  a  mid*(1 + R3/R2)  umbrales del Schmitt
    V+   = (tri/R8 + Vcc/R10') / (1/R8 + 1/R9' + 1/R10')
    sal  = V+*(1 + R7/R6) - mid*(R7/R6)                   restador (U2B)

con R9' = R9+R13 y R10' = R10+R14+R15.

Se reportan dos cosas distintas, que no hay que confundir:
  - el Monte Carlo, que es lo que se espera ver armando placas;
  - el peor caso exhaustivo (las 2^12 esquinas), que es la cota que no se
    puede pasar. Es bastante mas ancho y es el que manda para decidir si
    la salida puede llegar a lastimar al VCO.

Uso
---
    py tolerancias.py
"""

import itertools

import numpy as np

Vcc = 12.0
N = 200_000
SEMILLA = 20260925          # fija, para que los numeros de la tesis no se muevan

# Los valores de la placa (triangular.kicad_sch). R9' y R10' van por partes.
NOM = dict(R2=47e3, R3=12e3, R4=100e3, R5=100e3, R6=100e3, R7=100e3, R8=100e3,
           R9=100e3, R13=15e3, R10=680e3, R14=82e3, R15=6.8e3)

V_VCO = (18.0 - 0.055) / 4.949      # 3,63 V: el techo que impone el VCO


def salida(R):
    """(minimo, maximo) de la salida. Acepta escalares o arrays en R."""
    mid = Vcc * R["R5"] / (R["R4"] + R["R5"])
    k = R["R3"] / R["R2"]
    R9p = R["R9"] + R["R13"]
    R10p = R["R10"] + R["R14"] + R["R15"]
    G = 1/R["R8"] + 1/R9p + 1/R10p
    a = R["R7"] / R["R6"]
    out = []
    for tri in (mid - k * (Vcc - mid), mid * (1 + k)):
        out.append(((tri/R["R8"] + Vcc/R10p) / G) * (1 + a) - mid * a)
    return out[0], out[1]


def main():
    rng = np.random.default_rng(SEMILLA)
    nom_lo, nom_hi = salida(NOM)
    print(f"nominal: la salida va de {nom_lo:.4f} a {nom_hi:.4f} V")
    print(f"(el VCO admite hasta {V_VCO:.2f} V a la entrada del amplificador)")

    print(f"\nMonte Carlo, {N} placas, distribucion uniforme dentro de la banda:")
    for tol in (0.05, 0.01):
        R = {k: v * (1 + tol * rng.uniform(-1, 1, N)) for k, v in NOM.items()}
        lo, hi = salida(R)
        print(f"  {tol*100:2.0f} %: minimo de {lo.min():+.3f} a {lo.max():+.3f} V, "
              f"maximo de {hi.min():.3f} a {hi.max():.3f} V")
        print(f"        la salida arranca abajo de 0 V en el {100*(lo < 0).mean():4.1f} % "
              f"de las placas; pasa los {V_VCO:.2f} V en el {100*(hi > V_VCO).mean():.1f} %")

    print("\nPeor caso exhaustivo (las 2^12 esquinas, cada resistencia en un extremo):")
    esquinas = np.array(list(itertools.product([-1, 1], repeat=len(NOM))), dtype=float)
    for tol in (0.05, 0.01):
        R = {k: NOM[k] * (1 + tol * esquinas[:, i]) for i, k in enumerate(NOM)}
        lo, hi = salida(R)
        print(f"  {tol*100:2.0f} %: la salida puede ir de {lo.min():+.2f} a {hi.max():+.2f} V")

    print("\nCuanto mueve el extremo superior cada resistencia, de a una, por 1 %:")
    base = salida(NOM)[1]
    peso = []
    for k in NOM:
        d = max(abs(salida({**NOM, k: NOM[k]*1.01})[1] - base),
                abs(salida({**NOM, k: NOM[k]*0.99})[1] - base))
        peso.append((d, k))
    for d, k in sorted(peso, reverse=True):
        print(f"  {k:4s}: {d*1e3:5.1f} mV")


if __name__ == "__main__":
    main()
