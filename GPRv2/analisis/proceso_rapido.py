"""
GPRv2 - Primitivas de proceso rapidas
=====================================

Las mismas cuentas que hace `correccion_no_linealidad.py`, reescritas para
que se puedan hacer MUCHAS veces por segundo sin comerse la maquina. No hay
ningun algoritmo nuevo aca: `verificar_rapido.py` comprueba contra el modulo
original que los resultados son los mismos (el remuestreo, bit a bit dentro
del ruido de float; el ajuste de la triangular, dentro de 1 ppm).

Lo usa `vivo_rapido.py`. Los scripts viejos no se tocan.

Que se cambio y por que
-----------------------

1. REMUESTREO: de un `interp1d` cubico por rampa a UNA matriz.

   `remuestrear()` arma un spline cubico nuevo para cada rampa. Pero la grilla
   theta NO cambia entre rampas: sale de `eje_theta()`, que solo depende de la
   curva del VCO y del largo de la rampa. Y el spline cubico es un operador
   LINEAL sobre las muestras: si la grilla de entrada y la de salida estan
   fijas, remuestrear es multiplicar por una matriz fija.

   Esa matriz se arma una sola vez (interpolando la base canonica, o sea la
   identidad) y despues cada rampa es un producto matriz-vector, o mejor: N
   rampas juntas son UN producto de matrices, que va a BLAS.

   No es "otro interpolador": es el MISMO spline cubico not-a-knot que usa
   `interp1d(kind="cubic")`, escrito de otra forma. CLAUDE.md avisa de no
   cambiar el interpolador buscando SNR, y esto no lo cambia — el error
   relativo medido contra `interp1d` es 6e-16, o sea el redondeo de float64.

       interp1d por rampa   293 us
       matriz (lote de 20)   13 us      22x

2. FFT: de `np.fft.rfft` por rampa a `scipy.fft.rfft` de todo el lote en
   float32. numpy sube todo a float64 aunque la entrada sea float32; scipy
   respeta el tipo y devuelve complex64, que para magnitudes de FFT que van a
   una pantalla sobra. Ademas hace el lote entero de una y usa varios hilos.

       np.fft por rampa      27 us
       scipy en lote f32      5 us      5x

3. AJUSTE DE LA TRIANGULAR: de 1000 evaluaciones a ~90.

   `ajustar_triangular()` barre 600 periodos gruesos + 400 finos, y cada
   evaluacion es un `np.exp` complejo sobre ~940 lecturas: 105 ms. Como corre
   cada REAJUSTE_S = 2 s EN EL HILO DEL GRAFICO, es un congelamiento de 105 ms
   cada 2 segundos — media pantalla perdida.

   Aca la pasada gruesa va vectorizada (una matriz de fases, cos y sin en
   bloque) y con la cantidad de pasos sacada de los datos en vez de fija: el
   ancho del lobulo principal en T vale 1/N_periodos relativo, asi que con
   8*span*N_periodos puntos hay 4 puntos por lobulo y es imposible saltearlo.
   La pasada fina se reemplaza por una busqueda de seccion aurea sobre +-1
   paso grueso, que llega a 1e-9 relativo en 30 evaluaciones en vez de 400.

       ajustar_triangular()       105 ms
       ajustar_triangular_rapido()  2 ms     ~40x

4. PICO SUB-BIN: interpolacion parabolica sobre las tres magnitudes en dB
   alrededor del maximo. La precision del pico deja de estar atada al paso de
   bin, o sea al relleno de ceros. Es lo que se usa siempre en FMCW y es la
   diferencia entre tomar un punto de calibracion repetible y uno que salta
   de bin en bin.
"""

import numpy as np
from scipy.interpolate import CubicSpline

try:
    import scipy.fft as _sfft
    HAY_SCIPY_FFT = True
except ImportError:                      # pragma: no cover - scipy siempre esta
    HAY_SCIPY_FFT = False


# --- Remuestreo en theta, precalculado -------------------------------------

class Remuestreador:
    """
    El remuestreo de `remuestrear()` como una matriz fija.

    Se arma una vez por cada largo de rampa (o sea, cada vez que
    `_armar_ejes()` rehace los ejes) y de ahi en mas cada rampa cuesta un
    producto de matrices.

    `ventana` (la de la FFT) se pliega adentro de la matriz: ventanear es
    multiplicar cada muestra de salida por un numero, y eso es una fila de la
    matriz escalada. Sale gratis y ahorra una pasada por la memoria. La
    ventana queda igual guardada aparte, que es lo auditable: `aplicar()`
    devuelve el remuestreo puro, sin ventanear, para poder compararlo contra
    `remuestrear()`.
    """

    def __init__(self, theta, n, ventana=None, dtype=np.float32):
        theta = np.asarray(theta, dtype=float)
        # La misma grilla que arma remuestrear(): n puntos, n-1 pasos. El
        # fs efectivo que le corresponde lo da fs_theta() (ver CLAUDE.md).
        self.theta_uniforme = np.linspace(theta[0], theta[-1], n)
        # interp1d(kind="cubic") delega en make_interp_spline(k=3), que usa
        # condicion not-a-knot: el mismo spline que CubicSpline por defecto.
        # Interpolando la identidad sale la matriz del operador.
        M = CubicSpline(theta, np.eye(len(theta)), axis=0,
                        bc_type="not-a-knot")(self.theta_uniforme)
        self.M = np.ascontiguousarray(M, dtype=float)        # (n, n)
        self.ventana = (np.ones(n) if ventana is None
                        else np.asarray(ventana, dtype=float))
        # Transpuesta y contigua: el lote llega como (rampas, muestras), asi
        # que la cuenta es S @ MT y BLAS la quiere asi.
        self._MT = np.ascontiguousarray(self.M.T, dtype=dtype)
        self._MWT = np.ascontiguousarray((self.M * self.ventana[:, None]).T,
                                         dtype=dtype)
        self.dtype = dtype

    def aplicar(self, S):
        """Remuestreo puro de un lote (rampas, muestras). Sin ventanear."""
        return np.asarray(S, dtype=self.dtype) @ self._MT

    def aplicar_ventaneado(self, S):
        """Remuestreo + ventana de FFT, en un solo producto."""
        return np.asarray(S, dtype=self.dtype) @ self._MWT


# --- FFT en lote -----------------------------------------------------------

def largo_fft(n, relleno):
    """Largo de FFT >= n*relleno que la libreria sabe hacer rapido.

    El relleno no agrega resolucion (el ancho de bin vale c/(2*BW) y punto,
    ver CLAUDE.md): interpola. Asi que subir un poco el largo hasta el
    siguiente numero "lindo" no cuesta nada y puede ahorrar bastante tiempo.
    """
    objetivo = int(n * relleno)
    if HAY_SCIPY_FFT:
        return int(_sfft.next_fast_len(objetivo, real=True))
    return objetivo


def espectros(S, nfft, hilos=-1):
    """|rFFT| de un lote (rampas, muestras) ya ventaneado, en float32."""
    if HAY_SCIPY_FFT:
        return np.abs(_sfft.rfft(S, n=nfft, axis=-1, workers=hilos))
    return np.abs(np.fft.rfft(S, n=nfft, axis=-1)).astype(np.float32)


# --- Ajuste de la triangular -----------------------------------------------

def _pot_armonico(t, v, Ts, bloque=256):
    """|S(T)|^2 del primer armonico, para cada T de Ts, vectorizado.

    S(T) = sum v(t)*exp(-2i*pi*t/T). Se calcula con cos y sin en vez de con
    la exponencial compleja: `np.exp` de complejos es varias veces mas caro
    que un cos y un sin reales, y la parte pesada (la matriz de fases) es la
    misma. Se devuelve el modulo al cuadrado porque el argmax es el mismo y
    ahorra la raiz.

    Va por bloques de Ts para que la matriz de fases no crezca sin control:
    con 940 lecturas y 256 periodos son 2 MB, y no 40.
    """
    pot = np.empty(len(Ts))
    for i in range(0, len(Ts), bloque):
        w = (2.0 * np.pi) / Ts[i:i + bloque]
        fase = t[:, None] * w[None, :]
        re = v @ np.cos(fase)
        im = v @ np.sin(fase)
        pot[i:i + bloque] = re * re + im * im
    return pot


def _armonico(t, v, T):
    """S(T) para un solo T, complejo (hace falta el argumento para la fase)."""
    fase = t * (2.0 * np.pi / T)
    return np.dot(v, np.cos(fase)) - 1j * np.dot(v, np.sin(fase))


def _maximo_aureo(f, a, b, iteraciones=32):
    """Maximo de f en [a, b] por seccion aurea. f tiene que ser unimodal ahi.

    Lo es por construccion: el intervalo que se le pasa es +-1 paso de la
    grilla gruesa alrededor de su maximo, o sea medio lobulo principal.

    Cada vuelta achica el intervalo por 0,618, asi que 32 vueltas lo dividen
    por 3e-7. Con un intervalo inicial del 0,06 % de T eso deja el periodo con
    ~2e-10 de error relativo: mucho mas de lo que hace falta, y sigue siendo
    32 evaluaciones contra las 400 de la pasada fina original.
    """
    r = (np.sqrt(5.0) - 1.0) / 2.0
    c, d = b - r * (b - a), a + r * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iteraciones):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - r * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + r * (b - a)
            fd = f(d)
    return 0.5 * (a + b)


def ajustar_triangular_rapido(idx, val, fs, T_nom, span=0.25):
    """
    Igual que `ajustar_triangular()`: devuelve (T, t0), periodo completo en
    segundos e instante del primer vertice de MINIMO.

    La diferencia esta solo en como se busca el maximo, no en que se maximiza.
    Ver el encabezado del modulo, punto 3.
    """
    t = np.asarray(idx, dtype=float) / fs
    v = np.asarray(val, dtype=float)
    v = v - v.mean()
    if len(t) < 4:
        return T_nom, 0.0

    # Cuantos puntos de grilla hacen falta. El lobulo principal en T tiene
    # ancho relativo 1/N_periodos (a medio lobulo, la fase del borde de la
    # ventana ya se corrio pi), asi que pidiendo 4 puntos por lobulo sobre un
    # rango de 2*span sale 8*span*N_periodos. Fijo en 600 como estaba era
    # derrochar cuando el Tprf es largo y quedarse corto si alguna vez la
    # ventana de ajuste se hace muy grande.
    n_periodos = max((t[-1] - t[0]) / T_nom, 1.0)
    pasos = int(np.clip(8.0 * span * n_periodos, 64, 4000))

    Ts = np.linspace(T_nom * (1 - span), T_nom * (1 + span), pasos)
    i = int(np.argmax(_pot_armonico(t, v, Ts)))
    paso = Ts[1] - Ts[0]
    # El maximo verdadero esta a menos de medio paso del argmax de la grilla;
    # +-1 paso lo encierra con margen y sigue siendo medio lobulo, o sea
    # unimodal.
    a = max(Ts[i] - paso, Ts[0] * 0.5)
    b = Ts[i] + paso
    T = _maximo_aureo(lambda x: abs(_armonico(t, v, x)), a, b)

    # Con v(t) = f((t-t0)/T) y f par (minimo en el origen), sale
    # S = N*c1*exp(-2i*pi*t0/T) con c1 real NEGATIVO, o sea
    # arg(S) = -2*pi*t0/T + pi. Ojo con el signo: invertirlo devuelve T-t0 en
    # vez de t0, y eso agarra la bajada creyendo que es la subida (CLAUDE.md).
    t0 = (np.pi - np.angle(_armonico(t, v, T))) / (2 * np.pi) * T
    return T, t0 % T


# --- Pico sub-bin ----------------------------------------------------------

def pico_parabolico(y, i):
    """
    Corrimiento sub-bin del maximo, por parabola sobre los tres puntos en dB.

    `y` es el perfil (magnitudes lineales) e `i` el indice del maximo.
    Devuelve delta en bins, entre -0,5 y +0,5, para sumarle a `i`.

    El ancho de bin REAL no cambia (vale c/(2*BW), ver CLAUDE.md): lo que
    cambia es la precision con que se ubica el centro de un pico que ya se
    resolvio, que con ruido razonable baja a centesimas de bin. En dB y no en
    lineal porque cerca del maximo la respuesta de una ventana de Hann es
    casi una parabola en dB, no en amplitud.
    """
    n = len(y)
    if i <= 0 or i >= n - 1:
        return 0.0
    y0, y1, y2 = float(y[i - 1]), float(y[i]), float(y[i + 1])
    # Los perfiles con el fondo restado llevan piso en cero (maximum(p-f, 0)),
    # asi que un vecino del maximo puede venir en cero exacto. En dB eso es
    # -infinito, y metido en la parabola empuja el pico media grilla para el
    # otro lado. Si algun vecino se anulo no hay forma de saber la fraccion:
    # se devuelve el centro del bin, que es lo que habia antes de interpolar.
    if y0 <= 0.0 or y1 <= 0.0 or y2 <= 0.0:
        return 0.0
    a = 20.0 * np.log10(y0)
    b = 20.0 * np.log10(y1)
    c = 20.0 * np.log10(y2)
    den = a - 2.0 * b + c
    if den >= 0.0:                 # no es un maximo: no hay nada que corregir
        return 0.0
    d = 0.5 * (a - c) / den
    return float(np.clip(d, -0.5, 0.5))
