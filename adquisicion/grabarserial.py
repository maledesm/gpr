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

from protocolo import (Continuidad, Decodificador, autodetectar_puerto,
                       comando, configurar)

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config.json")
DATOS = os.path.normpath(os.path.join(AQUI, "..", "datos"))

POR_DEFECTO = {
    "puerto":            "auto",
    "f_start_ghz":       1.00,
    "f_stop_ghz":        1.75,
    "t_sweep_ms":        10.0,
    "fs":                32000,
    "dec":               4,
    "modo":              "continuo",   # continuo | rafaga
    "rafaga_on_sweeps":  3,
    "rafaga_off_sweeps": 1,
    "duracion_s":        30.0,         # 0 = hasta Ctrl+C
    "nota":              "",
}

CAMPOS = [
    ("puerto",            "Puerto serie ('auto' para detectar)",       str),
    ("f_start_ghz",       "Frecuencia inicial del sweep [GHz]",        float),
    ("f_stop_ghz",        "Frecuencia final del sweep [GHz]",          float),
    ("t_sweep_ms",        "Duracion del sweep [ms]",                   float),
    ("fs",                "Frecuencia de muestreo del ADC [Hz]",       int),
    ("dec",               "Diezmado en el firmware",                   int),
    ("modo",              "Modo de captura (continuo/rafaga)",         str),
    ("rafaga_on_sweeps",  "  Sweeps a capturar por rafaga",            int),
    ("rafaga_off_sweeps", "  Sweeps de pausa entre rafagas",           int),
    ("duracion_s",        "Duracion de la grabacion [s] (0 = Ctrl+C)", float),
    ("nota",              "Nota descriptiva de la medicion",           str),
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
    print("=" * 64)
    print(" Configuracion de la medicion")
    print(" Enter deja el valor entre corchetes; escribi para cambiarlo.")
    print("=" * 64)

    for clave, texto, tipo in CAMPOS:
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

    if cfg["modo"] not in ("continuo", "rafaga"):
        print(f"    [aviso] modo '{cfg['modo']}' desconocido; uso continuo.")
        cfg["modo"] = "continuo"
    return cfg


def resumen(cfg):
    """Calcula los numeros derivados y avisa si algo no cierra."""
    fs_eff = cfg["fs"] / cfg["dec"]
    bw_mhz = (cfg["f_stop_ghz"] - cfg["f_start_ghz"]) * 1000.0
    t_sweep = cfg["t_sweep_ms"] / 1000.0
    hz_por_metro = 2.0 * (bw_mhz * 1e6) / (3e8 * t_sweep)
    muestras_sweep = fs_eff * t_sweep

    if cfg["modo"] == "rafaga":
        raf_on = int(round(cfg["rafaga_on_sweeps"] * muestras_sweep))
        raf_off = int(round(cfg["rafaga_off_sweeps"] * muestras_sweep))
        util = raf_on / (raf_on + raf_off)
    else:
        raf_on = raf_off = 0
        util = 1.0

    caudal = fs_eff * 4 * util / 1000.0          # kB/s del enlace binario

    print()
    print("-" * 64)
    print(f"  Ancho de banda      : {bw_mhz:.0f} MHz")
    print(f"  Resolucion          : {3e8 / (2 * bw_mhz * 1e6) * 100:.1f} cm")
    print(f"  Beat                : {hz_por_metro:.1f} Hz por metro")
    print(f"  fs efectiva         : {fs_eff:.1f} Hz")
    print(f"  Muestras por sweep  : {muestras_sweep:.1f}")
    print(f"  Alcance maximo      : {fs_eff / 2 / hz_por_metro:.2f} m (Nyquist)")
    if cfg["modo"] == "rafaga":
        print(f"  Rafaga              : {raf_on} on / {raf_off} off "
              f"({util * 100:.0f}% util)")
    else:
        print(f"  Captura             : continua")
    print(f"  Caudal binario      : {caudal:.1f} kB/s")
    print("-" * 64)

    if muestras_sweep < 32:
        print("  [AVISO] Muy pocas muestras por sweep. Bajá 'dec' o subí 'fs'.")
    if caudal > 200:
        print("  [AVISO] Caudal alto: puede haber perdidas. Subí 'dec' si aparecen.")
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
    info = configurar(ser, cfg["fs"], cfg["dec"], raf_on, raf_off, "l")
    if "fs (reloj ADC)" not in info:
        print("  [AVISO] El firmware no contesto 'info' como se esperaba.")
        print("          Verificá que tenga cargado PCM1808_ESP32C3_bin.")

    os.makedirs(DATOS, exist_ok=True)
    inicio = datetime.now()
    ruta = os.path.join(DATOS, inicio.strftime("%Y-%m-%d_%H%M%S") + ".csv")

    with open(ruta, "w", encoding="utf-8", newline="") as f:
        # --- Encabezado: todo lo que hace falta para interpretar el archivo
        #     dentro de dos meses sin acordarse de nada.
        f.write(f"# fecha            = {inicio.isoformat(timespec='seconds')}\n")
        f.write(f"# firmware         = PCM1808_ESP32C3_bin\n")
        f.write(f"# f_start_ghz      = {cfg['f_start_ghz']}\n")
        f.write(f"# f_stop_ghz       = {cfg['f_stop_ghz']}\n")
        f.write(f"# bw_mhz           = {bw_mhz:.1f}\n")
        f.write(f"# t_sweep_ms       = {cfg['t_sweep_ms']}\n")
        f.write(f"# hz_por_metro     = {hz_por_metro:.4f}\n")
        f.write(f"# fs               = {cfg['fs']}\n")
        f.write(f"# dec              = {cfg['dec']}\n")
        f.write(f"# fs_eff           = {fs_eff:.4f}\n")
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
                    for idx, flags, valores in dec_p.alimentar(datos):
                        cont.revisar(idx, flags, len(valores))
                        # El indice se escribe explicito: en modo rafaga el
                        # numero de fila NO es el tiempo, y sin esta columna
                        # el eje temporal quedaria comprimido en silencio.
                        base = idx
                        f.write("".join(
                            f"{base + k},{v:.8f}\n" for k, v in enumerate(valores)))
                        muestras += len(valores)

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

    comando(ser, "off", espera=0.2)
    ser.close()

    seg = time.time() - t0
    print("\n" + "=" * 64)
    print(f"  Archivo    : {ruta}")
    print(f"  Duracion   : {seg:.2f} s")
    print(f"  Muestras   : {muestras}  ({muestras / seg / 1000:.2f} kS/s medio)")
    print(f"  Paquetes   : {dec_p.paquetes_ok} ok, {dec_p.paquetes_crc} con CRC malo")
    print(f"  Basura     : {dec_p.bytes_basura} bytes descartados")
    if cfg["modo"] == "rafaga":
        print(f"  Pausas     : {cont.pausas} muestras (esperado)")
    if cont.perdidas:
        print(f"  PERDIDAS   : {cont.perdidas} muestras en {cont.eventos} eventos")
        print("               El enlace no dio abasto. Subí 'dec' y repetí.")
    else:
        print("  Perdidas   : ninguna")
    print("=" * 64)


if __name__ == "__main__":
    main()
