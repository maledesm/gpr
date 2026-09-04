"""
GPRv2 - Corrección de no linealidad del VCO por remuestreo temporal
====================================================================

Implementa la segunda mitad de:
    Anghel et al., "Nonlinearity Correction Algorithm for Wideband FMCW
    Radars", EUSIPCO 2013 (PDF en referencias/papers/).

El paper estima la no linealidad a ciegas con la HAF, para cuando no se
conoce la curva del VCO. Acá nos salteamos esa parte: la curva ya está
medida (VCO/Caracteristica VCO.csv), así que el eje de tiempo deformado
θ(t) sale directo de ella, sin ajuste polinomial ni HAF.

Idea (siempre que la rampa de tensión V(t) sea genuinamente lineal, que es
lo que da el generador de funciones de banco):

    f(t) = curva_vco(V(t))     frecuencia real instantánea del VCO
    g(t) = f(t) - f(0)         cuánto barrió el VCO hasta el instante t
    θ(t) = g(t) / α0           eje de tiempo "como si" el barrido fuera
                               lineal, con α0 = BW/T_sweep

Remuestrear la señal de batido (uniforme en t) sobre θ uniforme deja cada
blanco como un tono puro: la FFT de esa señal remuestreada da el perfil de
distancia correcto. Ver GPRv2/CONTEXTO.md, sección 4.

Dos modos, elegís abajo en MODO:

    "sintetico" - genera una señal de batido con la no linealidad REAL del
                  VCO (tomada de la curva medida) y compara la FFT con y
                  sin corrección. No necesita hardware: valida que el
                  remuestreo funciona contra blancos de distancia conocida.

    "csv"       - lee una captura real y corrige la primera rampa de subida
                  que encuentra usando la columna de sync (ver
                  extraer_rampas() más abajo - el generador de laboratorio
                  es una triangular real, y la bajada se invierte antes de
                  poder usarla, si aparece).

                  adquisicion.ino manda la salida ya diezmada a 6000
                  muestras/s fijas (ver SPS_SALIDA en el .ino), no la fs
                  real del ADC. Con T_sweep = 20 ms eso da 120 muestras por
                  rampa, y alcanza: el ancho de bin de la FFT vale c/(2·BW)
                  cualquiera sea fs, o sea que el diezmado NO cuesta
                  resolución. Lo que fs fija es el alcance no ambiguo.

Uso
---
    python correccion_no_linealidad.py
"""

import os
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt

# ─── Qué correr ───────────────────────────────────────────────────────────

MODO = "sintetico"   # "sintetico" | "csv"

# Solo se usa si MODO == "csv": el CSV que graba grabar_rampa.py en
# GPRv2/datos/ ("L,sync", sin encabezado). Si tiene varias rampas seguidas,
# acá se analiza solo la primera (ver extraer_rampas()).
CSV_ENTRADA = os.path.join("..", "datos", "captura.csv")
FS_CSV      = 6000.0   # sps de la salida diezmada de adquisicion.ino

# ─── Parámetros de la rampa hacia el VCO ─────────────────────────────────
# AJUSTAR cuando se mida la salida real del generador de laboratorio: esto
# asume que V(t) es una rampa lineal genuina de V_MIN a V_MAX en T_SWEEP.

VCO_CSV  = os.path.join("..", "..", "VCO", "Caracteristica VCO.csv")
# 20 ms: punto medio elegido para las primeras mediciones reales de
# laboratorio (no es lo que emite el banco casero de Martin, que sigue en
# 10 ms - ver GPRv2/CLAUDE.md). Con 50 ms el acoplamiento directo TX->RX a
# 0,15 m da 20,8 Hz, pegado al corte de 19 Hz del pasabajos post-mezclador;
# con 10 ms sobra margen pero quedan la mitad de muestras por rampa para el
# remuestreo. A 20 ms el mismo acoplamiento da 52 Hz (3x el corte, comodo) y
# hay el doble de muestras que a 10 ms para la misma FS_CSV.
T_SWEEP  = 20e-3          # s, rampa de subida (ver GPRv2/CLAUDE.md)
V_MIN    = 0.0            # V
V_MAX    = 3.00           # V  -> con la curva medida da BW = 1039 MHz

# ─── Blancos para el modo sintético: (distancia en m, amplitud en dB) ────

C = 3e8
BLANCOS = [
    (0.60, -10.0),
    (1.20,   0.0),
    (3.00, -15.0),
]
RUIDO_DB = -40.0
FS_SINTETICO = 48000.0

# ─── Curva del VCO ────────────────────────────────────────────────────────

def cargar_curva_vco(path):
    """Vin (V) -> Freq (MHz), interpolada. La curva es monótona creciente."""
    df = pd.read_csv(path, decimal=",").dropna(subset=["Vin", "Freq"])
    df = df.sort_values("Vin")
    # extrapolate: la medición arranca en Vin=0,002 V, no exactamente en 0
    return interp1d(df["Vin"], df["Freq"] * 1e6, kind="cubic",
                     fill_value="extrapolate")


def eje_theta(curva_vco, t):
    """
    A partir de la rampa lineal V(t) y la curva real del VCO, arma:
      f(t)      frecuencia real instantánea
      theta(t)  eje de tiempo deformado que linealiza el barrido
      alpha0    pendiente ideal (Hz/s) usada como referencia

    La duración de la rampa sale de 't', NO de la constante T_SWEEP. Con un
    generador de laboratorio la rampa dura lo que dura, no exactamente lo
    nominal, y una discrepancia ahí escala alpha0 y corre todas las
    distancias sin que nada avise. Los llamadores arman 't' con
    linspace(0, T, n, endpoint=False), así que la duración real ya viene
    adentro: T = t[-1] + paso.
    """
    paso = t[1] - t[0]
    T = t[-1] + paso
    v_t = V_MIN + (V_MAX - V_MIN) * (t / T)
    f_t = curva_vco(v_t)
    g_t = f_t - f_t[0]
    bw  = curva_vco(V_MAX) - curva_vco(V_MIN)
    alpha0 = bw / T
    theta = g_t / alpha0
    return f_t, theta, alpha0


def medir_rampa(sync, n_nominal, tol=0.2):
    """
    Largo real de una rampa de subida, en muestras, medido de la columna de
    sync. Devuelve None si no hay suficientes reinicios para decidir.

    No se puede saber de antemano si el generador marca una vez por rampa o
    una vez por ciclo completo, así que se compara la mediana de las
    distancias entre reinicios contra n_nominal y contra 2*n_nominal, y se
    elige la más cercana. Se usa la mediana y no el promedio porque un
    flanco perdido mete una distancia del doble o del triple, y la mediana
    no se inmuta.
    """
    ini = np.where(np.diff(sync) < 0)[0] + 1
    if len(ini) < 3:
        return None
    gap = np.median(np.diff(ini))
    if abs(gap - n_nominal) <= abs(gap - 2 * n_nominal):
        largo = gap
    else:
        largo = gap / 2
    if abs(largo - n_nominal) > tol * n_nominal:
        print(f"  [!] la rampa medida ({largo:.0f} muestras) difiere más del "
              f"{tol:.0%} de la nominal ({n_nominal}): revisá T_SWEEP o el sync")
        return None
    return int(round(largo))


def buscar_periodo(idx, val, fs, t_min=12e-3, t_max=200e-3):
    """
    Estimación GRUESA del período de la triangular, sin saber cuánto vale.

    ajustar_triangular() refina alrededor de un valor que ya se conoce; ésta
    es la que lo encuentra de cero, para no tener que tocar T_SWEEP cada vez
    que se cambia el Tprf del generador.

    Es una FFT sobre las lecturas del ADC. Llegan a paso fijo (una por bloque
    de DMA), así que ya están uniformemente muestreadas; si se perdió alguna
    línea el paso se rompe, y por eso se interpola a una grilla pareja antes.

    El máximo se busca sobre el PRIMER armónico. No hay riesgo de engancharse
    en un múltiplo: en 2T una triangular simétrica no tiene nada (sólo tiene
    armónicos impares) y en 3T tiene 1/9 de la amplitud.

    `t_min` no puede bajar de 2/187,5 s ~ 11 ms: es el Nyquist de las lecturas
    de la triangular, que salen a una por bloque de DMA.
    """
    idx = np.asarray(idx, dtype=float)
    val = np.asarray(val, dtype=float)
    if len(idx) < 32:
        return None
    paso = np.median(np.diff(idx))
    if paso <= 0:
        return None
    g = np.arange(idx[0], idx[-1], paso)
    v = np.interp(g, idx, val)
    v = v - v.mean()
    fs_g = fs / paso
    V = np.abs(np.fft.rfft(v * np.hanning(len(v))))
    f = np.fft.rfftfreq(len(v), 1.0 / fs_g)
    ok = (f >= 1.0 / t_max) & (f <= 1.0 / t_min) & (f > 0)
    if not ok.any():
        return None
    return 1.0 / f[ok][np.argmax(V[ok])]


def ajustar_triangular(idx, val, fs, T_nom, span=0.25):
    """
    Ajusta UN período y UNA fase a la triangular muestreada por el ADC.
    Devuelve (T, t0): período completo (subida+bajada) en segundos, y el
    instante del primer vértice de MÍNIMO, en segundos desde idx=0.

    'idx' y 'val' son las columnas de triangular.csv: índice de muestra de
    batido y valor crudo del ADC. 'T_nom' es el período de arranque de la
    búsqueda, en segundos, y 'span' cuánto se busca alrededor (±25 % por
    defecto; en tiempo real, cuando ya se conoce el período, conviene
    achicarlo mucho para que el ajuste sea barato y no salte de armónico).

    No se busca el vértice período por período. Con ~125 períodos en 5 s, el
    brazo de palanca de esos 5 segundos da el período con mucha más precisión
    que cualquier vértice individual, y de ahí salen todos los límites por
    multiplicación.

    El período se refina maximizando la magnitud del primer armónico, en dos
    pasadas (gruesa y fina). La fase sale del argumento de ese mismo armónico:
    una triangular con el mínimo en el origen es par, así que su primer
    armónico es real y negativo, y el desfasaje respecto de eso ubica el
    vértice.
    """
    t = np.asarray(idx, dtype=float) / fs
    v = np.asarray(val, dtype=float)
    v = v - v.mean()

    def armonico(T):
        return np.sum(v * np.exp(-2j * np.pi * t / T))

    for lo, hi, pasos in ((1 - span, 1 + span, 600), (0.998, 1.002, 400)):
        Ts = np.linspace(T_nom * lo, T_nom * hi, pasos)
        T_nom = Ts[np.argmax([abs(armonico(T)) for T in Ts])]
    T = T_nom

    # Con v(t) = f((t-t0)/T) y f par (mínimo en el origen), sale
    # S = N*c1*exp(-2i*pi*t0/T) con c1 real NEGATIVO, o sea
    # arg(S) = -2*pi*t0/T + pi. Ojo con el signo: invertirlo devuelve T-t0 en
    # vez de t0, y eso agarra la bajada creyendo que es la subida.
    t0 = (np.pi - np.angle(armonico(T))) / (2 * np.pi) * T
    return T, t0 % T


def rampas_desde_triangular(beat, idx, val, fs, n_nominal, span=0.25):
    """
    Límites de rampa sacados de la triangular muestreada por el ADC, para
    cuando el generador no da sync. Es ajustar_triangular() + el troceo.

    Devuelve (rampas, indices, n): las rampas ya orientadas como subida, con
    la bajada invertida en el tiempo como hace extraer_rampas().

    El período se BUSCA con buscar_periodo() y sólo se cae a `n_nominal` si la
    búsqueda no encuentra nada. Así, cambiar el Tprf del generador no obliga a
    tocar T_SWEEP para volver a analizar: la constante queda sólo como red de
    seguridad.
    """
    T_ini = buscar_periodo(idx, val, fs)
    if T_ini is None:
        T_ini, span = 2.0 * n_nominal / fs, span
    else:
        span = 0.10
    T, t0 = ajustar_triangular(idx, val, fs, T_ini, span)

    n = int(round(T * fs / 2))
    rampas, indices, subidas = [], [], 0
    k = 0
    while True:
        inicio = int(round((t0 + k * T) * fs))
        if inicio + n > len(beat):
            break
        k += 1
        if inicio < 0:
            continue
        rampas.append(beat[inicio:inicio + n])       # subida
        indices.append(inicio)
        subidas += 1
        if inicio + 2 * n <= len(beat):              # bajada, invertida
            rampas.append(beat[inicio + n:inicio + 2 * n][::-1])
            indices.append(inicio + n)
    print(f"  triangular: periodo {T*1e3:.3f} ms ({1/T:.3f} Hz), rampa {n} "
          f"muestras, {subidas} subidas + {len(rampas)-subidas} bajadas")
    return rampas, indices, n


def remuestrear(theta, señal, n):
    """Lleva la señal de theta (no uniforme) a una grilla theta uniforme."""
    theta_uniforme = np.linspace(theta[0], theta[-1], n)
    interp = interp1d(theta, señal, kind="cubic")
    return theta_uniforme, interp(theta_uniforme)


def fs_theta(theta, n):
    """
    Sample rate efectiva de la señal remuestreada por remuestrear().

    remuestrear() arma la grilla con linspace(theta[0], theta[-1], n), o sea
    n puntos y n-1 pasos: el paso es (theta[-1]-theta[0])/(n-1). Usar
    n/(theta[-1]-theta[0]) sobrestima la fs en un factor n/(n-1) (0,8 % con
    122 muestras por rampa) y eso escala TODAS las distancias, igual que el
    problema de T_SWEEP que documenta GPRv2/CLAUDE.md. Usar FS_CSV a secas
    tampoco es exacto (+0,27 %): theta no termina en T, termina en
    (f(t_ultimo)-f(0))/alpha0, y la curva del VCO no es lineal.
    """
    return (n - 1) / (theta[-1] - theta[0])


def perfil_distancia(señal, fs, alpha0):
    """FFT -> eje de rango, con la relación ideal f_beat = 2*R*alpha0/c."""
    n = len(señal)
    espectro = np.abs(np.fft.rfft(señal * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    rango = freqs * C / (2.0 * alpha0)
    return rango, espectro


def extraer_rampas(beat, sync, n, tol=0.1):
    """
    Devuelve (rampas, indices): cada rampa es un array de largo n, ya
    orientada como una SUBIDA (la bajada de una triangular llega invertida
    en el tiempo, lista para aplicarle el mismo mapa theta que a una
    subida). 'indices' es la muestra donde empieza cada una, para poder
    ubicarlas en el tiempo real de la captura.

    El generador de laboratorio es una triangular real (CONTEXTO.md §2), y
    no se sabe de antemano si el sync marca el principio de cada rampa de
    subida (una vez por rampa) o el principio de cada ciclo completo
    subida+bajada (una vez cada dos rampas) - depende del generador
    concreto y hay que verlo en el osciloscopio para saber cual es. Esta
    función no asume ninguna de las dos: mide la distancia real entre
    reinicios de 'sync' y decide segmento por segmento.
      - distancia ~= n       -> una sola subida entre reinicios (se usa tal cual).
      - distancia ~= 2*n     -> ciclo completo: la primera mitad es la
                                subida (se usa tal cual) y la segunda es la
                                bajada (se invierte con [::-1] antes de
                                usarla - el batido de una bajada simétrica,
                                leído al revés, es igual al de una subida).
      - cualquier otro valor -> se descarta (sync irregular o perdido).

    El ÚLTIMO reinicio del archivo, si no hay uno siguiente para medir la
    distancia real, se mide contra el final del archivo: si eso da ~n o ~2n
    se trata igual que cualquier otro (el archivo simplemente terminó justo
    ahí, sin nada raro). Si no da ninguno de los dos, no hay forma de saber
    si la grabación cortó a mitad de una bajada o si se perdió un flanco de
    sync - se descarta ese tramo por las dudas, no se arriesga una subida
    mezclada con datos de otra rampa.
    """
    ini = np.where(np.diff(sync) < 0)[0] + 1
    rampas, indices = [], []
    un_lado = ciclo = descartadas = 0
    for k, i in enumerate(ini):
        if i + n > len(beat):
            continue
        siguiente = ini[k + 1] if k + 1 < len(ini) else len(beat)
        gap = siguiente - i
        if abs(gap - n) <= tol * n:
            rampas.append(beat[i:i + n]); indices.append(i)
            un_lado += 1
        elif abs(gap - 2 * n) <= tol * n:
            rampas.append(beat[i:i + n]); indices.append(i)
            if i + 2 * n <= len(beat):
                rampas.append(beat[i + n:i + 2 * n][::-1]); indices.append(i + n)
            ciclo += 1
        else:
            descartadas += 1
    print(f"  rampas: {un_lado} de subida sola, {ciclo} ciclos completos "
          f"(subida+bajada invertida), {descartadas} descartadas por sync irregular")
    return rampas, indices


# ─── Modo sintético ───────────────────────────────────────────────────────

def generar_beat_sintetico(curva_vco, t):
    """
    Señal de batido con la no linealidad real del VCO: para un blanco a
    distancia r, la fase de batido es 2*pi*tau*(f(t) - f(0)) (tau = 2r/c).
    Con un barrido lineal ideal esto se reduce a la fórmula clásica
    f_beat = tau*alpha0 = cte; con la curva real no es constante, y ESO es
    lo que el remuestreo tiene que arreglar.
    """
    f_t = curva_vco(V_MIN + (V_MAX - V_MIN) * (t / T_SWEEP))
    g_t = f_t - f_t[0]

    señal = np.zeros_like(t)
    for r, amp_db in BLANCOS:
        tau = 2.0 * r / C
        amp = 10.0 ** (amp_db / 20.0)
        fase0 = np.random.uniform(0, 2 * np.pi)
        señal += amp * np.cos(2 * np.pi * tau * g_t + fase0)

    pico = np.max(np.abs(señal))
    señal += np.random.normal(0.0, pico * 10 ** (RUIDO_DB / 20.0), len(t))
    return señal


def correr_sintetico():
    curva_vco = cargar_curva_vco(VCO_CSV)
    n = int(round(T_SWEEP * FS_SINTETICO))
    t = np.linspace(0, T_SWEEP, n, endpoint=False)

    beat = generar_beat_sintetico(curva_vco, t)
    f_t, theta, alpha0 = eje_theta(curva_vco, t)

    print(f"BW real (curva VCO, {V_MIN}-{V_MAX} V): {(curva_vco(V_MAX)-curva_vco(V_MIN))/1e6:.1f} MHz")
    print(f"alpha0 (pendiente ideal): {alpha0/1e6:.2f} MHz/s")
    print("Blancos simulados:", BLANCOS)

    rango_sin, esp_sin = perfil_distancia(beat, FS_SINTETICO, alpha0)

    theta_u, beat_corr = remuestrear(theta, beat, n)
    fs_theta = n / (theta_u[-1] - theta_u[0])
    rango_con, esp_con = perfil_distancia(beat_corr, fs_theta, alpha0)

    graficar(t, beat, rango_sin, esp_sin, rango_con, esp_con)


# ─── Modo CSV real ────────────────────────────────────────────────────────

def correr_csv():
    curva_vco = cargar_curva_vco(VCO_CSV)
    d = pd.read_csv(CSV_ENTRADA, header=None).to_numpy(dtype=float)
    beat_completo, sync = d[:, 0], d[:, 1]   # adquisicion.ino emite L,sync
    n = int(round(T_SWEEP * FS_CSV))
    medido = medir_rampa(sync, n)
    if medido and medido != n:
        print(f"  rampa medida: {medido} muestras en vez de {n}")
        n = medido
    t = np.linspace(0, n / FS_CSV, n, endpoint=False)

    f_t, theta, alpha0 = eje_theta(curva_vco, t)
    print(f"Muestras leídas: {len(beat_completo)}  (fs={FS_CSV} sps, "
          f"T_rampa={n/FS_CSV*1e3:.2f} ms, n={n})")

    rampas, _ = extraer_rampas(beat_completo, sync, n)
    if not rampas:
        raise SystemExit("No se encontró ninguna rampa completa - revisá que el sync esté conectado.")
    beat = rampas[0]

    rango_sin, esp_sin = perfil_distancia(beat, FS_CSV, alpha0)

    theta_u, beat_corr = remuestrear(theta, beat, n)
    fs_theta = n / (theta_u[-1] - theta_u[0])
    rango_con, esp_con = perfil_distancia(beat_corr, fs_theta, alpha0)

    graficar(t, beat, rango_sin, esp_sin, rango_con, esp_con)


# ─── Gráficos ─────────────────────────────────────────────────────────────

def graficar(t, beat, rango_sin, esp_sin, rango_con, esp_con):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(9, 8))

    ax1.plot(t * 1e3, beat)
    ax1.set_xlabel("t [ms]")
    ax1.set_ylabel("beat(t)")
    ax1.set_title("Señal de batido cruda")

    ax2.plot(rango_sin, esp_sin)
    ax2.set_xlabel("Rango [m]")
    ax2.set_title("Perfil de distancia SIN corrección")
    ax2.set_xlim(0, max(r for r, _ in BLANCOS) * 1.5 if MODO == "sintetico" else None)

    ax3.plot(rango_con, esp_con)
    ax3.set_xlabel("Rango [m]")
    ax3.set_title("Perfil de distancia CON corrección (remuestreo en θ)")
    ax3.set_xlim(0, max(r for r, _ in BLANCOS) * 1.5 if MODO == "sintetico" else None)

    fig.tight_layout()
    plt.show()


# ─── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if MODO == "sintetico":
        correr_sintetico()
    elif MODO == "csv":
        correr_csv()
    else:
        raise SystemExit(f"MODO desconocido: {MODO!r} (usar 'sintetico' o 'csv')")
