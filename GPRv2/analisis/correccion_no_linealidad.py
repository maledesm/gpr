"""
GPRv2 - Corrección de no linealidad del VCO por remuestreo temporal
====================================================================

Implementa la segunda mitad de:
    Anghel et al., "Nonlinearity Correction Algorithm for Wideband FMCW
    Radars", EUSIPCO 2013 (PDF en referencias/papers/).

El paper estima la no linealidad a ciegas con la HAF, para cuando no se
conoce la curva del VCO. Acá nos salteamos esa parte: la curva ya está
medida (VCO/Caracteristica VCO.csv), así que el eje de tiempo deformado
θ(t) sale directo de ella, sin ajuste polinomial ni HAF.

Idea (siempre que la rampa de tensión V(t) sea genuinamente lineal, que es
lo que da el generador de funciones de banco):

    f(t) = curva_vco(V(t))     frecuencia real instantánea del VCO
    g(t) = f(t) - f(0)         cuánto barrió el VCO hasta el instante t
    θ(t) = g(t) / α0           eje de tiempo "como si" el barrido fuera
                               lineal, con α0 = BW/T_sweep

Remuestrear la señal de batido (uniforme en t) sobre θ uniforme deja cada
blanco como un tono puro: la FFT de esa señal remuestreada da el perfil de
distancia correcto. Ver GPRv2/CONTEXTO.md, sección 4.

Dos modos, elegís abajo en MODO:

    "sintetico" - genera una señal de batido con la no linealidad REAL del
                  VCO (tomada de la curva medida) y compara la FFT con y
                  sin corrección. No necesita hardware: valida que el
                  remuestreo funciona contra blancos de distancia conocida.

    "csv"       - lee una captura real de UNA rampa de subida (columnas de
                  muestras del ADC) y aplica la misma corrección.

                  OJO: adquisicion.ino hoy manda la salida ya diezmada a
                  2000 muestras/s fijas (ver SPS_SALIDA en el .ino), no la
                  fs real del ADC. Con T_sweep = 50 ms eso da ~100 muestras
                  por rampa - alcanza para probar que el código corre, pero
                  no para un perfil de distancia fino. Ese diezmado es para
                  mirar en el Serial Plotter, no para medir; cuando el
                  firmware grabe a fs completa (paso 3 del roadmap), este
                  modo va a dar resolución de verdad.

Uso
---
    python correccion_no_linealidad.py
"""

import os
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt

# ─── Qué correr ───────────────────────────────────────────────────────────

MODO = "sintetico"   # "sintetico" | "csv"

# Solo se usa si MODO == "csv": el CSV que graba grabar_rampa.py en
# GPRv2/datos/ (primera columna = canal L, sin encabezado). Si tiene varias
# ventanas seguidas, acá se analiza solo la primera.
CSV_ENTRADA = os.path.join("..", "datos", "captura.csv")
FS_CSV      = 2000.0   # sps de la salida diezmada de adquisicion.ino

# ─── Parámetros de la rampa hacia el VCO ─────────────────────────────────
# AJUSTAR cuando se mida la salida real del generador de laboratorio: esto
# asume que V(t) es una rampa lineal genuina de V_MIN a V_MAX en T_SWEEP.

VCO_CSV  = os.path.join("..", "..", "VCO", "Caracteristica VCO.csv")
T_SWEEP  = 50e-3          # s, rampa de subida (ver GPRv2/CONTEXTO.md)
V_MIN    = 0.0            # V
V_MAX    = 3.00           # V  -> con la curva medida da BW = 1039 MHz

# ─── Blancos para el modo sintético: (distancia en m, amplitud en dB) ────

C = 3e8
BLANCOS = [
    (0.60, -10.0),
    (1.20,   0.0),
    (3.00, -15.0),
]
RUIDO_DB = -40.0
FS_SINTETICO = 48000.0

# ─── Curva del VCO ────────────────────────────────────────────────────────

def cargar_curva_vco(path):
    """Vin (V) -> Freq (MHz), interpolada. La curva es monótona creciente."""
    df = pd.read_csv(path, decimal=",").dropna(subset=["Vin", "Freq"])
    df = df.sort_values("Vin")
    # extrapolate: la medición arranca en Vin=0,002 V, no exactamente en 0
    return interp1d(df["Vin"], df["Freq"] * 1e6, kind="cubic",
                     fill_value="extrapolate")


def eje_theta(curva_vco, t):
    """
    A partir de la rampa lineal V(t) y la curva real del VCO, arma:
      f(t)      frecuencia real instantánea
      theta(t)  eje de tiempo deformado que linealiza el barrido
      alpha0    pendiente ideal (Hz/s) usada como referencia
    """
    v_t = V_MIN + (V_MAX - V_MIN) * (t / T_SWEEP)
    f_t = curva_vco(v_t)
    g_t = f_t - f_t[0]
    bw  = curva_vco(V_MAX) - curva_vco(V_MIN)
    alpha0 = bw / T_SWEEP
    theta = g_t / alpha0
    return f_t, theta, alpha0


def remuestrear(theta, señal, n):
    """Lleva la señal de theta (no uniforme) a una grilla theta uniforme."""
    theta_uniforme = np.linspace(theta[0], theta[-1], n)
    interp = interp1d(theta, señal, kind="cubic")
    return theta_uniforme, interp(theta_uniforme)


def perfil_distancia(señal, fs, alpha0):
    """FFT -> eje de rango, con la relación ideal f_beat = 2*R*alpha0/c."""
    n = len(señal)
    espectro = np.abs(np.fft.rfft(señal * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    rango = freqs * C / (2.0 * alpha0)
    return rango, espectro


# ─── Modo sintético ───────────────────────────────────────────────────────

def generar_beat_sintetico(curva_vco, t):
    """
    Señal de batido con la no linealidad real del VCO: para un blanco a
    distancia r, la fase de batido es 2*pi*tau*(f(t) - f(0)) (tau = 2r/c).
    Con un barrido lineal ideal esto se reduce a la fórmula clásica
    f_beat = tau*alpha0 = cte; con la curva real no es constante, y ESO es
    lo que el remuestreo tiene que arreglar.
    """
    f_t = curva_vco(V_MIN + (V_MAX - V_MIN) * (t / T_SWEEP))
    g_t = f_t - f_t[0]

    señal = np.zeros_like(t)
    for r, amp_db in BLANCOS:
        tau = 2.0 * r / C
        amp = 10.0 ** (amp_db / 20.0)
        fase0 = np.random.uniform(0, 2 * np.pi)
        señal += amp * np.cos(2 * np.pi * tau * g_t + fase0)

    pico = np.max(np.abs(señal))
    señal += np.random.normal(0.0, pico * 10 ** (RUIDO_DB / 20.0), len(t))
    return señal


def correr_sintetico():
    curva_vco = cargar_curva_vco(VCO_CSV)
    n = int(round(T_SWEEP * FS_SINTETICO))
    t = np.linspace(0, T_SWEEP, n, endpoint=False)

    beat = generar_beat_sintetico(curva_vco, t)
    f_t, theta, alpha0 = eje_theta(curva_vco, t)

    print(f"BW real (curva VCO, {V_MIN}-{V_MAX} V): {(curva_vco(V_MAX)-curva_vco(V_MIN))/1e6:.1f} MHz")
    print(f"alpha0 (pendiente ideal): {alpha0/1e6:.2f} MHz/s")
    print("Blancos simulados:", BLANCOS)

    rango_sin, esp_sin = perfil_distancia(beat, FS_SINTETICO, alpha0)

    theta_u, beat_corr = remuestrear(theta, beat, n)
    fs_theta = n / (theta_u[-1] - theta_u[0])
    rango_con, esp_con = perfil_distancia(beat_corr, fs_theta, alpha0)

    graficar(t, beat, rango_sin, esp_sin, rango_con, esp_con)


# ─── Modo CSV real ────────────────────────────────────────────────────────

def correr_csv():
    curva_vco = cargar_curva_vco(VCO_CSV)
    crudo = pd.read_csv(CSV_ENTRADA, header=None).iloc[:, 0].to_numpy(dtype=float)
    # El archivo puede tener varias ventanas seguidas (grabar_rampa.py con
    # DURACION_S largo, para waterfall.py) - acá se analiza solo la primera.
    n = int(round(T_SWEEP * FS_CSV))
    beat = crudo[:n]
    t = np.linspace(0, T_SWEEP, n, endpoint=False)

    f_t, theta, alpha0 = eje_theta(curva_vco, t)
    print(f"Muestras leídas: {n}  (fs={FS_CSV} sps, T_sweep={T_SWEEP*1e3:.0f} ms)")

    rango_sin, esp_sin = perfil_distancia(beat, FS_CSV, alpha0)

    theta_u, beat_corr = remuestrear(theta, beat, n)
    fs_theta = n / (theta_u[-1] - theta_u[0])
    rango_con, esp_con = perfil_distancia(beat_corr, fs_theta, alpha0)

    graficar(t, beat, rango_sin, esp_sin, rango_con, esp_con)


# ─── Gráficos ─────────────────────────────────────────────────────────────

def graficar(t, beat, rango_sin, esp_sin, rango_con, esp_con):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(9, 8))

    ax1.plot(t * 1e3, beat)
    ax1.set_xlabel("t [ms]")
    ax1.set_ylabel("beat(t)")
    ax1.set_title("Señal de batido cruda")

    ax2.plot(rango_sin, esp_sin)
    ax2.set_xlabel("Rango [m]")
    ax2.set_title("Perfil de distancia SIN corrección")
    ax2.set_xlim(0, max(r for r, _ in BLANCOS) * 1.5 if MODO == "sintetico" else None)

    ax3.plot(rango_con, esp_con)
    ax3.set_xlabel("Rango [m]")
    ax3.set_title("Perfil de distancia CON corrección (remuestreo en θ)")
    ax3.set_xlim(0, max(r for r, _ in BLANCOS) * 1.5 if MODO == "sintetico" else None)

    fig.tight_layout()
    plt.show()


# ─── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if MODO == "sintetico":
        correr_sintetico()
    elif MODO == "csv":
        correr_csv()
    else:
        raise SystemExit(f"MODO desconocido: {MODO!r} (usar 'sintetico' o 'csv')")
