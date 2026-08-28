"""
Lanzador: arranca la grabacion por placa de audio y el graficador en vivo.

    python medir_audio.py

Es el gemelo de adquisicion/medir.py, pero llamando a grabaraudio.py en vez de
grabarserial.py. El graficador es EL MISMO: graficarserial.py no distingue de
donde salio el CSV, porque el formato es identico.

Son dos procesos separados a proposito: si el graficador se cuelga o lo cerras,
la grabacion sigue. La grabacion es lo que no se puede perder.
"""

import glob
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, ".."))
DATOS = os.path.join(RAIZ, "datos")
GRAFICADOR = os.path.join(RAIZ, "adquisicion", "graficarserial.py")


def csvs():
    return set(glob.glob(os.path.join(DATOS, "*.csv")))


def main():
    os.makedirs(DATOS, exist_ok=True)
    antes = csvs()

    grabador = subprocess.Popen(
        [sys.executable, os.path.join(AQUI, "grabaraudio.py")])

    # Esperar a que el grabador cree el archivo. Puede tardar lo que el usuario
    # tarde en contestar las preguntas, mas el segundo y medio de verificacion
    # de la tasa de muestreo, asi que no hay timeout: se corta solo si el
    # grabador termina.
    nuevo = None
    while grabador.poll() is None and nuevo is None:
        aparecidos = csvs() - antes
        if aparecidos:
            nuevo = max(aparecidos, key=os.path.getmtime)
            time.sleep(0.6)          # que alcance a escribir el encabezado
        else:
            time.sleep(0.3)

    grafico = None
    if nuevo:
        if not os.path.exists(GRAFICADOR):
            print(f"\n  [aviso] No encuentro {GRAFICADOR}; grabo sin graficar.")
        else:
            grafico = subprocess.Popen([sys.executable, GRAFICADOR, nuevo])

    try:
        grabador.wait()
    except KeyboardInterrupt:
        # El Ctrl+C ya llego al grabador por el grupo de procesos de la consola;
        # aca solo esperamos a que cierre los archivos prolijamente.
        try:
            grabador.wait(timeout=10)
        except subprocess.TimeoutExpired:
            grabador.terminate()

    if grafico and grafico.poll() is None:
        print("\n  El grafico queda abierto. Cerralo cuando termines de mirar.")


if __name__ == "__main__":
    main()
