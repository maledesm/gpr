"""
GPRv2 - Figura del generador de triangular (triangular2.asc)
============================================================

Lee triangular2.raw (el .step del pote, 5 posiciones) y arma una figura de
3x2: una fila por posicion del pote (0, 0,5 y 1). A la izquierda la salida de
0 a 3 V con el sync, en milisegundos; a la derecha su espectro (las rayas de
los armonicos) contra la envolvente de una triangular ideal de la misma
amplitud.

La ventana de tiempo es la misma en las tres filas y sale del periodo mas
largo, asi que en la fila mas lenta entra poco mas de un periodo y en la mas
rapida entran varios. El eje de frecuencia va en armonicos porque los
periodos de las tres filas difieren 13 veces.

Uso
---
    python graficar_triangular2.py

Antes hay que simular triangular2.asc para que exista el .raw.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

AQUI    = os.path.dirname(os.path.abspath(__file__))
RAW     = os.path.join(AQUI, "triangular2.raw")
SALIDA  = os.path.join(AQUI, "triangular2.png")

POSICIONES = [0, 2, 4]   # indices del .step: pos = 0, 0,5 y 1
ETIQUETAS  = ["0", "0,5", "1"]

VISTA_MARGEN   = 1.55    # la ventana de tiempo, contra el periodo mas largo
PERIODOS_FFT   = 60      # tope de periodos en la FFT: cuantos mas, mas finas
                         # salen las rayas de los armonicos
ARRANQUE_S     = 0.35    # lo que se descarta del principio: el oscilador arranca
MUESTRAS_POR_T = 4096    # remuestreo uniforme, por periodo
RELLENO_IDEAL  = 64      # ceros alrededor del triangulo ideal, para que su
                         # transformada salga continua y no en rayas
ARMONICOS      = 15      # hasta donde llega el eje de frecuencia

# Paleta validada: violeta y aqua se separan bien incluso simulando daltonismo
# (dE OKLab 37 con protanopia y 31 con deuteranopia, contra un objetivo de 8).
C_SALIDA = "#4a3aa7"   # violeta
C_SYNC   = "#1baf7a"   # aqua
C_IDEAL  = "#52514e"   # gris neutro, la referencia no es una serie mas
C_LIMITE = "#8a8a85"


def leer_raw(path):
    """Devuelve (nombres, [(t, datos) por paso]) de un .raw binario de LTspice.

    El encabezado va en UTF-16LE y los datos en binario: el tiempo en doble
    precision y el resto en simple. Los pasos van concatenados y se separan
    porque el tiempo vuelve a empezar.
    """
    crudo = open(path, "rb").read()
    marca = "Binary:\n".encode("utf-16-le")
    i = crudo.find(marca)
    if i < 0:
        raise SystemExit("no es un .raw binario de LTspice")
    cab = crudo[:i].decode("utf-16-le")
    datos = crudo[i + len(marca):]

    n_var = n_pts = None
    nombres = []
    leyendo = False
    for linea in cab.splitlines():
        if linea.startswith("No. Variables:"):
            n_var = int(linea.split(":")[1])
        elif linea.startswith("No. Points:"):
            n_pts = int(linea.split(":")[1])
        elif linea.startswith("Variables:"):
            leyendo = True
        elif leyendo and linea.startswith("\t"):
            nombres.append(linea.split("\t")[2])

    # El tamaño de cada punto sale de los datos: LTspice guarda el tiempo en
    # 8 bytes y las variables en 4, salvo que el .raw sea todo de 8. Con
    # 8 + 4*(n-1) bytes el punto no es multiplo de 8, asi que hace falta un
    # dtype estructurado y no se puede leer con un salto fijo.
    por_punto = len(datos) // n_pts
    if por_punto == 8 + 4 * (n_var - 1):
        dt = np.dtype([("t", "<f8"), ("v", "<f4", (n_var - 1,))])
        reg = np.frombuffer(datos, dtype=dt, count=n_pts)
        t, v = reg["t"].astype(np.float64), reg["v"].astype(np.float64)
    elif por_punto == 8 * n_var:
        todo = np.frombuffer(datos, dtype=np.float64).reshape(n_pts, n_var)
        t, v = todo[:, 0].copy(), todo[:, 1:].copy()
    else:
        raise SystemExit(f"formato inesperado: {por_punto} bytes por punto")

    t = np.abs(t)   # LTspice marca el arranque de cada paso con el signo
    cortes = np.flatnonzero(np.diff(t) < 0) + 1
    pasos = [(t[a:b], v[a:b]) for a, b in zip(np.r_[0, cortes], np.r_[cortes, n_pts])]
    return nombres, pasos


def periodo_y_vertices(t, x):
    """Periodo (s) y tiempos de los cruces de subida por el valor medio.

    El periodo sale de una recta ajustada a los cruces contra su indice y no
    de la mediana de las diferencias: con el brazo de palanca de toda la
    corrida el error es mucho menor, y la FFT necesita que la ventana sea de
    periodos ENTEROS para que no haya fuga.
    """
    medio = 0.5 * (x.max() + x.min())
    sube = np.flatnonzero((x[:-1] < medio) & (x[1:] >= medio))
    cruces = t[sube] + (medio - x[sube]) * (t[sube + 1] - t[sube]) / (x[sube + 1] - x[sube])
    cruces = cruces[cruces >= ARRANQUE_S]
    if len(cruces) < 3:
        raise SystemExit("no se encontraron suficientes periodos")
    T = float(np.polyfit(np.arange(len(cruces)), cruces, 1)[0])
    return T, cruces


def espectro(t, x, T, n_periodos, por_periodo, t_fin=None):
    """FFT de una ventana de n_periodos enteros, remuestreada uniforme."""
    fin = t[-1] if t_fin is None else t_fin
    ini = fin - n_periodos * T
    n = n_periodos * por_periodo
    tt = ini + n_periodos * T * np.arange(n) / n       # sin repetir el final
    xx = np.interp(tt, t, x)
    X = np.abs(np.fft.rfft(xx)) / n
    arm = np.arange(len(X)) / n_periodos               # eje en armonicos
    return arm, X


def envolvente_ideal(por_periodo, relleno):
    """Envolvente del espectro de una triangular ideal.

    Es la transformada de UN SOLO periodo rellenado con ceros: eso da la
    curva continua sobre la que se apoyan los armonicos del caso periodico,
    con sus ceros en los armonicos pares. La amplitud no importa porque
    despues se normaliza contra la fundamental.
    """
    # El triangulo arranca y termina en cero, y asi tiene que quedar: si se le
    # resta el valor medio aparecen dos escalones en los extremos y el
    # espectro pasa a caer como 1/f en vez de 1/f**2.
    u = np.arange(por_periodo) / por_periodo
    tri = np.where(u < 0.5, 2 * u, 2 * (1 - u))
    X = np.abs(np.fft.rfft(tri, por_periodo * relleno))
    arm = np.arange(len(X)) / relleno           # eje en armonicos
    return arm, X


def norm(X, i_fundamental):
    """Magnitud normalizada a la FUNDAMENTAL, no al maximo: el maximo es la
    continua (la salida va de 0 a 3 V) y dejaria la fundamental abajo de 1."""
    return X / X[i_fundamental]


def main():
    if not os.path.exists(RAW):
        sys.exit(f"falta {RAW}: simula triangular2.asc primero")
    nombres, pasos = leer_raw(RAW)
    # nombres[0] es el tiempo, que va aparte: las columnas arrancan en el 1
    i_sal = nombres.index("V(salida)") - 1
    i_syn = nombres.index("V(sync)") - 1

    fig, ejes = plt.subplots(3, 2, figsize=(12.5, 8.5))

    # La ventana de tiempo es comun: la fija el periodo mas largo de las tres
    # filas, para que en esa entre poco mas de un periodo entero.
    periodos = [periodo_y_vertices(pasos[p][0], pasos[p][1][:, i_sal])[0] for p in POSICIONES]
    ventana = VISTA_MARGEN * max(periodos)

    for fila, (paso, etiqueta) in enumerate(zip(POSICIONES, ETIQUETAS)):
        t, v = pasos[paso]
        sal, syn = v[:, i_sal], v[:, i_syn]
        T, cruces = periodo_y_vertices(t, sal)

        # --- tiempo: la ventana comun, arrancando en un cruce de subida. Se
        # remuestrea parejo porque las corridas rapidas traen muchos mas
        # puntos por periodo que las lentas.
        # el ultimo cruce que deja la ventana ENTERA adentro de la corrida: si
        # se pasa del final, np.interp repite el ultimo valor y dibuja una
        # meseta que no existe
        k = np.searchsorted(cruces, t[-1] - ventana) - 1
        if k < 0:
            raise SystemExit("la corrida es mas corta que la ventana de tiempo")
        t0 = cruces[k]
        ms = np.linspace(0, ventana * 1e3, 4000)
        tt = t0 + ms * 1e-3

        sal_v = np.interp(tt, t, sal)
        vmax, vmin = sal_v.max(), sal_v.min()

        ax = ejes[fila, 0]
        ax.plot(ms, sal_v, color=C_SALIDA, lw=2, label="salida")
        ax.plot(ms, np.interp(tt, t, syn), color=C_SYNC, lw=2, label="sync")
        for v_lim, arriba in ((vmax, True), (vmin, False)):
            ax.axhline(v_lim, color=C_LIMITE, lw=1.2, ls="--", zorder=1)
            ax.annotate(f"{v_lim:.3f} V", xy=(0.008, v_lim), xycoords=("axes fraction", "data"),
                        ha="left", va="bottom" if arriba else "top", fontsize=8, color=C_LIMITE,
                        bbox=dict(fc="white", ec="none", alpha=0.75, pad=1))
        ax.set_xlim(0, ventana * 1e3)
        ax.set_ylim(-0.5, 3.7)
        ax.set_ylabel("V")
        ax.grid(alpha=0.25)
        ax.set_title(f"pos = {etiqueta}   ·   T = {T*1e3:.1f} ms", fontsize=11)
        if fila == 0:
            ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
        if fila == 2:
            ax.set_xlabel("Tiempo [ms]")

        # --- espectro. La ventana se cierra en un cruce y tiene todos los
        # periodos ENTEROS que entren en la corrida: cuantos mas, mas finas
        # salen las rayas de los armonicos.
        fin = cruces[-1]
        n_per = min(PERIODOS_FFT, int((fin - ARRANQUE_S) / T))
        arm, X = espectro(t, sal, T, n_per, MUESTRAS_POR_T, t_fin=fin)
        armi, Xi = envolvente_ideal(MUESTRAS_POR_T, RELLENO_IDEAL)

        ax = ejes[fila, 1]
        ax.plot(arm, norm(X, n_per), color=C_SALIDA, lw=2, label="simulada")
        ax.plot(armi, norm(Xi, RELLENO_IDEAL), color=C_IDEAL, lw=2, ls="--",
                label="envolvente ideal")
        ax.set_xlim(0, ARMONICOS)
        ax.set_ylim(0, 1.08)
        ax.set_ylabel("Magnitud")
        ax.grid(alpha=0.25)
        ax.set_title("Armonicos", fontsize=11)
        if fila == 0:
            ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
        if fila == 2:
            ax.set_xlabel("Armonico (f / f0)")

    fig.tight_layout()
    fig.savefig(SALIDA, dpi=150)
    print(f"figura: {SALIDA}")


if __name__ == "__main__":
    main()
