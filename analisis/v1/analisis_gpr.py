"""
GPR FMCW - Análisis exploratorio v1
Objetivo: cargar los CSV del osciloscopio, verificar el chirp en CH2 (VCO)
y hacer una primera inspección de CH1 (señal recibida).
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ─── Configuración ────────────────────────────────────────────────────────────

DATA_DIR = os.path.join("..", "..", "datos")   # los CSV viven en datos/ del repo
CSV_FILES = {
    "medicion_1": os.path.join(DATA_DIR, "SDS00001.CSV"),
    "medicion_2": os.path.join(DATA_DIR, "SDS00002.CSV"),
    "medicion_3": os.path.join(DATA_DIR, "SDS00003.CSV"),
}
HEADER_ROWS = 10          # filas de metadata del osciloscopio a saltear

# ─── Carga de datos ───────────────────────────────────────────────────────────

def cargar_csv(path):
    """Lee un CSV del osciloscopio Siglent y devuelve tiempo, CH1, CH2."""
    df = pd.read_csv(
        path,
        skiprows=HEADER_ROWS,
        header=None,
        usecols=[3, 4, 5],
        names=["tiempo", "CH1", "CH2"],
    )
    df = df.dropna().astype(float).reset_index(drop=True)
    return df

# ─── Visualización básica ─────────────────────────────────────────────────────

def plot_señales_crudas(nombre, df):
    fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    fig.suptitle(f"{nombre} — Señales crudas", fontsize=13)

    axes[0].plot(df["tiempo"], df["CH1"], linewidth=0.6, color="steelblue")
    axes[0].set_ylabel("CH1 — Rx (V)")
    axes[0].set_title("Canal recibido")
    axes[0].grid(True, alpha=0.4)

    axes[1].plot(df["tiempo"], df["CH2"], linewidth=0.6, color="darkorange")
    axes[1].set_ylabel("CH2 — VCO (V)")
    axes[1].set_xlabel("Tiempo (s)")
    axes[1].set_title("Tensión de control VCO (chirp triangular)")
    axes[1].grid(True, alpha=0.4)

    plt.tight_layout()
    plt.savefig(f"{nombre}_señales_crudas.png", dpi=150)
    plt.show()
    print(f"  Guardado: {nombre}_señales_crudas.png")


def plot_espectro(nombre, df):
    """FFT simple de CH1 para ver si hay energía más allá del ruido."""
    fs = 1.0 / (df["tiempo"].iloc[1] - df["tiempo"].iloc[0])
    señal = df["CH1"].values - df["CH1"].mean()   # remover DC

    N = len(señal)
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)
    magnitud = np.abs(np.fft.rfft(señal)) * 2 / N

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(freqs, magnitud, linewidth=0.7, color="steelblue")
    ax.set_xlabel("Frecuencia (Hz)")
    ax.set_ylabel("|FFT| (V)")
    ax.set_title(f"{nombre} — Espectro de CH1 (señal recibida)")
    ax.set_xlim(0, fs / 2)
    ax.grid(True, alpha=0.4)
    plt.tight_layout()
    plt.savefig(f"{nombre}_espectro_CH1.png", dpi=150)
    plt.show()
    print(f"  Guardado: {nombre}_espectro_CH1.png")


def estadisticas(nombre, df):
    fs = 1.0 / (df["tiempo"].iloc[1] - df["tiempo"].iloc[0])
    duracion = df["tiempo"].iloc[-1] - df["tiempo"].iloc[0]
    print(f"\n{'─'*50}")
    print(f"  {nombre}")
    print(f"{'─'*50}")
    print(f"  Muestras   : {len(df)}")
    print(f"  Fs         : {fs:.1f} Hz")
    print(f"  Duración   : {duracion:.3f} s")
    print(f"  CH1  min/max/std : {df['CH1'].min():.4f} / {df['CH1'].max():.4f} / {df['CH1'].std():.4f} V")
    print(f"  CH2  min/max     : {df['CH2'].min():.4f} / {df['CH2'].max():.4f} V")


# ─── Main ─────────────────────────────────────────────────────────────────────

os.chdir(os.path.dirname(os.path.abspath(__file__)))   # output en carpeta v1/

for nombre, path in CSV_FILES.items():
    print(f"\nCargando {path} ...")
    df = cargar_csv(path)
    estadisticas(nombre, df)
    plot_señales_crudas(nombre, df)
    plot_espectro(nombre, df)

print("\nListo.")
