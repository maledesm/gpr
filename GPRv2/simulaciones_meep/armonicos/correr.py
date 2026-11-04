"""
GPRv2 - Armonicos del VCO: simulacion contra las capturas del 2026-09-28
========================================================================

    python correr.py               las dos sondas (adaptada y corto)
    python correr.py adaptada      una sola

Necesita las escenas de MEEP de banda ancha en salidas/<sonda>/ (las corre
GPRv2/simular_armonicos.bat). Las figuras y el resumen van aparte, en
figuras/<sonda>/, para no mezclarlos con los datos de MEEP:

    entradas.png              lo que entra al modelo y de donde sale
    cascada_1m.png            de lo ideal a lo real, una cosa por vez (placa a 1 m)
    medido_vs_simulado.png    las cinco distancias, cf y sf, contra lo medido
    fantasmas.png             el fantasma de un blanco segun el modelo, y la potencia
                              en las bandas donde caen, medida contra simulada
    generador_propio.png      escenario B: la LM324 (prediccion)
    fuga.png                  variante con un camino de fuga ajustado
    resumen.txt               todos los numeros (los del blanco puntual, solo aca)

Los resultados y como leerlos: LEEME.md.

Que se compara con que: las capturas "cf" (fondo sin medir) contra la escena
completa, y las "sf" (fondo congelado) contra placa con el fondo de la escena
vacia restado EN MODULO, como lo hace vivo_rapido (no la resta compleja de
relevar.py). Cada curva en dB respecto de su propio maximo.
"""

import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402
from scipy import signal                                          # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import parametros as P                                            # noqa: E402
import radar as R                                                 # noqa: E402
import sintesis as S                                              # noqa: E402

CAPTURAS = os.path.join(P.GPRV2, "datos", "capturas")
XMAX = 2500.0             # Hz: arriba de 2400 el diezmado ya no limpia
PISO = -60.0
VENTANA_FANTASMA = 15.0   # Hz alrededor de n*f_placa donde se busca el fantasma
MED, SIM, IDEAL = "0.1", "C3", "0.55"


def leer_captura(d, tipo):
    ruta = os.path.join(CAPTURAS, f"placa_{round(d * 100)}cm_{tipo}.csv")
    x = np.genfromtxt(ruta, delimiter=",", comments="#", names=True)
    return x["f_hz"], x["mag"]


def pico(hz, mag, desde=100.0, hasta=900.0):
    """(Hz, dB respecto del maximo de la curva) del maximo en la ventana."""
    m = (hz >= desde) & (hz <= hasta)
    i = np.flatnonzero(m)[np.argmax(mag[m])]
    return float(hz[i]), float(S.db_norm(mag)[i])


BANDAS = [(150.0, 400.0), (650.0, 1400.0), (1400.0, 2300.0)]   # Hz: abajo, 2f, 3f


def potencia_banda(hz, mag, lo, hi):
    """Potencia media en [lo, hi] en dB, respecto del maximo de la curva."""
    m = (hz >= lo) & (hz <= hi)
    return float(10 * np.log10(np.mean(mag[m] ** 2) / mag.max() ** 2))


# Blanco puntual: un retardo puro, sin escena. La distancia aparente es la de
# la placa a 1 m en las capturas (509,7 Hz / 138,6 Hz/m). Sirve para ver lo
# que pone el RADAR (VCO, triangular, armonicos, software) sin lo que pone la
# escena (la placa - vacio de MEEP trae la pared tapada con signo menos).
D_AP_PUNTUAL = 3.677


def metricas_puntual(M, kw, kwb=None):
    """Texto con pico, ancho a -6 dB, lobulo y fantasmas de un blanco puntual."""
    tau = 2 * D_AP_PUNTUAL / R.C
    esc = {"placa": S.SoloFuga(tau), "vacio": S.SoloFuga(tau)}
    pr, cf, _ = M.correr(P.D_NORMALIZA, escenas=esc, **kw, **(kwb or {}))
    fb, _ = pico(pr.hz, cf)
    db = S.db_norm(cf)
    i = int(np.argmin(np.abs(pr.hz - fb)))
    izq, der = i, i
    while izq > 0 and db[izq] > -6:
        izq -= 1
    while der < len(db) - 1 and db[der] > -6:
        der += 1
    lob = max(db[(np.abs(pr.hz - fb) > 45) & (np.abs(pr.hz - fb) < 250)])
    return (f"pico {fb:6.1f} Hz  ancho {pr.hz[der]-pr.hz[izq]:5.1f} Hz  lobulo {lob:6.1f}  "
            f"2f {nivel_en(pr.hz, cf, 2*fb):6.1f}  3f {nivel_en(pr.hz, cf, 3*fb):6.1f} dB")


class Diferencia:
    """Una escena menos otra, en complejo: el eco de la placa solo."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def __call__(self, f, n=1):
        return self.a(f, n) - self.b(f, n)


def nivel_en(hz, mag, f0, ancho=VENTANA_FANTASMA):
    """dB (respecto del maximo de la curva) del maximo a +-ancho de f0.

    Con el fondo restado en modulo hay bins en cero exacto: se recorta en
    -99 para que no salgan -240 dB que no significan nada.
    """
    m = np.abs(hz - f0) <= ancho
    return max(float(S.db_norm(mag)[m].max()), -99.0)


class Modelo:
    """Todo lo que no cambia entre corridas de una misma sonda."""

    def __init__(self, sonda):
        self.sonda = sonda
        self.dir = os.path.join(P.SALIDAS_RAIZ, sonda)
        self.cv, self.cc = S.curvas()
        self.env = S.envolventes()
        self.sos, self.filtro = S.cadena_if()
        t0 = time.time()
        self.placa = {}
        for d in P.BARRIDO:
            ruta = os.path.join(self.dir, "H_placa_" + f"{d:.2f}".replace(".", "p") + ".npz")
            self.placa[d] = S.Escena(ruta)
        self.vacio = S.Escena(os.path.join(self.dir, "H_vacio_barrido.npz"))
        tri = S.tri_sdg(self.cv)
        f_barrido = tri.f(np.linspace(0, tri.T / 2, 2000))
        self.g = S.normalizacion(self.placa[P.D_NORMALIZA], self.vacio, f_barrido)
        for e in list(self.placa.values()) + [self.vacio]:
            e.g = self.g
        print(f"  escenas de {sonda}: {time.time() - t0:.0f} s; cadena plana: "
              f"g2 = {20*np.log10(self.g[1]):+.1f} dB, g3 = {20*np.log10(self.g[2]):+.1f} dB")

    def correr(self, d, tri, curva_soft, v_soft, cadena=True, arm=(1,),
               a3=None, modelo="multiplicador", psi=0.0, ruido=0.0,
               ajuste_soft=False, fuga=None, complejo=False, escenas=None):
        """Una distancia: (Procesado, perfil cf, perfil sf)."""
        if escenas is None:
            pl, va = self.placa[d], self.vacio
            if fuga is not None:
                pl, va = pl.con_fuga(fuga), va.con_fuga(fuga)
            escenas = {"placa": pl, "vacio": va}
        co = S.Corrida(tri, escenas, self.env, modelo=modelo, a3_dbc=a3,
                       psi=np.radians(psi), armonicos=arm, cadena=cadena,
                       ruido=ruido, sos=self.sos)
        pr = S.Procesado(co, curva_soft, v_soft, ajuste_soft=ajuste_soft,
                         complejo=complejo)
        if complejo:
            return pr, None, None
        cf = pr.perfil("placa")
        sf = np.maximum(cf - pr.fondo("vacio"), 0.0)
        return pr, cf, sf


def tri_lineal(cv):
    """VCO ideal: lineal entre los mismos extremos que la curva real."""
    f0, f1 = float(cv(P.V_SDG[0])), float(cv(P.V_SDG[1]))
    lin = lambda v: f0 + (f1 - f0) * (np.asarray(v) - P.V_SDG[0]) / (P.V_SDG[1] - P.V_SDG[0])
    tri = S.tri_sdg(cv)
    tri.f_de_v = lin
    tri.nombre = "SDG830, VCO lineal"
    return tri, lin


def pasos_cascada(M, sigma):
    tri_l, lin = tri_lineal(M.cv)
    tri = S.tri_sdg(M.cv)
    v = P.V_SDG
    a3 = P.A3_DBC_CASCADA
    return [
        ("0  ideal: VCO lineal, triangular perfecta, solo f, sin cadena de IF",
         dict(tri=tri_l, curva_soft=lin, v_soft=v, cadena=False)),
        ("1  + cadena de IF y firmware", dict(tri=tri_l, curva_soft=lin, v_soft=v)),
        ("2  + VCO real, corregido con su propia curva",
         dict(tri=tri, curva_soft=M.cv, v_soft=v)),
        ("3  + corregido con la curva vieja (la del software)",
         dict(tri=tri, curva_soft=M.cc, v_soft=v)),
        ("4  + 2º armónico (Max Hold), mezclador multiplicador",
         dict(tri=tri, curva_soft=M.cc, v_soft=v, arm=(1, 2))),
        (f"5  + 3er armónico a {a3:g} dBc (supuesto)",
         dict(tri=tri, curva_soft=M.cc, v_soft=v, arm=(1, 2, 3), a3=a3)),
        ("6  + ruido blanco al piso medido",
         dict(tri=tri, curva_soft=M.cc, v_soft=v, arm=(1, 2, 3), a3=a3, ruido=sigma)),
    ]


def calibrar_ruido(M):
    """sigma del ruido blanco que da el piso medido en RUIDO_BANDA (cf, 1 m)."""
    tri = S.tri_sdg(M.cv)
    d = P.D_NORMALIZA
    _, cf, _ = M.correr(d, tri, M.cc, P.V_SDG, arm=(1, 2, 3), a3=P.A3_DBC_CASCADA)
    pr, cfr, _ = M.correr(d, tri, M.cc, P.V_SDG, escenas={"placa": lambda f, n=1: 0 * f,
                                                          "vacio": lambda f, n=1: 0 * f},
                          ruido=1.0)
    hz_m, mag_m = leer_captura(d, "cf")
    b = (hz_m >= P.RUIDO_BANDA[0]) & (hz_m <= P.RUIDO_BANDA[1])
    piso_med = np.median(S.db_norm(mag_m)[b])
    b = (pr.hz >= P.RUIDO_BANDA[0]) & (pr.hz <= P.RUIDO_BANDA[1])
    piso_1 = np.median(20 * np.log10(cfr[b] / cf.max()))
    return 10 ** ((piso_med - piso_1) / 20), piso_med


def marcas(a, f_b, color="0.5"):
    for n, ls in ((2, "--"), (3, ":")):
        a.axvline(n * f_b, color=color, ls=ls, lw=0.8)


def main():
    sondas = sys.argv[1:] or ["adaptada", "corto"]
    for sonda in sondas:
        correr_sonda(sonda)


def correr_sonda(sonda):
    M = Modelo(sonda)
    figs = os.path.join(AQUI, "figuras", sonda)
    os.makedirs(figs, exist_ok=True)
    out = lambda nombre: os.path.join(figs, nombre)
    log = open(out("resumen.txt"), "w", encoding="utf-8")

    def say(*a):
        s = " ".join(str(x) for x in a)
        print(s)
        log.write(s + "\n")

    fe, a1, a2 = M.env
    banda = (fe >= P.F_PISO_B) & (fe <= P.F_TOPE_B)
    say("=" * 78)
    say(f"Armonicos del VCO - sonda {sonda} - {time.strftime('%Y-%m-%d %H:%M')}")
    say("=" * 78)
    say(f"MEEP: banda {P.F_MIN/1e9:.2f}-{P.F_MAX/1e9:.2f} GHz, resolucion {P.RESOLUCION}, "
        f"placa {P.BARRIDO} m, pared {P.MURO_DIST} m")
    say(f"cadena plana: g2 {20*np.log10(M.g[1]):+.1f} dB, g3 {20*np.log10(M.g[2]):+.1f} dB "
        f"(lo que se reescala H del aire a 2f y 3f)")
    say(f"fundamental (Max Hold): {a1[banda].min():+.1f} a {a1[banda].max():+.1f} dB; "
        f"2o armonico {a2[banda].min():.1f} a {a2[banda].max():.1f} dBc")
    say(f"filtro post-mezclador G=1 ajustado: pasaaltos 1er orden {M.filtro[0]:.0f} Hz, "
        f"pasabajos Butterworth orden {M.filtro[1]} en {M.filtro[2]/1e3:.1f} kHz")

    sigma, piso_med = calibrar_ruido(M)
    say(f"ruido: piso medido (cf, 1 m, {P.RUIDO_BANDA[0]:.0f}-{P.RUIDO_BANDA[1]:.0f} Hz) "
        f"{piso_med:.1f} dB -> sigma {sigma:.3g}")

    # ---------------------------------------------------------------- cascada
    pasos = pasos_cascada(M, sigma)
    res = {}           # (paso, d) -> (hz, cf, sf)
    for i, (nombre, kw) in enumerate(pasos):
        for d in P.BARRIDO:
            pr, cf, sf = M.correr(d, **kw)
            res[i, d] = (pr.hz, cf, sf)
    say("\n--- Cascada: pico de la placa y fantasmas (cf | sf), dB respecto del maximo")
    say(f"  {'paso':58s} {'d':>5s} {'f_placa':>8s} {'2f':>7s} {'3f':>7s} | {'f_placa':>8s} {'2f':>7s} {'3f':>7s}")
    for i, (nombre, _) in enumerate(pasos):
        for d in P.BARRIDO:
            hz, cf, sf = res[i, d]
            fb_c, _ = pico(hz, cf)
            fb_s, _ = pico(hz, sf)
            say(f"  {nombre[:58]:58s} {d:5.2f} {fb_c:8.1f} {nivel_en(hz, cf, 2*fb_c):7.1f} "
                f"{nivel_en(hz, cf, 3*fb_c):7.1f} | {fb_s:8.1f} {nivel_en(hz, sf, 2*fb_s):7.1f} "
                f"{nivel_en(hz, sf, 3*fb_s):7.1f}")
    say(f"\n--- La cascada con un blanco puntual a {D_AP_PUNTUAL:.2f} m aparentes (sin MEEP)")
    for nombre, kw in pasos:
        say(f"  {nombre[:58]:58s} " + metricas_puntual(M, kw))
    say("\n--- Medido (28-09): pico y nivel donde caerian los fantasmas")
    for d in P.BARRIDO:
        linea = f"  {d:5.2f} m"
        for tipo in ("cf", "sf"):
            hz, mag = leer_captura(d, tipo)
            fb, _ = pico(hz, mag)
            linea += (f"   {tipo}: f_placa {fb:6.1f}  en 2f {nivel_en(hz, mag, 2*fb):6.1f}"
                      f"  en 3f {nivel_en(hz, mag, 3*fb):6.1f}")
        say(linea)

    # figura: cascada a 1 m
    d = P.D_NORMALIZA
    fig, axs = plt.subplots(len(pasos), 2, figsize=(15, 2.1 * len(pasos)), sharex=True,
                            sharey=True, squeeze=False)
    for j, tipo in enumerate(("cf", "sf")):
        hz_m, mag_m = leer_captura(d, tipo)
        for i, (nombre, _) in enumerate(pasos):
            a = axs[i, j]
            hz, cf, sf = res[i, d]
            y = cf if tipo == "cf" else sf
            a.plot(hz_m, S.db_norm(mag_m), color=MED, lw=0.8, alpha=0.45, label="medido 28-09")
            a.plot(hz, S.db_norm(y), color=SIM if i else IDEAL, lw=1.1, label="simulado")
            fb, _ = pico(hz, y)
            marcas(a, fb)
            a.text(0.995, 0.92, nombre, transform=a.transAxes, ha="right", va="top",
                   fontsize=8.5, bbox=dict(fc="w", ec="none", alpha=0.85))
            a.grid(alpha=0.3)
            if i == 0:
                a.set_title("fondo sin medir (cf) — escena completa" if tipo == "cf" else
                            "fondo congelado (sf) — placa con el vacío restado en módulo",
                            fontsize=10)
                a.legend(loc="lower left", fontsize=8)
    axs[0, 0].set_xlim(0, XMAX)
    axs[0, 0].set_ylim(PISO, 3)
    for a in axs[-1]:
        a.set_xlabel("frecuencia de batido [Hz]   (-- 2f, ··· 3f de la placa)")
    for a in axs[:, 0]:
        a.set_ylabel("dB", fontsize=8)
    fig.suptitle(f"Placa a {d:.2f} m: de lo ideal a lo real, agregando una cosa por vez "
                 f"(sonda {sonda})", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    R.guardar_figura(fig, out("cascada_1m.png"))
    plt.close(fig)

    # figura: las cinco distancias, ideal y final contra lo medido
    final = len(pasos) - 2           # sin ruido: se ve mejor que es cada pico
    fig, axs = plt.subplots(len(P.BARRIDO), 2, figsize=(15, 2.3 * len(P.BARRIDO)),
                            sharex=True, sharey=True, squeeze=False)
    for i, d in enumerate(P.BARRIDO):
        for j, tipo in enumerate(("cf", "sf")):
            a = axs[i, j]
            hz_m, mag_m = leer_captura(d, tipo)
            a.plot(hz_m, S.db_norm(mag_m), color=MED, lw=1.1, label="medido 28-09")
            for k, col, ls, et in ((0, IDEAL, "--", "ideal (paso 0)"),
                                   (final, SIM, "-", "simulado (paso 5)")):
                hz, cf, sf = res[k, d]
                a.plot(hz, S.db_norm(cf if tipo == "cf" else sf), color=col, ls=ls, lw=1.0,
                       label=et)
            fb, _ = pico(*res[final, d][:2]) if tipo == "cf" else pico(res[final, d][0], res[final, d][2])
            marcas(a, fb, SIM)
            a.text(0.01, 0.9, f"{d*100:.0f} cm", transform=a.transAxes, fontweight="bold",
                   va="top")
            a.grid(alpha=0.3)
            if i == 0:
                a.set_title("cf — escena completa" if tipo == "cf" else
                            "sf — fondo restado en módulo", fontsize=10)
                a.legend(fontsize=8, loc="upper right")
    axs[0, 0].set_xlim(0, XMAX)
    axs[0, 0].set_ylim(PISO, 3)
    for a in axs[-1]:
        a.set_xlabel("frecuencia de batido [Hz]   (líneas rojas: 2f -- y 3f ··· de la placa simulada)")
    fig.suptitle(f"Medido (28-09, SDG830) contra simulado, sonda {sonda}", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    R.guardar_figura(fig, out("medido_vs_simulado.png"))
    plt.close(fig)

    # --------------------------------------------------------- sensibilidad
    # (1) El fantasma de UN blanco: solo el eco de la placa (placa - vacio en
    # complejo, sin pared ni acoplamiento), para que no se mezcle con nada.
    say("\n--- Fantasma de la placa sola (placa - vacio en complejo), cf, dB respecto del eco;"
        " promedio [min, max] sobre las 5 distancias")
    tri = S.tri_sdg(M.cv)
    variantes = []
    for a3 in P.A3_DBC:
        variantes.append((f"multiplicador, 3o {('sin' if a3 is None else f'{a3:g} dBc')}",
                          dict(modelo="multiplicador", a3=a3)))
    for psi in P.PSI_GRADOS:
        for a3 in (None, P.A3_DBC_CASCADA):
            variantes.append((f"conmutado psi {psi:g}°, 3o {('sin' if a3 is None else f'{a3:g} dBc')}",
                              dict(modelo="conmutado", psi=psi, a3=a3)))
    variantes.append(("sin armónicos (paso 3)", dict(arm=(1,))))
    tabla = []
    for nombre, kw in variantes:
        kw = {"arm": (1, 2, 3), **kw}
        n2s, n3s = [], []
        for d in P.BARRIDO:
            sola = {"placa": Diferencia(M.placa[d], M.vacio), "vacio": Diferencia(M.vacio, M.vacio)}
            pr, cf, _ = M.correr(d, tri, M.cc, P.V_SDG, escenas=sola, **kw)
            fb, _ = pico(pr.hz, cf)
            n2s.append(nivel_en(pr.hz, cf, 2 * fb))
            n3s.append(nivel_en(pr.hz, cf, 3 * fb))
        tabla.append((nombre, np.array(n2s), np.array(n3s)))
        say(f"  {nombre:32s} 2f {np.mean(n2s):6.1f} [{min(n2s):6.1f}, {max(n2s):6.1f}]   "
            f"3f {np.mean(n3s):6.1f} [{min(n3s):6.1f}, {max(n3s):6.1f}] dB")
    say(f"\n--- Lo mismo con un blanco puntual a {D_AP_PUNTUAL:.2f} m aparentes (sin MEEP): "
        f"el fantasma 'puro'")
    for nombre, kw in variantes:
        kw = {"arm": (1, 2, 3), **kw}
        say(f"  {nombre:32s} " + metricas_puntual(M, dict(tri=tri, curva_soft=M.cc,
                                                           v_soft=P.V_SDG, **kw)))

    # (2) La potencia en las bandas donde caen los fantasmas de TODOS los
    # caminos (acoplamiento, placa, pared): medido contra cada paso.
    say(f"\n--- Potencia media en bandas (cf, dB respecto del maximo): medido contra la cascada")
    linea = f"  {'':58s}" + "".join(f" {a:4.0f}-{b:<4.0f}" for a, b in BANDAS)
    say(linea)
    pot = {}
    for d in P.BARRIDO:
        hz, mag = leer_captura(d, "cf")
        pot["medido", d] = [potencia_banda(hz, mag, *b) for b in BANDAS]
    for i, (nombre, _) in enumerate(pasos):
        for d in P.BARRIDO:
            hz, cf, _ = res[i, d]
            pot[i, d] = [potencia_banda(hz, cf, *b) for b in BANDAS]
    for clave, nombre in [("medido", "medido 28-09")] + list(enumerate(n for n, _ in pasos)):
        v = np.array([pot[clave, d] for d in P.BARRIDO])
        say(f"  {nombre[:58]:58s}" + "".join(f" {x:9.1f}" for x in v.mean(axis=0)))

    fig, (a, b) = plt.subplots(1, 2, figsize=(16, 6.5), gridspec_kw=dict(width_ratios=[1.1, 1]))
    y = np.arange(len(tabla))
    for k, (col, et) in enumerate((("C0", "fantasma 2f"), ("C1", "fantasma 3f"))):
        med = np.array([t[1 + k].mean() for t in tabla])
        lo = np.array([t[1 + k].min() for t in tabla])
        hi = np.array([t[1 + k].max() for t in tabla])
        yy = y + (k - 0.5) * 0.4
        a.barh(yy, med - PISO, left=PISO, height=0.4, color=col, alpha=0.85, label=et)
        a.errorbar(med, yy, xerr=[med - lo, hi - med], fmt="none", ecolor="k", lw=0.8)
    a.set_yticks(y, [t[0] for t in tabla], fontsize=8.5)
    a.invert_yaxis()
    a.set_xlim(PISO, 0)
    a.set_xlabel("dB respecto del eco de la placa (placa sola, cf; barra: promedio de las "
                 "5 distancias, línea: rango)")
    a.set_title("El fantasma de un blanco aislado, según el modelo", fontsize=10)
    a.legend(fontsize=8, loc="lower right")
    a.grid(alpha=0.3, axis="x")
    x = np.arange(len(BANDAS))
    claves = [("medido", "medido 28-09", "k")] + [(i, n[:2].strip() + " " + n[3:].strip()[:38], c)
                                                  for (i, (n, _)), c in zip(
                                                      enumerate(pasos), ["0.75", "0.6", "C2", "C4", "C0", "C3", "C1"])
                                                  if i in (0, 3, 4, 5)]
    ancho = 0.8 / len(claves)
    for j, (clave, et, col) in enumerate(claves):
        v = np.array([pot[clave, d] for d in P.BARRIDO])
        xx = x + (j - (len(claves) - 1) / 2) * ancho
        b.bar(xx, v.mean(axis=0) - PISO, bottom=PISO, width=ancho, color=col, label=et)
        b.errorbar(xx, v.mean(axis=0), yerr=[v.mean(axis=0) - v.min(axis=0),
                                             v.max(axis=0) - v.mean(axis=0)],
                   fmt="none", ecolor="k", lw=0.8)
    b.set_xticks(x, [f"{lo:.0f}–{hi:.0f} Hz" for lo, hi in BANDAS])
    b.set_ylim(PISO, -10)
    b.set_ylabel("potencia media en la banda, dB respecto del máximo (cf)")
    b.set_title("Dónde caen los fantasmas de todos los caminos: medido contra la cascada",
                fontsize=10)
    b.grid(alpha=0.3, axis="y")
    b.legend(fontsize=8)
    fig.suptitle(f"Fantasmas de los armónicos (sonda {sonda})", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    R.guardar_figura(fig, out("fantasmas.png"))
    plt.close(fig)

    # ------------------------------------------------- escenario B: LM324
    say("\n--- Escenario B: generador propio (LM324), prediccion, placa a 1 m")
    tm = S.tri_lm324_medida(M.cv)
    tl = S.tri_lm324_ltspice(M.cv)
    say(f"  triangular medida: T {tm.T*1e3:.2f} ms, {tm.vmin:.3f}-{tm.vmax:.3f} V, subida "
        f"{100*tm.frac_sube:.2f} % del periodo; LTspice: subida {100*tl.frac_sube:.2f} %")
    say(f"  hipotesis Max Hold: corrimiento {tm.offset:+.3f} V (lleva {tm.vmin:.2f} V a "
        f"{P.F_PISO_B/1e6:.0f} MHz), recorte en {P.F_TOPE_B/1e6:.0f} MHz")
    v_act = (tm.vmin, tm.vmax)
    kwb = dict(arm=(1, 2, 3), a3=P.A3_DBC_CASCADA)
    casos_b = [
        ("A: SDG830 (paso 5)", dict(tri=S.tri_sdg(M.cv), curva_soft=M.cc, v_soft=P.V_SDG)),
        ("B1: LM324 medida, software de hoy (0-3 V)",
         dict(tri=tm, curva_soft=M.cc, v_soft=P.V_SOFT_HOY)),
        (f"B2: LM324 medida, software con {v_act[0]:.2f}-{v_act[1]:.2f} V",
         dict(tri=tm, curva_soft=M.cc, v_soft=v_act)),
        ("B3: LM324 segun LTspice, software actualizado",
         dict(tri=tl, curva_soft=M.cc, v_soft=v_act)),
        ("B4: como B2 pero con el ajuste de fase de vivo_rapido",
         dict(tri=tm, curva_soft=M.cc, v_soft=v_act, ajuste_soft=True)),
        ("B5: como B2, y el software sabe del corrimiento (no del recorte)",
         dict(tri=tm, curva_soft=S.curva_corrida(M.cc, tm.offset), v_soft=v_act)),
    ]
    # Que pesa de la LM324: con el software de B5 (sabe del corrimiento), se
    # prende una imperfeccion por vez. Solo van al resumen, no a la figura.
    sabe = S.curva_corrida(M.cc, tm.offset)
    for nombre, flags in (("B6: LM324 sin asimetria, sin residuo, sin recorte", (0, 0, 0)),
                          ("B7:   + solo la asimetria (50,75/49,25 %)", (1, 0, 0)),
                          ("B8:   + solo el residuo (curvatura y escalon)", (0, 1, 0)),
                          ("B9:   + solo el recorte en 1991 MHz", (0, 0, 1))):
        casos_b.append((nombre, dict(tri=S.tri_lm324_medida(M.cv, *map(bool, flags)),
                                     curva_soft=sabe, v_soft=v_act)))
    say(f"  (pico, ancho a -6 dB, lobulo mas alto entre 45 y 250 Hz del pico (fuera del lobulo principal de Hann) y fantasmas: de un "
        f"BLANCO PUNTUAL a {D_AP_PUNTUAL:.2f} m aparentes, la placa a 1 m medida; sin MEEP)")
    res_b = {}
    for nombre, kw in casos_b:
        for d in P.BARRIDO:
            pr, cf, sf = M.correr(d, **kw, **kwb)
            res_b[nombre, d] = (pr, cf, sf)
        say(f"  {nombre:66s} " + metricas_puntual(M, kw, kwb))

    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.3], hspace=0.3)
    a = fig.add_subplot(gs[0, 0])
    u = np.linspace(0, 1, 4000, endpoint=False)
    for tri, col in ((S.tri_sdg(M.cv), "0.4"), (tm, "C0"), (tl, "C2")):
        v = tri.forma(u)
        ideal = tri.vmin + (tri.vmax - tri.vmin) * (1 - np.abs(2 * u - 1))
        a.plot(u * tri.T * 1e3, (v - ideal) * 1e3, color=col, lw=1, label=tri.nombre)
    a.set_xlabel("t desde el vértice de abajo [ms]")
    a.set_ylabel("V − triangular simétrica ideal [mV]")
    a.set_title("Forma de la triangular (la asimetría domina)", fontsize=10)
    a.grid(alpha=0.3)
    a.legend(fontsize=8)
    a = fig.add_subplot(gs[0, 1])
    t = np.linspace(0, tm.T, 4000, endpoint=False)
    a.plot(t * 1e3, S.tri_sdg(M.cv).f(t * P.TPRF_SDG / tm.T) / 1e6, color="0.4", lw=1,
           label="A: SDG830")
    a.plot(t * 1e3, tm.f(t) / 1e6, color="C0", lw=1, label="B: LM324 + hipótesis Max Hold")
    a.set_xlabel("t [ms]")
    a.set_ylabel("f del VCO [MHz]")
    a.set_title("Barrido del VCO (recorte arriba, corrimiento abajo)", fontsize=10)
    a.grid(alpha=0.3)
    a.legend(fontsize=8)
    a = fig.add_subplot(gs[1, :])
    for (nombre, _), col in zip(casos_b, ("0.4", "C3", "C0", "C2", "C4", "C1")):
        pr, cf, sf = res_b[nombre, P.D_NORMALIZA]
        a.plot(pr.hz, S.db_norm(sf), color=col, lw=1.1, label=nombre)
    a.set_xlim(0, XMAX)
    a.set_ylim(PISO, 3)
    a.set_xlabel("frecuencia de batido [Hz]")
    a.set_ylabel("dB (sf, 1 m)")
    a.grid(alpha=0.3)
    a.legend(fontsize=8.5)
    a.set_title("Placa a 1 m con el fondo restado: qué cambiaría con el generador propio",
                fontsize=10)
    fig.suptitle(f"Escenario B, generador con LM324: predicción (sonda {sonda})", fontsize=12)
    R.guardar_figura(fig, out("generador_propio.png"))
    plt.close(fig)

    # ------------------------------------------------------- variante: fuga
    say("\n--- Variante: fuga interna ajustada a las capturas cf (200-800 Hz)")
    tri = S.tri_sdg(M.cv)
    kwf = dict(tri=tri, curva_soft=M.cc, v_soft=P.V_SDG, arm=(1, 2, 3), a3=P.A3_DBC_CASCADA,
               complejo=True)
    base = {}
    for d in P.BARRIDO:
        pr, _, _ = M.correr(d, **kwf)
        base[d] = pr
    ref = []
    for d in [P.D_NORMALIZA]:
        f_b = tri.f(np.linspace(0, tri.T / 2, 2000))
        e = M.placa[d](f_b) - M.vacio(f_b)
        ref.append(np.sqrt(np.mean(np.abs(e) ** 2)))
    ref = ref[0]
    d_aps = np.arange(P.FUGA_D_AP[0], P.FUGA_D_AP[1] + 1e-9, 0.05)
    niveles = np.arange(P.FUGA_NIVEL_DB[0], P.FUGA_NIVEL_DB[1] + 1e-9, 1.0)
    # La fase de la fuga contra la placa es libre: sin ella el mapa sale a
    # rayas (cada 5 cm de retardo la fase relativa en el centro de la banda
    # da media vuelta) y el ajuste elige fases, no distancias.
    fases = np.radians(np.arange(0, 360, 30))
    med = {d: leer_captura(d, "cf") for d in P.BARRIDO}
    err = np.zeros((len(d_aps), len(niveles), len(fases)))
    for i, dap in enumerate(d_aps):
        tau = 2 * dap / R.C
        for d in P.BARRIDO:
            pf, _, _ = M.correr(d, escenas={"placa": S.SoloFuga(tau), "vacio": S.SoloFuga(tau)},
                                **kwf)
            Eb = base[d].E["placa"][-P.RAMPAS_EN_FILA:]
            Ef = pf.E["placa"][-P.RAMPAS_EN_FILA:]
            hz_m, mag_m = med[d]
            ym = np.maximum(S.db_norm(mag_m), -35)
            banda = (hz_m >= 200) & (hz_m <= 800)
            for k, ndb in enumerate(niveles):
                for q, fi in enumerate(fases):
                    L = ref * 10 ** (ndb / 20) * np.exp(1j * fi)
                    p = np.abs(Eb + L * Ef).mean(axis=0)
                    ys = np.maximum(np.interp(hz_m, base[d].hz, S.db_norm(p)), -35)
                    err[i, k, q] += np.mean((ys[banda] - ym[banda]) ** 2)
    err /= len(P.BARRIDO)
    i, k, q = np.unravel_index(np.argmin(err), err.shape)
    dap, ndb, fase = d_aps[i], niveles[k], fases[q]
    err_fase = err[i, k, q]
    err = err.min(axis=2)            # para el mapa: la mejor fase de cada punto
    hz_pm = base[P.D_NORMALIZA].hz_por_m
    sin_fuga = np.mean([np.mean((np.maximum(np.interp(med[d][0], base[d].hz,
                                                       S.db_norm(np.abs(base[d].E['placa'][-8:]).mean(0))), -35)
                                 - np.maximum(S.db_norm(med[d][1]), -35))[(med[d][0] >= 200) & (med[d][0] <= 800)] ** 2)
                        for d in P.BARRIDO])
    say(f"  mejor: {dap:.2f} m aparentes ({dap*hz_pm:.0f} Hz, tau {2*dap/R.C*1e9:.2f} ns), "
        f"nivel {ndb:+.0f} dB respecto del eco de la placa a 1 m, fase {np.degrees(fase):.0f}°"
        + ("  [EN EL BORDE del rango: no esta acotado]"
           if ndb in (niveles[0], niveles[-1]) or dap in (d_aps[0], d_aps[-1]) else ""))
    say(f"  error cuadratico medio en 200-800 Hz: {np.sqrt(err_fase):.1f} dB con fuga, "
        f"{np.sqrt(sin_fuga):.1f} dB sin fuga")
    say(f"  su fantasma 2f caeria en {2*dap*hz_pm:.0f} Hz y el 3f en {3*dap*hz_pm:.0f} Hz")
    fuga = (ref * 10 ** (ndb / 20) * np.exp(1j * fase), 2 * dap / R.C)

    fig = plt.figure(figsize=(15, 11))
    gs = fig.add_gridspec(len(P.BARRIDO), 2, width_ratios=[1, 2.2], hspace=0.35)
    a = fig.add_subplot(gs[:, 0])
    im = a.pcolormesh(niveles, d_aps, np.sqrt(err), shading="auto", cmap="viridis_r")
    a.plot(ndb, dap, "r+", ms=14, mew=2)
    fig.colorbar(im, ax=a, label="error rms en 200-800 Hz [dB]")
    a.set_xlabel("nivel de la fuga [dB respecto del eco a 1 m]")
    a.set_ylabel("distancia aparente de la fuga [m]")
    a.set_title("Ajuste (todas las distancias juntas)", fontsize=10)
    for j, d in enumerate(P.BARRIDO):
        a = fig.add_subplot(gs[j, 1])
        hz_m, mag_m = med[d]
        a.plot(hz_m, S.db_norm(mag_m), color=MED, lw=1.1, label="medido cf")
        pr, cf, _ = M.correr(d, tri, M.cc, P.V_SDG, arm=(1, 2, 3), a3=P.A3_DBC_CASCADA)
        a.plot(pr.hz, S.db_norm(cf), color=SIM, lw=0.9, alpha=0.6, label="simulado, sin fuga")
        pr, cf, _ = M.correr(d, tri, M.cc, P.V_SDG, arm=(1, 2, 3), a3=P.A3_DBC_CASCADA,
                             fuga=fuga)
        a.plot(pr.hz, S.db_norm(cf), color="C0", lw=1.1, label="simulado, con fuga")
        for n, ls in ((1, "-"), (2, "--"), (3, ":")):
            a.axvline(n * dap * hz_pm, color="C0", ls=ls, lw=0.7)
        a.text(0.01, 0.88, f"{d*100:.0f} cm", transform=a.transAxes, fontweight="bold")
        a.set_xlim(0, XMAX)
        a.set_ylim(PISO, 3)
        a.grid(alpha=0.3)
        if j == 0:
            a.legend(fontsize=8, loc="upper right")
            a.set_title("cf con y sin fuga (azul: la fuga y sus fantasmas 2f, 3f)", fontsize=10)
    a.set_xlabel("frecuencia de batido [Hz]")
    fig.suptitle(f"Variante: un camino de fuga interna AJUSTADO, no medido (sonda {sonda})",
                 fontsize=12)
    R.guardar_figura(fig, out("fuga.png"))
    plt.close(fig)

    # ------------------------------------------------------------- entradas
    figura_entradas(M, out("entradas.png"))
    log.close()
    print(f"\n  listo: {figs}")


def figura_entradas(M, destino):
    fig, axs = plt.subplots(2, 3, figsize=(16, 9))
    a = axs[0, 0]
    v = np.linspace(-0.3, 3.4, 400)
    a.plot(v, M.cv(v) / 1e6, "C0", label="VCO 2026-10-19 (la 'verdadera')")
    a.plot(v, M.cc(v) / 1e6, "C1--", label="VCO vieja (la del software)")
    tm = S.tri_lm324_medida(M.cv)
    vv = np.linspace(tm.vmin, tm.vmax, 300)
    a.plot(vv, tm.f_de_v(vv) / 1e6, "C3", lw=2, label="LM324: corrimiento + recorte")
    a.set_xlabel("tensión del generador [V]")
    a.set_ylabel("f [MHz]")
    a.set_title("Curva del VCO", fontsize=10)
    a.grid(alpha=0.3)
    a.legend(fontsize=8, loc="upper left")
    ins = a.inset_axes([0.55, 0.1, 0.42, 0.35])
    vd = np.linspace(0, 3, 300)
    ins.plot(vd, (M.cv(vd) - M.cc(vd)) / 1e6, "k", lw=1)
    ins.axhline(0, color="0.6", lw=0.6)
    ins.set_title("10-19 − vieja [MHz]", fontsize=7.5)
    ins.tick_params(labelsize=7)
    ins.grid(alpha=0.3)
    a = axs[0, 1]
    fe, a1, a2 = M.env
    b = (fe >= P.F_PISO_B) & (fe <= P.F_TOPE_B)
    a.plot(fe[b] / 1e6, a1[b], "C0", label="fundamental [dB, media 0]")
    a.plot(fe[b] / 1e6, a2[b], "C3", label="2º armónico [dBc]")
    medido = b & (fe >= P.A2_F_DESDE) & (fe <= P.A2_F_HASTA)
    a.plot(fe[medido] / 1e6, a2[medido], "C3", lw=3, alpha=0.4, label="2º: tramo medido")
    for x in P.A3_DBC[1:]:
        a.axhline(x, color="C2", ls=":", lw=1)
    a.text(1000, P.A3_DBC[1] + 0.5, "3er armónico (supuesto)", color="C2", fontsize=8)
    a.set_xlabel("f de la fundamental [MHz]")
    a.set_title("Del Max Hold de la salida del VCO", fontsize=10)
    a.grid(alpha=0.3)
    a.legend(fontsize=8)
    a = axs[0, 2]
    fh = np.linspace(0.9e9, 6.2e9, 600)
    for ruta, col in ((P.S2P_TX, "C0"), (P.S2P_RX, "C1")):
        a.plot(fh / 1e9, 20 * np.log10(np.abs(R.s21_extendido(ruta, fh))), col,
               label=os.path.basename(ruta))
    a.axvline(2.5, color="0.5", ls=":")
    a.text(2.55, -0.3, "arriba: extrapolado", fontsize=8, color="0.4")
    a.set_xlabel("f [GHz]")
    a.set_ylabel("|S21| [dB]")
    a.set_title("Cables RG-213 de 1 m", fontsize=10)
    a.grid(alpha=0.3)
    a.legend(fontsize=8)
    a = axs[1, 0]
    d = np.genfromtxt(P.FILTRO_IF_CSV, delimiter=",", names=True, dtype=None, encoding="utf-8")
    fo, ho = d["f_Hz"].astype(float), d["H_G1_norm_dB"].astype(float)
    a.semilogx(fo, ho, "ko", ms=4, label="medido G=1")
    w, h = signal.sosfreqz(M.sos, worN=np.logspace(-1, 4.38, 600),
                                                fs=P.FS_ADC)
    a.semilogx(w, 20 * np.log10(np.abs(h) + 1e-12), "C3",
               label=f"modelo: {M.filtro[0]:.0f} Hz / Butter {M.filtro[1]} en "
                     f"{M.filtro[2]/1e3:.1f} kHz + acople + PCM")
    a.axvspan(100, 2400, color="C0", alpha=0.08)
    a.set_ylim(-40, 3)
    a.set_xlabel("f [Hz]")
    a.set_title("Cadena de IF (la banda útil, sombreada, es plana)", fontsize=10)
    a.grid(alpha=0.3, which="both")
    a.legend(fontsize=7.5)
    a = axs[1, 1]
    tri = S.tri_sdg(M.cv)
    fb = tri.f(np.linspace(0, tri.T / 2, 2000))
    fx = np.linspace(0.9e9, 6.15e9, 2000)
    eco = M.placa[P.D_NORMALIZA]
    e = (np.interp(fx, eco.f, np.abs(eco.aire - M.vacio.aire)))
    a.plot(fx / 1e9, 20 * np.log10(e / np.sqrt(np.mean(np.abs(np.interp(fb, eco.f, np.abs(eco.aire - M.vacio.aire))) ** 2))),
           "0.3", lw=0.8, label="|H| del eco de la placa (MEEP, 2D)")
    for n, col in ((1, "C0"), (2, "C3"), (3, "C2")):
        a.axvspan(n * fb.min() / 1e9, n * fb.max() / 1e9, color=col, alpha=0.1)
        a.text(n * fb.mean() / 1e9, 12, f"{n}f", color=col, ha="center")
    a.set_xlabel("f [GHz]")
    a.set_ylabel("dB respecto de la banda de f")
    a.set_title(f"Eco a 1 m. Cadena plana: g2 = {20*np.log10(M.g[1]):+.1f} dB, "
                f"g3 = {20*np.log10(M.g[2]):+.1f} dB", fontsize=10)
    a.set_ylim(-40, 20)
    a.grid(alpha=0.3)
    a.legend(fontsize=8)
    a = axs[1, 2]
    a.axis("off")
    txt = ("Supuestos (ver parametros.py):\n\n"
           "· 2º armónico arriba de 1500 MHz: constante\n"
           "· 3er armónico: no medido, -15 o -25 dBc\n"
           "· PA, splitter, LNA, mezclador: planos a 2f y 3f\n"
           "· mezclador: multiplicador (base) o conmutado\n"
           "  con fase 0/45/90° entre f y 2f\n"
           "· escenario B: corrimiento y recorte para\n"
           "  reproducir la banda del Max Hold (hipótesis)\n"
           "· sincronismo perfecto (salvo B4)\n"
           "· fuga: ajustada, no medida\n"
           "· MEEP 2D: niveles cualitativos, posiciones sí")
    a.text(0, 1, txt, va="top", fontsize=10, family="monospace")
    fig.suptitle(f"Entradas del modelo (sonda {M.sonda})", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    R.guardar_figura(fig, destino)
    plt.close(fig)


if __name__ == "__main__":
    main()
