"""
GPRv3 - Banco sintetico
=======================

Arma, sin hardware, los mismos paquetes que manda la placa: una triangular
con subida y bajada desparejas barre el VCO (con su curva real), cada blanco
deja su batido, y el resultado pasa por el mismo diezmado y la misma
ubicacion de flancos que el firmware. El diezmado y la cuenta de los flancos
son una copia en enteros de nucleo.h; `verificar.py` comprueba contra el C
compilado que dan bit a bit lo mismo.

Lo usan `vivo.py --sintetico` (para probar la ventana sin banco) y
`verificar.py`.
"""

import struct
from dataclasses import dataclass, field

import numpy as np

import config as cfg
import protocolo as pr

FS = 48000
BLOQUE = 256

HB = np.array([
    -135143, 0, 1143002, 0, -4050661, 0, 10527053, 0, -23184129, 0,
    47232807, 0, -99955210, 0, 336873039, 536840308, 336873039, 0,
    -99955210, 0, 47232807, 0, -23184129, 0, 10527053, 0, -4050661, 0,
    1143002, 0, -135143], dtype=np.int64)


def indice_flanco256(n_in_ult, t_bloque, t_flanco, fs, dec):
    """Copia de indiceFlanco256() de nucleo.h."""
    j = n_in_ult * 1000000 - (t_bloque - t_flanco) * fs
    j += 14 * (dec - 1) * 1000000
    if j < 0:
        return -1
    return (j // dec) * 256 // 1000000


class Diezmador:
    """La cascada de semibanda de nucleo.h, en enteros y por tandas."""

    def __init__(self, dec):
        self.n = int(dec).bit_length() - 1
        if dec != 1 << self.n or not 1 <= self.n <= 4:
            raise ValueError("dec tiene que ser 2, 4, 8 o 16")
        self.hist = [np.zeros(30, dtype=np.int64) for _ in range(self.n)]

    def pasar(self, x):
        """x: int64, largo multiplo de dec. Devuelve len(x)/dec muestras."""
        for e in range(self.n):
            xp = np.concatenate([self.hist[e], x])
            self.hist[e] = xp[-30:]
            v = np.lib.stride_tricks.sliding_window_view(xp, 31)[1::2]
            x = (v @ HB) >> 30
        return x


@dataclass
class Banco:
    """La verdad del banco simulado."""
    sps: int = cfg.SPS_DEF
    tprf: object = 0.100            # s, o una funcion t -> s (pote moviendose)
    frac_subida: float = 0.505      # medido: 50,5 ms de subida en 100
    v_min: float = cfg.V_MIN
    v_max: float = cfg.V_MAX
    # (distancia aparente [m] o funcion t -> m, amplitud en cuentas del ADC)
    blancos: list = field(default_factory=lambda: [(1.61, 8e5), (3.70, 2e5)])
    ruido: float = 2e4              # cuentas rms a 48 kHz
    retardo: float = 0.0            # s, atraso del batido respecto del sync
    jitter_us: float = 0.0          # rms del instante de cada flanco
    sync_alto_es_bajada: bool = True
    fase_inicial: float = 0.0137    # s, para no arrancar justo en un vertice


class Generador:

    def __init__(self, banco, curva, semilla=0):
        self.b = banco
        self.curva = curva
        self.dec = FS // banco.sps
        self.rng = np.random.default_rng(semilla)
        self.fases = self.rng.uniform(0, 2 * np.pi, len(banco.blancos))
        self.diez = Diezmador(self.dec)
        self.j = 0                    # tramas de entrada generadas
        self.n_out = 0
        self.flancos = 0
        self.arrancado = False
        # Vertices de la triangular: instante y si es un valle.
        t0 = banco.fase_inicial - 2 * self._tprf(0.0)
        self.tv = [t0]
        self.valle = [True]
        self.k_flanco = 1             # proximo vertice a informar

    def _tprf(self, t):
        return self.b.tprf(t) if callable(self.b.tprf) else self.b.tprf

    def _extender(self, t):
        while self.tv[-1] <= t:
            T = self._tprf(self.tv[-1])
            f = self.b.frac_subida if self.valle[-1] else 1 - self.b.frac_subida
            self.tv.append(self.tv[-1] + T * f)
            self.valle.append(not self.valle[-1])

    def frecuencia(self, t):
        """Frecuencia del VCO en los instantes t (creciente)."""
        self._extender(t[-1])
        tv = np.asarray(self.tv)
        i = np.searchsorted(tv, t, "right") - 1
        u = (t - tv[i]) / (tv[i + 1] - tv[i])
        u = np.where(np.asarray(self.valle)[i], u, 1.0 - u)
        return self.curva(self.b.v_min + (self.b.v_max - self.b.v_min) * u)

    def crudo(self, n_bloques):
        """(muestras a 48 kHz en int64, [(t_us, nivel)] de los flancos)."""
        n = n_bloques * BLOQUE
        t = (self.j + 1 + np.arange(n)) / FS
        f = self.frecuencia(t - self.b.retardo)
        x = self.rng.normal(0.0, self.b.ruido, n) if self.b.ruido else np.zeros(n)
        for (d, amp), fase in zip(self.b.blancos, self.fases):
            dist = d(t) if callable(d) else d
            x += amp * np.cos(2 * np.pi * (2.0 * dist / cfg.C) * f + fase)
        x = np.clip(np.rint(x), -8388608, 8388607).astype(np.int64)

        flancos = []
        self._extender(t[-1])
        while self.k_flanco < len(self.tv) and self.tv[self.k_flanco] <= t[-1]:
            tv = self.tv[self.k_flanco]
            if tv > 0:
                t_us = int(round(tv * 1e6 + self.rng.normal(0, self.b.jitter_us)
                                 if self.b.jitter_us else tv * 1e6))
                # En un valle arranca la subida: el sync baja.
                nivel = int(self.valle[self.k_flanco]
                            != self.b.sync_alto_es_bajada)
                flancos.append((t_us, nivel))
            self.k_flanco += 1
        self.j += n
        sobran = len(self.tv) - 32      # los vertices viejos no hacen falta
        if sobran > 32:
            del self.tv[:sobran], self.valle[:sobran]
            self.k_flanco -= sobran
        return x, flancos

    def bloques(self, n_bloques):
        """Los paquetes de `n_bloques` bloques de DMA, como los manda la placa."""
        salida = []
        if not self.arrancado:
            salida.append(pr.info(FS, self.dec))
            self.arrancado = True
        j0 = self.j
        x, flancos = self.crudo(n_bloques)
        y = self.diez.pasar(x)
        por_bloque = BLOQUE // self.dec
        k = 0
        for b in range(n_bloques):
            n_in_ult = j0 + (b + 1) * BLOQUE - 1
            t_bloque = ((n_in_ult + 1) * 1000000 + FS // 2) // FS
            # En el ultimo bloque salen todos los que queden: el redondeo a
            # microsegundos puede dejar alguno un pelo despues del final.
            ultimo = b == n_bloques - 1
            while k < len(flancos) and (ultimo or flancos[k][0] <= t_bloque):
                idx = indice_flanco256(n_in_ult, t_bloque, flancos[k][0],
                                       FS, self.dec)
                if idx >= 0:
                    salida.append(pr.sync(idx, flancos[k][1], flancos[k][0]))
                k += 1
                self.flancos += 1
            salida.append(pr.datos(self.n_out,
                                   y[b * por_bloque:(b + 1) * por_bloque]))
            self.n_out += por_bloque
        return b"".join(salida)

    def entrada_c(self, n_bloques):
        """El mismo tramo, en el formato que lee firmware/prueba_pc."""
        x, flancos = self.crudo(n_bloques)
        cab = struct.pack("<IIIIq", FS, self.dec, len(x), len(flancos), 0)
        cuerpo = x.astype("<i4").tobytes()
        cola = b"".join(struct.pack("<qB", t, n) for t, n in flancos)
        return cab + cuerpo + cola


def banco_demo():
    """Lo que muestra `vivo.py --sintetico`: el acoplamiento directo, una
    pared quieta y una placa que va y viene."""
    def placa(t):
        return 2.9 + 0.5 * np.sin(2 * np.pi * t / 20.0)
    return Banco(blancos=[(1.61, 8e5), (4.20, 1.2e5), (placa, 2.5e5)])
