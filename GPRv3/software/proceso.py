"""
GPRv3 - De una rampa al perfil de distancia
===========================================

La no linealidad del VCO se corrige como en GPRv2 (Anghel et al., EUSIPCO
2013, con la curva medida en vez de la HAF): el batido se remuestrea sobre
un eje de FRECUENCIA uniforme y recien ahi se hace la FFT.

Lo que cambia respecto de GPRv2 es que el remuestreo se hace a un paso de
frecuencia fijo, y no a una cantidad fija de puntos por rampa. Con eso el
eje de distancia no depende de cuanto dura la rampa ni de que parte se usa,
y el radargrama no se reinicia al mover el pote ni los deslizadores. Ver
GPRv3/README.md.
"""

import csv
import math

import numpy as np
import scipy.fft as sfft
from scipy.interpolate import CubicSpline
from scipy.signal import windows

import config as cfg

P_MAX = 6      # el paso de frecuencia se puede afinar hasta 2^6 veces

# Ventanas de la FFT. De arriba hacia abajo: lobulos laterales mas bajos a
# cambio de un pico mas ancho (README, "Ventana de la FFT").
VENTANAS = {
    "rectangular": windows.boxcar,
    "hamming": windows.hamming,
    "hann": windows.hann,
    "blackman": windows.blackman,
    "blackman-harris": windows.blackmanharris,
}


class CurvaVCO:
    """Tension de control [V] -> frecuencia [Hz], spline cubico por los puntos."""

    def __init__(self, v, f):
        orden = np.argsort(v)
        self.v = np.asarray(v, dtype=float)[orden]
        self.f = np.asarray(f, dtype=float)[orden]
        self._s = CubicSpline(self.v, self.f)

    def __call__(self, v):
        return self._s(v)


def cargar_curva(ruta=cfg.VCO_CSV):
    """Lee Vin, Freq [MHz] de los CSV de VCO/ (coma decimal)."""
    v, f = [], []
    with open(ruta, encoding="utf-8", newline="") as arch:
        filas = csv.reader(arch)
        next(filas)
        for fila in filas:
            if len(fila) < 2 or not fila[0].strip() or not fila[1].strip():
                continue
            v.append(float(fila[0].replace(",", ".")))
            f.append(float(fila[1].replace(",", ".")) * 1e6)
    return CurvaVCO(v, f)


class Mapa:
    """
    f(u) y su inversa, con u la fraccion de la excursion de la triangular:
    0 en el valle y 1 en la cima. Como la triangular es recta, u es tambien
    la fraccion de tiempo de la rampa (contada desde el valle).

    [u_lo, u_hi] es la parte de la rampa que se usa (los dos deslizadores).
    """

    def __init__(self, curva, v_min, v_max, u_lo=0.0, u_hi=1.0, n=4097):
        self.u = np.linspace(0.0, 1.0, n)
        self.f = curva(v_min + (v_max - v_min) * self.u)
        if np.any(np.diff(self.f) <= 0):
            raise ValueError("la curva del VCO no es monotona entre "
                             f"{v_min} y {v_max} V")
        self.v_min, self.v_max = v_min, v_max
        self.u_lo, self.u_hi = float(u_lo), float(u_hi)
        self.bw_total = float(self.f[-1] - self.f[0])
        self.f_lo, self.f_hi = (float(x) for x in
                                np.interp([u_lo, u_hi], self.u, self.f))
        self.bw = self.f_hi - self.f_lo
        dfdu = np.gradient(self.f, self.u)
        self.dfdu_min = float(dfdu[(self.u >= u_lo) & (self.u <= u_hi)].min())

    def u_de_f(self, f):
        return np.interp(f, self.f, self.u)

    def v_de_u(self, u):
        return self.v_min + (self.v_max - self.v_min) * u


class Procesador:
    """Rampas -> perfiles de POTENCIA sobre un eje de distancia fijo, de
    paso DR_M. Un tono de amplitud A (cuentas del ADC) da un pico de A^2."""

    def __init__(self, curva, sps, v_min=None, v_max=None):
        self.curva = curva
        self.sps = float(sps)
        self.v_min = cfg.V_MIN if v_min is None else v_min
        self.v_max = cfg.V_MAX if v_max is None else v_max
        self.k = int(round(cfg.D_MAX_M / cfg.DR_M)) + 1
        self.eje_m = np.arange(self.k) * cfg.DR_M
        # Paso de frecuencia base: con NFFT_BASE puntos de FFT da justo DR_M
        # por bin. Cada afinado divide el paso por dos y duplica la FFT, asi
        # que el bin sigue midiendo lo mismo.
        self.df0 = cfg.C / (2.0 * cfg.DR_M * cfg.NFFT_BASE)
        self.ventana_fft = "hann"
        self.fijar_ventana(0.0, 1.0)

    def fijar_fft(self, nombre):
        self.ventana_fft = nombre
        self._grillas = {}

    def fijar_ventana(self, u_lo, u_hi):
        self.mapa = Mapa(self.curva, self.v_min, self.v_max, u_lo, u_hi)
        self._grillas = {}

    def afinado(self, largo):
        """Cuantas veces hay que partir el paso base para una rampa de
        `largo` muestras: el paso uniforme no puede ser mas grueso que el
        mas fino que traen las muestras (donde el VCO barre mas lento)."""
        df_min = self.mapa.dfdu_min / largo
        p = math.ceil(math.log2(self.df0 / df_min))
        return int(min(max(p, 0), P_MAX))

    def grilla(self, p):
        """(u de cada punto, ventana ya normalizada, largo de FFT)."""
        if p not in self._grillas:
            df = self.df0 / 2 ** p
            m = int(self.mapa.bw // df)
            if m < 16:
                raise ValueError("la parte usada de la rampa es demasiado "
                                 "angosta")
            f0 = self.mapa.f_lo + (self.mapa.bw - m * df) / 2.0
            u = self.mapa.u_de_f(f0 + (np.arange(m) + 0.5) * df)
            w = VENTANAS[self.ventana_fft](m)
            # 2/sum(w): un tono de amplitud A da un pico de altura A, sea
            # cual sea la cantidad de puntos. Los perfiles quedan en cuentas
            # del ADC y son comparables entre si.
            self._grillas[p] = (u, w * (2.0 / w.sum()), cfg.NFFT_BASE << p)
        return self._grillas[p]

    def procesar(self, muestras, rampas):
        """Perfiles |FFT|^2 (float32, len(rampas) x k) de un lote de rampas.

        Las muestras tienen que cubrir cada rampa con MARGEN_MUESTRAS de
        sobra a cada lado.
        """
        E = np.empty((len(rampas), self.k), dtype=np.float32)
        if not rampas:
            return E
        a = np.array([r.a for r in rampas])
        largo = np.array([r.b - r.a for r in rampas])
        sube = np.array([r.sube for r in rampas])
        i0 = int(math.floor(a.min())) - cfg.MARGEN_MUESTRAS
        i1 = int(math.ceil((a + largo).max())) + cfg.MARGEN_MUESTRAS + 1
        # Un solo spline cubico sobre el tramo entero, evaluado en los
        # puntos de todas las rampas.
        spline = CubicSpline(np.arange(i1 - i0), muestras.tramo(i0, i1))
        ps = np.array([self.afinado(x) for x in largo])
        for p in np.unique(ps):
            sel = np.flatnonzero(ps == p)
            u, w, nfft = self.grilla(int(p))
            # La bajada recorre las mismas frecuencias al reves: se lee de
            # atras para adelante y queda igual que una subida.
            frac = np.where(sube[sel, None], u[None, :], 1.0 - u[None, :])
            Y = spline(a[sel, None] - i0 + frac * largo[sel, None])
            Y -= Y.mean(axis=1, keepdims=True)
            Y *= w
            S = sfft.rfft(Y.astype(np.float32), n=nfft, axis=1, workers=-1)
            S = S[:, :self.k]
            E[sel] = S.real ** 2 + S.imag ** 2
        return E

    def cruda(self, muestras, rampa):
        """(u, batido) de una rampa sin procesar, del valle a la cima."""
        i = np.arange(math.ceil(rampa.a), math.floor(rampa.b) + 1)
        u = (i - rampa.a) / (rampa.b - rampa.a)
        v = muestras.tramo(int(i[0]), int(i[-1]) + 1)
        return (u, v.copy()) if rampa.sube else (1.0 - u[::-1], v[::-1].copy())


def pico_parabolico(y, i):
    """Corrimiento sub-bin del maximo (parabola sobre tres puntos en dB)."""
    if i <= 0 or i >= len(y) - 1:
        return 0.0
    y0, y1, y2 = float(y[i - 1]), float(y[i]), float(y[i + 1])
    if y0 <= 0.0 or y1 <= 0.0 or y2 <= 0.0:
        return 0.0
    a, b, c = (20.0 * math.log10(x) for x in (y0, y1, y2))
    den = a - 2.0 * b + c
    if den >= 0.0:
        return 0.0
    return float(min(max(0.5 * (a - c) / den, -0.5), 0.5))
