"""
GPRv2 - Radargrama en tiempo real
===================================

Abre el puerto del ESP32-C3, manda 'run' y va dibujando mientras las muestras
llegan. Es waterfall.py sin tener que grabar primero y analizar despues.

La ventana tiene tres partes:

    izquierda   todas las configuraciones, en cuadros de texto. Se tipea el
                valor y se aprieta Enter, y los botones.
    centro      arriba el radargrama, que corre VERTICAL: distancia en x,
                tiempo en y, la fila mas nueva abajo de todo y las viejas
                subiendo, con una traza roja siguiendo el pico fila por fila.
                Abajo, la FFT de la ultima fila, con el mismo eje x.
    derecha     arriba el cuadro de informacion de la captura (Tprf, rampa,
                barrido, tensiones medidas de la triangular, resolucion).
                Abajo, la triangular plegada en un periodo.

El eje de distancia arranca SIEMPRE en 0: es la referencia, y con una
calibracion de offset negativo el eje crudo empieza en un numero negativo.

Todo lo que se muestra se graba a datos/captura.csv y datos/triangular.csv,
asi que se puede volver a analizar despues con waterfall.py o
graficar_captura.py. OJO: sobrescribe la captura anterior.

Calibracion del eje de distancia
--------------------------------
El eje crudo sale de alpha0 = BW/T con la BW de la curva del VCO, y en el
banco real no da: una placa a 1 m puede aparecer en 4 m. Por eso el eje se
calibra con blancos de distancia conocida, con dos puntos:

    1. poner la placa a una distancia, tipearla en "dist. real [m]",
       apretar "tomar punto"
    2. moverla a otra distancia bien distinta, repetir
    3. apretar "calibrar"

Eso ajusta d_real = a*d_crudo + b por minimos cuadrados: 'a' corrige la
pendiente (o sea la BW efectiva, que evidentemente no es la nominal) y 'b'
el retardo fijo de cables y electronica. Queda guardado en
datos/calibracion_distancia.json y se carga solo la proxima vez.

OJO CON LO QUE LA CALIBRACION TAPA. Un factor de escala de 1,1 o 1,2 es
retardo y tolerancias. Un factor de 4 NO: quiere decir que la BW efectiva
del barrido es cuatro veces la nominal, o que el tramo que se esta tratando
como una rampa no es la rampa entera. La calibracion lo hace ver bien igual,
asi que conviene mirar el numero de "BW efectiva" que imprime al calibrar y
desconfiar si esta lejos de los 1039 MHz de la curva del VCO.

Controles
---------
    cuadros de texto (izquierda), Enter para aplicar:
        rampas/col     cuantas rampas se promedian en cada fila
        ventana [s]    cuanto tiempo se muestra
        alcance [m]    tope del eje de distancia
        piso / techo   escala de color, en dB respecto del pico en pantalla
        ignorar < [m]  desde donde busca el pico para calibrar (el
                       acoplamiento directo TX->RX vive cerca de cero y se
                       lleva puesto cualquier argmax)
        dist. real [m] la distancia verdadera del blanco, para calibrar
    botones:  eje: m <-> Hz | tomar punto | calibrar | borrar cal
    e         lo mismo que el boton de eje
    a         autoescala el color a lo que hay en pantalla
    q         salir

Como se sincroniza sin sync
---------------------------
Los limites de rampa salen de la triangular que el ESP32 muestrea por GPIO3
(ver ajustar_triangular()), y el ajuste se REHACE cada REAJUSTE_S segundos
sobre los ultimos VENTANA_AJUSTE_S de triangular.

Hace falta porque el error del ajuste se ACUMULA hacia adelante. Que el reloj
del generador y el del ESP32 no sean el mismo no es el problema: una
diferencia constante de reloj hace que el C3 vea un periodo constante y
distinto del nominal, y el ajuste lo mide igual de bien. El problema es que
ese periodo medido tiene un error residual, y cada rampa se ubica
multiplicando el periodo por su indice: el error crece lineal con el tiempo.

Medido sobre un stream sintetico con 200 ppm de deriva de reloj:

    con reajuste cada 2 s     9 us de error  = 0,05 % de la rampa
    sin reajuste, a los 60 s  1095 us        = 5,40 % de la rampa

Esto anda con sync o sin sync: las lineas '#v,...' salen siempre. La columna
de sync del CSV se graba pero no se usa aca.

Uso
---
    python vivo.py
"""

import json
import os
import re
import threading
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox

import serial
from serial.tools import list_ports

from correccion_no_linealidad import (
    T_SWEEP, C, V_MIN, V_MAX, cargar_curva_vco, eje_theta, remuestrear,
    ajustar_triangular, fs_theta,
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
# (ver GPRv2/CLAUDE.md). Lo que hace es interpolar, y sin el la rampa de 120
# muestras da 61 bins para todo el eje y sale en bandas gruesas.
RELLENO   = 8
VENTANA_DEF = 20.0   # s de historia que se muestran
VENTANA_MAX = 120.0
ALCANCE_DEF = 5.0    # m, tope del eje de distancia
IGNORAR_DEF = 0.3    # m, desde donde se busca el pico para calibrar
PISO_DEF  = -40.0    # dB respecto del pico en pantalla
TECHO_DEF = 0.0
PROMEDIO_CAL_S = 2.0  # cuanto se promedia para tomar un punto de calibracion
# Cuanto tiene que despegarse el pico de una fila del fondo de esa fila para
# que la traza roja lo marque. Sin esto la traza une los maximos de filas de
# puro ruido y dibuja un blanco que no existe.
TRAZA_MIN_DB = 3.0
# Fraccion del ciclo pegada a un riel a partir de la cual se avisa. 2 % era
# demasiado sensible: con la triangular sana el vertice de abajo roza el cero
# y saltaba la alarma sin motivo. Con la triangular entrando sin dividir el
# recorte fue del 18 %, asi que 5 % separa bien los dos casos.
UMBRAL_SAT = 0.05
# El ADC del C3 a 12 bits con la atenuacion por defecto llega a ~2,5 V, y el
# divisor 4k7/4k7 le da la mitad de lo que sale del generador.
ADC_FS_V = 2.5
DIVISOR = 2.0

AQUI    = os.path.dirname(os.path.abspath(__file__))
DATOS   = os.path.join(AQUI, "..", "datos")
SALIDA  = os.path.join(DATOS, "captura.csv")
SAL_TRI = os.path.join(DATOS, "triangular.csv")
CAL_JSON = os.path.join(DATOS, "calibracion_distancia.json")
VCO_CSV = os.path.join(AQUI, "..", "..", "VCO", "Caracteristica VCO.csv")

# Las lineas cortadas por la mitad son normales (la primera del stream siempre,
# y a ~85 kB/s el CDC parte alguna): se filtran aca y se cuentan.
RE_MUESTRA = re.compile(r"^-?\d+,-?\d+$")
RE_TRI = re.compile(r"^\d+,\d+$")


# --- Lectura del puerto ----------------------------------------------------

class Lector(threading.Thread):
    """
    Hilo que vacia el puerto serie, clasifica las lineas y las va escribiendo
    a disco. El hilo del grafico le pide las nuevas con tomar().

    Lee por bloques con read(in_waiting) y parte las lineas a mano en vez de
    usar readline(): a 6000 sps son ~6000 readline() por segundo, y con el
    GIL peleando contra el redibujado de matplotlib eso se atrasa y termina
    desbordando el buffer del sistema. Por bloques son ~50 llamadas/s.
    """

    def __init__(self, ser, f_cap, f_tri):
        super().__init__(daemon=True)
        self.ser = ser
        self.f_cap = f_cap
        self.f_tri = f_tri
        self.lock = threading.Lock()
        self._beat = []          # muestras nuevas, sin consumir por el grafico
        self._tri = []           # (fila, adc) nuevos, sin consumir
        self.n_filas = 0         # filas escritas = indice absoluto de muestra
        self.descartadas = 0
        self.parar = False

    def run(self):
        resto = b""
        while not self.parar:
            try:
                # read() bloquea hasta el timeout del puerto cuando no hay
                # nada, asi que este lazo no hace spin si la placa calla.
                datos = self.ser.read(max(1, self.ser.in_waiting))
            except Exception:
                break
            if not datos:
                continue
            trozos = (resto + datos).split(b"\n")
            resto = trozos.pop()          # la ultima puede estar cortada
            self.procesar(trozos)

    def procesar(self, trozos):
        """Clasifica lineas completas, las escribe a disco y las encola.

        Aparte de run() para poder probarla sin puerto ni hilos.
        """
        beat, tri, txt_cap, txt_tri = [], [], [], []
        for cruda in trozos:
            linea = cruda.decode("ascii", "ignore").strip()
            if not linea:
                continue
            if linea.startswith("#v,"):
                if not RE_TRI.match(linea[3:]):
                    self.descartadas += 1
                    continue
                # El indice que manda la placa se ignora a proposito y se
                # usa el propio contador de filas: si se perdio una linea
                # de muestra, el indice de la placa ya no apunta a la fila
                # correcta del CSV, y el contador propio si.
                fila = self.n_filas - 1
                if fila < 0:
                    continue
                adc = int(linea[3:].split(",")[0])
                tri.append((fila, adc))
                txt_tri.append(f"{adc},{fila}")
            elif linea.startswith("#"):
                continue                    # respuestas a comandos
            elif RE_MUESTRA.match(linea):
                beat.append(int(linea.split(",", 1)[0]))
                txt_cap.append(linea)
                self.n_filas += 1
            else:
                self.descartadas += 1
        if txt_cap:
            self.f_cap.write("\n".join(txt_cap) + "\n")
        if txt_tri:
            self.f_tri.write("\n".join(txt_tri) + "\n")
        with self.lock:
            self._beat.extend(beat)
            self._tri.extend(tri)

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
    Mapa afin d_real = a*d_crudo + b, ajustado con blancos de distancia
    conocida. 'a' corrige la pendiente (la BW efectiva del barrido no es la
    nominal) y 'b' el retardo fijo de cables y electronica.

    Con dos puntos la recta pasa exacta por los dos; con mas, minimos
    cuadrados. Se guarda en JSON para no tener que rehacerla cada vez.
    """

    def __init__(self):
        self.a, self.b = 1.0, 0.0
        self.puntos = []          # [(d_crudo, d_real), ...]

    @property
    def activa(self):
        return self.a != 1.0 or self.b != 0.0

    def aplicar(self, d):
        return self.a * np.asarray(d) + self.b

    def ajustar(self):
        """Devuelve un texto con el resultado, o el motivo de no poder."""
        if len(self.puntos) < 2:
            return "faltan puntos (hacen falta 2)"
        crudo = np.array([p[0] for p in self.puntos])
        real = np.array([p[1] for p in self.puntos])
        if np.ptp(crudo) < 1e-6:
            return "los puntos estan a la misma distancia cruda"
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
        # el indice absoluto de beat[0]: se va tirando lo ya consumido para
        # que el buffer no crezca toda la sesion.
        self.beat = np.empty(0)
        self.base = 0
        self.n_total = 0

        self.tri_fila, self.tri_adc = [], []   # ventana para el ajuste
        self.T = self.t0 = None
        self.n = 0
        self.k = 0                 # indice de la proxima rampa a procesar
        self.t_ajuste = 0.0

        # Los perfiles van a un buffer numpy preasignado y no a una lista: con
        # relleno x8 cada perfil son ~500 numeros y la ventana puede pedir
        # miles, asi que armar un array nuevo en cada refresco seria copiar
        # decenas de MB cinco veces por segundo.
        self.P = self.tp = None
        self.n_perf = 0
        self.cap = self.necesarios = 0

        self.n_rampas = N_DEFECTO
        self.ventana = VENTANA_DEF
        self.alcance = ALCANCE_DEF
        self.ignorar = IGNORAR_DEF
        self.en_metros = True
        self.piso, self.techo = PISO_DEF, TECHO_DEF
        self.dist_real = 1.0
        self.aviso = ""

    # --- datos ---

    def drenar(self):
        beat, tri = self.lec.tomar()
        if beat:
            self.beat = np.concatenate([self.beat, np.asarray(beat, float)])
            self.n_total += len(beat)
        for fila, adc in tri:
            self.tri_fila.append(fila)
            self.tri_adc.append(adc)
        # La ventana de ajuste se recorta por tiempo, no por cantidad: la tasa
        # de lecturas depende de fs y del tamano de bloque del firmware.
        corte = self.n_total - VENTANA_AJUSTE_S * FS
        while self.tri_fila and self.tri_fila[0] < corte:
            self.tri_fila.pop(0)
            self.tri_adc.pop(0)

    def saturacion(self):
        """Fraccion de la triangular que llega pegada a un riel del ADC.

        Es el chequeo mas importante del banco y por eso esta a la vista. Si
        la triangular se sale del rango, la rampa de tension NO es la que el
        codigo asume (V_MIN a V_MAX a lo largo de toda la rampa): el VCO
        recorre su rango en una fraccion del tiempo, el alpha0 real es mayor
        que el asumido y TODAS las distancias salen mas grandes. Y peor: el
        mapa theta de eje_theta() queda aplicado sobre una v(t) equivocada,
        asi que no es un error de escala que se arregle calibrando el eje,
        los picos se ensucian.

        Medido el 2026-09-04 sobre datos/triangular.csv: 16 % del ciclo
        pegado a 4095, triangular de ~5,4 V pico a pico en vez de 3. La causa
        mas probable de un factor 2 justo es el generador configurado para
        carga de 50 ohm manejando una entrada de alta impedancia, que
        duplica la amplitud respecto de lo que muestra el panel.
        """
        if not self.tri_adc:
            return 0.0
        a = np.asarray(self.tri_adc)
        return float(((a >= 4090) | (a <= 5)).mean())

    def ajustar(self, primera_vez):
        """Rehace el ajuste de periodo y fase de la triangular."""
        if len(self.tri_fila) < 20:
            return False
        # La primera vez se busca ancho alrededor del nominal; despues ya se
        # sabe donde esta y se busca angosto, que es mas barato y no puede
        # saltar a un armonico vecino.
        T_ini = 2.0 * T_SWEEP if primera_vez else self.T
        span = 0.25 if primera_vez else 0.01
        T, t0 = ajustar_triangular(self.tri_fila, self.tri_adc, FS, T_ini, span)

        if primera_vez:
            self.T, self.t0 = T, t0
            self.n = int(round(T * FS / 2))
            self.k = 0
            self._armar_ejes()
            return True

        # Se conserva la posicion actual: k se recalcula para que la proxima
        # rampa caiga donde iba a caer, con el periodo y la fase nuevos. Sin
        # esto, un reajuste reprocesa rampas viejas o se saltea algunas.
        t_prox = self.t0 + self.k * self.T / 2
        k = int(round((t_prox - t0) / (T / 2)))
        # Histeresis en n: sin esto, un T que oscila alrededor de un valor
        # medio hace saltar n entre dos enteros y los perfiles dejan de tener
        # todos el mismo largo.
        if abs(T * FS / 2 - self.n) > 0.6:
            self.n = int(round(T * FS / 2))
            self._armar_ejes()         # tambien vacia el buffer de perfiles:
                                       # cambio el largo y no se pueden mezclar
            print(f"  [!] la rampa cambio a {self.n} muestras, se reinicia "
                  f"el radargrama")
        self.T, self.t0, self.k = T, t0, max(k, 0)
        return True

    def _armar_ejes(self):
        n = self.n
        t = np.linspace(0, n / FS, n, endpoint=False)
        _, self.theta, self.alpha0 = eje_theta(self.curva, t)
        self.fs_th = fs_theta(self.theta, n)
        self.nfft = RELLENO * n
        self.ventana_fft = np.hanning(n)
        freqs = np.fft.rfftfreq(self.nfft, d=1.0 / self.fs_th)
        self.eje_hz = freqs
        self.eje_m_crudo = freqs * C / (2.0 * self.alpha0)

        # Capacidad: el doble de lo que pide la ventana mas larga. Al llenarse
        # se descarta SOLO el excedente y quedan 'necesarios' perfiles, o sea
        # una ventana maxima entera. Antes se tiraba la mitad del buffer, y
        # con una ventana grande la pantalla colapsaba y volvia a crecer en
        # ciclo cada vez que se llenaba.
        self.necesarios = int(VENTANA_MAX * 2 / self.T) + 10
        self.cap = 2 * self.necesarios
        self.P = self.tp = None
        self.n_perf = 0

    @property
    def eje_m(self):
        """Eje de distancia ya calibrado."""
        return self.cal.aplicar(self.eje_m_crudo)

    def _guardar_perfil(self, esp, t):
        if self.P is None:
            # float32: son magnitudes para dibujar, no hace falta doble
            # precision, y a 500 numeros por perfil la mitad de memoria se nota.
            self.P = np.empty((self.cap, len(esp)), dtype=np.float32)
            self.tp = np.empty(self.cap)
        if self.n_perf == self.cap:
            self.P[:self.necesarios] = self.P[self.cap - self.necesarios:]
            self.tp[:self.necesarios] = self.tp[self.cap - self.necesarios:]
            self.n_perf = self.necesarios
        self.P[self.n_perf] = esp
        self.tp[self.n_perf] = t
        self.n_perf += 1

    def procesar(self):
        """Trocea todas las rampas completas que hayan llegado."""
        while True:
            ini = int(round((self.t0 + self.k * self.T / 2) * FS))
            fin = ini + self.n
            if fin > self.n_total:
                break
            impar = self.k % 2          # 0 = subida, 1 = bajada
            self.k += 1
            if ini < self.base:         # quedo atras por un reajuste
                continue
            seg = self.beat[ini - self.base:fin - self.base]
            if impar:
                seg = seg[::-1]         # la bajada, leida al reves, es una subida
            seg = seg - seg.mean()
            _, corr = remuestrear(self.theta, seg, self.n)
            # FFT propia y no perfil_distancia(), por el relleno de ceros: esa
            # no rellena y con 120 muestras por rampa deja 61 bins.
            esp = np.abs(np.fft.rfft(corr * self.ventana_fft, n=self.nfft))
            self._guardar_perfil(esp, fin / FS)

        # Tirar lo ya consumido, dejando un margen por si un reajuste corre
        # los limites un poco para atras.
        ini = int(round((self.t0 + self.k * self.T / 2) * FS))
        corte = max(0, ini - 4 * self.n - self.base)
        if corte:
            self.beat = self.beat[corte:]
            self.base += corte

    def matriz(self):
        """Agrupa los perfiles de a n_rampas.

        Devuelve (db, span) con db de forma (filas, bins), la fila 0 la mas
        VIEJA y la ultima la mas nueva, y span los segundos que abarca. El
        agrupado se rehace entero en cada refresco a partir de los perfiles de
        a UNA rampa, asi cambiar rampas/col o la ventana reagrupa todo lo que
        hay en pantalla y no solo lo que venga de ahi en mas.
        """
        # Se puede llamar antes de la calibracion de la triangular (el boton
        # de tomar punto, por ejemplo), y ahi no hay ni periodo ni perfiles.
        if self.T is None or not self.n_perf:
            return None, 0.0
        N = self.n_rampas
        caben = min(self.n_perf, int(round(self.ventana / (self.T / 2))))
        filas = caben // N
        if filas < 1:
            return None, 0.0
        usadas = filas * N
        P = self.P[self.n_perf - usadas:self.n_perf]        # vista, no copia
        M = P.reshape(filas, N, P.shape[1]).mean(axis=1)
        db = 20 * np.log10(M / (M.max() + 1e-12) + 1e-12)
        return db, self.tp[self.n_perf - 1] - self.tp[self.n_perf - usadas]

    def perfil_actual(self):
        """Promedio de los ultimos PROMEDIO_CAL_S, para tomar puntos."""
        if self.T is None or not self.n_perf:
            return None
        cuantos = max(1, min(self.n_perf,
                             int(round(PROMEDIO_CAL_S / (self.T / 2)))))
        return self.P[self.n_perf - cuantos:self.n_perf].mean(axis=0)

    def pico_crudo(self):
        """Distancia CRUDA del pico mas fuerte, salteando el acoplamiento.

        Se saltea todo lo que este debajo de 'ignorar': el acoplamiento
        directo TX->RX vive cerca de cero, es lo mas fuerte de la pantalla y
        se lleva puesto cualquier argmax.
        """
        perfil = self.perfil_actual()
        if perfil is None:
            return None
        # El umbral se tipea en el eje que se esta viendo (calibrado), asi que
        # se convierte a crudo antes de comparar.
        umbral = (self.ignorar - self.cal.b) / self.cal.a
        sel = self.eje_m_crudo >= umbral
        if not sel.any():
            return None
        i = np.argmax(np.where(sel, perfil, -np.inf))
        return float(self.eje_m_crudo[i])

    # --- grafico ---

    def armar_figura(self):
        self.fig = plt.figure(figsize=(14, 8))
        self.ax = self.fig.add_axes([0.265, 0.42, 0.455, 0.50])   # radargrama
        self.axf = self.fig.add_axes([0.265, 0.08, 0.455, 0.26],  # FFT
                                     sharex=self.ax)
        self.axc = self.fig.add_axes([0.732, 0.42, 0.011, 0.50])  # colorbar
        self.axi = self.fig.add_axes([0.795, 0.42, 0.195, 0.50])  # info
        self.axt = self.fig.add_axes([0.795, 0.08, 0.195, 0.20])  # triangular

        self.im = self.ax.imshow(np.zeros((2, 2)), origin="upper",
                                 aspect="auto", cmap="viridis",
                                 extent=(0, ALCANCE_DEF, 0, VENTANA_DEF),
                                 vmin=self.piso, vmax=self.techo)
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
        self.axf.set_ylabel("dB rel. al pico")
        self.axf.grid(alpha=0.3)
        self.axf.set_ylim(self.piso, self.techo)

        # Cuadro de informacion: es un axes sin ticks, o sea un rectangulo con
        # marco, y adentro un bloque de texto monoespaciado.
        self.axi.set_xticks([]); self.axi.set_yticks([])
        self.axi.set_title("Captura", fontsize=9)
        # 7,2 pt y no 8: son 31 lineas y a 8 pt la ultima se sale del marco.
        self.info = self.axi.text(0.04, 0.975, "", transform=self.axi.transAxes,
                                  va="top", ha="left", fontsize=7.2,
                                  family="monospace")

        # Cuadrito de la triangular. Se dibuja PLEGADA en fase y no como serie
        # de tiempo: a ~188 lecturas/s son 7,5 puntos por periodo, que sueltos
        # parecen ruido. Plegando los ultimos VENTANA_AJUSTE_S se ven ~940
        # puntos sobre un periodo y la forma (y cualquier recorte) salta a la
        # vista. Es ademas la misma vista sobre la que se ajusta el periodo.
        self.axt.set_xticks([]); self.axt.set_yticks([])
        self.axt.set_title("Triangular (plegada)", fontsize=9)
        (self.tri_pts,) = self.axt.plot([], [], ".", ms=1.5, alpha=0.4,
                                        color="tab:red")
        self.axt.axhline(4095, color="k", ls="--", lw=0.8)
        self.axt.axhline(0, color="k", ls="--", lw=0.8)
        self.axt.set_ylim(-250, 4345)

        self._armar_controles()
        self._poner_eje_x()

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
            ("dist_real", "dist. real [m]", lambda: f"{self.dist_real:g}"),
        ]
        y = 0.90
        for nombre, etiqueta, leer in campos:
            ax = self.fig.add_axes([0.135, y, 0.075, 0.038])
            caja = TextBox(ax, etiqueta + "  ", initial=leer())
            caja.on_submit(lambda t, k=nombre: self._escribir(k, t))
            self.cajas[nombre] = (caja, leer)
            y -= 0.052

        y -= 0.02
        self.botones = []
        for etiqueta, fn in (("eje: m <-> Hz", self._cambiar_eje),
                             ("tomar punto", self._tomar_punto),
                             ("calibrar", self._calibrar),
                             ("borrar cal", self._borrar_cal)):
            ax = self.fig.add_axes([0.045, y, 0.165, 0.042])
            b = Button(ax, etiqueta)
            b.on_clicked(fn)
            self.botones.append(b)          # hay que retenerlos o se mueren
            y -= 0.055

        self.estado = self.fig.text(0.03, y - 0.02, "", va="top", ha="left",
                                    fontsize=8.5, family="monospace")
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
        elif campo == "dist_real":
            self.dist_real = v
        self.aviso = ""
        self._refrescar_cajas()
        self._poner_eje_x()

    def _refrescar_cajas(self):
        """Deja los cuadros mostrando el valor que de verdad quedo."""
        for caja, leer in self.cajas.values():
            texto = leer()
            if caja.text != texto:
                caja.set_val(texto)

    def _cambiar_eje(self, _=None):
        self.en_metros = not self.en_metros
        self._poner_eje_x()

    def _tomar_punto(self, _=None):
        d = self.pico_crudo()
        if d is None:
            self.aviso = "todavia no hay perfil"
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
            # La pendiente dice cuanto se equivoca la BW efectiva: d va como
            # 1/alpha0, asi que la BW real es la nominal dividida por 'a'.
            bw_nom = (self.curva(V_MAX) - self.curva(V_MIN)) / 1e6
            print(f"  BW efectiva implicada: {bw_nom/self.cal.a:.0f} MHz "
                  f"(la nominal de la curva del VCO es {bw_nom:.0f} MHz)")
            if not 0.7 < self.cal.a < 1.4:
                print("  [!] esa pendiente esta muy lejos de 1: la calibracion "
                      "lo va a hacer ver bien, pero hay algo del banco que no "
                      "es lo que creemos (BW real del barrido, o el tramo que "
                      "se esta tomando como rampa).")
        self._poner_eje_x()

    def _borrar_cal(self, _=None):
        self.cal.borrar()
        try:
            os.remove(CAL_JSON)
        except OSError:
            pass
        self.aviso = "calibracion borrada, eje crudo"
        self._poner_eje_x()

    def _tecla(self, ev):
        # Mientras se tipea en un cuadro, las teclas son del cuadro.
        if any(c.capturekeystrokes for c, _ in self.cajas.values()):
            return
        if ev.key == "e":
            self.en_metros = not self.en_metros
            self._poner_eje_x()
        elif ev.key == "a":
            db, _ = self.matriz()
            if db is not None:
                # El piso al percentil 60 y no al minimo: el minimo lo fija
                # un solo bin y deja casi todo el rango de color sin usar.
                # Redondeado, porque el numero va a parar a un cuadro de texto
                # y "-33.7" se lee, "-33.69521484" no.
                self.piso = round(float(np.percentile(db, 60)), 1)
                self.techo = round(float(db.max()), 1)
                self._refrescar_cajas()

    def _eje_x(self):
        return self.eje_m if self.en_metros else self.eje_hz

    def _poner_eje_x(self):
        if self.T is None:
            self.axf.set_xlabel("Distancia [m]")
            return
        eje = self._eje_x()
        if self.en_metros:
            tope, etiqueta = self.alcance, "Distancia [m]"
        else:
            # El alcance se tipea siempre en metros: es la misma escala con
            # otra unidad, asi el numero quiere decir lo mismo en los dos modos.
            tope = np.interp(self.alcance, self.eje_m, self.eje_hz)
            etiqueta = "Frecuencia de batido [Hz]"
        self.axf.set_xlabel(etiqueta)
        # Siempre desde 0, no desde eje[0]: con calibracion 'b' negativo el eje
        # crudo arranca en un numero negativo, y arrancar el grafico ahi mueve
        # el cero de lugar cada vez que se recalibra. El cero es la referencia.
        self.ax.set_xlim(0.0, min(tope, eje[-1]))
        _, _, y0, y1 = self.im.get_extent()
        self.im.set_extent((eje[0], eje[-1], y0, y1))

    def actualizar(self, _=None):
        """Un refresco. Siempre termina pidiendo el redibujo.

        Sin el draw_idle() final la pantalla se queda congelada: mutar los
        artistas (set_data, set_title) NO repinta por si solo, y lo unico que
        forzaba el repaint era mover un control. Se ve como que el programa
        anda pero la imagen no avanza hasta que tocas algo.
        """
        try:
            self._actualizar()
        finally:
            self.fig.canvas.draw_idle()

    def _actualizar(self):
        self.drenar()
        ahora = self.n_total / FS

        if self.T is None:
            if ahora < CALIBRACION_S:
                self.txt.set_text(f"calibrando la triangular... "
                                  f"{ahora:.1f} / {CALIBRACION_S:.0f} s")
                return
            if not self.ajustar(primera_vez=True):
                self.txt.set_text(
                    "no llegan lineas '#v,...': la placa tiene firmware viejo,\n"
                    "reflashea firmware/adquisicion/adquisicion.ino")
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
        db, span = self.matriz()
        self._poner_estado(ahora, db)
        if db is None:
            return

        eje = self._eje_x()
        lo, hi = min(self.piso, self.techo), max(self.piso, self.techo)
        if hi <= lo:
            hi = lo + 1.0

        # origin="upper": la fila 0 del array (la mas VIEJA) va arriba, y la
        # ultima (la mas nueva) abajo de todo, pegada al panel de la FFT.
        self.im.set_data(db)
        self.im.set_extent((eje[0], eje[-1], 0, max(span, 1e-3)))
        self.im.set_clim(lo, hi)
        self.ax.set_ylim(max(span, 1e-3), 0)

        self.linea.set_data(eje, db[-1])
        self.axf.set_ylim(lo, hi)
        pico = self.pico_crudo()
        if pico is not None:
            x = (self.cal.aplicar(pico) if self.en_metros else
                 np.interp(pico, self.eje_m_crudo, self.eje_hz))
            self.marca.set_xdata([x, x])

        xs, ys = self.traza_picos(db, span)
        self.traza.set_data(xs, ys)
        self._dibujar_triangular()

    def traza_picos(self, db, span):
        """Posicion del pico fila por fila, para seguir el blanco.

        Devuelve (x, y) listos para dibujar sobre el radargrama. Las filas
        donde el pico no se despega del fondo salen NaN, asi la linea se corta
        en vez de inventar una posicion: con la escala de dB automatica,
        cualquier fila de puro ruido igual tiene un maximo, y unir esos
        maximos daria una traza que parece un blanco moviendose y no es nada.
        """
        umbral = (self.ignorar - self.cal.b) / self.cal.a
        sel = self.eje_m_crudo >= umbral
        if not sel.any():
            return [], []
        campo = np.where(sel, db, -np.inf)
        i = np.argmax(campo, axis=1)
        alto = campo[np.arange(len(i)), i]
        fondo = np.median(db[:, sel], axis=1)
        eje = self._eje_x()
        x = np.where(alto - fondo >= TRAZA_MIN_DB, eje[i], np.nan)
        # Fila 0 = la mas vieja = arriba de todo (origin="upper").
        filas = db.shape[0]
        y = span * (filas - 0.5 - np.arange(filas)) / filas
        return x, y

    def _dibujar_triangular(self):
        """El cuadrito de la triangular, plegada en fase sobre un periodo."""
        if not self.tri_fila:
            return
        idx = np.asarray(self.tri_fila, dtype=float)
        val = np.asarray(self.tri_adc, dtype=float)
        fase = ((idx / FS - self.t0) % self.T) / self.T
        self.tri_pts.set_data(fase * self.T * 1e3, val)
        self.axt.set_xlim(0, self.T * 1e3)

    def _volts(self):
        """(min, max) de la triangular en V del generador, y si esta pegada.

        El ADC del C3 con la atenuacion por defecto llega a ~ADC_FS_V, y el
        divisor 4k7/4k7 le da la mitad de lo que sale del generador. Es una
        medicion floja (el ADC comprime cerca del riel) pero alcanza para
        darse cuenta de que la amplitud no es la que uno cree - que fue
        exactamente el problema del 2026-09-04.
        """
        if not self.tri_adc:
            return None, None
        a = np.asarray(self.tri_adc, dtype=float) / 4095 * ADC_FS_V * DIVISOR
        return a.min(), a.max()

    def _poner_estado(self, ahora, db):
        filas = 0 if db is None else db.shape[0]
        pico = self.pico_crudo()
        if self.cal.activa:
            cal = f"d = {self.cal.a:.4f}*crudo\n      {self.cal.b:+.3f} m"
        else:
            cal = "sin calibrar (crudo)"
        lin_pico = ("pico: -" if pico is None else
                    f"pico: {self.cal.aplicar(pico):.3f} m\n"
                    f"      (crudo {pico:.3f})")
        self.estado.set_text(
            f"calibracion:\n  {cal}\n"
            f"puntos: {len(self.cal.puntos)}\n"
            f"{lin_pico}\n"
            f"\n{self.aviso}")
        self.ax.set_title(f"Radargrama - {self.n_rampas} rampas/fila "
                          f"({self.n_rampas*self.T/2*1e3:.0f} ms)", fontsize=10)

        # --- el cuadro de la derecha ---
        sat = self.saturacion()
        vmin, vmax = self._volts()
        bw = self.curva(V_MAX) - self.curva(V_MIN)
        alpha0 = bw / (self.T / 2)
        # Resolucion en distancia: c/(2*BW), y no la depende de fs (ver
        # GPRv2/CLAUDE.md). Alcance no ambiguo: el Nyquist del eje de batido.
        res = C / (2 * bw)
        d_nyq = (self.fs_th / 2) * C / (2 * alpha0)
        lin_sat = ("OK" if sat <= UMBRAL_SAT else
                   f"RECORTADA ({sat*100:.0f}%)")
        self.info.set_text(
            f"corriendo    {ahora/60:6.1f} min\n"
            f"muestras     {self.lec.n_filas:9d}\n"
            f"cortadas     {self.lec.descartadas:9d}\n"
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
            f"-- pantalla --\n"
            f"filas        {filas:9d}\n"
            f"rampas/fila  {self.n_rampas:9d}\n"
            f"por fila     {self.n_rampas*self.T/2*1e3:6.0f} ms")


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
        # cuadros ni blitear, solo llamar a actualizar() cada tanto.
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
