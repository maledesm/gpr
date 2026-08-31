"""
GPRv2 - Radargrama (distancia vs. tiempo)
===========================================

Trocea una captura larga (varios "barridos" seguidos, grabados con
grabar_rampa.py) en ventanas de T_SWEEP y les aplica la misma corrección de
no linealidad que correccion_no_linealidad.py, ventana por ventana.
Reusa sus funciones en vez de duplicar la corrección.

El resultado es un radargrama: tiempo de captura en x, distancia en y,
potencia en color. Un blanco que se mueve (ej. correr una chapa metálica a
mano) aparece como una traza que se desplaza en el eje de distancia - sirve
para confirmar de un vistazo que el radar responde al movimiento.

OJO: sin sync (paso 1 del roadmap de GPRv2/CONTEXTO.md), las ventanas NO
están alineadas a rampas reales del generador: son cortes de T_SWEEP
segundos sobre el stream continuo, y el corte puede caer a mitad de una
rampa real y mezclar dos. Cada ventana sigue siendo válida en sí misma (el
blanco está quieto en esos 50 ms); lo que puede fallar es la prolijidad
del recorte, no la corrección. Con sync esto se arregla solo.

Uso
---
    python waterfall.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from correccion_no_linealidad import (
    VCO_CSV, T_SWEEP, C,
    cargar_curva_vco, eje_theta, remuestrear, perfil_distancia,
)

CSV_ENTRADA = os.path.join("..", "datos", "captura.csv")
FS_CSV = 2000.0    # sps de la salida diezmada de adquisicion.ino
D_MAX = 5.0        # m, recorte del eje de distancia para el gráfico


def main():
    curva_vco = cargar_curva_vco(VCO_CSV)
    crudo = pd.read_csv(CSV_ENTRADA, header=None).iloc[:, 0].to_numpy(dtype=float)

    n_ventana = int(round(T_SWEEP * FS_CSV))
    n_ventanas = len(crudo) // n_ventana
    if n_ventanas < 2:
        raise SystemExit(f"Solo hay {len(crudo)} muestras ({n_ventana} por ventana) - "
                          f"grabá más tiempo con grabar_rampa.py (subí DURACION_S).")
    bloques = crudo[:n_ventanas * n_ventana].reshape(n_ventanas, n_ventana)
    print(f"{len(crudo)} muestras -> {n_ventanas} ventanas de {n_ventana}")

    t = np.linspace(0, T_SWEEP, n_ventana, endpoint=False)
    _, theta, alpha0 = eje_theta(curva_vco, t)

    perfiles = []
    for bloque in bloques:
        _, corregido = remuestrear(theta, bloque, n_ventana)
        fs_theta = n_ventana / T_SWEEP
        rango, espectro = perfil_distancia(corregido, fs_theta, alpha0)
        perfiles.append(espectro)

    matriz = np.array(perfiles).T                       # filas=rango, columnas=tiempo
    matriz_db = 20 * np.log10(matriz / matriz.max() + 1e-12)
    tiempos = np.arange(n_ventanas) * T_SWEEP

    fig, ax = plt.subplots(figsize=(9, 5))
    m = ax.pcolormesh(tiempos, rango, matriz_db, shading="auto",
                       vmin=-40, vmax=0, cmap="viridis")
    ax.set_ylim(0, D_MAX)
    ax.set_xlabel("Tiempo de captura [s]")
    ax.set_ylabel("Distancia [m]")
    ax.set_title("Radargrama - distancia vs. tiempo")
    fig.colorbar(m, ax=ax, label="Potencia relativa [dB]")
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
