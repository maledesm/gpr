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

Salen DOS archivos, porque la placa emite dos tipos de linea intercaladas:

    datos/captura.csv     "L,sync"   una por muestra de batido
    datos/triangular.csv  "adc,indice"  una por bloque de DMA, de las
                          lineas "#v,..." - es la triangular del generador
                          leida por GPIO3, y es de donde salen los limites
                          de rampa cuando el generador no da sync.

adquisicion.ino emite las lineas "#v,..." SIEMPRE, aunque GPIO3 este al
aire. Si no llega ninguna, la placa tiene firmware viejo: hay que
reflashear firmware/adquisicion/adquisicion.ino.

Uso
---
    python grabar_rampa.py
"""

import os
import re
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
SALIDA_TRI = os.path.join(DATOS, "triangular.csv")

# El primer readline() suele agarrar una linea cortada por la mitad, y a
# ~85 kB/s cualquier hipo del CDC puede partir otra. numpy.loadtxt() se cae
# con un "12345" suelto o un "12,34,5" pegoteado, asi que se filtra aca en vez
# de descubrirlo despues en el grafico.
RE_MUESTRA = re.compile(r"^-?\d+,-?\d+$")
RE_TRI = re.compile(r"^\d+,\d+$")


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
    lineas, tri = [], []
    descartadas = 0
    t0 = time.time()
    while time.time() - t0 < DURACION_S + MARGEN_S:
        cruda = ser.readline().decode(errors="ignore").strip()
        if not cruda:
            continue
        if cruda.startswith("#v,"):
            # lectura del ADC de la triangular: "#v,<adc>,<indice>". Va a un
            # archivo aparte para no cambiarle el formato a captura.csv.
            if RE_TRI.match(cruda[3:]):
                tri.append(cruda[3:])
            else:
                descartadas += 1
        elif cruda.startswith("#"):
            pass                      # respuestas a comandos y avisos
        elif RE_MUESTRA.match(cruda):
            lineas.append(cruda)
        else:
            descartadas += 1

    ser.write(b"stop\n")
    ser.close()

    if not lineas:
        raise SystemExit("No llego ninguna muestra. Revisa que la placa este "
                          "enchufada y que el Monitor Serie del IDE este cerrado.")

    os.makedirs(DATOS, exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print(f"Guardado: {SALIDA}  ({len(lineas)} muestras)")

    # La triangular se escribe SIEMPRE que haya llegado algo, y si no llego
    # nada se borra el archivo viejo. Dejar el de la corrida anterior seria
    # peor que no tener ninguno: graficar_captura.py cortaria la captura de
    # hoy con los vertices de ayer y no habria como darse cuenta.
    if tri:
        with open(SALIDA_TRI, "w", encoding="utf-8") as f:
            f.write("\n".join(tri) + "\n")
        print(f"Guardado: {SALIDA_TRI}  ({len(tri)} lecturas de la "
              f"triangular, {len(tri)/DURACION_S:.0f}/s)")
    else:
        if os.path.exists(SALIDA_TRI):
            os.remove(SALIDA_TRI)
        print("[!] No llego ninguna linea '#v,...': la placa tiene una version "
              "vieja del firmware. Reflashea firmware/adquisicion/adquisicion.ino, "
              "que las emite siempre. Sin esas lineas y sin sync no hay de donde "
              "sacar los limites de rampa.")

    if descartadas:
        print(f"  ({descartadas} lineas cortadas descartadas, normal la "
              f"primera; muchas mas serian desborde del CDC)")


if __name__ == "__main__":
    main()
