# PCM1808 + ESP32-C3 SuperMini — banco de prueba

Firmware para verificar que el PCM1808 digitaliza bien, inyectando una senoidal
con un generador de funciones. La frecuencia de muestreo es una variable que se
cambia en caliente por consola.

- Sketch: [`PCM1808_ESP32C3/PCM1808_ESP32C3.ino`](PCM1808_ESP32C3/PCM1808_ESP32C3.ino)
- Estudio de hardware completo (y por qué esto después hay que adaptarlo para el
  GPR): [`ESTUDIO_HARDWARE.md`](ESTUDIO_HARDWARE.md)

---

## 1. Cableado

| ESP32-C3 SuperMini | | Módulo PCM1808 | Qué es |
|---|---|---|---|
| `GPIO4` | → | `SCK` | **SCKI / master clock** = 256·fs |
| `GPIO5` | → | `BCK` | bit clock = 64·fs |
| `GPIO6` | → | `LRC` | LRCK / word select = fs |
| `GPIO7` | ← | `OUT` | DOUT, datos serie |
| `5V` | → | `5V` | VCC analógico |
| `3V3` | → | `3.3` | VDD digital |
| `GND` | ↔ | `GND` | los dos pines |
| `GND` | → | `FMY` | FMT = LOW → formato I²S |
| `GND` | → | `MDI` | MD1 = LOW ┐ |
| `GND` | → | `MDO` | MD0 = LOW ┘ modo esclavo |

### Las tres cosas que hay que mirar antes de conectar

1. **`SCK` en este módulo es el MASTER CLOCK, no el bit clock.** El bit clock es
   `BCK`. En casi todos los micrófonos I²S de hobby `SCK` significa bit clock —
   acá no. Cruzarlos es el error número uno con este chip y el síntoma es "todo
   cero". El firmware lo detecta y te lo dice.
2. **`VCC` va a 5 V, no a 3.3 V.** El fondo de escala es `0.6 · VCC` = **3.0 Vpp**.
   Con 3.3 V el chip queda fuera del rango de operación recomendado (4.5 V mínimo).
3. **Fijate si tu módulo tiene un oscilador soldado** (paquete metálico de 4 patas
   o cristal cilíndrico). Muchos clones vienen cableados en modo maestro con un
   cristal de 12.288 MHz. Si es tu caso no podés inyectar SCKI desde el ESP32 —
   chocarían dos salidas — y hay que desoldarlo.

`FMT`, `MD0` y `MD1` tienen pulldown interno de 50 kΩ, así que al aire ya quedan
en LOW. Igual atalos a GND con cable: con RF cerca no querés entradas flotando.

**MD1/MD0 se leen una sola vez, al encender.** No se pueden cambiar en caliente.

### Alimentación (recomendado, no imprescindible para la primera prueba)

```
USB 5V ──┬── 10 Ω ──┬─────────── VCC (5V) del PCM1808
         │          │
         │         ═╪═ 100 µF   ═╪═ 100 nF   ← lo más cerca del chip posible
         │          │            │
         └──────────┴────────────┴── GND
```

El pin `5V` del SuperMini es VBUS del USB directo, y es ruidoso. El ruido en VCC
entra por VREF (= 0.5·VCC) derecho a la señal. Para la primera prueba andá sin
filtro; si después ves basura en el espectro, esto es lo primero.

---

## 2. Configuración del Arduino IDE

**La opción más simple:** elegí la placa **“Nologo ESP32C3 Super Mini”**. Esa
definición trae `usb_mode=1` y `cdc_on_boot=1` fijos y el menú *CDC On Boot* solo
ofrece *Enabled*, así que no hay forma de equivocarse.

Si preferís el genérico:

| Opción | Valor |
|---|---|
| Placa | **ESP32C3 Dev Module** |
| **USB CDC On Boot** | **Enabled** ← el default es *Disabled* |
| Core Arduino-ESP32 | **3.x o superior** |

### Por qué importa

En el core 3.x, `Serial` es un macro que apunta a hardware distinto según esa
opción (`HardwareSerial.h:439`):

| USB CDC On Boot | `Serial` es | Dónde sale |
|---|---|---|
| **Enabled** | `HWCDCSerial` | USB nativo, el mismo cable que usás para programar |
| **Disabled** | `Serial0` | **UART0, pines GPIO20/21** |

El `ESP32C3 Dev Module` viene con `cdc_on_boot=0` de fábrica (`boards.txt:1445`).
O sea que por defecto el sketch imprime por unos pines a los que no tenés nada
conectado y **en el Monitor Serie no aparece nada, aunque el programa corra
perfecto**. La subida funciona igual porque el flasheo lo hace el ROM por el
USB-Serial-JTAG, que es otro camino.

**El firmware ya está blindado contra esto:** si detecta que lo compilaste con
CDC deshabilitado, levanta el CDC nativo a mano y escribe por los dos puertos a
la vez, además de avisarte en el banner. Aun así conviene poner bien la opción.

El sketch usa la API `i2s_std` de ESP-IDF 5.x. Si tenés el core 2.x no compila y
te tira un `#error` explicando por qué. Se actualiza desde
*Herramientas → Placa → Gestor de tarjetas → esp32*.

---

## 3. Conexión del generador de funciones

```
Generador ──────────► entrada VINL del módulo (canal izquierdo)
   GND    ──────────► GND
```

Ajustes de arranque sugeridos:

| Parámetro | Valor |
|---|---|
| Forma | senoidal |
| Frecuencia | **100 Hz** |
| Amplitud | **1 Vpp** |
| Offset DC | **0 V** |

⚠ **Nunca pases de 3.0 Vpp.** El delta-sigma no clipea suave como un SAR: se
vuelve inestable y escupe basura. El LED azul se queda fijo cuando detecta
saturación.

⚠ **Ojo con la impedancia.** La entrada del PCM1808 son 60 kΩ. Si tu generador
está calibrado para carga de 50 Ω, te va a entregar **el doble** de lo que marca
la pantalla. Poné `High-Z` en el generador si lo tiene; si no, contá con el
factor 2.

⚠ **El offset DC no se mide.** El PCM1808 tiene un pasa-altos digital interno
(1.9·10⁻⁵ · fs → 0.91 Hz a 48 kHz) más el capacitor de acople del módulo. Es
estructural, no hay manera de puentearlo. **Por debajo de ~5 Hz la medición no es
confiable.** Para el GPR esto importa muchísimo — está analizado en
[`ESTUDIO_HARDWARE.md`](ESTUDIO_HARDWARE.md).

---

## 4. Primer arranque

Al bootear, el firmware imprime el estado, corre un **diagnóstico de conexión**
y queda en modo `stats`. Si el cableado está bien vas a ver algo así:

```
--- ventana 2.048 s  |  fs=48000 Hz  D=48  fs_eff=1000.0 Hz  |  captura 100.0%
      DC(mV)    Vpp(mV)   Vrms(mV)   dBFS     f(Hz)   ciclos
  L      0.002    999.412    353.489    -9.5   100.001   204
  R      0.001      0.021      0.004  -103.2     0.000   0
```

Qué mirar:

| Campo | Qué te dice |
|---|---|
| `f(Hz)` | Frecuencia medida. Con una senoidal limpia da mejor que 0.1 %. **Si coincide con el generador, el ADC funciona.** |
| `Vpp` | Amplitud. Comparala contra el generador (acordate del factor 2 por impedancia). |
| `DC` | Debe dar prácticamente cero siempre — el HPF lo mata. |
| `dBFS` | Cuánto margen te queda. Apuntá a −6 a −1 dBFS para exprimir el ADC. |
| `captura` | Debe decir 100 %. Si baja, la salida serie no da abasto: subí `dec`. |
| `CLIP!` | Estás saturando. Bajá la amplitud del generador. |

**Piso de ruido**: cortocircuitá la entrada a GND y mirá `Vrms`. Con VCC limpio
deberías estar en el orden de las decenas de µV.

---

## 5. Ver la onda en el Serial Plotter

**El Serial Plotter no tiene nada que configurar** — no tiene opciones de parseo.
Todo se resuelve desde el firmware.

En el **Monitor Serie** (no en el plotter, que no tiene dónde escribir), tipeá:

```
sig 100
```
```
plot
```

(`sig` = la frecuencia que le pusiste al generador). Recién ahí abrí
*Herramientas → Serial Plotter*.

> **El orden importa.** El modo al arrancar es `stats`, que imprime una tabla de
> texto con las mediciones. Si abrís el plotter estando en `stats`, el plotter
> agarra los números de esa tabla y te dibuja series llamadas `value 1`,
> `value 2`… — que es exactamente lo que no querés. **La configuración se guarda
> en la flash**, así que la ponés una vez y sobrevive al reset que provoca abrir
> el plotter.

### Por qué hace falta `sig`, y por qué `plot` es un osciloscopio

Hay un conflicto de fondo entre lo que necesita la señal y lo que aguanta el
plotter:

- Para dibujar una senoidal de 1 kHz hacen falta **miles de puntos por segundo**.
- El Serial Plotter del IDE 2.x no pasa de **unos cientos** antes de saturarse y
  mostrar un fragmento minúsculo desplazándose a toda velocidad.
- Y no podés bajar la frecuencia del generador para compensar, porque abajo de
  ~5 Hz **te la come el pasa-altos del PCM1808**.

La salida es desacoplar la captura del dibujo. El modo `plot` funciona como un
osciloscopio: **captura un bloque contiguo de muestras a la `fs` real, y después
lo reproduce despacio.** La forma de onda queda intacta — el plotter no sabe que
le están pasando una grabación. Barrido rápido, tiempo muerto, barrido rápido,
igual que un osciloscopio de verdad.

### La base de tiempo no interpreta la señal

`win` y `sig` son **el equivalente a la perilla de TIME/DIV de un osciloscopio**:
lo único que eligen es cuánto tiempo de señal entra en la pantalla. No asumen
nada sobre lo que estás midiendo, no sintetizan nada y no interpolan nada. **Cada
punto dibujado es una muestra real del ADC.** Si le metés una cuadrada vas a ver
una cuadrada; si le metés ruido, ruido.

- `win <ms>` — pedís la ventana en milisegundos. Es la forma directa.
- `sig <hz>` — lo mismo, pero se lo pedís en frecuencia: encuadra ~8 ciclos de
  una señal de esa frecuencia. Es un atajo de `win`, nada más.

Con `dec` mayor que 1, cada punto es el **promedio** de D muestras consecutivas
(que es la forma correcta de diezmar, y de paso te da SNR). Si querés muestras
crudas, una a una, poné `dec 1`.

`sig <hz>` ajusta el diezmado para que en un barrido entren **~8 ciclos** de una
señal de esa frecuencia:

| Generador | Comando | D | fs_eff | Puntos/ciclo |
|---|---|---|---|---|
| 50 Hz | `sig 50` | 19 | 2526 Hz | 51 |
| 100 Hz | `sig 100` | 10 | 4800 Hz | 48 |
| 1 kHz | `sig 1000` | 1 | 48000 Hz | 48 |

En los tres casos ves lo mismo en pantalla: 8 ciclos limpios, dibujados en 2 s.

### Ajustes finos

| Comando | Qué hace | Default |
|---|---|---|
| `n <puntos>` | Puntos por barrido. Más = ventana más larga. | 400 |
| `rate <pts/s>` | Cadencia hacia el plotter. Bajalo si tu IDE se atraganta. | 200 |
| `unit v\|mv` | Unidad. En mV el autoescalado del plotter anda mucho mejor. | mV |
| `fmt label` | `L:valor` — leyenda en el Serial Plotter del IDE 2.x | ✔ |
| `fmt plain` | Solo el número — IDE 1.8, Serial Studio, scripts propios | |

En modo gráfico el firmware **silencia todos los mensajes de texto** (los `[OK]`,
los avisos, la cabecera al reconectar). Una sola línea de texto suelta le
desordena las series al plotter, así que mientras graficás no sale nada que no
sea un dato.

### `stream`: tiempo real, sin pausas

```
stream
```

Emite una línea por muestra en tiempo real, sin capturar ni pausar. **Solo sirve
si `fs_eff` < ~200 Hz** o si vas a leer el puerto con otro programa (Python,
Serial Studio) en vez del plotter del IDE. Es lo que antes hacía `plot`.

---

## 6. Comandos

| Comando | Qué hace |
|---|---|
| `fs <hz>` | Frecuencia de muestreo del ADC, **8000 a 96000**. Reconfigura el I²S en caliente. |
| `dec <n>` | Factor de diezmado, 1 a 4096. |
| `eff <hz>` | Elige `dec` solo para acercarse a esa `fs_eff`. |
| **`sig <hz>`** | **Ajuste automático: encuadra ~8 ciclos de una señal de esa frecuencia. Empezá por acá.** |
| `ch l\|r\|both` | Canal a mostrar. |
| `plot` | Modo osciloscopio, para el Serial Plotter. |
| `stream` | Tiempo real, una línea por muestra. |
| `stats` | Medición periódica (el modo por defecto al arrancar). |
| `raw` | CSV `t,L,R` para volcar y procesar en Python. |
| `off` | Detiene la salida. |
| `n <puntos>` | Puntos por barrido del osciloscopio (16–2048). |
| `rate <pts/s>` | Cadencia hacia el plotter (10–2000). |
| `unit v\|mv` | Unidad de los valores. |
| `fmt label\|plain` | Con etiqueta `L:` o solo el número. |
| `diag` | Repite el diagnóstico de conexión. |
| `info` | Estado actual y parámetros derivados. |
| `help` | Lista de comandos. |

### fs y diezmado

Son dos cosas distintas y las dos importan:

- **`fs`** es el reloj real del ADC (8–96 kHz). Determina el ancho de banda
  analógico y el ruido de cuantización.
- **`dec`** promedia `D` muestras consecutivas. Baja el caudal por USB `D` veces
  y **te regala `10·log10(D)` dB de SNR**: con `D = 48` son **+17 dB**, casi
  3 bits efectivos.

`fs_eff = fs / D` es lo que sale por el USB. La banda útil de la salida es
`fs_eff / 2`.

> **Elegí `fs` entre 16000, 32000 y 48000.** El ESP32-C3 no tiene APLL: el I²S
> cuelga del PLL de 160 MHz con un divisor fraccionario, y esas tres salen
> exactas. 44100 tiene ~0.005 % de error y 96000 ~0.04 %. Para un FMCW eso es un
> error de distancia de 2.5 mm en 5 m, o sea irrelevante — pero conviene saberlo.

---

## 7. Si algo no anda

### “Sube bien pero no veo nada en el Monitor Serie”

Mirá el **LED azul**. Es el diagnóstico que decide todo:

- **Parpadea** (6 destellos rápidos al arrancar, después ~1 Hz) → el sketch está
  corriendo. El problema es del **puerto serie**, no del firmware. Seguí abajo.
- **No parpadea** → el sketch no arranca. Saltá a la tabla de la sección
  siguiente (lo más probable: DOUT en un strapping pin, o la placa quedó en modo
  descarga y necesita un reset).

Si parpadea, en orden:

1. **Recompilá y volvé a subir** con la versión actual del sketch. La consola
   dual salió después de la primera entrega; si subiste la original y tenías
   *CDC On Boot: Disabled*, la salida se iba por GPIO20/21.
2. **Reseleccioná el puerto** en *Herramientas → Puerto*. Después de cada subida
   el C3 re-enumera y el IDE se queda con el puerto viejo.
3. **Cerrá y reabrí el Monitor Serie.** El firmware detecta cuando abrís el
   puerto y vuelve a imprimir la cabecera solo, así que no hace falta resetear.
4. **Apretá el botón de reset** de la placa con el monitor ya abierto.
5. Poné la placa en **“Nologo ESP32C3 Super Mini”** (sección 2) y volvé a subir.

### Tabla general

| Síntoma | Causa más probable |
|---|---|
| **Todo cero en los dos canales** | SCKI no llega. Revisá `GPIO4 → SCK`. Sin SCKI el PCM1808 se queda en reset. Segunda causa: cruzaste `SCK` con `BCK`. |
| **Todo cero y el módulo tiene oscilador** | Está en modo maestro y choca con el ESP32. Verificá MD1/MD0 a GND; puede que haya que desoldar el oscilador. |
| **Hay datos pero sin señal** | Entrada al aire o generador apagado. El diagnóstico lo distingue de "todo cero". |
| **Los 8 bits bajos no son cero** | Desalineación de trama. Revisá FMT a GND (formato I²S) y MD1/MD0 a GND. |
| **`captura` < 100 %** | La salida serie no da abasto. Subí `dec` o pasá a `stats`. |
| **Silencios digitales periódicos** | Pérdida de sincronismo LRCK↔SCKI. No debería pasar (los tres relojes salen del mismo divisor), pero si pasa es esto. |
| **Piso de ruido alto / basura en el espectro** | Ruido del USB en VCC. Poné el filtro RC, o alimentá con batería + LDO. |
| **Ruido a frecuencias altas** | Crosstalk de BCK (MHz) sobre la entrada analógica. Cables cortos, GND de guarda. |
| **No compila, error de `i2s_std.h`** | Tenés el core 2.x. Actualizá a 3.x. |
| **No se ve nada en el monitor serie** | Falta *USB CDC On Boot: Enabled*. Ver arriba. |
| **No bootea con el módulo conectado** | DOUT en un strapping pin. Tiene que ir a GPIO7, no a GPIO2/8/9. |
| **El LED no parpadea nunca** | El sketch no corre: reset, o modo descarga, o boot fallido por strapping. |
| **El plotter va rapidísimo / se ve un fragmento** | Estás en `stream` con `fs_eff` alta. Usá `plot`, que es el modo osciloscopio. |
| **El plotter no dibuja nada o se resetea la leyenda** | Se le está colando texto entre los datos. Comprobá que estés en `plot` o `stream` (ahí el firmware silencia los mensajes) y no en `raw`. |
| **La senoidal se ve como un garabato** | Muy pocos puntos por ciclo. Corré `sig <frecuencia_del_generador>`. |
| **`stats` reporta una frecuencia que no es la del generador** | Aliasing: la señal supera el Nyquist de `fs_eff`. Bajá `dec` o corré `sig`. |

---

## 8. Qué falta para el GPR

Este firmware es el banco de prueba. Para el radar hay que agregar:

- **Segundo canal para I/Q** — el código ya lee estéreo y `ch both` los muestra;
  falta la conversión a complejo y el procesamiento.
- **Sincronismo con el sweep** — sin esto no se puede promediar coherentemente ni
  hacer FFT por barrido. Hay tres arquitecturas posibles, están en la sección 6
  de [`ESTUDIO_HARDWARE.md`](ESTUDIO_HARDWARE.md).
- **Acelerar el sweep** — este es el punto crítico. Con `T_sweep = 1.46 s` las
  frecuencias de beat caen entre 0.7 y 7 Hz, o sea adentro del pasa-altos del
  PCM1808. La sección 0 del estudio tiene los números.
