"""
GPRv3 - Verificacion sin hardware
=================================

    python verificar.py

Comprueba todo lo que se puede comprobar sin la placa:

  1. el protocolo (ida y vuelta, reenganche, bytes corruptos);
  2. que el nucleo del firmware, compilado con gcc para la PC, arma bit a
     bit los mismos paquetes que el modelo en Python (si no hay gcc, se
     saltea);
  3. que el flanco del sync cae en la muestra que corresponde despues del
     filtro de diezmado;
  4. que blancos sinteticos de distancia conocida salen en su lugar, con
     cualquier sps, cualquier Tprf, moviendo el pote y recortando la rampa;
  5. que paquetes perdidos, flancos espurios y flancos faltantes se
     descartan sin arruinar la medicion;
  6. la grabacion y las capturas;
  7. que una captura REAL de GPRv2 da el mismo perfil con la cadena nueva
     que con la vieja (si los datos de GPRv2 estan en el repo).

  8. que RETARDO_S corrige un atraso del batido respecto del sync;
  9. las ventanas de FFT, que las filas ya dibujadas no se recalculan y el
     ajuste automatico del retardo;
 10. la curva del barrido medida con un retardo conocido.

Al final informa cuanto cuesta ese atraso si no se compensa.
"""

import os
import random
import shutil
import subprocess
import sys
import tempfile

import numpy as np

import captura
import config as cfg
import protocolo as pr
import sintetico as s
from fuentes import Eventos, Grabador, leer_grabacion
from modelo import Radar
from proceso import cargar_curva, pico_parabolico

RES = []
BLANCOS = [(1.61, 8e5), (3.70, 2e5)]


def ok(nombre, cond, detalle=""):
    RES.append(bool(cond))
    print(f"  [{'ok' if cond else 'FALLA'}] {nombre}" + (f"  ({detalle})" if detalle else ""))


def paquetes_de(datos, trozo=997):
    dec = pr.Decodificador()
    paq = []
    for i in range(0, len(datos), trozo):
        paq += dec.alimentar(datos[i:i + trozo])
    return paq, dec


def eventos_de(paquetes):
    ev = Eventos()
    for tipo, carga in paquetes:
        ev.agregar(tipo, carga)
    return ev


def radar_de(curva, paquetes, **ajustes):
    r = Radar(curva)
    for k, v in ajustes.items():
        setattr(r, k, v)
    r.ventana = 1e9
    r.alimentar(eventos_de(paquetes))
    return r


def pico(perfil, d0, ancho=0.25):
    """(distancia, amplitud) del maximo a menos de `ancho` de d0."""
    a = int(round((d0 - ancho) / cfg.DR_M))
    b = int(round((d0 + ancho) / cfg.DR_M))
    i = a + int(np.argmax(perfil[a:b]))
    return (i + pico_parabolico(perfil, i)) * cfg.DR_M, float(perfil[i])


def perfil_medio(radar):
    """Raiz de la potencia media: amplitud, en cuentas del ADC."""
    return np.sqrt(radar.P[:radar.n_perf].mean(axis=0))


def perfil_sentido(radar):
    return np.sqrt(radar._promedio(radar._indices(1e9)))


def generar(curva, segundos=4.0, semilla=1, **banco):
    banco.setdefault("blancos", BLANCOS)
    g = s.Generador(s.Banco(**banco), curva, semilla)
    return g.bloques(int(segundos * s.FS / s.BLOQUE))


# --- 1 ---------------------------------------------------------------------

def protocolo():
    print("1. Protocolo")
    muestras = np.array([0, 1, -1, 8388607, -8388608, 0x5AA5, 123456, -654321])
    originales = [
        (pr.INFO, pr.info(48000, 4, 10, 256)),
        (pr.DATOS, pr.datos(4000000000, muestras)),
        (pr.SYNC, pr.sync(123456 * 256 + 77, 1, 987654321)),
        (pr.ESTADO, pr.estado(1, 2, 3, 4)),
        (pr.TEXTO, pr.texto("hola")),
    ]
    paq, dec = paquetes_de(b"".join(p for _, p in originales))
    ok("ida y vuelta de los cinco tipos",
       [t for t, _ in paq] == [t for t, _ in originales] and dec.basura == 0)
    idx0, v = pr.leer_datos(paq[1][1])
    ok("muestras de 24 bits con signo, y un 0xA5 0x5A adentro de los datos",
       idx0 == 4000000000 and np.array_equal(v, muestras))
    pos, nivel, t_us = pr.leer_sync(paq[2][1])
    ok("flanco con fraccion", pos == 123456 + 77 / 256 and nivel == 1
       and t_us == 987654321)
    ok("informacion", pr.leer_info(paq[0][1])["sps"] == 12000)

    curva = cargar_curva()
    limpio = generar(curva, 1.0)
    ref, _ = paquetes_de(limpio)
    texto = b"# GPRv3 adquisicion con sincronismo\r\n# comandos: run\r\n\xa5"
    sucio = texto + limpio[:5000] + b"\xa5\x5aXX" + limpio[5000:] + b"# stop\r\n"
    iguales = True
    for trozo in (1, 7, 64, 4096):
        paq, dec = paquetes_de(sucio, trozo)
        iguales &= len(paq) >= len(ref) - 1 and dec.basura > len(texto)
    ok("se engancha con texto y basura en el medio, en trozos de 1 a 4096",
       iguales, f"{len(ref)} paquetes")
    roto = bytearray(limpio)
    roto[len(roto) // 2] ^= 0x10
    paq, dec = paquetes_de(bytes(roto))
    ok("un byte corrupto cuesta un solo paquete",
       len(paq) == len(ref) - 1 and dec.crc_malos >= 1)


# --- 2 y 3 -----------------------------------------------------------------

def firmware_c(curva):
    print("2. El nucleo del firmware, compilado para la PC")
    gcc = shutil.which("gcc")
    fuente = os.path.join(cfg.RAIZ, "firmware", "prueba_pc", "prueba_nucleo.c")
    if not gcc:
        print("  (no hay gcc: se saltea)")
        return
    tmp = tempfile.mkdtemp(prefix="gprv3_")
    exe = os.path.join(tmp, "prueba_nucleo.exe")
    c = subprocess.run([gcc, "-O2", "-o", exe, fuente], capture_output=True,
                       text=True)
    ok("compila", c.returncode == 0, c.stderr.strip()[:200])
    if c.returncode:
        return
    n = 400
    for dec in (2, 4, 8, 16):
        banco = dict(sps=s.FS // dec, tprf=0.0437, ruido=3e5)
        with open(os.path.join(tmp, "e.bin"), "wb") as f:
            f.write(s.Generador(s.Banco(**banco), curva, 7).entrada_c(n))
        python, _ = paquetes_de(s.Generador(s.Banco(**banco), curva, 7).bloques(n))
        salidas = []
        for atraso in (0, 3000, 9000):
            subprocess.run([exe, os.path.join(tmp, "e.bin"),
                            os.path.join(tmp, "s.gpr3"), str(atraso)], check=True)
            with open(os.path.join(tmp, "s.gpr3"), "rb") as f:
                paq, d = paquetes_de(f.read())
            salidas.append([p for p in paq if p[0] in (pr.INFO, pr.DATOS, pr.SYNC)])
        en_c = salidas[0]
        # El modelo puede informar un flanco de mas si cayo justo al final.
        ok(f"dec {dec}: los paquetes del C y del modelo son identicos",
           d.basura == 0 and en_c == python[:len(en_c)]
           and len(python) - len(en_c) <= 1, f"{len(en_c)} paquetes")
        peor = 0.0
        mismos = True
        for otra in salidas[1:]:
            mismos &= ([p for p in otra if p[0] == pr.DATOS]
                       == [p for p in en_c if p[0] == pr.DATOS])
            a = [pr.leer_sync(c)[0] for t, c in en_c if t == pr.SYNC]
            b = [pr.leer_sync(c)[0] for t, c in otra if t == pr.SYNC]
            peor = max(peor, max(abs(x - y) for x, y in zip(a, b)))
        # El reloj de la placa cuenta microsegundos: hasta ahi puede variar.
        ok(f"dec {dec}: el flanco cae igual aunque el lazo lo atienda tarde",
           mismos and peor <= 1.5e-6 * s.FS / dec + 1 / 256,
           f"peor diferencia {peor / (s.FS / dec) * 1e6:.2f} us")
    shutil.rmtree(tmp, ignore_errors=True)


def retardo_del_filtro():
    print("3. El flanco y el retardo del filtro de diezmado")
    for dec in (2, 4, 8, 16):
        esperado = 1000
        j0 = esperado * dec - 14 * (dec - 1)
        x = np.zeros(2048 * dec, dtype=np.int64)
        x[j0] = 4000000
        m = int(np.argmax(np.abs(s.Diezmador(dec).pasar(x))))
        n_in_ult = 2047
        t = lambda j: (j + 1) * 1000000 // s.FS
        idx = s.indice_flanco256(n_in_ult, t(n_in_ult), t(j0), s.FS, dec) / 256
        ok(f"dec {dec}: un impulso y un flanco simultaneos salen en la misma muestra",
           m == esperado and abs(idx - esperado) < 0.01,
           f"impulso en {m}, flanco en {idx:.3f}")


# --- 4 ---------------------------------------------------------------------

def distancias(curva):
    print("4. Blancos sinteticos de distancia conocida")

    def revisar(nombre, radar, tol_m=0.005, tol_amp=0.03):
        p = perfil_medio(radar)
        peor_d = peor_a = 0.0
        for d0, a0 in BLANCOS:
            d, a = pico(p, d0)
            peor_d = max(peor_d, abs(d - d0))
            peor_a = max(peor_a, abs(a / a0 - 1))
        ok(nombre, peor_d < tol_m and peor_a < tol_amp and radar.n_perf > 5,
           f"error {peor_d * 1e3:.1f} mm, amplitud {peor_a * 100:.1f} %, "
           f"{radar.n_perf} rampas")

    for sps, tprf in ((12000, 0.100), (6000, 0.100), (24000, 0.100),
                      (12000, 0.020), (24000, 0.275), (3000, 0.150)):
        revisar(f"{sps} sps, Tprf {tprf * 1e3:.0f} ms",
                radar_de(curva, paquetes_de(generar(curva, sps=sps, tprf=tprf))[0]))

    paq, _ = paquetes_de(generar(curva, 6.0, tprf=lambda t: 0.050 + 0.015 * t))
    r = radar_de(curva, paq)
    revisar("moviendo el pote de 50 a 140 ms, sin reiniciar nada", r)
    ok("  ...y casi todas las rampas sirven",
       r.seg.validas > 0.9 * (r.seg.flancos - 1),
       f"{r.seg.validas} de {r.seg.flancos - 1}")

    paq, _ = paquetes_de(generar(curva))
    r = Radar(curva)
    r.fijar_ventana(0.15, 0.85)
    r.ventana = 1e9
    r.alimentar(eventos_de(paq))
    revisar("usando solo del 15 al 85 % de la rampa", r)
    res = r.resumen()
    ok("  ...con la resolucion que corresponde a la banda que queda",
       abs(res["resolucion"] - cfg.C / (2 * res["bw"])) < 1e-9
       and res["bw"] < 0.8 * res["bw_total"],
       f"{res['resolucion'] * 100:.1f} cm con {res['bw'] / 1e6:.0f} MHz")

    r = radar_de(curva, paq)
    picos = {}
    for sentido in ("subida", "bajada"):
        r.sentido = sentido
        picos[sentido] = pico(perfil_sentido(r), 3.70)
    ok("subidas y bajadas dan el mismo pico",
       abs(picos["subida"][0] - picos["bajada"][0]) < 0.003
       and abs(picos["subida"][1] / picos["bajada"][1] - 1) < 0.03,
       f"{picos['subida'][0]:.4f} y {picos['bajada'][0]:.4f} m")

    # Que la prueba es sensible: con la polaridad del sync al reves, el mapa
    # se aplica espejado y el pico se desparrama.
    paq, _ = paquetes_de(generar(curva, sync_alto_es_bajada=False))
    a = pico(perfil_medio(radar_de(curva, paq)), 3.70)[1]
    ok("con la polaridad del sync invertida el pico se cae (y se nota)",
       a < 0.5 * 2e5, f"queda en {a / 2e5 * 100:.0f} % de la amplitud")


# --- 5 ---------------------------------------------------------------------

def robustez(curva):
    print("5. Paquetes perdidos y flancos malos")
    paq, _ = paquetes_de(generar(curva, 6.0))
    azar = random.Random(3)

    def picos_bien(r, tol_amp=0.05):
        p = perfil_medio(r)
        return all(abs(pico(p, d0)[0] - d0) < 0.006
                   and abs(pico(p, d0)[1] / a0 - 1) < tol_amp
                   for d0, a0 in BLANCOS)

    falta = [p for p in paq if p[0] != pr.DATOS or azar.random() > 0.02]
    r = radar_de(curva, falta)
    ok("2 % de los paquetes de datos perdidos: se descartan esas rampas",
       picos_bien(r) and r.sin_muestras > 0 and len(r.muestras.huecos) >= 0,
       f"{r.sin_muestras} rampas descartadas, {r.n_perf} buenas")

    sucio = []
    for p in paq:
        sucio.append(p)
        if p[0] == pr.SYNC and azar.random() < 0.08:
            pos, nivel, t_us = pr.leer_sync(p[1])
            d = azar.uniform(0.2, 0.8) * 0.05 * 12000
            sucio.append((pr.SYNC, pr.sync(int((pos + d) * 256), 1 - nivel,
                                           t_us + int(d / 12000 * 1e6))[5:-2]))
            sucio.append((pr.SYNC, pr.sync(int((pos + d + 30) * 256), nivel,
                                           t_us + int((d + 30) / 12000 * 1e6))[5:-2]))
    r = radar_de(curva, sucio)
    ok("flancos espurios en el medio de una rampa: se descartan los pedazos",
       picos_bien(r) and r.seg.incoherentes + r.seg.fuera_de_rango > 0,
       f"{r.seg.incoherentes + r.seg.fuera_de_rango} pedazos descartados, "
       f"{r.n_perf} rampas buenas")

    falta = [p for p in paq if p[0] != pr.SYNC or azar.random() > 0.05]
    r = radar_de(curva, falta)
    ok("flancos que no llegaron: no se usa la rampa doble",
       picos_bien(r) and r.seg.repetidos > 0,
       f"{r.seg.repetidos} repetidos, {r.n_perf} rampas buenas")

    r = radar_de(curva, paq + paquetes_de(generar(curva, 2.0, sps=6000))[0])
    ok("la placa se reinicia con otros sps: arranca de cero",
       r.sps == 6000 and picos_bien(r))


# --- 6 ---------------------------------------------------------------------

def grabacion_y_captura(curva):
    print("6. Grabacion y capturas")
    tmp = tempfile.mkdtemp(prefix="gprv3_")
    paq, _ = paquetes_de(generar(curva))
    g = Grabador({"prueba": 1}, None, carpeta=tmp, sello="prueba")
    g.escribir(paq)
    g.cerrar()
    ev = leer_grabacion(g.ruta)
    r1 = radar_de(curva, paq)
    r2 = Radar(curva)
    r2.ventana = 1e9
    r2.alimentar(ev)
    ok("lo grabado se lee y da el mismo perfil",
       ev.meta == {"prueba": 1, "parte": 1}
       and np.array_equal(perfil_medio(r1), perfil_medio(r2)))

    viejo = cfg.CAPTURAS
    cfg.CAPTURAS = os.path.join(tmp, "capturas")
    try:
        r1.ventana = 20.0
        r1.ignorar = 2.0
        msj, base = captura.guardar(r1, "placa: 1m?")
        ok("guarda el par PNG + CSV, con un nombre que Windows acepta",
           base is not None and os.path.getsize(base + ".png") > 20000
           and os.path.basename(base) == "placa_ 1m_", msj)
        _, base2 = captura.guardar(r1, "placa: 1m?")
        ok("no pisa una captura anterior", base2 == base + "_2")
        meta, col = captura.leer_csv(base + ".csv")
        i = int(np.argmax(col["mag"][100:])) + 100
        ok("el CSV trae la curva y el pico que se informa",
           abs(float(meta["pico_crudo_m"]) - 3.70) < 0.005
           and abs(col["d_crudo_m"][i] - 3.70) < 0.02
           and abs(col["db_norm"].max()) < 1e-6,
           f"pico {meta['pico_crudo_m']} m")
        v2 = os.path.join(cfg.RAIZ, "..", "GPRv2", "analisis")
        if os.path.exists(os.path.join(v2, "proceso_rapido.py")):
            sys.path.insert(0, v2)
            from proceso_rapido import leer_fft_captura
            m2, c2 = leer_fft_captura(base + ".csv")
            ok("el lector de GPRv2 (leer_fft_captura) lo lee igual",
               m2 == meta and all(np.array_equal(c2[k], col[k]) for k in col))
    finally:
        cfg.CAPTURAS = viejo
        shutil.rmtree(tmp, ignore_errors=True)


# --- 7 ---------------------------------------------------------------------

def contra_gprv2():
    print("7. Una captura real de GPRv2, con la cadena vieja y con la nueva")
    v2 = os.path.normpath(os.path.join(cfg.RAIZ, "..", "GPRv2"))
    sello = "28-09-2026_17-53-54"
    cap = os.path.join(v2, "datos", f"captura_{sello}.csv")
    tri = os.path.join(v2, "datos", f"triangular_{sello}.csv")
    curva_csv = os.path.join(v2, "..", "VCO", "Caracteristica VCO.csv")
    if not (os.path.exists(cap) and os.path.exists(tri)):
        print("  (no estan los datos de GPRv2: se saltea)")
        return
    import io
    from contextlib import redirect_stdout
    sys.path.insert(0, os.path.join(v2, "analisis"))
    import correccion_no_linealidad as cnl

    fs = 6000.0
    beat = np.loadtxt(cap, delimiter=",", usecols=0)
    adc, fila = np.loadtxt(tri, delimiter=",", unpack=True)

    # La cadena vieja: limites de rampa ajustados a la triangular, un spline
    # por rampa sobre theta y FFT con relleno x8.
    with redirect_stdout(io.StringIO()):
        rampas, _, n = cnl.rampas_desde_triangular(beat, fila, adc, fs, 300)
        T, t0 = cnl.ajustar_triangular(fila, adc, fs,
                                       cnl.buscar_periodo(fila, adc, fs), 0.10)
    curva_v2 = cnl.cargar_curva_vco(curva_csv)
    t = np.linspace(0, n / fs, n, endpoint=False)
    _, theta, alpha0 = cnl.eje_theta(curva_v2, t)
    E = np.zeros(4 * n + 1)
    for x in rampas:
        _, y = cnl.remuestrear(theta, x - x.mean(), n)
        E += np.abs(np.fft.rfft(y * np.hanning(n), 8 * n)) ** 2
    E = np.sqrt(E)      # promedio en potencia, como hace la cadena nueva
    eje_v2 = np.fft.rfftfreq(8 * n, 1 / cnl.fs_theta(theta, n)) * cnl.C / (2 * alpha0)

    # La nueva: los mismos vertices, pasados como flancos de sync.
    ev = Eventos()
    ev.info = {"sps": 6000}
    ev.muestras = [(0, beat.astype(np.int32))]
    k = np.arange(int((len(beat) / fs - t0) / (T / 2)))
    ev.flancos = [(float((t0 + i * T / 2) * fs), int(i % 2), int(i * T / 2 * 1e6))
                  for i in k]
    guardado = cfg.V_MIN, cfg.V_MAX
    cfg.V_MIN, cfg.V_MAX = cnl.V_MIN, cnl.V_MAX
    try:
        r = Radar(cargar_curva(curva_csv))
        r.ventana = 1e9
        r.alimentar(ev)
    finally:
        cfg.V_MIN, cfg.V_MAX = guardado
    nuevo = perfil_medio(r)
    viejo = np.interp(r.eje_m_crudo, eje_v2, E)
    zona = (r.eje_m_crudo > 0.3) & (r.eje_m_crudo < 10.0)
    i_n = np.flatnonzero(zona)[np.argmax(nuevo[zona])]
    d_n = (i_n + pico_parabolico(nuevo, i_n)) * cfg.DR_M
    i_v = np.argmax(np.where((eje_v2 > 0.3) & (eje_v2 < 10.0), E, 0))
    d_v = eje_v2[i_v] + pico_parabolico(E, i_v) * (eje_v2[1] - eje_v2[0])
    corr = np.corrcoef(20 * np.log10(nuevo[zona]), 20 * np.log10(viejo[zona]))[0, 1]
    ok("las dos usan casi todas las rampas", abs(r.n_perf - len(rampas)) <= 2,
       f"{len(rampas)} y {r.n_perf}, Tprf {T * 1e3:.3f} ms")
    ok("el pico mas fuerte cae en el mismo lugar", abs(d_n - d_v) < 0.02,
       f"vieja {d_v:.3f} m, nueva {d_n:.3f} m")
    ok("los perfiles coinciden entre 0,3 y 10 m", corr > 0.98,
       f"correlacion de los dB {corr:.4f}")


# --- informe ---------------------------------------------------------------

def retardo_extra(curva):
    print("8. RETARDO_S corrige un atraso del batido respecto del sync")
    paq, _ = paquetes_de(generar(curva, tprf=0.020, retardo=0.36e-3))
    cfg.RETARDO_S = 0.36e-3
    try:
        r = radar_de(curva, paq)
    finally:
        cfg.RETARDO_S = 0.0
    d, a = pico(perfil_medio(r), 3.70)
    sub, baj = r.picos_por_sentido()
    ok("con el retardo cargado, el pico vuelve a su lugar y a su altura",
       abs(d - 3.70) < 0.005 and abs(a / 2e5 - 1) < 0.03
       and abs(sub - baj) < 0.005,
       f"{d:.4f} m, subida - bajada {(sub - baj) * 100:+.2f} cm")


def lo_nuevo(curva):
    print("9. Ventanas de FFT, filas que no se recalculan y retardo automatico")
    paq, _ = paquetes_de(generar(curva))
    from proceso import VENTANAS
    for nombre in VENTANAS:
        r = Radar(curva)
        r.fijar_fft(nombre)
        r.alimentar(eventos_de(paq))
        peor_d = peor_a = 0.0
        for d0, a0 in BLANCOS:
            d, a = pico(perfil_medio(r), d0)
            peor_d = max(peor_d, abs(d - d0))
            peor_a = max(peor_a, abs(a / a0 - 1))
        # Con la rectangular los lobulos del blanco fuerte (-13 dB) pisan al
        # debil: es lo que se espera de esa ventana, no un error.
        tol_d, tol_a = (0.02, 0.10) if nombre == "rectangular" else (0.005, 0.03)
        ok(f"ventana {nombre}: los picos en su lugar y con su altura",
           peor_d < tol_d and peor_a < tol_a,
           f"error {peor_d * 1e3:.1f} mm, amplitud {peor_a * 100:.1f} %")

    r = Radar(curva)
    r.ventana = 1e9
    r.ignorar = 2.0
    mitad = len(paq) // 2
    r.alimentar(eventos_de(paq[:mitad]))
    n1 = r.n_filas
    antes = r.F[:n1].copy()
    r.n_rampas = 4
    r.medir_fondo()
    r.alimentar(eventos_de(paq[mitad:]))
    nuevas = slice(n1, r.n_filas)
    ok("cambiar rampas/fila y medir el fondo no toca las filas ya dibujadas",
       n1 > 2 and r.n_filas > n1 + 2 and np.array_equal(r.F[:n1], antes)
       and np.all(r.f_n[:n1] == 8) and np.all(np.isnan(r.f_ref[:n1])),
       f"{n1} filas viejas")
    ok("...y las nuevas salen con el agrupado y el fondo nuevos",
       np.all(r.f_n[nuevas] == 4) and not np.any(np.isnan(r.f_ref[nuevas]))
       and r.F[nuevas].max() < 0.2 * antes.max(),
       f"{r.n_filas - n1} filas nuevas")
    m = r.matriz()
    ok("el radargrama sale parejo en tiempo aunque las filas duren distinto",
       m is not None and abs(m["span"] - (r.f_fin[r.n_filas - 1] - r.f_ini[0])) < 1e-6
       and m["db"].shape[0] == round(m["span"] / 0.2))

    from modelo import AjusteRetardo
    g = s.Generador(s.Banco(tprf=0.040, retardo=0.36e-3, blancos=BLANCOS), curva, 1)
    r = Radar(curva)
    r.alimentar(eventos_de(paquetes_de(g.bloques(4 * 188))[0]))
    aj = AjusteRetardo(r)
    msj = None
    for _ in range(200):
        r.alimentar(eventos_de(paquetes_de(g.bloques(47))[0]))
        msj = aj.paso()
        if msj:
            break
    ok("el ajuste automatico encuentra el retardo del batido",
       msj is not None and "ajustado" in msj and abs(r.retardo - 0.36e-3) < 30e-6,
       f"{msj}, en {r.ahora():.0f} s")


def curva_medida(curva):
    print("10. Curva del barrido medida con un retardo conocido")
    # Un banco que NO es el que supone config.py: triangular 0,15 V mas arriba
    # y el batido atrasado 0,36 ms.
    real = dict(tprf=0.040, v_min=cfg.V_MIN + 0.15, v_max=cfg.V_MAX + 0.15,
                retardo=0.36e-3)
    g = s.Generador(s.Banco(blancos=[(4.20, 6e5)], **real), curva, 1)
    r = Radar(curva)
    r.alimentar(eventos_de(paquetes_de(g.bloques(188))[0]))
    r.calibrar_barrido(4.20)
    for _ in range(40):
        r.alimentar(eventos_de(paquetes_de(g.bloques(47))[0]))
        if r.cal_mensaje:
            break
    b = r.barrido_medido
    bw_real = float(curva(real["v_max"]) - curva(real["v_min"])) / 1e6
    ok("mide el barrido de las dos rampas", b is not None and r.barrido is b
       and abs(b["bw_mhz"] / bw_real - 1) < 0.02, r.cal_mensaje or "")
    if b is None:
        return
    tmp = tempfile.mkdtemp(prefix="gprv3_")
    r.guardar_barrido(os.path.join(tmp, "b.json"))
    r2 = Radar(curva)
    ok("la curva se guarda y se vuelve a leer",
       r2.cargar_barrido(os.path.join(tmp, "b.json")) == b)
    shutil.rmtree(tmp, ignore_errors=True)

    escena = [(1.61, 8e5), (3.70, 8e4), (7.25, 2e4)]
    paq, _ = paquetes_de(generar(curva, 6.0, blancos=escena, ruido=2e3, **real))
    res = {}
    for nombre, usar in (("estatica", None), ("medida", b)):
        x = Radar(curva)
        x.usar_barrido(usar)
        x.fijar_ventana(0.04, 0.96)
        x.alimentar(eventos_de(paq))
        p = perfil_medio(x)
        p = 20 * np.log10(p / p.max())
        d = x.eje_m_crudo
        res[nombre] = (float(np.median(p[(d > 9) & (d < 12)])),
                       [pico(perfil_medio(x), d0) for d0, _ in escena])
    piso_e, _ = res["estatica"]
    piso_m, picos = res["medida"]
    ok("con la curva medida, los tres blancos en su lugar y con su altura",
       all(abs(dm - d0) < 0.01 and abs(20 * np.log10(am / a0)) < 1.0
           for (dm, am), (d0, a0) in zip(picos, escena)),
       ", ".join(f"{dm:.3f} m" for dm, _ in picos))
    ok("...y las colas del blanco fuerte bajan (usando subidas Y bajadas)",
       piso_m < piso_e - 10,
       f"piso entre 9 y 12 m: {piso_e:.0f} dB con la estatica, "
       f"{piso_m:.0f} dB con la medida")

    g = s.Generador(s.Banco(blancos=[(0.60, 6e5)], **real), curva, 1)
    r = Radar(curva)
    r.alimentar(eventos_de(paquetes_de(g.bloques(188))[0]))
    r.calibrar_barrido(0.60)
    for _ in range(40):
        r.alimentar(eventos_de(paquetes_de(g.bloques(47))[0]))
        if r.cal_mensaje:
            break
    ok("con un retardo demasiado corto avisa y no cambia nada",
       r.barrido is None and r.cal_mensaje is not None
       and "vueltas" in r.cal_mensaje, r.cal_mensaje or "")


def costo_del_retardo(curva):
    print("Informe: cuanto cuesta un retardo sin compensar (RETARDO_S = 0)")
    print("  (0,36 ms es el del filtro digital del PCM1808 a 48 kHz)")
    for tprf in (0.100, 0.020):
        for ret in (0.0, 0.36e-3, 1.0e-3):
            paq, _ = paquetes_de(generar(curva, tprf=tprf, retardo=ret,
                                         blancos=[(3.70, 2e5)], ruido=0))
            r = radar_de(curva, paq)
            fila = []
            for sentido in ("subida", "bajada", "ambas"):
                r.sentido = sentido
                d, a = pico(perfil_sentido(r), 3.70)
                fila.append(f"{sentido} {d:.3f} m {20 * np.log10(a / 2e5):+5.1f} dB")
            print(f"  Tprf {tprf * 1e3:3.0f} ms, retardo {ret * 1e3:.2f} ms: "
                  + " | ".join(fila))


def main():
    curva = cargar_curva()
    protocolo()
    firmware_c(curva)
    retardo_del_filtro()
    distancias(curva)
    robustez(curva)
    grabacion_y_captura(curva)
    contra_gprv2()
    retardo_extra(curva)
    lo_nuevo(curva)
    curva_medida(curva)
    costo_del_retardo(curva)
    mal = RES.count(False)
    print(f"\n{len(RES)} comprobaciones, {mal} fallaron." if mal else
          f"\n{len(RES)} comprobaciones, todas bien.")
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
