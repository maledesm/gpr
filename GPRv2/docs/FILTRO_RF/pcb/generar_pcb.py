"""
Genera la placa de prueba con los tres pasabajos de RF (A, B del libro y B recortado x0,935).

La geometria sale de ../diseno_hong.json con la MISMA funcion que uso openEMS
(openems/simular_filtro.py, geometria()), asi el cobre es exactamente lo simulado.

  - FR4 1,6 mm, cobre 72 um, dos capas: pistas arriba, plano de masa entero abajo
  - 56 x 75 mm, los tres filtros centrados, uno debajo del otro
  - linea de 50 ohm de cada filtro hasta el canto, SMA de borde Amphenol 132289 en cada punta
  - arriba no hay cobre de masa cerca de los filtros (como en la simulacion), solo los pads
    de masa de los SMA, unidos al plano de abajo con vias

Uso (con el Python de KiCad, no con el del venv):
  "D:/Program Files/KiCAD/bin/python.exe" generar_pcb.py
"""
import os, sys, json, math

import pcbnew

AQUI = os.path.dirname(os.path.abspath(__file__))
FILTRO = os.path.join(AQUI, "..")
SALIDA = os.path.join(AQUI, "filtros_rf.kicad_pcb")
LIB_SMA = r"D:\Program Files\KiCAD\share\kicad\footprints\Connector_Coaxial.pretty"
FP_SMA = "SMA_Amphenol_132289_EdgeMount"     # SMA de borde para placa de 0,062" (1,6 mm)
# el SMA que se va a usar tiene 4 patas de masa en las esquinas del cuadrado: las dos de abajo
# apoyan en la cara de abajo y las dos de arriba quedan en el aire. Se arma un footprint propio,
# igual al de Amphenol pero sin los pads de masa de arriba, en una biblioteca local del proyecto.
LIB_LOCAL = os.path.join(AQUI, "filtros_rf.pretty")
FP_LOCAL = "SMA_Borde_GND_Abajo"

W, H = 56.0, 75.0                     # mm
LIB_HUECO = r"D:\Program Files\KiCAD\share\kicad\footprints\MountingHole.pretty"
FP_HUECO = "MountingHole_3.2mm_M3"    # agujero sin metalizar de 3,2 mm, para tornillo M3
D_HUECO = 4.0                         # centro del agujero a 4 mm de cada borde
ESQUINA = 8.0                         # cuadrado sin cobre (ninguna cara) en cada esquina
ORIGEN = (100.0, 50.0)                # esquina superior izquierda en la hoja
T_CU = 0.072                          # mm
FILAS = [                             # (diseno, recorte, y de la linea [mm desde arriba], net, rotulo)
    ("A_n5", 1.0, 16.0, "FILTRO_A", "A  n=5"),
    ("B_n7", 1.0, 38.0, "FILTRO_B", "B  n=7 (libro)"),
    ("B_n7", 0.935, 60.0, "FILTRO_B_REC", "B  n=7 rec. x0,935"),
]
MM = pcbnew.FromMM


def P(x, y):
    """mm de placa (x a la derecha, y hacia abajo desde la esquina) -> coordenadas de KiCad"""
    return pcbnew.VECTOR2I(MM(ORIGEN[0] + x), MM(ORIGEN[1] + y))


def geometria(r, recorte):
    """copia de openems/simular_filtro.py:geometria() (sin importar openEMS, que no esta en este Python)"""
    LADOS = {"A_n5": [1, 1], "B_n7": [1, -1, 1]}
    li = r["lineas"]
    wL, wC, w0 = li["W_L_mm"], li["W_C_mm"], li["W_0_mm"]
    rects, x, js = [], 0.0, []
    for i, l in enumerate(r["l_serie_mm"]):
        rects.append([x, x + l, -wL / 2, wL / 2])
        x += l
        if i < len(r["stubs"]):
            js.append(x)
    largo = x
    for xj, s, sg in zip(js, r["stubs"], LADOS[r["nombre"]]):
        lt, lp = s["lL_corregido_mm"] * recorte, s["lC_final_mm"] * recorte
        y1, y2, y3 = wL / 2, wL / 2 + lt, wL / 2 + lt + lp
        rects.append([xj - wL / 2, xj + wL / 2] + sorted([sg * y1, sg * y2]))
        rects.append([xj - wC / 2, xj + wC / 2] + sorted([sg * y2, sg * y3]))
    return rects, largo, w0


def poligono(rects):
    """union de rectangulos [x0, x1, y0, y1] (mm de placa) en un solo poligono"""
    total = pcbnew.SHAPE_POLY_SET()
    for x0, x1, y0, y1 in rects:
        p = pcbnew.SHAPE_POLY_SET()
        p.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            p.Append(P(x, y))
        total.BooleanAdd(p)
    total.Simplify()
    return total


def red(board, nombre):
    n = pcbnew.NETINFO_ITEM(board, nombre)
    board.Add(n)
    return n


def texto(board, s, x, y, alto=1.2, capa=pcbnew.F_SilkS):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(P(x, y))
    t.SetLayer(capa)
    t.SetTextSize(pcbnew.VECTOR2I(MM(alto), MM(alto)))
    t.SetTextThickness(MM(alto * 0.15))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    if capa == pcbnew.B_SilkS:
        t.SetMirrored(True)
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    board.Add(t)


def escribir_stackup(ruta):
    """stackup real (FR4 1,6 mm, cobre 72 um en las dos caras), escrito en el archivo porque la
    API de Python de KiCad no expone el stackup. Solo documenta: no cambia el cobre dibujado."""
    # sin mascara ni serigrafia: el fabricante solo trabaja el cobre
    nucleo = 1.6 - 2 * T_CU
    st = ('\t\t(stackup\n'
          f'\t\t\t(layer "F.Cu" (type "copper") (thickness {T_CU}))\n'
          f'\t\t\t(layer "dielectric 1" (type "core") (thickness {nucleo:.3f}) (material "FR4") '
          '(epsilon_r 4.4) (loss_tangent 0.025))\n'
          f'\t\t\t(layer "B.Cu" (type "copper") (thickness {T_CU}))\n'
          '\t\t\t(copper_finish "None")\n'
          '\t\t\t(dielectric_constraints no)\n'
          '\t\t)\n')
    txt = open(ruta, encoding="utf-8").read()
    if "(stackup" not in txt:
        i = txt.index("(setup") + len("(setup")
        txt = txt[:i] + "\n" + st + txt[i:].lstrip("\n")
        open(ruta, "w", encoding="utf-8").write(txt)


def crear_footprint_sma():
    """footprint local: el Amphenol 132289 sin los pads de masa de la cara de arriba
    (pin central arriba, masa solo abajo) + fp-lib-table del proyecto que lo registra"""
    txt = open(os.path.join(LIB_SMA, FP_SMA + ".kicad_mod"), encoding="utf-8").read()

    def bloques(s, cabeza):
        """(inicio, fin) de cada expresion que empieza con `cabeza`, contando parentesis"""
        i = 0
        while True:
            i = s.find(cabeza, i)
            if i < 0:
                return
            n, j = 0, i
            while True:
                n += {"(": 1, ")": -1}.get(s[j], 0)
                j += 1
                if n == 0:
                    break
            yield i, j
            i = j

    # se sacan los pads de masa (pad "2") que estan en la cara de arriba
    fuera = [(a, b) for a, b in bloques(txt, '(pad "2"') if '"F.Cu"' in txt[a:b]]
    for a, b in reversed(fuera):
        a0 = txt.rfind("\n", 0, a) + 1
        txt = txt[:a0] + txt[b:].lstrip(" \t").lstrip("\n")
    txt = txt.replace(f'(footprint "{FP_SMA}"', f'(footprint "{FP_LOCAL}"', 1)
    i, j = next(bloques(txt, "(descr"))
    txt = txt[:i] + ('(descr "SMA de borde para placa de 1,6 mm, 4 patas de masa en las esquinas: '
                     'solo las dos de abajo apoyan en la placa (basado en Amphenol 132289)")') + txt[j:]
    os.makedirs(LIB_LOCAL, exist_ok=True)
    with open(os.path.join(LIB_LOCAL, FP_LOCAL + ".kicad_mod"), "w", encoding="utf-8") as f:
        f.write(txt)
    with open(os.path.join(AQUI, "fp-lib-table"), "w", encoding="utf-8") as f:
        f.write('(fp_lib_table\n  (version 7)\n'
                '  (lib (name "filtros_rf")(type "KiCad")(uri "${KIPRJMOD}/filtros_rf.pretty")'
                '(options "")(descr "footprints propios de la placa de filtros"))\n)\n')


def main():
    dis = json.load(open(os.path.join(FILTRO, "diseno_hong.json"), encoding="utf-8"))
    crear_footprint_sma()
    board = pcbnew.BOARD()
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    ds.SetBoardThickness(MM(1.6))
    # el plano de masa llega hasta el canto: debajo de la linea de 50 ohm, junto al SMA, no
    # tiene que haber un tramo sin masa (las esquinas de los tornillos quedan igual sin cobre)
    ds.m_CopperEdgeClearance = 0
    gnd = red(board, "GND")

    # borde de la placa
    borde = pcbnew.PCB_SHAPE(board)
    borde.SetShape(pcbnew.SHAPE_T_RECT)
    borde.SetStart(P(0, 0))
    borde.SetEnd(P(W, H))
    borde.SetLayer(pcbnew.Edge_Cuts)
    borde.SetWidth(MM(0.1))
    board.Add(borde)

    nref = 1
    for nombre, rec, yl, net, rot in FILAS:
        r = dis[nombre]
        rects, largo, w0 = geometria(r, rec)
        x0 = (W - largo) / 2
        n = red(board, net)
        # cobre: filtro + lineas de 50 ohm hasta los cantos (y de geometria hacia arriba)
        placa = [[x0 + a, x0 + b, yl - d, yl - c] for a, b, c, d in rects]
        placa += [[0.0, x0, yl - w0 / 2, yl + w0 / 2], [x0 + largo, W, yl - w0 / 2, yl + w0 / 2]]
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_POLY)
        s.SetPolyShape(poligono(placa))
        s.SetFilled(True)
        s.SetWidth(0)
        s.SetLayer(pcbnew.F_Cu)
        s.SetNet(n)
        board.Add(s)
        # SMA de borde en cada punta (el conector apunta hacia +x del footprint; el canto cae en x = +2,54)
        for xc, ang in ((2.54, 180.0), (W - 2.54, 0.0)):
            fp = pcbnew.FootprintLoad(LIB_LOCAL, FP_LOCAL)
            fp.SetFPID(pcbnew.LIB_ID("filtros_rf", FP_LOCAL))
            fp.SetReference(f"J{nref}")
            nref += 1
            fp.SetValue("SMA borde")
            fp.SetPosition(P(xc, yl))
            fp.SetOrientationDegrees(ang)
            for pad in fp.Pads():
                pad.SetNet(n if pad.GetNumber() == "1" else gnd)
            board.Add(fp)
        texto(board, rot, ESQUINA + 1.0, yl - 9.5)

    # agujeros de fijacion en las esquinas: sin metalizar y con la esquina entera sin cobre
    # en las dos caras, asi el tornillo no toca masa y el plano no rodea el agujero
    for i, (xh, yh) in enumerate(((D_HUECO, D_HUECO), (W - D_HUECO, D_HUECO),
                                  (D_HUECO, H - D_HUECO), (W - D_HUECO, H - D_HUECO))):
        fp = pcbnew.FootprintLoad(LIB_HUECO, FP_HUECO)
        fp.SetFPID(pcbnew.LIB_ID("MountingHole", FP_HUECO))
        fp.SetReference(f"H{i + 1}")
        fp.SetValue("M3")
        fp.SetPosition(P(xh, yh))
        fp.Reference().SetVisible(False)
        board.Add(fp)
        x0 = 0.0 if xh < W / 2 else W - ESQUINA
        y0 = 0.0 if yh < H / 2 else H - ESQUINA
        k = pcbnew.ZONE(board)
        k.SetIsRuleArea(True)
        k.SetDoNotAllowZoneFills(True)
        k.SetDoNotAllowTracks(True)
        k.SetDoNotAllowVias(True)
        k.SetDoNotAllowPads(False)                  # el agujero es un "pad" sin cobre
        k.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.B_Cu)
        k.SetLayerSet(ls)
        for x, y in ((x0, y0), (x0 + ESQUINA, y0), (x0 + ESQUINA, y0 + ESQUINA), (x0, y0 + ESQUINA)):
            k.AppendCorner(P(x, y), -1)
        board.Add(k)

    texto(board, "Pasabajos RF GPR - FR4 1,6 mm - Cu 72 um", ESQUINA + 1.0, H - 3.0, alto=1.0)
    texto(board, "Hong 5.1.3 / FIUBA 2026", W / 2, H - 3.0, alto=1.0, capa=pcbnew.B_SilkS)

    # plano de masa entero abajo
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.B_Cu)
    z.SetNet(gnd)
    for x, y in ((0, 0), (W, 0), (W, H), (0, H)):
        z.AppendCorner(P(x, y), -1)
    z.SetMinThickness(MM(0.25))
    z.SetLocalClearance(MM(0.3))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    board.Add(z)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    pcbnew.SaveBoard(SALIDA, board)
    escribir_stackup(SALIDA)
    # regla: SMA de borde, lineas de RF y plano de masa llegan al canto a proposito
    with open(SALIDA.replace(".kicad_pcb", ".kicad_dru"), "w", encoding="utf-8") as f:
        f.write('(version 1)\n'
                '(rule "SMA de borde, lineas de RF y plano de masa hasta el canto"\n'
                '  (constraint edge_clearance (min 0mm))\n'
                '  (severity ignore))\n')
    print("escrito", SALIDA)


if __name__ == "__main__":
    main()
