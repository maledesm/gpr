"""
Cola de MEEP (se corre desde Windows): espera a que termine la cola de openEMS y lanza en WSL
cada diseno con 6 procesos MPI. Log en resultados/<tag>/log.txt, estado en cola_estado.txt.

Uso:  C:/Users/tinch/venvs/gpr-win/Scripts/python.exe cola_meep.py [--esperar PID]
"""
import os, time, subprocess, argparse, datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
WSL_DIR = "/mnt/d/Docs/FIUBA/6to año/Tesis/gpr-tesis/GPRv2/docs/FILTRO_RF/meep"
ENV = "/opt/miniforge/envs/meep_mpi/bin"
TOPE_S = 3 * 3600
TRABAJOS = [("A", 8, 1.0), ("B", 8, 0.935)]       # la B con los stubs recortados x0,935
NP = 6


def estado(reg):
    open(os.path.join(AQUI, "cola_estado.txt"), "w", encoding="utf-8").write("\n".join(reg) + "\n")


def no_suspender():
    """pide a Windows que no suspenda por inactividad mientras viva este proceso (no cambia la configuracion)"""
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main():
    no_suspender()
    a = argparse.ArgumentParser()
    a.add_argument("--esperar", type=int, default=None)
    x = a.parse_args()
    reg = [f"cola MEEP iniciada {datetime.datetime.now():%Y-%m-%d %H:%M}"]
    if x.esperar:
        reg.append(f"esperando que termine el PID {x.esperar} (cola de openEMS)")
        estado(reg)
        while str(x.esperar) in subprocess.run(["tasklist", "/FI", f"PID eq {x.esperar}"],
                                               capture_output=True, text=True).stdout:
            time.sleep(30)
    for d, res, rec in TRABAJOS:
        tag = {"A": "A_n5", "B": "B_n7"}[d] + f"_res{res}" + (f"_rec{rec:g}" if rec != 1 else "")
        carpeta = os.path.join(AQUI, "resultados", tag)
        os.makedirs(carpeta, exist_ok=True)
        t0 = time.time()
        reg.append(f"{datetime.datetime.now():%H:%M} -> {tag}, {NP} procesos (log en resultados/{tag}/log.txt)")
        estado(reg)
        cmd = (f'cd "{WSL_DIR}" && {ENV}/mpirun -np {NP} {ENV}/python '
               f'simular_filtro_meep.py {d} --res {res} --recorte {rec}')
        with open(os.path.join(carpeta, "log.txt"), "w", encoding="utf-8") as log:
            p = subprocess.Popen(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "bash", "-c", cmd],
                                 stdout=log, stderr=subprocess.STDOUT)
            try:
                rc = p.wait(timeout=TOPE_S)
                r = "ok" if rc == 0 else f"ERROR (codigo {rc})"
            except subprocess.TimeoutExpired:
                p.kill()
                subprocess.run(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "pkill", "-f", "simular_filtro_meep"])
                r = "CORTADO por superar 3 h"
        reg[-1] += f"  {r}, {(time.time()-t0)/60:.1f} min"
        estado(reg)
        subprocess.run([r"C:\Users\tinch\venvs\openems\Scripts\python.exe", "dashboard.py"],
                       cwd=os.path.join(AQUI, "..", "openems"), capture_output=True)
    reg.append(f"cola MEEP terminada {datetime.datetime.now():%Y-%m-%d %H:%M}")
    estado(reg)


if __name__ == "__main__":
    main()
