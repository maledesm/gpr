"""
Lanzador: arranca la grabacion y el graficador con un solo comando.

    python medir.py

Corre grabarserial.py en primer plano (para que las preguntas y el Ctrl+C
funcionen normalmente) y, apenas aparece el CSV nuevo, abre graficarserial.py
apuntando a el.

Son dos procesos separados a proposito: si el graficador se cuelga o lo cerras,
la grabacion sigue. La grabacion es lo que no se puede perder.

Al terminar la captura el grafico QUEDA ABIERTO, para poder seguir mirando la
medicion con calma.
"""

import glob
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.normpath(os.path.join(AQUI, "..", "datos"))


def csvs():
    return set(glob.glob(os.path.join(DATOS, "*.csv")))


def main():
    os.makedirs(DATOS, exist_ok=True)
    antes = csvs()

    grabador = subprocess.Popen(
        [sys.executable, os.path.join(AQUI, "grabarserial.py")])

    # Esperar a que el grabador cree el archivo. Puede tardar lo que el usuario
    # tarde en contestar las preguntas, asi que no hay timeout: se corta solo
    # si el grabador termina.
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
        grafico = subprocess.Popen(
            [sys.executable, os.path.join(AQUI, "graficarserial.py"), nuevo])

    try:
        grabador.wait()
    except KeyboardInterrupt:
        # El Ctrl+C ya llego al grabador por el grupo de procesos de la consola;
        # aca solo esperamos a que cierre el archivo prolijamente.
        try:
            grabador.wait(timeout=10)
        except subprocess.TimeoutExpired:
            grabador.terminate()

    if grafico and grafico.poll() is None:
        print("\n  El grafico queda abierto. Cerralo cuando termines de mirar.")


if __name__ == "__main__":
    main()
