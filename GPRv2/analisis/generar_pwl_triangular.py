"""
GPRv2 - PWL del PWM que sintetiza la triangular, para probar el RC en LTspice
=============================================================================

Escribe la forma de onda CRUDA que saldria del GPIO del ESP32-C3: una
portadora de PWM cuyo ciclo de trabajo recorre una triangular. En LTspice se
carga como fuente de tension y se le prueba el RC de reconstruccion, que es
lo que hay que dimensionar.

    V1  n001  0  PWL file=pwm_triangular.pwl

LEDC del ESP32-C3 corre del reloj de 80 MHz, asi que la frecuencia de la
portadora y la resolucion estan atadas: f = 80e6 / 2**BITS. Con 10 bits son
78,125 kHz y 1024 niveles.

El RC es el compromiso central y por eso conviene simularlo en vez de
calcularlo: si corta bajo, mata el ripple pero redondea los vertices de la
triangular; si corta alto, deja pasar el ripple de la portadora, que sobre la
sintonia del VCO se traduce en jitter de frecuencia.

Uso
---
    python generar_pwl_triangular.py
"""

import os
import numpy as np

VDD        = 3.3        # V, salida del GPIO
BITS       = 10         # LEDC: 80 MHz / 2**BITS
T_TRIANG   = 40e-3      # s, periodo completo (subida + bajada)
N_PERIODOS = 2
T_FLANCO   = 10e-9      # s, transicion del GPIO. LTspice no quiere dV/dt infinito.

F_PWM   = 80e6 / 2**BITS
NIVELES = 2**BITS
AQUI    = os.path.dirname(os.path.abspath(__file__))
SALIDA  = os.path.join(AQUI, "..", "datos", "pwm_triangular.pwl")


def main():
    tp = 1.0 / F_PWM
    n_ciclos = int(round(N_PERIODOS * T_TRIANG / tp))

    # Ciclo de trabajo: triangular de 0 a 1 y de vuelta, cuantizada a NIVELES.
    t_ciclo = (np.arange(n_ciclos) + 0.5) * tp
    u = (t_ciclo % T_TRIANG) / T_TRIANG
    duty = np.where(u < 0.5, 2 * u, 2 * (1 - u))
    duty = np.round(duty * (NIVELES - 1)) / (NIVELES - 1)

    pts = []
    for k, d in enumerate(duty):
        t0 = k * tp
        alto = d * tp
        if alto <= T_FLANCO:                 # duty 0: se queda abajo
            continue
        if alto >= tp - T_FLANCO:            # duty 1: se queda arriba
            pts += [(t0, VDD), (t0 + tp, VDD)]
            continue
        pts += [(t0, 0.0),
                (t0 + T_FLANCO, VDD),
                (t0 + alto, VDD),
                (t0 + alto + T_FLANCO, 0.0)]

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        for t, v in pts:
            f.write(f"{t:.10e} {v:.3f}\n")
        f.write(f"{n_ciclos * tp:.10e} 0.000\n")

    print(f"portadora    {F_PWM/1e3:.3f} kHz  ({BITS} bits, {NIVELES} niveles)")
    print(f"triangular   {T_TRIANG*1e3:.1f} ms de periodo, {1/T_TRIANG:.1f} Hz")
    print(f"             {n_ciclos} ciclos de PWM, {n_ciclos//N_PERIODOS} por triangular")
    print(f"escalon      {VDD/NIVELES*1e3:.2f} mV")
    print(f"archivo      {os.path.normpath(SALIDA)}  ({len(pts)} puntos)")


if __name__ == "__main__":
    main()
