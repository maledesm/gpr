# GPRv3 — adquisición con sincronismo por hardware

Sistema nuevo (firmware del ESP32-C3 + software de la PC) para el radar con el
**generador de triangular analógico** (`GPRv2/docs/PWM/`). El ESP32 ya no
muestrea la triangular por GPIO3. Lee la cuadrada de sincronismo del generador
y con sus flancos la PC corta las rampas.

Es una carpeta aparte. **No toca nada de `GPRv2/`**, que sigue andando igual
con el generador de laboratorio. Lo único compartido es `VCO/` (se lee, no se
copia).

> ⚠️ **Estado al 2026-11-16: escrito y verificado SIN banco.** El firmware
> compila pero nunca corrió en la placa. Todo lo demás está probado contra
> streams sintéticos, contra el núcleo del firmware compilado para la PC y
> contra una captura real de GPRv2. La lista de lo que falta mirar en el banco
> está en [Primera vez en el banco](#primera-vez-en-el-banco).

## Uso

| | |
|---|---|
| `vivo.bat` | radargrama en tiempo real, con la placa |
| `simular.bat` | lo mismo sin banco, con blancos simulados |
| `grabar.bat [segundos]` | graba el crudo a `datos/captura_<fecha>.gpr3`, sin ventana |
| `analizar.bat [archivo]` | figura de una grabación (sin archivo, la más nueva) |
| `verificar.bat` | las 58 comprobaciones sin hardware (~40 s) |
| `compilar.bat [COMx]` | compila el firmware con arduino-cli; con puerto, lo carga |

`vivo.bat --archivo datos\captura_X.gpr3` reproduce una grabación en la misma
ventana. Python: el venv `gpr-win` de siempre, que ya tiene todo
(`requirements.txt`).

```
GPRv3/
  firmware/adquisicion_sync/   el .ino y nucleo.h (diezmado, flancos, paquetes)
  firmware/prueba_pc/          el mismo nucleo.h compilado para la PC
  software/
    config.py      parámetros del banco: lo único que se toca a mano
    protocolo.py   paquetes binarios
    fuentes.py     placa, grabación o banco sintético, misma interfaz
    rampas.py      flancos -> rampas
    proceso.py     rampa -> perfil de distancia
    modelo.py      el radar sin ventana: perfiles, fondo, pico, calibración
    vivo.py        la ventana (pyqtgraph)
    captura.py     PNG + CSV de lo que se ve
    grabar.py, analizar.py, sintetico.py, verificar.py
  datos/           grabaciones, capturas, calibración (arranca vacío)
```

## La ventana

Lo de `vivo_rapido.py` está todo: rampas/fila, ventana, alcance, piso y techo,
eje en m o Hz, ignorar, medir fondo, fondo automático (MTI), puerta de
detección con margen, calibración por puntos, captura PNG + CSV con
temporizador y cartel, y la columna de controles que se acuerda. Teclas `e`,
`a`, `f`, `s`, `q`. Lo nuevo:

- **Líneas rojas**: cada cambio de un ajuste deja una marca en ese instante
  del radargrama (una línea a tiempo constante, o sea horizontal) (rampas/fila, ignorar, margen, sentido de las rampas, fondo,
  calibración, los tres deslizadores). No marcan los que solo cambian la vista
  (ventana, alcance, piso, techo, eje, autoescala). La traza del pico pasó a
  blanco para no confundirse con las marcas. Las marcas se pierden si la placa
  se reinicia (cambio de muestras/s).
- **Tema oscuro**, con el mismo fondo en la ventana, los controles y los
  gráficos, letra seminegrita y botones redondeados. El PNG de captura sigue en blanco, que es lo que va al informe.
- **Deslizador de retardo** (±2 ms, pasos de 10 µs, arranca en 0). Corre los
  límites de las rampas que se procesen de ahí en más. Ver
  [Retardos](#retardos).
- **Los dos deslizadores** (abajo a la derecha). El de **valle**, al subirlo,
  deja de usar muestras del principio de la triangular. El de **cima**, al
  bajarlo, deja de usar las del final. Van en % de la rampa y al lado dicen a
  qué tensión y a qué frecuencia del VCO corresponden. El gráfico de arriba
  muestra la última subida y la última bajada superpuestas, con lo descartado
  en gris. Recortar cuesta resolución (`c/2·BW` con la banda que queda) y el
  panel la informa. Reemplazan al "tiempo de guarda" que se había hablado.
- **`rampas`: ambas / subida / bajada.** Para comparar los dos sentidos.
- **`pico subida − bajada`** en el panel. Es el diagnóstico del retardo (ver
  [Retardos](#retardos)).
- **`muestras/s`**: 3000, 6000, 12000 o 24000. Reinicia la placa. Con Tprf
  corto hace falta más (el panel dice hasta dónde llega el alcance no ambiguo).
- **`grabar crudo`** es una casilla, se puede prender en el medio de una corrida.
- **Carteles rojos**: `SIN SYNC` si dejan de llegar flancos y `LA PLACA NO
  CONTESTA` si lo que llega no es GPRv3 (por ejemplo, el firmware viejo).
- **Mover el pote no reinicia nada.** Tampoco mover los deslizadores.

La pantalla va en pyqtgraph y no en matplotlib. Medido con el banco sintético,
un cuadro cuesta ~8 a 11 ms (contra 22 de `vivo_rapido.py` con blitting), así
que el refresco bajó de 200 a 100 ms. Los controles son widgets de verdad y la
barra de color se puede arrastrar. El PNG de captura sí se arma con matplotlib,
aparte de la pantalla, y por eso no depende del tamaño de la ventana.

## Cómo funciona

### Sincronismo

El firmware atiende los **dos** flancos de la cuadrada (GPIO10, `PIN_SYNC` en
el `.ino`). Medido con el Tektronix el 2026-11-06, el flanco de **subida** cae
en el vértice de **arriba** y el de bajada en el de abajo
(`SYNC_ALTO_ES_BAJADA` en `config.py`). Cada rampa va de un flanco al
siguiente con **su largo real**, así que la subida de 50,5 ms y la bajada de
49,4 ms dejan de cortarse en mitades iguales. La bajada se lee al revés y
queda como una subida.

Para ubicar un flanco sobre el eje de muestras hacen falta dos relojes
comparables. El instante del flanco se toma en su interrupción y el de cada
bloque de 256 tramas en la interrupción de fin de bloque del DMA (no al volver
de `i2s_channel_read()`, porque si el lazo viene atrasado esa lectura devuelve
un bloque viejo). Los dos salen del mismo cristal, así que no hay deriva. El
flanco viaja como índice de muestra de salida con fracción de 1/256.

Una rampa se descarta si llegan dos flancos del mismo sentido, si su duración
cae fuera de 4 a 300 ms, si difiere más de 15 % de la mediana de las últimas
cinco de su sentido (un flanco espurio la parte en pedazos) o si pisa un hueco
de muestras. El panel cuenta cada caso.

### Protocolo

```
A5 5A | tipo (1) | largo (2) | carga | crc16 (2)        todo little endian
```

| tipo | carga |
|---|---|
| `D` | índice de la primera muestra (u32) + muestras de 24 bits con signo |
| `S` | índice (u32) + fracción/256 (u8) + nivel (u8) + µs de la placa (u32) |
| `I` | versión, fs, dec, pin del sync, tramas por bloque. Sale con cada `run` |
| `E` | desbordes del DMA, paquetes descartados, flancos, errores. Una vez por segundo |
| `T` | texto |

Los comandos hacia la placa siguen siendo líneas de texto: `run`, `stop`,
`sps N`, `info` y `texto` (emite `batido,sync` para el Serial Plotter).

Por qué debería andar mejor que el binario anterior:

- **Se engancha solo.** Lo que no sea un paquete con su CRC bien se saltea.
  No importa en qué byte se abra el puerto ni que la placa mande texto.
- **Cada paquete de datos trae su índice.** Si se pierde uno, la PC ve el
  hueco y descarta solo las rampas que lo pisan. Nada se corre.
- **Un paquete entra entero o no entra.** El firmware mira el lugar libre
  antes de escribir, con un buffer de TX de 8 kB. Nunca bloquea el lazo ni
  manda medio paquete.
- **Caudal.** 3 bytes por muestra son 38 kB/s a 12000 sps y 75 kB/s a 24000,
  contra un techo de ~100 kB/s. En texto, 6000 sps ya eran 78 kB/s.
- El puerto se abre con DTR y RTS en bajo, como en GPRv2, para no reiniciar
  la placa.

Las grabaciones `.gpr3` son esos mismos paquetes más uno `M` con metadatos
(fecha, vértices, curva). Pesan ~2,3 MB por minuto a 12000 sps y se parten a
los 90 MB.

### Corrección de la no linealidad

Es la de GPRv2 (curva estática del VCO y triangular recta, opción "a"), con
`Caracteristica VCO 2026-10-19.csv` y los vértices medidos con el Tek, **0,12
a 3,06 V**. Con eso la curva da 994 a 2000 MHz (1006 MHz).

Lo que cambia es **cómo** se remuestrea. GPRv2 llevaba cada rampa a N puntos
uniformes en θ, con N igual a las muestras de la rampa, y entonces el eje de
distancia dependía del largo de la rampa. Acá se remuestrea a un **paso de
frecuencia fijo** Δf, y la FFT de eso tiene bins de `c/(2·N_fft·Δf)`, que no
dependen ni de la duración de la rampa ni de la parte que se use. El eje
guardado es siempre de 2 cm por bin hasta 30 m. Por eso no hay que reiniciar
nada cuando se mueve el pote o un deslizador.

- Δf arranca en 1,83 MHz con FFT de 4096 y se parte de a mitades (duplicando
  la FFT) hasta que no sea más grueso que el paso más fino que traen las
  muestras. A 100 ms y 12000 sps da 1099 puntos y FFT de 8192.
- El interpolador sigue siendo un spline cúbico. Se arma uno solo sobre el
  tramo continuo de batido y se evalúa en los puntos de todas las rampas del
  lote, con sus límites fraccionarios.
- La ventana de la FFT se elige (rectangular, Hamming, Hann, Blackman,
  Blackman-Harris; arranca en Hann). En ese orden bajan los lóbulos laterales
  y se ensancha el pico. La amplitud se normaliza con `2/Σw`, así que un tono
  de amplitud A (cuentas del ADC) da lo mismo con cualquier ventana y Tprf.
- **Los perfiles son de potencia.** De cada rampa se guarda `|FFT|²` y las
  rampas de una fila se promedian en potencia (periodograma promediado). Se
  muestra `10·log10`. El fondo también se resta en potencia, con piso en
  cero. Hasta acá se promediaban módulos, que deja el piso de ruido ~1 dB
  abajo de lo real. En los CSV, `mag` es la raíz de esa potencia media y
  sigue en cuentas del ADC.

### Lo que se cambia vale "de ahí en más"

Cada fila del radargrama se calcula una sola vez, cuando junta sus rampas, con
el fondo, la referencia de dB, el agrupado, el sentido, la ventana de FFT, el
recorte y el retardo de ese momento, y no se vuelve a tocar. Un cambio deja
su línea roja y afecta solo a lo que entra después. Por eso las filas pueden
durar distinto (otro rampas/fila, otro Tprf): al dibujar se llevan a una
grilla pareja en tiempo, y donde no hubo datos queda vacío.

Siguen valiendo para toda la pantalla los que son de vista: ventana, alcance,
piso, techo, colores, eje m/Hz y la **calibración de distancia** (cambia los
números del eje, no los datos). También la referencia de 0 dB cuando no hay
fondo, que es el máximo de lo que se ve. El pico, la puerta de detección y la
FFT de abajo son siempre "lo de ahora".

### Promedio coherente, descartado (2026-11-16)

Se probó sobre una captura real de GPRv2 (28/9) promediar y restar el fondo
en complejo. La fase del batido se repite de rampa a rampa mientras la escena
está quieta (es `2π·τ·f(t)`, no depende de la fase del VCO), pero deriva unos
20° en 33 s. Con eso, la resta coherente de un fondo congelado deja −29 dB de
residuo a los 4 s y −9 dB a los 31 s, contra −51 y −38 dB de la resta de
módulos. Y el promedio coherente de 8 rampas baja el piso 2 dB, no los 9
teóricos, porque ese piso no es ruido al azar. No se implementó.

### Retardos

El firmware compensa **solo** el retardo de su propio filtro de diezmado, que
es exacto y sin eso el flanco quedaría corrido 2,2 ms: la salida `m` de la
cascada corresponde a la trama de entrada `dec·m − 14·(dec−1)`. Nada más se
compensa (decisión del 2026-11-16).

Lo que queda afuera es el filtro digital del PCM1808 (17,4/fs = 0,36 ms según
la hoja de datos, sin verificar en el banco) y el pasabajos post-mezclador.
Simulado con un blanco a 3,70 m:

| Tprf | atraso | pico de las subidas | de las bajadas | pérdida |
|---|---|---|---|---|
| 100 ms | 0,36 ms | 3,709 m | 3,690 m | 0,1 dB |
| 100 ms | 1,00 ms | 3,724 m | 3,671 m | 0,9 dB |
| 20 ms | 0,36 ms | 3,736 m | 3,647 m | 2,5 dB |
| 20 ms | 1,00 ms | (desparramado) | | 6 a 7 dB |

A 100 ms no importa. **Con el pote en períodos cortos sí**, y recortar con los
deslizadores no lo arregla, porque lo que se corre es el mapa entero. Si en el
banco `pico subida − bajada` da distinto de cero y crece al acortar el Tprf,
es esto. Para compensarlo está el deslizador de **retardo** de la ventana
(arranca en 0, que no hace nada, y se guarda con el resto de los controles):
se mueve hasta que la diferencia dé cero. `RETARDO_S` en `config.py` es el
valor inicial para `grabar.py`, `analizar.py` y `verificar.py`.

## Qué se verificó sin banco

`verificar.bat`, 58 comprobaciones (las de abajo más ventanas de FFT, filas que no se recalculan, retardo automático y curva medida):

1. Protocolo: ida y vuelta, reenganche con texto y basura en trozos de 1 a
   4096 bytes, un byte corrupto cuesta un solo paquete.
2. `nucleo.h` compilado con gcc arma **byte a byte** los mismos paquetes que
   el modelo de Python, con dec 2, 4, 8 y 16. El flanco cae en el mismo lugar
   (dentro de 1,3 µs) aunque el lazo lo atienda 3 o 9 ms tarde.
3. Un impulso y un flanco simultáneos salen en la misma muestra de salida.
4. Blancos sintéticos a 1,61 y 3,70 m: error ≤ 0,2 mm y amplitud dentro de
   1,2 % con seis combinaciones de sps y Tprf (20 a 275 ms), moviendo el pote
   de 50 a 140 ms y usando solo del 15 al 85 % de la rampa. Subidas y bajadas
   dan el mismo pico. Con la polaridad del sync al revés el pico cae a la
   mitad, o sea que la prueba es sensible.
5. Con 2 % de paquetes perdidos, con flancos espurios y con flancos faltantes,
   los picos no se mueven.
6. Grabación y captura. El CSV lo lee también `leer_fft_captura` de GPRv2.
7. **Una captura real** (`GPRv2/datos/captura_28-09-2026_17-53-54.csv`, con
   los vértices del ajuste viejo pasados como flancos): el pico da 3,800 m con
   la cadena vieja y 3,801 m con la nueva, y los perfiles coinciden entre 0,3
   y 10 m con correlación 0,9998.
8. `RETARDO_S` devuelve el pico a su lugar.

## Primera vez en el banco

Nada de esto se pudo probar y es lo primero a mirar.

1. **En qué GPIO está el sync.** El firmware asume GPIO10 (`PIN_SYNC`).
2. **Nivel del sync.** Con el LM324 el alto medido es 2,63 V y el C3
   garantiza el uno lógico recién desde 2,475 V (0,75·VDD). Hay 0,15 V de
   margen. Si además hay un divisor entre el generador y el pin, puede no
   llegar. Si aparece `SIN SYNC` con todo conectado, es lo primero a medir.
3. Cargar con `compilar.bat COMx` y abrir `vivo.bat`. El panel tiene que
   mostrar el Tprf del generador, subida ~1 ms más larga que la bajada,
   `descartadas` quieto, `bytes malos` quieto después del arranque, y
   `desbordes` y `descartados` de la placa en 0.
4. **`jitter`.** Es el desvío de la duración de las rampas según el reloj de
   la placa. Debería ser de decenas de µs. Si salta de a ~5 ms, el instante de
   bloque está mal asignado (bloques de DMA de 5,33 ms).
5. **Polaridad.** Si los picos salen anchos y bajos y mejoran cambiando
   `SYNC_ALTO_ES_BAJADA`, estaba al revés.
6. **`pico subida − bajada`**, con Tprf largo y corto (ver Retardos).
7. Calibrar la distancia de cero: `datos/` no hereda la calibración de GPRv2.

## Diferencias con GPRv2 que conviene tener presentes

- `C` vale 299 792 458 m/s (antes 3·10⁸): 0,07 % en distancia.
- La distancia cruda cambia respecto de las capturas viejas porque cambiaron
  la curva y los vértices. La calibración se toma de nuevo.
- El perfil está en cuentas del ADC, no en unidades de FFT. Las `mag` de los
  CSV nuevos no se comparan con las viejas sin normalizar.
- En el CSV de captura cambian algunos metadatos (`subida_ms`, `bajada_ms`,
  `rampa_desde_pct`, `rampa_hasta_pct`, `bw_total_mhz`, `paso_eje_m`; ya no
  están `fs_theta_sps`, `relleno` ni `triangular_saturada_pct`). Las seis
  columnas y `alpha0_hz_s` son las mismas.
- Al cambiar rampas/fila ya no se reagrupa lo que está en pantalla.
- Se recuerdan 6000 rampas (`PERFILES_MAX`): 5 min a Tprf 100 ms, 1 min a 20.
- El índice de muestra es de 32 bits. Da la vuelta a las 49 h a 24000 sps y
  la PC lo toma como un reinicio de la placa.

## Pendientes (anotados el 2026-11-17)

Para la tanda de mediciones finales, además de lo de "Primera vez en el banco":

- [ ] **Aislar las antenas entre sí** (chapa o absorbente entre las dos
  bocinas) y medir el acoplamiento directo antes y después. Es el pico más
  fuerte de la señal y lo que fija cuánto rango dinámico queda. Ya estaba
  planeado; queda acá para no olvidarlo.
- [ ] **Medir la curva del barrido con un retardo conocido.** Ya está
  programado (ver "Curva medida" abajo); falta hacer la medición.
- [ ] Comparaciones para el escrito: con y sin filtro de RF, con y sin
  remuestreo, curva vieja contra nueva del VCO, triangular de laboratorio
  contra analógica, curva estática contra curva medida con el retardo.
- [ ] B-scan: solo si antes se comprueba que el radar ve a través del suelo.
  El objetivo de la tesis queda abierto: si no funciona como GPR, se presenta
  como radar de distancia.

Descartado por presupuesto: canal de referencia en vivo en el canal derecho
del PCM1808 (pide un segundo mezclador). Va como trabajo futuro.

### Pendientes que están anotados en otros lados del repo

Relevados el 2026-11-17, para tenerlos juntos. El detalle está en cada archivo.

- `GPRv2/docs/FILTRO_RF/README.md` §6: fabricar la placa (A, B, línea de paso
  y resonador λ/4), medirla con el tracking generator o el VNA, esquinas de εr
  (4,2 y 4,8), margen de recorte de los stubs del A, y confirmar en
  `simulaciones_meep/armonicos/` cuánto atenúa la ventana de Hann el armónico
  que se escapa por debajo de 2,35 GHz. Opcional: MEEP más fino.
- `GPRv2/simulaciones_meep/armonicos/LEEME.md`, "Lo que falta medir": 2.º y
  3.er armónico hasta ~6 GHz a la salida del VCO, del PA y en el LO; la
  medición con barrel y atenuador (es la misma de la curva medida, y de paso
  muestra los fantasmas en 2f y 3f); la salida del amplificador ×4,95 para
  ver si recorta; y un blanco único y quieto procesado con las dos curvas del
  VCO.
- `GPRv2/mediciones/README.md`, "Falta medir o confirmar": espesor de la
  chapa de las bocinas, cuál conector es el de TX, si están paralelas y
  cuánto entra la sonda.
- `GPRv2/docs/PWM/README.md`: repetibilidad del nivel de continua de la
  triangular (medir los vértices con el Tek en dos o tres encendidos).
- `GPRv2/CLAUDE.md`: el experimento del ADC de GPIO3 quedó en pausa y el
  firmware viejo sigue con las líneas `#v3`. Con GPRv3 deja de importar,
  porque ya no se lee la triangular.
- `README.md` de la raíz: la lista de pendientes es de la etapa del DAC
  (acelerar el sweep, sincronismo, segundo canal I/Q) y está desactualizada.

## Curva medida con un retardo conocido

En vez de suponer f(t) con la curva estática del VCO y una triangular recta,
se la mide con el propio radar. Se sacan las antenas y se une el cable de TX
con el de RX por un barrel **con atenuador**, sumando un coaxil como línea de
retardo. El radar ve un solo eco, de retardo τ conocido, y la fase de su
batido vale `2π·τ·f(t)`: cada vuelta de fase son `1/τ` Hz de barrido.

Uso, en la ventana (grupo "Procesamiento"):

1. Escribir el retardo de referencia en **metros aparentes** (`c·τ/2`, lo que
   el radar mostraría para ese cable; sale de las mediciones del VNA).
2. `medir curva`. Mide 5 s, promedia las rampas, saca la fase y guarda
   `datos/calibracion_barrido.json`. Pone el retardo en 0 (la curva medida ya
   lo trae adentro) y pasa a usarla, con su marca roja.
3. El selector `curva VCO` cambia entre `estática` y `medida`, para comparar.

Detalles:

- Se mide una curva para la subida y otra para la bajada.
- Hacen falta al menos 8 vueltas de fase en la rampa, o sea más de ~1,2 m
  aparentes. Con menos avisa y no cambia nada. Más cable, mejor.
- La curva vale para el Tprf y el encendido en que se midió (el panel dice a
  qué Tprf). Si se mueve el pote hay que repetirla.
- El 3 % de cada punta de la rampa no se mide (se extrapola en línea recta).
- τ fija la escala: un error de 1 % en el retardo de referencia es 1 % en
  todas las distancias. La calibración de distancia de siempre lo absorbe.
- Los MHz que informa el panel con la curva medida están anclados a la curva
  estática en el medio de la rampa. La constante no cambia las distancias.

Simulado (`verificar.py`, punto 10) con la triangular 0,15 V más arriba y el
batido atrasado 0,36 ms respecto de lo que supone `config.py`: el piso entre 9
y 12 m baja de −53 a −74 dB y un blanco de −32 dB que quedaba tapado aparece
en su lugar. Cuánto mejora en el banco depende de cuánto se aparte el barrido
real del supuesto, y eso recién se sabe midiendo.

## Bitácora

**2026-11-16.** Primera versión, escrita en una sesión sin banco a partir de
`adquisicion.ino` y `vivo_rapido.py`. Decisiones de Martín: solo el generador
analógico y solo el sync (sin GPIO3), rampas cortadas en la PC, binario simple,
las dos rampas, deslizadores de valle y cima, opción (a) para f(t), sin
compensar el corrimiento de continua entre encendidos, datos y calibración de
cero, siempre con PC. Se instaló arduino-cli 1.6.0 con winget. El firmware
compila para `nologo_esp32c3_super_mini` con el core esp32 3.3.10 (296 kB).

**2026-11-16, más tarde.** A pedido de Martín: promedio en potencia (lo
preguntó un profesor), ventana de FFT elegible, gráfico de la triangular
**dibujada** (no se mide: sale de las duraciones del sync y de los vértices de
`config.py`), botón que ajusta el retardo solo (lleva `pico subida − bajada` a
cero por la secante, tarda ~10 s y necesita la escena quieta), todo "de ahí en
más" salvo la calibración, selector de colores (inferno por defecto) y ventana
maximizada. El diagnóstico del enlace pasó a la barra de estado. La ventana
necesita 766 px de alto, así que entra en 1080p también con Windows al 125 %.
