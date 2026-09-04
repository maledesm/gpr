"""
GPRv2 - Graba muestras por serie a CSV
========================================

Abre el puerto del ESP32-C3 (adquisicion.ino), manda 'run', graba
DURACION_S segundos de muestras "L,sync" y las guarda en GPRv2/datos/,
listas para correccion_no_linealidad.py, graficar_captura.py o
waterfall.py.

DURACION_S por default alcanza para varias rampas: sirve tanto para una
prueba rapida como para grabar un rato moviendo un blanco a mano y mirar
el resultado en waterfall.py.

adquisicion.ino ya lee el sync del generador (columna 'sync' del CSV:
muestras desde el ultimo flanco) - graficar_captura.py y waterfall.py
cortan por ahi, no a ciegas cada T_SWEEP.

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

    # Sin tocar DTR/RTS: pyserial los afirma a los dos al abrir, y en el USB
    # nativo del ESP32-C3 esa combinacion es justo la que resetea el chip. El
    # USB se re-enumera, el handle viejo queda invalido y el write de 'run'
    # falla con "El dispositivo no reconoce el comando".
    ser = serial.Serial()
    ser.port = puerto
    ser.baudrate = BAUD
    ser.timeout = 0.2
    ser.dtr = False
    ser.rts = False
    ser.open()
    time.sleep(0.5)   # que se asiente el puerto
    ser.reset_input_buffer()
    ser.write(b"run\n")

    print(f"Grabando {DURACION_S:.0f} s...")
    lineas = []
    t0 = time.time()
    while time.time() - t0 < DURACION_S + MARGEN_S:
        cruda = ser.readline().decode(errors="ignore").strip()
        if cruda and not cruda.startswith("#"):
            lineas.append(cruda)

    ser.write(b"stop\n")
    ser.close()

    if not lineas:
        raise SystemExit("No llego ninguna muestra. Revisa que la placa este "
                          "enchufada y que el Monitor Serie del IDE este cerrado.")

    os.makedirs(DATOS, exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")

    print(f"Guardado: {SALIDA}  ({len(lineas)} muestras)")


if __name__ == "__main__":
    main()
