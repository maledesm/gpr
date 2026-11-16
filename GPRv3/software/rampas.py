"""
GPRv3 - Del chorro de muestras y flancos a rampas
=================================================

`Muestras` guarda el batido con su indice absoluto (el que cuenta la placa)
y recuerda los huecos. `Segmentador` convierte los flancos del sync en
rampas: cada rampa va de un flanco al siguiente, con su largo real.
"""

from collections import deque
from typing import NamedTuple

import numpy as np

import config as cfg


class Rampa(NamedTuple):
    a: float        # donde empieza, en muestras (con fraccion)
    b: float        # donde termina
    sube: bool      # True = del valle a la cima


class Muestras:
    """Batido contiguo desde `base` hasta `fin` (indices absolutos)."""

    def __init__(self):
        self.buf = np.empty(0)
        self.base = 0
        self.huecos = []           # [(desde, hasta)], indices absolutos
        self.total = 0

    @property
    def fin(self):
        return self.base + len(self.buf)

    def agregar(self, idx0, v):
        """False si el indice retrocedio (la placa se reinicio)."""
        if not len(self.buf) and not self.total:
            self.base = idx0
        if idx0 < self.fin:
            return False
        if idx0 > self.fin:
            # Paquetes perdidos: se rellena con ceros y se anota, para no
            # usar ninguna rampa que pise el hueco.
            self.huecos.append((self.fin, idx0))
            v = np.concatenate([np.zeros(idx0 - self.fin), v])
        self.buf = np.concatenate([self.buf, np.asarray(v, dtype=float)])
        self.total += len(v)
        return True

    def tramo(self, i0, i1):
        return self.buf[i0 - self.base:i1 - self.base]

    def pisa_hueco(self, i0, i1):
        return any(d < i1 and h > i0 for d, h in self.huecos)

    def descartar_hasta(self, i):
        corte = min(max(i - self.base, 0), len(self.buf))
        if corte:
            self.buf = self.buf[corte:]
            self.base += corte
            self.huecos = [(d, h) for d, h in self.huecos if h > self.base]


class Segmentador:
    """
    Flancos -> rampas. Se descarta la rampa cuando:
      - llegan dos flancos seguidos del mismo sentido (se perdio uno),
      - la duracion cae fuera de [T_RAMPA_MIN, T_RAMPA_MAX],
      - la duracion difiere mas de TOL_RAMPA de la mediana de las ultimas
        del mismo sentido (un flanco espurio parte una rampa en pedazos).
    La mediana se arma tambien con las descartadas, para que se acomode sola
    cuando se mueve el pote.
    """

    def __init__(self, sps):
        self.sps = float(sps)
        self.ant = None                      # (pos, nivel, t_us)
        self.ultimas = {True: deque(maxlen=cfg.MEMORIA_RAMPAS),
                        False: deque(maxlen=cfg.MEMORIA_RAMPAS)}
        self.validas = 0
        self.repetidos = 0
        self.fuera_de_rango = 0
        self.incoherentes = 0
        self.flancos = 0
        self.t_us = {True: deque(maxlen=40), False: deque(maxlen=40)}

    def flanco(self, pos, nivel, t_us=0):
        """Devuelve la Rampa que este flanco cierra, o None."""
        self.flancos += 1
        ant, self.ant = self.ant, (pos, nivel, t_us)
        if ant is None:
            return None
        if nivel == ant[1]:
            self.repetidos += 1
            return None
        largo = pos - ant[0]
        dur = largo / self.sps
        if not cfg.T_RAMPA_MIN <= dur <= cfg.T_RAMPA_MAX:
            self.fuera_de_rango += 1
            return None
        # La rampa arranco en `ant`: si ahi el sync quedo en alto, baja.
        sube = (ant[1] == 0) == cfg.SYNC_ALTO_ES_BAJADA
        vistas = self.ultimas[sube]
        ref = float(np.median(vistas)) if len(vistas) >= 3 else None
        vistas.append(largo)
        # Duracion por el reloj de la placa, independiente del eje de
        # muestras: sirve para ver el jitter del sync.
        self.t_us[sube].append(((t_us - ant[2]) & 0xFFFFFFFF) * 1e-6)
        if ref is not None and abs(largo - ref) > cfg.TOL_RAMPA * ref:
            self.incoherentes += 1
            return None
        self.validas += 1
        return Rampa(ant[0], pos, sube)

    def duracion(self, sube):
        """Mediana de las ultimas rampas de ese sentido [s], o None."""
        v = self.ultimas[sube]
        return float(np.median(v)) / self.sps if v else None

    def jitter_us(self, sube):
        """Desvio de la duracion de las ultimas rampas [us], o None."""
        v = self.t_us[sube]
        if len(v) < 5:
            return None
        v = np.asarray(v)
        return float(np.median(np.abs(v - np.median(v))) * 1.4826e6)
