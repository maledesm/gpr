"""
GPRv2 - Genera la tabla del chirp para el Arduino Uno
======================================================

El Uno sustituye a toda la cadena de RF en el banco de casa: emite una señal
de batido con la no linealidad REAL del VCO (tomada de VCO/Caracteristica
VCO.csv) más un sync que marca el principio de cada rampa. Así se puede
probar la corrección de correccion_no_linealidad.py sin VCO, sin mixer y sin
antenas: si el remuestreo funciona, el pico tiene que caer en R_BLANCO.

El ATmega328P no puede calcular un coseno a 8 kHz (le llevaría más de los
125 us que tiene por muestra), así que la forma de onda va precalculada acá
y el firmware sólo lee la tabla.

Escribe GPRv2/firmware/generador_chirp/tabla_chirp.h.

Uso
---
    python generar_tabla_chirp.py
"""

import os
import numpy as np

from correccion_no_linealidad import cargar_curva_vco, T_SWEEP, V_MIN, V_MAX, C

# ─── Parámetros ───────────────────────────────────────────────────────────

# Dos blancos: a 0.60 m la no linealidad del VCO corre el pico casi un 45 %,
# a 1.20 m solo un 8 %. Con los dos se ve el efecto grande y que la correccion
# no rompe el que ya estaba casi bien.
BLANCOS   = [0.60, 1.20]   # m
FS_UNO    = 16000     # Hz, tasa del ISR del Uno. 16 MHz / 1000 exactos.
# AMPLITUD va de la mano con RUIDO en generador_chirp.ino: los dos comparten
# el rango de 8 bits del PWM y AMPLITUD + RUIDO no puede pasar de 127.
#
#     AMPLITUD  RUIDO   SNR crudo   pico sobre piso
#         90       25     +10,1 dB       ~19 dB      <- limpio, para diagnosticar
#         29       98     -11,6 dB        5,2 dB     <- caso extremo, calibrado
#
# Los dos pares estan medidos contra el pipeline COMPLETO, con el remuestreo
# cubico. Si se cambia el remuestreo hay que rehacerlos.
AMPLITUD  = 90        # cuentas de PWM sobre el centro de 128

AQUI    = os.path.dirname(os.path.abspath(__file__))
VCO_CSV = os.path.join(AQUI, "..", "..", "VCO", "Caracteristica VCO.csv")
SALIDA  = os.path.join(AQUI, "..", "firmware", "generador_chirp", "tabla_chirp.h")


def main():
    curva = cargar_curva_vco(VCO_CSV)

    n = int(round(T_SWEEP * FS_UNO))
    t = np.linspace(0, T_SWEEP, n, endpoint=False)
    v = V_MIN + (V_MAX - V_MIN) * (t / T_SWEEP)
    f = curva(v)
    g = f - f[0]

    beat = np.zeros_like(g)
    for r in BLANCOS:
        beat += np.cos(2 * np.pi * (2.0 * r / C) * g)
    beat /= len(BLANCOS)
    tabla = np.rint(128 + AMPLITUD * beat).astype(int).clip(0, 255)

    bw = f[-1] - f[0]
    dg = np.gradient(g, t)
    print(f"BW              {bw/1e6:.1f} MHz")
    for r in BLANCOS:
        fi = (2.0 * r / C) * dg
        print(f"blanco {r:.2f} m    f_beat {fi.min():.0f} a {fi.max():.0f} Hz "
              f"(media {(2.0*r/C)*bw/T_SWEEP:.0f} Hz)")
    print(f"tabla           {n} valores a {FS_UNO} Hz = {T_SWEEP*1e3:.0f} ms")

    with open(SALIDA, "w", encoding="utf-8") as fh:
        fh.write("// Generado por GPRv2/analisis/generar_tabla_chirp.py -- no editar a mano.\n")
        fh.write(f"// Blancos {BLANCOS} m, BW {bw/1e6:.1f} MHz.\n\n")
        fh.write("#include <avr/pgmspace.h>\n\n")
        fh.write(f"#define CHIRP_N   {n}\n")
        fh.write(f"#define CHIRP_FS  {FS_UNO}\n\n")
        fh.write("const uint8_t chirp[CHIRP_N] PROGMEM = {\n")
        for i in range(0, n, 16):
            fh.write("  " + ", ".join(f"{x:3d}" for x in tabla[i:i+16]) + ",\n")
        fh.write("};\n")

    print(f"\nEscrito: {os.path.normpath(SALIDA)}")


if __name__ == "__main__":
    main()
