"""
Procesamiento de senal para el graficador y para el analisis offline.

Todo el DSP vive aca, en numpy/scipy, sin nada de interfaz grafica. La idea es
que la parte que hay que entender y justificar en la tesis se pueda leer, probar
y reusar sin arrastrar Qt, y que graficarserial.py quede como una cascara que
solo dibuja.

Autoprueba:
    python dsp.py --test
"""

import sys

import numpy as np
from scipy import signal

C_LUZ = 3e8

VENTANAS = ["hann", "hamming", "blackman", "flattop", "rectangular"]


# ---------------------------------------------------------------------------
# Ventaneo
# ---------------------------------------------------------------------------

def ventana(nombre: str, n: int) -> np.ndarray:
    """Ventana de analisis.

    Que ventana usar no es un detalle cosmetico:

      rectangular  No atenua nada, asi que la fuga espectral es enorme (primer
                   lobulo lateral a -13 dB y caida lentisima). Solo sirve si la
                   senal cae exactamente en el centro de un bin. Es la que hace
                   que se vean "faldas" anchas alrededor de cada armonico.
      hann         El compromiso razonable por defecto: lobulos a -31 dB con
                   caida rapida. Es la que conviene para el GPR.
      hamming      Primer lobulo mas bajo (-43 dB) pero cola mas alta que hann.
      blackman     Lobulos a -58 dB, a costa de un pico mas ancho. Util cuando
                   hay un eco fuerte cerca de uno debil (el caso del GPR con
                   acoplamiento directo).
      flattop      Deforma el pico a proposito para que su ALTURA sea exacta
                   sin importar donde caiga respecto del bin. Es la correcta
                   para MEDIR amplitudes; pesima para resolver dos tonos juntos.
    """
    nombre = nombre.lower()
    if nombre == "rectangular":
        return np.ones(n)
    if nombre == "hann":
        return signal.windows.hann(n, sym=False)
    if nombre == "hamming":
        return signal.windows.hamming(n, sym=False)
    if nombre == "blackman":
        return signal.windows.blackman(n, sym=False)
    if nombre == "flattop":
        return signal.windows.flattop(n, sym=False)
    raise ValueError(f"ventana desconocida: {nombre}")


# ---------------------------------------------------------------------------
# Espectro
# ---------------------------------------------------------------------------

def espectro(x: np.ndarray, fs: float, nombre_ventana: str = "hann",
             zero_pad: int = 1):
    """Densidad espectral de potencia de un bloque. Devuelve (frecuencias, potencia).

    zero_pad multiplica el largo de la FFT rellenando con ceros. NO agrega
    resolucion real -- dos tonos separados por menos de fs/N siguen sin poder
    distinguirse -- pero interpola el espectro, y eso hace que la ALTURA y la
    POSICION de un pico se lean mucho mejor. Para el GPR, donde el pico se
    convierte en distancia, interpolar reduce el error de lectura.

    NORMALIZACION DE AMPLITUD: el pico de un tono de amplitud A vale A^2, o sea
    20*log10(A) en dB, sin importar que ventana se use. Es la que corresponde
    para un radar, donde los blancos son tonos discretos y lo que se quiere leer
    es su amplitud.

    La alternativa habitual (dividir por sum(w^2), o sea densidad espectral) es
    la correcta para medir RUIDO, pero hace que el pico de un tono dependa del
    ancho de banda equivalente de la ventana: con flattop el pico caeria 5.8 dB
    respecto de rectangular, que es justo lo contrario de lo que uno espera al
    elegir flattop para medir amplitudes.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 8:
        return np.zeros(0), np.zeros(0)

    w = ventana(nombre_ventana, n)
    xw = (x - x.mean()) * w                 # sin media: el DC tapa todo

    nfft = int(2 ** np.ceil(np.log2(n * max(1, zero_pad))))
    X = np.fft.rfft(xw, n=nfft)

    amp = np.abs(X) / np.sum(w)
    amp[1:-1] *= 2.0                        # espectro de un solo lado
    frec = np.fft.rfftfreq(nfft, 1.0 / fs)
    return frec, amp ** 2


def a_db(pot: np.ndarray, piso: float = 1e-20) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(pot, piso))


class Promediador:
    """Promedia potencia entre bloques sucesivos.

    Es el control que mas rinde en un GPR: el eco de un blanco es coherente y
    se repite igual en cada sweep, mientras que el ruido es aleatorio y se
    cancela. Promediando K bloques, la relacion senal-ruido mejora ~10*log10(K)
    dB: con K=16 son 12 dB, con K=64 son 18 dB.

    Se promedia POTENCIA, no dB. Promediar decibeles da un resultado sesgado
    hacia abajo porque el logaritmo no es lineal.
    """

    def __init__(self, k: int = 1):
        self.k = max(1, int(k))
        self._buf = []

    def configurar(self, k: int):
        k = max(1, int(k))
        if k != self.k:
            self.k = k
            self._buf.clear()

    def reiniciar(self):
        self._buf.clear()

    def agregar(self, pot: np.ndarray) -> np.ndarray:
        if self._buf and len(self._buf[0]) != len(pot):
            self._buf.clear()               # cambio el tamano de la FFT
        self._buf.append(pot)
        if len(self._buf) > self.k:
            del self._buf[:len(self._buf) - self.k]
        return np.mean(self._buf, axis=0)

    @property
    def cargados(self) -> int:
        return len(self._buf)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def pasaaltos(x: np.ndarray, fs: float, fc: float, orden: int = 4) -> np.ndarray:
    """Pasa-altos de fase cero.

    En el GPR sirve para atenuar el acoplamiento directo entre antenas, que
    aparece como un eco enorme a distancia casi nula y con sus faldas tapa los
    blancos cercanos.

    filtfilt aplica el filtro hacia adelante y hacia atras: no introduce
    desfasaje, que importa porque un corrimiento de fase se traduce en un
    corrimiento de distancia.
    """
    if fc <= 0 or fc >= fs / 2:
        return x
    sos = signal.butter(orden, fc, btype="high", fs=fs, output="sos")
    if len(x) <= 3 * orden * 2:
        return x
    return signal.sosfiltfilt(sos, x)


def notch(x: np.ndarray, fs: float, f0: float = 50.0, q: float = 30.0) -> np.ndarray:
    """Elimina un tono angosto. Por defecto los 50 Hz de la red."""
    if f0 <= 0 or f0 >= fs / 2:
        return x
    b, a = signal.iirnotch(f0, q, fs)
    if len(x) <= 12:
        return x
    return signal.filtfilt(b, a, x)


def decimar(x: np.ndarray, factor: int) -> np.ndarray:
    """Diezmado por promedio de bloques. Solo para visualizacion.

    OJO: no confundir con el 'dec' del firmware. Aquel es irreversible (los
    datos se graban ya diezmados); este es cosmetico y no toca el archivo.
    """
    factor = max(1, int(factor))
    if factor == 1:
        return x
    n = (len(x) // factor) * factor
    if n == 0:
        return x
    return x[:n].reshape(-1, factor).mean(axis=1)


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------

def frec_a_distancia(f, bw_hz: float, t_sweep_s: float, eps_r: float = 1.0):
    """Convierte frecuencia de beat en distancia.

        R = f_beat * v * T_sweep / (2 * BW)      con  v = c / sqrt(eps_r)

    Es la ecuacion que convierte el eje del espectro en el perfil de distancia
    del radar. eps_r = 1 es aire; en suelo humedo ronda 9, y ahi las distancias
    se dividen por 3.
    """
    if bw_hz <= 0 or t_sweep_s <= 0:
        return np.zeros_like(np.asarray(f, dtype=float))
    v = C_LUZ / np.sqrt(max(eps_r, 1e-9))
    return np.asarray(f, dtype=float) * v * t_sweep_s / (2.0 * bw_hz)


def resolucion_distancia(bw_hz: float, eps_r: float = 1.0) -> float:
    """Resolucion teorica: c / (2*BW). La fija el ancho de banda, NO el
    tiempo de sweep ni la frecuencia de muestreo."""
    if bw_hz <= 0:
        return float("inf")
    return (C_LUZ / np.sqrt(max(eps_r, 1e-9))) / (2.0 * bw_hz)


# ---------------------------------------------------------------------------
# Autoprueba
# ---------------------------------------------------------------------------

def autoprueba():
    print("Autoprueba de dsp.py")
    print("=" * 60)
    fallos = 0

    def chequear(nombre, ok, detalle=""):
        nonlocal fallos
        print(f"  [{'OK ' if ok else 'MAL'}] {nombre}" + (f"  {detalle}" if detalle else ""))
        if not ok:
            fallos += 1

    fs, n = 8000.0, 4096
    t = np.arange(n) / fs

    # 1. El pico cae en la frecuencia correcta
    x = np.sin(2 * np.pi * 500.0 * t)
    f, p = espectro(x, fs, "hann")
    chequear("pico en la frecuencia correcta", abs(f[np.argmax(p)] - 500.0) < 2.0,
             f"{f[np.argmax(p)]:.2f} Hz")

    # 2. Un tono de amplitud conocida tiene que leerse en su valor real.
    #    Se lo pone a MEDIO BIN de distancia de un centro, que es el peor caso:
    #    ahi una ventana rectangular pierde 3.92 dB (scalloping), y ese error
    #    se traduciria directamente en subestimar la reflectividad de un blanco.
    f_peor = (257 + 0.5) * fs / n                # 502.93 Hz
    x = 0.5 * np.sin(2 * np.pi * f_peor * t)     # 0.5 -> 20*log10(0.5) = -6.02 dB
    _, p_ft = espectro(x, fs, "flattop")
    _, p_re = espectro(x, fs, "rectangular")
    db_ft = 10 * np.log10(p_ft.max())
    db_re = 10 * np.log10(p_re.max())
    chequear("flattop lee la amplitud real entre bins", abs(db_ft + 6.02) < 0.2,
             f"{db_ft:.2f} dB (real -6.02)")
    chequear("rectangular pierde ~3.9 dB por scalloping",
             abs((db_ft - db_re) - 3.92) < 0.3,
             f"{db_re:.2f} dB, {db_ft - db_re:.2f} dB por debajo (teorico 3.92)")

    # 3. El promediado de K bloques baja el ruido ~10*log10(K)
    rng = np.random.default_rng(0)
    prom = Promediador(16)
    for _ in range(16):
        _, p = espectro(rng.normal(size=1024), fs, "hann")
        prom_out = prom.agregar(p)
    _, p1 = espectro(rng.normal(size=1024), fs, "hann")
    disp_1 = np.std(a_db(p1))
    disp_16 = np.std(a_db(prom_out))
    chequear("promediar reduce la dispersion", disp_16 < disp_1 * 0.6,
             f"{disp_1:.1f} dB -> {disp_16:.1f} dB")

    # 4. El pasa-altos saca la continua y deja pasar el tono
    x = 5.0 + np.sin(2 * np.pi * 500.0 * t)
    y = pasaaltos(x, fs, 50.0)
    chequear("pasa-altos elimina la continua",
             abs(y.mean()) < 0.01 and abs(y.std() - 0.707) < 0.05,
             f"media {y.mean():.4f}, rms {y.std():.3f}")

    # 5. Ida y vuelta frecuencia <-> distancia
    bw, ts = 750e6, 10e-3
    d = frec_a_distancia(500.0, bw, ts)
    chequear("500 Hz -> 1 m", abs(d - 1.0) < 1e-6, f"{d:.4f} m")
    d9 = frec_a_distancia(500.0, bw, ts, eps_r=9.0)
    chequear("con eps_r=9 la distancia se divide por 3", abs(d9 - 1 / 3) < 1e-6,
             f"{d9:.4f} m")
    chequear("resolucion = c/2BW", abs(resolucion_distancia(bw) - 0.2) < 1e-9,
             f"{resolucion_distancia(bw) * 100:.1f} cm")

    # 6. El diezmado visual conserva la forma
    x = np.sin(2 * np.pi * 10.0 * t)
    xd = decimar(x, 8)
    chequear("diezmado conserva amplitud", abs(xd.std() - x.std()) < 0.02,
             f"rms {x.std():.3f} -> {xd.std():.3f}")

    # 7. El zero padding interpola: al muestrear el espectro mas fino, el pico
    #    encontrado no puede ser mas bajo, y se acerca a la amplitud real.
    x = np.sin(2 * np.pi * 503.7 * t)
    _, p1 = espectro(x, fs, "hann", zero_pad=1)
    _, p8 = espectro(x, fs, "hann", zero_pad=8)
    db1, db8 = 10 * np.log10(p1.max()), 10 * np.log10(p8.max())
    chequear("zero padding recupera altura de pico", db8 >= db1 - 1e-9 and abs(db8) < 0.1,
             f"{db1:.3f} -> {db8:.3f} dB (real 0.00)")

    print("=" * 60)
    print("TODO OK" if fallos == 0 else f"{fallos} PRUEBA(S) FALLARON")
    return fallos


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(1 if autoprueba() else 0)
    print(__doc__)
