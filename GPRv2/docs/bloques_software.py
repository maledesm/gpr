"""
Diagramas en bloques del software de GPRv2: que se hace con los datos, en que
orden y que corre en paralelo. No muestran funciones ni metodos.

    python bloques_software.py    ->  ../../redaccion/figuras/software/bloques_*.pdf
                                      (y un .png al lado, para mirarlos rapido)

A diferencia de diagrama_llamadas.py, esto NO sale del codigo automaticamente:
un analisis del fuente no sabe que el Lector corre en otro hilo, que el
grafico se refresca cada 200 ms ni que el DMA llena bloques sin usar la CPU.
Esta escrito a mano a partir de leer el codigo, asi que si se cambia la
estructura de vivo_rapido.py o de adquisicion.ino hay que actualizarlo aca.

Estilo: cajas blancas, borde negro, esquinas vivas, igual que
docs/diagrama_bloques.py, para que se imprima en blanco y negro. Los
recuadros punteados agrupan lo que corre junto (un hilo, la interrupcion, el
hardware); dos recuadros distintos corren EN PARALELO.
"""

import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SALIDA = Path(__file__).resolve().parents[2] / "redaccion" / "figuras" / "software"

ESTILO = """
  fontname="Helvetica"; fontsize=12;
  newrank=true; compound=true; nodesep=0.35; ranksep=0.42;
  node [shape=box, fontname="Helvetica", fontsize=11, color="black",
        penwidth=1.3, margin="0.16,0.07"];
  edge [fontname="Helvetica", fontsize=9.5, color="black", penwidth=1.0,
        arrowsize=0.75];
"""

GRUPO = 'style="dashed"; color="gray35"; penwidth=1.1; labeljust="l"; fontsize=11;'


# --------------------------------------------------------------------------
# Firmware: adquisicion.ino en el ESP32-C3
# --------------------------------------------------------------------------

FIRMWARE = """
digraph firmware {
  rankdir=TB;
""" + ESTILO + """
  // Entradas fisicas, arriba de la columna que las recibe
  beat_in [label="Señal de batido\n(salida del mezclador)", shape=plaintext];
  tri_in  [label="Triangular del generador\n(divisor 4k7 / 4k7 a GPIO3)", shape=plaintext];
  sync_in [label="Sync del generador\n(hoy no llega)", shape=plaintext, fontcolor="gray40"];

  subgraph cluster_hw {
    label="HARDWARE\ncorre solo, sin usar la CPU";
    """ + GRUPO + """
    pcm [label="PCM1808\nconvierte a digital\n24 bits, 48 000 muestras/s"];
    dma [label="DMA del I2S\nllena bloques de 256 muestras\n(uno cada 5,3 ms)"];
    pcm -> dma;
  }

  subgraph cluster_loop {
    label="LAZO PRINCIPAL\nuna vuelta por bloque, ~187 por segundo";
    """ + GRUPO + """
    cmd    [label="1. Atender comandos de la PC\n(run / stop / fs)"];
    tomar  [label="2. Esperar el bloque del DMA\ny anotar la hora"];
    leertri[label="3. Leer la triangular\n(una lectura del ADC)"];
    filtro [label="4. Filtro antialias + diezmado ×8\n48 000 → 6 000 muestras/s\n(entran 256, salen 32)"];
    fase   [label="5. A cada muestra: tiempo desde\nel último flanco de sync\n(-1 si nunca llegó)"];
    enviar [label="6. Mandar por USB\n32 líneas  \\"batido,sync\\"\n1 línea  \\"#v,triangular,índice\\""];
    cmd -> tomar -> leertri -> filtro -> fase -> enviar;
  }

  subgraph cluster_isr {
    label="INTERRUPCIÓN\nen cualquier momento";
    """ + GRUPO + """
    isr [label="Anotar la hora\ndel flanco", style="dashed"];
  }

  pc [label="PC  —  vivo_rapido.py\n6 000 líneas por segundo, ~78 kB/s", peripheries=2];

  beat_in -> pcm;
  tri_in  -> leertri;
  sync_in -> isr [style=dashed, color="gray40"];
  dma -> tomar [label=" bloque\n lleno"];
  isr -> fase  [style=dashed, color="gray40", fontcolor="gray40", label=" horas de\n los flancos"];
  enviar -> pc [label=" USB"];

  { rank=same; beat_in; tri_in; sync_in; }
  { rank=same; pcm; cmd; isr; }
}
"""


# --------------------------------------------------------------------------
# PC: vivo_rapido.py
# --------------------------------------------------------------------------

VIVO_RAPIDO = """
digraph vivo_rapido {
  rankdir=TB;
""" + ESTILO + """
  esp [label="ESP32-C3  —  adquisicion.ino\nbatido: 6 000 muestras/s   triangular: ~187 lecturas/s",
       peripheries=2];

  subgraph cluster_lector {
    label="HILO 1: LECTOR\ncorre todo el tiempo";
    """ + GRUPO + """
    leer    [label="Leer lo que va\nllegando al puerto"];
    separar [label="Separar las líneas\nbatido  |  triangular"];
    guardar [label="Escribir todo a disco,\ntal cual llega"];
    leer -> separar -> guardar;
    nota [shape=plaintext, fontsize=10, label="Los dos hilos corren a la vez:\nmientras el hilo 2 hace las FFT\ny dibuja, el hilo 1 sigue\nrecibiendo y grabando, así\nno se pierde ninguna muestra."];
    guardar -> nota [style=invis];
  }

  disco [label="captura_<fecha>.csv\ntriangular_<fecha>.csv", shape=cylinder];
  cola  [label="Cola\ncompartida", style="bold"];

  subgraph cluster_grafico {
    label="HILO 2: GRÁFICO\nse despierta cada 200 ms y procesa lo que se juntó";
    """ + GRUPO + """
    tomar  [label="1. Sacar todo lo nuevo de la cola"];
    ajuste [label="2. Ajustar la triangular (período y fase)\nal arrancar lo busca con 4 s de datos,\ndespués lo corrige cada 2 s"];
    cortar [label="3. Cortar el batido en rampas\nlas bajadas se dan vuelta y quedan como subidas"];
    remu   [label="4. Remuestrear en θ\ncorrige que el VCO no barre lineal"];
    fft    [label="5. Ventana de Hann + FFT\ncada rampa → un perfil de distancia"];
    buffer [label="6. Guardar el perfil\n(quedan los últimos 20 a 120 s)"];
    prom   [label="7. Promediar N rampas por fila"];
    fondo  [label="8. Restar el fondo (si hay) y pasar a dB\n→ radargrama"];
    pico   [label="9. ¿Hay blanco? (energía sobre el fondo)\nsi hay: pico → distancia calibrada"];
    dibu   [label="10. Actualizar la pantalla\n(solo lo que cambió)"];

    tomar -> ajuste [label=" triangular"];
    tomar -> cortar [label=" batido"];
    ajuste -> cortar [label=" dónde empieza\n cada rampa"];
    cortar -> remu -> fft -> buffer -> prom -> fondo -> pico -> dibu;
  }

  vco     [label="Curva del VCO\n(medida en el banco)", shape=note];
  usuario [label="Controles del usuario\nN, ventana, alcance,\nmedir fondo / MTI,\ncalibrar distancia", shape=note];

  esp -> leer [label=" USB"];
  guardar -> disco;
  separar -> cola;
  cola -> tomar;
  vco -> remu [style=dashed];
  usuario -> prom [style=dashed];
  usuario -> fondo [style=dashed];
  usuario -> pico [style=dashed];

  { rank=same; separar; cola; tomar; }
  { rank=same; remu; vco; }
  { rank=same; fondo; usuario; }
}
"""


DIAGRAMAS = {
    "bloques_firmware": FIRMWARE,
    "bloques_vivo_rapido": VIVO_RAPIDO,
}


def main():
    if not shutil.which("dot"):
        sys.exit("Falta Graphviz (el comando 'dot') en el PATH.")
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, fuente in DIAGRAMAS.items():
        dot = SALIDA / (nombre + ".dot")
        dot.write_text(fuente, encoding="utf-8")
        for fmt, extra in (("pdf", []), ("png", ["-Gdpi=130"])):
            r = subprocess.run(["dot", "-T" + fmt, *extra, "-o",
                                str(dot.with_suffix("." + fmt)), str(dot)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit("ERROR en %s: %s" % (nombre, r.stderr.strip()))
        print("Generado: figuras/software/%s.pdf" % nombre)


if __name__ == "__main__":
    main()
