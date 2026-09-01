"""
GPRv2 - Mira una captura: señal cruda y efecto del remuestreo
==============================================================

Dos paneles:

  1. La señal de batido con el sync superpuesto, para ver que el recorte en
     rampas es el correcto.
  2. El espectro promediado sobre todas las rampas, con y sin remuestreo,
     en eje de FRECUENCIA. Sin corregir, cada blanco se desparrama sobre
     todo el rango de frecuencias instantáneas que barre; corregido, se
     junta en un tono. Ese es el efecto que se quiere ver.

El recorte en rampas sale de la tercera columna del CSV (muestras desde el
último flanco de sync), no de cortar a ciegas cada T_SWEEP.

Uso
---
    python graficar_captura.py
"""

import os
import numpy as np
import matplotlib.pyplot as plt

from correccion_no_linealidad import (
    T_SWEEP, cargar_curva_vco, eje_theta, remuestrear,
)

FS       = 4000.0   # sps de la salida diezmada de adquisicion.ino (SPS_SALIDA)
RAMPAS   = 3        # cuántas dibujar en el panel de arriba
F_MAX    = 400.0    # Hz, recorte del eje del espectro
RELLENO  = 8        # relleno de ceros de la FFT


def espectro(x, fs, n):
    """FFT con relleno de ceros. No se usa perfil_distancia() de
    correccion_no_linealidad porque esa no rellena: con rampas de 50 ms la
    resolucion real es 1/T = 20 Hz y quedan 5 puntos por pico, con lo cual no
    se ve la forma. El relleno interpola, no agrega informacion."""
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=n))
    return np.fft.rfftfreq(n, 1.0 / fs), X

AQUI     = os.path.dirname(os.path.abspath(__file__))
CAPTURA  = os.path.join(AQUI, "..", "datos", "captura.csv")
VCO_CSV  = os.path.join(AQUI, "..", "..", "VCO", "Caracteristica VCO.csv")


def main():
    d = np.loadtxt(CAPTURA, delimiter=",")
    beat, sync = d[:, 0], d[:, 1]   # adquisicion.ino emite L,sync

    # Cada reinicio del contador de sync es el principio de una rampa.
    ini = np.where(np.diff(sync) < 0)[0] + 1
    n = int(round(T_SWEEP * FS))
    ini = ini[ini + n <= len(beat)]

    # Chequeo de salud, para diagnosticar sin tener que abrir el CSV.
    largos = np.diff(np.where(np.diff(sync) < 0)[0] + 1)
    print(f"{len(d)} muestras = {len(d)/FS:.2f} s, {len(ini)} rampas de {n}")
    print(f"  nivel L    {beat.std():9.0f} cuentas rms "
          f"({beat.std()/8388608*1500:7.1f} mVrms)   satura: "
          f"{(np.abs(beat) > 8300000).sum()} muestras")
    print(f"  sync       {sync.min():.0f} a {sync.max():.0f}, "
          f"{(sync < 0).sum()} negativos")
    print(f"  largo rampa {largos.min()} a {largos.max()} "
          f"(deberian ser todos {n})")

    curva = cargar_curva_vco(VCO_CSV)
    t = np.linspace(0, T_SWEEP, n, endpoint=False)
    _, theta, alpha0 = eje_theta(curva, t)

    nfft = RELLENO * n
    sin_c, con_c = [], []
    for k in ini:
        v = beat[k:k+n] - beat[k:k+n].mean()
        freq, esp = espectro(v, FS, nfft)
        th, corr = remuestrear(theta, v, n)
        _, esp_c = espectro(corr, n / (th[-1] - th[0]), nfft)
        sin_c.append(esp)
        con_c.append(esp_c)

    E1 = np.mean(sin_c, axis=0)
    E2 = np.mean(con_c, axis=0)
    ref = E2.max()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))

    m = ini[0] + RAMPAS * n
    tt = np.arange(ini[0], m) / FS * 1e3
    ax1.plot(tt, beat[ini[0]:m], lw=0.9, color="tab:blue", label="batido (L)")
    ax1.set_xlabel("t [ms]")
    ax1.set_ylabel("cuentas del ADC", color="tab:blue")
    ax1.tick_params(axis="y", labelcolor="tab:blue")

    axs = ax1.twinx()
    axs.plot(tt, sync[ini[0]:m], lw=1.2, color="tab:red", label="sync")
    axs.set_ylabel("muestras desde el flanco", color="tab:red")
    axs.tick_params(axis="y", labelcolor="tab:red")
    ax1.set_title(f"Señal y sync ({RAMPAS} rampas de {T_SWEEP*1e3:.0f} ms)")

    ax2.plot(freq, 20*np.log10(E1/ref + 1e-12), lw=1.2,
             label="sin remuestreo", color="tab:orange")
    ax2.plot(freq, 20*np.log10(E2/ref + 1e-12), lw=1.2,
             label="con remuestreo", color="tab:green")
    ax2.set_xlim(0, F_MAX)
    ax2.set_ylim(-40, 5)
    ax2.set_xlabel("Frecuencia de batido [Hz]")
    ax2.set_ylabel("dB rel. al pico corregido")
    ax2.set_title(f"Espectro promediado sobre {len(ini)} rampas")
    ax2.grid(alpha=0.3)
    ax2.legend()

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
