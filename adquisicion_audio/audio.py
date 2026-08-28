"""
Capa de hardware de audio: encontrar la placa, abrir el stream, escribir el WAV.

Es el equivalente de protocolo.py pero del lado de la UMC22. La idea es la
misma: que grabaraudio.py se ocupe de la logica de la medicion y no sepa nada
de PortAudio ni de formatos de archivo.

sounddevice se importa ADENTRO de las funciones a proposito. Asi este modulo y
su autoprueba corren tambien en la maquina de analisis, donde no hay placa de
sonido ni PortAudio instalado.

Autoprueba (no necesita la placa enchufada):
    python audio.py --test

Listado de dispositivos (si necesita PortAudio):
    python audio.py --listar
"""

import os
import sys
import wave

import numpy as np


# Trozos de nombre por los que se reconoce la placa. Windows la enumera
# distinto segun el driver: con el generico de clase USB aparece como
# "Microfono (2- USB Audio CODEC)" y con el de Behringer como "UMC ASIO
# Driver", asi que hay que buscar por varios lados.
PISTAS_PLACA = ("umc", "u-phoria", "uphoria", "behringer", "usb audio codec")

# Orden de preferencia de la API de audio. No es cosmetico:
#   ASIO    va derecho al driver de la placa, sin mezclador de por medio.
#   WASAPI  admite modo EXCLUSIVO, que tambien saltea el mezclador.
#   WDM-KS  streaming de kernel, tambien directo, pero mas fragil.
#   Las ultimas dos pasan SIEMPRE por el mezclador de Windows, que puede
#           reamostrear en silencio y aplicar "mejoras" (AGC, supresion de
#           ruido) sin avisar. Para una medicion eso es veneno.
PREFERENCIA_API = ("ASIO", "Windows WASAPI", "Windows WDM-KS",
                   "Windows DirectSound", "MME")

# Fondo de escala de un int16. La UMC22 convierte a 16 bits, asi que pedirle
# int16 a PortAudio no pierde nada y ademas evita una conversion de formato de
# mas adentro de la libreria.
FONDO_ESCALA = 32768.0


class Entrada:
    """Un dispositivo de entrada ya resuelto a (indice, API, canales)."""

    def __init__(self, idx, nombre, api, canales, fs_nominal):
        self.idx = idx
        self.nombre = nombre
        self.api = api
        self.canales = canales
        self.fs_nominal = fs_nominal

    @property
    def es_placa(self):
        n = self.nombre.lower()
        return any(p in n for p in PISTAS_PLACA)

    def __str__(self):
        marca = "  <- placa de audio" if self.es_placa else ""
        return (f"[{self.idx:3d}] {self.nombre[:42]:42s} {self.api[:18]:18s} "
                f"{self.canales} ch  {self.fs_nominal:6.0f} Hz{marca}")


def listar():
    """Todos los dispositivos que tienen al menos un canal de entrada."""
    import sounddevice as sd

    apis = [a["name"] for a in sd.query_hostapis()]
    salida = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        salida.append(Entrada(i, d["name"], apis[d["hostapi"]],
                              d["max_input_channels"], d["default_samplerate"]))
    return salida


def tabla():
    """Listado imprimible de las entradas disponibles."""
    lineas = [str(e) for e in listar()]
    if not lineas:
        return "  (no hay ningun dispositivo de entrada)"
    return "\n".join("  " + l for l in lineas)


def _puntaje_api(nombre_api):
    """Menor es mejor. Las APIs desconocidas van al final."""
    for k, p in enumerate(PREFERENCIA_API):
        if p.lower() in nombre_api.lower():
            return k
    return len(PREFERENCIA_API)


def elegir(pedido="auto", n_canales=1):
    """Resuelve lo que pidio el usuario a un dispositivo concreto.

    'pedido' puede ser:
      'auto'      buscar la placa por nombre y quedarse con la mejor API
      un numero   indice de PortAudio, tal cual lo lista --listar
      un texto    parte del nombre del dispositivo

    'n_canales' es cuantos canales hacen falta. Importa porque Windows enumera
    el MISMO dispositivo una vez por API y no todas ofrecen lo mismo: con la
    UMC22 y el driver generico, WASAPI aparecia con 1 solo canal (el formato
    compartido estaba en mono) mientras WDM-KS ofrecia los 2. Sin esto, la
    preferencia de API ganaba y se elegia una entrada que no alcanzaba.

    Devuelve una Entrada, o None si no encontro nada.
    """
    entradas = listar()
    if not entradas:
        return None

    pedido = str(pedido).strip()

    if pedido.lstrip("-").isdigit():
        idx = int(pedido)
        for e in entradas:
            if e.idx == idx:
                return e
        return None

    if pedido.lower() == "auto":
        candidatos = [e for e in entradas if e.es_placa]
    else:
        candidatos = [e for e in entradas if pedido.lower() in e.nombre.lower()]

    if not candidatos:
        return None

    # Primero se descarta lo que no alcanza, DESPUES se prefiere la API. Al
    # reves, una entrada mono con la API mas directa le ganaba a una estereo con
    # una API peor, y el stream ni abria.
    candidatos.sort(key=lambda e: (0 if e.canales >= n_canales else 1,
                                   _puntaje_api(e.api), -e.canales))
    return candidatos[0]


def ajustes_exclusivos(entrada):
    """Extra settings para pedir modo exclusivo, si la API lo soporta.

    Solo WASAPI tiene el concepto. En ASIO el acceso ya es exclusivo por
    naturaleza, y en MME/DirectSound no existe: ahi devuelve None y el stream se
    abre compartido, pasando por el mezclador de Windows.
    """
    import sounddevice as sd

    if "wasapi" in entrada.api.lower():
        return sd.WasapiSettings(exclusive=True)
    return None


class EscritorWav:
    """WAV PCM de 16 bits que se escribe incrementalmente.

    Se usa el modulo 'wave' de la biblioteca estandar y no soundfile para no
    sumar una dependencia que no hace falta. El detalle que importa:
    writeframes() reescribe el tamano en la cabecera en CADA llamada, asi que si
    el programa se corta a la mitad el archivo que quedo en disco sigue siendo un
    WAV valido. Es la misma politica que el CSV de grabarserial.py: lo grabado no
    se pierde.

    Ojo: eso vale para el archivo EN DISCO, y el buffer de Python se interpone.
    El archivo se abre aca (en vez de dejar que lo abra 'wave') justamente para
    quedarse con el descriptor y poder hacer flush+fsync desde sincronizar().
    Sin eso, un Ctrl+C dejaba un WAV de cero bytes: verificado en la autoprueba.
    """

    def __init__(self, ruta, canales, fs):
        self.ruta = ruta
        self.canales = canales
        self.fs = fs
        self.cuadros = 0
        self._f = open(ruta, "wb")
        self._w = wave.open(self._f, "wb")
        self._w.setnchannels(canales)
        self._w.setsampwidth(2)
        self._w.setframerate(int(round(fs)))

    def escribir(self, bloque):
        """bloque: array int16 de forma (cuadros, canales)."""
        if bloque.dtype != np.int16:
            raise TypeError(f"el WAV espera int16, llego {bloque.dtype}")
        if bloque.ndim != 2 or bloque.shape[1] != self.canales:
            raise ValueError(f"forma {bloque.shape}, esperaba (n, {self.canales})")
        self._w.writeframes(bloque.tobytes())
        self.cuadros += bloque.shape[0]

    def sincronizar(self):
        """Baja a disco lo escrito hasta ahora, cabecera incluida."""
        self._f.flush()
        os.fsync(self._f.fileno())

    def cerrar(self):
        # wave no cierra un archivo que no abrio el, asi que hay que cerrar los
        # dos: primero el wrapper (que parcha la cabecera), despues el archivo.
        try:
            self._w.close()
        except Exception:
            pass
        try:
            self._f.close()
        except Exception:
            pass


def leer_wav(ruta):
    """Devuelve (fs, datos int16 de forma (cuadros, canales)). Para el analisis."""
    with wave.open(ruta, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("solo se manejan WAV de 16 bits")
        canales = w.getnchannels()
        fs = w.getframerate()
        crudo = w.readframes(w.getnframes())
    datos = np.frombuffer(crudo, dtype="<i2").reshape(-1, canales)
    return fs, datos


def a_fraccion(bloque):
    """int16 -> fraccion de fondo de escala, en [-1, 1)."""
    return np.asarray(bloque, dtype=np.float64) / FONDO_ESCALA


def dbfs(x):
    """Pico de una senal, en dB respecto del fondo de escala.

    Sirve para vigilar el clipeo mientras se graba: la entrada de instrumento de
    la UMC22 satura en -3 dBu con la perilla al minimo, y un clipeo pasa
    desapercibido a ojo pero ensucia toda la FFT con armonicos que no existen.
    """
    pico = float(np.max(np.abs(np.asarray(x, dtype=np.float64))))
    if pico <= 0:
        return -np.inf
    return 20.0 * np.log10(pico)


# ---------------------------------------------------------------------------
# Autoprueba
# ---------------------------------------------------------------------------

def _test():
    import os
    import tempfile

    fallos = 0

    def check(nombre, cond, detalle=""):
        nonlocal fallos
        print(f"  {'ok   ' if cond else 'FALLA'}  {nombre:44s} {detalle}")
        if not cond:
            fallos += 1

    print("\n--- conversion de escala ---")
    check("int16 maximo -> ~+1", abs(a_fraccion(np.int16(32767)) - 0.99997) < 1e-4)
    check("int16 minimo -> -1", a_fraccion(np.int16(-32768)) == -1.0)
    check("cero -> 0", a_fraccion(np.int16(0)) == 0.0)
    check("dbfs de fondo de escala = 0 dB", abs(dbfs([1.0, -0.5])) < 1e-9)
    check("dbfs de la mitad = -6 dB", abs(dbfs([0.5]) + 6.0206) < 1e-3)

    print("\n--- WAV: ida y vuelta ---")
    # Dos canales con contenido distinto, para detectar un intercalado al reves.
    # Ese es el error clasico y silencioso: el beat termina en el canal de
    # sincronismo y no se nota hasta que la FFT no da nada.
    n, fs = 5000, 48000
    t = np.arange(n) / fs
    izq = (20000 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16)
    der = (10000 * np.sin(2 * np.pi * 200 * t)).astype(np.int16)
    original = np.column_stack([izq, der])

    ruta = os.path.join(tempfile.gettempdir(), "_prueba_audio_gpr.wav")
    w = EscritorWav(ruta, 2, fs)
    for i in range(0, n, 512):                 # por bloques, como en la captura
        w.escribir(original[i:i + 512])
    w.cerrar()

    fs_leido, vuelta = leer_wav(ruta)
    check("fs preservada", fs_leido == fs, str(fs_leido))
    check("forma preservada", vuelta.shape == original.shape, str(vuelta.shape))
    check("muestras identicas", np.array_equal(vuelta, original))
    check("canales no intercambiados",
          np.array_equal(vuelta[:, 0], izq) and np.array_equal(vuelta[:, 1], der))
    check("cuadros contados", w.cuadros == n, str(w.cuadros))

    print("\n--- WAV: sobrevive a un corte ---")
    # Se escribe y NO se cierra, para simular un Ctrl+C o una caida.
    ruta2 = os.path.join(tempfile.gettempdir(), "_prueba_audio_corte.wav")
    w2 = EscritorWav(ruta2, 1, fs)
    w2.escribir(izq[:1000].reshape(-1, 1))
    w2.sincronizar()
    _, parcial = leer_wav(ruta2)
    check("lo grabado se lee sin cerrar", parcial.shape == (1000, 1),
          str(parcial.shape))
    w2.cerrar()

    print("\n--- validacion de argumentos ---")
    ruta3 = os.path.join(tempfile.gettempdir(), "_prueba_audio_arg.wav")
    w3 = EscritorWav(ruta3, 2, fs)
    try:
        w3.escribir(np.zeros((10, 2), dtype=np.float32))
        check("rechaza float32", False)
    except TypeError:
        check("rechaza float32", True)
    try:
        w3.escribir(np.zeros((10, 1), dtype=np.int16))
        check("rechaza cantidad de canales incorrecta", False)
    except ValueError:
        check("rechaza cantidad de canales incorrecta", True)
    w3.cerrar()

    print("\n--- orden de preferencia de APIs ---")
    check("ASIO gana a WASAPI",
          _puntaje_api("ASIO") < _puntaje_api("Windows WASAPI"))
    check("WASAPI gana a MME",
          _puntaje_api("Windows WASAPI") < _puntaje_api("MME"))
    check("API desconocida ultima", _puntaje_api("Sarasa") == len(PREFERENCIA_API))

    print("\n--- eleccion entre APIs del mismo dispositivo ---")
    # El caso real del banco: la UMC22 con el driver generico aparecia en WASAPI
    # con 1 canal y en WDM-KS con 2. Pidiendo 2, tiene que ganar WDM-KS aunque
    # su API este mas abajo en la preferencia.
    global listar
    _listar = listar
    listar = lambda: [
        Entrada(1, "Microphone (USB Audio CODEC )", "MME", 2, 44100),
        Entrada(14, "Microphone (USB Audio CODEC )", "Windows WASAPI", 1, 48000),
        Entrada(37, "Microphone (USB Audio CODEC)", "Windows WDM-KS", 2, 44100),
    ]
    try:
        check("pidiendo 2 canales gana el que los tiene",
              elegir("auto", 2).idx == 37, f"idx {elegir('auto', 2).idx}")
        check("pidiendo 1 canal gana la mejor API",
              elegir("auto", 1).idx == 14, f"idx {elegir('auto', 1).idx}")
        check("el indice explicito manda igual", elegir("14", 2).idx == 14)
    finally:
        listar = _listar

    print("\n--- deteccion de la placa por nombre ---")
    check("UMC ASIO Driver",
          Entrada(0, "UMC ASIO Driver", "ASIO", 2, 48000).es_placa)
    check("USB Audio CODEC",
          Entrada(0, "Microfono (2- USB Audio CODEC)", "MME", 2, 48000).es_placa)
    check("no confunde el micro de la notebook",
          not Entrada(0, "Microphone Array (Realtek)", "MME", 2, 48000).es_placa)

    for r in (ruta, ruta2, ruta3):
        try:
            os.remove(r)
        except OSError:
            pass

    print()
    if fallos:
        print(f"  {fallos} prueba(s) FALLARON")
        return 1
    print("  todo bien")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_test())
    if "--listar" in sys.argv:
        print("\nEntradas de audio disponibles:\n")
        print(tabla())
        e = elegir("auto")
        print(f"\n  auto -> {e if e else 'no encontre la placa'}\n")
        sys.exit(0)
    print(__doc__)
