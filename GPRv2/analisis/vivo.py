"""
GPRv2 - Radargrama en tiempo real
===================================

Abre el puerto del ESP32-C3, manda 'run' y va dibujando el radargrama
mientras las muestras llegan: distancia en y, tiempo en x, potencia en
color. Es waterfall.py, pero sin tener que grabar primero y analizar
despues. Sirve para apuntar la antena, mover un blanco a mano y ver la
traza desplazarse, y para darse cuenta EN EL MOMENTO de que el nivel esta
mal o de que el recorte de rampas se perdio.

Todo lo que se muestra se graba igual a datos/captura.csv y
datos/triangular.csv, asi que cualquier cosa que se vea en vivo se puede
volver a analizar despues con waterfall.py o graficar_captura.py.
OJO: sobrescribe la captura anterior, igual que grabar_rampa.py.

Controles
---------
    slider "rampas/col"      cuantas rampas se promedian en cada columna
                             del radargrama. Mas rampas = menos ruido y
                             menos resolucion temporal.
    slider "ventana [s]"     cuantos segundos de historia se muestran. Es la
                             ventana la que manda: la cantidad de columnas
                             sale de ella y de rampas/col.
    slider "alcance [m]"     tope del eje y. En modo Hz se convierte sola,
                             asi la posicion del slider dice lo mismo en los
                             dos modos.
    sliders "piso" y "techo" limites de la escala de color, en dB respecto
                             del pico de lo que se esta viendo.
    +  /  -                  ajuste fino de rampas/col
    e                        alterna el eje y entre distancia [m] y
                             frecuencia de batido [Hz]
    a                        autoescala el color a lo que hay en pantalla
    q                        salir

Los tres primeros sliders se pueden mover mientras corre y reagrupan TODO lo
que hay en pantalla, no solo lo que venga de ahi en mas: se guardan los
perfiles de a una rampa y el agrupado se rehace en cada refresco.

Como se sincroniza sin sync
---------------------------
Igual que graficar_captura.py: los limites de rampa salen de la triangular
que el ESP32 muestrea por GPIO3 (ver ajustar_triangular()). La diferencia es
que aca el ajuste se REHACE cada REAJUSTE_S segundos sobre los ultimos
VENTANA_AJUSTE_S de triangular.

Hace falta porque el error del ajuste se ACUMULA hacia adelante. Que el
reloj del generador y el del ESP32 no sean el mismo no es el problema: una
diferencia constante de reloj hace que el C3 vea un periodo constante y
distinto del nominal, y el ajuste lo mide igual de bien. El problema es que
ese periodo medido tiene un error residual, y cada rampa se ubica
multiplicando el periodo por su indice: el error crece lineal con el tiempo
desde el ajuste.

Medido sobre un stream sintetico con 200 ppm de deriva de reloj, comparando
contra los vertices verdaderos:

    con reajuste cada 2 s     9 us de error  = 0,05 % de la rampa
    sin reajuste, a los 60 s  1095 us        = 5,40 % de la rampa

o sea que sin reajuste se degrada sola, y a los 10 minutos ya no serviria.
Con reajuste el error no crece: se vuelve a anclar antes de que importe.

Esto anda con sync o sin sync: las lineas '#v,...' de la triangular salen
siempre. La columna de sync del CSV se graba pero no se usa aca.

Uso
---
    python vivo.py
"""

import os
import re
import threading
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

import serial
from serial.tools import list_ports

from correccion_no_linealidad import (
    T_SWEEP, C, cargar_curva_vco, eje_theta, remuestrear,
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

N_DEFECTO = 8        # rampas promediadas por columna al arrancar
N_MAX     = 64
# Relleno de ceros de la FFT de cada rampa. NO agrega resolucion: el ancho de
# bin real vale c/(2*BW) = 14,4 cm y eso no lo cambia nada (ver GPRv2/
# CLAUDE.md). Lo que hace es interpolar, y sin el la rampa de 120 muestras da
# 61 bins para todo el eje - el radargrama sale en bandas gruesas y no se ve
# la forma de los picos. Es el mismo RELLENO de graficar_captura.py.
RELLENO   = 8
VENTANA_DEF = 20.0   # s de historia que se muestran
VENTANA_MAX = 120.0
ALCANCE_DEF = 5.0    # m, tope del eje de distancia
ALCANCE_MAX = 10.0
PISO_DEF  = -40.0    # dB respecto del pico en pantalla
TECHO_DEF = 0.0

AQUI    = os.path.dirname(os.path.abspath(__file__))
DATOS   = os.path.join(AQUI, "..", "datos")
SALIDA  = os.path.join(DATOS, "captura.csv")
SAL_TRI = os.path.join(DATOS, "triangular.csv")
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


# --- El radargrama ---------------------------------------------------------

class Vivo:

    def __init__(self, lector, curva):
        self.lec = lector
        self.curva = curva

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
        # decenas de MB cinco veces por segundo. Aca el agrupado trabaja sobre
        # una vista.
        self.P = self.tp = None
        self.n_perf = 0
        self.cap = 0

        self.n_rampas = N_DEFECTO
        self.ventana = VENTANA_DEF
        self.alcance = ALCANCE_DEF
        self.en_metros = True
        self.piso, self.techo = PISO_DEF, TECHO_DEF

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
        _, self.theta, alpha0 = eje_theta(self.curva, t)
        self.fs_th = fs_theta(self.theta, n)
        self.nfft = RELLENO * n
        self.ventana_fft = np.hanning(n)
        freqs = np.fft.rfftfreq(self.nfft, d=1.0 / self.fs_th)
        self.eje_hz = freqs
        self.eje_m = freqs * C / (2.0 * alpha0)
        # Capacidad del buffer de perfiles: lo que entra en la ventana mas
        # larga que el slider puede pedir, con margen.
        self.cap = int(VENTANA_MAX * 2 / self.T) + 200
        self.P = self.tp = None
        self.n_perf = 0

    def _guardar_perfil(self, esp, t):
        if self.P is None:
            self.P = np.empty((self.cap, len(esp)))
            self.tp = np.empty(self.cap)
        if self.n_perf == self.cap:
            # Se compacta a la mitad de una, no fila por fila: una copia cada
            # cap/2 perfiles en vez de una por perfil.
            mitad = self.cap // 2
            self.P[:mitad] = self.P[mitad:]
            self.tp[:mitad] = self.tp[mitad:]
            self.n_perf = mitad
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
            # no rellena y con 120 muestras por rampa deja 61 bins para todo
            # el eje. Los ejes en m y en Hz ya estan armados en _armar_ejes().
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
        """Agrupa los perfiles de a n_rampas y devuelve (matriz_db, t0, t1).

        El agrupado se rehace entero en cada refresco a partir de los perfiles
        de a UNA rampa, asi mover el slider de rampas/columna o el de ventana
        reagrupa todo lo que hay en pantalla en vez de valer solo de ahi en
        mas.
        """
        # Se puede llamar antes de la calibracion (la tecla 'a', por ejemplo),
        # y ahi todavia no hay ni periodo ni perfiles.
        if self.T is None or not self.n_perf:
            return None, 0, 0
        N = self.n_rampas
        # Cuantos perfiles entran en la ventana pedida. Es la ventana la que
        # manda: el numero de columnas sale de ella y de N, no al reves.
        caben = min(self.n_perf, int(round(self.ventana / (self.T / 2))))
        cols = caben // N
        if cols < 1:
            return None, 0, 0
        usadas = cols * N
        P = self.P[self.n_perf - usadas:self.n_perf]        # vista, no copia
        M = P.reshape(cols, N, P.shape[1]).mean(axis=1).T   # filas = rango
        db = 20 * np.log10(M / (M.max() + 1e-12) + 1e-12)
        return db, self.tp[self.n_perf - usadas], self.tp[self.n_perf - 1]

    # --- grafico ---

    def armar_figura(self):
        self.fig, self.ax = plt.subplots(figsize=(11, 7))
        self.fig.subplots_adjust(bottom=0.26, top=0.93)
        self.im = self.ax.imshow(np.zeros((2, 2)), origin="lower",
                                 aspect="auto", cmap="viridis",
                                 extent=(0, 1, 0, ALCANCE_DEF),
                                 vmin=self.piso, vmax=self.techo)
        self.ax.set_xlabel("Tiempo de captura [s]")
        self.fig.colorbar(self.im, ax=self.ax, label="Potencia relativa [dB]")
        self.txt = self.ax.text(0.5, 0.5, "esperando muestras...",
                                transform=self.ax.transAxes, ha="center",
                                va="center", fontsize=13, color="0.3")

        # Dos columnas de sliders: los tres que cambian QUE se mide a la
        # izquierda, los dos de escala de color a la derecha.
        izq = [self.fig.add_axes([0.14, y, 0.28, 0.03])
               for y in (0.145, 0.09, 0.035)]
        der = [self.fig.add_axes([0.63, y, 0.28, 0.03])
               for y in (0.145, 0.09)]
        self.s_n = Slider(izq[0], "rampas/col", 1, N_MAX,
                          valinit=self.n_rampas, valstep=1)
        self.s_vent = Slider(izq[1], "ventana [s]", 1.0, VENTANA_MAX,
                             valinit=self.ventana)
        self.s_alc = Slider(izq[2], "alcance [m]", 0.2, ALCANCE_MAX,
                            valinit=self.alcance)
        self.s_piso = Slider(der[0], "piso [dB]", -90.0, -5.0,
                             valinit=self.piso)
        self.s_techo = Slider(der[1], "techo [dB]", -60.0, 5.0,
                              valinit=self.techo)
        self.s_n.on_changed(self._cambio_medida)
        self.s_vent.on_changed(self._cambio_medida)
        self.s_alc.on_changed(self._cambio_alcance)
        self.s_piso.on_changed(self._cambio_color)
        self.s_techo.on_changed(self._cambio_color)
        self.fig.canvas.mpl_connect("key_press_event", self._tecla)
        self._poner_eje_y()

    def _cambio_medida(self, v):
        self.n_rampas = int(self.s_n.val)
        self.ventana = self.s_vent.val

    def _cambio_alcance(self, v):
        self.alcance = self.s_alc.val
        self._poner_eje_y()

    def _cambio_color(self, v):
        self.piso, self.techo = self.s_piso.val, self.s_techo.val

    def _tecla(self, ev):
        if ev.key in ("+", "="):
            self.s_n.set_val(min(N_MAX, self.n_rampas + 1))
        elif ev.key == "-":
            self.s_n.set_val(max(1, self.n_rampas - 1))
        elif ev.key == "e":
            self.en_metros = not self.en_metros
            self._poner_eje_y()
        elif ev.key == "a":
            db, _, _ = self.matriz()
            if db is not None:
                # El piso al percentil 60 y no al minimo: el minimo lo fija
                # un solo bin y deja casi todo el rango de color sin usar.
                self.s_piso.set_val(max(-90.0, float(np.percentile(db, 60))))
                self.s_techo.set_val(min(5.0, float(db.max())))

    def _poner_eje_y(self):
        if self.T is None:
            self.ax.set_ylabel("Distancia [m]")
            return
        eje = self.eje_m if self.en_metros else self.eje_hz
        # El slider de alcance esta siempre en metros, tambien cuando el eje
        # se muestra en Hz: es la misma escala con otra unidad, y asi la
        # posicion del slider quiere decir lo mismo en los dos modos.
        tope = (self.alcance if self.en_metros
                else self.alcance * self.eje_hz[-1] / self.eje_m[-1])
        x0, x1, _, _ = self.im.get_extent()
        self.im.set_extent((x0, x1, eje[0], eje[-1]))
        self.ax.set_ylim(0, min(tope, eje[-1]))
        self.ax.set_ylabel("Distancia [m]" if self.en_metros
                           else "Frecuencia de batido [Hz]")

    def actualizar(self, _=None):
        """Un refresco. Siempre termina pidiendo el redibujo.

        Sin el draw_idle() final la pantalla se queda congelada: mutar los
        artistas (set_data, set_title) NO repinta por si solo, y lo unico que
        forzaba el repaint era mover un slider. Se ve como que el programa
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
            self.txt.set_visible(False)
            self._poner_eje_y()
        elif ahora - self.t_ajuste > REAJUSTE_S:
            self.t_ajuste = ahora
            self.ajustar(primera_vez=False)

        self.procesar()
        db, ta, tb = self.matriz()
        if db is None:
            return
        if tb <= ta:
            tb = ta + 1e-3
        eje = self.eje_m if self.en_metros else self.eje_hz
        self.im.set_data(db)
        self.im.set_extent((ta, tb, eje[0], eje[-1]))
        lo, hi = min(self.piso, self.techo), max(self.piso, self.techo)
        self.im.set_clim(lo, hi if hi > lo else lo + 1.0)
        self.ax.set_xlim(ta, tb)
        self.ax.set_title(
            f"{ahora:.0f} s   |   {self.n_rampas} rampas/columna "
            f"({self.n_rampas*self.T/2*1e3:.0f} ms)   |   rampa {self.n} "
            f"muestras ({self.T/2*1e3:.2f} ms)   |   "
            f"{self.lec.descartadas} lineas cortadas")


def main():
    curva = cargar_curva_vco(VCO_CSV)
    os.makedirs(DATOS, exist_ok=True)
    ser = abrir_puerto()
    print(f"Grabando a {SALIDA} (y {SAL_TRI}). Sobrescribe lo anterior.")

    with open(SALIDA, "w", encoding="utf-8", newline="\n") as f_cap, \
         open(SAL_TRI, "w", encoding="utf-8", newline="\n") as f_tri:
        lec = Lector(ser, f_cap, f_tri)
        lec.start()
        vivo = Vivo(lec, curva)
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
