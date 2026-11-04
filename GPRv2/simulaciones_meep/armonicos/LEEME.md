# Armónicos del VCO: simulación contra las capturas del 2026-09-28

Extiende la simulación MEEP de Santiago (`../`, corrida `mediciones_2026-09-28`, la de
la pared) para ver qué hacen los armónicos del VCO, la no linealidad del VCO, la
triangular y la cadena de IF en el espectro que muestra `vivo_rapido`. Hecho el
2026-11-02, con las decisiones de Martín de ese día (las 19 preguntas del chat).

**Los archivos de Santiago no se tocaron.** `parametros.py`, `escena.py`, `radar.py` y
`correr_meep.sh` de esta carpeta son copias, con lo que cambia anotado arriba de cada
una.

## Cómo se corre

Doble click en **`GPRv2/simular_armonicos.bat`**:

1. MEEP en WSL: placa a 0,70 / 0,80 / 0,90 / 1,00 / 1,20 m y la escena vacía, para la
   sonda adaptada y la sonda en corto. Cada escena guarda la traza en la sonda RX, y
   de ella sale H(f) a cualquier frecuencia.
2. `correr.py` en Windows: síntesis, procesado y figuras.

Con `MEEP=0` en el `.bat` se saltea el paso 1. Sirve si las escenas ya están y solo
cambió el modelo.

En la máquina de Martín, Miniforge y el env `meep` están en **`D:\WSL\miniforge3`**,
porque el C: está lleno. `correr_meep.sh` usa ese o, si no existe, `~/miniconda3`.

## Qué hay en cada archivo

| archivo | qué hace |
|---|---|
| `parametros.py` | copia del de Santiago, con banda 0,9–6,25 GHz y resolución 50. Al final, **todos los parámetros y supuestos del modelo**. |
| `escena.py` | copia; solo cambia el pulso (derivada de la gaussiana, sin continua, más ancho). |
| `radar.py` | copia; cables extrapolados arriba de 2,5 GHz y `H_en()`: H exacta a cualquier f con la DFT de la traza. |
| `sintesis.py` | el modelo: triangulares, VCO con armónicos, mezclador, cadena de IF, firmware y el procesado de `vivo_rapido`. |
| `correr.py` | la cascada, la sensibilidad, el escenario B, la variante con fuga y las figuras. |
| `triangular_lm324_ltspice_100ms.csv` | un período de la LM324 según LTspice; cómo se sacó, en su cabecera. |

## El modelo, en una línea por pieza

- **Escena**: la de Santiago (bocinas del croquis, placa de 70 cm, pared a 1,26 m con
  ε = 5), en 2D. MEEP da H(f) del aire entre las sondas.
- **Cables**: el S21 medido con el VNA; arriba de 2,5 GHz, un modelo de coaxil
  ajustado y enganchado al último punto. **Retardo interno**: 4 ns, igual para todos
  los armónicos.
- **VCO**: el "verdadero" sigue la curva del 2026-10-19; el software corrige con la
  vieja, como hoy. La envolvente de la fundamental y el 2º armónico (−6 a −12 dBc)
  salen del Max Hold. El 3º no está medido: −15 o −25 dBc.
- **Armónicos**: el del orden n lee la escena en n·f(t), así que cada camino deja un
  pico en n veces su frecuencia aparente: **el fantasma**.
- **Mezclador**: multiplicador (base; el fantasma va con a_n²) o conmutado
  (sensibilidad; depende de la fase ψ entre f y 2f en el LO, que no se midió).
- **Cadena plana** (supuesto): PA, splitter, LNA y mezclador tratan igual a 2f y 3f que
  a f. Para que el 2D no meta su pendiente, H del aire a n·f se reescala para que el eco
  de la placa a 1 m tenga el mismo nivel medio que a f.
- **Triangular**:
  - **A**, la del SDG830, ideal de 0 a 3 V con el Tprf de las capturas: es la que se
    compara con lo medido.
  - **B**, la LM324: la medida con el osciloscopio (tanda 2, ~100 ms, residuo
    suavizado) o la de LTspice. Lleva el corrimiento y el recorte que reproducen el
    Max Hold (hipótesis).
- **Cadena de IF**: el filtro post-mezclador G=1 ajustado a lo medido (pasaaltos de 1er
  orden y pasabajos de Butterworth), el acople y el pasaaltos del PCM1808, y el retardo
  de su filtro digital (17,4/fs, de la hoja de datos, a confirmar).
- **Firmware**: la cascada de semibandas del `.ino`, coeficiente por coeficiente. La
  triangular se lee una vez por bloque de DMA, con el índice corrido 13 muestras.
- **Procesado**: el de `vivo_rapido`, con sus mismas funciones:
  1. corta las rampas;
  2. invierte la bajada;
  3. resta la media de cada rampa;
  4. remuestrea en θ con la curva del software;
  5. ventana de Hann y relleno ×8;
  6. promedia en módulo las últimas 8 rampas;
  7. resta el fondo en módulo, con piso cero.

  Sincronismo perfecto, salvo el caso B4.

Dos cosas que se agregaron al revisar los resultados:

- **La traza de MEEP se ventanea desde los 70 ns.** A los 100 ns todavía tiene
  energía (−30 dB con la sonda adaptada), y cortarla de golpe metía un eco falso en
  ~2350 Hz (`TAPER_DESDE_NS`).
- **Blanco puntual.** Para medir lo que pone el radar sin lo que pone la escena se
  usa, además, un retardo puro a la distancia aparente de la placa a 1 m. La
  "placa sola" de MEEP (placa − vacío) no es un blanco único: trae la pared, que la
  placa tapa, con signo menos.

## Resultados (corrida del 2026-11-03)

Los números son de la **sonda adaptada**. La de corto exagera los rebotes dentro de la
bocina: en la banda de 650–1400 Hz da −14 dB ya en el caso ideal, contra −26 medido.
Queda como cota. Las figuras y los números están en **`figuras/<sonda>/`**
(`resumen.txt`); `salidas/<sonda>/` tiene solo los datos de MEEP.

**Lo que hay que tener presente al leerlos:** el MEEP es 2D, así que las posiciones
valen y los niveles son cualitativos. La cadena plana a 2f y 3f es un supuesto. El 3er
armónico no está medido.

### 1. Los armónicos explican la energía medida entre 0,8 y 2,4 kHz

Potencia media de las capturas cf, en dB respecto del máximo, promediada sobre las
cinco distancias (`fantasmas.png`, a la derecha):

| | 150–400 Hz | 650–1400 Hz | 1400–2300 Hz |
|---|---|---|---|
| **medido 28-09** | **−12,5** | **−25,8** | **−38,0** |
| 0. ideal | −36,7 | −31,7 | −71,5 |
| 3. + VCO real, corregido con la curva vieja | −18,5 | −27,7 | −69,6 |
| 4. + 2º armónico (Max Hold) | −18,5 | **−25,8** | −45,0 |
| 5. + 3º armónico a −15 dBc | −18,5 | −25,8 | **−39,5** |

- Sin armónicos, la simulación no tiene nada arriba de ~1,2 kHz.
- El 2º armónico, con el nivel medido en el Max Hold, deja la banda de 650–1400 Hz
  justo en lo medido.
- Para llegar a 1400–2300 Hz hace falta un 3º armónico del orden de −15 dBc, o
  ruido. **Eso no se puede separar sin medir el 3º.** El paso 6 (ruido) coincide por
  construcción, porque el ruido se calibró en esa banda.

En `medido_vs_simulado.png` se ve que la caída del "piso" de las capturas, de −25 dB en
1 kHz a −50 dB en 2,4 kHz, la reproduce la simulación con armónicos y no la ideal.

### 2. Cuánto vale el fantasma de un blanco

Medido con el blanco puntual, el 2f queda respecto del pico del blanco en:

| mezclador | fantasma 2f |
|---|---|
| multiplicador | **−23 dB** |
| conmutado, ψ = 0° o 45° | −22 a −25 dB |
| conmutado, ψ = 90°, sin 3º | −40 dB (el 2º del LO no conmuta) |

El 3f queda en −33 dB con el 3º a −15 dBc, y en −43 dB con el 3º a −25 dBc. En MEEP,
la placa sola da un 2f de −26 dB, entre −34 y −21 según la distancia.

El fantasma cae en **2·(d + 2,69 m) − 2,69 m**: la placa a 1 m lo pone en ~4,7 m
calibrados, ~1016 Hz.

### 3. Lo que más pesa cerca del blanco no son los armónicos: es la curva del VCO

- Las dos caracterizaciones del VCO difieren **hasta ±8 MHz entre 1,1 y 1,8 V**. Está
  en los datos crudos, no lo agrega la interpolación (ver `entradas.png`).
- Si el VCO sigue la del 19-10 y se corrige con la vieja, un blanco puntual deja un
  **lóbulo a −5,3 dB, ~75 Hz por debajo del pico** (~0,5 m). Con la curva correcta,
  −17,6 dB.
- Es la misma forma que la **loma de −3 a −5 dB en ~400–460 Hz** de todas las capturas.
  Es la explicación más simple de esa loma, aunque no la única (ver el punto 6).
- Consecuencia: el remuestreo necesita la curva con un error de **~1 MHz**, y la
  repetibilidad medida es de ±8 MHz.
- **Propuesta:** calibrar f(t) en el banco. Con el barrel y un cable (un solo
  retardo conocido), la fase del batido es 2π·f(t)·τ, así que da f(t) directamente.

### 4. Detalles chicos de la cadena

- **Retardo del filtro del PCM1808** (17,4/fs, de la hoja de datos, **a confirmar**).
  El firmware no lo compensa. Con el VCO no lineal, desalinear 0,36 ms sube los
  lóbulos de −21,7 a −17,6 dB. Se arregla sumando 2 muestras al retardo que compensa
  el firmware.
- **Rizado de ±2 dB de la fundamental** (Max Hold). Como modulación de amplitud sube
  los lóbulos de −31,5 (Hann puro) a −23 dB con el multiplicador, o a −28 dB con el
  conmutado. Parte de ese rizado puede ser del armado de la medición.
- **La cadena de IF y el diezmado no cambian nada visible** (paso 1).

### 5. El generador propio (LM324): predicción

Blanco puntual, `generador_propio.png`:

| caso | pico | ancho a −6 dB |
|---|---|---|
| SDG830 (A) | 509 Hz | 47 Hz |
| LM324, software de hoy (0–3 V) | 491 Hz | 74 Hz |
| LM324, software con los extremos del osciloscopio | **453 Hz** | 76 Hz |
| LM324, software que sabe del corrimiento | 486 Hz | 69 Hz |

- **El ensanchamiento lo pone el residuo de la rampa** (la curvatura y el escalón de
  ~0,95 V): solo, ya da 67 Hz.
- La asimetría medida (50,75/49,25 %) y el recorte en 1991 MHz, cada uno por su lado,
  no cambian el ancho.
- Con la forma de LTspice el pico se abre a 133 Hz. Lo más probable es que sea su
  asimetría (46,5/53,5 %, siete veces la medida), pero no se separó.
- **Si el escalón de 0,95 V es del osciloscopio y no del LM324**, este punto es
  pesimista. Medir a 0,5 V/div.
- **"Actualizar" el software con los extremos del osciloscopio empeora la escala**:
  el VCO no barre lo que dice la curva estática para esas tensiones (corrimiento y
  recorte del Max Hold). Hay que recalibrar Hz por metro con distancias conocidas.

### 6. Variante con fuga interna (ajustada, no medida)

Es un camino del TX al RX que no pasa por las bocinas, por la aislación finita del
splitter y del mezclador, o por los cables juntos. Se ajustó un retardo, un nivel y una
fase contra las capturas cf, y el mejor queda en:

- **3,1 m aparentes (~430 Hz)**;
- **+8 dB respecto del eco de la placa a 1 m**;
- error de 5,2 dB en 200–800 Hz, contra 9,0 dB sin fuga.

Su fantasma 2f caería en ~860 Hz. **Compite con la explicación del punto 3** por la
misma loma, y con estas capturas no se pueden separar. Hay dos pruebas que las
distinguen: el barrel, y las bocinas mirando a un absorbente.

### Lo que falta medir para sacar supuestos

1. El 2º y el 3º armónico hasta ~6 GHz, a la salida del VCO, del PA y en el LO del
   mezclador. Saca la "cadena plana" y el 3º supuesto.
2. Barrel con atenuador, sin antenas:
   - un solo retardo, así que los picos en 2f₁ y 3f₁ son fantasmas puros;
   - mide el retardo interno;
   - calibra f(t) (punto 3).
3. La triangular de la LM324 a 0,5 V/div (el escalón) y la salida del amplificador
   ×4,95 (el recorte).
4. Un blanco único y quieto, procesado con las dos curvas del VCO: la buena es la que
   da el pico más angosto. Los crudos de las 17:37–17:53 del 28-09 no sirven para esto,
   porque la escena cambia durante la corrida.
