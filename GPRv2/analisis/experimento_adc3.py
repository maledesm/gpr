"""
GPRv2 - Experimento: la triangular sale con dos lineas. Tres lecturas del ADC
por iteracion, para saber DONDE se sortea el estado.
===========================================================================

Contexto en GPRv2/CLAUDE.md ("La triangular sale con dos lineas"). Resumen:
la lectura de GPIO3 cae al azar en uno de dos estados separados ~390 cuentas
(~0,24 V en el pin), y NO es un corrimiento temporal. Falta saber si el
estado cambia entre CONVERSIONES o entre ITERACIONES del lazo del firmware.

El firmware (con el experimento puesto) lee el ADC tres veces pegadas al
principio de cada iteracion y emite, ademas de la linea "#v,..." de siempre:

    #v3,<a1>,<a2>,<a3>,<us desde la lectura de la iteracion anterior>

Lo que este script mira:

  1. DENTRO de la iteracion: si a1, a2 y a3 coinciden (dentro del ruido del
     ADC) o si saltan ~390 cuentas entre si. Si saltan entre conversiones
     separadas por microsegundos, es el ADC o su driver, y el momento del
     lazo no tiene nada que ver.
  2. ENTRE iteraciones: si las tres coinciden pero el promedio de las tres
     sigue bimodal, el estado se sortea por iteracion, o sea por lo que el
     micro esta haciendo en ese momento (USB, DMA).
  3. El tiempo entre iteraciones: 5333 us nominales. Si el estado va con
     iteraciones mas cortas o mas largas de lo normal, apunta al USB.

Uso
---
    python experimento_adc3.py             graba DURACION_S y analiza
    python experimento_adc3.py <archivo>   analiza un stream ya grabado

El stream crudo queda entero en datos/experimento_adc3_<sello>.txt (esta en
.gitignore), asi que se puede volver a analizar.
"""

import os
import sys
import time
from math import erf

import numpy as np
import serial
from serial.tools import list_ports

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(AQUI, "..", "datos")
# correccion_no_linealidad.py usa rutas relativas al directorio actual. El
# directorio original se guarda para resolver el archivo que venga por argv.
CWD0 = os.getcwd()
sys.path.insert(0, AQUI)
os.chdir(AQUI)
from correccion_no_linealidad import buscar_periodo          # noqa: E402
from proceso_rapido import ajustar_triangular_rapido          # noqa: E402

PUERTO = "auto"
BAUD = 115200
VID_ESPRESSIF = 0x303A
FS = 6000.0
DURACION_S = 60.0
FORMATO_SELLO = "%d-%m-%Y_%H-%M-%S"

# Dos lecturas separadas por menos de esto se consideran la misma (ruido del
# ADC); separadas por mas de SALTO, un cambio de estado. La separacion medida
# entre los dos estados fue ~390 cuentas, y el ruido dentro de cada uno ~120.
RUIDO_ADC = 60
SALTO = 250


def abrir_puerto():
    puerto = PUERTO
    if puerto == "auto":
        cand = [p for p in list_ports.comports() if p.vid == VID_ESPRESSIF]
        if len(cand) != 1:
            for p in cand:
                print("   ", p.device, "-", p.description)
            raise SystemExit(
                "No encontre exactamente un ESP32 (esta enchufado? el Monitor "
                "Serie del IDE tiene que estar cerrado). Si no, pone el puerto "
                "a mano en PUERTO.")
        puerto = cand[0].device
        print(f"Puerto detectado: {puerto}")
    # Sin tocar DTR/RTS: en el USB nativo del C3 esa combinacion es la de
    # reset (ver GPRv2/CLAUDE.md).
    ser = serial.Serial()
    ser.port = puerto
    ser.baudrate = BAUD
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    ser.open()
    time.sleep(0.5)
    ser.reset_input_buffer()
    return ser


def grabar(path):
    ser = abrir_puerto()
    ser.write(b"run\n")
    print(f"Grabando {DURACION_S:.0f} s de stream crudo en {path}")
    t0 = time.time()
    n = 0
    with open(path, "wb") as f:
        while time.time() - t0 < DURACION_S:
            datos = ser.read(max(1, ser.in_waiting))
            if datos:
                f.write(datos)
                n += len(datos)
    ser.write(b"stop\n")
    ser.close()
    print(f"  {n/1e6:.1f} MB, {n/DURACION_S/1e3:.0f} kB/s")


def leer(path):
    """(indice de muestra, a1, a2, a3, dt_us) por iteracion."""
    filas = []
    indice = -1
    with open(path, "rb") as f:
        for cruda in f:
            linea = cruda.decode("ascii", "ignore").strip()
            if linea.startswith("#v,"):
                try:
                    indice = int(linea.split(",")[2])
                except (IndexError, ValueError):
                    pass
            elif linea.startswith("#v3,"):
                try:
                    a1, a2, a3, dt = (int(x) for x in linea[4:].split(","))
                except ValueError:
                    continue
                filas.append((indice, a1, a2, a3, dt))
    if not filas:
        raise SystemExit(
            "No llego ninguna linea '#v3,...': la placa tiene el firmware sin "
            "el experimento. Reflashea firmware/adquisicion/adquisicion.ino.")
    d = np.array(filas, dtype=float)
    return d[:, 0], d[:, 1], d[:, 2], d[:, 3], d[:, 4]


def separacion(r):
    """Distancia entre los dos grupos del residuo, partidos por la mediana."""
    alto = r > np.median(r)
    return float(r[alto].mean() - r[~alto].mean())


def analizar(path):
    idx, a1, a2, a3, dt = leer(path)
    n = len(idx)
    print(f"\n{path}\n  {n} iteraciones = {n * 32 / FS:.1f} s")

    # El triangulo se ajusta sobre a1, que es la lectura que usan vivo.py y
    # vivo_rapido.py. Las tres estan a microsegundos, comparten la fase.
    T_ini = buscar_periodo(list(idx), list(a1), FS)
    if T_ini is None:
        raise SystemExit("no pude encontrar el periodo de la triangular")
    T, t0 = ajustar_triangular_rapido(list(idx), list(a1), FS, T_ini, 0.10)
    fase = ((idx / FS - t0) % T) / T
    forma = 1 - np.abs(2 * fase - 1)
    (v0, amp), *_ = np.linalg.lstsq(np.c_[np.ones_like(forma), forma], a1,
                                    rcond=None)
    pend = 2 * amp / T / 1e3          # cuentas por ms
    print(f"  triangular: T = {T*1e3:.3f} ms, {v0:.0f} a {v0+amp:.0f} cuentas, "
          f"{pend:.1f} cuentas/ms")
    # Lejos de los vertices y del riel de 0, donde la separacion es limpia.
    rampa = ((np.abs(fase - 0.25) < 0.15) | (np.abs(fase - 0.75) < 0.15))
    modelo = v0 + amp * forma
    r1, r2, r3 = a1 - modelo, a2 - modelo, a3 - modelo
    rm = (r1 + r2 + r3) / 3

    print("\n--- 1. DENTRO de la iteracion (tres conversiones a microsegundos) ---")
    for nombre, d in (("a2 - a1", a2 - a1), ("a3 - a2", a3 - a2),
                      ("a3 - a1", a3 - a1)):
        d = d[rampa]
        print(f"  {nombre}: mediana |d| {np.median(np.abs(d)):4.0f}, p90 "
              f"{np.percentile(np.abs(d), 90):4.0f} cuentas;  iguales "
              f"(<{RUIDO_ADC}) {100*(np.abs(d) < RUIDO_ADC).mean():4.1f} %,  "
              f"salto (>{SALTO}) {100*(np.abs(d) > SALTO).mean():4.1f} %")
    d13 = (a3 - a1)[rampa]
    frac_salto = float((np.abs(d13) > SALTO).mean())
    print("  histograma de a3 - a1 en la rampa:")
    h, b = np.histogram(d13, bins=np.arange(-600, 601, 50))
    for hh, bb in zip(h, b):
        if hh:
            print(f"    {bb:+5.0f}: {'#' * (hh * 50 // max(h.max(), 1))} {hh}")

    print("\n--- 2. ENTRE iteraciones ---")
    for nombre, r in (("a1 sola", r1), ("a2 sola", r2), ("a3 sola", r3),
                      ("promedio de las tres", rm)):
        rr = r[rampa]
        print(f"  {nombre:22s}: separacion entre grupos {separacion(rr):4.0f} "
              f"cuentas, std total {rr.std():4.0f}")
    sep_m = separacion(rm[rampa])
    s = (rm[rampa] > 0).astype(int)
    if len(s) > 2:
        p11 = s[1:][s[:-1] == 1].mean() if (s[:-1] == 1).any() else np.nan
        p01 = s[1:][s[:-1] == 0].mean() if (s[:-1] == 0).any() else np.nan
        print(f"  fraccion 'alta' {s.mean():.2f};  P(alta|anterior alta) "
              f"{p11:.2f}, P(alta|anterior baja) {p01:.2f}")

    print("\n--- 3. tiempo entre iteraciones (5333 us nominales) ---")
    dtv = dt[1:]                      # la primera trae 0
    print(f"  mediana {np.median(dtv):.0f} us, p5 {np.percentile(dtv, 5):.0f}, "
          f"p95 {np.percentile(dtv, 95):.0f}, min {dtv.min():.0f}, "
          f"max {dtv.max():.0f}")
    h, b = np.histogram(dtv, bins=np.arange(0, 12001, 500))
    for hh, bb in zip(h, b):
        if hh:
            print(f"    {bb:5.0f}..{bb+500:5.0f} us: "
                  f"{'#' * (hh * 50 // max(h.max(), 1))} {hh}")
    alto = rm > 0
    m = rampa.copy(); m[0] = False
    # dt de ESTA iteracion (cuanto tardo en llegar hasta esta lectura) y de la
    # SIGUIENTE (cuanto tardo lo que vino despues de leer: imprimir el bloque).
    dt_sig = np.r_[dt[1:], np.nan]
    for nombre, x in (("dt hasta esta lectura", dt),
                      ("dt de la iteracion siguiente", dt_sig)):
        ok = m & np.isfinite(x)
        print(f"  {nombre:30s}: estado alto {x[ok & alto].mean():6.0f} us, "
              f"estado bajo {x[ok & ~alto].mean():6.0f} us;  "
              f"corr con el residuo {np.corrcoef(x[ok], rm[ok])[0, 1]:+.2f}")

    # El estadistico que decide, y no depende del ruido: la separacion entre
    # grupos del PROMEDIO de las tres contra la de una lectura sola. Si el
    # estado se sortea por iteracion, las tres traen el mismo offset y
    # promediar no lo achica (cociente ~1). Si se sortea por conversion, el
    # promedio de tres offsets independientes de +-195 se comprime (cociente
    # ~0,55). Probado sobre streams sinteticos: 0,98 contra 0,55.
    sep_1 = float(np.mean([separacion(r[rampa]) for r in (r1, r2, r3)]))
    cociente = sep_m / sep_1 if sep_1 > 0 else 1.0
    # De apoyo: cuantos saltos a3-a1 explica el ruido de UNA conversion. El
    # ruido se mide sobre a1 dentro de cada estado (partido por el promedio,
    # que es el que mejor separa los estados).
    alto_r = rm[rampa] > np.median(rm[rampa])
    rr1 = r1[rampa]
    ruido = float(np.mean([rr1[alto_r].std(), rr1[~alto_r].std()]))
    esperado = 2 * (1 - 0.5 * (1 + erf(SALTO / (ruido * np.sqrt(2)) / np.sqrt(2))))
    print(f"\n  separacion del promedio / de una lectura sola: {cociente:.2f} "
          f"(~1 = mismo estado en las tres, ~0,55 = estado por conversion)")
    print(f"  saltos a3-a1 > {SALTO}: observados {100*frac_salto:.1f} %, "
          f"esperados con el mismo estado en las tres y {ruido:.0f} cuentas "
          f"de ruido por conversion: {100*esperado:.1f} %")

    print("\n--- veredicto ---")
    if sep_m < SALTO * 0.6 and sep_1 < SALTO * 0.6:
        print("  En esta captura NO se ve la bimodalidad (separacion chica). "
              "Si el cuadro de la triangular la mostraba, revisar que el "
              "stream sea de la misma placa y el mismo cableado.")
    elif cociente < 0.8:
        print(f"  El estado cambia DENTRO de la iteracion: promediar las tres "
              f"conversiones, separadas por microsegundos, achica la "
              f"separacion a {cociente:.2f} de la de una sola, y a3 - a1 salta "
              f"mas de {SALTO} cuentas en el {100*frac_salto:.0f} % de las "
              f"iteraciones. Es el ADC o su driver, no el momento del lazo "
              f"(USB, DMA).")
    else:
        print(f"  Las tres conversiones coinciden (solo el "
              f"{100*frac_salto:.0f} % salta) y el promedio sigue bimodal "
              f"({sep_m:.0f} cuentas): el estado se sortea POR ITERACION, o "
              f"sea por lo que el micro esta haciendo en el momento de leer.")
        ok = m & np.isfinite(dt_sig)
        dif = abs(dt[m & alto].mean() - dt[m & ~alto].mean())
        if dif > 300:
            print(f"  Y va con el tiempo de iteracion (difiere {dif:.0f} us "
                  f"entre estados): apunta al USB / al atraso del lazo.")
        else:
            print("  El tiempo de iteracion es el mismo en los dos estados: "
                  "no es el atraso del lazo. Queda lo que este activo en ese "
                  "instante (USB vaciando la cola, DMA) o la alimentacion.")


def main():
    if len(sys.argv) > 1:
        path = os.path.join(CWD0, sys.argv[1])
    else:
        os.makedirs(DATOS, exist_ok=True)
        sello = time.strftime(FORMATO_SELLO)
        path = os.path.join(DATOS, f"experimento_adc3_{sello}.txt")
        grabar(path)
    analizar(path)


if __name__ == "__main__":
    main()
