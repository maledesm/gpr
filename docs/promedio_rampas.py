"""
Promedio de rampas: incoherente contra coherente, y magnitud contra potencia.

Genera las dos figuras del capitulo de procesamiento de la tesis
(redaccion/figuras/procesamiento/) y deja en consola los numeros que cita el
texto. Es una simulacion de Monte Carlo con la MISMA cadena que vivo_rapido.py
para una rampa: 300 muestras a 6000 sps, media restada, Hann, FFT con relleno
x8 (nfft = 2400). No se modela el remuestreo en theta: con un tono sintetico
ideal es la identidad, y lo que se quiere mostrar es la estadistica del
promedio, no la correccion del VCO.

Uso:
    python docs/promedio_rampas.py
"""

import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "..", "redaccion", "figuras", "procesamiento")

FS = 6000.0
N_MUESTRAS = 300          # una rampa de 50 ms
NFFT = 2400               # relleno x8, como vivo_rapido.py
F_BLANCO = 498.0          # Hz: la placa a 90 cm del 28/09 (pico_hz = 497,99)
SNR_RAMPA_DB = -12.0      # SNR por muestra de UNA rampa: el pico apenas asoma
N_FILA = 8                # rampas por fila, el valor por defecto
SEMILLA = 2026


def rampas(m, rng, fase_fija=True):
    """m rampas de batido: tono + ruido blanco gaussiano de varianza 1."""
    t = np.arange(N_MUESTRAS) / FS
    a = np.sqrt(2.0) * 10 ** (SNR_RAMPA_DB / 20)        # potencia del tono
    fase = np.zeros((m, 1)) if fase_fija else rng.uniform(0, 2 * np.pi, (m, 1))
    x = a * np.cos(2 * np.pi * F_BLANCO * t[None, :] + fase)
    x = x + rng.standard_normal((m, N_MUESTRAS))
    return x - x.mean(axis=1, keepdims=True)


def fft_rampas(x):
    """X_k complejo de cada rampa: Hann + rFFT con relleno."""
    return np.fft.rfft(x * np.hanning(N_MUESTRAS)[None, :], n=NFFT, axis=1)


def main():
    rng = np.random.default_rng(SEMILLA)
    os.makedirs(SALIDA, exist_ok=True)
    f = np.fft.rfftfreq(NFFT, 1 / FS)
    zona_ruido = (f > 1200) & (f < 2400)       # lejos del blanco y de la DC

    # ---- figura 1: espectros de una fila con los cuatro criterios ----------
    X = fft_rampas(rampas(N_FILA, rng))
    curvas = {
        "una sola rampa": np.abs(X[0]) ** 2,
        f"incoherente, magnitud (N={N_FILA})": np.mean(np.abs(X), 0) ** 2,
        f"incoherente, potencia (N={N_FILA})": np.mean(np.abs(X) ** 2, 0),
        f"coherente (N={N_FILA})": np.abs(np.mean(X, 0)) ** 2,
    }
    # Todo referido al piso de ruido de UNA rampa (potencia media del ruido
    # por bin), estimado aparte con muchas rampas de ruido puro.
    Xr = fft_rampas(rng.standard_normal((4000, N_MUESTRAS)))
    piso = np.mean(np.abs(Xr[:, zona_ruido]) ** 2)

    fig, ejes = plt.subplots(len(curvas), 1, figsize=(7.5, 8.2), sharex=True)
    print("Figura 1 - pico y piso de cada criterio (dB sobre el piso de "
          "una rampa):")
    for ax, (nombre, p) in zip(ejes, curvas.items()):
        db = 10 * np.log10(p / piso)
        ax.plot(f, db, lw=0.8, color="tab:blue")
        piso_c = 10 * np.log10(np.mean(p[zona_ruido]) / piso)
        disp = np.std(db[zona_ruido])
        pico = db[np.argmin(np.abs(f - F_BLANCO))]
        ax.axhline(piso_c, color="tab:red", ls="--", lw=0.9)
        ax.set_title(f"{nombre}:  piso {piso_c:+.1f} dB,  "
                     f"dispersión {disp:.1f} dB,  pico {pico:+.1f} dB",
                     fontsize=9)
        ax.set_ylim(-35, 25)
        ax.set_ylabel("dB")
        ax.grid(alpha=0.3)
        print(f"  {nombre:32s} piso {piso_c:+6.2f}  disp {disp:5.2f}  "
              f"pico {pico:+6.2f}")
    ejes[-1].set_xlabel("Frecuencia de batido [Hz]")
    ejes[-1].set_xlim(0, 1500)
    fig.tight_layout()
    fig.savefig(os.path.join(SALIDA, "promedio_espectros.png"), dpi=200)
    plt.close(fig)

    # ---- figura 2: piso y dispersion contra N ------------------------------
    Ns = np.array([1, 2, 4, 8, 16, 32, 64])
    rep = 300
    res = {k: ([], []) for k in ("mag", "pot", "coh")}
    for N in Ns:
        Z = fft_rampas(rng.standard_normal((rep * N, N_MUESTRAS)))
        Z = Z[:, zona_ruido].reshape(rep, N, -1)
        ests = {"mag": np.mean(np.abs(Z), 1) ** 2,
                "pot": np.mean(np.abs(Z) ** 2, 1),
                "coh": np.abs(np.mean(Z, 1)) ** 2}
        for k, e in ests.items():
            db = 10 * np.log10(e / piso)
            res[k][0].append(np.mean(10 * np.log10(np.mean(e, 1) / piso)))
            res[k][1].append(np.mean(np.std(db, 1)))

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.6))
    estilos = {"mag": ("incoherente, magnitud", "tab:blue", "o"),
               "pot": ("incoherente, potencia", "tab:green", "s"),
               "coh": ("coherente", "tab:red", "^")}
    for k, (nombre, color, m) in estilos.items():
        a1.plot(Ns, res[k][0], marker=m, color=color, label=nombre)
        a2.plot(Ns, res[k][1], marker=m, color=color, label=nombre)
    a1.plot(Ns, -10 * np.log10(Ns), "k:", lw=1, label=r"$-10\log_{10}N$")
    a1.set_title("Nivel medio del piso de ruido", fontsize=10)
    a1.set_ylabel("dB respecto de una rampa")
    a2.set_title("Dispersión del piso (desvío en dB)", fontsize=10)
    a2.set_ylabel("dB")
    for a in (a1, a2):
        a.set_xscale("log", base=2)
        a.set_xticks(Ns, [str(n) for n in Ns])
        a.set_xlabel("Rampas promediadas N")
        a.grid(alpha=0.3)
    a1.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(SALIDA, "promedio_vs_N.png"), dpi=200)
    plt.close(fig)

    print("\nFigura 2 - piso medio [dB] / dispersion [dB] contra N:")
    for i, N in enumerate(Ns):
        print(f"  N={N:3d}  mag {res['mag'][0][i]:+6.2f}/{res['mag'][1][i]:4.2f}"
              f"  pot {res['pot'][0][i]:+6.2f}/{res['pot'][1][i]:4.2f}"
              f"  coh {res['coh'][0][i]:+6.2f}/{res['coh'][1][i]:4.2f}")

    # ---- sesgos de magnitud y de log, sobre ruido puro ----------------------
    Z = Xr[:, zona_ruido].ravel()
    p_ver = np.mean(np.abs(Z) ** 2)
    sesgo_mag = 10 * np.log10(np.mean(np.abs(Z)) ** 2 / p_ver)
    sesgo_log = np.mean(10 * np.log10(np.abs(Z) ** 2)) - 10 * np.log10(p_ver)
    print(f"\nSesgo de promediar magnitud: {sesgo_mag:+.2f} dB "
          f"(teorico {10*np.log10(np.pi/4):+.2f})")
    print(f"Sesgo de promediar en dB:    {sesgo_log:+.2f} dB "
          f"(teorico {-10*np.log10(np.e)*0.5772157:+.2f})")


if __name__ == "__main__":
    main()
