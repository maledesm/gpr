"""
GPRv2 - Corridas del zener de proteccion del VCO (D1)
=====================================================

Arma variantes del netlist de la placa (pcb/triangular/triangular_kicad.cir,
que genera simular_kicad.py desde el esquematico de KiCad) y las corre en
LTspice. Todo sale a zener/.

Se cambian dos cosas y nada mas:
  - el zener: 1N4729A (el que se usa), 1N4728A (el que se descarto) o ninguno;
  - R9: 100k (normal) o 1G (la falla: R9 abierta, que suelta el divisor de la
    entrada + del restador y manda la salida a 10 V).

Al zener se le pone una fuente de 0 V en serie para poder medir su corriente.

Ademas corre un barrido DC de los dos modelos de zener solos (zener/iv.cir):
es de donde sale el panel derecho de la figura del vertice.

Se simula una sola posicion del pote (la 0, la mas rapida) porque el nivel al
que clampea el zener no depende de la posicion, y a pote 1 el 1N4728A no
converge: el recorte le colapsa el paso de tiempo.

Uso
---
    py simular_zener.py

Tarda ~6 minutos: seis corridas de 0,9 s en paralelo, mas el barrido.
Despues: py graficar_zener.py
"""

import os
import re
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(AQUI, "pcb", "triangular", "triangular_kicad.cir")
DEST = os.path.join(AQUI, "zener")
LTSPICE = r"C:\Program Files\LTC\LTspice.exe"

T_SIM = 0.9          # s por corrida; los primeros ~0,3 s son el arranque
DESDE = 0.6 * T_SIM  # de aca en adelante se miden los niveles

# nombre        zener      R9 abierta
CORRIDAS = [("z_sin",  None,      False),
            ("z_4729", "1N4729A", False),
            ("z_4728", "1N4728A", False),
            ("f_sin",  None,      True),
            ("f_4729", "1N4729A", True),
            ("f_4728", "1N4728A", True)]

IV = """\
* Curva inversa de los dos zeners (modelos de Diodes Inc., zener_1N472xA.lib).
* Cada uno cuelga del mismo barrido con una fuente de 0 V en serie, para leer
* las dos corrientes por separado. En el simbolo de KiCad 1 = anodo, 2 = catodo.
XA 0 na DI_1N4728A
Va na n 0
XB 0 nb DI_1N4729A
Vb nb n 0
V1 n 0 0
.dc V1 2.4 4.2 0.002
.lib ../zener_1N472xA.lib
.end
"""


def variante(base, nombre, zener, r9_abierta):
    L = []
    for ln in base:
        if ln.startswith("XD1 "):
            if zener is None:
                continue                      # sin zener: se saca y listo
            L += [f"XD1 0 nz DI_{zener}", "Vz nz salida 0"]
            continue
        if ln.startswith("R9 "):
            pat = ln.rsplit(" ", 1)[0]
            L.append(f"{pat} {'1G' if r9_abierta else '100k'}")
            continue
        if ln.startswith(".step "):
            # una sola posicion: un .step de un solo valor da error
            L.append(".param pos=0")
            continue
        if ln.startswith(".tran "):
            L.append(f".tran 0 {T_SIM:g} 0 20u startup")
            continue
        if ln.startswith(".save "):
            L.append(".save V(salida) V(sync) V(sq) V(tri) V(mid)"
                     + (" I(Vz)" if zener else ""))
            continue
        if ln.startswith(".meas "):
            continue                          # las de abajo reemplazan a estas
        if ln.startswith(".lib "):
            L.append(".lib ../" + ln.split()[1].replace("../../", ""))
            continue
        if ln.startswith(".end"):
            L.append(f".meas tran vmax MAX V(salida) FROM {DESDE:g} TO {T_SIM:g}")
            L.append(f".meas tran vmin MIN V(salida) FROM {DESDE:g} TO {T_SIM:g}")
            if zener:
                L.append(f".meas tran izmin MIN I(Vz) FROM {DESDE:g} TO {T_SIM:g}")
            L.append(".end")
            continue
        L.append(ln)
    p = os.path.join(DEST, nombre + ".cir")
    open(p, "w", encoding="ascii", newline="\r\n").write("\n".join(L) + "\n")
    return p


def main():
    if not os.path.exists(LTSPICE):
        sys.exit(f"no encuentro LTspice en {LTSPICE}")
    if not os.path.exists(BASE):
        sys.exit(f"falta {BASE}: corre antes pcb/triangular/simular_kicad.py")
    os.makedirs(DEST, exist_ok=True)

    base = open(BASE, encoding="ascii").read().splitlines()
    cir = [variante(base, *c) for c in CORRIDAS]

    p_iv = os.path.join(DEST, "iv.cir")
    open(p_iv, "w", encoding="ascii", newline="\r\n").write(IV)
    cir.append(p_iv)

    # en paralelo: son seis corridas de ~1 minuto cada una
    procs = [subprocess.Popen([LTSPICE, "-b", p], cwd=DEST,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for p in cir]
    for p in procs:
        p.wait()

    print("resultados (Vsalida, y la corriente del zener donde lo hay):")
    for nombre, zener, falla in CORRIDAS:
        log = os.path.join(DEST, nombre + ".log")
        if not os.path.exists(log):
            print(f"  {nombre:7s} NO CORRIO")
            continue
        txt = open(log, encoding="latin-1").read()
        val = dict(re.findall(r"^(vmax|vmin|izmin): \S+=([-\d.e+]+)", txt, re.M))
        que = f"{'R9 abierta' if falla else 'normal':11s} {zener or 'sin zener':9s}"
        linea = f"  {nombre:7s} {que}  {float(val['vmin']):7.4f} a {float(val['vmax']):7.4f} V"
        if "izmin" in val:
            linea += f"   Iz = {abs(float(val['izmin']))*1e3:6.3f} mA"
        print(linea)
    print(f"\nlisto: {DEST}\nahora: py graficar_zener.py")


if __name__ == "__main__":
    main()
