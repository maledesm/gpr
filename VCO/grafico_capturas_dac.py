"""
Las cuatro capturas del osciloscopio de la salida del DAC, apiladas.

    python grafico_capturas_dac.py  ->  dac_capturas_osciloscopio.png

Compara la rampa con y sin predistorsion, a dos PRF distintas. Sobre cada
tramo monotono se superpone su ajuste por minimos cuadrados: es la rampa
lineal que mejor lo aproxima. La separacion entre la traza y ese ajuste es
la comba de la predistorsion -- la inversa de la curva del VCO, que es lo
que hace que la FRECUENCIA barra lineal aunque la tension no lo haga.

Con predistorsion apagada esa misma separacion mide otra cosa: la linealidad
real de la rampa, y sirve de piso de comparacion.
"""

import csv
import os

import numpy as np
from scipy.signal import find_peaks

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.chdir(os.path.dirname(os.path.abspath(__file__)))
CARPETA = "Osciloscopio DAC"

VERDE = "#1B7F3B"      # con predistorsion
ROJO  = "#C43E1C"      # sin predistorsion
GRIS  = "#7A7A7A"      # ajuste lineal

# (archivo, predistorsion, PRF en ms)
CAPTURAS = [
    ("SDS00001.CSV", True,  50.0),
    ("SDS00002.CSV", False, 50.0),
    ("SDS00003.CSV", True,   5.0),
    ("SDS00004.CSV", False,  5.0),
]

# Los extremos de la triangular estan redondeados (el DAC se queda un paso en
# el tope antes de invertir). Se descarta ese 10 % de cada punta antes de
# ajustar: si no, las esquinas dominan el error y tapan lo que se quiere medir.
RECORTE = 0.10

# Comba que predice la tabla de predistorsion (la genera analisis_vco.py: 1024
# entradas, 0.002 a 3.000 V) respecto de su propia recta de ajuste. Sirve para
# contrastar contra lo medido.
COMBA_TABLA = 57.0    # mV rms   (201 mV pico)


def cargar(ruta):
    """Lee un CSV de Siglent SDS1000CML+.

    El formato pone los metadatos en las columnas 0-1 de las primeras filas y
    los datos en las columnas 3-4 desde la fila 2 (la 0 son los nombres de
    columna y la 1 las unidades). Ambos bloques conviven uno al lado del otro.
    """
    t, v, meta = [], [], {}
    with open(ruta, encoding="utf-8-sig", errors="replace") as fh:
        for i, fila in enumerate(csv.reader(fh)):
            if len(fila) >= 2 and fila[0].strip():
                meta[fila[0].strip()] = fila[1].strip()
            if i >= 2 and len(fila) >= 5:
                try:
                    t.append(float(fila[3]))
                    v.append(float(fila[4]))
                except ValueError:
                    pass
    return np.array(t), np.array(v), meta


def extremos(v, muestras_periodo):
    """Indices de picos y valles alternados: delimitan cada rampa.

    Lo que manda aca es la PROMINENCIA, no la distancia. Filtrando solo por
    distancia, find_peaks encuentra maximos locales del ruido en mitad de la
    rampa y la separacion minima no los descarta: el resultado son "picos" a
    0.7 V y "valles" a 2.3 V, y las rectas de referencia quedan ancladas en
    cualquier lado. Exigiendo que el extremo sobresalga medio pico a pico solo
    sobreviven los vertices reales de la triangular.
    """
    prom = 0.5 * (v.max() - v.min())
    d = max(int(muestras_periodo * 0.4), 5)
    picos, _ = find_peaks(v, prominence=prom, distance=d)
    valles, _ = find_peaks(-v, prominence=prom, distance=d)
    # Se etiqueta cada extremo y se descartan los repetidos del mismo tipo: si
    # quedaran dos picos seguidos, el tramo entre ellos no es una rampa y el
    # ajuste lineal no significaria nada.
    marcados = sorted([(i, +1) for i in picos] + [(i, -1) for i in valles])
    idx, ultimo = [], 0
    for i, tipo in marcados:
        if tipo != ultimo:
            idx.append(i)
            ultimo = tipo
    return np.array(idx, dtype=int)


def tramos(t_ms, v, idx):
    """Ajusta una recta a cada rampa. Devuelve (segmentos_para_dibujar, desvios)."""
    segmentos, desvios = [], []
    for a, b in zip(idx[:-1], idx[1:]):
        m = int((b - a) * RECORTE)
        s = slice(a + m, b - m)
        if s.stop - s.start < 10:
            continue
        p = np.polyfit(t_ms[s], v[s], 1)
        segmentos.append((t_ms[a:b + 1], np.polyval(p, t_ms[a:b + 1])))
        # RMS y no maximo: el osciloscopio digitaliza a 8 bits sobre 8 V de
        # pantalla, o sea ~31 mV por codigo, y el maximo se lo lleva siempre
        # alguna muestra ruidosa suelta. El RMS promedia ese ruido y deja ver
        # la comba, que es sistematica.
        desvios.append(float(np.std(v[s] - np.polyval(p, t_ms[s]))))
    return segmentos, desvios


# ===========================================================================

fig, axes = plt.subplots(4, 1, figsize=(15, 13))
resumen = []

for ax, (archivo, pre, prf_ms) in zip(axes, CAPTURAS):
    t, v, meta = cargar(os.path.join(CARPETA, archivo))
    t_ms = (t - t[0]) * 1000.0
    color = VERDE if pre else ROJO

    idx = extremos(v, prf_ms / np.median(np.diff(t_ms)))
    segmentos, desvios = tramos(t_ms, v, idx)

    for k, (xs, ys) in enumerate(segmentos):
        ax.plot(xs, ys, "--", color=GRIS, lw=2.0, zorder=2,
                label="Ajuste lineal por rampa" if k == 0 else None)
    ax.plot(t_ms, v, "-", color=color, lw=2.6, zorder=3, label="Salida del DAC")

    d = float(np.mean(desvios)) * 1000.0 if desvios else float("nan")
    estado = "CON predistorsión" if pre else "SIN predistorsión"
    detalle = (f"comba de {d:.0f} mV rms sobre la recta  (la tabla predice {COMBA_TABLA:.0f})"
               if pre else f"desvío de la recta: {d:.0f} mV rms  (piso de ruido)")
    ax.set_title(f"{estado}   ·   PRF {prf_ms:.0f} ms   ·   {archivo}   —   {detalle}",
                 fontsize=13, fontweight="bold", color=color, loc="left", pad=8)

    ax.set_ylabel("Tensión  [V]", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3, lw=1)
    ax.set_xlim(t_ms[0], t_ms[-1])
    ax.tick_params(labelsize=11)
    resumen.append((archivo, pre, prf_ms, len(v), np.median(np.diff(t)),
                    t_ms[-1], v.min(), v.max(), d))

# Misma escala vertical en los cuatro, con lugar arriba para que la leyenda no
# se monte sobre los picos.
lo = min(a.get_ylim()[0] for a in axes)
hi = max(a.get_ylim()[1] for a in axes)
for a in axes:
    a.set_ylim(lo, hi + (hi - lo) * 0.16)
    a.legend(loc="upper right", fontsize=10, framealpha=0.95, ncol=2)

axes[-1].set_xlabel("Tiempo  [ms]", fontsize=13, fontweight="bold")

fig.suptitle("Salida del DAC MCP4725 — rampa de sintonía del VCO",
             fontsize=16, fontweight="bold", y=0.985)
plt.tight_layout(rect=[0, 0, 1, 0.965])
plt.savefig("dac_capturas_osciloscopio.png", dpi=150)

print("Generado: dac_capturas_osciloscopio.png\n")
for arch, pre, prf, n, dt, dur, vmin, vmax, d in resumen:
    print(f"{arch}  pre={'ON ' if pre else 'OFF'}  PRF={prf:>2.0f} ms | "
          f"{n} pts, dt={dt*1e6:.1f} us, registro {dur:.1f} ms | "
          f"V {vmin:.2f}..{vmax:.2f} ({vmax-vmin:.2f} Vpp) | "
          f"desvio de la recta {d:.0f} mV rms")
print(f"\nComba que predice la tabla de predistorsion: {COMBA_TABLA:.0f} mV rms")
