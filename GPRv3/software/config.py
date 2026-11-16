"""
GPRv3 - Parametros del banco y del programa
===========================================

Lo que hay que tocar a mano cuando cambia el banco esta aca y en ningun otro
lado. El porque de cada valor esta en GPRv3/README.md.
"""

import os

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, ".."))
DATOS = os.path.join(RAIZ, "datos")
CAPTURAS = os.path.join(DATOS, "capturas")
CAL_JSON = os.path.join(DATOS, "calibracion_distancia.json")
CONFIG_JSON = os.path.join(DATOS, "vivo_config.json")

C = 299792458.0

# --- Barrido ---------------------------------------------------------------

VCO_CSV = os.path.join(RAIZ, "..", "VCO", "Caracteristica VCO 2026-10-19.csv")
# Vertices de la triangular a la entrada del amplificador del VCO, medidos
# con el Tektronix el 2026-11-06.
V_MIN = 0.12
V_MAX = 3.06
# Medido el 2026-11-06: el flanco de subida del sync cae en el vertice de
# ARRIBA, o sea que con el sync en alto la triangular baja.
SYNC_ALTO_ES_BAJADA = True

# --- Puerto ----------------------------------------------------------------

PUERTO = "auto"          # "auto" o algo como "COM5"
BAUD = 115200
VID_ESPRESSIF = 0x303A
SPS_DEF = 12000
SPS_OPCIONES = (3000, 6000, 12000, 24000)

# --- Rampas ----------------------------------------------------------------

T_RAMPA_MIN = 4e-3       # s, fuera de esto el flanco se toma por espurio
T_RAMPA_MAX = 0.30
TOL_RAMPA = 0.15         # cuanto puede diferir una rampa de las ultimas
MEMORIA_RAMPAS = 5       # cuantas rampas del mismo sentido se recuerdan
MARGEN_MUESTRAS = 4      # muestras de mas a cada lado para el spline
# Atraso del batido respecto del sync [s]: corre los limites de todas las
# rampas. En 0 no se compensa nada (ver README, "Retardos"). Se ajusta en el
# banco hasta que el pico de las subidas y el de las bajadas coincidan.
RETARDO_S = 0.0

# --- Perfil de distancia ---------------------------------------------------

DR_M = 0.02              # paso del eje de distancia guardado
D_MAX_M = 30.0           # hasta donde se guarda el perfil
NFFT_BASE = 4096         # largo de FFT del paso de frecuencia mas grueso
PERFILES_MAX = 6000      # rampas que se recuerdan (tope de la ventana)

# --- Programa en vivo ------------------------------------------------------

REFRESCO_MS = 100
N_DEFECTO = 8            # rampas promediadas por fila
N_MAX = 256
VENTANA_DEF = 20.0       # s de historia en pantalla
VENTANA_MAX = 300.0
ALCANCE_DEF = 5.0        # m
IGNORAR_DEF = 0.3        # m, debajo vive el acoplamiento directo
PISO_DEF, TECHO_DEF = -40.0, 0.0        # dB, sin fondo
PISO_FONDO, TECHO_FONDO = -20.0, 20.0   # dB, con fondo
PROMEDIO_CAL_S = 2.0     # cuanto se promedia para el pico y la calibracion
FONDO_S = 3.0            # cuanto se promedia al medir el fondo
MARGEN_DEF = 6.0         # dB, puerta de deteccion con fondo congelado
MARGEN_MTI = -20.0       # dB, idem con fondo automatico
TAU_MTI = 30.0           # s
TRAZA_MIN_DB = 3.0       # el pico de una fila tiene que despegarse esto
MAX_FILAS = 600          # tope de filas que se mandan a la pantalla
VENTANA_FFT_DEF = "hann"
MAPAS_COLOR = ("inferno", "viridis", "magma", "plasma", "turbo", "jet",
               "cividis", "gray")
MAPA_COLOR_DEF = "inferno"
# Ajuste automatico del retardo: hasta cuanto se acepta de diferencia entre
# el pico de las subidas y el de las bajadas, y en cuantos pasos.
AUTO_TOL_M = 0.002
AUTO_PASOS = 8
AUTO_PRIMER_PASO_S = 100e-6
RETARDO_MAX_S = 2e-3
SIN_SYNC_S = 0.6         # sin flancos durante esto: se avisa
VALLE_MAX, CIMA_MIN = 45, 55   # % de la rampa, topes de los dos deslizadores

# --- Grabacion y capturas --------------------------------------------------

GRABAR_CRUDO = False     # valor inicial de la casilla "grabar crudo"
LIMITE_PARTE_MB = 90     # GitHub rechaza archivos de mas de 100 MB
FORMATO_SELLO = "%d-%m-%Y_%H-%M-%S"
DPI_CAPTURA = 200
NOMBRE_CAPTURA_DEF = "captura"
ESPERA_MAX = 300.0
