"""
GPRv3 - El radar, sin ventana
=============================

`Radar` recibe los eventos de una fuente, corta las rampas, guarda los
perfiles y responde lo que la pantalla necesita: la matriz del radargrama,
el pico, el fondo, la puerta de deteccion y la calibracion. No sabe nada de
Qt, asi que lo usan igual `vivo.py`, `analizar.py` y `verificar.py`.
"""

import json
import math
import time

import numpy as np

import config as cfg
from proceso import Procesador, pico_parabolico
from rampas import Muestras, Rampa, Segmentador

SENTIDOS = ("ambas", "subida", "bajada")
LOTE = 128


class Calibracion:
    """d_real = a*d_crudo + b. Con un solo punto ajusta solo el offset: el
    retardo de los cables es un offset puro y la pendiente tiene que dar 1."""

    def __init__(self):
        self.a, self.b = 1.0, 0.0
        self.puntos = []          # [(d_crudo, d_real)]

    @property
    def activa(self):
        return self.a != 1.0 or self.b != 0.0

    def aplicar(self, d):
        return self.a * np.asarray(d) + self.b

    def crudo_de(self, d_real):
        return (d_real - self.b) / self.a if self.a else d_real

    def ajustar(self):
        if not self.puntos:
            return "no hay ningun punto tomado"
        crudo = np.array([p[0] for p in self.puntos])
        real = np.array([p[1] for p in self.puntos])
        if len(self.puntos) == 1 or np.ptp(crudo) < 1e-6:
            self.a, self.b = 1.0, float(real[0] - crudo[0])
            return f"solo offset: b={self.b:+.3f} m (pendiente fija en 1)"
        self.a, self.b = (float(x) for x in np.polyfit(crudo, real, 1))
        return f"a={self.a:.4f}  b={self.b:+.3f} m"

    def borrar(self):
        self.a, self.b = 1.0, 0.0
        self.puntos = []

    def guardar(self, ruta=cfg.CAL_JSON):
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"a": self.a, "b": self.b, "puntos": self.puntos,
                       "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)

    def cargar(self, ruta=cfg.CAL_JSON):
        try:
            with open(ruta, encoding="utf-8") as f:
                d = json.load(f)
            self.a, self.b = float(d["a"]), float(d["b"])
            self.puntos = [tuple(p) for p in d.get("puntos", [])]
            return d.get("fecha", "?")
        except (OSError, ValueError, KeyError):
            return None


class Radar:

    def __init__(self, curva, cal=None):
        self.curva = curva
        self.cal = cal or Calibracion()
        self.sps = None
        self.proc = None
        self.u_lo, self.u_hi = 0.0, 1.0
        # Atraso del batido respecto del sync [s]: corre los limites de las
        # rampas que se procesen de aca en mas (README, "Retardos").
        self.retardo = cfg.RETARDO_S

        # Lo que se elige en la pantalla.
        self.n_rampas = cfg.N_DEFECTO
        self.ventana = cfg.VENTANA_DEF
        self.alcance = cfg.ALCANCE_DEF
        self.ignorar = cfg.IGNORAR_DEF
        self.margen = cfg.MARGEN_DEF
        self.piso, self.techo = cfg.PISO_DEF, cfg.TECHO_DEF
        self.sentido = "ambas"
        self.en_metros = False
        self.ventana_fft = cfg.VENTANA_FFT_DEF
        self.mapa_color = cfg.MAPA_COLOR_DEF

        self.P = None
        self.ref_pantalla = 1.0
        self._cache = {}
        self.borrar_fondo()
        self.reiniciar(None)

    # --- entrada ---

    def reiniciar(self, sps):
        """Arranca de cero: lo llama cada paquete de informacion."""
        self.sps = sps
        self.muestras = Muestras()
        self.pend = []
        self.n_perf = 0
        self.sin_muestras = 0
        self.ultima = {True: None, False: None}   # (u, batido) de la ultima
        self.t_flanco = None
        self.seg = None
        self.marcas = []          # instantes en que se cambio algo
        self.n_filas = 0
        self._acum = None         # la fila que se esta juntando
        self._cache.clear()
        if sps:
            self.seg = Segmentador(sps)
            self.proc = Procesador(self.curva, sps)
            self.proc.fijar_ventana(self.u_lo, self.u_hi)
            self.proc.fijar_fft(self.ventana_fft)
            if self.P is None:
                cap = cfg.PERFILES_MAX + cfg.PERFILES_MAX // 4
                # Un perfil de potencia por rampa: de aca salen el pico, el
                # fondo y la puerta, que son siempre "lo de ahora".
                self.P = np.zeros((cap, self.proc.k), dtype=np.float32)
                self.tp = np.zeros(cap)
                self.sube = np.zeros(cap, dtype=bool)
                self.dur = np.zeros(cap, dtype=np.float32)
                # Las filas del radargrama, ya con el fondo restado. Una fila
                # se calcula al cerrarse y no se vuelve a tocar: lo que se
                # cambie despues vale de ahi en mas.
                self.F = np.zeros((cap, self.proc.k), dtype=np.float32)
                self.f_ini = np.zeros(cap)
                self.f_fin = np.zeros(cap)
                self.f_ref = np.zeros(cap)      # NaN: sin fondo
                self.f_n = np.zeros(cap, dtype=np.int32)

    def fijar_ventana(self, u_lo, u_hi):
        """Que parte de la rampa se usa (fracciones, 0 valle y 1 cima)."""
        self.u_lo, self.u_hi = float(u_lo), float(u_hi)
        if self.proc is not None:
            self.proc.fijar_ventana(self.u_lo, self.u_hi)

    def fijar_fft(self, nombre):
        """Ventana de la FFT, para las rampas que se procesen de aca en mas."""
        self.ventana_fft = nombre
        if self.proc is not None:
            self.proc.fijar_fft(nombre)

    def ahora(self):
        """El reloj de la placa [s] en la ultima rampa procesada."""
        return float(self.tp[self.n_perf - 1]) if self.n_perf else 0.0

    def marcar(self):
        """Anota que ahora se cambio algo: sale como una linea roja en el
        radargrama, para ver desde donde vale el cambio."""
        if self.n_perf and self.tp[self.n_perf - 1] not in self.marcas[-1:]:
            self.marcas.append(float(self.tp[self.n_perf - 1]))
            del self.marcas[:-200]

    def alimentar(self, ev):
        """Procesa lo que trajo `fuente.tomar()`. Devuelve rampas nuevas."""
        self._cache.clear()
        if ev.info is not None:
            self.reiniciar(ev.info["sps"])
        if not self.sps:
            return 0
        for idx0, v in self._pegar(ev.muestras):
            if not self.muestras.agregar(idx0, v):
                self.reiniciar(self.sps)          # la placa se reinicio
                self.muestras.agregar(idx0, v)
        for pos, nivel, t_us in ev.flancos:
            self.t_flanco = time.monotonic()
            r = self.seg.flanco(pos, nivel, t_us)
            if r is not None:
                d = self.retardo * self.sps
                self.pend.append(Rampa(r.a + d, r.b + d, r.sube))
        return self._procesar()

    @staticmethod
    def _pegar(paquetes):
        """Junta los paquetes de datos contiguos en tramos largos."""
        tramos = []
        for idx0, v in paquetes:
            if tramos and tramos[-1][0] + tramos[-1][1] == idx0:
                tramos[-1][1] += len(v)
                tramos[-1][2].append(v)
            else:
                tramos.append([idx0, len(v), [v]])
        return [(i, np.concatenate(vs)) for i, _, vs in tramos]

    def _procesar(self):
        m = cfg.MARGEN_MUESTRAS
        fin = self.muestras.fin
        listas = []
        while self.pend and math.ceil(self.pend[0].b) + m + 1 <= fin:
            r = self.pend.pop(0)
            i0, i1 = math.floor(r.a) - m, math.ceil(r.b) + m + 1
            if i0 < self.muestras.base or self.muestras.pisa_hueco(i0, i1):
                self.sin_muestras += 1
                continue
            listas.append(r)
        for k in range(0, len(listas), LOTE):
            lote = listas[k:k + LOTE]
            E = self.proc.procesar(self.muestras, lote)
            self._guardar(E, lote)
            if self.mti:
                self._actualizar_mti(E, sum(r.b - r.a for r in lote) / self.sps)
            self._armar_filas(E, lote)
        for r in listas[-2:]:
            self.ultima[r.sube] = self.proc.cruda(self.muestras, r)

        # Se conserva desde la rampa mas vieja que todavia no se proceso.
        desde = fin
        if self.pend:
            desde = self.pend[0].a
        elif self.seg.ant is not None:
            desde = self.seg.ant[0]
        tope = fin - int(2 * cfg.T_RAMPA_MAX * self.sps)
        self.muestras.descartar_hasta(max(int(desde) - m - 2, tope))
        return len(listas)

    def _guardar(self, E, rampas):
        n = len(rampas)
        cap = len(self.P)
        if self.n_perf + n > cap:
            quedan = cfg.PERFILES_MAX - n
            d = self.n_perf - quedan
            for a in (self.P, self.tp, self.sube, self.dur):
                a[:quedan] = a[d:self.n_perf]
            self.n_perf = quedan
        s = slice(self.n_perf, self.n_perf + n)
        self.P[s] = E
        self.tp[s] = [r.b / self.sps for r in rampas]
        self.sube[s] = [r.sube for r in rampas]
        self.dur[s] = [(r.b - r.a) / self.sps for r in rampas]
        self.n_perf += n

    def _armar_filas(self, E, rampas):
        """Junta rampas de a n_rampas (del sentido elegido) y cierra filas
        del radargrama, con el fondo y la referencia de ESE momento."""
        clave = (self.n_rampas, self.sentido)
        for i, r in enumerate(rampas):
            if self.sentido != "ambas" and r.sube != (self.sentido == "subida"):
                continue
            a = self._acum
            if a is None or a["clave"] != clave:
                # Cambio el agrupado o el sentido: la fila a medio juntar se
                # descarta y arranca una nueva.
                a = self._acum = {"clave": clave, "suma": np.zeros(self.proc.k),
                                  "n": 0, "ini": r.a / self.sps}
            a["suma"] += E[i]
            a["n"] += 1
            if a["n"] < self.n_rampas:
                continue
            if self.n_filas == len(self.F):
                d = self.n_filas - cfg.PERFILES_MAX
                for x in (self.F, self.f_ini, self.f_fin, self.f_ref, self.f_n):
                    x[:cfg.PERFILES_MAX] = x[d:self.n_filas]
                self.n_filas = cfg.PERFILES_MAX
            k = self.n_filas
            p = a["suma"] / a["n"]
            if self.fondo is None:
                self.F[k], self.f_ref[k] = p, np.nan
            else:
                # Resta en potencia, con piso en cero.
                self.F[k] = np.maximum(p - self.fondo, 0.0)
                self.f_ref[k] = self.fondo_ref
            self.f_ini[k], self.f_fin[k] = a["ini"], r.b / self.sps
            self.f_n[k] = a["n"]
            self.n_filas += 1
            self._acum = None

    @property
    def n_ef(self):
        """Rampas promediadas en la ultima fila."""
        return int(self.f_n[self.n_filas - 1]) if self.n_filas else self.n_rampas

    # --- ejes ---

    @property
    def eje_m_crudo(self):
        return self.proc.eje_m

    @property
    def eje_m(self):
        return self.cal.aplicar(self.proc.eje_m)

    def t_rampa(self):
        """Duracion media de una rampa [s] (promedio de subida y bajada)."""
        if self.seg is None:
            return None
        d = [x for x in (self.seg.duracion(True), self.seg.duracion(False)) if x]
        return sum(d) / len(d) if d else None

    def alpha0(self):
        """Pendiente nominal del barrido [Hz/s]: toda la banda en una rampa."""
        t = self.t_rampa()
        return self.proc.mapa.bw_total / t if t else None

    def hz_por_m(self):
        a = self.alpha0()
        return 2.0 * a / cfg.C if a else None

    def eje_x(self):
        if self.en_metros or not self.hz_por_m():
            return self.eje_m
        return self.eje_m_crudo * self.hz_por_m()

    def _i_zona(self):
        """Primer bin por encima de 'ignorar' (debajo, el acoplamiento)."""
        x = self.cal.crudo_de(self.ignorar)
        return int(np.clip(np.searchsorted(self.eje_m_crudo, x), 0,
                           self.proc.k - 2))

    def _i_alcance(self):
        x = self.cal.crudo_de(self.alcance)
        i1 = int(np.searchsorted(self.eje_m_crudo, x, "right")) + 1
        return int(np.clip(i1, self._i_zona() + 3, self.proc.k))

    # --- seleccion de perfiles ---

    def _indices(self, segundos):
        """Indices de los perfiles de los ultimos `segundos`, del sentido
        elegido, del mas viejo al mas nuevo."""
        n = self.n_perf
        if not n:
            return np.empty(0, dtype=np.intp)
        i0 = int(np.searchsorted(self.tp[:n], self.tp[n - 1] - segundos))
        idx = np.arange(i0, n)
        if self.sentido == "subida":
            idx = idx[self.sube[i0:n]]
        elif self.sentido == "bajada":
            idx = idx[~self.sube[i0:n]]
        return idx

    def _promedio(self, idx, i1=None):
        if self.sentido == "ambas":          # contiguos: sin copiar
            return self.P[idx[0]:idx[-1] + 1, :i1].mean(axis=0)
        return self.P[idx, :i1].mean(axis=0)

    def matriz(self):
        """El radargrama: dict con db (filas x bins visibles, la fila 0 es la
        mas vieja, NaN donde no hubo datos), el tiempo que abarca [s], los
        bordes del eje de distancia y hace cuanto fue cada marca de cambio.
        None si todavia no hay nada.

        Las filas guardadas duran lo que duraron (segun las rampas por fila y
        el Tprf de su momento): aca se llevan a una grilla pareja en tiempo.
        """
        n = self.n_filas
        if not n:
            return None
        ahora = float(self.f_fin[n - 1])
        j0 = int(np.searchsorted(self.f_fin[:n], ahora - self.ventana, "right"))
        j0 = min(j0, n - 1)
        ini, fin = self.f_ini[j0:n], self.f_fin[j0:n]
        t0 = max(ahora - self.ventana, float(ini[0]))
        span = ahora - t0
        if span <= 0:
            return None
        i1 = self._i_alcance()
        V = self.F[j0:n, :i1]
        ref = self.f_ref[j0:n].copy()
        libres = np.isnan(ref)
        if libres.any():
            # Sin fondo, 0 dB es el maximo de lo que se ve. Es una referencia
            # de color, no un dato: por eso es la unica que vale para atras.
            ref[libres] = float(V[libres].max()) + 1e-30
        self.ref_pantalla = float(ref[-1])
        D = 10 * np.log10(V / ref[:, None] + 1e-24)
        H = int(np.clip(round(span / float((fin - ini).min())), 1, cfg.MAX_FILAS))
        tc = t0 + (np.arange(H) + 0.5) * span / H
        k = np.minimum(np.searchsorted(fin, tc), len(fin) - 1)
        db = np.where((ini[k] <= tc)[:, None], D[k], np.nan)
        eje = self.eje_x()
        paso = float(eje[1] - eje[0])
        return {"db": db, "span": span, "d0": float(eje[0] - paso / 2),
                "d1": float(eje[i1 - 1] + paso / 2), "filas": H,
                "marcas": [ahora - x for x in self.marcas
                           if 0.0 <= ahora - x <= span]}

    def traza(self, m):
        """El pico de cada fila de `matriz()`: (distancia, segundos atras).
        Una fila cuyo pico no se despega de su mediana sale NaN, para no unir
        con una linea los maximos de filas que son puro ruido."""
        db = np.nan_to_num(m["db"], nan=-300.0)
        i0 = min(self._i_zona(), db.shape[1] - 1)
        i = i0 + np.argmax(db[:, i0:], axis=1)
        pico = db[np.arange(len(db)), i]
        x = self.eje_x()[i].astype(float)
        x[(pico - np.median(db[:, i0:], axis=1) < cfg.TRAZA_MIN_DB)
          | (pico < -250)] = np.nan
        filas = len(db)
        return x, m["span"] * (filas - np.arange(filas) - 0.5) / filas

    def fila_actual(self):
        """La ultima fila del radargrama, en todo el eje: (potencia con el
        fondo ya restado, referencia de 0 dB, si tenia fondo). None si no
        hay."""
        if not self.n_filas or self.matriz() is None:
            return None
        k = self.n_filas - 1
        return self.F[k], self.ref_pantalla, not np.isnan(self.f_ref[k])

    def perfil_actual(self, crudo=False):
        """Promedio de los ultimos PROMEDIO_CAL_S, con el fondo restado
        salvo que se pida crudo."""
        clave = "crudo" if crudo else "perfil"
        if clave not in self._cache:
            idx = self._indices(cfg.PROMEDIO_CAL_S)
            p = self._promedio(idx) if len(idx) else None
            self._cache["crudo"] = p
            self._cache["perfil"] = (p if p is None or self.fondo is None
                                     else np.maximum(p - self.fondo, 0.0))
        return self._cache[clave]

    # --- deteccion ---

    def energia_actual_db(self):
        if self.fondo is None:
            return None
        p = self.perfil_actual(crudo=True)
        if p is None:
            return None
        z = p[self._i_zona():]
        if self.mti:
            z = np.maximum(z - self.fondo[self._i_zona():], 0.0)
        return 10 * math.log10(float(z.sum())
                               / (self.fondo_energia + 1e-30) + 1e-30)

    def hay_blanco(self):
        """Sin fondo medido devuelve True: no hay contra que comparar."""
        if self.fondo is None:
            return True
        e = self.energia_actual_db()
        return e is not None and e >= self.margen

    def pico_crudo(self):
        """Distancia cruda del pico [m], o None si no hay blanco."""
        if "pico" not in self._cache:
            d = None
            perfil = self.perfil_actual() if self.hay_blanco() else None
            if perfil is not None:
                i0 = self._i_zona()
                i = i0 + int(np.argmax(perfil[i0:]))
                d = float(self.eje_m_crudo[i]
                          + pico_parabolico(perfil, i) * cfg.DR_M)
            self._cache["pico"] = d
        return self._cache["pico"]

    def picos_por_sentido(self):
        """(pico de las subidas, pico de las bajadas) [m crudos], buscados
        cerca del pico comun. Si el batido llega atrasado respecto del sync,
        uno se corre para un lado y el otro para el otro: la diferencia es la
        forma de ver ese atraso en el banco. None si no hay de las dos."""
        pico = self.pico_crudo()
        if pico is None:
            return None
        guardado, d = self.sentido, []
        try:
            for self.sentido in ("subida", "bajada"):
                idx = self._indices(cfg.PROMEDIO_CAL_S)
                if not len(idx):
                    return None
                a = max(int((pico - 0.3) / cfg.DR_M), 1)
                p = self._promedio(idx, a + int(0.6 / cfg.DR_M))
                if self.fondo is not None:
                    p = np.maximum(p - self.fondo[:len(p)], 0.0)
                i = a + int(np.argmax(p[a:]))
                d.append((i + pico_parabolico(p, i)) * cfg.DR_M)
        finally:
            self.sentido = guardado
        return tuple(d)

    # --- fondo ---

    def _fijar_fondo(self, perfil):
        self.fondo = perfil
        z = perfil[self._i_zona():]
        self.fondo_energia = float(z.sum())       # los perfiles son potencia
        # 0 dB pasa a ser "tan fuerte como lo mas fuerte que hay sin blanco".
        self.fondo_ref = float(max(z.max(), 1e-12))

    def recalcular_fondo(self):
        """Despues de cambiar 'ignorar': la puerta compara la zona nueva."""
        if self.fondo is not None:
            self._fijar_fondo(self.fondo)

    def medir_fondo(self):
        idx = self._indices(cfg.FONDO_S)
        if not len(idx):
            return "todavia no hay perfil"
        self.mti = False
        self._fijar_fondo(self._promedio(idx).copy())
        self.piso, self.techo = cfg.PISO_FONDO, cfg.TECHO_FONDO
        return f"fondo medido sobre {len(idx)} rampas"

    def borrar_fondo(self):
        self.fondo = None
        self.fondo_energia = 0.0
        self.fondo_ref = 1.0
        self.mti = False
        self.t_mti_ref = 0.0

    def alternar_mti(self):
        if self.mti:
            self.borrar_fondo()
            self.piso, self.techo = cfg.PISO_DEF, cfg.TECHO_DEF
            self.margen = cfg.MARGEN_DEF
            return "fondo automatico apagado"
        self.borrar_fondo()
        self.mti = True
        self.margen = cfg.MARGEN_MTI
        return f"fondo automatico: lo quieto se va en ~{cfg.TAU_MTI:.0f} s"

    def _actualizar_mti(self, E, dt):
        """Fondo automatico: promedio exponencial de los perfiles que llegan."""
        nuevo = E.mean(axis=0)
        if self.fondo is None:
            self._fijar_fondo(nuevo.copy())
            self.piso, self.techo = cfg.PISO_FONDO, cfg.TECHO_FONDO
            return
        self.fondo += (1.0 - math.exp(-dt / cfg.TAU_MTI)) * (nuevo - self.fondo)
        # La referencia de dB se rehace a lo sumo dos veces por segundo: si
        # no, la escala de color querria decir otra cosa en cada cuadro.
        if time.monotonic() - self.t_mti_ref > 0.5:
            self.t_mti_ref = time.monotonic()
            self._fijar_fondo(self.fondo)

    # --- informacion ---

    def hay_sync(self):
        return (self.t_flanco is not None
                and time.monotonic() - self.t_flanco < cfg.SIN_SYNC_S)

    def resumen(self):
        """Los numeros del barrido que muestran la pantalla y las capturas."""
        if self.proc is None:
            return None
        mp = self.proc.mapa
        ts, tb = self.seg.duracion(True), self.seg.duracion(False)
        tr = self.t_rampa()
        largo = tr * self.sps if tr else None
        r = {
            "sps": self.sps, "t_subida": ts, "t_bajada": tb,
            "tprf": ts + tb if ts and tb else None,
            "jitter_us": self.seg.jitter_us(True),
            "u_lo": mp.u_lo, "u_hi": mp.u_hi,
            "v_lo": mp.v_de_u(mp.u_lo), "v_hi": mp.v_de_u(mp.u_hi),
            "f_lo": mp.f_lo, "f_hi": mp.f_hi, "bw": mp.bw,
            "bw_total": mp.bw_total, "resolucion": cfg.C / (2 * mp.bw),
            "alpha0": self.alpha0(), "hz_por_m": self.hz_por_m(),
            "muestras_rampa": largo, "validas": self.seg.validas,
            "repetidos": self.seg.repetidos,
            "fuera_de_rango": self.seg.fuera_de_rango,
            "incoherentes": self.seg.incoherentes,
            "sin_muestras": self.sin_muestras,
            "huecos": len(self.muestras.huecos),
            "ventana_fft": self.ventana_fft, "retardo": self.retardo,
        }
        if largo:
            p = self.proc.afinado(largo)
            r["nfft"] = cfg.NFFT_BASE << p
            r["puntos"] = len(self.proc.grilla(p)[0])
            # Hasta donde llega el batido sin plegarse, en la parte de la
            # rampa donde el VCO barre mas rapido.
            dfdu_max = float(np.gradient(mp.f, mp.u)[
                (mp.u >= mp.u_lo) & (mp.u <= mp.u_hi)].max())
            r["no_ambiguo"] = cfg.C * self.sps * tr / (4 * dfdu_max)
        return r


class AjusteRetardo:
    """
    Mueve `radar.retardo` hasta que el pico de las subidas y el de las
    bajadas coincidan. Un atraso del batido corre uno para cada lado, asi que
    la diferencia es (casi) proporcional al error: se busca el cero por la
    secante. Despues de cada cambio espera rampas nuevas antes de medir.

    `paso()` se llama en cada refresco. Devuelve None mientras trabaja y un
    texto cuando termino (bien o mal).
    """

    def __init__(self, radar):
        self.r = radar
        self.inicial = radar.retardo
        self.puntos = []                    # [(retardo, diferencia)]
        self.t_cambio = radar.ahora()

    def _poner(self, x):
        x = min(max(x, -cfg.RETARDO_MAX_S), cfg.RETARDO_MAX_S)
        self.r.retardo = round(x * 1e5) / 1e5          # pasos de 10 us
        self.r.marcar()
        self.t_cambio = self.r.ahora()

    def _abandonar(self, motivo):
        self.r.retardo = self.inicial
        self.r.marcar()
        return f"retardo: {motivo}; queda como estaba"

    def paso(self):
        r = self.r
        # Todo el promedio del pico tiene que ser posterior al cambio.
        if r.ahora() - self.t_cambio < 1.3 * cfg.PROMEDIO_CAL_S:
            return None
        ps = r.picos_por_sentido()
        if ps is None:
            return self._abandonar("no hay un pico claro en los dos sentidos")
        self.puntos.append((r.retardo, ps[0] - ps[1]))
        x1, d1 = self.puntos[-1]
        if abs(d1) <= cfg.AUTO_TOL_M:
            return (f"retardo ajustado en {x1 * 1e3:+.2f} ms "
                    f"(subida - bajada {d1 * 100:+.1f} cm)")
        if len(self.puntos) >= cfg.AUTO_PASOS:
            return self._abandonar("no convergio")
        if len(self.puntos) == 1:
            self._poner(x1 + cfg.AUTO_PRIMER_PASO_S)
            return None
        x0, d0 = self.puntos[-2]
        if x1 == x0 or abs(d1 - d0) < 1e-5:
            return self._abandonar("mover el retardo no cambia la diferencia")
        self._poner(x1 - d1 * (x1 - x0) / (d1 - d0))
        return None
