"""
Grabador: captura el beat desde la placa de audio (U-Phoria UMC22) a CSV + WAV.

    python grabaraudio.py               graba
    python grabaraudio.py --listar      muestra las entradas de audio
    python grabaraudio.py --calibrar 1.52   calibra la escala vertical
    python grabaraudio.py --test        autoprueba, sin hardware

Es el reemplazo TEMPORAL de grabarserial.py mientras se usa la placa de sonido
en lugar del PCM1808 + ESP32. La cadena de RF no cambia: cambia solo quien
digitaliza.

Escribe DOS archivos por captura, a proposito:

  datos/AAAA-MM-DD_HHMMSS.csv   solo el canal de beat, mismo formato exacto que
                                grabarserial.py -> graficarserial.py lo abre sin
                                tocarle una linea.
  datos/AAAA-MM-DD_HHMMSS.wav   los dos canales crudos en 16 bits. Es el master
                                para el analisis offline: si se grabo el
                                sincronismo de la rampa, esta ahi.

Los dos se escriben incrementalmente con flush periodico: si el programa se
corta a la mitad, lo grabado hasta ese momento es valido y esta en disco.
"""

import json
import os
import queue
import sys
import time
from datetime import datetime

import numpy as np

import audio

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config.json")
DATOS = os.path.normpath(os.path.join(AQUI, "..", "datos"))

C_LUZ = 3e8

# Cuadros por bloque del callback. 1024 a 48 kHz son 21 ms: suficiente para que
# el hilo de audio no se quede esperando al disco, y poco como para que la
# barra de estado se vea fluida.
BLOQUE = 1024

# Umbral de clipeo. La UMC22 satura en -3 dBu con la perilla al minimo, y lo que
# llega aca ya viene recortado: se detecta contando muestras pegadas al tope.
CLIP = 32700

# Frecuencia de corte inferior de la placa, de la hoja de datos: 10 Hz a -3 dB.
# Es MAS alta que el pasa-altos del PCM1808 (0.91 Hz a 48 kHz), asi que la
# restriccion sobre el sweep no se relaja al cambiar de ADC: se endurece.
CORTE_PLACA_HZ = 10.0

# Zona util del radar, para avisar si el beat cae contra el corte de la placa.
R_MIN_UTIL = 0.2

# Cuanto se le tolera a la tasa real de muestreo antes de dar la alarma. Ver
# medir_tasa(): 2 % es holgado para un cristal y estrecho para un error de
# configuracion, que se va en decenas de por ciento.
TOLERANCIA_FS = 0.02

POR_DEFECTO = {
    "dispositivo":      "auto",        # auto | indice | parte del nombre
    "fs":               48000,
    "canal_beat":       2,             # 2 = INSTRUMENT (Hi-Z), la que se usa
    "canal_sync":       1,             # 1 = combo, rampa del DAC; 0 = sin sync
    "exclusivo":        1,             # 1 = pedir modo exclusivo si se puede
    "escala_v_por_fs":  0.0,           # 0 = sin calibrar -> se graba en FS
    "atenuador":        10.1,          # divisor externo, solo informativo
    "f_start_ghz":      1.00,
    "f_stop_ghz":       2.00,
    "t_sweep_ms":       10.0,
    "duracion_s":       30.0,          # 0 = hasta Ctrl+C
    "nota":             "",
}

CAMPOS = [
    ("dispositivo",     "Dispositivo ('auto', indice o parte del nombre)", str),
    ("fs",              "Frecuencia de muestreo [Hz]",                     int),
    ("canal_beat",      "Canal del beat (1=combo, 2=instrument)",          int),
    ("canal_sync",      "Canal del sincronismo (0 = no grabarlo)",         int),
    ("exclusivo",       "Modo exclusivo, saltea el mezclador (1/0)",       int),
    ("atenuador",       "Divisor externo a la entrada (1 = ninguno)",      float),
    ("f_start_ghz",     "Frecuencia inicial del sweep [GHz]",              float),
    ("f_stop_ghz",      "Frecuencia final del sweep [GHz]",                float),
    ("t_sweep_ms",      "Duracion del sweep [ms]",                         float),
    ("duracion_s",      "Duracion de la grabacion [s] (0 = Ctrl+C)",       float),
    ("nota",            "Nota descriptiva de la medicion",                 str),
]


def cargar_config():
    cfg = dict(POR_DEFECTO)
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[aviso] No se pudo leer config.json ({e}); uso los valores por defecto.")
    return cfg


def guardar_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def preguntar(cfg):
    print()
    print("=" * 68)
    print(" Configuracion de la medicion (placa de audio)")
    print(" Enter deja el valor entre corchetes; escribi para cambiarlo.")
    print("=" * 68)

    for clave, texto, tipo in CAMPOS:
        while True:
            actual = cfg.get(clave, "")
            r = input(f"  {texto} [{actual}]: ").strip()
            if r == "":
                break
            try:
                cfg[clave] = tipo(r)
                break
            except ValueError:
                print(f"    -> tiene que ser {tipo.__name__}")

    if cfg["canal_beat"] == cfg["canal_sync"]:
        print("    [aviso] beat y sync no pueden ser el mismo canal; apago el sync.")
        cfg["canal_sync"] = 0
    return cfg


def resumen(cfg):
    """Calcula los numeros derivados y avisa si algo no cierra."""
    fs = float(cfg["fs"])
    bw_mhz = (cfg["f_stop_ghz"] - cfg["f_start_ghz"]) * 1000.0
    t_sweep = cfg["t_sweep_ms"] / 1000.0
    hz_por_metro = 2.0 * (bw_mhz * 1e6) / (C_LUZ * t_sweep)
    muestras_sweep = fs * t_sweep
    beat_min = hz_por_metro * R_MIN_UTIL
    r_max = fs / 2 / hz_por_metro if hz_por_metro else float("inf")

    n_canales = max(cfg["canal_beat"], cfg["canal_sync"])
    # El CSV es texto: ~20 bytes por muestra. El WAV son 2 bytes por canal.
    mb_csv = fs * 20 * max(cfg["duracion_s"], 0) / 1e6
    mb_wav = fs * 2 * n_canales * max(cfg["duracion_s"], 0) / 1e6

    print()
    print("-" * 68)
    print(f"  Ancho de banda      : {bw_mhz:.0f} MHz")
    print(f"  Resolucion          : {C_LUZ / (2 * bw_mhz * 1e6) * 100:.1f} cm")
    print(f"  Beat                : {hz_por_metro:.1f} Hz por metro")
    print(f"  fs                  : {fs:.0f} Hz  ({n_canales} canal/es)")
    print(f"  Muestras por sweep  : {muestras_sweep:.1f}")
    print(f"  Beat a {R_MIN_UTIL:.1f} m         : {beat_min:.1f} Hz")
    print(f"  Alcance maximo      : {r_max:.2f} m (Nyquist)")
    if cfg["duracion_s"] > 0:
        print(f"  Archivos            : ~{mb_csv:.0f} MB de CSV + ~{mb_wav:.0f} MB de WAV")
    print("-" * 68)

    if beat_min < 5 * CORTE_PLACA_HZ:
        print(f"  [AVISO] A {R_MIN_UTIL:.1f} m el beat da {beat_min:.1f} Hz y la placa cae")
        print(f"          a -3 dB en {CORTE_PLACA_HZ:.0f} Hz. Acorta t_sweep: el sweep")
        print("          rapido es tan necesario aca como con el PCM1808, o mas.")
    if muestras_sweep < 32:
        print("  [AVISO] Muy pocas muestras por sweep. Alarga t_sweep o subi fs.")
    if cfg["escala_v_por_fs"] <= 0:
        print("  [AVISO] Sin calibrar: el eje vertical va en fraccion de fondo de")
        print("          escala, no en volts. Corre --calibrar cuando tengas una")
        print("          amplitud conocida a mano.")
    return fs, bw_mhz, hz_por_metro, n_canales


def abrir_stream(cfg, n_canales, cola, estado, forzar_compartido=False):
    """Abre el InputStream ya resuelto. Devuelve (stream, entrada, exclusivo)."""
    import sounddevice as sd

    entrada = audio.elegir(cfg["dispositivo"], n_canales)
    if entrada is None:
        print("\n[ERROR] No encontre la placa de audio. Entradas disponibles:\n")
        print(audio.tabla())
        print("\n  - Revisa que la UMC22 este enchufada por USB.")
        print("  - O pone el indice a mano en 'dispositivo'.")
        sys.exit(1)

    if entrada.canales < n_canales:
        print(f"\n[ERROR] '{entrada.nombre}' ({entrada.api}) ofrece "
              f"{entrada.canales} canal/es")
        print(f"        y hacen falta {n_canales}. Ninguna de las APIs donde "
              "aparece la placa")
        print("        ofrece esa cantidad. Opciones, en orden:")
        print("          - Panel de sonido -> Propiedades del dispositivo ->")
        print("            Avanzado -> formato de 2 canales, 16 bit, 48000 Hz.")
        print("            Windows lo suele dejar en 1 canal y ahi WASAPI reporta mono.")
        print("          - Instalar el driver ASIO de Behringer.")
        print("          - Poner canal_sync = 0 y grabar un solo canal.")
        print("\n  Entradas disponibles:\n")
        print(audio.tabla())
        sys.exit(1)

    def callback(datos, cuadros, tiempo, flags):
        # El hilo de audio NO toca el disco: copia y sigue. Todo lo que tarde
        # aca se transforma en un overflow, o sea en muestras perdidas.
        if flags.input_overflow:
            estado["overflow"] += 1
        cola.put(datos.copy())

    comun = dict(device=entrada.idx, channels=n_canales,
                 samplerate=int(cfg["fs"]), dtype="int16",
                 blocksize=BLOQUE, callback=callback)

    if cfg["exclusivo"] and not forzar_compartido:
        extra = audio.ajustes_exclusivos(entrada)
        if extra is not None:
            try:
                return sd.InputStream(extra_settings=extra, **comun), entrada, True
            except Exception as e:
                # Pasa cuando otra aplicacion ya tiene la placa tomada, o cuando
                # la fs pedida no es la nativa del dispositivo. Se sigue en modo
                # compartido, pero avisando: ahi el mezclador puede reamostrear.
                print(f"\n  [aviso] No pude abrir en modo exclusivo ({e}).")
                print("          Sigo en modo compartido: revisa que en las")
                print("          propiedades del dispositivo este en 48000 Hz y")
                print("          que las 'mejoras' de audio esten desactivadas.")

    return sd.InputStream(**comun), entrada, False


def medir_tasa(stream, cola, canales, segundos=2.0, calentar=0.5):
    """Cuenta cuantas muestras por segundo entrega REALMENTE el stream.

    No es paranoia. Probando esto en el banco contra la placa interna de la
    maquina, WASAPI en modo EXCLUSIVO declaraba stream.samplerate = 48000 y
    entregaba 63.2 kS/s; el mismo dispositivo en modo compartido daba 47.7 kS/s,
    que es lo correcto.

    Un error asi no se ve en ningun lado: el WAV suena raro y nada mas. Pero el
    eje de frecuencias queda corrido un 32 %, y como la distancia sale de la
    frecuencia de beat, todas las mediciones salen mal en silencio. Por eso la
    tasa se MIDE antes de grabar en vez de creerle al driver.

    El calentamiento no es adorno. Entre el start() y el primer bloque hay una
    latencia de arranque que depende de la API —con WDM-KS son decenas de ms— y
    contarla adentro de la ventana da un error FIJO en tiempo que se traduce en
    un porcentaje: con 1.5 s de ventana, WDM-KS aparecia 4 % lento y disparaba
    la alarma sin tener nada malo. Se descartan los primeros bloques y recien
    ahi arranca el cronometro.
    """
    # Esperar al primer bloque: hasta que no llega, el stream todavia no corre.
    t_ini = time.time()
    while time.time() - t_ini < 5.0:
        try:
            cola.get(timeout=0.2)
            break
        except queue.Empty:
            pass

    t0 = time.time()
    while time.time() - t0 < calentar:
        try:
            cola.get(timeout=0.2)
        except queue.Empty:
            pass

    t0 = time.time()
    n = 0
    while time.time() - t0 < segundos:
        try:
            n += len(cola.get(timeout=0.2))
        except queue.Empty:
            pass
    return n / (time.time() - t0)


def abrir_y_verificar(cfg, n_canales, cola, estado):
    """Abre el stream, mide la tasa real y cae a modo compartido si no cierra.

    Devuelve (stream YA ARRANCADO, entrada, exclusivo, fs_medida).
    """
    fs_nom = float(cfg["fs"])

    def intentar(forzar_compartido):
        st, ent, exc = abrir_stream(cfg, n_canales, cola, estado,
                                    forzar_compartido=forzar_compartido)
        st.start()
        med = medir_tasa(st, cola, n_canales)
        return st, ent, exc, med, abs(med - fs_nom) / fs_nom

    print("\n  Verificando la tasa de muestreo real...")
    stream, entrada, exclusivo, medida, error = intentar(False)

    if error > TOLERANCIA_FS and exclusivo:
        print(f"  [aviso] En modo exclusivo entrega {medida:.0f} S/s y pidio "
              f"{fs_nom:.0f}. Reintento compartido.")
        stream.stop()
        stream.close()
        while not cola.empty():
            cola.get_nowait()
        stream, entrada, exclusivo, medida, error = intentar(True)

    if error > TOLERANCIA_FS:
        print()
        print("  " + "!" * 62)
        print(f"  !! La placa entrega {medida:.0f} S/s pero se le pidieron "
              f"{fs_nom:.0f} S/s.")
        print(f"  !! Son {error * 100:.1f} % de error. El eje de frecuencias, y por")
        print("  !! lo tanto el de distancias, va a quedar corrido en esa misma")
        print("  !! proporcion. Antes de medir en serio:")
        print("  !!   - Propiedades del dispositivo -> Avanzado -> 48000 Hz, 16 bit")
        print("  !!   - Desactivar todas las 'mejoras' de audio")
        print("  !!   - Probar con el driver ASIO de Behringer")
        print("  " + "!" * 62)
    else:
        print(f"  Tasa real: {medida:.0f} S/s contra {fs_nom:.0f} nominales "
              f"({error * 100:.2f} % de error). Bien.")

    # Lo capturado durante la verificacion se descarta: es el arranque del
    # stream y ademas ya se conto aparte.
    while not cola.empty():
        cola.get_nowait()
    return stream, entrada, exclusivo, medida


def escribir_encabezado(f, cfg, inicio, fs, bw_mhz, hz_por_metro,
                        entrada, exclusivo, unidad, fs_medida=0.0):
    """Todo lo que hace falta para interpretar el archivo dentro de dos meses.

    Las claves fs_eff, bw_mhz y t_sweep_ms son las que lee graficarserial.py.
    fs_eff existe aca aunque no haya diezmado, justamente para no tener que
    tocar el graficador.

    fs_eff queda en la NOMINAL a proposito, no en la medida: si las dos difieren
    hay un problema de configuracion que se arregla, no se compensa por software
    metiendo un numero raro en el eje. La medida se guarda al lado para que se
    pueda ver despues que las dos coincidian.
    """
    f.write(f"# fecha            = {inicio.isoformat(timespec='seconds')}\n")
    f.write(f"# adquisicion      = placa de audio (reemplazo temporal del PCM1808)\n")
    f.write(f"# dispositivo      = {entrada.nombre}\n")
    f.write(f"# api_audio        = {entrada.api}\n")
    f.write(f"# modo_exclusivo   = {'si' if exclusivo else 'no'}\n")
    f.write(f"# f_start_ghz      = {cfg['f_start_ghz']}\n")
    f.write(f"# f_stop_ghz       = {cfg['f_stop_ghz']}\n")
    f.write(f"# bw_mhz           = {bw_mhz:.1f}\n")
    f.write(f"# t_sweep_ms       = {cfg['t_sweep_ms']}\n")
    f.write(f"# hz_por_metro     = {hz_por_metro:.4f}\n")
    f.write(f"# fs               = {int(fs)}\n")
    f.write(f"# fs_medida        = {fs_medida:.1f}\n")
    f.write(f"# dec              = 1\n")
    f.write(f"# fs_eff           = {fs:.4f}\n")
    f.write(f"# modo             = continuo\n")
    f.write(f"# canal_beat       = {cfg['canal_beat']}\n")
    f.write(f"# canal_sync       = {cfg['canal_sync']}\n")
    f.write(f"# atenuador        = {cfg['atenuador']}\n")
    f.write(f"# escala_v_por_fs  = {cfg['escala_v_por_fs']}\n")
    f.write(f"# unidad           = {unidad}\n")
    f.write(f"# nota             = {cfg['nota']}\n")
    f.write("#\nidx,V\n")


def main():
    cfg = preguntar(cargar_config())
    guardar_config(cfg)
    fs, bw_mhz, hz_por_metro, n_canales = resumen(cfg)

    # Sin calibracion el CSV va en fraccion de fondo de escala. La columna se
    # sigue llamando 'V' para que graficarserial.py no cambie, pero el
    # encabezado dice la verdad en '# unidad'.
    escala = cfg["escala_v_por_fs"]
    unidad = "V" if escala > 0 else "FS"
    factor = escala if escala > 0 else 1.0

    cola = queue.Queue()
    estado = {"overflow": 0}
    stream, entrada, exclusivo, fs_medida = abrir_y_verificar(
        cfg, n_canales, cola, estado)

    print(f"\n  Dispositivo : {entrada.nombre}")
    print(f"  API         : {entrada.api}"
          f"{'  (exclusivo)' if exclusivo else '  (compartido)'}")

    os.makedirs(DATOS, exist_ok=True)
    inicio = datetime.now()
    base = os.path.join(DATOS, inicio.strftime("%Y-%m-%d_%H%M%S"))
    ruta_csv, ruta_wav = base + ".csv", base + ".wav"

    i_beat = cfg["canal_beat"] - 1
    wav = audio.EscritorWav(ruta_wav, n_canales, fs)

    muestras = 0
    clips = 0
    pico = 0
    t0 = time.time()

    # Para medir el ritmo real hay que cronometrar ENTRE bloques, no desde el
    # arranque: la latencia de la primera entrega es un retardo fijo que, metido
    # en el promedio, hace aparecer la captura mas lenta de lo que es. Se guarda
    # cuando llego el primer bloque y cuantas muestras vinieron despues de el.
    t_primero = None
    t_ultimo = None
    muestras_ritmo = 0

    with open(ruta_csv, "w", encoding="utf-8", newline="") as f:
        escribir_encabezado(f, cfg, inicio, fs, bw_mhz, hz_por_metro,
                            entrada, exclusivo, unidad, fs_medida)
        f.flush()

        print(f"\n  Grabando en: {os.path.basename(ruta_csv)} (+ .wav)")
        print("  Ctrl+C para terminar.\n")

        # El stream ya viene arrancado desde la verificacion de tasa.
        t0 = time.time()
        ultimo_flush = t0
        ultimo_aviso = t0

        try:
            while True:
                if cfg["duracion_s"] > 0 and time.time() - t0 >= cfg["duracion_s"]:
                    break
                try:
                    bloque = cola.get(timeout=0.2)
                except queue.Empty:
                    continue

                wav.escribir(bloque)

                if t_primero is None:
                    t_primero = time.time()
                else:
                    t_ultimo = time.time()
                    muestras_ritmo += len(bloque)

                beat = bloque[:, i_beat]
                p = int(np.max(np.abs(beat.astype(np.int32))))
                pico = max(pico, p)
                clips += int(np.count_nonzero(np.abs(beat.astype(np.int32)) >= CLIP))

                # El indice se escribe explicito por la misma razon que en
                # grabarserial.py: el numero de fila no es el tiempo. Aca ademas
                # es la unica forma de que se note un overflow, que corre el eje
                # temporal de todo lo que viene despues.
                vals = audio.a_fraccion(beat) * factor
                f.write("".join(f"{muestras + k},{v:.8f}\n"
                                for k, v in enumerate(vals)))
                muestras += len(vals)

                ahora = time.time()
                if ahora - ultimo_flush > 0.25:
                    f.flush()
                    os.fsync(f.fileno())
                    wav.sincronizar()
                    ultimo_flush = ahora

                if ahora - ultimo_aviso > 1.0:
                    seg = ahora - t0
                    ritmo = (muestras_ritmo / (t_ultimo - t_primero)
                             if t_ultimo and t_ultimo > t_primero else 0.0)
                    db = 20 * np.log10(pico / audio.FONDO_ESCALA) if pico else -99
                    sys.stdout.write(
                        f"\r  {seg:6.1f} s | {muestras:9d} muestras | "
                        f"{ritmo / 1000:6.2f} kS/s | pico {db:6.1f} dBFS | "
                        f"clip {clips} | overflow {estado['overflow']}   ")
                    sys.stdout.flush()
                    pico = 0                     # el pico es del ultimo segundo
                    ultimo_aviso = ahora

        except KeyboardInterrupt:
            print("\n\n  Interrumpido.")

        f.flush()
        os.fsync(f.fileno())

    stream.stop()
    stream.close()
    wav.cerrar()

    seg = time.time() - t0
    ritmo = (muestras_ritmo / (t_ultimo - t_primero)
             if t_ultimo and t_ultimo > t_primero else 0.0)
    print("\n" + "=" * 68)
    print(f"  CSV        : {ruta_csv}")
    print(f"  WAV        : {ruta_wav}")
    print(f"  Duracion   : {seg:.2f} s")
    print(f"  Muestras   : {muestras}")
    print(f"  Tasa       : {ritmo:.1f} S/s medidos, {fs:.0f} nominales "
          f"({abs(ritmo - fs) / fs * 100:.2f} % de error)")
    print(f"  Unidad     : {unidad}"
          f"{'' if unidad == 'V' else '  (sin calibrar; corre --calibrar)'}")
    if clips:
        print(f"  CLIPEO     : {clips} muestras al tope de escala")
        print("               Baja la perilla GAIN o agranda el divisor de entrada.")
    else:
        print("  Clipeo     : ninguno")
    if estado["overflow"]:
        print(f"  OVERFLOW   : {estado['overflow']} eventos")
        print("               Se perdieron muestras y el eje temporal quedo corrido")
        print("               a partir de ahi. Cerra lo que este usando el disco.")
    else:
        print("  Overflow   : ninguno")
    print("=" * 68)


# ---------------------------------------------------------------------------
# Calibracion de la escala vertical
# ---------------------------------------------------------------------------

def calibrar(vpp):
    """Mide cuantos volts del circuito equivalen a fondo de escala.

    Se inyecta una senal de amplitud CONOCIDA (por ejemplo la cuadrada de
    1.52 Vpp de firmware/generador_patron/, o un generador de funciones), se
    graban 2 s y se compara el pico medido contra el pico real.

    El numero que sale absorbe TODO: el divisor externo, la perilla GAIN y el
    fondo de escala de la placa. No se pueden separar y no hace falta.

    Por eso mismo: la calibracion vale mientras no se toque la perilla GAIN.
    Si la moves, hay que repetirla.
    """
    import sounddevice as sd

    cfg = cargar_config()
    n_canales = max(cfg["canal_beat"], cfg["canal_sync"])
    cola, estado = queue.Queue(), {"overflow": 0}
    stream, entrada, exclusivo = abrir_stream(cfg, n_canales, cola, estado)

    print(f"\n  Dispositivo : {entrada.nombre} ({entrada.api})")
    print(f"  Referencia  : {vpp} Vpp en el canal {cfg['canal_beat']}")
    print("  Grabando 2 s... no toques la perilla GAIN.\n")

    i_beat = cfg["canal_beat"] - 1
    trozos = []
    stream.start()
    t0 = time.time()
    while time.time() - t0 < 2.0:
        try:
            trozos.append(cola.get(timeout=0.2)[:, i_beat])
        except queue.Empty:
            pass
    stream.stop()
    stream.close()

    if not trozos:
        print("  [ERROR] No llego ninguna muestra.")
        return 1

    x = audio.a_fraccion(np.concatenate(trozos))
    # Percentil 99.9 y no el maximo: el maximo se lo lleva siempre una muestra
    # de ruido suelta. Es el mismo criterio que se uso para medir el desvio de
    # la rampa contra la recta en el osciloscopio.
    pico_fs = float(np.percentile(np.abs(x), 99.9))
    clips = int(np.count_nonzero(np.abs(np.concatenate(trozos)) >= CLIP))

    print(f"  Pico medido : {pico_fs:.5f} FS  ({20 * np.log10(pico_fs):.1f} dBFS)")
    if clips:
        print(f"  [ERROR] {clips} muestras clipeadas. Baja el GAIN y repeti:")
        print("          con la senal recortada la calibracion da cualquier cosa.")
        return 1
    if pico_fs < 0.02:
        print("  [ERROR] Senal demasiado chica (< -34 dBFS). Subi el GAIN y repeti.")
        return 1
    if pico_fs > 0.9:
        print("  [aviso] Muy cerca del tope. Deja algo de margen para la medicion.")

    escala = (vpp / 2.0) / pico_fs
    cfg["escala_v_por_fs"] = escala
    guardar_config(cfg)

    print(f"\n  escala_v_por_fs = {escala:.6f}  V pico por fondo de escala")
    print(f"  Fondo de escala = {2 * escala:.3f} Vpp en el circuito")
    print("  Guardado en config.json. Vale mientras no muevas la perilla GAIN.\n")
    return 0


# ---------------------------------------------------------------------------
# Autoprueba
# ---------------------------------------------------------------------------

def _test():
    import io
    import tempfile

    fallos = 0

    def check(nombre, cond, detalle=""):
        nonlocal fallos
        print(f"  {'ok   ' if cond else 'FALLA'}  {nombre:44s} {detalle}")
        if not cond:
            fallos += 1

    print("\n--- numeros derivados del sweep ---")
    cfg = dict(POR_DEFECTO)
    cfg["duracion_s"] = 0                       # calla el renglon de tamanos
    sal = io.StringIO()
    real, sys.stdout = sys.stdout, sal
    fs, bw, hzm, nc = resumen(cfg)
    sys.stdout = real
    texto = sal.getvalue()

    # BW = 1000 MHz -> 15 cm; T_sweep = 10 ms -> 666.7 Hz/m
    check("bw", abs(bw - 1000.0) < 1e-9, f"{bw:.1f} MHz")
    check("resolucion 15 cm", "15.0 cm" in texto)
    check("Hz por metro", abs(hzm - 666.667) < 0.01, f"{hzm:.2f}")
    check("canales = 2 con sync activo", nc == 2)
    check("alcance = Nyquist / (Hz por metro)",
          abs(fs / 2 / hzm - 36.0) < 0.1, f"{fs / 2 / hzm:.2f} m")

    print("\n--- avisos ---")
    lento = dict(POR_DEFECTO)
    lento["t_sweep_ms"] = 1460.0                # el sweep original de la tesis
    sal = io.StringIO()
    real, sys.stdout = sys.stdout, sal
    resumen(lento)
    sys.stdout = real
    check("avisa si el beat cae contra el corte de la placa",
          "-3 dB en 10 Hz" in sal.getvalue())

    sal = io.StringIO()
    real, sys.stdout = sys.stdout, sal
    resumen(dict(POR_DEFECTO))
    sys.stdout = real
    check("avisa que no esta calibrado", "Sin calibrar" in sal.getvalue())

    print("\n--- encabezado del CSV ---")
    ruta = os.path.join(tempfile.gettempdir(), "_prueba_grabaraudio.csv")
    ent = audio.Entrada(3, "UMC ASIO Driver", "ASIO", 2, 48000)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escribir_encabezado(f, cfg, datetime.now(), 48000.0, 1000.0, 666.667,
                            ent, True, "FS")
        f.write("0,0.10000000\n1,-0.20000000\n")

    # Se parsea igual que LectorCSV de graficarserial.py: si esto pasa, el
    # graficador abre el archivo sin cambiarle una linea.
    meta, filas = {}, []
    for linea in open(ruta, encoding="utf-8"):
        linea = linea.rstrip("\n")
        if not linea:
            continue
        if linea[0] == "#":
            if "=" in linea:
                k, v = linea[1:].split("=", 1)
                meta[k.strip()] = v.strip()
            continue
        if linea[0] == "i":
            continue
        a, b = linea.split(",")
        filas.append((int(a), float(b)))

    check("fs_eff en la metadata", meta.get("fs_eff") == "48000.0000",
          str(meta.get("fs_eff")))
    check("bw_mhz en la metadata", meta.get("bw_mhz") == "1000.0")
    check("t_sweep_ms en la metadata", meta.get("t_sweep_ms") == "10.0")
    check("unidad declarada", meta.get("unidad") == "FS")
    check("datos parseados", filas == [(0, 0.1), (1, -0.2)], str(filas))
    os.remove(ruta)

    print("\n--- conversion a la columna del CSV ---")
    # Con escala 1.6 V pico por fondo de escala, media escala son 0.8 V.
    medio = np.int16(16384)
    check("escala aplicada", abs(audio.a_fraccion(medio) * 1.6 - 0.8) < 1e-6)
    check("sin calibrar queda en FS", abs(audio.a_fraccion(medio) * 1.0 - 0.5) < 1e-6)

    print()
    if fallos:
        print(f"  {fallos} prueba(s) FALLARON")
        return 1
    print("  todo bien")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_test())
    if "--listar" in sys.argv:
        print("\nEntradas de audio disponibles:\n")
        print(audio.tabla())
        e = audio.elegir("auto")
        print(f"\n  auto -> {e if e else 'no encontre la placa'}\n")
        sys.exit(0)
    if "--calibrar" in sys.argv:
        i = sys.argv.index("--calibrar")
        if i + 1 >= len(sys.argv):
            print("Uso: python grabaraudio.py --calibrar <Vpp de la referencia>")
            sys.exit(1)
        sys.exit(calibrar(float(sys.argv[i + 1])))
    main()
