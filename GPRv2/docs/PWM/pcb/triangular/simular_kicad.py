"""
GPRv2 - Simular el esquematico de KiCad en LTspice
==================================================

Exporta el netlist de triangular.kicad_sch con kicad-cli y lo pasa a
triangular_kicad.cir, un netlist de LTspice con el modelo del TLC2272
(../../TLC2272.lib; el TLC2274 es el mismo operacional en cuadruple).

Los nodos y los valores salen del esquematico tal cual. Lo unico que se
agrega es lo que no esta en la placa:
  - la fuente de 12 V en J2;
  - el pote entre J1.1 (extremo) y J1.2 (cursor), barrido con .step;
  - .tran con startup y method=gear, sin los cuales el modelo no converge.

Los operacionales que sobran (hoy U1D, U2C y U2D) se dejan afuera: no cambian
nada (verificado: mismos periodos y niveles) y hacen la simulacion unas 8
veces mas lenta. Se detectan solos: son las unidades cuya salida solo va a su
propia entrada inversora. D1 (el zener de proteccion del VCO) entra con el modelo de Diodes
Inc. de ../../zener_1N472xA.lib, que se elige por el valor del simbolo
(1N4729A -> DI_1N4729A).

Uso
---
    py simular_kicad.py

Despues: abrir triangular_kicad.cir en el LTspice 24 (File > Open, tipo
"Netlists"), correrlo y graficar V(salida), V(sync) y V(sq). Ctrl+L muestra
el periodo y los niveles de cada posicion del pote. Tarda ~1 minuto.
"""

import os
import re
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SCH = os.path.join(AQUI, "triangular.kicad_sch")
NET = os.path.join(AQUI, "triangular_kicad.net")
CIR = os.path.join(AQUI, "triangular_kicad.cir")
KICAD_CLI = r"D:\Program Files\KiCAD\bin\kicad-cli.exe"

POSICIONES = "0 0.5 1"          # posiciones del pote que barre el .step
T_SIM = 1.5                     # segundos simulados por posicion


def exportar():
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", NET, SCH], check=True, capture_output=True)


def leer():
    """(componentes {ref: valor}, patas {(ref, pin): nodo}) del netlist."""
    txt = " ".join(open(NET, encoding="utf-8").read().split())
    comps = dict(re.findall(r'\(comp \(ref "([^"]+)"\) \(value "([^"]*)"\)', txt))
    patas, nombres = {}, {}
    for bloque in txt[txt.index("(nets"):].split("(net (code")[1:]:
        nombre = re.search(r'\(name "([^"]*)"\)', bloque).group(1)
        # "Net-(U1D-+)" y "Net-(U1D--)" se limpian igual: el + y el - se
        # escriben con letras, y si aun asi chocan se numeran
        limpio = re.sub(r"[^A-Za-z0-9_]", "_",
                        nombre.strip("/").replace("+", "mas").replace("-)", "menos)"))
        if nombre != "GND" and nombre not in nombres:
            nombres[nombre] = limpio if limpio not in nombres.values() else f"{limpio}_{len(nombres)}"
        nodo = "0" if nombre == "GND" else nombres[nombre]
        for ref, pin in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', bloque):
            patas[(ref, pin)] = nodo
    return comps, patas


def valor(v):
    """'8k2' -> '8.2k', '10u 25V' -> '10u'."""
    v = v.split()[0]
    m = re.fullmatch(r"(\d+)([kMmunp])(\d+)", v)
    return f"{m.group(1)}.{m.group(3)}{m.group(2)}" if m else v


def escribir(comps, patas):
    L = ["* GPRv2 - generado por simular_kicad.py desde triangular.kicad_sch. No editar a mano."]
    for ref, v in sorted(comps.items()):
        # solo R1, C1...: RV1 es el pote de prueba en paralelo con J1, y el pote
        # se simula una sola vez, con Rpote
        if re.fullmatch(r"[RC]\d+", ref):
            L.append(f"{ref} {patas[(ref, '1')]} {patas[(ref, '2')]} {valor(v)}")
    unidades = {"A": ("3", "2", "1"), "B": ("5", "6", "7"), "C": ("10", "9", "8"), "D": ("12", "13", "14")}
    for ref in sorted(r for r in comps if r.startswith("U")):
        vcc, vee = patas[(ref, "4")], patas[(ref, "11")]
        for u, (mas, menos, sal) in unidades.items():
            en_salida = [p for p, nodo in patas.items() if nodo == patas[(ref, sal)]]
            if sorted(en_salida) == sorted([(ref, sal), (ref, menos)]):
                continue                    # sobra: seguidor que no maneja nada
            L.append(f"X{ref}{u} {patas[(ref, mas)]} {patas[(ref, menos)]} {vcc} {vee} "
                     f"{patas[(ref, sal)]} TLC2272")
    # zener: en KiCad la pata 1 es el catodo y la 2 el anodo; el modelo va anodo, catodo
    zeners = sorted(r for r in comps if r.startswith("D"))
    for ref in zeners:
        L.append(f"X{ref} {patas[(ref, '2')]} {patas[(ref, '1')]} DI_{comps[ref]}")
    L.append(f"V12 {patas[('J2', '1')]} {patas[('J2', '2')]} 12")
    L.append(f"Rpote {patas[('J1', '1')]} {patas[('J1', '2')]} {{max(Rpot*pos,1m)}}")

    # por el nombre de la etiqueta del esquematico, no por la pata del operacional
    sal, syn, sq, tri, mid = "salida", "sync", "sq", "tri", "mid"
    faltan = [n for n in (sal, syn, sq, tri, mid) if n not in patas.values()]
    if faltan:
        sys.exit(f"no encuentro las etiquetas {faltan} en el esquematico")
    desde = f"{T_SIM * 0.6:g}"
    L += [".param Rpot=100k",
          f".step param pos list {POSICIONES}",
          f".tran 0 {T_SIM:g} 0 20u startup",
          ".options method=gear",
          f".save V({sal}) V({syn}) V({sq}) V({tri}) V({mid})",
          f".meas tran t1 WHEN V({sq})=6 RISE=3",
          f".meas tran t2 WHEN V({sq})=6 RISE=4",
          ".meas tran periodo PARAM t2-t1",
          ".meas tran frec PARAM 1/periodo",
          f".meas tran salmin MIN V({sal}) FROM {desde} TO {T_SIM:g}",
          f".meas tran salmax MAX V({sal}) FROM {desde} TO {T_SIM:g}",
          f".meas tran symin MIN V({syn}) FROM {desde} TO {T_SIM:g}",
          f".meas tran symax MAX V({syn}) FROM {desde} TO {T_SIM:g}",
          ".lib ../../TLC2272.lib"]
    if zeners:
        L.append(".lib ../../zener_1N472xA.lib")
    L.append(".end")
    open(CIR, "w", encoding="ascii", newline="\r\n").write("\n".join(L) + "\n")


def main():
    if not os.path.exists(KICAD_CLI):
        sys.exit(f"no encuentro kicad-cli en {KICAD_CLI}")
    exportar()
    comps, patas = leer()
    escribir(comps, patas)
    os.remove(NET)
    print("listo: triangular_kicad.cir")
    print("abrilo en el LTspice 24 y grafica V(salida), V(sync) y V(sq)")


if __name__ == "__main__":
    main()
