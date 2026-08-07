"""
GPR FMCW - Análisis procesado v2

Estructura real de CH2 (detectada del osciloscopio):
  - Rampa lenta de subida: ~1460 ms (0.08 V -> 2.2 V)  <-- UP-SWEEP a usar
  - Bajada abrupta (~1 muestra) al final del peak
  - El T_sweep real es ~1460 ms, no ~40 ms

Estrategia de segmentación:
  - Detectar valles (CH2 < umbral_bajo) como separadores entre sweeps
  - Cada segmento valle_fin[i] -> valle_inicio[i+1] = un up-sweep completo

Beat freq para target a distancia R:
  f_beat = 2 * R * BW / (c * T_sweep)
  -> Para R=1m, T=1.46s, BW=750MHz: f_beat = 3.4 Hz
  -> Para R=5m: f_beat = 17 Hz
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt

# ─── Parámetros del radar ─────────────────────────────────────────────────────

C       = 3e8
F_START = 1.00e9
F_STOP  = 1.75e9
BW      = F_STOP - F_START    # 750 MHz

D_MAX_PLOT = 5.0   # m

# ─── Archivos ─────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join("..", "..", "datos")   # los CSV viven en datos/ del repo
CSV_FILES = {
    "Medición 1 (vacío)":       os.path.join(DATA_DIR, "SDS00001.CSV"),
    "Medición 2 (vacío)":       os.path.join(DATA_DIR, "SDS00002.CSV"),
    "Medición 3 (con persona)": os.path.join(DATA_DIR, "SDS00003.CSV"),
}
HEADER_ROWS = 10

# ─── Carga ────────────────────────────────────────────────────────────────────

def cargar_csv(path):
    df = pd.read_csv(path, skiprows=HEADER_ROWS, header=None,
                     usecols=[3, 4, 5], names=["t", "CH1", "CH2"])
    return df.dropna().astype(float).reset_index(drop=True)

# ─── Segmentación por valles de CH2 ──────────────────────────────────────────

def detectar_segmentos(t, ch2):
    """
    Detecta los valles de CH2 y devuelve
    una lista de (idx_inicio, idx_fin) para cada up-sweep entre valles.
    También retorna T_sweep estimado.
    Umbral de valle = 15% del valor máximo de CH2 (robusto ante clipping).
    """
    umbral_valle  = ch2.max() * 0.10
    min_dur_muestras = max(int(fs * 0.015), 5)   # valles reales > 15 ms

    en_valle = ch2 < umbral_valle
    cambios = np.diff(en_valle.astype(int))
    inicios_all = np.where(cambios ==  1)[0] + 1
    fines_all   = np.where(cambios == -1)[0] + 1

    # Filtrar valles muy cortos (ruido de cuantización)
    pares = []
    for ini, fin in zip(inicios_all, fines_all):
        if fin > ini and (fin - ini) >= min_dur_muestras:
            pares.append((ini, fin))
    if not pares:
        return [], 0.0
    inicios_valle = np.array([p[0] for p in pares])
    fines_valle   = np.array([p[1] for p in pares])

    # Alinear: primer evento puede ser un fin (si record empieza en valle)
    if len(fines_valle) == 0 or len(inicios_valle) == 0:
        return [], 0.0
    if fines_valle[0] < inicios_valle[0]:
        fines_valle = fines_valle[1:]     # descartar fin huérfano al inicio

    n_sweeps = min(len(fines_valle), len(inicios_valle))
    segmentos = []
    for i in range(n_sweeps - 1):
        idx_ini = fines_valle[i]          # fin del valle actual
        idx_fin = inicios_valle[i + 1]    # inicio del siguiente valle
        if idx_fin > idx_ini:
            segmentos.append((idx_ini, idx_fin))

    if not segmentos:
        return [], 0.0

    T_sweep = np.mean([t[fin] - t[ini] for ini, fin in segmentos])
    return segmentos, T_sweep

# ─── Filtro pasa-altos ────────────────────────────────────────────────────────

def highpass(signal, fs, f_cutoff):
    sos = butter(4, f_cutoff, btype="high", fs=fs, output="sos")
    return sosfiltfilt(sos, signal)

# ─── Espectro promediado ──────────────────────────────────────────────────────

def espectro_promediado(t, ch1, segmentos, T_sweep):
    fs = 1.0 / (t[1] - t[0])

    # Corte HPF: por encima de la frecuencia de modulación (1/T_period)
    # T_period ≈ 2 * T_sweep (onda asimétrica, pero usamos 2x como aprox)
    f_mod    = 1.0 / (2.0 * T_sweep)
    f_cutoff = max(f_mod * 2.0, 0.5)   # mínimo 0.5 Hz
    ch1_filt = highpass(ch1, fs, f_cutoff)

    max_len = max(fin - ini for ini, fin in segmentos)
    N_fft   = int(2 ** np.ceil(np.log2(max_len)))

    acumulado = np.zeros(N_fft // 2 + 1)
    count = 0
    for ini, fin in segmentos:
        seg = ch1_filt[ini:fin].copy()
        seg -= seg.mean()
        seg_w          = seg * np.hanning(len(seg))
        seg_zp         = np.zeros(N_fft)
        seg_zp[:len(seg_w)] = seg_w
        acumulado     += np.abs(np.fft.rfft(seg_zp)) ** 2
        count         += 1

    pot_dB = 10 * np.log10(acumulado / count + 1e-20)
    freqs  = np.fft.rfftfreq(N_fft, 1.0 / fs)
    return freqs, pot_dB, f_cutoff

# ─── Frecuencia beat → distancia ─────────────────────────────────────────────

def freq_a_distancia(freqs, T_sweep):
    return (freqs * C * T_sweep) / (2.0 * BW)

# ─── Interpolación a eje común ────────────────────────────────────────────────

def interpolar(dist_src, pot_src, dist_dst):
    return np.interp(dist_dst, dist_src, pot_src)

# ─── Main ─────────────────────────────────────────────────────────────────────

os.chdir(os.path.dirname(os.path.abspath(__file__)))

eje_comun  = np.linspace(0, D_MAX_PLOT, 2000)
resultados = {}
colores    = ["steelblue", "darkorange", "seagreen"]

for nombre, path in CSV_FILES.items():
    print(f"\nProcesando {nombre} ...")
    df  = cargar_csv(path)
    t   = df["t"].values
    ch1 = df["CH1"].values
    ch2 = df["CH2"].values
    fs  = 1.0 / (t[1] - t[0])

    segmentos, T_sweep = detectar_segmentos(t, ch2)

    if not segmentos:
        print(f"  [AVISO] No se detectaron sweeps")
        continue

    freqs, pot_dB, f_cutoff = espectro_promediado(t, ch1, segmentos, T_sweep)
    distancias = freq_a_distancia(freqs, T_sweep)

    f_beat_1m  = 2 * 1.0 * BW / (C * T_sweep)
    f_beat_5m  = 2 * 5.0 * BW / (C * T_sweep)
    print(f"  Fs={fs:.0f} Hz | T_sweep={T_sweep*1000:.0f} ms | "
          f"Sweeps={len(segmentos)} | HPF={f_cutoff:.2f} Hz")
    print(f"  f_beat @ 1m={f_beat_1m:.2f} Hz | f_beat @ 5m={f_beat_5m:.2f} Hz")
    print(f"  Resolución en distancia: {C/(2*BW):.2f} m")

    pot_interp = interpolar(distancias, pot_dB, eje_comun)
    resultados[nombre] = pot_interp

# ─── Plot 1: espectros superpuestos ───────────────────────────────────────────

fig, axes = plt.subplots(2, 1, figsize=(13, 9))

for (nombre, pot), color in zip(resultados.items(), colores):
    axes[0].plot(eje_comun, pot, label=nombre, color=color, linewidth=1.2)

axes[0].set_title("GPR FMCW — Espectro promediado vs. distancia")
axes[0].set_xlabel("Distancia (m)")
axes[0].set_ylabel("Potencia (dB, escala relativa)")
axes[0].legend()
axes[0].grid(True, alpha=0.4)
axes[0].set_xlim(0, D_MAX_PLOT)

# ─── Plot 2: diferencial persona − baseline ───────────────────────────────────

nombres = list(resultados.keys())
if len(resultados) == 3:
    baseline = (resultados[nombres[0]] + resultados[nombres[1]]) / 2.0
    persona  = resultados[nombres[2]]
    diff     = persona - baseline

    axes[1].plot(eje_comun, diff, color="crimson", linewidth=1.2)
    axes[1].axhline(0, color="gray", linewidth=0.8, linestyle="--")
    axes[1].fill_between(eje_comun, diff, 0,
                         where=(diff > 0), color="crimson",  alpha=0.25,
                         label="Mayor potencia con persona")
    axes[1].fill_between(eje_comun, diff, 0,
                         where=(diff < 0), color="steelblue", alpha=0.25,
                         label="Menor potencia con persona")
    axes[1].set_title(f"Diferencial: {nombres[2]} − promedio baseline")
    axes[1].set_xlabel("Distancia (m)")
    axes[1].set_ylabel("ΔPotencia (dB)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.4)
    axes[1].set_xlim(0, D_MAX_PLOT)

plt.tight_layout()
plt.savefig("espectro_distancia.png", dpi=150)
plt.show()
print("\nGuardado: espectro_distancia.png")
