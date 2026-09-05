# GPRv2 — contexto y punto de partida

Este archivo es el **prompt de arranque** de una etapa nueva del proyecto. Pegalo
entero en un chat de Claude vacío, o decile *"leé `GPRv2/CONTEXTO.md` y seguí
esas instrucciones"*.

---

## PEGAR DESDE ACÁ

Vas a ayudarme con mi tesis de grado en Ingeniería Electrónica de la FIUBA.
Trabajamos en español: comentarios, commits y documentación.

**Este documento tiene prioridad sobre el repo.** El repo tiene la historia y los
datos medidos, que sirven; pero lo que quiero hacer *ahora* está acá, y donde se
contradigan, gana este archivo.

### Antes de responder nada

Leé, en este orden:

1. Este documento entero.
2. `VCO/Caracteristica VCO.csv` — la curva medida del VCO. Es el dato más
   importante del repo y lo vamos a seguir usando.
3. `docs/PCM1808_hardware.md` §1 a §5 — el ADC: relojes, modo esclavo,
   pasa-altos, front-end.
4. `docs/conexionado.md` — el cableado real.
5. `firmware/PCM1808_ESP32C3/PCM1808_ESP32C3.ino` — **sólo para saber qué NO
   repetir**. Es el firmware viejo: funciona, pero se volvió demasiado grande.
   Miralo para entender el hardware, no como modelo de código.

Después contame qué entendiste y hacé las preguntas que te queden. **No escribas
código hasta que acordemos un plan.**

---

## 1. Qué estamos construyendo

Un **GPR** (radar de penetración terrestre) **FMCW**. Se barre una rampa de
frecuencia, se mezcla el eco con lo transmitido, y la **frecuencia de batido** da
la distancia.

```
f_beat     = 2 · R · BW / (c · T_rampa)
resolución = c / (2 · BW)
```

Con `BW = 1039 MHz` eso son **6,93 / T_rampa** Hz por metro, y **14,4 cm** de
resolución en aire (4,8 cm en suelo con εr ≈ 9).

Con la rampa de ~50 ms que vamos a usar: **139 Hz por metro**.

---

## 2. Por qué empezamos de cero

Dos motivos, y el segundo importa tanto como el primero.

**Técnico.** Veníamos generando la rampa con un DAC MCP4725 por I²C. Cada
escritura tarda ~125 µs, así que la rampa salía **escalonada**: 74 escalones de
14 MHz. Eso convierte al radar en un **SFCW** (*stepped-frequency*), no un FMCW,
y le impone un alcance no ambiguo de `c/(4·Δf)` = 5,3 m que no queremos.
**Descartamos el DAC.** Ahora la rampa la genera un **generador de funciones de
laboratorio**, que da una triangular genuinamente continua.

**De método.** El código anterior creció por acumulación y dejó de ser algo que yo
entienda. Tenía decenas de comandos que nunca pedí, tres capas de sincronismo y
un protocolo binario con CRC. Quiero volver a tener control sobre lo que corre.

---

## 3. La cadena de hardware

```
Generador de funciones ──> amplificador ──> VCO ──> splitter ──┬──> Antena TX
   (triangular, ~50 ms)                                        │
                                                               └──> LO del mixer
                                                                        │
   Antena RX ──> LNA ──────────────────────────────────────────────> Mixer
                                                                        │
   ESP32-C3 <──I²S── PCM1808 <── filtro pasabajos <─────────────────────┘
       ↑
       └── sync del generador (cuadrada), para saber dónde empieza cada rampa
```

### Los números medidos

**VCO** (34 puntos, `VCO/Caracteristica VCO.csv`, precisión 1 MHz, saltos 100 mV)
- Con `Vin` de 0 a 3,00 V entrega **943 a 1982 MHz** → **BW = 1039 MHz**
- **La curva no es lineal**: `dF/dV` va de **468 a 167 MHz/V**, una variación de
  2,8 a 1. Sin corregir, un blanco a 1 m se desparrama entre 0,68 y 1,29 m.
- Entre el generador y el VCO hay un amplificador medido: `Vosc = 4,949·Vin + 0,055`

**PCM1808** (ADC, módulo comercial)
- ΔΣ de 24 bits, `fs` de 8 a 96 kHz. Modo **esclavo** (MD1 = MD0 = LOW): es la
  única forma de tener `fs` variable, el ESP32 le genera todos los relojes.
- Fondo de escala `0,6·VCC` = **3,0 Vpp con VCC = 5 V**. Impedancia 60 kΩ.
- Necesita **64 o 48 BCK por trama, nunca 32** → slots de 32 bits estéreo,
  y la muestra se recupera con `raw >> 8` sobre `int32_t`.
- Pasa-altos interno no desactivable: `0,019·fs/1000` Hz (0,91 Hz a 48 kHz), más
  el capacitor de acople del módulo (`CS 10`, o sea 10 µF contra 60 kΩ → 0,27 Hz).
  Combinado ~1,2 Hz; medido en el banco 1,27 Hz.

**Retardo de los cables** (medido 2026-09-05)
- El mezclador ve la DIFERENCIA de retardo entre sus dos entradas, así que los
  coaxiles de TX y RX se suman al retardo del blanco. Con **VF = 2/3, cada
  metro de coaxil son 0,75 m de offset** en la distancia leída.
- Con 3 m por antena: `D̃ = (3/2)·6 m = 9 m` → **offset de 4,5 m**. A `T_PRF`
  40 ms eso agrega **1500 Hz** al batido, contra los 333 Hz que da un blanco
  a 1 m.
- Es un **offset puro**: la pendiente sigue siendo 1 y la resolución no se
  toca. Se saca con un punto de calibración en `vivo.py`.
- Derivación completa, diagramas y tablas: **`GPRv2/docs/retardo_cables.md`**.

**Amplificador de RF y exposición** (agregado 2026-09-05)
- Salida del PA: **+24 dBm = 251 mW**. Con antenas de 6 a 10 dBi eso da
  **1 a 2,5 W de EIRP**.
- Densidad de potencia (campo lejano, `S = EIRP/4πr²`), caso de 8 dBi:

  | 20 cm | 30 cm | 50 cm | 1 m |
  |---|---|---|---|
  | 3,15 W/m² | 1,40 | 0,50 | 0,13 |

- Límite público general (FCC MPE / ICNIRP): **6,3 W/m²** en 943 MHz,
  10 W/m² arriba de 1,5 GHz. Ocupacional 5× más.
- **Se supera el límite público dentro de los 11 a 18 cm** de la antena,
  según la ganancia. Verificado por dos caminos: la fórmula de campo lejano y
  repartir los 251 mW sobre la apertura efectiva (19,7 W/m² pegado a la
  antena, mismo orden).
- **Regla del banco: no quedarse a menos de 50 cm del frente de la antena
  transmitiendo.** Deja un factor 8 a 20 de margen. Pasar caminando no es
  problema: los límites promedian sobre 30 minutos.
- Entre 25 y 57 cm todavía es campo cercano (`2D²/λ`), así que la fórmula
  sobrestima. Los números son cota superior; para un dato firme hace falta un
  medidor de campo.
- **Interferencia**: 251 mW barriendo 943-1982 MHz pisa GSM 900, GSM 1800 y
  UMTS/LTE banda 1 y 3. Usar sólo adentro, apuntando a tierra o a una pared
  interior, y no dejarlo transmitiendo sin medir.

**Filtro pasabajos post-mezclador**
- ⚠️ Tiene **corte inferior en 19 Hz**, mucho más alto que el del PCM1808. **Ese
  es el corte real de la cadena.** Limita cuán lento se puede barrer: con rampas
  mucho más lentas que 50 ms, los blancos cercanos se van abajo del corte.

**ESP32-C3 SuperMini**
- Un núcleo RISC-V a 160 MHz, **sin FPU** y **sin APLL**. 1× I²S, 1× I²C, 400 KB.
- Strapping: **GPIO2, GPIO8, GPIO9**. GPIO8 es el LED, activo en bajo.
- `fs` sale **exacta** en 16 / 32 / 48 kHz (divisor fraccionario del PLL de 160 MHz).
  44,1 tiene 0,005 % de error y 96 tiene 0,04 %.
- **No tolera 5 V en ningún pin.**

### Pines

| ESP32-C3 | | PCM1808 |
|---|---|---|
| `GPIO4` | → | `SCK` — **master clock (SCKI)**, 256·fs |
| `GPIO5` | → | `BCK` — bit clock, 64·fs |
| `GPIO6` | → | `LRC` — word select, = fs |
| `GPIO7` | ← | `OUT` — datos (DOUT) |
| `5V` | → | `5V` (VCC analógico, **5 V no 3,3**) |
| `3V3` | → | `3.3` (VDD digital) |
| `GND` | → | `FMY`, `MDI`, `MDO` (formato I²S + esclavo) |

**Libres**: GPIO0, GPIO1, GPIO3, GPIO10, GPIO20/21.
El sync del generador entra por uno de esos — a definir conmigo.

---

## 4. Lo que quiero hacer

### Primera etapa (empezamos por acá)

**Que el PCM1808 muestree y el ESP32 mande las muestras por serie a la PC**, en
un formato que se pueda mirar directo con el **Serial Plotter del Arduino IDE** o
con **Telemetry Viewer**. Nada de Python todavía. Nada de CSV todavía.

Eso es todo lo que quiero en el primer paso.

### Después, en orden

1. Leer el sync del generador para saber dónde empieza y termina cada rampa.
2. Grabar a CSV desde la PC (formato: ver los CSV viejos de `adquisicion/`).
3. FFT por barrido → perfil de distancia.
4. **Corrección de la no linealidad del VCO por remuestreo**: como no podemos
   medir el VCO en tiempo real, usamos la curva ya medida. Se mapea `t → V(t) →
   f(t)` con la curva, se remuestrea la señal de batido sobre un eje de
   frecuencia uniforme, y recién ahí se hace la FFT.

Esto último está basado en **Anghel et al., "Nonlinearity Correction Algorithm
for Wideband FMCW Radars", EUSIPCO 2013**. Ellos estiman la no linealidad de los
propios datos con la HAF; nosotros vamos a usar la curva medida, que es la
versión simple del mismo remuestreo. **No lo implementes ahora**, pero tenelo en
cuenta al diseñar para no cerrarte puertas.

⚠️ Ese remuestreo **reemplaza** a la predistorsión, no se suma. Nunca los dos.

---

## 5. Cómo quiero que trabajes

Esto es lo más importante del documento.

- **Preguntame antes de escribir cada archivo.** Cada archivo hace su parte y se
  edita por separado. Acordamos el plan, y recién después escribís.
- **Nunca hagas commit ni push sin preguntarme.** Quiero probar las cosas antes
  de subirlas, y poder volver a lo que ya estaba.
- **No agregues nada que no te haya pedido.** Ni comandos, ni modos, ni opciones
  "por si acaso". Si te parece que algo falta, decímelo y lo decido yo.
- **Lo más simple que funcione.** Sin patrones, sin capas, sin abstracciones
  preventivas. Si hay dos formas, la aburrida.
- **Comentarios mínimos.** Entiendo de código. Comentá sólo lo que no se deduce
  leyendo, típicamente el *porqué* de una decisión rara.
- **Sin autopruebas por ahora.** Más adelante veremos.
- Todo tiene que poder correrse **con un `.bat`**, para que testear sea rápido y
  no tenga que acordarme líneas de consola.

### Dónde va el código

Todo lo nuevo va en **`GPRv2/`**. No muevas ni toques nada de afuera: mi
compañero está trabajando en paralelo en `redaccion/` (la tesis) y en
`adquisicion_audio/`, y hay rutas fijas que se romperían.

`VCO/`, `docs/`, `redaccion/` y `datos/` son **compartidos**, no son "lo viejo".

---

## 6. Trampas que ya nos costaron tiempo

- **`SCK` del módulo PCM1808 es el MASTER CLOCK, no el bit clock.** El bit clock
  es `BCK`. Cruzarlos da "todo cero" y es el error #1 con este chip.
- **`Serial` es un macro.** Con *USB CDC On Boot = Disabled* apunta a UART0
  (GPIO20/21) y el monitor queda mudo aunque el programa corra perfecto. Compilá
  con la placa **Nologo ESP32C3 Super Mini**, o `ESP32C3 Dev Module` con
  *CDC On Boot = Enabled*.
- **El buffer de TX del HWCDC es de 256 bytes** y `write()` puede devolver menos
  de lo pedido. Si mandás bloques grandes, hay que mirar el valor de retorno.
- **El toolchain de Arduino no compila en rutas UNC** (`\\wsl.localhost\...`).
  Por eso el repo vive en `D:`.
- **El Serial Plotter del IDE 2.x muestra 50 puntos**, hardcodeado. Con miles de
  muestras por segundo no se ve nada.
- **El enlace USB CDC del C3 se satura arriba de ~100 kB/s.** Medido: a 192 kB/s
  desborda constantemente, a 128 kB/s desborda a veces, a 64 kB/s casi nunca.
- **Osciloscopio Siglent SDS1072CML+**: al guardar, *"Para Save"* tiene que estar
  en **ON** (si no, el CSV no tiene base de tiempo) y hay que poner **STOP**
  antes, o guarda archivos de 0 KB.
- No se puede tener el Monitor Serie abierto y un programa de la PC leyendo el
  puerto al mismo tiempo.

---

## 7. Restricción absoluta

En la carpeta de la tesis hay una carpeta de simulaciones electromagnéticas
(`CST`, ~59 GB), fuera del repo. **No se toca por ningún motivo**: ni mover, ni
renombrar, ni limpiar, ni indexar.

---

## 8. Contexto de trabajo

- Repo compartido con mi compañero: https://github.com/maledesm/gpr — público,
  rama `main`. `git pull` antes de empezar.
- Los mensajes de commit son largos y explican **por qué**, no sólo qué.
- Adquisición en **Windows** (`C:\Users\tinch\venvs\gpr-win`): el ESP32 es un
  puerto COM y WSL 2 no lo ve. El análisis offline puede correr en WSL.
- Instrumental: osciloscopio **Siglent SDS1072CML+** en el laboratorio, generador
  de funciones, analizador de espectro. En casa tengo un osciloscopio modesto.
- Blanco de prueba: **chapa metálica a 1,2 m**, o a **3 m del otro lado de una
  pared** — el radar la atraviesa sin problema.
- Entrega de la tesis: alrededor de **febrero de 2027**. Hay tiempo, no hay apuro.

---

## 9. Preguntas que tenés que hacerme ANTES de escribir código

Estas quedaron sin definir. No las asumas:

1. **Sync**: dije que quiero leer la cuadrada del generador con el ADC del
   ESP32-C3. Si te parece que una **entrada digital con interrupción** es más
   simple y precisa, decímelo y lo discutimos. En cualquier caso: **la salida de
   sync del generador suele ser 0–5 V y el C3 no lo tolera** — hay que definir el
   divisor y por qué pin entra.

2. **Caudal**: quiero mandar todas las muestras. Pero a 16 kHz en texto son
   ~128 kB/s, que está en el límite del CDC, y además el Serial Plotter no puede
   dibujar tantos puntos. Proponeme cómo resolverlo (diezmar, bajar `fs`, otra
   cosa) y lo decido.

3. **`fs`**: ¿fija en 16000, o cambiable por comando? Para la rampa de 50 ms,
   16 kHz alcanza de sobra.

4. **El `.bat`**: ¿compilar + cargar + abrir monitor? Decime qué te parece que
   tiene que hacer el primero.

## HASTA ACÁ
