"""
GPRv3 - Paquetes entre el ESP32 y la PC
=======================================

    A5 5A | tipo (1) | largo (2, LE) | carga | crc16 (2, LE)

El CRC es CRC-16/CCITT-FALSE sobre tipo + largo + carga. El lado del firmware
esta en firmware/adquisicion_sync/nucleo.h; `verificar.py` comprueba que los
dos coinciden. Las grabaciones (.gpr3) son estos mismos paquetes, uno atras
del otro, mas un paquete 'M' con metadatos que solo escribe la PC.
"""

import json
import struct
from binascii import crc_hqx

import numpy as np

MAGIA = b"\xA5\x5A"
VERSION = 1
DATOS, SYNC, INFO, ESTADO, TEXTO, META = b"D", b"S", b"I", b"E", b"T", b"M"
CARGA_MAX = 8192          # el firmware no pasa de 480; 'M' puede ser mas largo


# --- Armado ----------------------------------------------------------------

def armar(tipo, carga):
    cuerpo = tipo + struct.pack("<H", len(carga)) + carga
    return MAGIA + cuerpo + struct.pack("<H", crc_hqx(cuerpo, 0xFFFF))


def datos(idx0, muestras):
    m = np.clip(np.asarray(muestras, dtype=np.int64), -8388608, 8388607)
    tres = (m.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3]).tobytes()
    return armar(DATOS, struct.pack("<I", idx0 & 0xFFFFFFFF) + tres)


def sync(idx256, nivel, t_us=0):
    return armar(SYNC, struct.pack("<IBBI", (idx256 >> 8) & 0xFFFFFFFF,
                                   idx256 & 0xFF, nivel, t_us & 0xFFFFFFFF))


def info(fs, dec, pin=10, bloque=256):
    return armar(INFO, struct.pack("<BIHBH", VERSION, fs, dec, pin, bloque))


def estado(desbordes=0, descartados=0, flancos=0, errores=0):
    return armar(ESTADO, struct.pack("<IIII", desbordes, descartados,
                                     flancos, errores))


def texto(s):
    return armar(TEXTO, s.encode("ascii", "replace"))


def meta(d):
    return armar(META, json.dumps(d, ensure_ascii=True).encode("ascii"))


# --- Lectura ---------------------------------------------------------------

def leer_datos(carga):
    """(idx0, muestras int32) de la carga de un paquete de datos."""
    idx0 = int.from_bytes(carga[:4], "little")
    a = np.frombuffer(carga, dtype=np.uint8, offset=4)
    a = a[:len(a) // 3 * 3].reshape(-1, 3)
    v = (a[:, 0].astype(np.int32) | (a[:, 1].astype(np.int32) << 8)
         | (a[:, 2].astype(np.int8).astype(np.int32) << 16))
    return idx0, v


def leer_sync(carga):
    """(posicion en muestras, con fraccion; nivel; t_us)."""
    idx, frac, nivel, t_us = struct.unpack("<IBBI", carga[:10])
    return idx + frac / 256.0, nivel, t_us


def leer_info(carga):
    version, fs, dec, pin, bloque = struct.unpack("<BIHBH", carga[:10])
    return {"version": version, "fs": fs, "dec": dec, "sps": fs // dec,
            "pin_sync": pin, "bloque": bloque}


def leer_estado(carga):
    d, x, f, e = struct.unpack("<IIII", carga[:16])
    return {"desbordes": d, "descartados": x, "flancos": f, "errores": e}


class Decodificador:
    """
    Saca paquetes validos de un chorro de bytes. Se engancha solo: lo que no
    sea un paquete con su CRC bien (texto del arranque de la placa, un
    paquete cortado) se saltea y se cuenta en `basura`.
    """

    def __init__(self):
        self._buf = bytearray()
        self.paquetes = 0
        self.basura = 0            # bytes salteados
        self.crc_malos = 0
        self.ultima_basura = bytearray()   # para poder mostrar que era

    def _tirar(self, trozo):
        self.basura += len(trozo)
        self.ultima_basura += trozo
        del self.ultima_basura[:-200]

    def alimentar(self, nuevos):
        """Devuelve la lista de (tipo, carga) completos que haya."""
        buf = self._buf
        buf += nuevos
        n = len(buf)
        i = 0
        salida = []
        while True:
            j = buf.find(MAGIA, i)
            if j < 0:
                # Puede haber quedado la primera mitad de la magia al final.
                j = n - 1 if n > i and buf[n - 1] == MAGIA[0] else n
                if j > i:
                    self._tirar(buf[i:j])
                i = j
                break
            if j > i:
                self._tirar(buf[i:j])
            i = j
            if n - j < 5:
                break
            largo = buf[j + 3] | (buf[j + 4] << 8)
            fin = j + 5 + largo + 2
            if largo > CARGA_MAX:
                self._tirar(buf[j:j + 1])
                i = j + 1
                continue
            if fin > n:
                break
            crc = buf[fin - 2] | (buf[fin - 1] << 8)
            if crc_hqx(bytes(buf[j + 2:fin - 2]), 0xFFFF) != crc:
                self.crc_malos += 1
                self._tirar(buf[j:j + 1])
                i = j + 1
                continue
            salida.append((bytes(buf[j + 2:j + 3]), bytes(buf[j + 5:fin - 2])))
            i = fin
        del buf[:i]
        self.paquetes += len(salida)
        return salida
