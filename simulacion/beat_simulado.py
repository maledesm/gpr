"""
Simulador de señal de beat FMCW  →  salida de audio de la notebook
=================================================================

Genera la señal que entregaría el mixer del GPR ante un conjunto de blancos a
distintas profundidades, y la guarda como WAV para reproducirla por el jack de
auriculares hacia la entrada del PCM1808.

La idea: la banda de beat de un FMCW con sweep rápido cae dentro del audio, así
que la placa de sonido de cualquier notebook alcanza para simularlo con 16 bits
(~96 dB), mucho mejor que el PWM de 8 bits de un Arduino.

Uso
---
    python beat_simulado.py

Genera 'beat_gpr.wav'. Reproducilo EN BUCLE con cualquier reproductor (VLC:
tecla L; Windows Media Player: repetir) y conectá el jack a la entrada del
módulo.

Para reproducir directo desde Python, sin archivo intermedio:
    pip install sounddevice
y el script lo detecta solo.
"""

import os
import numpy as np
from scipy.io import wavfile

# ─── Parámetros del radar ────────────────────────────────────────────────────

C        = 3e8
F_START  = 1.00e9
F_STOP   = 1.75e9
BW       = F_STOP - F_START      # 750 MHz

T_SWEEP    = 10e-3               # 10 ms  ← el sweep acelerado que hay que lograr
EPSILON_R  = 1.0                 # 1.0 = aire · 9.0 ≈ suelo húmedo

# ─── Blancos: (profundidad en metros, amplitud en dB) ────────────────────────
# La amplitud va explícita en dB en vez de derivarse de 1/R², porque el rango
# dinámico es justamente lo que querés controlar al probar el procesamiento.
#
# Con la ley 1/R² pura, el acoplamiento directo a 0.15 m queda 66 dB por encima
# del blanco a 3 m y lo entierra. Eso es lo que pasa en un GPR real y es EL
# problema del método, pero para validar la cadena conviene arrancar con todos
# los blancos visibles e ir apretando el rango dinámico después.

BLANCOS = [
    (0.15,   0.0),   # acoplamiento directo TX→RX (el eco dominante)
    (0.60, -20.0),   # interfaz aire-suelo
    (1.50, -35.0),   # blanco enterrado
    (3.00, -45.0),   # blanco profundo
]

RUIDO_DB = -60.0                 # ruido blanco relativo al pico, en dB
                                 # deja 15 dB de margen sobre el blanco más débil

# ─── Parámetros del archivo de audio ─────────────────────────────────────────

FS_AUDIO  = 48000                # frecuencia de la placa de sonido
DURACION  = 60.0                 # segundos
PICO      = 0.5                  # 0.5 = mitad de fondo de escala, deja margen
SALIDA    = "beat_gpr.wav"

# ─── Cálculo ─────────────────────────────────────────────────────────────────

v_prop = C / np.sqrt(EPSILON_R)          # velocidad en el medio
hz_por_metro = 2.0 * BW / (v_prop * T_SWEEP)

n_por_sweep = int(round(T_SWEEP * FS_AUDIO))
n_sweeps    = int(DURACION / T_SWEEP)

print("Simulador de beat FMCW")
print("=" * 62)
print(f"  BW           : {BW/1e6:.0f} MHz")
print(f"  T_sweep      : {T_SWEEP*1e3:.2f} ms  ({1/T_SWEEP:.0f} sweeps/s)")
print(f"  epsilon_r    : {EPSILON_R}  (v = {v_prop/1e8:.2f}e8 m/s)")
print(f"  Beat         : {hz_por_metro:.1f} Hz por metro")
print(f"  Resolucion   : {v_prop/(2*BW)*100:.1f} cm")
print(f"  Muestras/sweep: {n_por_sweep}   Sweeps: {n_sweeps}")
print()
print("  Blancos simulados:")
print("    Profundidad   Amplitud      f_beat")

# Un solo sweep: dentro de cada rampa el beat de cada blanco es un tono puro.
# Al repetir el bloque aparece sola la discontinuidad del flyback, igual que en
# el radar real.
t = np.arange(n_por_sweep) / FS_AUDIO
sweep = np.zeros(n_por_sweep)

f_max = 0.0
for r, amp_db in BLANCOS:
    f_beat = hz_por_metro * r
    amp    = 10.0 ** (amp_db / 20.0)
    fase   = np.random.uniform(0, 2 * np.pi)
    sweep += amp * np.sin(2 * np.pi * f_beat * t + fase)
    f_max = max(f_max, f_beat)
    print(f"    {r:6.2f} m    {amp_db:6.1f} dB    {f_beat:8.1f} Hz")

# Repetir el sweep hasta completar la duración
señal = np.tile(sweep, n_sweeps)

# Ruido blanco
pico_limpio = np.max(np.abs(señal))
sigma = pico_limpio * (10 ** (RUIDO_DB / 20.0))
señal += np.random.normal(0.0, sigma, len(señal))

# Normalizar
señal = señal / np.max(np.abs(señal)) * PICO

print()
print(f"  f_beat maxima : {f_max:.0f} Hz")
print(f"  -> el ESP32 necesita fs_eff >= {2.5*f_max:.0f} Hz")
print(f"     sugerido:  fs 32000  +  dec 4   (fs_eff = 8000 Hz)")
print()

if f_max > FS_AUDIO / 2:
    print("  [AVISO] La beat maxima supera Nyquist de la placa de sonido.")
    print("          Aumenta T_SWEEP o reduce la profundidad maxima.")

# ─── Guardar ─────────────────────────────────────────────────────────────────

os.chdir(os.path.dirname(os.path.abspath(__file__)))
wavfile.write(SALIDA, FS_AUDIO, (señal * 32767).astype(np.int16))
print(f"  Guardado: {SALIDA}  ({len(señal)/FS_AUDIO:.1f} s, {os.path.getsize(SALIDA)/1e6:.1f} MB)")

# ─── Reproducción directa, si está sounddevice ───────────────────────────────

try:
    import sounddevice as sd
    print()
    print("  sounddevice detectado: reproduciendo en bucle. Ctrl+C para cortar.")
    while True:
        sd.play(señal, FS_AUDIO, blocking=True)
except ImportError:
    print()
    print("  Reproducilo en BUCLE con VLC (tecla L) o el reproductor que uses.")
except KeyboardInterrupt:
    print("\n  Detenido.")
