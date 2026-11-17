"""
GPRv3 - Capturas para el informe
================================

De lo que se esta viendo salen dos archivos con el mismo nombre en
datos/capturas/: un PNG que se explica solo (radargrama, FFT, estado del
banco) y un CSV con la curva de la FFT.

El CSV mantiene el formato de GPRv2 (`proceso_rapido.leer_fft_captura` lo
lee tal cual): la fila de nombres primero, despues los `# clave = valor` y
despues los datos. Cambian algunos metadatos, porque cambio la cadena.
"""

import os
import re
import time

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import config as cfg

ENCABEZADO = "# GPRv3 - FFT de una captura de vivo.py"


def ms(x):
    return "-" if not x else f"{x * 1e3:.3f}"


def texto_info(radar):
    """El cuadro de informacion del barrido, igual en pantalla y en el PNG."""
    r = radar.resumen()
    if r is None or not r["tprf"]:
        return "esperando rampas..."
    e_db = radar.energia_actual_db()
    ps = radar.picos_por_sentido()
    jit = r["jitter_us"]
    return (
        "-- sync --\n"
        f"Tprf      {ms(r['tprf']):>9} ms\n"
        f"subida    {ms(r['t_subida']):>9} ms\n"
        f"bajada    {ms(r['t_bajada']):>9} ms\n"
        f"jitter    {'-' if jit is None else f'{jit:.0f}':>9} us\n"
        f"salida    {r['sps']:9.0f} sps\n"
        f"por rampa {r['muestras_rampa']:9.1f} muestras\n"
        "\n-- parte usada de la rampa --\n"
        f"de {r['u_lo'] * 100:3.0f} a {r['u_hi'] * 100:3.0f} %\n"
        f"{r['v_lo']:.2f} a {r['v_hi']:.2f} V\n"
        f"{r['f_lo'] / 1e6:.0f} a {r['f_hi'] / 1e6:.0f} MHz\n"
        f"BW usada  {r['bw'] / 1e6:9.1f} MHz\n"
        f"resolucion{r['resolucion'] * 100:9.1f} cm\n"
        "\n-- barrido --\n"
        f"BW total  {r['bw_total'] / 1e6:9.1f} MHz\n"
        f"alpha0    {r['alpha0'] / 1e12:9.4f} THz/s\n"
        f"          {r['hz_por_m']:9.1f} Hz/m\n"
        f"no ambiguo{r['no_ambiguo']:9.1f} m\n"
        f"FFT {r['nfft']} sobre {r['puntos']} puntos\n"
        f"ventana   {r['ventana_fft']:>9}\n"
        f"curva     {r['curva']:>9}\n"
        + (f"  medida a Tprf {r['curva_tprf_ms']} ms\n" if r["curva"] == "medida"
           else "") +
        ""
        f"retardo   {r['retardo'] * 1e3:+9.2f} ms\n"
        "\n-- rampas --\n"
        f"validas   {r['validas']:9d}\n"
        f"descartadas {r['repetidos'] + r['fuera_de_rango'] + r['incoherentes'] + r['sin_muestras']:7d}\n"
        f"se usan   {radar.sentido:>9}\n"
        f"por fila  {radar.n_ef:9d}\n"
        "\n-- fondo --\n"
        + ("sin medir\n" if radar.fondo is None else
           f"{'automatico (MTI)' if radar.mti else 'congelado'}\n"
           f"energia   {0.0 if e_db is None else e_db:+9.1f} dB\n"
           f"margen    {radar.margen:+9.1f} dB\n"
           f"blanco    {'SI' if radar.hay_blanco() else 'no':>9}\n")
        + "\n-- distancia --\n"
        + (f"d = {radar.cal.a:.4f}*crudo {radar.cal.b:+.3f} m"
           if radar.cal.activa else "sin calibrar (cruda)")
        + ("" if ps is None else
           f"\npico subida - bajada {(ps[0] - ps[1]) * 100:+.1f} cm"))


def nombre_libre(nombre):
    """Ruta sin extension, libre para el par .png + .csv. Nunca pisa."""
    nombre = re.sub(r'[\\/:*?"<>|]', "_", (nombre or "").strip()).rstrip(" .")
    nombre = nombre or cfg.NOMBRE_CAPTURA_DEF
    os.makedirs(cfg.CAPTURAS, exist_ok=True)
    base = os.path.join(cfg.CAPTURAS, nombre)
    k = 2
    while os.path.exists(base + ".png") or os.path.exists(base + ".csv"):
        base = os.path.join(cfg.CAPTURAS, f"{nombre}_{k}")
        k += 1
    return base


def curva_fft(radar):
    """(mag, db_pantalla, que_es_0db) de la ultima fila, en todo el eje."""
    fila = radar.fila_actual()
    if fila is None:
        return None
    pot, ref, con_fondo = fila
    if con_fondo:
        que = ("pico del fondo en la zona util "
               + ("(fondo automatico MTI)" if radar.mti else "(fondo congelado)"))
    else:
        que = "maximo de la matriz visible (sin fondo medido)"
    # La fila es potencia media; `mag` es su raiz, en cuentas del ADC.
    return np.sqrt(pot), 10 * np.log10(pot / ref + 1e-24), que


def escribir_csv(ruta, radar, png, corrida):
    c = curva_fft(radar)
    r = radar.resumen()
    if c is None or r is None or not r["tprf"]:
        return False
    mag, db, que = c
    eje = radar.eje_m_crudo
    columnas = {
        "f_hz": (eje * r["hz_por_m"],
                 "frecuencia de batido [Hz] = d_crudo * hz_por_m"),
        "d_crudo_m": (eje, "distancia aparente SIN calibrar [m]"),
        "d_cal_m": (radar.cal.aplicar(eje),
                    "distancia calibrada [m] = cal_a*d_crudo + cal_b"),
        "mag": (mag, "amplitud del batido en cuentas del ADC: raiz de la "
                     "potencia media de las ultimas 'rampas_en_fila' rampas, "
                     "con el fondo ya restado (en potencia) si habia fondo"),
        "db_pantalla": (db, "la misma curva en dB, como en la pantalla "
                            "(ver que_es_0db)"),
        "db_norm": (20 * np.log10(mag / (mag.max() + 1e-30) + 1e-12),
                    "20*log10(mag / max(mag)), para superponer"),
    }
    pico = radar.pico_crudo()
    e_db = radar.energia_actual_db()
    meta = {
        "fecha": time.strftime("%d-%m-%Y %H:%M:%S"),
        "png": png,
        "corrida": corrida or "no se grabo el crudo",
        "tprf_ms": ms(r["tprf"]),
        "subida_ms": ms(r["t_subida"]),
        "bajada_ms": ms(r["t_bajada"]),
        "rampa_ms": ms(r["tprf"] / 2),
        "muestras_por_rampa": f"{r['muestras_rampa']:.1f}",
        "fs_sps": f"{r['sps']:.1f}",
        "nfft": r["nfft"],
        "puntos_remuestreo": r["puntos"],
        "paso_eje_m": cfg.DR_M,
        "ventana_fft": r["ventana_fft"],
        "promedio": "en potencia (|FFT|^2)",
        "retardo_ms": f"{r['retardo'] * 1e3:+.2f}",
        "correccion_no_linealidad": "remuestreo cubico a paso uniforme de "
                                    "frecuencia (curva del VCO)",
        "curva_vco": (os.path.basename(cfg.VCO_CSV) if radar.barrido is None
                      else "medida con un retardo de "
                           f"{radar.barrido['d_ref_m']} m el "
                           f"{radar.barrido['fecha']}, a Tprf "
                           f"{radar.barrido['tprf_ms']} ms"),
        "sincronismo": "flancos de la cuadrada del generador",
        "rampas_usadas": radar.sentido,
        "rampa_desde_pct": f"{r['u_lo'] * 100:.0f}",
        "rampa_hasta_pct": f"{r['u_hi'] * 100:.0f}",
        "bw_mhz": f"{r['bw'] / 1e6:.3f}",
        "bw_total_mhz": f"{r['bw_total'] / 1e6:.3f}",
        "f_min_mhz": f"{r['f_lo'] / 1e6:.3f}",
        "f_max_mhz": f"{r['f_hi'] / 1e6:.3f}",
        "v_min_v": cfg.V_MIN,
        "v_max_v": cfg.V_MAX,
        "alpha0_hz_s": f"{r['alpha0']:.6e}",
        "hz_por_m": f"{r['hz_por_m']:.4f}",
        "bin_resolucion_cm": f"{r['resolucion'] * 100:.2f}",
        "rampas_en_fila": radar.n_ef,
        "rampas_por_fila_pedidas": radar.n_rampas,
        "ventana_s": radar.ventana,
        "eje_en_pantalla": "m" if radar.en_metros else "Hz",
        "alcance_m": radar.alcance,
        "ignorar_m": radar.ignorar,
        "cal_a": f"{radar.cal.a:.6f}",
        "cal_b": f"{radar.cal.b:+.6f}",
        "calibrada": "si" if radar.cal.activa else "no",
        "fondo": ("sin medir" if radar.fondo is None else
                  "automatico MTI" if radar.mti else "congelado"),
        "que_es_0db": que,
        "ref_0db_lineal": f"{radar.ref_pantalla:.6e}",
        "margen_db": radar.margen,
        "energia_sobre_fondo_db": "-" if e_db is None else f"{e_db:.2f}",
        "hay_blanco": "si" if radar.hay_blanco() else "no",
        "pico_promedio_s": cfg.PROMEDIO_CAL_S,
        "pico_crudo_m": "-" if pico is None else f"{pico:.4f}",
        "pico_cal_m": "-" if pico is None else f"{float(radar.cal.aplicar(pico)):.4f}",
        "pico_hz": "-" if pico is None else f"{pico * r['hz_por_m']:.2f}",
    }
    lineas = [",".join(columnas), ENCABEZADO]
    lineas += [f"# col {k} = {v[1]}" for k, v in columnas.items()]
    lineas += [f"# {k} = {v}" for k, v in meta.items()]
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")
        np.savetxt(f, np.column_stack([v[0] for v in columnas.values()]),
                   delimiter=",", fmt="%.9g")
    return True


def leer_csv(ruta):
    """(meta, columnas) de un CSV de captura."""
    meta, cabecera, filas = {}, None, []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea.startswith("#"):
                cuerpo = linea[1:].strip()
                if "=" in cuerpo and not cuerpo.startswith("col "):
                    k, v = cuerpo.split("=", 1)
                    meta[k.strip()] = v.strip()
            elif linea and cabecera is None:
                cabecera = linea.split(",")
            elif linea:
                filas.append(linea)
    datos = np.loadtxt(filas, delimiter=",", ndmin=2)
    return meta, {k: datos[:, i] for i, k in enumerate(cabecera)}


def escribir_png(ruta, radar, titulo=""):
    m = radar.matriz()
    c = curva_fft(radar)
    if m is None or c is None:
        return False
    fig = Figure(figsize=(14, 8), facecolor="white")
    FigureCanvasAgg(fig)
    # La tercera columna es aire, para los numeros de la barra de color.
    gs = fig.add_gridspec(2, 4, width_ratios=[1, 0.025, 0.07, 0.40],
                          height_ratios=[3, 1.25], hspace=0.10, wspace=0.04,
                          left=0.06, right=0.985, top=0.94, bottom=0.08)
    ax = fig.add_subplot(gs[0, 0])
    axf = fig.add_subplot(gs[1, 0], sharex=ax)
    axc = fig.add_subplot(gs[0, 1])
    der = gs[:, 3].subgridspec(2, 1, height_ratios=[3, 1], hspace=0.22)
    axi = fig.add_subplot(der[0])
    axr = fig.add_subplot(der[1])

    unidad = "Distancia [m]" if radar.en_metros else "Frecuencia de batido [Hz]"
    im = ax.imshow(m["db"], aspect="auto", origin="upper",
                   cmap=radar.mapa_color,
                   extent=(m["d0"], m["d1"], 0, m["span"]),
                   vmin=radar.piso, vmax=radar.techo, interpolation="nearest")
    d, hace = radar.traza(m)
    ax.set_facecolor("0.85")              # donde no hubo datos
    ax.plot(d, hace, color="#40e0ff", lw=1.0)
    for t in m["marcas"]:                 # rojas con borde blanco
        ax.axhline(t, color="white", lw=2.2)
        ax.axhline(t, color="red", lw=1.0)
    ax.set_xlim(m["d0"], m["d1"])
    ax.set_ylim(0, m["span"])
    ax.set_ylabel("Tiempo atrás [s]  (0 = ahora; en rojo, los cambios)")
    ax.tick_params(labelbottom=False)
    r = radar.resumen()
    ax.set_title(titulo or f"Radargrama - {radar.n_ef} rampas por fila "
                 f"({radar.n_ef * r['tprf'] / 2 * 1e3:.0f} ms)", fontsize=10)
    fig.colorbar(im, cax=axc, label="dB")

    i1 = radar._i_alcance()
    eje = radar.eje_x()
    axf.plot(eje[:i1], c[1][:i1], color="tab:blue", lw=1.2)
    pico = radar.pico_crudo()
    if pico is not None:
        xp = float(np.interp(pico, radar.eje_m_crudo, eje))
        axf.axvline(xp, color="red", lw=0.8, ls="--")
        axf.text(0.99, 0.92, f"pico: {float(radar.cal.aplicar(pico)):.3f} m",
                 transform=axf.transAxes, ha="right", va="top", fontsize=9)
    axf.set_ylim(radar.piso, radar.techo + 3)
    axf.set_xlabel(unidad)
    axf.set_ylabel("dB")
    axf.grid(alpha=0.3)

    axi.axis("off")
    axi.text(0.02, 1.0, texto_info(radar), family="monospace", fontsize=7.5,
             va="top", ha="left", linespacing=1.15, transform=axi.transAxes)

    for sube, color, rot in ((True, "tab:blue", "subida"),
                             (False, "tab:orange", "bajada")):
        if radar.ultima[sube] is not None:
            u, v = radar.ultima[sube]
            axr.plot(u * 100, v / 8388608 * 100, color=color, lw=0.7, label=rot)
    axr.axvspan(0, radar.u_lo * 100, color="0.5", alpha=0.35, lw=0)
    axr.axvspan(radar.u_hi * 100, 100, color="0.5", alpha=0.35, lw=0)
    axr.set_xlim(0, 100)
    axr.set_xlabel("Posición en la rampa [%]  (0 = valle, 100 = cima)", fontsize=8)
    axr.set_ylabel("% del fondo de escala", fontsize=8)
    axr.set_title("Última rampa (en gris, lo que no se usa)", fontsize=9)
    axr.tick_params(labelsize=7)
    axr.legend(fontsize=7, loc="upper right")
    fig.savefig(ruta, dpi=cfg.DPI_CAPTURA)
    return True


def guardar(radar, nombre, corrida=None):
    """Guarda el par. Devuelve (mensaje, ruta base o None)."""
    try:
        base = nombre_libre(nombre)
        # El CSV va primero: si el PNG fallara igual quedan los numeros.
        if not escribir_csv(base + ".csv", radar, os.path.basename(base) + ".png",
                            corrida):
            return "todavia no hay nada que capturar", None
        escribir_png(base + ".png", radar)
    except OSError as e:
        return f"no pude guardar: {e}", None
    return f"guardada {os.path.basename(base)} (.png + .csv)", base
