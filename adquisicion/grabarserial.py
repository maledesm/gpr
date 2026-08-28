"""
Grabador: lee el flujo binario del ESP32 y lo va escribiendo a un CSV.

    python grabarserial.py

Pregunta los parametros (con la ultima configuracion como valor por defecto),
abre el puerto, configura el firmware, y graba hasta que se cumple la duracion
o hasta Ctrl+C.

El archivo se escribe INCREMENTALMENTE, con flush periodico: si el programa se
corta a la mitad, lo grabado hasta ese momento es valido y esta en disco. Eso
tambien es lo que le permite a graficarserial.py leer el archivo mientras se
esta escribiendo.

Nombre del archivo:  datos/AAAA-MM-DD_HHMMSS.csv
"""

import json
import os
import sys
import time
from datetime import datetime

import serial

from protocolo import (Continuidad, Decodificador, arrancar_barrido,
                       autodetectar_puerto, comando, configurar,
                       configurar_barrido)

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config.json")
DATOS = os.path.normpath(os.path.join(AQUI, "..", "datos"))

POR_DEFECTO = {
    "firmware":          "gpr_barrido",  # gpr_barrido | PCM1808_ESP32C3
    "puerto":            "auto",
    "f_start_ghz":       1.00,
    "f_stop_ghz":        2.00,
    "fs":                16000,
    # --- solo gpr_barrido (el radar completo) ---
    "pasos":             25,
    "nmue":              8,
    "predist":           "si",
    # --- solo PCM1808_ESP32C3 (el banco con generador de funciones) ---
    "t_sweep_ms":        10.0,
    "dec":               4,
    "modo":              "continuo",   # continuo | rafaga
    "rafaga_on_sweeps":  3,
    "rafaga_off_sweeps": 1,
    "duracion_s":        30.0,         # 0 = hasta Ctrl+C
    "nota":              "",
}

CAMPOS = [
    ("firmware",          "Firmware cargado (gpr_barrido/PCM1808_ESP32C3)", str),
    ("puerto",            "Puerto serie ('auto' para detectar)",       str),
    ("f_start_ghz",       "Frecuencia inicial del sweep [GHz]",        float),
    ("f_stop_ghz",        "Frecuencia final del sweep [GHz]",          float),
    ("fs",                "Frecuencia de muestreo del ADC [Hz]",       int),
    ("pasos",             "  Escalones del DAC por rampa",             int),
    ("nmue",              "  Muestras del ADC por escalon",            int),
    ("predist",           "  Predistorsion del VCO (si/no)",           str),
    ("t_sweep_ms",        "  Duracion del sweep [ms]",                 float),
    ("dec",               "  Diezmado en el firmware",                 int),
    ("modo",              "  Modo de captura (continuo/rafaga)",       str),
    ("rafaga_on_sweeps",  "    Sweeps a capturar por rafaga",          int),
    ("rafaga_off_sweeps", "    Sweeps de pausa entre rafagas",         int),
    ("duracion_s",        "Duracion de la grabacion [s] (0 = Ctrl+C)", float),
    ("nota",              "Nota descriptiva de la medicion",           str),
]

# Los dos firmwares no comparten comandos, asi que tampoco comparten
# parametros. En gpr_barrido el tiempo de barrido NO se elige: sale de
# pasos, nmue y fs, y por eso no se pregunta (se calcula en resumen()).
SOLO_BARRIDO = {"pasos", "nmue", "predist"}
SOLO_BANCO = {"t_sweep_ms", "dec", "modo",
              "rafaga_on_sweeps", "rafaga_off_sweeps"}


def es_barrido(cfg):
    return cfg.get("firmware", "gpr_barrido") == "gpr_barrido"


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
    print("=" * 64)
    print(" Configuracion de la medicion")
    print(" Enter deja el valor entre corchetes; escribi para cambiarlo.")
    print("=" * 64)

    for clave, texto, tipo in CAMPOS:
        # 'firmware' se pregunta primero, asi que para cuando llegamos a los
        # campos especificos ya sabemos cual de los dos hay que ofrecer.
        if es_barrido(cfg) and clave in SOLO_BANCO:
            continue
        if not es_barrido(cfg) and clave in SOLO_BARRIDO:
            continue
        # Los campos de rafaga solo tienen sentido en ese modo
        if clave.startswith("rafaga_") and cfg.get("modo") != "rafaga":
            continue
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

    if cfg["firmware"] not in ("gpr_barrido", "PCM1808_ESP32C3"):
        print(f"    [aviso] firmware '{cfg['firmware']}' desconocido; "
              f"uso gpr_barrido.")
        cfg["firmware"] = "gpr_barrido"
    if cfg["modo"] not in ("continuo", "rafaga"):
        print(f"    [aviso] modo '{cfg['modo']}' desconocido; uso continuo.")
        cfg["modo"] = "continuo"
    return cfg


def resumen(cfg):
    """Calcula los numeros derivados y avisa si algo no cierra."""
    bw_mhz = (cfg["f_stop_ghz"] - cfg["f_start_ghz"]) * 1000.0
    resol_m = 3e8 / (2 * bw_mhz * 1e6)

    if es_barrido(cfg):
        # En gpr_barrido no hay diezmado, y el tiempo de barrido no se elige:
        # sale de la cuenta de escalones. Con N escalones hay N-1 intervalos.
        fs_eff = float(cfg["fs"])
        intervalos = max(1, cfg["pasos"] - 1)
        muestras_sweep = intervalos * cfg["nmue"]
        t_sweep = muestras_sweep / fs_eff
        cfg["t_sweep_ms"] = t_sweep * 1000.0     # derivado, va a la metadata
        raf_on = raf_off = 0
        util = 1.0
        paso_us = cfg["nmue"] * 1e6 / fs_eff
        amb_m = intervalos * resol_m
    else:
        fs_eff = cfg["fs"] / cfg["dec"]
        t_sweep = cfg["t_sweep_ms"] / 1000.0
        muestras_sweep = fs_eff * t_sweep
        paso_us = amb_m = None
        if cfg["modo"] == "rafaga":
            raf_on = int(round(cfg["rafaga_on_sweeps"] * muestras_sweep))
            raf_off = int(round(cfg["rafaga_off_sweeps"] * muestras_sweep))
            util = raf_on / (raf_on + raf_off)
        else:
            raf_on = raf_off = 0
            util = 1.0

    hz_por_metro = 2.0 * (bw_mhz * 1e6) / (3e8 * t_sweep)
    caudal = fs_eff * 4 * util / 1000.0          # kB/s del enlace binario

    print()
    print("-" * 64)
    print(f"  Firmware            : {cfg['firmware']}")
    print(f"  Ancho de banda      : {bw_mhz:.0f} MHz")
    print(f"  Resolucion          : {resol_m * 100:.1f} cm en aire")
    print(f"  Beat                : {hz_por_metro:.1f} Hz por metro")
    print(f"  fs efectiva         : {fs_eff:.1f} Hz")
    print(f"  Muestras por sweep  : {muestras_sweep:.1f}")
    if es_barrido(cfg):
        print(f"  Rampa               : {t_sweep * 1000:.3f} ms  "
              f"(PRF {t_sweep * 2000:.3f} ms)")
        print(f"  Escalon del DAC     : {paso_us:.1f} us")
        print(f"  Alcance no ambiguo  : {amb_m:.2f} m (lo fija el DAC)")
    print(f"  Alcance por Nyquist : {fs_eff / 2 / hz_por_metro:.2f} m")
    if cfg["modo"] == "rafaga" and not es_barrido(cfg):
        print(f"  Rafaga              : {raf_on} on / {raf_off} off "
              f"({util * 100:.0f}% util)")
    print(f"  Caudal binario      : {caudal:.1f} kB/s")
    print("-" * 64)

    if muestras_sweep < 32:
        if es_barrido(cfg):
            print("  [AVISO] Muy pocas muestras por sweep. Subí 'pasos' o 'nmue'.")
        else:
            print("  [AVISO] Muy pocas muestras por sweep. Bajá 'dec' o subí 'fs'.")
    # Medido en el banco: a 128 kB/s ya aparecen desbordes del ring, y a
    # 192 kB/s son constantes. A 64 kB/s quedan en el orden de 1e-4.
    if caudal > 100:
        print("  [AVISO] Caudal alto: el CDC del C3 desborda por encima de")
        print("          ~100 kB/s. Bajá 'fs' si aparecen perdidas.")
    if es_barrido(cfg):
        if paso_us < 150:
            print(f"  [AVISO] El escalon dura {paso_us:.0f} us y una escritura")
            print("          I2C tarda ~125 us: no hay margen. Subí 'nmue'.")
        # El firmware programa el escalon con un entero de microsegundos: si
        # la division no da exacta, el planificador deriva y ensucia 'jit'.
        if abs(paso_us - round(paso_us)) > 1e-6:
            print(f"  [AVISO] El escalon da {paso_us:.3f} us, no entero. El")
            print("          firmware lo trunca y la metrica de jitter miente.")
            print("          Elegí 'nmue' y 'fs' con nmue*1e6/fs entero.")
    return fs_eff, raf_on, raf_off, bw_mhz, hz_por_metro


def abrir_puerto(cfg):
    puerto = cfg["puerto"]
    if puerto == "auto":
        puerto = autodetectar_puerto()
        if not puerto:
            print("\n[ERROR] No encontre el ESP32 por VID. Opciones:")
            print("  - Revisá que este enchufado y que el Monitor Serie este CERRADO.")
            print("  - Poné el puerto a mano en la configuracion (ej. COM3).")
            sys.exit(1)
        print(f"\n  Puerto detectado: {puerto}")
    return serial.Serial(puerto, 115200, timeout=0.1)


def main():
    cfg = preguntar(cargar_config())
    guardar_config(cfg)
    fs_eff, raf_on, raf_off, bw_mhz, hz_por_metro = resumen(cfg)

    ser = abrir_puerto(cfg)
    time.sleep(0.3)

    print("\n  Configurando el firmware...")
    if es_barrido(cfg):
        predist = str(cfg["predist"]).strip().lower().startswith("s")
        info = configurar_barrido(ser, cfg["fs"], cfg["pasos"], cfg["nmue"],
                                  predist=predist, canal="l")
        if "Escalones/rampa" not in info:
            print("  [AVISO] El firmware no contesto 'info' como se esperaba.")
            print("          Verificá que tenga cargado gpr_barrido.")
        if "NO CONECTADO" in info:
            print("  [AVISO] El firmware no encuentra el MCP4725: la rampa va")
            print("          EN SECO y no sale tension al VCO. Vas a grabar")
            print("          ruido. Revisá el I2C antes de seguir.")
    else:
        info = configurar(ser, cfg["fs"], cfg["dec"], raf_on, raf_off, "l")
        if "fs (reloj ADC)" not in info:
            print("  [AVISO] El firmware no contesto 'info' como se esperaba.")
            print("          Verificá que tenga cargado PCM1808_ESP32C3.")

    os.makedirs(DATOS, exist_ok=True)
    inicio = datetime.now()
    ruta = os.path.join(DATOS, inicio.strftime("%Y-%m-%d_%H%M%S") + ".csv")

    with open(ruta, "w", encoding="utf-8", newline="") as f:
        # --- Encabezado: todo lo que hace falta para interpretar el archivo
        #     dentro de dos meses sin acordarse de nada.
        f.write(f"# fecha            = {inicio.isoformat(timespec='seconds')}\n")
        f.write(f"# firmware         = {cfg['firmware']}\n")
        f.write(f"# f_start_ghz      = {cfg['f_start_ghz']}\n")
        f.write(f"# f_stop_ghz       = {cfg['f_stop_ghz']}\n")
        f.write(f"# bw_mhz           = {bw_mhz:.1f}\n")
        f.write(f"# t_sweep_ms       = {cfg['t_sweep_ms']}\n")
        f.write(f"# hz_por_metro     = {hz_por_metro:.4f}\n")
        f.write(f"# fs               = {cfg['fs']}\n")
        f.write(f"# fs_eff           = {fs_eff:.4f}\n")
        if es_barrido(cfg):
            f.write(f"# pasos            = {cfg['pasos']}\n")
            f.write(f"# nmue             = {cfg['nmue']}\n")
            f.write(f"# predist          = {cfg['predist']}\n")
        else:
            f.write(f"# dec              = {cfg['dec']}\n")
            f.write(f"# modo             = {cfg['modo']}\n")
            f.write(f"# rafaga_on        = {raf_on}\n")
            f.write(f"# rafaga_off       = {raf_off}\n")
        f.write(f"# canales          = L\n")
        f.write(f"# unidad           = V\n")
        f.write(f"# nota             = {cfg['nota']}\n")
        f.write("#\n# --- volcado de 'info' del firmware ---\n")
        for linea in info.splitlines():
            if linea.strip():
                f.write("# " + linea.rstrip() + "\n")
        f.write("#\nidx,V\n")
        f.flush()

        dec_p = Decodificador()
        cont = Continuidad()
        ser.reset_input_buffer()
        if es_barrido(cfg):
            # Acá 'bin' solo cambia el formato: la adquisicion la larga 'run'.
            arrancar_barrido(ser)
        else:
            comando(ser, "bin", espera=0.05)

        print(f"\n  Grabando en: {os.path.basename(ruta)}")
        print("  Ctrl+C para terminar.\n")

        t0 = time.time()
        ultimo_flush = t0
        ultimo_aviso = t0
        muestras = 0

        try:
            while True:
                if cfg["duracion_s"] > 0 and time.time() - t0 >= cfg["duracion_s"]:
                    break

                datos = ser.read(max(1, ser.in_waiting))
                if datos:
                    for p in dec_p.alimentar(datos):
                        cont.revisar(p.idx, p.flags, len(p.datos))
                        # El indice se escribe explicito: en modo rafaga el
                        # numero de fila NO es el tiempo, y sin esta columna
                        # el eje temporal quedaria comprimido en silencio.
                        base = p.idx
                        f.write("".join(
                            f"{base + k},{v:.8f}\n" for k, v in enumerate(p.datos)))
                        muestras += len(p.datos)

                ahora = time.time()
                if ahora - ultimo_flush > 0.25:
                    f.flush()
                    os.fsync(f.fileno())
                    ultimo_flush = ahora

                if ahora - ultimo_aviso > 1.0:
                    seg = ahora - t0
                    estado = (f"\r  {seg:6.1f} s | {muestras:9d} muestras | "
                              f"{muestras / seg / 1000:6.2f} kS/s | "
                              f"CRC {dec_p.paquetes_crc} | perdidas {cont.perdidas}")
                    sys.stdout.write(estado + "   ")
                    sys.stdout.flush()
                    ultimo_aviso = ahora

        except KeyboardInterrupt:
            print("\n\n  Interrumpido.")

        f.flush()
        os.fsync(f.fileno())

    comando(ser, "stop" if es_barrido(cfg) else "off", espera=0.2)
    ser.close()

    seg = time.time() - t0
    print("\n" + "=" * 64)
    print(f"  Archivo    : {ruta}")
    print(f"  Duracion   : {seg:.2f} s")
    print(f"  Muestras   : {muestras}  ({muestras / seg / 1000:.2f} kS/s medio)")
    print(f"  Paquetes   : {dec_p.paquetes_ok} ok, {dec_p.paquetes_crc} con CRC malo")
    print(f"  Basura     : {dec_p.bytes_basura} bytes descartados")
    if cfg["modo"] == "rafaga" and not es_barrido(cfg):
        print(f"  Pausas     : {cont.pausas} muestras (esperado)")
    if cont.perdidas:
        print(f"  PERDIDAS   : {cont.perdidas} muestras en {cont.eventos} eventos")
        print("               El enlace no dio abasto. Subí 'dec' y repetí.")
    else:
        print("  Perdidas   : ninguna")
    print("=" * 64)


if __name__ == "__main__":
    main()
