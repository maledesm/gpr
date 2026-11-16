"""
Ventanita con el progreso de la cola de MEEP (lee cola_estado.txt y el log de cada corrida).

Cada diseno son dos pasadas: la linea recta de referencia y el filtro. Cada pasada tiene dos
etapas: mientras dura el pulso (hasta t ~ T_PULSO, en unidades de MEEP) y despues el
decaimiento del campo hasta 1e-3 de su maximo (criterio de fin). El progreso de una pasada
se estima como 60 % por el tiempo del pulso y 40 % por cuanto bajo el campo (en escala log).
Es una estimacion: el filtro tarda mas en apagarse que la referencia.

Uso:  C:/Users/tinch/venvs/gpr-win/Scripts/pythonw.exe progreso_meep.py
"""
import os, re, math, time, datetime
import tkinter as tk
from tkinter import ttk

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(AQUI, "cola_estado.txt")
T_PULSO = 420.0          # la referencia de la A llego al criterio en t ~ 421
FIN_DECAY = 1e-3         # stop_when_fields_decayed(..., 1e-3)
PASADAS = ["referencia (línea recta)", "filtro"]


def n_trabajos():
    try:
        txt = open(os.path.join(AQUI, "cola_meep.py"), encoding="utf-8").read()
        return len(re.findall(r'\("([AB])",\s*\d+', txt.split("TRABAJOS =")[1].split("\n")[0]))
    except Exception:
        return 2


def leer_estado():
    try:
        lineas = open(ESTADO, encoding="utf-8").read().splitlines()
    except OSError:
        return None
    inicio = next((l for l in lineas if l.startswith("cola MEEP iniciada")), None)
    trab = [l for l in lineas if "->" in l]
    hechos = [l for l in trab if " min" in l]
    actual = trab[-1] if trab and trab[-1] not in hechos else None
    tag = re.search(r"-> (\S+?),", actual).group(1) if actual else None
    t0 = datetime.datetime.strptime(inicio[-16:], "%Y-%m-%d %H:%M") if inicio else None
    errores = [l for l in hechos if "ERROR" in l or "CORTADO" in l]
    return dict(hechos=len(hechos), tag=tag, t0=t0, terminada=any("cola MEEP terminada" in l for l in lineas),
                errores=errores)


def leer_log(tag):
    ruta = os.path.join(AQUI, "resultados", tag, "log.txt")
    try:
        txt = open(ruta, encoding="utf-8", errors="ignore").read()
    except OSError:
        return dict(pasada=0, t=0.0, ratio=1.0, sps=None, celdas=None)
    partes = re.split(r"run \d+ finished at t = [\d.]+", txt)
    pasada = len(partes) - 1
    ult = partes[-1]
    ts = re.findall(r"on time step \d+ \(time=([\d.]+)\), ([\d.]+) s/step", ult)
    dec = re.findall(r"field decay\(t = [\d.]+\): \S+ / \S+ = (\S+)", ult)
    celdas = re.search(r"([\d.]+) M celdas", txt)
    return dict(pasada=pasada, t=float(ts[-1][0]) if ts else 0.0, ratio=float(dec[-1]) if dec else 1.0,
                sps=float(ts[-1][1]) if ts else None, celdas=celdas.group(1) if celdas else None)


def frac_pasada(t, ratio):
    if ratio >= 0.99:
        return 0.6 * min(t / T_PULSO, 1.0)
    return 0.6 + 0.4 * min(1.0, max(0.0, math.log10(max(ratio, 1e-12)) / math.log10(FIN_DECAY)))


class Ventana:
    def __init__(self):
        self.n = n_trabajos()
        self.r = tk.Tk()
        self.r.title("MEEP · progreso")
        self.r.attributes("-topmost", True)
        self.r.resizable(False, False)
        f = ttk.Frame(self.r, padding=14)
        f.pack()
        self.titulo = ttk.Label(f, text="Simulación MEEP del filtro", font=("Segoe UI", 11, "bold"))
        self.titulo.grid(row=0, column=0, sticky="w")
        ttk.Label(f, text="Total", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.total = ttk.Progressbar(f, length=380, maximum=100)
        self.total.grid(row=2, column=0)
        self.t_total = ttk.Label(f, text="", font=("Segoe UI", 9))
        self.t_total.grid(row=3, column=0, sticky="w")
        self.l_pasada = ttk.Label(f, text="Pasada actual", font=("Segoe UI", 9))
        self.l_pasada.grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.pas = ttk.Progressbar(f, length=380, maximum=100)
        self.pas.grid(row=5, column=0)
        self.det = ttk.Label(f, text="", font=("Segoe UI", 9), foreground="#52514e", justify="left")
        self.det.grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.actualizar()
        self.r.mainloop()

    def actualizar(self):
        e = leer_estado()
        if e is None:
            self.det.config(text="No encuentro cola_estado.txt")
        elif e["terminada"] or (e["tag"] is None and e["hechos"] >= self.n):
            self.total["value"] = 100
            self.pas["value"] = 100
            msg = "Terminado." + (f"  Con problemas: {len(e['errores'])}" if e["errores"] else "")
            self.titulo.config(text="MEEP · " + msg)
            self.t_total.config(text=f"{e['hechos']} de {self.n} diseños")
            self.det.config(text="Ya se puede cerrar esta ventana.")
            self.r.bell()
            return
        elif e["tag"]:
            g = leer_log(e["tag"])
            fp = frac_pasada(g["t"], g["ratio"]) if g["pasada"] < 2 else 1.0
            avance = (e["hechos"] * 2 + min(g["pasada"], 2) + (fp if g["pasada"] < 2 else 0)) / (2 * self.n)
            self.total["value"] = 100 * avance
            self.pas["value"] = 100 * fp
            dis = "A" if e["tag"].startswith("A") else ("B recortado" if "rec" in e["tag"] else "B")
            self.titulo.config(text=f"MEEP · diseño {dis}  ({e['hechos'] + 1} de {self.n})")
            trans = ""
            if e["t0"] and avance > 0.02:
                dt = (datetime.datetime.now() - e["t0"]).total_seconds()
                resto = dt / avance - dt
                trans = f"  ·  lleva {dt/60:.0f} min, faltarían ~{resto/60:.0f} min (estimado)"
            self.t_total.config(text=f"{100*avance:.0f} %{trans}")
            nom = PASADAS[min(g["pasada"], 1)]
            self.l_pasada.config(text=f"Pasada {min(g['pasada'] + 1, 2)} de 2: {nom}")
            etapa = ("inyectando el pulso" if g["ratio"] >= 0.99 else
                     f"apagándose el campo: {10*math.log10(max(g['ratio'], 1e-12)):.0f} dB de −30 dB")
            self.det.config(text=f"t = {g['t']:.0f} (unidades de MEEP)  ·  {etapa}"
                                 + (f"\n{g['sps']:.2f} s por paso" if g["sps"] else ""))
        else:
            self.det.config(text="Esperando que arranque la próxima corrida…")
        self.r.after(5000, self.actualizar)


if __name__ == "__main__":
    Ventana()
