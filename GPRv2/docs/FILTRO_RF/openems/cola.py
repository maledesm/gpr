"""
Cola de simulaciones openEMS, una por vez (en paralelo se pisan los 12 hilos).

  - espera a que termine el proceso que se le pase con --esperar <PID>
  - corre cada trabajo con un tope de 2 h (si se pasa, lo corta y sigue con el siguiente)
  - guarda la salida completa del motor en resultados/<tag>/log.txt (para ver el progreso)
  - escribe el estado de la cola en cola_estado.txt y regenera dashboard.html despues de cada uno

Uso:  C:/Users/tinch/venvs/openems/Scripts/python.exe cola.py [--esperar PID]
"""
import os, sys, re, json, time, subprocess, argparse, datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
PY = r"C:\Users\tinch\venvs\openems\Scripts\python.exe"
TOPE_S = 2 * 3600

TRABAJOS = [
    # ya hechas (2026-11-10): A y B PEC lambda/20, convergencia de la A (lambda/30 y /40).
    # La convergencia mostro ~1 % en los ceros y ~2 dB en el rechazo de lambda/20 a /40,
    # menos que la tolerancia del FR4, asi que todo lo demas va en lambda/20.
    # ya hechas tambien: A y B en lamina (lambda/20).
    # B con los stubs recortados x0,935 (su primer cero cayo 7 % abajo): primero las cortas
    # ya hechas tambien: B recortada en PEC y en lamina. Martin eligio la B recortada (2026-11-10).
    # cobre de 72 um en bloque + FR4 con perdidas
    ("A", "thick", 20), ("B", "thick", 20, 0.935),
]
NOMBRE = {"A": "A_n5", "B": "B_n7"}
SIM_RAIZ = r"D:\sim_filtro"
# estancamiento: si la energia no baja al menos MEJORA_DB en VENTANA_S, se corta la corrida
# y se usa lo que hay (el motor para limpio con el archivo ABORT y se calculan los S igual)
MEJORA_DB, VENTANA_S = 0.5, 120
RE_DB = re.compile(r"Energy: ~\S+ \((-?)\s*([\d.]+)dB\)")


def ultimo_db(ruta_log):
    try:
        with open(ruta_log, encoding="utf-8", errors="ignore") as f:
            f.seek(max(0, os.path.getsize(ruta_log) - 4000))
            m = RE_DB.findall(f.read())
        return -float(m[-1][1]) if m else None
    except OSError:
        return None


def energia_final(ruta_log):
    """energia al terminar: la de la linea end-criteria, o la ultima informada"""
    try:
        txt = open(ruta_log, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    m = re.search(r"end-criteria of .* reached after \d+ timesteps \((-?[\d.]+)dB\)", txt)
    return float(m.group(1)) if m else ultimo_db(ruta_log)


def vigilar(p, ruta_log, sim_path):
    """espera a la corrida; devuelve (codigo, estancada). Codigo None = tope de 2 h"""
    t0, hist, estancada = time.time(), [], False
    while p.poll() is None:
        if time.time() - t0 > TOPE_S:
            p.kill()
            return None, False
        db = ultimo_db(ruta_log)
        ahora = time.time()
        if db is not None and db < -10:          # recien cuando el pulso ya paso
            hist.append((ahora, db))
            viejos = [v for t, v in hist if ahora - t >= VENTANA_S]
            if viejos and not estancada and db > viejos[-1] - MEJORA_DB:
                open(os.path.join(sim_path, "ABORT"), "w").close()
                estancada = True
        time.sleep(10)
    return p.returncode, estancada


def anotar_metricas(carpeta, fin, estancada):
    ruta = os.path.join(carpeta, "metricas.json")
    if os.path.exists(ruta):
        m = json.load(open(ruta, encoding="utf-8"))
        m.update(energia_final_dB=fin, estancada=estancada)
        json.dump(m, open(ruta, "w", encoding="utf-8"), indent=2)


def estado(lineas):
    with open(os.path.join(AQUI, "cola_estado.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--esperar", type=int, default=None)
    x = a.parse_args()
    reg = [f"cola iniciada {datetime.datetime.now():%Y-%m-%d %H:%M}"]
    if x.esperar:
        reg.append(f"esperando que termine el PID {x.esperar}")
        estado(reg)
        while subprocess.run(["tasklist", "/FI", f"PID eq {x.esperar}"], capture_output=True,
                             text=True).stdout.count(str(x.esperar)):
            time.sleep(20)
        reg.append(f"  PID {x.esperar} termino {datetime.datetime.now():%H:%M}")
    for trabajo in TRABAJOS:
        d, metal, N = trabajo[:3]
        recorte = trabajo[3] if len(trabajo) > 3 else 1.0
        tag = f"{NOMBRE[d]}_{metal}_er4.4_N{N}" + (f"_rec{recorte:g}" if recorte != 1 else "")
        carpeta = os.path.join(AQUI, "resultados", tag)
        os.makedirs(carpeta, exist_ok=True)
        t0 = time.time()
        reg.append(f"{datetime.datetime.now():%H:%M} -> {tag} (log en resultados/{tag}/log.txt)")
        estado(reg)
        ruta_log = os.path.join(carpeta, "log.txt")
        with open(ruta_log, "w", encoding="utf-8") as log:
            p = subprocess.Popen([PY, "-u", "simular_filtro.py", d, "--metal", metal, "--malla", str(N),
                                  "--recorte", str(recorte)],
                                 cwd=AQUI, stdout=log, stderr=subprocess.STDOUT)
            rc, estancada = vigilar(p, ruta_log, os.path.join(SIM_RAIZ, tag))
            if rc is None:
                res = "CORTADO por superar 2 h"
            else:
                res = "ok" if rc == 0 else f"ERROR (codigo {rc})"
        fin = energia_final(ruta_log)
        if fin is not None:
            res += f", energia final {fin:.1f} dB" + (" (estancada, cortada)" if estancada else "")
            anotar_metricas(carpeta, fin, estancada)
        reg[-1] += f"  {res}, {(time.time()-t0)/60:.1f} min"
        estado(reg)
        subprocess.run([PY, "dashboard.py"], cwd=AQUI, capture_output=True)
    reg.append(f"cola terminada {datetime.datetime.now():%Y-%m-%d %H:%M}")
    estado(reg)


if __name__ == "__main__":
    main()
