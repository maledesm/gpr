"""
GPRv2 - Pasabajos eliptico en microstrip para el 2o armonico del VCO
====================================================================

Sigue al pie de la letra a Hong y Lancaster, "Microstrip Filters for RF/Microwave
Applications" (Wiley, 2001), en referencias/. Cada paso cita su ecuacion:

  - prototipo:            Tabla 3.3 (eliptico, LAr = 0,1 dB, g0 = g(n+1) = 1)
  - escalado:             ec. 5.6
  - polos (ceros de S21): ec. 5.8
  - microstrip:           ec. 4.4 y 4.5 (Hammerstad-Jensen), 4.6b (lambda_g)
  - largos iniciales:     ec. 5.9
  - correccion de stubs:  ec. 5.11 (resuelta en fc y en el polo de cada stub,
                          con los tramos serie fijos, como en el libro)
  - extremo abierto:      ec. 4.40, se resta Dl al largo de cada parche
                          (ver la errata de xi1 en extremo_abierto())

La ec. 5.10 del libro corrige el par L5-C6 del final; nuestros prototipos (n impar,
Figura 3.11b) terminan en una L serie, sin C final, asi que no aplica.

Validacion: con los datos del ejemplo de la seccion 5.1.3 este codigo da
lL2 = 2,96 mm y lC2 = 5,62 mm; el libro da 2,98 y 5,61.

ERRATA de la Tabla 3.3: en n = 7 la columna g6' repite g4'. Para Os = 1,1494 el
valor correcto es g6' = 1,4096 (con 0,5816 el cero cae en O = 1,811, que no es
un cero de la funcion; con 1,4096 cae en 1,1633, que si lo es).

Uso:  python diseno_hong.py
"""
import json, os
import numpy as np
from scipy.optimize import brentq, fsolve

AQUI = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- especificacion
FC = 2.05e9          # fin del ripple de 0,1 dB
Z0 = 50.0
ER, H = 4.4, 1.6     # FR4 nominal: reemplazar por el del fabricante / el medido
Z0L = 110.0          # Z0C va por diseno, en PROTOTIPOS

# Tabla 3.3, fila Os = 1,1494 (orden g1, g2, g2', g3, g4, g4', ...)
PROTOTIPOS = {
    "A_n5": dict(n=5, Os=1.1494, LAs=24.5451, Z0C=30.0,
                 g=[0.8726, 1.0084, 0.3845, 1.3097, 0.4991, 1.4450, 0.4302]),
    "B_n7": dict(n=7, Os=1.1494, LAs=45.6916, Z0C=20.0,   # con 30 y 25 el stub 1 pide lL <= 0
                 g=[1.0252, 1.2157, 0.1940, 1.5811, 0.9939, 0.5816, 1.2382,
                    0.5243, 1.4096, 0.4369]),          # g6' corregido (errata)
}


# ---------------------------------------------------------------- microstrip
def microstrip(u, er=ER):
    """ec. 4.4 (er efectiva) y 4.5 (Zc), con u = W/h"""
    a = (1 + np.log((u**4 + (u / 52)**2) / (u**4 + 0.432)) / 49
         + np.log(1 + (u / 18.1)**3) / 18.7)
    b = 0.564 * ((er - 0.9) / (er + 3))**0.053
    ere = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u)**(-a * b)
    F = 6 + (2 * np.pi - 6) * np.exp(-(30.666 / u)**0.7528)
    zc = 120 * np.pi / (2 * np.pi * np.sqrt(ere)) * np.log(F / u + np.sqrt(1 + (2 / u)**2))
    return zc, ere


def linea(Z):
    """ancho [mm] y er efectiva para una Zc dada (inversion iterativa de 4.5, como
    sugiere el libro en 4.1.6 cuando se quiere mas precision que 4.10/4.11)"""
    u = brentq(lambda u: microstrip(u)[0] - Z, 1e-3, 100)
    return u * H, microstrip(u)[1]


def lam_g(f, ere):
    """ec. 4.6b, en mm"""
    return 300 / (f / 1e9 * np.sqrt(ere))


def extremo_abierto(W, ere, er=ER, h=H):
    """ec. 4.40 (seccion 4.3.1.2): alargamiento equivalente Dl [mm] de un extremo
    abierto de ancho W. Ojo: xi2 aparece dentro de xi3.

    ERRATA del libro en xi1: impreso como un solo cociente pierde la factorizacion de
    la formula original (Kirschning, Jansen y Koster), que es
        xi1 = 0.434907 * (ere^0.81 + 0.26)/(ere^0.81 - 0.189) * (u^0.8544 + 0.236)/(u^0.8544 + 0.87)
    Con la version impresa el ejemplo de 5.1.3 da Dl = 0,71 mm; con esta da 0,535 mm,
    que es el 0,54 mm que usa el propio libro."""
    u = W / h
    x1 = (0.434907 * (ere**0.81 + 0.26) / (ere**0.81 - 0.189)
          * (u**0.8544 + 0.236) / (u**0.8544 + 0.87))
    x2 = 1 + u**0.371 / (2.35 * er + 1)
    x3 = 1 + 0.5274 * np.arctan(0.084 * u**(1.9413 / x2)) / ere**0.9236
    x4 = 1 + 0.037 * np.arctan(0.067 * u**1.456) * (6 - 5 * np.exp(0.036 * (1 - er)))
    x5 = 1 - 0.218 * np.exp(-7.5 * u)
    return h * x1 * x3 * x5 / x4


# ---------------------------------------------------------------- diseno
def disenar(nombre, p):
    global Z0C
    Z0C = p["Z0C"]
    wL, eL = linea(Z0L)
    wC, eC = linea(Z0C)
    w0, _ = linea(Z0)
    g = p["g"]
    n = p["n"]
    # separar: series L (g1, g3, ...) y stubs (g_par = C, g_par' = L)
    serie = [g[0]] + [g[3 * k + 3] for k in range((n - 1) // 2)]
    stubs = [(g[3 * k + 1], g[3 * k + 2]) for k in range((n - 1) // 2)]
    wc = 2 * np.pi * FC
    Ls = [Z0 * x / wc for x in serie]                              # ec. 5.6
    St = [(c / (Z0 * wc), l * Z0 / wc) for c, l in stubs]          # (C, L')
    fp = [1 / (2 * np.pi * np.sqrt(C * L)) for C, L in St]          # ec. 5.8

    lL = lambda L: lam_g(FC, eL) / (2 * np.pi) * np.arcsin(wc * L / Z0L)    # ec. 5.9
    lC = lambda C: lam_g(FC, eC) / (2 * np.pi) * np.arcsin(wc * Z0C * C)
    l_serie = [lL(L) for L in Ls]
    ini = [(lL(L), lC(C)) for C, L in St]

    def B(f, a, b):          # susceptancia "compensada" del stub, B2(f) de la ec. 5.11
        gL, gC = lam_g(f, eL), lam_g(f, eC)
        return 1 / (Z0L * np.sin(2 * np.pi * a / gL) + Z0C * np.tan(np.pi * b / gC)
                    - 1 / (np.sin(2 * np.pi * b / gC) / Z0C + np.tan(np.pi * a / gL) / Z0L))

    corr = []
    for k, ((C, L), f_p) in enumerate(zip(St, fp)):
        izq, der = l_serie[k], l_serie[k + 1]
        dB = lambda f, a: sum(np.tan(np.pi * l / lam_g(f, eL)) / Z0L for l in (izq, a, der))
        lhs = lambda f: 1 / (2 * np.pi * f * L - 1 / (2 * np.pi * f * C))
        # en fp el lado izquierdo es infinito: la rama de lineas tiene que ser un corto
        eqs = lambda x: [(lhs(FC) - B(FC, *x) - dB(FC, x[0])) * 100, 1 / B(f_p, *x)]
        sol, info, ok, msg = fsolve(eqs, ini[k], full_output=True)
        corr.append(dict(lL=sol[0], lC=sol[1], convergio=bool(ok == 1)))

    dl = extremo_abierto(wC, eC)                                   # ec. 4.40, paso 4.4

    res = dict(
        nombre=nombre, n=n, Os=p["Os"], LAs_dB=p["LAs"], fc_GHz=FC / 1e9,
        sustrato=dict(er=ER, h_mm=H),
        lineas=dict(Z0L=Z0L, W_L_mm=wL, ere_L=eL, Z0C=Z0C, W_C_mm=wC, ere_C=eC,
                    Z0=Z0, W_0_mm=w0,
                    lg_fc_mm=dict(L=lam_g(FC, eL), C=lam_g(FC, eC)),
                    lg_fp_mm=[dict(f_GHz=f / 1e9, L=lam_g(f, eL), C=lam_g(f, eC)) for f in fp]),
        L_serie_nH=[L * 1e9 for L in Ls],
        stubs=[dict(C_pF=C * 1e12, L_nH=L * 1e9, fp_GHz=f / 1e9,
                    lL_inicial_mm=i[0], lC_inicial_mm=i[1],
                    lL_corregido_mm=c["lL"], lC_corregido_mm=c["lC"], convergio=c["convergio"],
                    lC_final_mm=c["lC"] - dl)
               for (C, L), f, i, c in zip(St, fp, ini, corr)],
        l_serie_mm=l_serie,
        dl_extremo_abierto_mm=dl,
    )
    return res


def imprimir(r):
    li = r["lineas"]
    print(f"\n=== {r['nombre']}: n = {r['n']}, Os = {r['Os']}, LAs = {r['LAs_dB']} dB ===")
    print(f"  Z0L {li['Z0L']:.0f} ohm: W = {li['W_L_mm']:.3f} mm, ere = {li['ere_L']:.3f}, "
          f"lg(fc) = {li['lg_fc_mm']['L']:.1f} mm")
    print(f"  Z0C {li['Z0C']:.0f} ohm: W = {li['W_C_mm']:.3f} mm, ere = {li['ere_C']:.3f}, "
          f"lg(fc) = {li['lg_fc_mm']['C']:.1f} mm")
    print(f"  Z0  {li['Z0']:.0f} ohm: W = {li['W_0_mm']:.3f} mm")
    for k, (L, l) in enumerate(zip(r["L_serie_nH"], r["l_serie_mm"])):
        print(f"  L serie {2*k+1}: {L:.3f} nH -> {l:.2f} mm (sin corregir, como en el libro)")
    for k, s in enumerate(r["stubs"]):
        print(f"  stub {k+1} (polo {s['fp_GHz']:.3f} GHz): C {s['C_pF']:.3f} pF, L' {s['L_nH']:.3f} nH | "
              f"inicial lL {s['lL_inicial_mm']:.2f} lC {s['lC_inicial_mm']:.2f} -> "
              f"corregido lL {s['lL_corregido_mm']:.2f} lC {s['lC_corregido_mm']:.2f} mm"
              + ("" if s["convergio"] else "   (NO CONVERGIO)"))
    print(f"  extremo abierto de los parches (ec. 4.40): Dl = {r['dl_extremo_abierto_mm']:.3f} mm")
    for k, s in enumerate(r["stubs"]):
        print(f"  stub {k+1} FINAL: fino {s['lL_corregido_mm']:.2f} mm x {li['W_L_mm']:.2f} mm, "
              f"parche {s['lC_final_mm']:.2f} mm x {li['W_C_mm']:.2f} mm")


if __name__ == "__main__":
    todo = {k: disenar(k, p) for k, p in PROTOTIPOS.items()}
    for r in todo.values():
        imprimir(r)
    with open(os.path.join(AQUI, "diseno_hong.json"), "w", encoding="utf-8") as f:
        json.dump(todo, f, indent=2, ensure_ascii=False)
    print("\nescrito diseno_hong.json")
