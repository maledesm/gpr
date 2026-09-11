"""
GPRv2 - Radargrama en tiempo real (version rapida)
==================================================

Es `vivo.py`, mismo programa y misma ventana, reescrito para que el refresco
no sea lo que limita. `vivo.py` NO se toca: queda como referencia y como red
de seguridad, y los dos graban el mismo formato de CSV.

Lo que hace, los controles, la calibracion, el fondo y la puerta de deteccion
estan documentados en `vivo.py` y en `GPRv2/CLAUDE.md`, y no cambiaron. Aca se
documenta SOLO lo que es distinto.

Uso
---
    python vivo_rapido.py


Que estaba lento y cuanto se gano
---------------------------------

Medido en esta maquina (Python 3.11, numpy 1.26, matplotlib 3.7), con la
ventana tipica de 20 s y con la de 120 s:

    ====================================  ==========  ==========  ======
    por cuadro (200 ms de presupuesto)      vivo.py    este       gano
    ====================================  ==========  ==========  ======
    dibujar, ventana 20 s                   211 ms      44 ms      4,8x
    dibujar, ventana 120 s                  340 ms      44 ms      7,7x
    agrupar + dB, ventana 120 s              30 ms     0,5 ms       60x
    ------------------------------------  ----------  ----------  ------
    cada 2 s: ajuste de la triangular       105 ms       4 ms       26x
    ------------------------------------  ----------  ----------  ------
    por rampa: remuestreo                   293 us      13 us        22x
    por rampa: FFT                           27 us       5 us       5,4x
    por segundo de stream: parseo            12 ms     6,5 ms      1,9x
    ====================================  ==========  ==========  ======

En `vivo.py` un cuadro cuesta 211 ms con 200 ms de presupuesto: la ventana
esta saturada, el timer se atrasa, y la pantalla va a tirones. Aca sobra mas
de un 75 % del tiempo.

Las cinco cosas que lo lograron
-------------------------------

1. SE DIBUJA SOLO LO QUE CAMBIA (blitting). Era lo mas caro por lejos.
   `draw()` repinta TODO: los 8 cuadros de texto, los 6 botones, la colorbar,
   los ticks, los titulos. Eso solo son ~140 ms y nada de eso cambia entre
   cuadros. Ahora el fondo se fotografia una vez y en cada refresco se
   restaura y se pintan encima nada mas los cinco artistas que se mueven.
   El fondo se vuelve a sacar solo cuando cambia algo del fondo: limites de
   eje, escala de color, titulo, o cualquier redibujado que dispare un
   widget. Ver `_pintar()`.

   Para que eso funcione los limites del eje de tiempo no pueden bailar en
   cada cuadro: se usa el span NOMINAL (filas * rampas/fila * T/2) en vez del
   medido de las marcas de tiempo. Difieren en menos de una muestra.

2. NO SE DIBUJAN FILAS NI COLUMNAS QUE NO SE VEN.
   - Columnas: el eje llega hasta el Nyquist (decenas de metros) pero se
     muestran 5. Se recorta al ultimo bin visible ANTES del log10 y antes de
     mandarlo a la pantalla.
   - Filas: con la ventana en 120 s salen hasta 3000 filas para ~400 pixeles
     de alto. Arriba de MAX_FILAS se agrupa de a mas rampas (`n_ef`), que es
     exactamente lo que hace el control de rampas/fila. El panel informa el
     agrupado efectivo, asi que no hay magia escondida.

3. EL REMUESTREO Y LA FFT VAN EN LOTE (ver `proceso_rapido.py`). El spline
   cubico sobre una grilla theta fija es un operador lineal: se precalcula
   como matriz una vez y cada rampa pasa a ser un producto que va a BLAS. Es
   el MISMO spline cubico, no otro interpolador — CLAUDE.md avisa de no
   cambiarlo buscando SNR y no se cambio; `verificar_rapido.py` lo comprueba
   contra `remuestrear()` (error relativo 6e-16).

4. EL AJUSTE DE LA TRIANGULAR NO CONGELA MAS LA VENTANA.
   `ajustar_triangular()` cuesta 105 ms y corre cada 2 s en el hilo del
   grafico: un tironazo de medio refresco cada dos segundos, bien visible.
   `ajustar_triangular_rapido()` hace la misma cuenta en ~4 ms.

5. LAS CUENTAS NO SE REPITEN. `_poner_estado()` llamaba a `pico_crudo()`,
   `hay_blanco()` y `energia_actual_db()` varias veces cada uno, y cada uno
   promediaba de nuevo cientos de perfiles: nueve veces el mismo promedio por
   cuadro. Ahora hay un cache que se vacia al principio de cada refresco.


Lo que ademas se agrego
-----------------------

PICO SUB-BIN. La distancia del pico sale de una parabola sobre las tres
magnitudes en dB alrededor del maximo, en vez del centro del bin. El ancho de
bin real no cambia (vale c/(2*BW), ver CLAUDE.md), pero el CENTRO de un pico
ya resuelto queda con precision de centesimas de bin en vez de saltar de bin
en bin. Se nota justo donde importa: tomando puntos de calibracion.

FONDO AUTOMATICO (MTI). Boton `fondo auto`, o la tecla `f`. En vez de medir el
fondo una vez con la sala vacia, lo estima todo el tiempo con un promedio
exponencial de constante TAU_MTI (30 s) y lo va restando. Es el "background
removal" clasico de GPR y no hace falta tener la sala vacia.

  Lo que hace, dicho con precision: al prenderlo, TODO lo que hay en ese
  momento pasa a ser fondo y se va de la pantalla. Lo que aparece o se mueve
  DESPUES salta, y despues se desvanece de vuelta en ~TAU_MTI segundos si se
  queda quieto. O sea que sirve para "mover la placa y mirar", no para medir
  un blanco que ya estaba y no se mueve. Para eso sigue estando `medir fondo`,
  que congela el fondo y no lo toca mas.

  Con el fondo automatico la puerta de deteccion NO puede comparar la energia
  cruda contra la del fondo como hace con el fondo congelado: el fondo
  persigue a la senal, asi que esas dos energias son la misma por
  construccion y el cociente daria 0 dB con blanco y sin blanco. Con MTI
  prendido la puerta mide el RESIDUO (lo que queda despues de restar) contra
  el fondo, que es exactamente "cuanto de lo que veo es nuevo". Ese cociente
  es mucho mas chico, asi que el margen arranca en MARGEN_MTI (-20 dB) en vez
  de +6, y se afina mirando el numero del panel.

MS/CUADRO EN EL PANEL. El cuadro de informacion muestra cuanto tarda un
refresco. Si alguna vez se acerca a REFRESCO_MS, hay que bajar la ventana o
subir rampas/fila, y ahora se ve en vez de adivinarse.

CAPTURAS PARA EL INFORME. Cuadro de texto `captura` + boton `guardar captura
PNG`, o la tecla `s`. Se tipea un nombre ("placa_1m", "sala_vacia"), se
aprieta, y queda en datos/capturas/<nombre>.png a DPI_CAPTURA (200 dpi =
2800x1600 px). No hace falta Enter: el nombre se lee del cuadro en el momento
de guardar. No sobrescribe nunca: si el nombre ya existe sale <nombre>_2.png.

  Se recorta la columna de controles, porque en un informe no pinta nada, y
  todo lo que importa de la configuracion queda igual adentro de la imagen:
  la escala de color en la colorbar, el alcance en el eje x, y el Tprf, la
  BW, el alpha0, la resolucion, la saturacion de la triangular, el estado
  del fondo y la calibracion en el cuadro de informacion de la derecha. La
  figura se explica sola seis meses despues. Con RECORTE_CAPTURA = None se
  guarda la ventana entera.

Teclas
------
    e   cambia el eje m <-> Hz
    a   autoescala el color a lo que hay en pantalla
    f   prende/apaga el fondo automatico (MTI)
    s   guarda una captura PNG
    q   salir

`f` y `s` son de matplotlib por defecto (pantalla completa y guardar). Se las
saca en armar_figura(); los atajos con ctrl siguen andando.
"""

import json
import os
import re
import threading
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox
from matplotlib.transforms import Bbox

import serial
from serial.tools import list_ports

from correccion_no_linealidad import (
    T_SWEEP, C, V_MIN, V_MAX, cargar_curva_vco, eje_theta,
    buscar_periodo, fs_theta,
)
from proceso_rapido import (
    Remuestreador, espectros, largo_fft, ajustar_triangular_rapido,
    pico_parabolico,
)

PUERTO = "auto"      # "auto" o algo como "COM5"
BAUD = 115200
VID_ESPRESSIF = 0x303A

FS = 6000.0          # sps de la salida diezmada de adquisicion.ino (SPS_SALIDA)

CALIBRACION_S    = 4.0    # cuanto se escucha antes de dibujar, para el 1er ajuste
VENTANA_AJUSTE_S = 5.0    # cuanta triangular entra en cada reajuste
REAJUSTE_S       = 2.0    # cada cuanto se rehace el ajuste de periodo y fase
REFRESCO_MS      = 200    # cada cuanto se redibuja

N_DEFECTO = 8        # rampas promediadas por fila al arrancar
N_MAX     = 64
# Relleno de ceros de la FFT de cada rampa. NO agrega resolucion: el ancho de
# bin real vale c/(2*BW) = 14,4 cm y eso solo lo cambia mas ancho de banda
# (ver GPRv2/CLAUDE.md). Lo que hace es interpolar, para que la rampa de 120
# muestras no salga en bandas gruesas.
#
# Con el pico sub-bin de `pico_parabolico()` la PRECISION del pico ya no
# depende de esto, asi que bajarlo a 4 no empeora ninguna medicion: solo
# suaviza menos el dibujo, a cambio de la mitad de memoria por perfil y la
# mitad de FFT. Queda en 8 para que la pantalla se vea igual que en vivo.py.
RELLENO   = 8
VENTANA_DEF = 20.0   # s de historia que se muestran
VENTANA_MAX = 120.0
ALCANCE_DEF = 5.0    # m, tope del eje de distancia
IGNORAR_DEF = 0.3    # m, desde donde se busca el pico para calibrar
PISO_DEF  = -40.0    # dB respecto del pico en pantalla
TECHO_DEF = 0.0
PISO_FONDO  = -20.0
TECHO_FONDO = 20.0
PROMEDIO_CAL_S = 2.0  # cuanto se promedia para tomar un punto de calibracion
FONDO_S = 3.0         # cuanto se promedia al medir el fondo
MARGEN_DEF = 6.0
TRAZA_MIN_DB = 3.0
UMBRAL_SAT = 0.05
ADC_FS_V = 2.5
DIVISOR = 2.0
VF_COAX = 0.66

# --- parametros nuevos, todos de rendimiento o de la funcion agregada ---

# Tope de filas que se le mandan a la pantalla. El radargrama tiene ~400
# pixeles de alto: arriba de esto las filas de mas no se ven, solo cuestan.
# Cuando se pasa, se agrupa de a mas rampas (que es lo mismo que subir
# rampas/fila) y el panel lo informa como "agrupado efectivo".
MAX_FILAS = 900
# El cuadro de informacion son 31 lineas de texto monoespaciado y la
# triangular son ~940 puntos: juntos cuestan mas que el radargrama y no hace
# falta que se refresquen 5 veces por segundo.
CADA_INFO = 3        # refrescos entre dos actualizaciones del cuadro de info
CADA_TRI  = 3        # idem para la triangular plegada
# Constante de tiempo del fondo automatico (MTI). 30 s: largo frente al
# tiempo que tarda uno en mover un blanco, corto frente a una sesion.
TAU_MTI = 30.0
# Margen de la puerta cuando el fondo es automatico. Ahi la puerta compara el
# RESIDUO contra el fondo (ver matriz()), y el residuo de un blanco es siempre
# mucho mas chico que la energia total de la escena (que incluye el
# acoplamiento directo, que es lo mas fuerte de todo): con +6 dB no pasaria
# nunca. -20 dB es un punto de partida razonable; se afina mirando el panel.
MARGEN_MTI = -20.0
# El blitting se apaga solo si el backend no lo banca (y se avisa por consola).
USAR_BLIT = True
# Tope de rampas procesadas por cuadro, por si hubo un parate largo: evita
# que un solo refresco intente masticar minutos de stream de golpe.
RAMPAS_POR_CUADRO = 512

# --- capturas de pantalla para el informe ---

# 200 dpi sobre una figura de 14x8 pulgadas dan 2800x1600 px, que entra
# holgado en una pagina de tesis sin verse pixelado. 300 si hace falta
# imprimir grande; arriba de eso el archivo crece y no se gana nada.
DPI_CAPTURA = 200
NOMBRE_CAPTURA_DEF = "captura"
# Que parte de la figura entra en la captura:
#   "paneles"  los cinco paneles con sus rotulos, sin la columna de controles.
#              El rectangulo se mide sobre la figura ya dibujada, asi que si
#              algun dia se mueve un axes no hay que venir a tocar un numero
#              a mano — y no corta ningun rotulo, que es lo que pasaba con el
#              recorte fijo (se comia el "Hace [s]").
#   None       la ventana entera, controles incluidos.
#   (x0,y0,x1,y1)  fracciones de la figura, a mano.
#
# Se saca la columna de controles porque en un informe no pinta nada, y todo
# lo que importa de la configuracion queda igual adentro: la escala de color
# en la colorbar, el alcance en el eje x, y el resto en el cuadro de la
# derecha.
RECORTE_CAPTURA = "paneles"
# Margen en pulgadas alrededor del recorte automatico, para que ningun rotulo
# quede pegado al borde.
MARGEN_CAPTURA = 0.10

AQUI    = os.path.dirname(os.path.abspath(__file__))
DATOS   = os.path.join(AQUI, "..", "datos")
SALIDA  = os.path.join(DATOS, "captura.csv")
SAL_TRI = os.path.join(DATOS, "triangular.csv")
CAL_JSON = os.path.join(DATOS, "calibracion_distancia.json")
CAPTURAS = os.path.join(DATOS, "capturas")
VCO_CSV = os.path.join(AQUI, "..", "..", "VCO", "Caracteristica VCO.csv")


# --- Lectura del puerto ----------------------------------------------------

class Lector(threading.Thread):
    """
    Igual que el de `vivo.py`: vacia el puerto, clasifica, escribe a disco y
    encola para el grafico. Cambia solo COMO parsea, porque a 6000 lineas por
    segundo el hilo del puerto le pelea el GIL al del dibujo.

      - Se decodifica el BLOQUE entero de una vez en vez de linea por linea.
        Un decode de 8 kB es una llamada a C; 6000 decodes de 12 bytes son
        6000 vueltas del interprete.
      - No hay regex en el camino caliente. La linea de muestra se reconoce
        por el primer caracter y se valida con el `int()` que hace falta
        igual: si no es un numero, el `except` la cuenta como cortada. Era
        exactamente lo que hacia la regex, pero sin el motor de regex.

    Medido sobre un segundo de stream sintetico: 12,4 ms -> 6,5 ms.
    """

    def __init__(self, ser, f_cap, f_tri):
        super().__init__(daemon=True)
        self.ser = ser
        self.f_cap = f_cap
        self.f_tri = f_tri
        self.lock = threading.Lock()
        self._beat = []
        self._tri = []
        self.n_filas = 0
        self.descartadas = 0
        self.parar = False
        # Retardo de grupo del filtro de diezmado de la placa, en muestras de
        # salida (ver vivo.py y CLAUDE.md). Firmware viejo -> 0.
        self.retardo = 0

    def run(self):
        resto = ""
        while not self.parar:
            try:
                datos = self.ser.read(max(1, self.ser.in_waiting))
            except Exception:
                break
            if not datos:
                continue
            resto = self.procesar(resto + datos.decode("ascii", "ignore"))

    def procesar(self, texto):
        """Consume las lineas completas de `texto` y devuelve el resto.

        Aparte de run() para poder probarla sin puerto ni hilos. Recibe str y
        no bytes justamente porque el decode se hace una sola vez por bloque.
        """
        trozos = texto.split("\n")
        resto = trozos.pop()            # la ultima puede estar cortada
        beat, tri, txt_cap, txt_tri = [], [], [], []
        n = self.n_filas
        malas = 0
        for linea in trozos:
            c = linea[:1]
            if c == "" or c == "\r":
                continue
            if c == "#":
                if linea.startswith("#v,"):
                    # El indice que manda la placa se ignora a proposito y se
                    # usa el contador propio de filas: si se perdio una linea
                    # de muestra, el indice de la placa ya no apunta a la fila
                    # correcta del CSV, y el contador propio si.
                    coma = linea.find(",", 3)
                    if coma < 0:
                        malas += 1
                        continue
                    try:
                        adc = int(linea[3:coma])
                    except ValueError:
                        malas += 1
                        continue
                    fila = n - 1 + self.retardo
                    if fila < 0:
                        continue
                    tri.append((fila, adc))
                    txt_tri.append(f"{adc},{fila}")
                elif linea.startswith("# retardo"):
                    try:
                        self.retardo = int(linea.split("=")[1].split()[0])
                    except (IndexError, ValueError):
                        pass
                continue
            coma = linea.find(",")
            if coma <= 0:
                malas += 1
                continue
            try:
                beat.append(int(linea[:coma]))
            except ValueError:
                malas += 1
                continue
            txt_cap.append(linea)
            n += 1
        self.n_filas = n
        self.descartadas += malas
        if txt_cap:
            self.f_cap.write("\n".join(txt_cap) + "\n")
        if txt_tri:
            self.f_tri.write("\n".join(txt_tri) + "\n")
        with self.lock:
            self._beat.extend(beat)
            self._tri.extend(tri)
        return resto

    def tomar(self):
        """Devuelve (muestras, lecturas de triangular) desde la ultima vez."""
        with self.lock:
            beat, tri = self._beat, self._tri
            self._beat, self._tri = [], []
        return beat, tri


def abrir_puerto():
    puerto = PUERTO
    if puerto == "auto":
        cand = [p for p in list_ports.comports() if p.vid == VID_ESPRESSIF]
        if len(cand) != 1:
            for p in cand:
                print("   ", p.device, "-", p.description)
            raise SystemExit(
                "No encontre exactamente un ESP32 (esta enchufado? el Monitor "
                "Serie del IDE tiene que estar cerrado). Si no, pone el puerto "
                "a mano en PUERTO.")
        puerto = cand[0].device
        print(f"Puerto detectado: {puerto}")

    # Sin tocar DTR/RTS: pyserial los afirma a los dos al abrir y en el USB
    # nativo del C3 esa combinacion es la de reset (ver GPRv2/CLAUDE.md).
    ser = serial.Serial()
    ser.port = puerto
    ser.baudrate = BAUD
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    ser.open()
    time.sleep(0.5)
    ser.reset_input_buffer()
    ser.write(b"run\n")
    return ser


# --- Calibracion del eje de distancia --------------------------------------

class Calibracion:
    """
    Mapa afin d_real = a*d_crudo + b. Identica a la de `vivo.py`, y comparten
    el mismo archivo `datos/calibracion_distancia.json`: una calibracion
    tomada con uno sirve para el otro.
    """

    def __init__(self):
        self.a, self.b = 1.0, 0.0
        self.puntos = []          # [(d_crudo, d_real), ...]

    @property
    def activa(self):
        return self.a != 1.0 or self.b != 0.0

    def aplicar(self, d):
        return self.a * np.asarray(d) + self.b

    def crudo_de(self, d_real):
        """El inverso: que distancia CRUDA corresponde a una calibrada."""
        return (d_real - self.b) / self.a if self.a else d_real

    def ajustar(self):
        """Devuelve un texto con el resultado, o el motivo de no poder.

        Con UN punto ajusta solo el offset, dejando la pendiente en 1: el
        retardo de los cables es fisicamente un offset puro (ver CLAUDE.md).
        Con dos o mas, minimos cuadrados, que ademas verifica que la pendiente
        de verdad da ~1.
        """
        if not self.puntos:
            return "no hay ningun punto tomado"
        crudo = np.array([p[0] for p in self.puntos])
        real = np.array([p[1] for p in self.puntos])
        if len(self.puntos) == 1 or np.ptp(crudo) < 1e-6:
            self.a = 1.0
            self.b = float(real[0] - crudo[0])
            return f"solo offset: b={self.b:+.3f} m (pendiente fija en 1)"
        self.a, self.b = np.polyfit(crudo, real, 1)
        return f"a={self.a:.4f}  b={self.b:+.3f} m"

    def borrar(self):
        self.a, self.b = 1.0, 0.0
        self.puntos = []

    def guardar(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"a": self.a, "b": self.b, "puntos": self.puntos,
                           "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}, f,
                          indent=2)
        except OSError as e:
            print(f"  [!] no pude guardar la calibracion: {e}")

    def cargar(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self.a = float(d["a"])
            self.b = float(d["b"])
            self.puntos = [tuple(p) for p in d.get("puntos", [])]
            return d.get("fecha", "?")
        except (OSError, ValueError, KeyError):
            return None


# --- El radargrama ---------------------------------------------------------

class Vivo:

    def __init__(self, lector, curva, cal=None):
        self.lec = lector
        self.curva = curva
        self.cal = cal if cal is not None else Calibracion()

        # Cola de muestras de batido todavia sin trocear en rampas. 'base' es
        # el indice absoluto de beat[0]. float64 a proposito: las muestras del
        # PCM1808 son de 24 bits sobre una continua que puede ser grande, y la
        # resta de la media tiene que hacerse con precision doble antes de
        # pasar a float32 para el remuestreo.
        self.beat = np.empty(0)
        self.base = 0
        self.n_total = 0

        self.tri_fila, self.tri_adc = [], []   # ventana para el ajuste
        self._tri_np = None        # cache de la version numpy de lo de arriba
        self.T = self.t0 = None
        self.n = 0
        self.k = 0                 # indice de la proxima rampa a procesar
        self.t_ajuste = 0.0
        self.rem = None            # Remuestreador, se arma con los ejes

        self.P = self.tp = None    # buffer de perfiles (float32) y sus tiempos
        self.n_perf = 0
        self.cap = self.necesarios = 0

        self.n_rampas = N_DEFECTO
        self.n_ef = N_DEFECTO      # agrupado efectivo (con la decimacion)
        self.ventana = VENTANA_DEF
        self.alcance = ALCANCE_DEF
        self.ignorar = IGNORAR_DEF
        self.margen = MARGEN_DEF
        self.en_metros = True
        self.piso, self.techo = PISO_DEF, TECHO_DEF
        self.dist_real = 1.0
        self.aviso = ""

        # Fondo. `fondo` es el que se usa; `mti` dice si ademas se lo va
        # reestimando solo con un promedio exponencial.
        self.fondo = None
        self.fondo_ref = 1.0
        self.fondo_energia = 0.0
        self.energia_db = None
        self.mti = False
        self.t_mti_ref = 0.0

        self._cache = {}           # se vacia al principio de cada refresco
        self._fondos = None        # fotos del fondo para el blitting
        self._estatico = None      # que valores tenia el fondo cuando se saco
        self._recapturando = False
        self._cuadro = 0
        self._ms_cuadro = 0.0
        self._en_refresco = False
        self.blit = USAR_BLIT

    # --- datos ---

    def drenar(self):
        beat, tri = self.lec.tomar()
        if beat:
            self.beat = np.concatenate([self.beat, np.asarray(beat, float)])
            self.n_total += len(beat)
        if tri:
            self.tri_fila.extend(f for f, _ in tri)
            self.tri_adc.extend(a for _, a in tri)
            self._tri_np = None
        # La ventana de ajuste se recorta por tiempo, no por cantidad: la tasa
        # de lecturas depende de fs y del tamano de bloque del firmware. Se
        # busca el corte de una y se rebana, en vez de sacar de a uno del
        # principio de la lista, que es cuadratico.
        corte = self.n_total - VENTANA_AJUSTE_S * FS
        if self.tri_fila and self.tri_fila[0] < corte:
            i = int(np.searchsorted(np.asarray(self.tri_fila), corte, "left"))
            del self.tri_fila[:i]
            del self.tri_adc[:i]
            self._tri_np = None

    def _tri_arrays(self):
        """(filas, adc) como arrays, cacheado: se usa en tres lugares."""
        if self._tri_np is None:
            self._tri_np = (np.asarray(self.tri_fila, dtype=float),
                            np.asarray(self.tri_adc, dtype=float))
        return self._tri_np

    def saturacion(self):
        """Fraccion de la triangular que llega pegada a un riel del ADC.

        Es el chequeo mas importante del banco (encontro una resistencia
        suelta del divisor, ver CLAUDE.md). Si la triangular se recorta, la
        rampa de tension no es la que asume el codigo y las distancias salen
        escaladas Y los picos ensuciados.
        """
        if "sat" not in self._cache:
            _, a = self._tri_arrays()
            self._cache["sat"] = (0.0 if not len(a) else
                                  float(((a >= 4090) | (a <= 5)).mean()))
        return self._cache["sat"]

    def ajustar(self, primera_vez):
        """Rehace el ajuste de periodo y fase de la triangular."""
        if len(self.tri_fila) < 20:
            return False
        if primera_vez:
            # El periodo se BUSCA, no se asume: engancharse en un armonico
            # del nominal ya paso una vez y devolvio un numero precioso y
            # falso (CLAUDE.md, "EL GENERADOR ESTABA EN Tprf = 80 ms").
            T_ini = buscar_periodo(self.tri_fila, self.tri_adc, FS)
            if T_ini is None:
                T_ini = 2.0 * T_SWEEP
            span = 0.10
        else:
            T_ini, span = self.T, 0.01
        T, t0 = ajustar_triangular_rapido(self.tri_fila, self.tri_adc, FS,
                                          T_ini, span)

        if primera_vez:
            self.T, self.t0 = T, t0
            self.n = int(round(T * FS / 2))
            self.k = 0
            self._armar_ejes()
            return True

        # Se conserva la posicion actual: k se recalcula para que la proxima
        # rampa caiga donde iba a caer, con el periodo y la fase nuevos.
        t_prox = self.t0 + self.k * self.T / 2
        k = int(round((t_prox - t0) / (T / 2)))
        # Histeresis en n: sin esto, un T que oscila alrededor de un valor
        # medio hace saltar n entre dos enteros y los perfiles dejan de tener
        # todos el mismo largo.
        if abs(T * FS / 2 - self.n) > 0.6:
            self.n = int(round(T * FS / 2))
            self._armar_ejes()
            print(f"  [!] la rampa cambio a {self.n} muestras, se reinicia "
                  f"el radargrama")
        self.T, self.t0, self.k = T, t0, max(k, 0)
        return True

    def _armar_ejes(self):
        n = self.n
        t = np.linspace(0, n / FS, n, endpoint=False)
        _, self.theta, self.alpha0 = eje_theta(self.curva, t)
        self.fs_th = fs_theta(self.theta, n)
        # Largo de FFT "lindo" >= n*RELLENO. El relleno interpola, no agrega
        # resolucion, asi que redondear para arriba al siguiente largo rapido
        # no cuesta nada y puede ahorrar bastante.
        self.nfft = largo_fft(n, RELLENO)
        self.ventana_fft = np.hanning(n)
        # El remuestreo cubico sobre una grilla theta FIJA es una matriz fija.
        # Se arma aca, una sola vez por largo de rampa, con la ventana de la
        # FFT ya plegada adentro. Ver proceso_rapido.Remuestreador.
        self.rem = Remuestreador(self.theta, n, self.ventana_fft)
        freqs = np.fft.rfftfreq(self.nfft, d=1.0 / self.fs_th)
        self.eje_hz = freqs
        self.eje_m_crudo = freqs * C / (2.0 * self.alpha0)
        self.paso_m = float(self.eje_m_crudo[1] - self.eje_m_crudo[0])

        # Capacidad: el doble de lo que pide la ventana mas larga. Al llenarse
        # se descarta SOLO el excedente y quedan 'necesarios' perfiles, o sea
        # una ventana maxima entera (ver CLAUDE.md).
        self.necesarios = int(VENTANA_MAX * 2 / self.T) + 10
        self.cap = 2 * self.necesarios
        self.P = self.tp = None
        self.n_perf = 0
        self.fondo = None
        self.borrar_fondo()
        self._cache.clear()

    @property
    def eje_m(self):
        """Eje de distancia ya calibrado."""
        return self.cal.aplicar(self.eje_m_crudo)

    # --- indices de zona, en vez de mascaras booleanas ---
    #
    # `eje_m_crudo` es monotono creciente, asi que "los bins por encima de X"
    # es siempre un tramo contiguo: alcanza con su indice de arranque. Con eso
    # las cuentas se hacen sobre REBANADAS (vistas, sin copiar) en vez de
    # indexar con booleanos, que copia el array entero cada vez.

    def _i_zona(self):
        """Primer bin por encima de 'ignorar'.

        Debajo vive el acoplamiento directo TX->RX, que es lo mas fuerte de la
        pantalla y se lleva puesto cualquier argmax. El umbral se tipea en el
        eje calibrado, asi que se convierte a crudo antes de comparar.
        """
        if "i0" not in self._cache:
            x = self.cal.crudo_de(self.ignorar)
            i0 = int(np.searchsorted(self.eje_m_crudo, x, "left"))
            self._cache["i0"] = min(i0, len(self.eje_m_crudo) - 1)
        return self._cache["i0"]

    def _i_alcance(self):
        """Un bin despues del ultimo que entra en el eje visible."""
        if "i1" not in self._cache:
            x = self.cal.crudo_de(self.alcance)
            i1 = int(np.searchsorted(self.eje_m_crudo, x, "right")) + 2
            i1 = int(np.clip(i1, self._i_zona() + 3, len(self.eje_m_crudo)))
            self._cache["i1"] = i1
        return self._cache["i1"]

    # --- perfiles ---

    def _guardar_perfiles(self, E, tiempos):
        """Mete un LOTE de perfiles en el buffer circular, de una."""
        m = len(E)
        if not m:
            return
        if self.P is None:
            # float32: son magnitudes para dibujar, no hace falta doble
            # precision, y a ~500 numeros por perfil la mitad de memoria se
            # nota cuando la ventana pide miles.
            self.P = np.empty((self.cap, E.shape[1]), dtype=np.float32)
            self.tp = np.empty(self.cap)
        if self.n_perf + m > self.cap:
            quedan = max(self.necesarios - m, 0)
            if quedan:
                self.P[:quedan] = self.P[self.n_perf - quedan:self.n_perf]
                self.tp[:quedan] = self.tp[self.n_perf - quedan:self.n_perf]
            self.n_perf = quedan
        if m > self.cap:                     # lote gigante: entra solo la cola
            E, tiempos, m = E[-self.cap:], tiempos[-self.cap:], self.cap
            self.n_perf = 0
        self.P[self.n_perf:self.n_perf + m] = E
        self.tp[self.n_perf:self.n_perf + m] = tiempos
        self.n_perf += m

    def procesar(self):
        """Trocea todas las rampas completas que hayan llegado, EN LOTE.

        La version de `vivo.py` hace un `for` por rampa y adentro arma un
        spline cubico nuevo y una FFT: 320 us por rampa. Aca las rampas se
        juntan en una matriz (rampas x muestras) de una sola indexada, el
        remuestreo es un producto de matrices y la FFT es una sola llamada
        para todo el lote: 18 us por rampa.
        """
        if self.T is None or self.rem is None:
            return 0
        paso = self.T / 2
        # Cota de cuantas rampas enteras entran, resuelta de una en vez de
        # probando de a una: ini(k) = round((t0 + k*paso)*FS), y hace falta
        # ini + n <= n_total.
        k_tope = int(np.floor(((self.n_total - self.n) / FS - self.t0) / paso)) + 2
        if k_tope <= self.k:
            return 0
        ks = np.arange(self.k, min(k_tope, self.k + RAMPAS_POR_CUADRO))
        ini = np.rint((self.t0 + ks * paso) * FS).astype(np.int64)
        entran = ini + self.n <= self.n_total
        ks, ini = ks[entran], ini[entran]
        if not len(ks):
            return 0
        self.k = int(ks[-1]) + 1

        # Las que quedaron atras por un reajuste ya no estan en el buffer.
        vale = ini >= self.base
        ks, ini = ks[vale], ini[vale]
        m = len(ini)
        if m:
            # Una sola indexada arma la matriz (rampas x muestras).
            filas = (ini - self.base)[:, None] + np.arange(self.n)[None, :]
            S = self.beat[filas]
            impar = (ks % 2).astype(bool)     # 0 = subida, 1 = bajada
            if impar.any():
                # La bajada, leida al reves, es una subida.
                S[impar] = S[impar, ::-1]
            # La media se saca en float64 y recien despues se pasa a float32:
            # la continua puede ser grande frente al batido, y restarla en
            # simple precision se comeria bits de la senal.
            S -= S.mean(axis=1, keepdims=True)
            SW = self.rem.aplicar_ventaneado(S)       # remuestreo + ventana
            E = espectros(SW, self.nfft)              # |rFFT| de todo el lote
            self._guardar_perfiles(E, (ini + self.n) / FS)
            if self.mti:
                self._actualizar_mti(E, m * paso)

        # Tirar lo ya consumido, dejando un margen por si un reajuste corre
        # los limites un poco para atras.
        arranque = int(round((self.t0 + self.k * paso) * FS))
        corte = max(0, arranque - 4 * self.n - self.base)
        if corte:
            self.beat = self.beat[corte:]
            self.base += corte
        return m

    def matriz(self):
        """Agrupa los perfiles de a n_ef y devuelve (db, span, x0, x1).

        `db` tiene forma (filas, bins VISIBLES): la fila 0 es la mas VIEJA y
        la ultima la mas nueva. `span` son los segundos que abarca y (x0, x1)
        los bordes del eje x que le corresponden.

        Tres diferencias con la de `vivo.py`, las tres de rendimiento:

        1. Se recorta a las columnas que se ven (hasta `alcance`) ANTES del
           log10. El eje llega al Nyquist, que son decenas de metros, y se
           muestran 5: el 85 % de las columnas no se dibujaba nunca.
           Ojo: eso hace que el 0 dB sin fondo medido sea el maximo de lo que
           se VE, que es lo que dice la documentacion que tiene que ser.
        2. Si salen mas filas que MAX_FILAS se agrupa de a mas rampas. Son
           filas que no entran en los pixeles del radargrama.
        3. Los dos agrupados (el del usuario y el de la pantalla) se hacen en
           un solo reshape, y la energia de la puerta sale de un einsum sobre
           una rebanada contigua en vez de una indexada booleana.
        """
        if self.T is None or not self.n_perf:
            return None, 0.0, 0.0, 1.0
        paso = self.T / 2
        caben = min(self.n_perf, int(round(self.ventana / paso)))
        N = self.n_rampas
        filas = caben // N
        if filas < 1:
            return None, 0.0, 0.0, 1.0
        # Decimacion de pantalla: subir el agrupado hasta que las filas entren
        # en MAX_FILAS. Es lo mismo que subir rampas/fila, y se informa.
        d = 1 if filas <= MAX_FILAS else int(np.ceil(filas / MAX_FILAS))
        self.n_ef = N * d
        filas = caben // self.n_ef
        if filas < 1:
            self.n_ef = N
            filas, d = caben // N, 1
        usadas = filas * self.n_ef
        P = self.P[self.n_perf - usadas:self.n_perf]        # vista, no copia
        M = P.reshape(filas, self.n_ef, P.shape[1]).mean(axis=1)

        i0, i1 = self._i_zona(), self._i_alcance()
        if self.fondo is None:
            self.energia_db = None
            V = M[:, :i1]
            db = 20 * np.log10(V / (V.max() + 1e-12) + 1e-12)
        else:
            # Con el fondo CONGELADO la puerta se decide con la energia CRUDA
            # contra la del fondo: "la energia medida supera a la del fondo
            # por un margen" es literalmente eso, y restar primero daria casi
            # cero siempre.
            # Con el fondo AUTOMATICO no sirve, y es importante: el fondo
            # persigue a la senal, asi que la energia cruda ES la del fondo
            # por construccion y el cociente daria 0 dB con blanco y sin
            # blanco. Ahi lo que hay que medir es el RESIDUO, que es
            # exactamente lo que el MTI deja: lo que cambio.
            Z = M[:, i0:]
            if self.mti:
                Z = np.maximum(Z - self.fondo[i0:], 0.0)
            e = np.einsum("ij,ij->i", Z, Z)
            self.energia_db = 10 * np.log10(e / (self.fondo_energia + 1e-30)
                                            + 1e-30)
            # Resta en amplitud con piso en cero: lo que se guarda son
            # magnitudes de FFT, no complejos, asi que no hay cancelacion
            # coherente posible. Alcanza para sacar los ecos fijos.
            V = np.maximum(M[:, :i1] - self.fondo[:i1], 0.0)
            # Referencia FIJA, la del fondo: normalizar al maximo hace que sin
            # blanco el propio fondo suba a 0 dB y aparezca un blanco donde no
            # hay nada.
            db = 20 * np.log10(V / self.fondo_ref + 1e-12)

        # Span NOMINAL y no medido de las marcas de tiempo. Difieren en menos
        # de una muestra, pero el medido se mueve un poquito en cada cuadro y
        # eso obligaria a recapturar el fondo del blitting siempre.
        span = filas * self.n_ef * paso
        # Los bordes de la imagen son bordes de bin, no centros: medio bin a
        # cada lado. Son 0,9 cm con el relleno x8, pero es gratis y es lo
        # correcto.
        x0 = self._eje_x()[0] - self.paso_eje() / 2
        x1 = self._eje_x()[i1 - 1] + self.paso_eje() / 2
        return db, span, x0, x1

    def paso_eje(self):
        eje = self._eje_x()
        return float(eje[1] - eje[0])

    def perfil_actual(self, crudo=False):
        """Promedio de los ultimos PROMEDIO_CAL_S, con el fondo ya restado
        salvo que se pida crudo (que es lo que hace falta para medirlo).

        Cacheado por cuadro: `_poner_estado()` lo pedia nueve veces.
        """
        clave = "perf_crudo" if crudo else "perf"
        if clave in self._cache:
            return self._cache[clave]
        if self.T is None or not self.n_perf:
            self._cache[clave] = None
            return None
        if "perf_crudo" not in self._cache:
            cuantos = max(1, min(self.n_perf,
                                 int(round(PROMEDIO_CAL_S / (self.T / 2)))))
            self._cache["perf_crudo"] = \
                self.P[self.n_perf - cuantos:self.n_perf].mean(axis=0)
        p = self._cache["perf_crudo"]
        if crudo:
            return p
        self._cache["perf"] = p if self.fondo is None else \
            np.maximum(p - self.fondo, 0.0)
        return self._cache["perf"]

    def energia_actual_db(self):
        """Cuanto supera la energia de ahora a la del fondo, en dB."""
        if "e_db" in self._cache:
            return self._cache["e_db"]
        v = None
        if self.fondo is not None:
            p = self.perfil_actual(crudo=True)
            if p is not None:
                i0 = self._i_zona()
                z = p[i0:]
                # Con fondo automatico, el residuo (ver matriz()): la energia
                # cruda seria la del fondo por construccion.
                if self.mti:
                    z = np.maximum(z - self.fondo[i0:], 0.0)
                e = float(np.dot(z, z))
                v = 10 * np.log10(e / (self.fondo_energia + 1e-30) + 1e-30)
        self._cache["e_db"] = v
        return v

    def hay_blanco(self):
        """Si la energia actual supera a la del fondo por 'margen' dB.

        Sin fondo medido devuelve True: no hay contra que comparar.
        """
        if self.fondo is None:
            return True
        e = self.energia_actual_db()
        return e is not None and e >= self.margen

    def pico_crudo(self):
        """Distancia CRUDA del pico, o None si no hay blanco que valga.

        Devuelve None cuando la energia no supera al fondo por el margen: sin
        eso, con la sala vacia el argmax devolvia igual una distancia, que es
        justo el numero inventado que hay que evitar.

        La posicion sale con interpolacion parabolica sub-bin: el centro de un
        pico ya resuelto queda con precision de centesimas de bin en vez de
        saltar de bin en bin, que es lo que hace repetible un punto de
        calibracion. El ancho de bin real no cambia, sigue siendo c/(2*BW).
        """
        if "pico" in self._cache:
            return self._cache["pico"]
        d = None
        if self.hay_blanco():
            perfil = self.perfil_actual()
            if perfil is not None:
                i0 = self._i_zona()
                if i0 < len(perfil) - 1:
                    i = i0 + int(np.argmax(perfil[i0:]))
                    d = float(self.eje_m_crudo[i]
                              + pico_parabolico(perfil, i) * self.paso_m)
        self._cache["pico"] = d
        return d

    # --- fondo ---

    def _fijar_fondo(self, perfil):
        """Deja `perfil` como fondo y rehace la referencia y la energia."""
        self.fondo = perfil
        i0 = self._i_zona()
        z = self.fondo[i0:]
        if not len(z):
            return
        self.fondo_energia = float(np.dot(z, z))
        # La referencia de dB es el pico del fondo en la zona util: 0 dB pasa
        # a querer decir "tan fuerte como lo mas fuerte que hay sin blanco".
        self.fondo_ref = float(max(z.max(), 1e-12))

    def medir_fondo(self):
        """Guarda el perfil de la sala vacia como fondo. Devuelve un aviso."""
        if self.T is None or not self.n_perf:
            return "todavia no hay perfil"
        self.mti = False
        cuantos = max(1, min(self.n_perf,
                             int(round(FONDO_S / (self.T / 2)))))
        self._fijar_fondo(self.P[self.n_perf - cuantos:self.n_perf]
                          .mean(axis=0).copy())
        # Medir el fondo cambia el SIGNIFICADO del 0 dB: deja de ser el maximo
        # de la pantalla y pasa a ser el pico del fondo, asi que un blanco
        # puede quedar muy por encima y con el techo en 0 saldria recortado.
        self.piso, self.techo = PISO_FONDO, TECHO_FONDO
        return f"fondo medido sobre {cuantos} rampas"

    def borrar_fondo(self):
        self.fondo = None
        self.fondo_energia = 0.0
        self.fondo_ref = 1.0
        self.energia_db = None
        self.mti = False

    def _actualizar_mti(self, E, dt):
        """Fondo automatico: promedio exponencial de los perfiles que llegan.

        Es el "background removal" clasico de GPR, o sea un pasaaltos en
        tiempo lento. Lo que no se mueve termina adentro del promedio y se
        resta solo, sin sala vacia y sin apretar nada. La contra es inherente
        al metodo y no un defecto: lo que ya estaba al prenderlo se va de una,
        y lo que aparece despues se desvanece en ~TAU_MTI segundos si se queda
        quieto. Para blancos quietos esta `medir fondo`, que lo congela.

        El lote entero se aplica de una: aplicar el promedio m veces seguidas
        con constante alpha equivale a aplicarlo una vez con
        1 - (1-alpha)^m = 1 - exp(-m*dt_rampa/TAU).
        """
        nuevo = E.mean(axis=0)
        if self.fondo is None:
            self._fijar_fondo(nuevo.copy())
            self.piso, self.techo = PISO_FONDO, TECHO_FONDO
            return
        a = 1.0 - float(np.exp(-dt / TAU_MTI))
        self.fondo += a * (nuevo - self.fondo)
        # La referencia de dB y la energia se rehacen a lo sumo dos veces por
        # segundo: si se movieran en cada lote, la escala de color querria
        # decir algo distinto en cada cuadro.
        ahora = time.monotonic()
        if ahora - self.t_mti_ref > 0.5:
            self.t_mti_ref = ahora
            self._fijar_fondo(self.fondo)

    # --- grafico ---

    def armar_figura(self):
        # matplotlib se reserva teclas sueltas para sus propios atajos, y dos
        # chocan con las nuestras: 'f' es pantalla completa y 's' abre su
        # dialogo de guardar. Sin sacarlas, apretar 'f' prendia el fondo auto
        # Y ponia la ventana en pantalla completa al mismo tiempo. Se les saca
        # la tecla suelta y se les deja el atajo con ctrl, que sigue andando.
        for clave, tecla in (("keymap.fullscreen", "f"), ("keymap.save", "s")):
            plt.rcParams[clave] = [k for k in plt.rcParams[clave] if k != tecla]

        self.fig = plt.figure(figsize=(14, 8))
        try:
            self.fig.canvas.manager.set_window_title(
                "GPRv2 - Radargrama en tiempo real (rapido)")
        except AttributeError:          # backend sin ventana (Agg, en pruebas)
            pass
        self.ax = self.fig.add_axes([0.265, 0.42, 0.455, 0.50])   # radargrama
        self.axf = self.fig.add_axes([0.265, 0.08, 0.455, 0.26],  # FFT
                                     sharex=self.ax)
        self.axc = self.fig.add_axes([0.732, 0.42, 0.011, 0.50])  # colorbar
        # El cuadro de info baja hasta 0.33 y no hasta 0.42 como en vivo.py:
        # entre el y la triangular habia 0.14 de figura sin usar, y el texto
        # ya no entraba. Son 39 lineas cuando hay fondo medido (vivo.py tenia
        # 31 y ya avisaba en un comentario que a 8 pt la ultima se salia),
        # porque se agregaron ms/cuadro, agrupado efectivo y el modo del
        # fondo. Con la altura nueva entran a 7 pt, que se lee.
        self.axi = self.fig.add_axes([0.795, 0.33, 0.195, 0.59])  # info
        self.axt = self.fig.add_axes([0.795, 0.05, 0.195, 0.19])  # triangular
        # El texto de estado va en su propio axes y no suelto en la figura:
        # para blitearlo hace falta un rectangulo fijo que restaurar.
        self.axe = self.fig.add_axes([0.020, 0.02, 0.215, 0.19])
        self.axe.set_axis_off()

        self.im = self.ax.imshow(np.zeros((2, 2)), origin="upper",
                                 aspect="auto", cmap="viridis",
                                 extent=(0, ALCANCE_DEF, 0, VENTANA_DEF),
                                 vmin=self.piso, vmax=self.techo,
                                 interpolation="nearest")
        self.ax.set_ylabel("Hace [s]")
        self.ax.tick_params(labelbottom=False)   # el eje x lo rotula la FFT
        self.fig.colorbar(self.im, cax=self.axc, label="Potencia relativa [dB]")
        self.txt = self.ax.text(0.5, 0.5, "esperando muestras...",
                                transform=self.ax.transAxes, ha="center",
                                va="center", fontsize=13, color="0.3")
        # Traza del blanco: el pico de cada fila, para seguirlo mientras se
        # mueve. Va sobre el radargrama, que es donde esta la historia.
        (self.traza,) = self.ax.plot([], [], color="red", lw=1.2, alpha=0.9,
                                     marker=".", ms=3, label="pico por fila")

        (self.linea,) = self.axf.plot([], [], lw=1.2, color="tab:blue")
        self.marca = self.axf.axvline(np.nan, color="tab:red", ls="--", lw=1.0)
        self.axf.set_ylabel("dB")
        self.axf.grid(alpha=0.3)
        self.axf.set_ylim(self.piso, self.techo)

        self.axi.set_xticks([]); self.axi.set_yticks([])
        self.axi.set_title("Captura", fontsize=9)
        self.info = self.axi.text(0.04, 0.985, "", transform=self.axi.transAxes,
                                  va="top", ha="left", fontsize=7.0,
                                  linespacing=1.15, family="monospace")

        # La triangular se dibuja PLEGADA en fase y no como serie de tiempo: a
        # ~188 lecturas/s son 7,5 puntos por periodo, que sueltos parecen
        # ruido. Plegando los ultimos VENTANA_AJUSTE_S se ven ~940 puntos
        # sobre un periodo y cualquier recorte salta a la vista.
        self.axt.set_xticks([]); self.axt.set_yticks([])
        self.axt.set_title("Triangular (plegada)", fontsize=9)
        (self.tri_pts,) = self.axt.plot([], [], ".", ms=1.5, alpha=0.4,
                                        color="tab:red")
        self.axt.axhline(4095, color="k", ls="--", lw=0.8)
        self.axt.axhline(0, color="k", ls="--", lw=0.8)
        self.axt.set_ylim(-250, 4345)

        self.estado = self.axe.text(0.0, 1.0, "", transform=self.axe.transAxes,
                                    va="top", ha="left", fontsize=8.5,
                                    family="monospace")

        self._armar_controles()
        self._poner_eje_x()
        # Los artistas que se mueven se pintan a mano en cada refresco; el
        # resto vive en la foto del fondo. Ver _pintar().
        self._moviles = ((self.ax, (self.im, self.traza)),
                         (self.axf, (self.linea, self.marca)),
                         (self.axi, (self.info,)),
                         (self.axt, (self.tri_pts,)),
                         (self.axe, (self.estado,)))
        self.fig.canvas.mpl_connect("draw_event", self._al_dibujar)

    def _armar_controles(self):
        """Columna de cuadros de texto y botones, toda a la izquierda."""
        self.cajas = {}
        campos = [
            ("n_rampas", "rampas/col", lambda: f"{self.n_rampas:d}"),
            ("ventana",  "ventana [s]", lambda: f"{self.ventana:g}"),
            ("alcance",  "alcance [m]", lambda: f"{self.alcance:g}"),
            ("piso",     "piso [dB]", lambda: f"{self.piso:g}"),
            ("techo",    "techo [dB]", lambda: f"{self.techo:g}"),
            ("ignorar",  "ignorar < [m]", lambda: f"{self.ignorar:g}"),
            ("margen",   "margen [dB]", lambda: f"{self.margen:g}"),
            ("dist_real", "dist. real [m]", lambda: f"{self.dist_real:g}"),
        ]
        y = 0.935
        for nombre, etiqueta, leer in campos:
            ax = self.fig.add_axes([0.135, y, 0.075, 0.030])
            caja = TextBox(ax, etiqueta + "  ", initial=leer())
            caja.on_submit(lambda t, k=nombre: self._escribir(k, t))
            self.cajas[nombre] = (caja, leer)
            y -= 0.040

        # El nombre de la captura va aparte de `cajas`: los otros cuadros son
        # numeros y pasan por _escribir(), este es texto libre. Se lee con
        # .text en el momento de guardar, asi que no hace falta apretar Enter:
        # alcanza con tipear y darle al boton.
        ax = self.fig.add_axes([0.118, y, 0.092, 0.030])
        self.caja_nombre = TextBox(ax, "captura  ", initial=NOMBRE_CAPTURA_DEF)
        y -= 0.040

        y -= 0.010
        self.botones = []
        for etiqueta, fn in (("guardar captura PNG", self.guardar_captura),
                             ("eje: m <-> Hz", self._cambiar_eje),
                             ("medir fondo", self._medir_fondo),
                             ("fondo auto (MTI)", self._alternar_mti),
                             ("borrar fondo", self._borrar_fondo),
                             ("tomar punto", self._tomar_punto),
                             ("calibrar", self._calibrar),
                             ("borrar cal", self._borrar_cal)):
            ax = self.fig.add_axes([0.045, y, 0.165, 0.032])
            b = Button(ax, etiqueta)
            b.on_clicked(fn)
            self.botones.append(b)          # hay que retenerlos o se mueren
            y -= 0.040
        self.fig.canvas.mpl_connect("key_press_event", self._tecla)

    def _escribir(self, campo, texto):
        """Aplica un cuadro de texto. Si no se entiende, lo deja como estaba."""
        try:
            v = float(texto.replace(",", "."))
        except ValueError:
            self.aviso = f"'{texto}' no es un numero"
            self._refrescar_cajas()
            return
        if campo == "n_rampas":
            self.n_rampas = int(np.clip(v, 1, N_MAX))
        elif campo == "ventana":
            self.ventana = float(np.clip(v, 0.5, VENTANA_MAX))
        elif campo == "alcance":
            self.alcance = max(v, 0.05)
        elif campo == "piso":
            self.piso = v
        elif campo == "techo":
            self.techo = v
        elif campo == "ignorar":
            self.ignorar = v
            # La zona util cambio, asi que la energia del fondo ya no es
            # comparable con la de ahora: hay que recalcularla sobre la zona
            # nueva, o la puerta decide con dos zonas distintas.
            self._cache.clear()
            if self.fondo is not None:
                self._fijar_fondo(self.fondo)
        elif campo == "margen":
            self.margen = v
        elif campo == "dist_real":
            self.dist_real = v
        self.aviso = ""
        self._cache.clear()
        self._refrescar_cajas()
        self._poner_eje_x()

    def _refrescar_cajas(self):
        """Deja los cuadros mostrando el valor que de verdad quedo.

        `TextBox.set_val()` dispara el callback de submit, o sea vuelve a
        entrar a `_escribir()`, que borra el aviso. En `vivo.py` eso hace que
        el mensaje de "medir fondo" y el de "fondo auto" se pierdan antes de
        llegar a la pantalla. Se guarda y se repone.
        """
        aviso = self.aviso
        for caja, leer in self.cajas.values():
            texto = leer()
            if caja.text != texto:
                caja.set_val(texto)
        self.aviso = aviso

    def _cambiar_eje(self, _=None):
        self.en_metros = not self.en_metros
        self._cache.clear()
        self._poner_eje_x()

    def _medir_fondo(self, _=None):
        self.aviso = self.medir_fondo()
        self._refrescar_cajas()      # medir_fondo() mueve piso y techo
        print("  " + self.aviso)

    def _alternar_mti(self, _=None):
        self.mti = not self.mti
        if self.mti:
            self.t_mti_ref = 0.0
            p = self.perfil_actual(crudo=True)
            if p is not None:
                self._fijar_fondo(p.copy())
                self.piso, self.techo = PISO_FONDO, TECHO_FONDO
            # La puerta pasa a medir el RESIDUO contra el fondo (ver
            # matriz()), que es un cociente mucho mas chico que el de la
            # energia cruda: con +6 dB no pasaria nunca nada. El panel muestra
            # el numero en vivo, asi que afinarlo es mirarlo y tipear.
            self.margen = MARGEN_MTI
            self.aviso = f"fondo auto ON (tau {TAU_MTI:.0f} s)"
        else:
            self.margen = MARGEN_DEF
            self.aviso = "fondo auto OFF (el fondo queda congelado)"
        self._refrescar_cajas()
        print("  " + self.aviso)

    def _borrar_fondo(self, _=None):
        self.borrar_fondo()
        self.piso, self.techo = PISO_DEF, TECHO_DEF
        self._refrescar_cajas()
        self.aviso = "fondo borrado"

    def _tomar_punto(self, _=None):
        d = self.pico_crudo()
        if d is None:
            self.aviso = "no hay blanco (o todavia no hay perfil)"
            return
        self.cal.puntos.append((d, self.dist_real))
        self.aviso = (f"punto {len(self.cal.puntos)}: crudo {d:.3f} m "
                      f"-> real {self.dist_real:.3f} m")
        print("  " + self.aviso)

    def _calibrar(self, _=None):
        msj = self.cal.ajustar()
        self.aviso = msj
        print(f"  calibracion: {msj}")
        if self.cal.activa:
            self.cal.guardar(CAL_JSON)
            # El offset es retardo electrico: cables, LNA, conectores. Un
            # metro de coaxil de VF 0,66 son 5,05 ns, que el radar lee como
            # 0,76 m de distancia aparente (ver docs/CABLES/).
            retardo_ns = -self.cal.b * 2 / C * 1e9
            cable_m = -self.cal.b * 2 * VF_COAX
            print(f"  offset {self.cal.b:+.3f} m = {retardo_ns:.1f} ns de "
                  f"retardo electrico = {cable_m:.1f} m de coaxil (VF "
                  f"{VF_COAX}) entre el camino de RX y el del LO")
            bw_nom = (self.curva(V_MAX) - self.curva(V_MIN)) / 1e6
            if len(self.cal.puntos) >= 2:
                print(f"  pendiente {self.cal.a:.4f} -> BW efectiva "
                      f"{bw_nom/self.cal.a:.0f} MHz (la nominal es "
                      f"{bw_nom:.0f} MHz)")
                if not 0.85 < self.cal.a < 1.18:
                    print("  [!] la pendiente tendria que dar ~1: el retardo "
                          "de cables es un offset puro y no escala. Si no da "
                          "1, revisa el periodo de la triangular (que el "
                          "panel coincida con el generador) antes que nada.")
        self._cache.clear()
        self._poner_eje_x()

    def _recorte_captura(self):
        """El rectangulo que entra en la captura, en pulgadas. Ver
        RECORTE_CAPTURA. Devuelve None para guardar la figura entera."""
        if RECORTE_CAPTURA is None:
            return None
        an, al = self.fig.get_size_inches()
        if RECORTE_CAPTURA != "paneles":
            x0, y0, x1, y1 = RECORTE_CAPTURA
            return Bbox([[x0 * an, y0 * al], [x1 * an, y1 * al]])
        # get_tightbbox() de cada axes incluye sus ticks, su rotulo y su
        # titulo, asi que la union de los cinco paneles no corta nada. Si el
        # backend no da renderer (no deberia pasar: todos los interactivos son
        # Agg por debajo), se guarda la figura entera antes que arriesgar un
        # recorte mal medido.
        try:
            ren = self.fig.canvas.get_renderer()
        except AttributeError:
            return None
        cajas = []
        for a in (self.ax, self.axf, self.axc, self.axi, self.axt):
            try:
                b = a.get_tightbbox(ren)
            except Exception:
                b = None
            if b is not None:
                cajas.append(b)
        if not cajas:
            return None
        bb = Bbox.union(cajas).transformed(self.fig.dpi_scale_trans.inverted())
        m = MARGEN_CAPTURA
        return Bbox([[max(bb.x0 - m, 0.0), max(bb.y0 - m, 0.0)],
                     [min(bb.x1 + m, an), min(bb.y1 + m, al)]])

    def guardar_captura(self, _=None):
        """Guarda lo que se esta viendo como PNG, con el nombre del cuadro.

        Para ir armando el informe sin tener que sacar screenshots a mano y
        despues adivinar cual era cual. Tres decisiones:

        - EL NOMBRE se lee de `caja_nombre.text` en el momento de apretar, no
          del callback de submit: asi alcanza con tipearlo, sin Enter. Se le
          sacan los caracteres que Windows no acepta en un nombre de archivo.

        - NO SOBRESCRIBE. Si `placa_1m.png` ya existe, el siguiente sale
          `placa_1m_2.png`. Guardar dos veces con el mismo nombre pasa todo el
          tiempo y perder la primera captura sin aviso seria peor que tener
          dos archivos.

        - SE RECORTA la columna de controles (ver RECORTE_CAPTURA). Lo que
          queda es el radargrama, la FFT, la colorbar, el cuadro de
          informacion y la triangular: la figura se explica sola, con el Tprf,
          la BW, el alpha0, la resolucion, el estado del fondo y la
          calibracion escritos adentro. Eso es justamente lo que uno necesita
          seis meses despues, cuando mira la captura y no se acuerda de nada.

        `savefig()` redibuja la figura entera por su cuenta, asi que el
        blitting no la afecta: el PNG sale completo aunque en pantalla solo se
        esten repintando los artistas moviles. Lo unico que pasa es que el
        redibujado invalida la foto del fondo, y el proximo refresco la
        vuelve a sacar.
        """
        nombre = (self.caja_nombre.text or "").strip()
        # Los prohibidos de Windows son \ / : * ? " < > | ; se sacan tambien
        # los puntos y espacios del final, que Windows recorta en silencio.
        nombre = re.sub(r'[\\/:*?"<>|]', "_", nombre).rstrip(" .")
        if not nombre:
            nombre = NOMBRE_CAPTURA_DEF
        try:
            os.makedirs(CAPTURAS, exist_ok=True)
        except OSError as e:
            self.aviso = f"no pude crear {CAPTURAS}: {e}"
            print("  [!] " + self.aviso)
            return
        ruta = os.path.join(CAPTURAS, nombre + ".png")
        k = 2
        while os.path.exists(ruta):
            ruta = os.path.join(CAPTURAS, f"{nombre}_{k}.png")
            k += 1

        recorte = self._recorte_captura()
        # Los controles se ESCONDEN mientras se guarda, en vez de confiar en
        # que el recorte los deje afuera. Un aviso largo del texto de estado
        # ("punto 1: crudo 1.199 m -> real 1.200 m") se desborda de su axes y
        # se metia por el borde izquierdo de la captura. Escondidos no pueden
        # aparecer, midan lo que midan. `savefig()` redibuja, asi que basta
        # con taparlos durante la llamada.
        ocultos = []
        if recorte is not None and RECORTE_CAPTURA == "paneles":
            ocultos = ([c.ax for c, _ in self.cajas.values()]
                       + [self.caja_nombre.ax]
                       + [b.ax for b in self.botones] + [self.axe])
        for a in ocultos:
            a.set_visible(False)
        try:
            self.fig.savefig(ruta, dpi=DPI_CAPTURA, bbox_inches=recorte,
                             facecolor=self.fig.get_facecolor())
        except Exception as e:
            self.aviso = f"no pude guardar: {e}"
            print("  [!] " + self.aviso)
            return
        finally:
            for a in ocultos:
                a.set_visible(True)
            # Redibujar invalido la foto del fondo del blitting; el proximo
            # refresco la vuelve a sacar sola (ver _al_dibujar).
            self._fondos = None
        self.aviso = f"guardada {os.path.basename(ruta)}"
        print(f"  captura -> {os.path.abspath(ruta)}")

    def _borrar_cal(self, _=None):
        self.cal.borrar()
        try:
            os.remove(CAL_JSON)
        except OSError:
            pass
        self.aviso = "calibracion borrada, eje crudo"
        self._cache.clear()
        self._poner_eje_x()

    def _tecla(self, ev):
        # Mientras se tipea en un cuadro, las teclas son del cuadro. El del
        # nombre de la captura cuenta: si no, escribir "fondo_sala" prendia el
        # MTI con la 'f' y guardaba una captura con la 's'.
        if any(c.capturekeystrokes for c, _ in self.cajas.values()):
            return
        if self.caja_nombre.capturekeystrokes:
            return
        if ev.key == "e":
            self._cambiar_eje()
        elif ev.key == "f":
            self._alternar_mti()
        elif ev.key == "s":
            self.guardar_captura()
        elif ev.key == "a":
            db, _, _, _ = self.matriz()
            if db is not None:
                # El piso al percentil 60 y no al minimo: el minimo lo fija un
                # solo bin y deja casi todo el rango de color sin usar.
                # Redondeado, porque el numero va a un cuadro de texto.
                self.piso = round(float(np.percentile(db, 60)), 1)
                self.techo = round(float(db.max()), 1)
                self._refrescar_cajas()

    def _eje_x(self):
        return self.eje_m if self.en_metros else self.eje_hz

    def _poner_eje_x(self):
        if self.T is None:
            self.axf.set_xlabel("Distancia [m]")
            return
        if self.en_metros:
            tope, etiqueta = self.alcance, "Distancia [m]"
        else:
            # El alcance se tipea siempre en metros: es la misma escala con
            # otra unidad, asi el numero quiere decir lo mismo en los dos modos.
            tope = float(np.interp(self.alcance, self.eje_m, self.eje_hz))
            etiqueta = "Frecuencia de batido [Hz]"
        self.axf.set_xlabel(etiqueta)
        # Siempre desde 0, no desde eje[0]: con calibracion 'b' negativo el eje
        # crudo arranca en un numero negativo, y arrancar el grafico ahi mueve
        # el cero de lugar cada vez que se recalibra. El cero es la referencia.
        self.ax.set_xlim(0.0, min(tope, float(self._eje_x()[-1])))

    # --- blitting ---

    def _al_dibujar(self, _ev):
        """Alguien repinto todo (un widget, un resize): la foto ya no sirve."""
        if not self._recapturando:
            self._fondos = None

    def _sacar_fondos(self):
        """Repinta todo sin los artistas moviles y se guarda esa foto."""
        self._recapturando = True
        try:
            moviles = [a for _, arts in self._moviles for a in arts]
            for a in moviles:
                a.set_visible(False)
            self.fig.canvas.draw()
            self._fondos = {ax: self.fig.canvas.copy_from_bbox(ax.bbox)
                            for ax, _ in self._moviles}
            for a in moviles:
                a.set_visible(True)
        finally:
            self._recapturando = False

    def _estado_estatico(self):
        """Todo lo que vive en la foto del fondo y puede cambiar.

        Si algo de esto cambio hay que volver a sacar la foto; si no, alcanza
        con restaurarla y pintar encima.
        """
        return (self.ax.get_xlim(), self.ax.get_ylim(), self.axf.get_ylim(),
                self.im.get_clim(), self.ax.get_title(),
                self.axf.get_xlabel(), self.axf.get_ylabel(),
                self.axt.get_xlim(), self.txt.get_visible())

    def _pintar(self, con_info, con_tri):
        """Un refresco de pantalla.

        `draw()` repinta la figura entera: los 8 cuadros de texto, los 6
        botones, la colorbar, todos los ticks. Eso solo son ~140 ms y nada de
        eso cambia. Aca se restaura la foto del fondo y se pintan encima los
        cinco artistas que se mueven: ~44 ms.

        El cuadro de informacion (31 lineas de monoespaciada) y la triangular
        (~940 puntos) se saltean en la mayoria de los cuadros: cuestan mas que
        el radargrama y no aportan nada a 5 Hz.
        """
        if not self.blit:
            self.fig.canvas.draw_idle()
            return
        try:
            estatico = self._estado_estatico()
            if self._fondos is None or estatico != self._estatico:
                self._sacar_fondos()
                self._estatico = estatico
                con_info = con_tri = True
            lienzo = self.fig.canvas
            for ax, artistas in self._moviles:
                if ax is self.axi and not con_info:
                    continue
                if ax is self.axt and not con_tri:
                    continue
                lienzo.restore_region(self._fondos[ax])
                for a in artistas:
                    ax.draw_artist(a)
                lienzo.blit(ax.bbox)
        except Exception as e:
            # Backend que no banca blit: se avisa una vez y se sigue con el
            # dibujado completo de siempre.
            self.blit = False
            print(f"  [!] el backend no banca blitting ({e}); "
                  f"sigo con el dibujado completo, va a ir mas lento")
            self.fig.canvas.draw_idle()

    # --- refresco ---

    def actualizar(self, _=None):
        """Un refresco. Reentrante-seguro: si el anterior todavia no termino
        (maquina cargada), este se saltea en vez de encimarse."""
        if self._en_refresco:
            return
        self._en_refresco = True
        t_ini = time.perf_counter()
        try:
            self._actualizar()
        finally:
            self._ms_cuadro = (time.perf_counter() - t_ini) * 1e3
            self._en_refresco = False

    def _actualizar(self):
        self._cache.clear()
        self._cuadro += 1
        con_info = self._cuadro % CADA_INFO == 0
        con_tri = self._cuadro % CADA_TRI == 0

        self.drenar()
        ahora = self.n_total / FS

        if self.T is None:
            if ahora < CALIBRACION_S:
                self.txt.set_text(f"calibrando la triangular... "
                                  f"{ahora:.1f} / {CALIBRACION_S:.0f} s")
                self.fig.canvas.draw_idle()
                return
            if not self.ajustar(primera_vez=True):
                self.txt.set_text(
                    "no llegan lineas '#v,...': la placa tiene firmware viejo,\n"
                    "reflashea firmware/adquisicion/adquisicion.ino")
                self.fig.canvas.draw_idle()
                return
            print(f"  triangular: periodo {self.T*1e3:.3f} ms "
                  f"({1/self.T:.3f} Hz), rampa {self.n} muestras")
            sat = self.saturacion()
            if sat > UMBRAL_SAT:
                print(f"  [!] la triangular llega RECORTADA: {sat*100:.0f} % "
                      f"del ciclo pegado a un riel del ADC. La rampa de "
                      f"tension no es la que asume el codigo, asi que las "
                      f"distancias salen escaladas Y los picos ensuciados. "
                      f"Bajale la amplitud al generador (y fijate que este en "
                      f"carga HighZ y no 50 ohm) ANTES de calibrar el eje: "
                      f"calibrar sobre esto tapa el problema, no lo arregla.")
            self.txt.set_visible(False)
            self._poner_eje_x()
        elif ahora - self.t_ajuste > REAJUSTE_S:
            self.t_ajuste = ahora
            self.ajustar(primera_vez=False)

        self.procesar()
        db, span, x0, x1 = self.matriz()
        if con_info:
            self._poner_info(ahora, db)
        self._poner_estado()
        if db is None:
            self._pintar(con_info, con_tri)
            return

        eje = self._eje_x()
        i1 = self._i_alcance()
        lo, hi = min(self.piso, self.techo), max(self.piso, self.techo)
        if hi <= lo:
            hi = lo + 1.0

        # origin="upper": la fila 0 del array (la mas VIEJA) va arriba, y la
        # ultima (la mas nueva) abajo de todo, pegada al panel de la FFT.
        span = max(span, 1e-3)
        self.im.set_data(db)
        self.im.set_extent((x0, x1, 0, span))
        self.im.set_clim(lo, hi)
        # El eje de tiempo se fija en la VENTANA pedida y no en el span que hay
        # cargado. Mientras el buffer se llena, el span crece en cada cuadro:
        # si el eje lo siguiera, los ticks cambiarian siempre y habria que
        # repintar el fondo entero en cada refresco — o sea, ningun blitting
        # justo en el primer medio minuto. Con el eje fijo, lo que falta se ve
        # como espacio vacio arriba (la parte vieja), que es lo que es.
        self.ax.set_ylim(self.ventana, 0)

        self.linea.set_data(eje[:i1], db[-1])
        self.axf.set_ylim(lo, hi)
        self.axf.set_ylabel("dB sobre el fondo" if self.fondo is not None
                            else "dB rel. al pico")
        pico = self.pico_crudo()
        # Sin blanco, pico_crudo() devuelve None y la marca se va del grafico
        # en vez de quedarse clavada donde estaba el ultimo: dejarla puesta es
        # exactamente el numero inventado que se quiere evitar.
        x = np.nan
        if pico is not None:
            x = (float(self.cal.aplicar(pico)) if self.en_metros else
                 float(np.interp(pico, self.eje_m_crudo, self.eje_hz)))
        self.marca.set_xdata([x, x])

        xs, ys = self.traza_picos(db, span)
        self.traza.set_data(xs, ys)
        if con_tri:
            self._dibujar_triangular()
        self._pintar(con_info, con_tri)

    def traza_picos(self, db, span):
        """Posicion del pico fila por fila, para seguir el blanco.

        Las filas donde el pico no se despega del fondo salen NaN, asi la
        linea se corta en vez de inventar una posicion: con la escala de dB
        automatica cualquier fila de puro ruido tiene un maximo, y unir esos
        maximos daria una traza que parece un blanco moviendose y no es nada.

        `db` ya viene recortado a lo que se ve, asi que la traza busca el pico
        adentro del alcance en pantalla. Un pico mas lejos que el alcance no
        se podia dibujar igual: quedaba fuera del eje.
        """
        i0 = self._i_zona()
        if i0 >= db.shape[1] - 1:
            return [], []
        campo = db[:, i0:]
        i = np.argmax(campo, axis=1)
        alto = campo[np.arange(len(i)), i]
        fondo = np.median(campo, axis=1)
        vale = alto - fondo >= TRAZA_MIN_DB
        # Con fondo medido manda ademas la puerta de energia, fila por fila:
        # una fila sin blanco no marca nada aunque su maximo local sobresalga
        # del ruido de esa misma fila.
        if self.energia_db is not None and len(self.energia_db) == len(vale):
            vale &= self.energia_db >= self.margen
        eje = self._eje_x()
        x = np.where(vale, eje[i + i0], np.nan)
        # Fila 0 = la mas vieja = arriba de todo (origin="upper").
        filas = db.shape[0]
        y = span * (filas - 0.5 - np.arange(filas)) / filas
        return x, y

    def _dibujar_triangular(self):
        """El cuadrito de la triangular, plegada en fase sobre un periodo."""
        if not self.tri_fila or self.T is None:
            return
        idx, val = self._tri_arrays()
        fase = ((idx / FS - self.t0) % self.T) / self.T
        self.tri_pts.set_data(fase * self.T * 1e3, val)
        # Redondeado a 0,01 ms: cada reajuste mueve T unos pocos ppm, y si el
        # limite del eje lo siguiera con todos sus decimales habria que
        # repintar el fondo entero cada REAJUSTE_S. Con el redondeo cambia
        # solo si T se movio de verdad.
        self.axt.set_xlim(0, round(self.T * 1e3, 2))

    def _volts(self):
        """(min, max) de la triangular en V del generador.

        El ADC del C3 con la atenuacion por defecto llega a ~ADC_FS_V y el
        divisor 4k7/4k7 le da la mitad de lo que sale del generador. Es una
        medicion floja (el ADC comprime cerca del riel) pero alcanza para
        darse cuenta de que la amplitud no es la que uno cree.
        """
        _, a = self._tri_arrays()
        if not len(a):
            return None, None
        v = a / 4095 * ADC_FS_V * DIVISOR
        return float(v.min()), float(v.max())

    def _poner_estado(self):
        pico = self.pico_crudo()
        if self.cal.activa:
            cal = f"d = {self.cal.a:.4f}*crudo\n      {self.cal.b:+.3f} m"
        else:
            cal = "sin calibrar (crudo)"
        if self.fondo is None:
            lin_fondo = "fondo: sin medir\n  (normaliza al maximo)"
        else:
            e_db = self.energia_actual_db()
            lin_fondo = (
                f"fondo: {'AUTO (MTI)' if self.mti else 'medido'}\n"
                f"energia: {0.0 if e_db is None else e_db:+6.1f} dB\n"
                f"margen:  {self.margen:+6.1f} dB\n"
                f"  -> {'HAY BLANCO' if self.hay_blanco() else 'sin blanco'}")
        lin_pico = ("pico: -" if pico is None else
                    f"pico: {float(self.cal.aplicar(pico)):.3f} m\n"
                    f"      (crudo {pico:.3f})")
        self.estado.set_text(
            f"{lin_fondo}\n"
            f"{lin_pico}\n"
            f"\ncalibracion:\n  {cal}\n"
            f"puntos: {len(self.cal.puntos)}\n"
            f"\n{self.aviso}")

    def _poner_info(self, ahora, db):
        filas = 0 if db is None else db.shape[0]
        titulo = (f"Radargrama - {self.n_rampas} rampas/fila "
                  f"({self.n_rampas*self.T/2*1e3:.0f} ms)"
                  if self.T else "Radargrama")
        if self.ax.get_title() != titulo:
            self.ax.set_title(titulo, fontsize=10)

        sat = self.saturacion()
        vmin, vmax = self._volts()
        bw = self.curva(V_MAX) - self.curva(V_MIN)
        alpha0 = bw / (self.T / 2)
        # Resolucion en distancia: c/(2*BW), y no depende de fs (CLAUDE.md).
        # Alcance no ambiguo: el Nyquist del eje de batido.
        res = C / (2 * bw)
        d_nyq = (self.fs_th / 2) * C / (2 * alpha0)
        lin_sat = "OK" if sat <= UMBRAL_SAT else f"RECORTADA ({sat*100:.0f}%)"
        e_db = self.energia_actual_db()
        self.info.set_text(
            f"corriendo    {ahora/60:6.1f} min\n"
            f"muestras     {self.lec.n_filas:9d}\n"
            f"cortadas     {self.lec.descartadas:9d}\n"
            f"ms/cuadro    {self._ms_cuadro:9.1f}\n"
            f"\n"
            f"-- rampa --\n"
            f"Tprf (ciclo) {self.T*1e3:8.3f} ms\n"
            f"  = {1/self.T:.3f} Hz\n"
            f"rampa        {self.T/2*1e3:8.3f} ms\n"
            f"             {self.n:6d} muestras\n"
            f"fs salida    {FS:8.0f} sps\n"
            f"fs en theta  {self.fs_th:8.1f} sps\n"
            f"\n"
            f"-- barrido --\n"
            f"BW (curva)   {bw/1e6:8.1f} MHz\n"
            f"V_MIN..V_MAX {V_MIN:.2f}..{V_MAX:.2f} V\n"
            f"alpha0     {alpha0/1e12:8.4f} THz/s\n"
            f"bin         {res*100:8.1f} cm\n"
            f"no ambiguo  {d_nyq:8.2f} m\n"
            f"  ({alpha0*2/C:.0f} Hz por metro)\n"
            f"\n"
            f"-- triangular --\n"
            f"medida GPIO3 x{DIVISOR:.0f}\n"
            + (f"  {vmin:5.2f} a {vmax:5.2f} V\n" if vmin is not None
               else "  -\n") +
            f"  pico a pico {(vmax-vmin) if vmin is not None else 0:5.2f} V\n"
            f"riel del ADC {lin_sat}\n"
            f"lecturas/s   {len(self.tri_fila)/VENTANA_AJUSTE_S:8.0f}\n"
            f"\n"
            f"-- fondo --\n"
            + ("sin medir\n" if self.fondo is None else
               f"modo      {'AUTO (MTI)' if self.mti else 'congelado':>8}\n"
               f"energia   {0.0 if e_db is None else e_db:+8.1f} dB\n"
               f"margen    {self.margen:+8.1f} dB\n"
               f"blanco    {'SI' if self.hay_blanco() else 'no':>8}\n") +
            f"\n"
            f"-- pantalla --\n"
            f"filas        {filas:9d}\n"
            f"rampas/fila  {self.n_rampas:9d}\n"
            f"agrupado ef. {self.n_ef:9d}\n"
            f"por fila     {self.n_ef*self.T/2*1e3:6.0f} ms")


def main():
    curva = cargar_curva_vco(VCO_CSV)
    os.makedirs(DATOS, exist_ok=True)

    cal = Calibracion()
    fecha = cal.cargar(CAL_JSON)
    if fecha:
        print(f"Calibracion de distancia cargada ({fecha}): "
              f"d = {cal.a:.4f}*crudo {cal.b:+.3f} m")
    else:
        print("Sin calibracion de distancia: el eje esta CRUDO.\n"
              "  Para calibrarlo: poner una placa a una distancia conocida,\n"
              "  tipearla en 'dist. real [m]', 'tomar punto'; repetir a otra\n"
              "  distancia bien distinta, y despues 'calibrar'.")

    ser = abrir_puerto()
    print(f"Grabando a {SALIDA} (y {SAL_TRI}). Sobrescribe lo anterior.")

    with open(SALIDA, "w", encoding="utf-8", newline="\n") as f_cap, \
         open(SAL_TRI, "w", encoding="utf-8", newline="\n") as f_tri:
        lec = Lector(ser, f_cap, f_tri)
        lec.start()
        vivo = Vivo(lec, curva, cal)
        vivo.armar_figura()
        # El timer del canvas en vez de FuncAnimation: no hace falta guardar
        # cuadros, y el blitting lo maneja _pintar() a mano.
        timer = vivo.fig.canvas.new_timer(interval=REFRESCO_MS)
        timer.add_callback(vivo.actualizar)
        timer.start()
        try:
            plt.show()
        finally:
            timer.stop()
            lec.parar = True
            lec.join(timeout=1.0)
            try:
                ser.write(b"stop\n")
            except Exception:
                pass
            ser.close()
    print(f"Listo. {lec.n_filas} muestras guardadas en {SALIDA}.")


if __name__ == "__main__":
    main()
