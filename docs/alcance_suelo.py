"""
Profundidad maxima estimada, para suelo seco y humedo, en funcion del PRF.

    python alcance_suelo.py

Combina los tres limites que compiten:

  1. ATENUACION del suelo    -> no depende del PRF, pero se mide contra el
                                presupuesto de SNR, que SI depende del PRF
                                a traves de la ganancia de proceso.
  2. AMBIGUEDAD del barrido  -> los escalones del DAC generan replicas del
                                blanco cada c/(2*df). Depende del PRF porque
                                el PRF fija cuantos escalones entran.
  3. NYQUIST del ADC         -> nunca llega a ser el limitante con fs=48 kHz
                                (da 3x mas celdas que el DAC), se calcula
                                igual para verificarlo.

La profundidad reportada es el MINIMO de los tres.

ADVERTENCIA SOBRE LA PRECISION
------------------------------
Los numeros salen de la ecuacion radar con parametros SUPUESTOS, no medidos.
Los dos mas flojos son:

  - PRESUPUESTO: se toma el rango dinamico del receptor (62 dB medidos en una
    captura preliminar) como si fuera la relacion senal transmitida / piso de
    ruido. Eso vale solo si la senal de referencia en el mezclador llega a
    fondo de escala. Con la potencia de transmision real este numero cambia.
  - SIGMA del blanco: 0.05 m2 es un objeto tipo cano o piedra. Un blanco mas
    chico o mas parecido al suelo baja mucho la profundidad.

Un error de 10 dB en el presupuesto mueve la profundidad en 10/(2*alfa)
metros: 1 m en suelo seco, 12 cm en suelo humedo. O sea que en suelo humedo
el resultado es robusto y en suelo seco no.
"""

import numpy as np

# --- Radar -------------------------------------------------------------------
BW        = 1000e6        # Hz, banda 1.0 a 2.0 GHz
F_CENTRO  = 1.5e9         # Hz
C         = 3e8
G_ANT_DBI = 6.0           # ganancia de cada antena
SIGMA     = 0.05          # m2, seccion eficaz del blanco

# --- Cadena de adquisicion ---------------------------------------------------
FS        = 48000.0       # Hz
T_ESCRIT  = 125e-6        # s, una escritura I2C medida
TABLA_N   = 1024          # entradas de tabla_vco.h: tope de escalones utiles
DR_RX     = 62.0          # dB, rango dinamico medido (ver advertencia)
T_TOTAL   = 1.0           # s de integracion total

# --- Suelos ------------------------------------------------------------------
# alfa a ~1.5 GHz. Varian muchisimo con la humedad; son valores centrales de
# rangos publicados (seco 3-10, humedo 20-60 dB/m).
SUELOS = [
    ("Suelo seco",   4.0,  5.0),      # (nombre, eps_r, alfa dB/m)
    ("Suelo húmedo", 9.0, 40.0),
]

PRFS = [5e-3, 50e-3, 500e-3]          # periodo completo de la triangular


def perdida(r, lam, alfa):
    """Perdida total de ida y vuelta [dB] para un blanco puntual a distancia r.

    Ecuacion radar de blanco puntual (divergencia 1/R^4) mas la atenuacion
    exponencial del medio. Para una INTERFAZ plana la divergencia es 1/R^2 en
    vez de 1/R^4 y las profundidades dan bastante mayores: esto es el caso
    conservador.
    """
    g = 10 ** (G_ANT_DBI / 10)
    difusion = 10 * np.log10((4 * np.pi) ** 3 * r ** 4 / (g ** 2 * lam ** 2 * SIGMA))
    return difusion + 2 * alfa * r


def alcance_por_atenuacion(presupuesto, lam, alfa):
    """Resuelve perdida(R) = presupuesto por biseccion. perdida() es monotona."""
    lo, hi = 1e-3, 100.0
    if perdida(lo, lam, alfa) > presupuesto:
        return 0.0
    for _ in range(200):
        med = 0.5 * (lo + hi)
        if perdida(med, lam, alfa) < presupuesto:
            lo = med
        else:
            hi = med
    return 0.5 * (lo + hi)


# ===========================================================================

print("=" * 78)
print(" PROFUNDIDAD MAXIMA ESTIMADA vs PRF")
print("=" * 78)
print(f" BW {BW/1e6:.0f} MHz | fs {FS/1000:.0f} kHz | escritura I2C {T_ESCRIT*1e6:.0f} us"
      f" | integracion {T_TOTAL:.1f} s")
print(f" Presupuesto base {DR_RX:.0f} dB | antenas {G_ANT_DBI:.0f} dBi | sigma {SIGMA} m2")
print("=" * 78)

for nombre, eps_r, alfa in SUELOS:
    v = C / np.sqrt(eps_r)
    lam = v / F_CENTRO
    dr = v / (2 * BW)                      # celda de distancia en este medio

    print(f"\n{nombre}   (eps_r={eps_r:.0f}, alfa={alfa:.0f} dB/m, "
          f"v=c/{np.sqrt(eps_r):.0f}, resolucion={dr*100:.1f} cm)")
    print("-" * 78)
    print(f"{'PRF':>8} {'pasos':>7} {'G proc':>8} {'G proc':>8} "
          f"{'atenua':>8} {'atenua':>8} {'ambig':>8} {'LIMITE':>8} {'LIMITE':>8}")
    print(f"{'':>8} {'DAC':>7} {'sinc':>8} {'sin':>8} "
          f"{'sinc':>8} {'sin':>8} {'DAC':>8} {'sinc':>8} {'sin':>8}")
    print("-" * 78)

    for prf in PRFS:
        t_rampa = prf / 2.0
        n_pasos = min(int(t_rampa / T_ESCRIT), TABLA_N)
        n_muest = int(FS * t_rampa)
        m_rampas = T_TOTAL / t_rampa

        g_fft = 10 * np.log10(n_muest / 2)
        g_coh = g_fft + 10 * np.log10(m_rampas)      # promediado coherente
        g_inc = g_fft + 5 * np.log10(m_rampas)       # solo en potencia

        r_coh = alcance_por_atenuacion(DR_RX + g_coh, lam, alfa)
        r_inc = alcance_por_atenuacion(DR_RX + g_inc, lam, alfa)

        r_ambig = n_pasos * dr                        # replicas cada N celdas
        r_nyq = (n_muest / 2) * dr                    # techo del muestreo

        lim_coh = min(r_coh, r_ambig, r_nyq)
        lim_inc = min(r_inc, r_ambig, r_nyq)

        print(f"{prf*1000:>7.0f}m {n_pasos:>7d} {g_coh:>7.1f}dB {g_inc:>7.1f}dB "
              f"{r_coh:>7.2f}m {r_inc:>7.2f}m {r_ambig:>7.2f}m "
              f"{lim_coh:>7.2f}m {lim_inc:>7.2f}m")

print("\n" + "=" * 78)
print(" 'sinc' = con sincronismo de barrido (promediado coherente)")
print(" 'sin'  = sin sincronismo (solo promediado en potencia)")
print(" LIMITE = minimo entre atenuacion, ambigüedad del DAC y Nyquist")
print("=" * 78)

# Sensibilidad: cuanto mueve la profundidad un error en el presupuesto
print("\nSensibilidad a un error de 10 dB en el presupuesto:")
for nombre, eps_r, alfa in SUELOS:
    print(f"  {nombre:<14}: +-{10/(2*alfa)*100:5.0f} cm")
