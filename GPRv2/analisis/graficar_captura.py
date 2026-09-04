"""
GPRv2 - Mira una captura: señal cruda y efecto del remuestreo
==============================================================

Dos paneles:

  1. La señal de batido cruda, con el sync superpuesto - o con la
     triangular medida por el ADC, si el generador no da sync. Las
     verticales son los límites de rampa detectados, y sirven para
     verificar A OJO que el recorte da bien: tienen que caer alternadas en
     los MÍNIMOS de la triangular (arranque de subida) y en los MÁXIMOS
     (arranque de bajada, que se usa invertida en el tiempo).
  2. El espectro promediado sobre todas las rampas de subida (incluida la
     bajada ya invertida, si el generador la entrega), con y sin
     remuestreo, en eje de FRECUENCIA. Sin corregir, cada blanco se
     desparrama sobre todo el rango de frecuencias instantáneas que barre;
     corregido, se junta en un tono. Ese es el efecto que se quiere ver.

El recorte sale de la columna de sync del CSV, y si no hay sync, de la
triangular que el ESP32 muestrea por GPIO3 y guarda en datos/triangular.csv
(ver rampas_desde_triangular()). Nunca se corta a ciegas cada T_SWEEP: el
largo de rampa se mide, porque un generador de laboratorio no entrega
exactamente lo nominal.

Uso
---
    python graficar_captura.py
"""

import os
import numpy as np
import matplotlib.pyplot as plt

from correccion_no_linealidad import (
    T_SWEEP, cargar_curva_vco, eje_theta, remuestrear, extraer_rampas,
    medir_rampa, rampas_desde_triangular, fs_theta,
)

FS       = 6000.0   # sps de la salida diezmada de adquisicion.ino (SPS_SALIDA)
RAMPAS   = 3        # cuántas dibujar en el panel de arriba
# Recorte del eje del espectro. None = hasta Nyquist, que es lo sano: una
# constante fija esconde los picos en silencio si despues se acorta la rampa.
F_MAX    = None
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
TRIANG   = os.path.join(AQUI, "..", "datos", "triangular.csv")


def main():
    d = np.loadtxt(CAPTURA, delimiter=",")
    beat, sync = d[:, 0], d[:, 1]   # adquisicion.ino emite L,sync
    n = int(round(T_SWEEP * FS))

    # Chequeo de salud, para diagnosticar sin tener que abrir el CSV.
    ini_bruto = np.where(np.diff(sync) < 0)[0] + 1
    largos = np.diff(ini_bruto)
    print(f"{len(d)} muestras = {len(d)/FS:.2f} s, {len(ini_bruto)} reinicios de sync")
    print(f"  nivel L    {beat.std():9.0f} cuentas rms "
          f"({beat.std()/8388608*1500:7.1f} mVrms)   satura: "
          f"{(np.abs(beat) > 8300000).sum()} muestras")
    print(f"  sync       {sync.min():.0f} a {sync.max():.0f}, "
          f"{(sync < 0).sum()} negativos")
    if len(largos):
        print(f"  entre reinicios: {largos.min()} a {largos.max()} muestras "
              f"({n} = una subida sola, {2*n} = ciclo subida+bajada)")

    # Dos caminos para saber dónde empieza cada rampa. El sync digital es más
    # preciso, pero si el generador no lo da, la triangular muestreada por el
    # ADC alcanza: ver rampas_desde_triangular().
    # El sync se acepta solo si medir_rampa() lo valida. No alcanza con que la
    # columna traiga algo distinto de -1: un GPIO10 al aire se acopla con la
    # rafaga de USB de cada bloque de DMA y produce una columna que PARECE
    # sync pero tiene las distancias en multiplos del tamano de bloque.
    tri = None
    if os.path.exists(TRIANG):
        tri = np.loadtxt(TRIANG, delimiter=",", ndmin=2)

    medido = medir_rampa(sync, n) if (len(sync) and sync.max() > 0) else None
    hay_sync = medido is not None

    if hay_sync:
        if medido != n:
            print(f"  rampa medida: {medido} muestras "
                  f"({medido/FS*1e3:.2f} ms) en vez de {n} ({T_SWEEP*1e3:.2f} ms)")
            n = medido
        rampas, ini_rampas = extraer_rampas(beat, sync, n)
    elif tri is not None and len(tri) > 10:
        print("  sin sync: los límites de rampa salen de la triangular")
        rampas, ini_rampas, n = rampas_desde_triangular(
            beat, tri[:, 1], tri[:, 0], FS, n)
    else:
        raise SystemExit(
            "No hay de donde sacar los limites de rampa. El sync no es "
            "utilizable (o no esta, o es ruido de un pin al aire) y no hay "
            "datos/triangular.csv. Si ese archivo falta, la placa tiene una "
            "version vieja del firmware: el nuevo emite las lineas #v,... "
            "siempre, aunque GPIO3 este desconectado.")
    if not rampas:
        raise SystemExit("No se encontró ninguna rampa.")

    curva = cargar_curva_vco(VCO_CSV)
    t = np.linspace(0, n / FS, n, endpoint=False)
    _, theta, alpha0 = eje_theta(curva, t)

    fs_th = fs_theta(theta, n)   # NO es n/(th[-1]-th[0]): ver fs_theta()
    nfft = RELLENO * n
    sin_c, con_c = [], []
    for v_cruda in rampas:
        v = v_cruda - v_cruda.mean()
        freq, esp = espectro(v, FS, nfft)
        _, corr = remuestrear(theta, v, n)
        _, esp_c = espectro(corr, fs_th, nfft)
        sin_c.append(esp)
        con_c.append(esp_c)

    E1 = np.mean(sin_c, axis=0)
    E2 = np.mean(con_c, axis=0)
    ref = E2.max()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))

    inicio = (ini_bruto[0] if hay_sync and len(ini_bruto) else
              (ini_rampas[0] if ini_rampas else 0))
    m = min(inicio + RAMPAS * n, len(beat))
    tt = np.arange(inicio, m) / FS * 1e3
    ax1.plot(tt, beat[inicio:m], lw=0.9, color="tab:blue", label="batido (L)")
    ax1.set_xlabel("t [ms]")
    ax1.set_ylabel("cuentas del ADC", color="tab:blue")
    ax1.tick_params(axis="y", labelcolor="tab:blue")

    axs = ax1.twinx()
    if hay_sync:
        axs.plot(tt, sync[inicio:m], lw=1.2, color="tab:red", label="sync")
        axs.set_ylabel("muestras desde el flanco", color="tab:red")
        titulo = "Señal y sync crudos"
    else:
        # Sin sync se dibuja la triangular medida por el ADC, que es de donde
        # salieron los límites. Las verticales son los arranques de subida
        # detectados: tienen que caer en los MÍNIMOS de la triangular.
        sel = (tri[:, 1] >= inicio) & (tri[:, 1] < m)
        axs.plot(tri[sel, 1] / FS * 1e3, tri[sel, 0], ".-", lw=1.0, ms=4,
                 color="tab:red", label="triangular")
        axs.set_ylabel("triangular [cuentas del ADC]", color="tab:red")
        titulo = "Señal y triangular crudas"
    axs.tick_params(axis="y", labelcolor="tab:red")
    for k in ini_rampas:
        if inicio <= k < m:
            ax1.axvline(k / FS * 1e3, color="k", ls=":", lw=0.8)
    ax1.set_title(f"{titulo} - las verticales son limites de rampa: caen "
                  f"alternadas en minimos (subida) y maximos (bajada)")

    ax2.plot(freq, 20*np.log10(E1/ref + 1e-12), lw=1.2,
             label="sin remuestreo", color="tab:orange")
    ax2.plot(freq, 20*np.log10(E2/ref + 1e-12), lw=1.2,
             label="con remuestreo", color="tab:green")
    ax2.set_xlim(0, F_MAX if F_MAX else FS / 2)
    ax2.set_ylim(-40, 5)
    ax2.set_xlabel("Frecuencia de batido [Hz]")
    ax2.set_ylabel("dB rel. al pico corregido")
    ax2.set_title(f"Espectro promediado sobre {len(rampas)} rampas")
    ax2.grid(alpha=0.3)
    ax2.legend()

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
