"""
GPRv2 - Graba muestras por serie a CSV
========================================

Abre el puerto del ESP32-C3 (adquisicion.ino), manda 'run', graba
DURACION_S segundos de muestras "L,R" y las guarda en GPRv2/datos/,
listas para correccion_no_linealidad.py (una sola ventana) o
waterfall.py (varias ventanas seguidas) - ambos toman la primera
columna, L.

DURACION_S por default alcanza para varias ventanas de T_SWEEP: sirve
tanto para una prueba rapida (correccion_no_linealidad.py igual solo usa
la primera ventana) como para grabar un rato moviendo un blanco a mano y
mirar el resultado en waterfall.py.

OJO: adquisicion.ino todavia no lee el sync del generador (paso 1 del
roadmap en GPRv2/CONTEXTO.md), asi que esto graba tiempo continuo
cualquiera, no rampas de subida alineadas una por una. Cada ventana de
T_SWEEP sigue siendo valida en si misma (el blanco esta quieto en esos
50 ms), pero el corte entre ventanas puede caer a mitad de una rampa real
y mezclar dos. Con sync esto se prolija solo.

Uso
---
    python grabar_rampa.py
"""

import os
import time

import serial
from serial.tools import list_ports

PUERTO = "auto"      # "auto" o algo como "COM5"
BAUD = 115200

T_SWEEP = 50e-3       # tiene que coincidir con T_SWEEP de correccion_no_linealidad.py
DURACION_S = 5.0      # cuanto grabar en total (da tiempo a mover un blanco a mano)
MARGEN_S = 0.3        # de mas, para no perder el principio por el warm-up del puerto

VID_ESPRESSIF = 0x303A

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "..", "datos")
SALIDA = os.path.join(DATOS, "captura.csv")


def detectar_puerto():
    candidatos = [p for p in list_ports.comports() if p.vid == VID_ESPRESSIF]
    if len(candidatos) == 1:
        return candidatos[0].device
    if len(candidatos) > 1:
        print("Hay varios ESP32 conectados, elegi uno a mano con PUERTO:")
        for p in candidatos:
            print("   ", p.device, "-", p.description)
    return None


def main():
    puerto = PUERTO
    if puerto == "auto":
        puerto = detectar_puerto()
        if not puerto:
            raise SystemExit("No encontre el ESP32 (esta enchufado? "
                              "el Monitor Serie del IDE tiene que estar cerrado). "
                              "Si no, poné el puerto a mano en PUERTO.")
        print(f"Puerto detectado: {puerto}")

    ser = serial.Serial(puerto, BAUD, timeout=0.2)
    time.sleep(2.0)   # el ESP32-C3 resetea al abrir el puerto USB
    ser.reset_input_buffer()
    ser.write(b"run\n")

    lineas = []
    t0 = time.time()
    while time.time() - t0 < DURACION_S + MARGEN_S:
        cruda = ser.readline().decode(errors="ignore").strip()
        if cruda and not cruda.startswith("#"):
            lineas.append(cruda)

    ser.write(b"stop\n")
    ser.close()

    os.makedirs(DATOS, exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")

    print(f"Guardado: {SALIDA}  ({len(lineas)} muestras)")


if __name__ == "__main__":
    main()
