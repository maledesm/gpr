"""
Protocolo binario del firmware PCM1808_ESP32C3.

Trama:
    [0xA5 0x5A] [idx:uint32] [n:uint16] [flags:uint8] [n x float32] [crc16]
         2           4           2          1            4*n           2

    idx    indice ABSOLUTO de la primera muestra del paquete, contado desde el
           inicio de la captura. No es un contador de paquetes: avanza con el
           tiempo real, tambien durante las pausas del modo rafaga. Gracias a
           eso los huecos son explicitos y se puede distinguir una pausa
           esperada de una perdida del DMA.
    flags  bit0 = primer paquete de una rafaga
    datos  float32 little-endian, en VOLTS
    crc16  CCITT-FALSE (poly 0x1021, init 0xFFFF) sobre idx..datos

Autoprueba, sin hardware:

    python protocolo.py --test
"""

import struct
import sys
import time
from typing import NamedTuple, Optional

import numpy as np

# Dos formatos de trama conviven a proposito.
#
#   v1  0xA5 0x5A  magic(2) + idx(4) + n(2) + flags(1)                    = 9
#   v2  0xA5 0x5B  magic(2) + idx(4) + n(2) + flags(1) + rampa(4)         = 13
#
# El v2 lo emite gpr_barrido, que ademas de las muestras manda en que barrido
# van: cada trama pertenece a UNA sola rampa y la que la inaugura viene con
# FLAG_VERTICE. O sea que la segmentacion en barridos llega hecha desde el
# firmware y no hay que buscarla en la senal.
#
# El preambulo distinto no es capricho: si el firmware nuevo hablara con un
# decodificador viejo, este no sincronizaria y fallaria limpio, en vez de leer
# los campos corridos y entregar datos plausibles pero equivocados.
MAGIC_V1 = b"\xA5\x5A"
MAGIC_V2 = b"\xA5\x5B"
CAB_V1 = 9
CAB_V2 = 13

MAGIC = MAGIC_V1        # compatibilidad con codigo que lo importaba
CAB = CAB_V1

MAX_MUESTRAS = 4096     # cota de sanidad: descarta cabeceras absurdas

VID_ESPRESSIF = 0x303A  # USB Serial/JTAG del ESP32-C3

FLAG_INICIO_RAFAGA = 0x01   # v1: arranque de rafaga  ·  v2: primera trama
FLAG_OVF_DMA       = 0x02   # v2: hubo desborde del DMA del I2S
FLAG_BAJADA        = 0x04   # v2: la rampa de esta trama es descendente
FLAG_VERTICE       = 0x08   # v2: esta trama inaugura un barrido
FLAG_OVF_RING      = 0x10   # v2: el firmware no vacio su buffer a tiempo


class Paquete(NamedTuple):
    idx: int
    flags: int
    datos: np.ndarray
    rampa: Optional[int]    # numero de barrido; None en v1
    version: int            # 1 o 2


# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------

def _tabla_crc16():
    """CRC-16/CCITT-FALSE por tabla. El firmware lo hace bit a bit; en Python
    eso seria carisimo, asi que aca se precalcula una tabla de 256 entradas."""
    tabla = []
    for b in range(256):
        crc = b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        tabla.append(crc)
    return tabla


_CRC_TABLA = _tabla_crc16()


def crc16(datos: bytes) -> int:
    crc = 0xFFFF
    for byte in datos:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLA[((crc >> 8) ^ byte) & 0xFF]
    return crc


# ---------------------------------------------------------------------------
# Decodificador
# ---------------------------------------------------------------------------

class Decodificador:
    """Convierte un flujo de bytes en paquetes.

    Se le van pasando trozos de lo que llega del puerto con alimentar(), sin
    importar como caigan los cortes: un paquete puede venir partido en varias
    lecturas, o pueden llegar varios juntos.

    Ante bytes corruptos resincroniza buscando el preambulo. Un CRC malo hace
    que se descarte el paquete y se siga buscando desde el byte siguiente al
    preambulo, no desde el final del paquete: si el campo 'n' vino corrupto,
    saltar 'n' muestras nos dejaria en cualquier lado.
    """

    def __init__(self):
        self.buf = bytearray()
        self.paquetes_ok = 0
        self.paquetes_crc = 0     # descartados por CRC
        self.bytes_basura = 0     # descartados buscando sincronismo
        self.muestras = 0

    def _hallar(self):
        """Posicion del proximo preambulo y su version.

        Devuelve (-1, 0) si no hay ninguno, y (pos, 0) cuando el buffer termina
        justo en un 0xA5 suelto: ahi todavia no se sabe la version y hay que
        esperar el byte siguiente en vez de tirarlo.
        """
        i = 0
        while True:
            i = self.buf.find(0xA5, i)
            if i < 0:
                return -1, 0
            if i + 1 >= len(self.buf):
                return i, 0
            b = self.buf[i + 1]
            if b == 0x5A:
                return i, 1
            if b == 0x5B:
                return i, 2
            i += 1

    def alimentar(self, datos: bytes):
        """Agrega bytes y devuelve los Paquete completos que se hayan armado."""
        self.buf.extend(datos)
        salida = []

        while True:
            i, ver = self._hallar()
            if i < 0:
                # Sin preambulo a la vista. Se conserva el ultimo byte por si
                # es la primera mitad de un preambulo partido entre lecturas.
                if len(self.buf) > 1:
                    self.bytes_basura += len(self.buf) - 1
                    del self.buf[:-1]
                break

            if i > 0:
                self.bytes_basura += i
                del self.buf[:i]

            if ver == 0:
                break                                  # falta el segundo byte

            cab = CAB_V1 if ver == 1 else CAB_V2
            if len(self.buf) < cab:
                break                                  # falta cabecera

            idx, n, flags = struct.unpack_from("<IHB", self.buf, 2)
            rampa = struct.unpack_from("<I", self.buf, 9)[0] if ver == 2 else None

            if n == 0 or n > MAX_MUESTRAS:
                del self.buf[:2]                       # preambulo falso
                self.bytes_basura += 2
                continue

            total = cab + 4 * n + 2
            if len(self.buf) < total:
                break                                  # falta cuerpo

            cuerpo = bytes(self.buf[2:cab + 4 * n])
            crc_rx = struct.unpack_from("<H", self.buf, cab + 4 * n)[0]

            if crc16(cuerpo) != crc_rx:
                self.paquetes_crc += 1
                del self.buf[:2]
                continue

            datos_np = np.frombuffer(bytes(self.buf[cab:cab + 4 * n]), dtype="<f4")
            salida.append(Paquete(idx, flags, datos_np, rampa, ver))
            self.paquetes_ok += 1
            self.muestras += n
            del self.buf[:total]

        return salida


class Continuidad:
    """Verifica que los indices sean consecutivos.

    Distingue dos casos que se ven igual en el flujo pero significan cosas
    opuestas:
      - hueco con FLAG_INICIO_RAFAGA -> pausa configurada, es esperado
      - hueco sin ese flag           -> el DMA desbordo, se perdieron muestras

    El segundo es el modo de falla peligroso: corrompe la fase de la FFT sin
    dar ninguna senal visible en los datos.
    """

    def __init__(self):
        self.siguiente = None
        self.perdidas = 0        # muestras perdidas de verdad
        self.pausas = 0          # muestras salteadas por rafaga (esperado)
        self.eventos = 0         # cantidad de perdidas distintas

    def revisar(self, idx: int, flags: int, n: int) -> int:
        """Devuelve cuantas muestras faltan antes de este paquete."""
        faltan = 0
        if self.siguiente is not None and idx != self.siguiente:
            faltan = idx - self.siguiente
            if faltan < 0:
                faltan = 0                    # reinicio de captura
            elif flags & FLAG_INICIO_RAFAGA:
                self.pausas += faltan
            else:
                self.perdidas += faltan
                self.eventos += 1
        self.siguiente = idx + n
        return faltan


# ---------------------------------------------------------------------------
# Puerto serie
# ---------------------------------------------------------------------------

def autodetectar_puerto():
    """Busca el ESP32-C3 por VID de Espressif. Devuelve el nombre o None."""
    from serial.tools import list_ports
    candidatos = [p for p in list_ports.comports() if p.vid == VID_ESPRESSIF]
    if len(candidatos) == 1:
        return candidatos[0].device
    if len(candidatos) > 1:
        print("Hay varios ESP32 conectados:")
        for p in candidatos:
            print("   ", p.device, "-", p.description)
    return None


def leer_hasta_silencio(ser, silencio=0.35, limite=4.0) -> str:
    """Lee texto hasta que el firmware deja de hablar.

    No se puede esperar un terminador concreto porque las respuestas varian en
    largo (info son 25 lineas, un [OK] es una). Se lee hasta que pasa
    'silencio' sin recibir nada.
    """
    t0 = time.time()
    ultimo = time.time()
    out = bytearray()
    while time.time() - t0 < limite:
        n = ser.in_waiting
        if n:
            out.extend(ser.read(n))
            ultimo = time.time()
        elif time.time() - ultimo > silencio:
            break
        else:
            time.sleep(0.01)
    return out.decode("ascii", errors="replace")


def comando(ser, texto, espera=0.35):
    """Manda un comando de texto y devuelve lo que conteste."""
    ser.reset_input_buffer()
    ser.write((texto + "\n").encode("ascii"))
    ser.flush()
    return leer_hasta_silencio(ser, silencio=espera)


def configurar(ser, fs, dec, raf_on=0, raf_off=0, canal="l"):
    """Deja el firmware listo y devuelve el volcado de 'info'.

    El orden importa: primero salir de cualquier modo grafico (donde el
    firmware silencia las respuestas), despues configurar, y recien al final
    pedir info. Lo que devuelve info es lo que se escribe en la metadata: asi
    queda registrado lo que el firmware REALMENTE tiene, no lo que creiamos
    haberle mandado.
    """
    comando(ser, "off")
    comando(ser, f"fs {int(fs)}")
    comando(ser, f"dec {int(dec)}")
    comando(ser, f"ch {canal}")
    comando(ser, f"raf {int(raf_on)} {int(raf_off)}")
    return comando(ser, "info", espera=0.6)


# ---------------------------------------------------------------------------
# Autoprueba
# ---------------------------------------------------------------------------

def _armar(idx, muestras, flags=0):
    n = len(muestras)
    cuerpo = struct.pack("<IHB", idx, n, flags) + np.asarray(muestras, dtype="<f4").tobytes()
    return MAGIC_V1 + cuerpo + struct.pack("<H", crc16(cuerpo))


def _armar2(idx, muestras, flags=0, rampa=0):
    n = len(muestras)
    cuerpo = (struct.pack("<IHBI", idx, n, flags, rampa)
              + np.asarray(muestras, dtype="<f4").tobytes())
    return MAGIC_V2 + cuerpo + struct.pack("<H", crc16(cuerpo))


def autoprueba():
    print("Autoprueba del decodificador (sin hardware)")
    print("=" * 58)
    fallos = 0

    def chequear(nombre, ok, detalle=""):
        nonlocal fallos
        print(f"  [{'OK ' if ok else 'MAL'}] {nombre}" + (f"  {detalle}" if detalle else ""))
        if not ok:
            fallos += 1

    # 0. Valor conocido de la norma.
    #    Es el unico test que ancla el algoritmo a algo externo. Los demas
    #    generan las tramas con este mismo crc16 y despues las verifican con
    #    el, asi que validan el decodificador contra si mismo y NO podrian
    #    detectar que el firmware calcula otra cosa. Este si.
    chequear("CRC de la norma (CCITT-FALSE)", crc16(b"123456789") == 0x29B1,
             f"crc16('123456789') = {crc16(b'123456789'):#06x}, norma = 0x29b1")

    # 1. Ida y vuelta simple
    d = Decodificador()
    origen = np.arange(256, dtype="<f4") * 0.001
    paq = d.alimentar(_armar(0, origen))
    chequear("paquete simple", len(paq) == 1 and np.array_equal(paq[0][2], origen))

    # 2. Partido byte a byte: el caso real, porque el puerto entrega trozos
    #    arbitrarios y un paquete casi nunca cae entero en una lectura.
    d = Decodificador()
    crudo = _armar(100, origen)
    recibidos = []
    for b in range(len(crudo)):
        recibidos += d.alimentar(crudo[b:b + 1])
    chequear("partido byte a byte", len(recibidos) == 1 and recibidos[0][0] == 100)

    # 3. Varios paquetes en una sola entrega
    d = Decodificador()
    juntos = b"".join(_armar(i * 256, origen) for i in range(4))
    paq = d.alimentar(juntos)
    chequear("cuatro paquetes juntos", len(paq) == 4,
             f"idx={[p[0] for p in paq]}")

    # 4. Basura antes del preambulo
    d = Decodificador()
    paq = d.alimentar(b"\x00\xFF basura suelta " + _armar(7, origen))
    chequear("resincroniza tras basura", len(paq) == 1 and d.bytes_basura > 0,
             f"{d.bytes_basura} bytes descartados")

    # 5. CRC corrupto: se descarta y se sigue con el proximo
    d = Decodificador()
    malo = bytearray(_armar(0, origen))
    malo[CAB + 4] ^= 0xFF                       # corromper un dato
    paq = d.alimentar(bytes(malo) + _armar(256, origen))
    chequear("descarta CRC malo y sigue",
             len(paq) == 1 and paq[0][0] == 256 and d.paquetes_crc == 1)

    # 6. Cabecera absurda: 'n' enorme no debe colgar ni reservar memoria
    d = Decodificador()
    paq = d.alimentar(MAGIC + struct.pack("<IHB", 0, 60000, 0) + _armar(5, origen))
    chequear("rechaza n fuera de rango", len(paq) == 1 and paq[0][0] == 5)

    # 7. Continuidad: distingue pausa de perdida
    c = Continuidad()
    c.revisar(0, FLAG_INICIO_RAFAGA, 256)
    c.revisar(256, 0, 256)
    c.revisar(1024, FLAG_INICIO_RAFAGA, 256)    # hueco esperado (rafaga)
    c.revisar(2048, 0, 256)                     # hueco NO esperado (perdida)
    chequear("separa pausa de perdida",
             c.pausas == 512 and c.perdidas == 768 and c.eventos == 1,
             f"pausas={c.pausas} perdidas={c.perdidas}")

    # 8. El CRC detecta un bit dado vuelta en cualquier posicion
    base = _armar(0, origen[:8])
    cuerpo = base[2:-2]
    esperado = crc16(cuerpo)
    detectados = 0
    for bit in range(0, len(cuerpo) * 8, 7):
        mutado = bytearray(cuerpo)
        mutado[bit // 8] ^= 1 << (bit % 8)
        if crc16(bytes(mutado)) != esperado:
            detectados += 1
    total = len(range(0, len(cuerpo) * 8, 7))
    chequear("CRC detecta bit flips", detectados == total, f"{detectados}/{total}")

    # 9. Trama v2: ademas de las muestras trae el numero de barrido
    d = Decodificador()
    paq = d.alimentar(_armar2(0, origen, flags=FLAG_VERTICE, rampa=42))
    ok = (len(paq) == 1 and paq[0].version == 2 and paq[0].rampa == 42
          and paq[0].flags & FLAG_VERTICE and np.array_equal(paq[0].datos, origen))
    chequear("trama v2 con numero de barrido", ok,
             f"rampa={paq[0].rampa if paq else None}")

    # 10. Los dos formatos en el mismo flujo. No es hipotetico: conviven
    #     mientras haya capturas viejas y firmware nuevo.
    d = Decodificador()
    paq = d.alimentar(_armar(0, origen) + _armar2(256, origen, rampa=1)
                      + _armar(512, origen))
    chequear("v1 y v2 mezclados", [p.version for p in paq] == [1, 2, 1],
             f"versiones={[p.version for p in paq]}, rampas={[p.rampa for p in paq]}")

    # 11. Partido justo entre los dos bytes del preambulo. Es el caso que
    #     rompe si al no reconocer la version se tira el 0xA5 suelto.
    d = Decodificador()
    crudo = _armar2(9, origen, rampa=3)
    recibidos = d.alimentar(crudo[:1])          # solo el 0xA5
    recibidos += d.alimentar(crudo[1:])
    chequear("preambulo v2 partido al medio",
             len(recibidos) == 1 and recibidos[0].rampa == 3 and d.bytes_basura == 0,
             f"basura={d.bytes_basura}")

    # 12. Sentido de la rampa
    d = Decodificador()
    paq = d.alimentar(_armar2(0, origen, flags=FLAG_VERTICE | FLAG_BAJADA, rampa=7)
                      + _armar2(256, origen, flags=0, rampa=7))
    chequear("marca de bajada y continuacion de barrido",
             len(paq) == 2
             and bool(paq[0].flags & FLAG_BAJADA)
             and bool(paq[0].flags & FLAG_VERTICE)
             and not (paq[1].flags & FLAG_VERTICE)
             and paq[1].rampa == 7)

    print("=" * 58)
    print("TODO OK" if fallos == 0 else f"{fallos} PRUEBA(S) FALLARON")
    return fallos


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(1 if autoprueba() else 0)
    print(__doc__)
    print("\nPuertos con VID de Espressif:", autodetectar_puerto() or "ninguno")
