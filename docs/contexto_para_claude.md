# Contexto del proyecto para Claude

Este archivo es un **prompt de arranque**. Está pensado para pegarlo entero en
un chat nuevo de Claude, de modo que arranque con el mismo contexto que el otro.

Somos dos personas trabajando en paralelo en la misma tesis, cada una con su
cuenta. Este documento es lo que mantiene los dos chats alineados: si algo
cambia de fondo en el proyecto, se actualiza acá y se vuelve a pegar.

> **Para el que lo pega**: podés mandar el archivo entero, o —si ya clonaste el
> repo— decirle a Claude *"leé `docs/contexto_para_claude.md` y seguí esas
> instrucciones"*. Es lo mismo.

---

## PEGAR DESDE ACÁ

Vas a ayudarme con mi tesis de grado en Ingeniería Electrónica de la FIUBA
(Facultad de Ingeniería, UBA). Antes de responder nada, leé todo este contexto.
Está escrito para que no necesites preguntarme cosas básicas del proyecto.

Trabajamos en español. Los comentarios de código, los mensajes de commit y la
documentación van en español.

---

### 1. Qué estamos construyendo

Un **GPR** (radar de penetración terrestre) de tipo **FMCW** (onda continua
modulada en frecuencia). La idea es barrer una rampa de frecuencia, mezclar el
eco con la señal transmitida, y quedarse con la **frecuencia de beat**, que es
proporcional a la distancia al blanco.

Las relaciones que gobiernan todo el diseño:

```
f_beat      = 2 · R · BW / (c · T_sweep)         [Hz]
resolución  = c / (2 · BW)                        [m]
R           = bin · N_sweep · c / (2 · BW · N)    [m]
```

En la última, `fs` **se cancela** si `T_sweep` se mide en cantidad de muestras
en vez de en segundos. Es un detalle que simplifica mucho el procesamiento: no
hace falta conocer la frecuencia de muestreo con precisión para calcular
distancias, alcanza con contar muestras por barrido.

En suelo, la resolución mejora por `√εr`: con εr ≈ 9 (típico de suelo húmedo),
divide por 3.

**La banda de diseño es 1,0 a 2,0 GHz**, o sea `BW = 1000 MHz` → resolución
**15 cm en aire, 5 cm en suelo**, y `f_beat = 6,67 / T_sweep` Hz por metro. (Si
ves 750 MHz o 1,75 GHz en algún lado, es de una prueba inicial y quedó viejo.)

Lo que entrega el VCO hoy con la tabla actual es **943–1982 MHz** (BW 1039 MHz,
14,4 cm): cubre prácticamente la banda de diseño y con algo más de ancho. Llegar
a 2,000 GHz exactos pide **3,091 V** y el tope de la tabla es 3,00 V, así que hoy
se queda en 1982 MHz. Es alcanzable (el DAC llega a VDD = 3,3 V) pero hay que
regenerar `tabla_vco.h` con otro `V_MAX_USO`.

---

### 2. Cómo trabajamos los dos

- **Un solo repo**, compartido: https://github.com/maledesm/gpr — público, rama
  `main`. Usuario del dueño: `maledesm`.
- Cada uno tiene su chat de Claude, su clon del repo y (en general) su propio
  hardware o turnos en el banco.
- **Antes de empezar a trabajar**: `git pull`. **Al terminar algo que anda**:
  commit + push. Si los dos tocan lo mismo a la vez se arma conflicto, así que
  conviene avisarse qué carpeta va a tocar cada uno.
- Los mensajes de commit son largos y explican **por qué**, no sólo qué. Si
  arreglaste un bug, el mensaje dice cuál era el síntoma y cuál la causa. Eso ya
  nos salvó varias veces de repetir errores.

**Restricción absoluta**: en la carpeta de la tesis existe además una carpeta de
**simulaciones electromagnéticas (`CST`, ~59 GB)**. **No se toca por ningún
motivo**: ni mover, ni renombrar, ni limpiar, ni indexar. Está fuera del repo a
propósito.

---

### 3. El hardware

#### Cadena de RF (el radar propiamente dicho)

```
ESP32-C3 ──I²C──> MCP4725 ──> amplificador ──> VCO ──> [TX]
                  (DAC 12b)                     │
                                                └──> mezclador ──> filtro
                                                          ↑           │
                                                        [RX]          v
                                        ESP32-C3 <──I²S── PCM1808 <───┘
```

El ESP32-C3 hace **las dos puntas**: genera la rampa de sintonía por I²C y
digitaliza el beat por I²S.

#### Componentes y los números que importan

**ESP32-C3 SuperMini** (el controlador)
- Un solo núcleo RISC-V a 160 MHz. **Sin FPU** (`rv32imc_zicsr_zifencei`): todo
  cálculo en punto flotante lo emula por software y es lentísimo. Por eso las
  tablas se precalculan **offline en Python** y el firmware sólo las indexa.
- **Sin DAC** y **sin APLL**. 1× I²S, 1× I²C. 400 KB de SRAM, sin PSRAM.
- Pines de strapping: GPIO2, GPIO8, GPIO9. **GPIO8 es el LED, activo en bajo.**
- Se evaluó pasar a un ESP32-S3 o a un ESP32 clásico de dos núcleos y se decidió
  **quedarse con el C3**. El S3 tampoco tiene DAC (se lo sacaron), y para lo que
  hacemos no justifica el cambio.

**PCM1808** (el ADC, en un módulo comercial)
- ΔΣ de **24 bits**, `fs` de **8 a 96 kHz**.
- Fondo de escala = `0.6 · VCC` = **3.0 Vpp con VCC = 5 V**. VREF = `0.5 · VCC`.
- Impedancia de entrada **60 kΩ**.
- **Filtro pasa-altos interno, no desactivable**: `f_c = 0.019 · fs / 1000` Hz
  (0.91 Hz a 48 kHz). **Este es el condicionante central del proyecto** — ver §7.
- Antialias analógico: −3 dB en 1.3 MHz. Filtro digital: banda de paso
  `0.454·fs`, banda de rechazo `0.583·fs`, −65 dB.
- Va en **modo esclavo** (MD1 = MD0 = LOW), que es la única forma de tener `fs`
  variable: el ESP32 le genera todos los relojes. FMT = LOW → formato I²S.
- Necesita **64 o 48 BCK por trama, nunca 32**.

**MCP4725** (el DAC de la rampa)
- 12 bits, I²C, salida de 0 a VDD, establecimiento en 6 µs.
- Direcciones posibles **0x60 a 0x67** (el módulo trae una fija; el firmware las
  escanea todas y te dice cuál encontró).
- **Sólo se usa el comando *Fast Mode Write* (2 bytes). Nunca el de EEPROM**: la
  EEPROM aguanta ~1 millón de ciclos y cada escritura tarda 25–50 ms. En una
  rampa se escribe cientos de veces por segundo, así que la quemaría en minutos.
- **Una escritura I²C medida tarda ≈125 µs** (≈75 µs de bus a 400 kHz + ≈50 µs
  de overhead del driver `Wire` por transacción). Este número fija el techo de
  velocidad de la rampa — ver §7.

**VCO** (caracterizado en el banco, datos en `VCO/Caracteristica VCO.csv`)
- 34 puntos medidos cada 100 mV, con precisión de espectro de 1 MHz.
- Con la entrada de **0 a 3.00 V** entrega **943 a 1982 MHz**, o sea
  **BW = 1039 MHz** → **resolución 14.4 cm** en aire. Para 2.000 GHz exactos
  harían falta 3.091 V (ver §1).
- **La curva no es lineal**: la sensibilidad `dF/dV` va de **167 a 468 MHz/V**,
  una variación de **2.8 a 1**. Eso, sin corregir, ensancha el pico de distancia
  en la misma proporción y arruina la resolución.
- Entre el DAC y el VCO hay un amplificador, medido: `Vosc = 4.949·Vin + 0.055`.

**Arduino Uno** (`firmware/generador_patron/`)
- Genera una cuadrada simétrica de 100 Hz como señal de referencia, para validar
  toda la cadena de adquisición sin necesidad del circuito de RF.
- Divisor 10k/4k7 a la salida → 1.52 Vpp, para no saturar el PCM1808.

**Osciloscopio Siglent SDS1072CML+**
- Al guardar pregunta **"Data Depth"** y **"Para Save"**. **"Para Save" tiene que
  estar en ON**: es lo que escribe la cabecera con `Sample Interval`; sin eso el
  CSV no tiene base de tiempo utilizable.
- **Hay que poner STOP antes de guardar.** Si está corriendo, o si el trigger no
  dice `Trig'd`, guarda archivos de 0 KB. Nos pasó y perdimos capturas.
- Formato del CSV: 10 filas de metadatos en las columnas 0–1, y los datos en las
  **columnas 3 (tiempo, s) y 4 (CH1, V) desde la fila 2**. Los dos bloques
  conviven uno al lado del otro en el mismo archivo. Hay coma al final de línea.

#### Cableado

**PCM1808 ← ESP32-C3** (detalle completo en `docs/conexionado.md` y
`docs/PCM1808_uso.md`):

| ESP32-C3 | | PCM1808 | Qué es |
|---|---|---|---|
| `GPIO4` | → | `SCK` | **master clock (SCKI)** = 256·fs |
| `GPIO5` | → | `BCK` | bit clock = 64·fs |
| `GPIO6` | → | `LRC` | word select = fs |
| `GPIO7` | ← | `OUT` | datos serie (DOUT) |
| `5V` | → | `5V` | VCC analógico (**5 V, no 3.3**) |
| `3V3` | → | `3.3` | VDD digital |
| `GND` | → | `FMY`, `MDI`, `MDO` | formato I²S + modo esclavo |

**MCP4725 ← ESP32-C3**: `GPIO0` = SDA, `GPIO1` = SCL, VCC = **3.3 V** (la salida
del DAC es de 0 a VDD, así que VDD define la escala completa).

**Tres trampas del PCM1808 que ya nos costaron tiempo:**
1. **`SCK` en este módulo es el MASTER CLOCK, no el bit clock.** En casi todos
   los micrófonos I²S de hobby `SCK` significa bit clock. Cruzarlo con `BCK` da
   "todo cero" y es el error número uno con este chip.
2. **`VCC` va a 5 V.** Con 3.3 V el chip queda fuera del rango recomendado.
3. **Fijate si tu módulo tiene un oscilador soldado.** Muchos clones vienen
   cableados en modo maestro con un cristal de 12.288 MHz; en ese caso no podés
   inyectar SCKI desde el ESP32 y hay que desoldarlo.

Y sobre la alimentación: el pin `5V` del SuperMini es VBUS del USB directo y es
ruidoso. El ruido entra por VREF (= 0.5·VCC) derecho a la señal. Hay un RC
recomendado (10 Ω + 100 µF + 100 nF) en `docs/PCM1808_uso.md`.

#### Camino alternativo de digitalización: placa de audio U-Phoria UMC22

Hay un **segundo camino, temporal**, para digitalizar el beat: una placa de
sonido USB Behringer U-Phoria UMC22 en lugar del PCM1808 + ESP32. La cadena de
RF no cambia; cambia sólo quién muestrea. Software en `adquisicion_audio/`, con
su propio README.

Sirve para medir sin depender del firmware ni del enlace binario, y para tener
un segundo canal ya disponible. **No reemplaza al PCM1808**: es un desvío para
destrabar el banco.

| | PCM1808 + ESP32 | UMC22 |
|---|---|---|
| Resolución | 24 bits | **16 bits** |
| `fs` | 8–96 kHz, variable en caliente | 44.1 / 48 kHz |
| Corte inferior | 0.91 Hz a 48 kHz | **10 Hz** (−3 dB) |
| Sincronismo con la rampa | atable a la cuenta de muestras | **no hay** |
| Canales | 1 (el segundo está pendiente) | 2 |

**El corte inferior es lo que importa: la UMC22 corta MÁS ARRIBA que el
PCM1808.** O sea que el pendiente número 1 (acelerar el sweep) no se relaja al
cambiar de ADC, se endurece. Con `T_sweep = 10 ms` el beat a 0.2 m son 133 Hz y
sobra margen; con el sweep original de 1.46 s no se ve nada.

Los 16 bits no son el límite real: el piso de ruido medido de la cadena da ~62 dB
de SNR (≈10 bits efectivos).

**Conexionado:** entrada 2, el jack de 1/4" **INSTRUMENT** (Hi-Z, 1 MΩ), con
plug **TS mono**: *tip* = señal, *sleeve* = GND. **No** en el combo XLR, que va
al preamp de micrófono y tiene el botón de **+48 V** al lado. Satura en −3 dBu
(≈1.55 Vpp) con la perilla GAIN al mínimo y el peor caso de la cadena es 3 Vpp,
así que hace falta un divisor de entrada (10 kΩ / 1.1 kΩ, división por 10.1).

**Dos trampas que ya nos costaron tiempo con esta placa:**
1. **WASAPI en modo exclusivo puede mentir la frecuencia de muestreo.** Contra
   la placa interna de una de las máquinas, `stream.samplerate` declaraba 48000
   y el stream entregaba **63.2 kS/s**; el mismo dispositivo en modo compartido
   daba 47.7 kS/s. No se ve en ningún lado —el WAV suena raro y nada más— pero
   corre el eje de frecuencias un 32 %, y como la distancia sale del beat,
   arruina todo en silencio. Por eso `grabaraudio.py` **mide** la tasa real
   antes de grabar y reintenta en compartido si se va más del 2 %.
2. **Sin calibrar no hay volts.** Entre el divisor y la perilla GAIN no hay forma
   de saber a qué tensión corresponde el fondo de escala, así que el CSV va en
   fracción de fondo de escala y el encabezado lo dice (`unidad = FS`). Se mide
   con `--calibrar` contra una amplitud conocida (la cuadrada de 1.52 Vpp del
   `generador_patron` sirve) y **vale mientras no se mueva la perilla GAIN**.

---

### 4. El repositorio

```
firmware/
  PCM1808_ESP32C3/      ★ EL FIRMWARE VIGENTE del radar. Es el que va en la placa.
  prueba_mcp4725/         Sketch AISLADO de la rampa del DAC. No toca I²S ni PCM1808.
    tabla_vco.h           GENERADO por VCO/analisis_vco.py — no editar a mano.
  generador_patron/       Arduino Uno: cuadrada de 100 Hz de referencia.
  historico/              Etapas viejas. NO cargar: ver su README.

adquisicion/            Captura y visualización en vivo (corre en WINDOWS)
  medir.py                Lanzador: arranca grabador + graficador.
  grabarserial.py         Graba el flujo binario a CSV con metadata completa.
  graficarserial.py       Espectro + osciloscopio + B-scan en tiempo real (pyqtgraph).
  protocolo.py            Decodificador de tramas.   Autoprueba: --test
  dsp.py                  Ventanas, FFT, filtros, distancia.  Autoprueba: --test

adquisicion_audio/      Captura por placa de audio UMC22 — TEMPORAL, ver §3
  medir_audio.py          Lanzador: grabador + el MISMO graficarserial.py.
  grabaraudio.py          Graba a CSV (formato IDENTICO al de grabarserial.py,
                          para no tocar el graficador) + WAV crudo de 2 canales.
                          Autoprueba: --test.  Utilidades: --listar, --calibrar
  audio.py                Dispositivos, API de audio, WAV.  Autoprueba: --test
  config.json             Generado, por máquina, en .gitignore.
                          ⚠ No toca adquisicion/, firmware/ ni analisis/. Para
                          volver al PCM1808 alcanza con correr medir.py.

analisis/               Procesamiento offline (WSL o Windows)
  v1/  Espectros y señales crudas por medición.
  v2/  Segmentación por sweeps + espectro promediado vs. distancia.

VCO/                    Caracterización y linealización del VCO
  Caracteristica VCO.csv  34 puntos medidos (Vin, Freq, Vosc). Decimales con COMA.
  analisis_vco.py         Genera firmware/prueba_mcp4725/tabla_vco.h + curva_vco.png
                          ⚠ HAY DOS COPIAS de tabla_vco.h (prueba_mcp4725 y
                          gpr_barrido) y el script escribe SOLO la primera. La
                          segunda es copia a mano: si regenerás la tabla, hay que
                          copiarla, o divergen en silencio. Pendiente: que el
                          script escriba las dos.
  grafico_vco.py          Figura F vs V con dF/dV
  grafico_capturas_dac.py Figura de las 4 capturas de osciloscopio
  Osciloscopio DAC/       SDS00001..4 (.CSV y .BMP)

Filtro Pasabajos/       Caracterización de un filtro activo (trabajo práctico aparte)
docs/                   conexionado, validación de banco, hardware y uso del PCM1808
  placa_audio_umc22.md    Puesta en marcha de la UMC22 en una máquina nueva:
                          instalación, formato de Windows, diagnóstico.
simulacion/             beat_simulado.py (WAV de prueba) y lpda_meep.py (antena en MEEP)
datos/                  Capturas. Los .csv están en .gitignore.
medir.bat / graficar.bat / pruebas.bat / medir_audio.bat   Accesos en la raíz
```

**Convenciones del repo:**
- Los `.bat` no llevan rutas fijas: se ubican con `%~dp0` y usan `cd /d`. El repo
  se puede mover o clonar en otra máquina y siguen andando. (Ojo: en `cmd.exe`
  un `cd` a otra unidad **no cambia de unidad** sin `/d`.)
- `.gitignore` excluye `*.png`, `*.pdf`, `*.svg`, `datos/*.csv`, los venv y las
  simulaciones pesadas. Las figuras que son **resultado final** se agregan a mano
  con `git add -f` y quedan listadas en un comentario del propio `.gitignore`.
- Los archivos generados llevan un encabezado que dice que son generados y qué
  script los produce (`tabla_vco.h` es el ejemplo).

**Dos entornos de Python, a propósito distintos:**

| Dónde | Ruta típica | Para qué |
|---|---|---|
| **Windows** | `%USERPROFILE%\venvs\gpr-win` | **Adquisición.** Obligatorio: el ESP32 es un puerto COM y **WSL 2 no lo ve** |
| WSL / Linux | `~/venv_gpr` | Análisis offline. No toca hardware |

En Windows: Python 3.11, `pyserial`, `numpy`, `scipy`, `matplotlib`, `pyqtgraph`,
`PyQt6`. En la máquina del dueño hay además un workaround de `pip.ini` apuntando
a un `ca-bundle.pem` porque el antivirus (Kaspersky) rompe la validación de
certificados de `pip`. Si `pip` te falla con error de SSL, es eso.

---

### 5. El firmware

#### `firmware/PCM1808_ESP32C3/` — el del radar

I²S en modo maestro, PCM1808 esclavo, slots de 32 bits estéreo, y `raw >> 8`
para recuperar el entero de 24 bits con signo.

Modos de salida: `off`, `plot`, `stream`, `stats`, `raw`, `bin`.
Comandos: `fs dec eff sig win ch n rate unit fmt raf bin plot stream stats raw
off diag fsmed info reset help`. Están documentados en `docs/PCM1808_uso.md`.

**Trama binaria** (la que consume el software de Python):
```
[0xA5 0x5A][idx:u32][n:u16][flags:u8][n × float32][crc16]
```
con `n = 256` muestras por trama.

#### `firmware/prueba_mcp4725/` — la rampa del DAC

Sketch **independiente**: no toca el I²S ni el PCM1808, para poder probar la
rampa sin arriesgar la cadena de adquisición.

Autodetecta la dirección del DAC entre 0x60 y 0x67 y mide cuánto tarda una
escritura promediando 200.

Valores por defecto: `g_rampa_us = 2500` (duración de **una** rampa, o sea media
onda), `g_pasos = 200`, `g_max = 3723` (= 3.00 V con VDD = 3.3 V),
`g_clk = 400000`, `g_predist = true`.

Comandos: `t <ms>` (acepta decimales), `prf <ms>`, `n`, `max`, `clk`, `dc`,
`pre on|off`, `run`, `info`.

#### Las dos cosas del firmware que más nos hicieron perder tiempo

**1. No salía nada por el puerto serie.** En el core Arduino-ESP32 3.x, `Serial`
es un **macro** que apunta a hardware distinto según la opción *USB CDC On Boot*:

| USB CDC On Boot | `Serial` es | Sale por |
|---|---|---|
| Enabled | `HWCDCSerial` | USB nativo (el mismo cable de programación) |
| **Disabled** (el default del `ESP32C3 Dev Module`) | `Serial0` | **UART0, GPIO20/21** |

O sea que por defecto el sketch imprime por pines a los que no hay nada
conectado, y el Monitor Serie queda mudo **aunque el programa corra perfecto**.
La subida funciona igual porque el flasheo lo hace el ROM por otro camino.

La solución que usamos es una clase `Consola` que escribe **por los dos**
simultáneamente, así funciona con cualquier configuración. Está en los dos
sketches. Alternativa: elegir la placa **"Nologo ESP32C3 Super Mini"**, que trae
`cdc_on_boot=1` fijo.

**2. Tramas binarias truncadas a 256 bytes.** El buffer de TX del HWCDC es de
**256 bytes por defecto** (`HWCDC.cpp:422`, `setTxBufferSize(256)`) y
`Serial.write()` puede devolver **menos de lo pedido**. Ignorar ese valor de
retorno cortaba las tramas. Se arregló con `Serial.ampliarBufferTx(4096)` más un
bucle de reintento con timeout. Verificado después: **8001.6 S/s medidos contra
8000 nominales, cero pérdidas**.

Otros detalles que ya están resueltos y conviene no volver a pisar:
- En un `.ino` los prototipos se autogeneran, así que **un `struct` usado por una
  función tiene que estar declarado antes** o da `does not name a type`.
- `%u` con un `uint32_t` da warning: va `%lu` con `(unsigned long)`.
- El `++` sobre una variable `volatile` está deprecado en C++20: se escribe
  `x = x + 1;`.
- Hay persistencia en NVS porque la ventana del Serial Plotter **no tiene entrada
  de texto** y reabrirla resetea la placa; sin NVS se perdía la configuración.

---

### 6. Cronología: en qué orden hicimos las cosas

1. **Estudio del circuito del PCM1808** antes de escribir una línea de código:
   relojes, modos, pasa-altos, ruido, fondo de escala. Quedó en
   `docs/PCM1808_hardware.md`. De ahí salió que el modo esclavo es la única forma
   de tener `fs` variable.
2. **Firmware de banco** para digitalizar una senoidal de un generador de
   funciones, un solo canal, legible en el Serial Plotter del Arduino IDE.
3. **Pelea con el Serial Plotter**: resultó que el IDE 2.x muestra **sólo 50
   puntos**, hardcodeado (`dataPointThreshold = useState(50)`). Con 1000
   muestras/s no se veía nada. Se rediseñó el modo `plot` como
   captura-en-ráfaga + reproducción lenta, y se agregaron `sig` (TIME/DIV),
   `win <ms>`, `n` y `rate`. **Cada punto que se dibuja es una muestra real del
   ADC**, no una senoidal reconstruida.
4. Se probó **Telemetry Viewer** como visualizador, y después se reemplazó por
   **software propio en Python** que además **graba a CSV**.
5. **Generador de patrones en Arduino Uno** para validar sin RF.
6. **Creación del repo en GitHub** (público) y **consolidación**: había tres
   carpetas desparramadas con cosas del GPR y se unificaron en una sola.
7. **Enlace binario con CRC** + grabador a CSV con metadata + graficador en vivo
   (espectro, osciloscopio, B-scan).
8. **Caracterización de un filtro activo pasabajos** (trabajo aparte, en
   `Filtro Pasabajos/`). Se descubrió que el flanco superior **depende de la
   amplitud**, o sea que la caída que se veía era distorsión del amplificador y
   no la respuesta del filtro. Se separa el trazo en continuo/punteado en el
   límite de distorsión (1750 Hz).
9. **Caracterización del VCO** con saltos de 100 mV y 1 MHz de precisión.
10. **Linealización del barrido por predistorsión** (`VCO/analisis_vco.py`):
    se invierte la curva medida con PCHIP y se genera `tabla_vco.h`. Resultado:
    `dF/dt` pasó de variar **0.68–1.29×** a **0.991–1.010×**, con 0.20 MHz de
    error pico sobre 1039 MHz de barrido.
    **Ojo con qué es lo que mejora:** la resolución la fija el ancho de banda
    (`c/2BW` = 14.4 cm con 1039 MHz) y la predistorsión **no la cambia**. Lo que
    corrige es el **ensanchamiento** del pico: sin predistorsión, un blanco
    puntual a 1 m se desparrama entre ~0.68 y ~1.29 m porque la pendiente `dF/dt`
    varía en esa proporción. Con predistorsión el pico se concentra donde
    corresponde y recién ahí se aprovechan los 14.4 cm.
11. **Capturas de osciloscopio de la rampa** con y sin predistorsión, a PRF de
    50 ms y 5 ms → `VCO/dac_capturas_osciloscopio.png`.

**Por qué PCHIP y no spline cúbico**: PCHIP preserva la forma y la monotonía, y
no inventa oscilaciones entre puntos medidos. Para poder **invertir** la curva
hace falta que sea monótona, así que es la elección obligada. Contrapartida: su
derivada **amplifica** el ruido de cuantización de la medición, así que cuando
graficamos `dF/dV` hay que suavizar con Savitzky-Golay.

---

### 7. Estado actual

**Funcionando y verificado sobre hardware:**
- Digitalización con PCM1808, validada contra generador de funciones.
- `fs` variable en caliente (8–96 kHz).
- Enlace binario con CRC: 8001.6 S/s medidos, cero pérdidas.
- Grabación a CSV con metadata y verificación de continuidad.
- Visualización en vivo: espectro, osciloscopio y B-scan.
- Rampa del DAC con predistorsión, corriendo a PRF de 5 ms.

**Camino alternativo por placa de audio (`adquisicion_audio/`): cadena
verificada con la placa conectada, sin señal de radar todavía.** Las dos
autopruebas pasan y la captura se probó contra la UMC22 real: WDM-KS, 48 kHz,
2 canales, 0,05 % de error de tasa, 238592 muestras en 5,1 s sin clipeo ni
overflow, CSV y WAV consistentes muestra a muestra. Piso de ruido con las
entradas al aire: −78 dBFS. **Falta medir con la cadena de RF conectada.**
Ver §3 para el conexionado y las trampas de la placa, y
`docs/placa_audio_umc22.md` para dejarla andando en una máquina nueva.

**Pendiente, en orden de importancia:**

1. **Acelerar el sweep FMCW. Es el bloqueante principal.** Con el
   `T_sweep ≈ 1.46 s` original, las frecuencias de beat de la zona útil (0.2–2 m)
   caen entre 0.9 y 9 Hz — o sea **adentro del pasa-altos del PCM1808, que no se
   puede desactivar**. Bajando a 5–10 ms el beat pasa a 130 Hz – 2.7 kHz y el
   problema desaparece. **Techo duro**: el período de la rampa es
   `2 × n_pasos × 125 µs`, así que con 200 pasos da 50 ms como mínimo. Para ir
   más rápido hay que bajar `n` o acelerar la escritura I²C.
   **Cambiar de ADC no lo esquiva**: la placa de audio corta a 10 Hz, más arriba
   que el PCM1808, así que este pendiente sigue igual de vivo por los dos
   caminos.
2. **Sincronismo entre la rampa y el reloj de muestreo del I²S.** Sin él no se
   puede promediar coherentemente entre barridos. La idea es atar los pasos del
   DAC a la cuenta de muestras.
3. **Integrar el DAC al firmware principal** (hoy está en un sketch aparte).
4. **Medir el riel de 3V3 real con el tester** y regenerar `tabla_vco.h` si
   difiere de los 3.300 V asumidos: ese valor **escala todo el barrido**.
5. Caracterizar el piso de ruido con batería. Una captura preliminar dio ~62 dB
   de SNR (≈10 bits efectivos) con un pico de red en 50 Hz, bastante por debajo
   de los 99 dB del chip.
6. Atenuador de entrada, dimensionado para 3 Vpp (el peor caso).
7. Clamp / Zener de protección para el VCO (falta saber la tensión de
   alimentación del amplificador).
8. Segundo canal para I/Q.

**Dos cosas abiertas de la última sesión, sin resolver:**
- En las capturas de osciloscopio, **la comba de la predistorsión no se separa
  del piso de ruido**: con `pre on` dio 32 y 53 mV rms, con `pre off` 23 y
  49 mV rms, y la tabla predice 57 mV rms (201 mV pico). Falta confirmar en el
  banco que la predistorsión estuviera efectivamente activa en esas capturas.
  Se resuelve con una captura a 50 ms con más resolución vertical (500 mV/div
  con offset, para bajar a la mitad el ruido de cuantización).
- **La amplitud medida da 3.16 Vpp y debería dar 3.00.** Puede ser exactitud
  vertical del osciloscopio (±3 % típico) más offset, o que el riel real no sea
  3.300 V. Está ligado al punto 4 de arriba.

---

### 8. Cosas que ya aprendimos y no conviene volver a discutir

- **dB**: `20·log10` para tensión (×2 = 6 dB), `10·log10` para potencia
  (×2 = 3 dB). −3 dB = mitad de potencia = 0.707 en tensión.
- **Normalización de espectro**: usamos normalización **en amplitud**, no PSD,
  para que el pico de un tono valga su amplitud real sin importar la ventana. La
  pérdida por scalloping con ventana rectangular es de **3.92 dB** en el peor
  caso (medio bin).
- Al medir el **desvío contra una recta** en una captura de osciloscopio, usar
  **RMS y no máximo**: el Siglent digitaliza a 8 bits sobre 8 V de pantalla
  (≈31 mV por código) y el máximo se lo lleva siempre una muestra ruidosa suelta.
- Para encontrar los vértices de una triangular con `scipy.signal.find_peaks`,
  hay que filtrar por **prominencia**, no por distancia. Filtrando sólo por
  distancia encuentra máximos locales del ruido en mitad de la rampa.
- Para medir `dF/dt` sobre la tabla del VCO hay que usar una **ventana de ~32
  entradas**, no entradas adyacentes: a escala de una entrada domina la
  cuantización de 12 bits del DAC y el resultado es un artefacto numérico.
- Si un comando por serie no se ejecuta, revisar la configuración de **carriage
  return** del monitor.
- No se puede tener el Monitor Serie del Arduino IDE abierto y el software de
  Python midiendo al mismo tiempo: **un solo programa puede tener el puerto COM
  abierto**.

---

### 9. Cómo quiero que trabajes

- **Verificá contra el repo antes de afirmar.** Este documento puede quedar
  desactualizado; el código no. Si algo no coincide, decímelo.
- **Números y mediciones reales, no estimaciones presentadas como hechos.** Si
  algo no está medido, decilo.
- Si encontrás un problema en lo que te pido, decilo en una o dos frases y
  **seguí adelante** con el trabajo, dejando la suposición explícita.
- Cuando toques código, **hacelo parecido al que ya está**: comentarios en
  español que expliquen el porqué, y misma densidad de comentarios.
- Si generás una figura, **abrila y miralas antes de darla por buena**. Líneas
  gruesas y colores bien diferenciados.
- Los scripts de análisis se corren y se muestra la salida real. Si un test
  falla, se dice que falló.

## HASTA ACÁ
