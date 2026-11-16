"""
GPRv3 - De donde salen los paquetes
===================================

Tres fuentes con la misma interfaz (`tomar()` devuelve lo que llego desde la
ultima vez): el puerto serie de la placa, una grabacion .gpr3 y el banco
sintetico. Las tres pasan por el mismo `Decodificador`, asi que lo que se
prueba sin hardware es el mismo camino que corre en el banco.
"""

import json
import os
import threading
import time

import config as cfg
import protocolo as pr


class Eventos:
    def __init__(self):
        self.muestras = []     # [(idx0, int32[])]
        self.flancos = []      # [(posicion, nivel, t_us)]
        self.info = None       # dict, si llego un paquete de informacion
        self.textos = []
        self.meta = None

    def agregar(self, tipo, carga):
        if tipo == pr.DATOS:
            self.muestras.append(pr.leer_datos(carga))
        elif tipo == pr.SYNC:
            self.flancos.append(pr.leer_sync(carga))
        elif tipo == pr.INFO:
            # Un paquete de informacion marca un arranque: lo anterior es de
            # otra corrida de la placa y no se mezcla.
            self.muestras, self.flancos = [], []
            self.info = pr.leer_info(carga)
        elif tipo == pr.TEXTO:
            self.textos.append(carga.decode("ascii", "replace"))
        elif tipo == pr.META:
            try:
                self.meta = json.loads(carga.decode("ascii"))
            except ValueError:
                pass


class Grabador:
    """Escribe los paquetes tal cual a datos/captura_<sello>.gpr3."""

    def __init__(self, meta, info_carga, carpeta=cfg.DATOS, sello=None):
        self.carpeta = carpeta
        self.sello = sello or time.strftime(cfg.FORMATO_SELLO)
        self.meta = dict(meta)
        self.info_carga = info_carga
        self.parte = 0
        self.total = 0
        self.f = None
        self._abrir()

    def _abrir(self):
        if self.f:
            self.f.close()
        self.parte += 1
        sufijo = "" if self.parte == 1 else f"_parte{self.parte}"
        os.makedirs(self.carpeta, exist_ok=True)
        self.ruta = os.path.join(self.carpeta,
                                 f"captura_{self.sello}{sufijo}.gpr3")
        self.f = open(self.ruta, "wb")
        self.bytes = 0
        self.meta["parte"] = self.parte
        self._escribir(pr.meta(self.meta))
        if self.info_carga:
            self._escribir(pr.armar(pr.INFO, self.info_carga))

    def _escribir(self, b):
        self.f.write(b)
        self.bytes += len(b)
        self.total += len(b)

    def escribir(self, paquetes):
        for tipo, carga in paquetes:
            if tipo == pr.INFO:
                self.info_carga = carga
            if tipo != pr.META:
                self._escribir(pr.armar(tipo, carga))
        if self.bytes >= cfg.LIMITE_PARTE_MB * 1_000_000:
            self._abrir()

    def cerrar(self):
        if self.f:
            self.f.close()
            self.f = None


class Fuente(threading.Thread):

    en_vivo = True       # False: se puede leer entera de una (un archivo)
    nombre = "?"

    def __init__(self):
        super().__init__(daemon=True)
        self.dec = pr.Decodificador()
        self.lock = threading.Lock()
        self._ev = Eventos()
        self.info = None
        self.info_carga = None
        self.estado = {}
        self.grabador = None
        self.parar = False
        self.error = None
        self.t_ultimo = time.monotonic()

    def _entra(self, datos):
        self._despachar(self.dec.alimentar(datos))

    def _despachar(self, paquetes):
        if not paquetes:
            return
        self.t_ultimo = time.monotonic()
        with self.lock:
            for tipo, carga in paquetes:
                if tipo == pr.ESTADO:
                    self.estado = pr.leer_estado(carga)
                else:
                    self._ev.agregar(tipo, carga)
                    if tipo == pr.INFO:
                        self.info = self._ev.info
                        self.info_carga = carga
        g = self.grabador
        if g is not None:
            try:
                g.escribir(paquetes)
            except (OSError, ValueError) as e:   # ValueError: lo cerraron
                if self.grabador is g:
                    self.error = f"no pude grabar: {e}"
                    self.grabador = None

    def tomar(self):
        with self.lock:
            ev, self._ev = self._ev, Eventos()
        return ev

    def arrancar(self, sps):
        pass

    def cerrar(self):
        self.parar = True
        if self.is_alive():
            self.join(timeout=1.0)
        if self.grabador:
            self.grabador.cerrar()


# --- La placa ---------------------------------------------------------------

def buscar_puerto():
    from serial.tools import list_ports
    if cfg.PUERTO != "auto":
        return cfg.PUERTO
    cand = [p for p in list_ports.comports() if p.vid == cfg.VID_ESPRESSIF]
    if len(cand) != 1:
        lista = "".join(f"\n    {p.device} - {p.description}" for p in cand)
        raise SystemExit(
            "No encontre exactamente un ESP32 (esta enchufado? el Monitor "
            "Serie del IDE tiene que estar cerrado). Si no, pone el puerto a "
            "mano en PUERTO, en config.py." + lista)
    return cand[0].device


class FuenteSerie(Fuente):

    def __init__(self, sps=cfg.SPS_DEF):
        super().__init__()
        import serial
        puerto = buscar_puerto()
        self.nombre = puerto
        # DTR y RTS en bajo ANTES de abrir: pyserial los afirma por defecto
        # y en el USB nativo del C3 esa combinacion reinicia la placa.
        self.ser = serial.Serial()
        self.ser.port = puerto
        self.ser.baudrate = cfg.BAUD
        self.ser.timeout = 0.05
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.arrancar(sps)

    def arrancar(self, sps):
        """Para, fija los sps y vuelve a arrancar. Lo que la placa conteste
        en texto mientras tanto lo saltea el decodificador; el paquete de
        informacion que manda 'run' avisa que empezo una corrida nueva."""
        self.ser.write(b"stop\n")
        time.sleep(0.1)
        self.ser.write(f"sps {int(sps)}\n".encode())
        time.sleep(0.5)          # el I2S se reinicia y calienta el PCM1808
        self.ser.write(b"run\n")

    def run(self):
        while not self.parar:
            try:
                datos = self.ser.read(max(1, self.ser.in_waiting))
            except Exception as e:
                self.error = f"se corto el puerto: {e}"
                break
            if datos:
                self._entra(datos)

    def cerrar(self):
        super().cerrar()
        try:
            self.ser.write(b"stop\n")
            self.ser.close()
        except Exception:
            pass


# --- Una grabacion ----------------------------------------------------------

def leer_paquetes(ruta):
    with open(ruta, "rb") as f:
        return pr.Decodificador().alimentar(f.read())


def leer_grabacion(ruta):
    """Toda la grabacion de una vez, como Eventos."""
    ev = Eventos()
    for tipo, carga in leer_paquetes(ruta):
        if tipo == pr.INFO and ev.info is not None:
            continue             # el de cada parte, no un arranque nuevo
        if tipo != pr.ESTADO:
            ev.agregar(tipo, carga)
    return ev


class FuenteArchivo(Fuente):
    """Reproduce una grabacion al ritmo en que se tomo."""

    def __init__(self, ruta, velocidad=1.0):
        super().__init__()
        self.nombre = os.path.basename(ruta)
        self.paquetes = leer_paquetes(ruta)
        self.velocidad = velocidad
        self.sps = cfg.SPS_DEF
        for tipo, carga in self.paquetes:
            if tipo == pr.INFO:
                self.sps = pr.leer_info(carga)["sps"]
                break

    def run(self):
        t0 = time.monotonic()
        emitidas = 0
        lote = []
        for tipo, carga in self.paquetes:
            if self.parar:
                return
            lote.append((tipo, carga))
            if tipo != pr.DATOS:
                continue
            emitidas += (len(carga) - 4) // 3
            falta = emitidas / (self.sps * self.velocidad) - (time.monotonic() - t0)
            if falta > 0.02:
                self._despachar(lote)
                lote = []
                time.sleep(falta)
        self._despachar(lote)
        self.error = "termino la grabacion"


# --- El banco sintetico -----------------------------------------------------

class FuenteSintetica(Fuente):

    nombre = "sintetico"

    def __init__(self, curva, banco=None, sps=cfg.SPS_DEF):
        super().__init__()
        import sintetico
        self._sint = sintetico
        self.curva = curva
        self.banco = banco or sintetico.Banco()
        self.banco.sps = sps
        self._nuevo = True

    def arrancar(self, sps):
        self.banco.sps = int(sps)
        self._nuevo = True

    def run(self):
        s = self._sint
        while not self.parar:
            if self._nuevo:
                self._nuevo = False
                gen = s.Generador(self.banco, self.curva)
                t0 = time.monotonic()
                hechos = 0
            debidos = int((time.monotonic() - t0) * s.FS / s.BLOQUE)
            n = min(debidos - hechos, 200)
            if n > 0:
                self._entra(gen.bloques(n))
                hechos = debidos
            time.sleep(0.03)
