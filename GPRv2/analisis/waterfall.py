"""
GPRv2 - Radargrama (distancia vs. tiempo)
===========================================

Trocea una captura larga (varios barridos seguidos, grabados con
grabar_rampa.py) en rampas de subida reales -cortadas por la columna de
sync, no a ciegas cada T_SWEEP- y les aplica la misma corrección de no
linealidad que correccion_no_linealidad.py, rampa por rampa. Reusa sus
funciones en vez de duplicar la corrección.

El generador de laboratorio es una triangular real: la bajada de cada ciclo
se usa también, invertida en el tiempo (ver extraer_rampas() en
correccion_no_linealidad.py) - duplica la cantidad de "fotos" por segundo
del radargrama frente a usar solo la subida.

El resultado es un radargrama: tiempo de captura en x, distancia en y,
potencia en color. Un blanco que se mueve (ej. correr una chapa metálica a
mano) aparece como una traza que se desplaza en el eje de distancia - sirve
para confirmar de un vistazo que el radar responde al movimiento.

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
    medir_rampa, extraer_rampas, rampas_desde_triangular, fs_theta,
)

# Rutas relativas a ESTE archivo, no al directorio actual: waterfall.py se
# corre tanto parado en analisis/ como desde la raiz del repo.
AQUI = os.path.dirname(os.path.abspath(__file__))
CSV_ENTRADA = os.path.join(AQUI, "..", "datos", "captura.csv")
TRIANG = os.path.join(AQUI, "..", "datos", "triangular.csv")
FS_CSV = 6000.0    # sps de la salida diezmada de adquisicion.ino
D_MAX = 5.0        # m, recorte del eje de distancia para el gráfico


def main():
    curva_vco = cargar_curva_vco(VCO_CSV)
    d = pd.read_csv(CSV_ENTRADA, header=None).to_numpy(dtype=float)
    beat, sync = d[:, 0], d[:, 1]   # adquisicion.ino emite L,sync

    n = int(round(T_SWEEP * FS_CSV))

    # Dos caminos para cortar las rampas, igual que graficar_captura.py: el
    # sync digital si lo hay, y si no la triangular que el ESP32 muestrea por
    # GPIO3 y grabar_rampa.py deja en datos/triangular.csv. El sync se acepta
    # solo si medir_rampa() lo valida: un GPIO10 al aire se acopla con la
    # rafaga de USB de cada bloque de DMA y produce una columna que PARECE
    # sync pero tiene las distancias en multiplos del tamano de bloque.
    medido = medir_rampa(sync, n) if (len(sync) and sync.max() > 0) else None
    if medido is not None:
        if medido != n:
            print(f"  rampa medida: {medido} muestras en vez de {n}")
            n = medido
        rampas, indices = extraer_rampas(beat, sync, n)
    elif os.path.exists(TRIANG):
        tri = np.loadtxt(TRIANG, delimiter=",", ndmin=2)
        if len(tri) < 10:
            raise SystemExit("datos/triangular.csv tiene muy pocas lecturas "
                              "como para ajustarle un periodo.")
        print("  sin sync: los límites de rampa salen de la triangular")
        rampas, indices, n = rampas_desde_triangular(
            beat, tri[:, 1], tri[:, 0], FS_CSV, n)
    else:
        raise SystemExit(
            "No hay de donde sacar los limites de rampa: el sync no es "
            "utilizable y no existe datos/triangular.csv. Volvé a grabar con "
            "grabar_rampa.py; si avisa que no llegan lineas '#v,...', "
            "reflasheá firmware/adquisicion/adquisicion.ino.")
    if len(rampas) < 2:
        raise SystemExit(f"Solo se encontraron {len(rampas)} rampas - "
                          f"grabá más tiempo con grabar_rampa.py (subí DURACION_S).")
    print(f"{len(beat)} muestras -> {len(rampas)} rampas de {n}")

    t = np.linspace(0, n / FS_CSV, n, endpoint=False)
    _, theta, alpha0 = eje_theta(curva_vco, t)
    fs_th = fs_theta(theta, n)   # NO es FS_CSV: ver fs_theta()

    perfiles = []
    for bloque_crudo in rampas:
        bloque = bloque_crudo - bloque_crudo.mean()
        _, corregido = remuestrear(theta, bloque, n)
        rango, espectro = perfil_distancia(corregido, fs_th, alpha0)
        perfiles.append(espectro)

    matriz = np.array(perfiles).T                       # filas=rango, columnas=tiempo
    matriz_db = 20 * np.log10(matriz / matriz.max() + 1e-12)
    tiempos = np.array(indices) / FS_CSV   # tiempo real de cada rampa (subida u
                                            # bajada invertida), no un índice a ciegas

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
