"""
Diagramas del codigo de GPRv2, generados desde el fuente.

    python diagrama_llamadas.py                  ->  proyecto + modulos
    python diagrama_llamadas.py --vista proyecto ->  el mapa general, 1 figura
    python diagrama_llamadas.py --vista modulos  ->  1 figura por archivo
    python diagrama_llamadas.py --vista completo ->  todas las funciones (apendice)
    python diagrama_llamadas.py --listar

Salida: ../../redaccion/figuras/codigo/*.pdf, vectorial, para \\includegraphics.
Al lado queda el .dot por si hay que retocar algo a mano.

Tres vistas, porque son tres preguntas distintas
------------------------------------------------
Un solo diagrama con todas las llamadas no se entiende: vivo_rapido.py tiene
53 funciones y 81 llamadas, y dibujadas todas juntas quedan al mismo nivel,
sin jerarquia y sin por donde empezar a leer. No es un problema de estilo:
un grafo de llamadas no es un diagrama de flujo.

  proyecto   Un archivo = una caja. Las flechas son imports. Responde "que
             piezas hay y cual depende de cual". Es la figura para abrir el
             capitulo de software.

  modulos    Un archivo por figura. Las cajas son las CLASES y las funciones
             de nivel superior, no los metodos: las llamadas entre metodos de
             dos clases se agregan en una sola flecha, con la cantidad al
             lado. Responde "como estan repartidas las responsabilidades
             adentro de este archivo". Es la que sirve para explicar el codigo.

  completo   Todas las funciones, una caja cada una. Responde "quien llama
             exactamente a quien". Solo sirve como referencia puntual o
             apendice; no la pongas en el cuerpo de la tesis.

De donde salen los datos
------------------------
De graphify-out/graph.json, que se arma parseando el AST de cada archivo con
tree-sitter. Las aristas que se dibujan son SOLO las marcadas EXTRACTED, es
decir llamadas o imports escritos literalmente en el codigo. No hay nada
inferido por un modelo de lenguaje: si hay una flecha, existe esa linea en el
fuente. Eso es lo que permite citar el diagrama en la tesis.

La jerarquia clase/metodo sale de las relaciones `method` y `contains` del
mismo grafo, que es lo que permite agregar la vista de modulos.

Para regenerar el grafo despues de tocar codigo:

    graphify update .        (re-parsea, no usa LLM ni tiene costo)

Lo que un grafo estatico NO puede ver
-------------------------------------
Quedan afuera, por construccion, las llamadas que no estan escritas como tales:

  - punteros a funcion y tablas de despacho,
  - las ISR: el hardware las dispara, ninguna linea las llama. Se dibujan
    igual, con doble borde y sin flechas entrantes, porque que aparezcan
    sueltas ES el dato,
  - callbacks registrados en tiempo de ejecucion (attachInterrupt, el stack de
    I2S, los widgets de matplotlib),
  - lo que expanden las macros.

En el firmware eso no es un detalle menor: el sincronismo entre el barrido y
el muestreo pasa justamente por ahi. Esos enlaces hay que explicarlos en el
texto.

Estilo
------
Escala de grises, sin relleno de color, igual que el resto de las figuras,
para que sobreviva a la impresion en blanco y negro.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

# La consola de Windows es cp1252 y se cae con las flechas y las tildes.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent                      # GPRv2/
GRAFO = RAIZ / "graphify-out" / "graph.json"
SALIDA = RAIZ.parent / "redaccion" / "figuras" / "codigo"

LLAMADAS = {"calls", "indirect_call"}
IMPORTS = {"imports", "imports_from"}

# Puntos de entrada: nadie los llama desde el codigo, los invoca el runtime
# (Arduino, el interprete, el hardware).
ENTRADAS = re.compile(
    r"^(setup|loop|main|__main__|app_main"
    r"|isr.*|.*_isr|.*_vect|.*_handler|.*Handler)\(?\)?$", re.I)

MINIMO_NODOS = 4

CABECERA = [
    "digraph g {",
    "  rankdir=LR;",
    '  bgcolor="white";',
    "  splines=spline;",
    "  nodesep=0.24;  ranksep=0.60;",
    '  node [shape=box, style="rounded", fontname="Georgia", fontsize=10,',
    '        color="gray25", fontcolor="black", margin="0.11,0.06"];',
    '  edge [color="gray45", arrowsize=0.6, penwidth=0.8,',
    '        fontname="Georgia", fontsize=8, fontcolor="gray40"];',
    '  graph [fontname="Georgia", fontsize=9];',
]


def sin_tildes(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[\s_-]+", "_", re.sub(r"[^\w\s.-]", "", s).strip().lower())


def escapar(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def render(dot, nombre, formato):
    SALIDA.mkdir(parents=True, exist_ok=True)
    base = SALIDA / nombre
    base.with_suffix(".dot").write_text(dot, encoding="utf-8")
    r = subprocess.run(["dot", "-T" + formato, "-o",
                        str(base.with_suffix("." + formato)),
                        str(base.with_suffix(".dot"))],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  ERROR en %s: %s" % (nombre, r.stderr.strip()[:170]))
        return False
    return True


class Grafo:
    def __init__(self, datos):
        self.n = {x["id"]: x for x in datos["nodes"]}
        self.e = datos["links"]
        self.lbl = {i: str(x.get("label", i)) for i, x in self.n.items()}
        self.arch = {i: (x.get("source_file") or "?").replace("\\", "/")
                     for i, x in self.n.items()}
        self.linea = {i: x.get("source_location") for i, x in self.n.items()}

        # metodo -> clase que lo contiene. Es lo que permite agregar.
        self.duenio = {}
        for x in self.e:
            if x.get("relation") == "method":
                self.duenio[x["target"]] = x["source"]

        self.llamadas = [x for x in self.e if x.get("relation") in LLAMADAS]
        self.imports = [x for x in self.e if x.get("relation") in IMPORTS]

    def es_archivo(self, i):
        """El nodo que representa al archivo entero, no a un simbolo suyo."""
        return self.lbl.get(i, "").endswith((".py", ".ino", ".h", ".c", ".cpp"))

    def es_codigo(self, i):
        """Descarta los nodos `rationale`.

        graphify crea un nodo por cada docstring y por cada comentario de
        peso. Son utiles para buscar en el grafo, pero no son codigo: en
        vivo_rapido.py son 40 de 47 nodos y dibujados como cajas tapaban por
        completo las 7 que importan.
        """
        x = self.n.get(i, {})
        return x.get("file_type") == "code"

    def raiz(self, i):
        """Sube de un metodo a su clase. Los demas nodos son su propia raiz."""
        return self.duenio.get(i, i)


# --------------------------------------------------------------------------
# Vista proyecto: un archivo por caja, las flechas son imports
# --------------------------------------------------------------------------

def vista_proyecto(g):
    aristas = set()
    archivos = set()
    for x in g.imports:
        o, d = x["source"], x["target"]
        # Solo import de modulo a modulo. El import de un simbolo suelto se
        # atribuye al archivo donde vive ese simbolo.
        oa = g.arch.get(o, "?")
        da = g.arch.get(d, "?") if not g.es_archivo(d) else g.lbl[d]
        if not oa or oa == "?" or not da or da == "?":
            continue
        oa, da = oa.split("/")[-1], da.split("/")[-1]
        if oa != da:
            aristas.add((oa, da))
            archivos.update((oa, da))

    # Un archivo con main() o setup()/loop() es por donde se entra al sistema.
    entradas = set()
    for i, et in g.lbl.items():
        if ENTRADAS.match(et) and g.arch.get(i, "?") != "?":
            entradas.add(g.arch[i].split("/")[-1])
    archivos.update(a for a in entradas if a)

    L = list(CABECERA)
    L[1] = "  rankdir=TB;"                     # de arriba hacia abajo se lee mejor
    for a in sorted(archivos):
        doble = ", peripheries=2" if a in entradas else ""
        L.append('  "%s" [label="%s"%s];' % (escapar(a), escapar(a), doble))
    for o, d in sorted(aristas):
        L.append('  "%s" -> "%s";' % (escapar(o), escapar(d)))
    L.append("}")
    return "\n".join(L) + "\n", len(archivos), len(aristas)


# --------------------------------------------------------------------------
# Vista modulos: clases y funciones de nivel superior de UN archivo
# --------------------------------------------------------------------------

def vista_modulos(g, arch):
    """Colapsa cada metodo en su clase y agrega las llamadas entre cajas."""
    propios = {i for i, a in g.arch.items() if a == arch}
    # Caja = raiz del simbolo, salvo el nodo del archivo mismo.
    cajas = {g.raiz(i) for i in propios}
    cajas = {c for c in cajas if c in g.n and not g.es_archivo(c)
             and g.es_codigo(c)}

    peso = defaultdict(int)
    for x in g.llamadas:
        o, d = g.raiz(x["source"]), g.raiz(x["target"])
        if o in cajas and d in cajas and o != d:
            peso[(o, d)] += 1

    # Cuantos metodos agrupa cada caja: va en la etiqueta, asi no se pierde.
    hijos = defaultdict(int)
    for i in propios:
        if not g.es_codigo(i):
            continue
        r = g.raiz(i)
        if r != i and r in cajas:
            hijos[r] += 1

    L = list(CABECERA)
    corto = arch.split("/")[-1]
    for c in sorted(cajas, key=lambda x: g.lbl.get(x, "")):
        et = g.lbl.get(c, c)
        ln = g.linea.get(c)
        sub = "%s:%s" % (corto, ln) if ln else corto
        if hijos.get(c):
            sub += "  (%d metodos)" % hijos[c]
        doble = ", peripheries=2" if ENTRADAS.match(et) else ""
        L.append('  "%s" [label="%s\\n%s"%s];'
                 % (escapar(c), escapar(et), escapar(sub), doble))
    for (o, d), w in sorted(peso.items(), key=lambda kv: -kv[1]):
        etq = ' [label="%d"]' % w if w > 1 else ""
        L.append('  "%s" -> "%s"%s;' % (escapar(o), escapar(d), etq))
    L.append("}")
    return "\n".join(L) + "\n", len(cajas), len(peso)


# --------------------------------------------------------------------------
# Vista completo: todas las funciones de UN archivo
# --------------------------------------------------------------------------

def vista_completo(g, arch):
    activos = set()
    for x in g.llamadas:
        activos.add(x["source"])
        activos.add(x["target"])
    nodos = [i for i, a in g.arch.items()
             if a == arch and g.es_codigo(i)
             and (i in activos or ENTRADAS.match(g.lbl.get(i, "")))]
    ids = set(nodos)
    corto = arch.split("/")[-1]

    L = list(CABECERA)
    for i in sorted(nodos, key=lambda x: g.lbl.get(x, "")):
        et = g.lbl.get(i, i)
        ln = g.linea.get(i)
        sub = "%s:%s" % (corto, ln) if ln else corto
        attrs = []
        if ENTRADAS.match(et):
            attrs.append("peripheries=2")
        if et.startswith("."):
            attrs += ['color="gray60"', 'fontcolor="gray35"']
        extra = (", " + ", ".join(attrs)) if attrs else ""
        L.append('  "%s" [label="%s\\n%s"%s];'
                 % (escapar(i), escapar(et), escapar(sub), extra))

    vistas = set()
    for x in g.llamadas:
        o, d = x["source"], x["target"]
        if o in ids and d in ids and (o, d) not in vistas:
            vistas.add((o, d))
            pun = "[style=dashed]" if x.get("relation") == "indirect_call" else ""
            L.append('  "%s" -> "%s"%s;' % (escapar(o), escapar(d), pun))
    L.append("}")
    return "\n".join(L) + "\n", len(nodos), len(vistas)


# --------------------------------------------------------------------------

def archivos_con_codigo(g):
    """Archivos que tienen al menos una llamada o un punto de entrada."""
    activos = set()
    for x in g.llamadas:
        activos.add(x["source"])
        activos.add(x["target"])
    por = defaultdict(int)
    for i, a in g.arch.items():
        if (a != "?" and g.es_codigo(i)
                and (i in activos or ENTRADAS.match(g.lbl.get(i, "")))):
            por[a] += 1
    return por


def main():
    p = argparse.ArgumentParser(
        description="Diagramas del codigo de GPRv2, desde el fuente.")
    p.add_argument("--vista", action="append",
                   choices=["proyecto", "modulos", "completo"],
                   help="que vista generar (repetible; default proyecto+modulos)")
    p.add_argument("--listar", action="store_true", help="lista los archivos y sale")
    p.add_argument("--archivo", action="append",
                   help="filtra por parte del nombre (repetible)")
    p.add_argument("--todos", action="store_true",
                   help="incluye los archivos con pocas llamadas")
    p.add_argument("--formato", default="pdf", help="pdf (default), png, svg")
    args = p.parse_args()

    if not GRAFO.exists():
        sys.exit("Falta %s\nCorrer primero, desde GPRv2/:\n"
                 "    graphify extract . --code-only" % GRAFO)
    if not shutil.which("dot"):
        sys.exit("Falta Graphviz (el comando 'dot') en el PATH.\n"
                 "Instalar de https://graphviz.org/download/")

    g = Grafo(json.loads(GRAFO.read_text(encoding="utf-8")))
    por_arch = archivos_con_codigo(g)

    if args.listar:
        print("%d archivos:\n" % len(por_arch))
        for a, n in sorted(por_arch.items(), key=lambda kv: -kv[1]):
            marca = " " if n >= MINIMO_NODOS else "*"
            print("  %s%3d simbolos   %s" % (marca, n, a))
        print("\n  * por debajo del minimo: solo con --todos")
        return

    vistas = args.vista or ["proyecto", "modulos"]
    elegidos = sorted(por_arch)
    if args.archivo:
        elegidos = [a for a in elegidos
                    if any(f.lower() in a.lower() for f in args.archivo)]
    if not args.todos:
        elegidos = [a for a in elegidos if por_arch[a] >= MINIMO_NODOS]

    hechos = 0

    if "proyecto" in vistas:
        dot, nn, na = vista_proyecto(g)
        if render(dot, "mapa_proyecto", args.formato):
            print("Generado: figuras/codigo/mapa_proyecto.%s   "
                  "(%d archivos, %d dependencias)" % (args.formato, nn, na))
            hechos += 1

    for arch in elegidos:
        nombre = sin_tildes(arch.split("/")[-1].rsplit(".", 1)[0])
        if "modulos" in vistas:
            dot, nn, na = vista_modulos(g, arch)
            if nn and render(dot, "modulos_" + nombre, args.formato):
                print("Generado: figuras/codigo/modulos_%s.%s   "
                      "(%d cajas, %d relaciones)  <- %s"
                      % (nombre, args.formato, nn, na, arch))
                hechos += 1
        if "completo" in vistas:
            dot, nn, na = vista_completo(g, arch)
            if nn and render(dot, "llamadas_" + nombre, args.formato):
                print("Generado: figuras/codigo/llamadas_%s.%s   "
                      "(%d funciones, %d llamadas)  <- %s"
                      % (nombre, args.formato, nn, na, arch))
                hechos += 1

    print("\n%d figuras en %s" % (hechos, SALIDA))


if __name__ == "__main__":
    main()
