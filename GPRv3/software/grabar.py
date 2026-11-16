"""
GPRv3 - Graba el crudo de la placa a un .gpr3, sin ventana
==========================================================

    python grabar.py [segundos] [--sps N] [--sintetico]

Deja datos/captura_<fecha>.gpr3, que despues se mira con analizar.py o se
reproduce con `vivo.py --archivo`.
"""

import argparse
import os
import time

import config as cfg
from fuentes import FuenteSerie, FuenteSintetica, Grabador
from modelo import Radar
from proceso import cargar_curva


def metadatos(fuente):
    """Lo que hace falta saber del banco para volver a procesar el crudo."""
    return {"fecha": time.strftime("%d-%m-%Y %H:%M:%S"),
            "fuente": fuente.nombre, "v_min": cfg.V_MIN, "v_max": cfg.V_MAX,
            "curva_vco": os.path.basename(cfg.VCO_CSV),
            "sync_alto_es_bajada": cfg.SYNC_ALTO_ES_BAJADA}


def main():
    ap = argparse.ArgumentParser(description="GPRv3 - grabar el crudo")
    ap.add_argument("segundos", nargs="?", type=float, default=10.0)
    ap.add_argument("--sps", type=int, default=cfg.SPS_DEF,
                    choices=cfg.SPS_OPCIONES)
    ap.add_argument("--sintetico", action="store_true")
    args = ap.parse_args()

    curva = cargar_curva()
    fuente = (FuenteSintetica(curva, sps=args.sps) if args.sintetico
              else FuenteSerie(args.sps))
    radar = Radar(curva)
    fuente.start()
    print(f"Fuente: {fuente.nombre}. Esperando a la placa...")
    t0 = time.monotonic()
    while fuente.info_carga is None:
        if time.monotonic() - t0 > 3.0:
            fuente.cerrar()
            raise SystemExit(
                "La placa no contesto. Tiene cargado adquisicion_sync?\n"
                f"Lo ultimo que llego: {bytes(fuente.dec.ultima_basura)!r}")
        time.sleep(0.05)

    fuente.grabador = Grabador(metadatos(fuente), fuente.info_carga)
    print(f"Grabando {args.segundos:.0f} s en {fuente.grabador.ruta}")
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < args.segundos and not fuente.error:
            time.sleep(1.0)
            radar.alimentar(fuente.tomar())
            r = radar.resumen()
            tprf = f"{r['tprf'] * 1e3:.2f} ms" if r and r["tprf"] else "SIN SYNC"
            print(f"  {time.monotonic() - t0:5.1f} s  {radar.muestras.total:9d} "
                  f"muestras  {radar.seg.validas:6d} rampas  Tprf {tprf}")
    except KeyboardInterrupt:
        print("  cortado")
    g = fuente.grabador
    fuente.cerrar()
    if fuente.error:
        print("  [!]", fuente.error)
    print(f"Listo: {g.total / 1e6:.2f} MB en {g.parte} archivo(s), "
          f"{fuente.dec.basura} bytes malos, "
          f"{len(radar.muestras.huecos)} huecos.")


if __name__ == "__main__":
    main()
