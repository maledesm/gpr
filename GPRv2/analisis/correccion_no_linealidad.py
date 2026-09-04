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

    "csv"       - lee una captura real y corrige la primera rampa de subida
                  que encuentra usando la columna de sync (ver
                  extraer_rampas() más abajo - el generador de laboratorio
                  es una triangular real, y la bajada se invierte antes de
                  poder usarla, si aparece).

                  adquisicion.ino manda la salida ya diezmada a 6000
                  muestras/s fijas (ver SPS_SALIDA en el .ino), no la fs
                  real del ADC. Con T_sweep = 20 ms eso da 120 muestras por
                  rampa, y alcanza: el ancho de bin de la FFT vale c/(2·BW)
                  cualquiera sea fs, o sea que el diezmado NO cuesta
                  resolución. Lo que fs fija es el alcance no ambiguo.

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
# GPRv2/datos/ ("L,sync", sin encabezado). Si tiene varias rampas seguidas,
# acá se analiza solo la primera (ver extraer_rampas()).
CSV_ENTRADA = os.path.join("..", "datos", "captura.csv")
FS_CSV      = 6000.0   # sps de la salida diezmada de adquisicion.ino

# ─── Parámetros de la rampa hacia el VCO ─────────────────────────────────
# AJUSTAR cuando se mida la salida real del generador de laboratorio: esto
# asume que V(t) es una rampa lineal genuina de V_MIN a V_MAX en T_SWEEP.

VCO_CSV  = os.path.join("..", "..", "VCO", "Caracteristica VCO.csv")
# 20 ms: punto medio elegido para las primeras mediciones reales de
# laboratorio (no es lo que emite el banco casero de Martin, que sigue en
# 10 ms - ver GPRv2/CLAUDE.md). Con 50 ms el acoplamiento directo TX->RX a
# 0,15 m da 20,8 Hz, pegado al corte de 19 Hz del pasabajos post-mezclador;
# con 10 ms sobra margen pero quedan la mitad de muestras por rampa para el
# remuestreo. A 20 ms el mismo acoplamiento da 52 Hz (3x el corte, comodo) y
# hay el doble de muestras que a 10 ms para la misma FS_CSV.
T_SWEEP  = 20e-3          # s, rampa de subida (ver GPRv2/CLAUDE.md)
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


def extraer_rampas(beat, sync, n, tol=0.1):
    """
    Devuelve (rampas, indices): cada rampa es un array de largo n, ya
    orientada como una SUBIDA (la bajada de una triangular llega invertida
    en el tiempo, lista para aplicarle el mismo mapa theta que a una
    subida). 'indices' es la muestra donde empieza cada una, para poder
    ubicarlas en el tiempo real de la captura.

    El generador de laboratorio es una triangular real (CONTEXTO.md §2), y
    no se sabe de antemano si el sync marca el principio de cada rampa de
    subida (una vez por rampa) o el principio de cada ciclo completo
    subida+bajada (una vez cada dos rampas) - depende del generador
    concreto y hay que verlo en el osciloscopio para saber cual es. Esta
    función no asume ninguna de las dos: mide la distancia real entre
    reinicios de 'sync' y decide segmento por segmento.
      - distancia ~= n       -> una sola subida entre reinicios (se usa tal cual).
      - distancia ~= 2*n     -> ciclo completo: la primera mitad es la
                                subida (se usa tal cual) y la segunda es la
                                bajada (se invierte con [::-1] antes de
                                usarla - el batido de una bajada simétrica,
                                leído al revés, es igual al de una subida).
      - cualquier otro valor -> se descarta (sync irregular o perdido).

    El ÚLTIMO reinicio del archivo, si no hay uno siguiente para medir la
    distancia real, se mide contra el final del archivo: si eso da ~n o ~2n
    se trata igual que cualquier otro (el archivo simplemente terminó justo
    ahí, sin nada raro). Si no da ninguno de los dos, no hay forma de saber
    si la grabación cortó a mitad de una bajada o si se perdió un flanco de
    sync - se descarta ese tramo por las dudas, no se arriesga una subida
    mezclada con datos de otra rampa.
    """
    ini = np.where(np.diff(sync) < 0)[0] + 1
    rampas, indices = [], []
    un_lado = ciclo = descartadas = 0
    for k, i in enumerate(ini):
        if i + n > len(beat):
            continue
        siguiente = ini[k + 1] if k + 1 < len(ini) else len(beat)
        gap = siguiente - i
        if abs(gap - n) <= tol * n:
            rampas.append(beat[i:i + n]); indices.append(i)
            un_lado += 1
        elif abs(gap - 2 * n) <= tol * n:
            rampas.append(beat[i:i + n]); indices.append(i)
            if i + 2 * n <= len(beat):
                rampas.append(beat[i + n:i + 2 * n][::-1]); indices.append(i + n)
            ciclo += 1
        else:
            descartadas += 1
    print(f"  rampas: {un_lado} de subida sola, {ciclo} ciclos completos "
          f"(subida+bajada invertida), {descartadas} descartadas por sync irregular")
    return rampas, indices


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
    d = pd.read_csv(CSV_ENTRADA, header=None).to_numpy(dtype=float)
    beat_completo, sync = d[:, 0], d[:, 1]   # adquisicion.ino emite L,sync
    n = int(round(T_SWEEP * FS_CSV))
    t = np.linspace(0, T_SWEEP, n, endpoint=False)

    f_t, theta, alpha0 = eje_theta(curva_vco, t)
    print(f"Muestras leídas: {len(beat_completo)}  (fs={FS_CSV} sps, T_sweep={T_SWEEP*1e3:.0f} ms, n={n})")

    rampas, _ = extraer_rampas(beat_completo, sync, n)
    if not rampas:
        raise SystemExit("No se encontró ninguna rampa completa - revisá que el sync esté conectado.")
    beat = rampas[0]

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
