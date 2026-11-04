"""
GPRv2 - Batido sintetico con armonicos, triangular real y cadena de IF
======================================================================

Lo que `radar.sintetizar()` hace para una rampa ideal, pero con todo lo que
tiene el banco en el medio. De punta a punta, una corrida de DURACION_S:

  1. La triangular del generador, V(t): la ideal del SDG830 o la LM324
     (medida con el osciloscopio, o la de LTspice).
  2. f(t) = curva del VCO (V(t)). Con la LM324, ademas, el corrimiento y el
     recorte que se vieron en el Max Hold (parametros.py, F_PISO_B/F_TOPE_B).
  3. El VCO saca f, 2f y 3f. Envolvente de la fundamental y nivel del 2o
     contra f, del Max Hold; el 3o es un parametro.
  4. El mezclador. Para cada armonico n la escena se lee en n*f(t): el
     batido de ese armonico es Re{c_n * H(n f(t))}, o sea un pico en n veces
     la frecuencia aparente de cada camino (el FANTASMA). El coeficiente c_n
     depende del modelo de mezclador (ver coeficientes()).
  5. La cadena de IF: filtro post-mezclador (G=1, ajustado a lo medido), el
     acople y el pasaaltos del PCM1808, el retardo de su filtro digital.
  6. El firmware: cascada de tres semibandas con los coeficientes del .ino,
     48 k -> 6 k, y una lectura de la triangular por bloque de DMA con el
     indice corrido 13 muestras, como lo emite adquisicion.ino.
  7. vivo_rapido: busca el periodo y la fase de la triangular con LAS MISMAS
     funciones (buscar_periodo, ajustar_triangular_rapido), corta las rampas,
     da vuelta las bajadas, saca la media, remuestrea en theta con la curva
     del software (Remuestreador), Hann, FFT con relleno x8, y promedia el
     modulo de las ultimas 8 rampas. El fondo congelado se resta en modulo,
     con piso en cero, como en el banco.

Por que el batido del armonico n es Re{c_n H(n f)}
-------------------------------------------------

El VCO saca sum_n a_n cos(n phi + psi_n). Cada componente pasa por la escena
lineal y llega como Re{a_n e^{j psi_n} H(n f) e^{j n phi}} (la misma
aproximacion cuasi-estatica de radar.py, valida para cada armonico). Un
multiplicador por el LO = sum_m a_m cos(m phi + psi_m) deja en banda base
solo los terminos con m = n: 1/2 a_n^2 Re{H(n f)}. Las fases psi_n se
cancelan. Un mezclador conmutado multiplica por sign(LO), cuya serie de
Fourier S_n depende de a_2, a_3 y de las fases: ahi queda
1/2 Re{conj(S_n) a_n e^{j psi_n} H(n f)}.
"""

import glob
import json
import os
import sys

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.optimize import brentq

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import parametros as P                                            # noqa: E402
import radar as R                                                 # noqa: E402
import correccion_no_linealidad as CNL                            # noqa: E402
from proceso_rapido import (Remuestreador, espectros, largo_fft,  # noqa: E402
                            ajustar_triangular_rapido)

# Coeficientes de la semibanda de adquisicion.ino (Q30). Copiados a mano:
# si se cambian en el .ino, cambiarlos aca.
HB = np.array([
    -135143, 0, 1143002, 0, -4050661, 0, 10527053, 0, -23184129, 0,
    47232807, 0, -99955210, 0, 336873039, 536840308, 336873039, 0,
    -99955210, 0, 47232807, 0, -23184129, 0, 10527053, 0, -4050661, 0,
    1143002, 0, -135143], dtype=float) / 2.0 ** 30

PASO_TABLA = 0.25e6       # Hz, grilla de H donde despues se interpola


# --- VCO ---------------------------------------------------------------------

def curvas():
    """(verdadera, la del software): Vin [V] -> f [Hz]."""
    return R.cargar_curva_vco(P.VCO_CSV_VERDAD), R.cargar_curva_vco(P.VCO_CSV_CORR)


def envolventes():
    """Del Max Hold: (f, nivel de la fundamental [dB, media 0], 2o [dBc]).

    El Max Hold deja peines (el analizador barre mas lento que el chirp y
    solo lo agarra donde se cruzan). La envolvente es el maximo de las tres
    capturas, despues un maximo movil de 13 puntos (38 MHz) que tapa los
    huecos y un promedio de 9 que lo suaviza.
    """
    trazas = []
    for ruta in sorted(glob.glob(os.path.join(P.MAXHOLD_DIR, "SSA_*.csv"))):
        L = open(ruta, encoding="utf-8", errors="replace").read().splitlines()
        i = L.index("Trace Data")
        trazas.append(np.array([[float(x) for x in l.split(",")[:2]]
                                for l in L[i + 1:] if l.strip()]))
    fm = trazas[0][:, 0]
    env = uniform_filter1d(maximum_filter1d(np.max([t[:, 1] for t in trazas], axis=0), 13), 9)

    def nivel(f):
        return np.interp(f, fm, env)

    f = np.arange(900e6, 2100e6, 1e6)
    banda = (f >= P.F_PISO_B) & (f <= P.F_TOPE_B)
    a1 = nivel(f) - nivel(f[banda]).mean()
    fl = np.clip(f, P.A2_F_DESDE, P.A2_F_HASTA)
    a2 = nivel(2 * fl) - nivel(fl)
    prom = (f >= P.A2_F_PROM) & (f <= P.A2_F_HASTA)
    a2[f > P.A2_F_HASTA] = a2[prom].mean()
    return f, a1, a2


# --- Triangulares ------------------------------------------------------------

class Triangular:
    """V(t) del generador, periodo T, vertice de abajo en t = 0.

    `forma(u)` da V en un periodo, u en [0, 1). `f_de_v` lleva la tension del
    generador a la frecuencia del VCO (curva + corrimiento + recorte).
    """

    def __init__(self, nombre, T, forma, vmin, vmax, f_de_v):
        self.nombre, self.T, self.forma = nombre, T, forma
        self.vmin, self.vmax, self.f_de_v = vmin, vmax, f_de_v

    def V(self, t):
        return self.forma((np.asarray(t) / self.T) % 1.0)

    def f(self, t):
        return self.f_de_v(self.V(t))


def tri_sdg(curva_v):
    """El SDG830: triangular ideal de 0 a 3 V, simetrica."""
    v0, v1 = P.V_SDG
    return Triangular("SDG830 ideal", P.TPRF_SDG,
                      lambda u: v0 + (v1 - v0) * (1 - np.abs(2 * u - 1)),
                      v0, v1, curva_v)


def _f_lm324(curva_v, vmin):
    """Tension del generador -> f con la HIPOTESIS del Max Hold.

    Corrimiento: el que lleva vmin a F_PISO_B. Recorte en F_TOPE_B.
    """
    v_piso = brentq(lambda v: curva_v(v) - P.F_PISO_B, -1.0, 2.0)
    off = v_piso - vmin
    return (lambda v: np.minimum(curva_v(np.asarray(v) + off), P.F_TOPE_B)), off


def curva_corrida(curva, off):
    """La curva del software desplazada `off` V: un software que sabe del
    corrimiento. El recorte no se puede corregir remuestreando (ahi f no
    cambia y theta deja de crecer), asi que esta curva no lo tiene."""
    return lambda v: curva(np.asarray(v) + off)


def tri_lm324_medida(curva_v, asimetria=True, residuo=True, recorte=True):
    """La LM324 con los numeros del osciloscopio (tanda 2, ~100 ms).

    Los tres flags apagan de a una las imperfecciones, para ver cual pesa:
    `asimetria` (subida y bajada de distinta duracion), `residuo` (la
    curvatura medida de cada rampa) y `recorte` (el tope de 1991 MHz; el
    corrimiento queda siempre, porque solo mueve la banda).

    Subida y bajada rectas entre vmin y vmax, con la duracion que dice el
    sync (sync alto = bajada), mas el residuo promedio medido de cada una.
    El residuo esta medido en el 90 % central de la rampa; hacia los vertices
    se lleva linealmente a cero.

    El residuo se SUAVIZA con una media movil de RESIDUO_SUAVE puntos (de
    200 por rampa: ~2,5 ms). El osciloscopio cuantiza en 40 mV y el promedio
    de una docena de rampas deja +-10 mV de ruido punto a punto, que un
    integrador con 2,2 uF no puede tener; usado tal cual, mete en f(t) un
    jitter que no existe. La curvatura y el escalon de ~0,95 V quedan.
    """
    r = json.load(open(P.TRI_JSON, encoding="utf-8"))[P.TRI_CAPTURA]
    T, baja, vmin, vmax = r["T"], r["duty"], r["vmin"], r["vmax"]
    us = 0.05 + 0.90 * np.arange(200) / 199
    u_r = np.r_[0.0, us, 1.0]
    res = {k: np.r_[0.0, uniform_filter1d(np.asarray(r["prom"][k]), P.RESIDUO_SUAVE,
                                          mode="nearest"), 0.0] * (1.0 if residuo else 0.0)
           for k in ("sube", "baja")}
    if not asimetria:
        baja = 0.5
    fs = 1.0 - baja

    def forma(u):
        u = np.asarray(u, dtype=float)
        sube = u < fs
        x = np.where(sube, u / fs, (u - fs) / baja)
        lin = np.where(sube, vmin + (vmax - vmin) * x, vmax - (vmax - vmin) * x)
        return lin + np.where(sube, np.interp(x, u_r, res["sube"]),
                              np.interp(x, u_r, res["baja"]))

    f_de_v, off = _f_lm324(curva_v, vmin)
    if not recorte:
        f_de_v = curva_corrida(curva_v, off)
    t = Triangular("LM324 medida (osciloscopio)", T, forma, vmin, vmax, f_de_v)
    t.offset, t.frac_sube = off, fs
    return t


def tri_lm324_ltspice(curva_v):
    """La forma de LTspice, con el periodo y los extremos MEDIDOS."""
    r = json.load(open(P.TRI_JSON, encoding="utf-8"))[P.TRI_CAPTURA]
    d = np.loadtxt(P.TRI_LTSPICE, delimiter=",", comments="#")
    u = (d[:, 0] - d[0, 0]) / (d[-1, 0] - d[0, 0])
    x = (d[:, 1] - d[:, 1].min()) / (d[:, 1].max() - d[:, 1].min())
    vmin, vmax = r["vmin"], r["vmax"]

    def forma(uu):
        return vmin + (vmax - vmin) * np.interp(uu, u, x)

    f_de_v, off = _f_lm324(curva_v, vmin)
    t = Triangular("LM324 segun LTspice", r["T"], forma, vmin, vmax, f_de_v)
    t.offset, t.frac_sube = off, float(u[np.argmax(x)])
    return t


# --- La escena: H a cualquier frecuencia ----------------------------------------

class Escena:
    """H total (aire de MEEP + cables + interno + fuga) en una grilla fina.

    `g` = [1, g2, g3]: el reescalado de "cadena plana" del aire a 2f y 3f
    (parametros.py, D_NORMALIZA). Se calcula afuera, con la placa a 1 m, y
    se aplica igual a todas las escenas de la misma sonda.
    """

    def __init__(self, ruta_npz, g=(1.0, 1.0, 1.0), fuga=None):
        self.ruta = ruta_npz
        self.npz = dict(np.load(ruta_npz))
        self.f = np.arange(0.90e9, 6.20e9, PASO_TABLA)
        self.aire = R.H_en(self.npz, self.f)
        self.H = R.aplicar_cadena(self.f, self.aire, P.MODO_CABLE)
        self.g = g
        self.fuga = fuga

    def con_fuga(self, fuga):
        """La misma escena con un camino de fuga (nivel, tau) sumado."""
        otra = object.__new__(Escena)
        otra.__dict__.update(self.__dict__)
        otra.fuga = fuga
        return otra

    def __call__(self, f, n=1):
        """H total en n*f. El reescalado de "cadena plana" va solo sobre lo
        que viene de MEEP; la fuga es electronica y no lo lleva."""
        x = n * np.asarray(f)
        h = self.g[n - 1] * (np.interp(x, self.f, self.H.real)
                             + 1j * np.interp(x, self.f, self.H.imag))
        if self.fuga is not None:
            nivel, tau = self.fuga
            h = h + nivel * np.exp(-2j * np.pi * x * tau)
        return h


class SoloFuga:
    """Solo el camino de fuga, con nivel 1: para el ajuste (el batido es
    lineal en H, asi que se escala despues)."""

    def __init__(self, tau):
        self.tau = tau

    def __call__(self, f, n=1):
        return np.exp(-2j * np.pi * n * np.asarray(f) * self.tau)


def normalizacion(placa, vacio, f_barrido):
    """g_n de la "cadena plana": nivel medio del eco de la placa a f sobre n*f.

    Se usa el AIRE solo (placa - vacio, sin cables), para no normalizar de
    paso la perdida real de los cables a n*f.
    """
    eco = lambda x: (np.interp(x, placa.f, placa.aire.real - vacio.aire.real)
                     + 1j * np.interp(x, placa.f, placa.aire.imag - vacio.aire.imag))
    ref = np.sqrt(np.mean(np.abs(eco(f_barrido)) ** 2))
    return [1.0] + [ref / np.sqrt(np.mean(np.abs(eco(n * f_barrido)) ** 2)) for n in (2, 3)]


# --- Mezclador ------------------------------------------------------------------

def _serie_sign(a2, a3, psi):
    """S_1..S_3 de sign(cos x + a2 cos(2x+psi) + a3 cos 3x), complejos."""
    x = np.linspace(0, 2 * np.pi, 4096, endpoint=False)
    s = np.sign(np.cos(x) + a2 * np.cos(2 * x + psi) + a3 * np.cos(3 * x))
    S = np.fft.fft(s) / len(x) * 2
    return S[1:4]


def coeficientes(f, env, modelo, a3_dbc=None, psi=0.0):
    """c_n(f) complejos (n = 1, 2, 3) tales que el batido es
    1/2 sum_n Re{c_n H(n f)}.

    multiplicador: c_n = A1^2 a_n^2 (las fases se cancelan).
    conmutado:     c_n = A1 conj(S_n) a_n e^{j psi_n} / |S_1|, con S_n la
                   serie de sign(LO). El LO no tiene envolvente: conmuta.
    """
    fe, a1_db, a2_db = env
    A1 = 10 ** (np.interp(f, fe, a1_db) / 20)
    a2 = 10 ** (np.interp(f, fe, a2_db) / 20)
    a3 = 0.0 if a3_dbc is None else 10 ** (a3_dbc / 20)
    c = np.zeros((3, len(f)), dtype=complex)
    if modelo == "multiplicador":
        c[0] = A1 ** 2
        c[1] = (A1 * a2) ** 2
        c[2] = (A1 * a3) ** 2
        return c
    # conmutado: S_n depende de a2, que cambia despacio con f -> tabla
    grilla = np.linspace(a2.min(), a2.max(), 64) if a2.max() > a2.min() else a2[:1]
    tabla = np.array([_serie_sign(x, a3, psi) for x in grilla])
    S = np.array([np.interp(a2, grilla, tabla[:, k].real)
                  + 1j * np.interp(a2, grilla, tabla[:, k].imag) for k in range(3)])
    norma = np.abs(S[0])
    c[0] = A1 * np.conj(S[0]) / norma
    c[1] = A1 * np.conj(S[1]) * a2 * np.exp(1j * psi) / norma
    c[2] = A1 * np.conj(S[2]) * a3 / norma
    return c


# --- Cadena de IF -----------------------------------------------------------------

def ajuste_filtro_if():
    """(fc del pasaaltos de 1er orden, orden y fc del pasabajos) del filtro G=1.

    Pasaaltos con los puntos "sin distorsion" hasta 100 Hz; pasabajos de
    Butterworth con los de 10 kHz para arriba (estan marcados con
    distorsion, pero el pasabajos queda lejisimos de la banda util: da
    igual cuanto valga exactamente).
    """
    d = np.genfromtxt(P.FILTRO_IF_CSV, delimiter=",", names=True, dtype=None,
                      encoding="utf-8")
    f, h = d["f_Hz"].astype(float), d["H_G1_norm_dB"].astype(float)
    ok = np.isfinite(h)
    f, h, nota = f[ok], h[ok], d["nota"][ok]
    bajo = (f <= 100) & np.char.startswith(np.char.lower(nota.astype(str)), "sin")
    fcs = np.linspace(5, 40, 701)
    err = [np.sum((h[bajo] + 10 * np.log10(1 + (fc / f[bajo]) ** 2)) ** 2) for fc in fcs]
    fc_h = float(fcs[int(np.argmin(err))])
    alto = f >= 10e3
    mejor = None
    for orden in range(1, 7):
        for fc in np.linspace(15e3, 40e3, 501):
            e = np.sum((h[alto] + 10 * np.log10(1 + (f[alto] / fc) ** (2 * orden))) ** 2)
            if mejor is None or e < mejor[0]:
                mejor = (e, orden, fc)
    return fc_h, mejor[1], float(mejor[2])


def cadena_if():
    """Lista de sos (a FS_ADC) de la cadena analogica + el pasaaltos del PCM."""
    fc_h, n_l, fc_l = ajuste_filtro_if()
    fs = P.FS_ADC
    sos = [signal.butter(1, fc_h, "highpass", fs=fs, output="sos"),
           signal.butter(n_l, fc_l, "lowpass", fs=fs, output="sos"),
           signal.butter(1, P.ACOPLE_HPF_HZ, "highpass", fs=fs, output="sos"),
           signal.butter(1, P.PCM_HPF_HZ, "highpass", fs=fs, output="sos")]
    return np.vstack(sos), (fc_h, n_l, fc_l)


def diezmar(x):
    """La cascada de semibandas del firmware: 48 k -> 6 k.

    Cada etapa es el FIR de 31 coeficientes con estado inicial cero, y emite
    una salida cada dos entradas, empezando por la SEGUNDA (en el .ino la
    fase arranca en 0 y se invierte antes de mirar). La salida m sale con la
    entrada 8m+7.
    """
    for _ in range(3):
        x = signal.lfilter(HB, 1.0, x)[1::2]
    return x


# --- La corrida entera ---------------------------------------------------------------

class Corrida:
    """Batido de 6 kHz y lecturas de la triangular, como las manda el ESP32."""

    def __init__(self, tri, escenas, env, modelo="multiplicador", a3_dbc=None,
                 psi=0.0, armonicos=(1, 2, 3), cadena=True, ruido=0.0,
                 semilla=0, sos=None):
        n48 = int(P.DURACION_S * P.FS_ADC)
        t = np.arange(n48) / P.FS_ADC
        # El ADC muestrea en t, pero lo que sale ya paso por su filtro
        # digital: la muestra i corresponde a la entrada analogica de
        # t - PCM_RETARDO. La triangular se lee en tiempo real.
        f = tri.f(t - (P.PCM_RETARDO if cadena else 0.0))
        c = coeficientes(f, env, modelo, a3_dbc, psi)
        self.y = {}
        for k, (nombre, H) in enumerate(escenas.items()):
            b = np.zeros(n48)
            for n in armonicos:
                if np.any(c[n - 1]):
                    b += 0.5 * np.real(c[n - 1] * H(f, n))
            if ruido:
                b = b + np.random.default_rng(semilla + k).normal(0, ruido, n48)
            if cadena:
                b = signal.sosfilt(sos, b)
                self.y[nombre] = diezmar(b)
            else:
                # sin cadena: muestreo directo a 6 k, en el instante en que
                # el firmware sin filtro emitiria la muestra
                self.y[nombre] = b[7::P.DEC]
        # Una lectura por bloque de DMA, al final del bloque, con el indice
        # que emite adquisicion.ino: n_emitidas - 1 + retardo.
        nb = n48 // P.BLOQUE_DMA
        b = np.arange(1, nb + 1)
        tb = (P.BLOQUE_DMA * b - 1) / P.FS_ADC
        por = P.BLOQUE_DMA // P.DEC
        self.idx = por * b - 1 + (P.RETARDO_FIRMWARE if cadena else 0)
        self.val = np.round(tri.V(tb) / 2 / P.ADC_TRI_FONDO * 4095)
        self.tri = tri
        # Sincronismo PERFECTO (respuesta 14): el periodo exacto y el vertice
        # de abajo exacto, en la escala de tiempo en que el software lee las
        # lecturas (indice / FS). Lo que no es perfecto sigue estando: el
        # retardo del PCM1808 y el 0,125 de muestra que el firmware no
        # compensa, porque eso le pasa igual al banco.
        corr = self.idx[0] / P.FS - tb[0]
        self.sync = (tri.T, corr % tri.T)


class Procesado:
    """Lo que hace vivo_rapido con una Corrida.

    `curva` y `v_rango` son los del SOFTWARE: con que curva y con que rampa
    de tension arma el eje theta. `ajuste_soft`: en vez del sincronismo
    perfecto, el periodo y la fase que saca vivo_rapido de las lecturas (con
    una triangular asimetrica no coinciden con el vertice).
    """

    def __init__(self, corrida, curva, v_rango, ajuste_soft=False, complejo=False):
        idx, val = corrida.idx, corrida.val
        if ajuste_soft:
            T0 = CNL.buscar_periodo(idx, val, P.FS)
            T, t0 = ajustar_triangular_rapido(idx, val, P.FS, T0, 0.10)
            T, t0 = ajustar_triangular_rapido(idx, val, P.FS, T, 0.01)
        else:
            T, t0 = corrida.sync
        n = int(round(T * P.FS / 2))
        t = np.linspace(0, n / P.FS, n, endpoint=False)
        v_ant = CNL.V_MIN, CNL.V_MAX
        CNL.V_MIN, CNL.V_MAX = v_rango
        try:
            _, theta, alpha0 = CNL.eje_theta(curva, t)
        finally:
            CNL.V_MIN, CNL.V_MAX = v_ant
        self.T, self.t0, self.n, self.alpha0 = T, t0, n, alpha0
        self.fs_th = CNL.fs_theta(theta, n)
        self.nfft = largo_fft(n, P.RELLENO_FFT)
        self.rem = Remuestreador(theta, n, np.hanning(n))
        self.hz = np.fft.rfftfreq(self.nfft, d=1.0 / self.fs_th)
        self.hz_por_m = 2 * alpha0 / R.C
        self.E = {}
        for nombre, y in corrida.y.items():
            paso = T / 2
            k_tope = int(np.floor(((len(y) - n) / P.FS - t0) / paso))
            ks = np.arange(0, k_tope + 1)
            ini = np.rint((t0 + ks * paso) * P.FS).astype(np.int64)
            ok = (ini + n <= len(y)) & (ini / P.FS >= P.DESCARTE_S)
            ks, ini = ks[ok], ini[ok]
            S = y[ini[:, None] + np.arange(n)[None, :]].astype(float)
            impar = (ks % 2).astype(bool)
            S[impar] = S[impar, ::-1]
            S -= S.mean(axis=1, keepdims=True)
            SW = self.rem.aplicar_ventaneado(S)
            # complejo: para el ajuste de la fuga, que suma caminos antes
            # de tomar el modulo (el batido es lineal en H)
            self.E[nombre] = (np.fft.rfft(SW, n=self.nfft, axis=-1) if complejo
                              else espectros(SW, self.nfft))

    def perfil(self, nombre, cuantas=P.RAMPAS_EN_FILA):
        """Promedio del modulo de las ultimas `cuantas` rampas."""
        return self.E[nombre][-cuantas:].mean(axis=0)

    def fondo(self, nombre):
        """El fondo congelado: promedio de todas las rampas despues del descarte."""
        return self.E[nombre].mean(axis=0)


def db_norm(mag):
    return 20 * np.log10(mag / mag.max() + 1e-12)
