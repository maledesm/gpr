# GPRv2 — notas para Claude

Este archivo se carga solo al trabajar en `GPRv2/`. Está para que ninguna
sesión trabaje con parámetros viejos.

`GPRv2/CONTEXTO.md` sigue siendo el documento que manda. Esto es sólo el
estado actual del banco, que cambia más seguido.

## ⚠️ `T_SWEEP` y `SPS_SALIDA` tienen dos valores en paralelo, no confundirlos

`T_SWEEP` (en `analisis/correccion_no_linealidad.py`) y `SPS_SALIDA`/`FS_DEF`
(en `firmware/adquisicion/adquisicion.ino`, compartido por los dos bancos)
sirven a dos bancos distintos que se usan en paralelo:

- **Banco casero de Martin** (`firmware/generador_chirp`, Arduino Uno, sin
  RF): calibrado a **10 ms**, `SPS_SALIDA` 4000, `FS_DEF` 16000 — ver la
  sección de abajo, "Estado del banco".
- **Primeras mediciones reales de laboratorio de Santiago** (VCO, mezclador,
  antenas de verdad): **20 ms**, `SPS_SALIDA` 6000, `FS_DEF` 48000 -
  elegido el 2026-09-02. A 10 ms sobra margen frente al corte de 19 Hz del
  pasabajos post-mezclador pero quedan pocas muestras por rampa para el
  remuestreo; a 20 ms el acoplamiento directo a 0,15 m sigue 3x arriba del
  corte (52 Hz) y hay más margen. `SPS_SALIDA` se subió de 4000 a 6000
  (dec exacto ×8 con `FS_DEF`=48000) porque a 20 ms sobraba presupuesto de
  ancho de banda: 6000 sps da 120 muestras/rampa a ~78 kB/s, todavía lejos
  de los ~128 kB/s donde el CDC empieza a desbordar. No es una discrepancia
  con el punto de abajo: son bancos distintos, midiendo cosas distintas, en
  paralelo.

**`adquisicion.ino` es el MISMO archivo para los dos bancos** - si alguno de
los dos necesita sus propios `FS_DEF`/`SPS_SALIDA` para seguir midiendo,
avisar antes de re-flashear con los valores del otro.

**Antes de tocar estos parámetros**: fijate cuál de los dos bancos se está
usando esa sesión, y avisá si los cambiás — el otro los necesita en su valor.

## Se puede medir SIN sync: la triangular se muestrea por GPIO3

El generador del laboratorio (Siglent SDG830) **no está dando sync** por el
BNC `Sync Out/Ext Trig`, con `Utility → Sync → State: On` y todo. Sin
resolver. Mientras tanto hay un camino alternativo, y funciona.

`adquisicion.ino` lee el ADC de **GPIO3** una vez por bloque de DMA (~187
lecturas/s = 7,5 por período de 40 ms) y emite `#v,<adc>,<indice>`, donde el
índice es la muestra de batido a la que corresponde. La lectura se hace
pegada al timestamp del bloque y se emite recién al final, para que el
instante coincida con el de la última muestra del bloque.

`grabar_rampa.py` separa esas líneas a `datos/triangular.csv` (`adc,indice`),
así `captura.csv` no cambia de formato. Si no llega ninguna línea
`#v,...` avisa (firmware viejo) y **borra el `triangular.csv` anterior**:
dejarlo cortaría la captura de hoy con los vértices de ayer, en silencio.

`graficar_captura.py` **y `waterfall.py`** usan el sync si `medir_rampa()`
lo valida, y la triangular si no.

`rampas_desde_triangular()` ajusta **un período y una fase a la captura
entera**, no vértice por vértice: con ~125 períodos en 5 s, el brazo de
palanca da el período con mucha más precisión. El período se refina
maximizando el primer armónico y la fase sale de su argumento.

**Cuidado con el signo de la fase.** Con `v(t) = f((t-t0)/T)` y `f` par,
`arg(S) = -2π·t0/T + π`. Invertir ese signo devuelve `T-t0` en vez de `t0`,
o sea agarra la BAJADA creyendo que es la subida, y no lo notás porque el
período sale bien igual. Ya pasó una vez.

Medido con triangulares sintéticas: el período sale exacto y el vértice con
0 µs de error, degradando a 167 µs (una muestra a 6000 sps) con 120 cuentas
de ruido de ADC sobre una triangular de 2048. Prueba de punta a punta con
rampa 2 % más larga que la nominal y la captura arrancando fuera de un
vértice: blancos a 1,20 y 2,40 m salieron en 1,226 y 2,435 m.

**Hardware**: divisor 4k7/4k7 de la triangular a GPIO3. Baja los 3 V a 1,5,
que cae en el medio del rango útil del ADC del C3 (~0 a 2,5 V); a 3 V pelados
el ADC se vuelve no lineal cerca del riel.

**El camino del sync sigue intacto.** `graficar_captura.py` usa el sync si la
columna trae algo distinto de -1, y la triangular si no. Si el sync aparece,
no hay nada que deshacer.

## `vivo.py` - radargrama en tiempo real (`vivo.bat`)

Agregado el 2026-09-04. Es `waterfall.py` pero dibujando mientras llega:
un hilo vacía el puerto y escribe `datos/captura.csv` y
`datos/triangular.csv`, y el hilo del gráfico trocea las rampas nuevas cada
200 ms. Lo que se ve en vivo queda grabado, así que se puede volver a
analizar después con los scripts de siempre.

La ventana tiene cuatro zonas: los controles **todos a la izquierda**, en
cuadros de texto (Enter para aplicar) y botones; en el centro el radargrama
**vertical** (distancia en x, tiempo en y, la fila más nueva abajo de todo)
y debajo la **FFT de esa última fila** compartiendo el eje x; y a la derecha
el **cuadro de información de la captura** y, abajo, la **triangular
plegada**.

Cuadros: `rampas/col`, `ventana [s]`, `alcance [m]`, `piso`/`techo` [dB],
`ignorar < [m]` y `dist. real [m]`. Botones: `eje: m <-> Hz`, `tomar punto`,
`calibrar`, `borrar cal`. Teclas: `e` (lo mismo que el botón de eje) y `a`
(autoescala el color). El alcance se tipea siempre en metros y se convierte
solo al pasar a Hz.

### Fondo y puerta de detección

Agregado el 2026-09-04, porque sin blanco el programa igual informaba una
distancia: al normalizar al máximo de la pantalla, el eco fijo de la sala
sube a 0 dB y aparece un pico donde no hay nada.

Con la sala vacía, **`medir fondo`** promedia `FONDO_S` (3 s) y guarda ese
perfil. A partir de ahí:

1. **Se resta** de lo que se mide, así los ecos fijos salen de la pantalla.
   Es resta en amplitud con piso en cero: lo que se guarda son magnitudes de
   FFT, no complejos, o sea que no hay cancelación coherente posible.
2. **La referencia de dB pasa a ser fija** (el pico del fondo) en vez del
   máximo de la pantalla. Esto es lo que arregla la distancia inventada, y de
   paso hace que la escala de color quiera decir siempre lo mismo.
3. **Puerta de energía**: sólo si la energía medida supera a la del fondo por
   `margen` dB (cuadro de texto, 6 dB por defecto) se declara que hay blanco.
   Si no, `pico_crudo()` devuelve `None`, la marca de la FFT se va del gráfico
   y la traza roja se corta.

**La energía de la puerta se calcula sobre la señal CRUDA**, no sobre la que
ya tiene el fondo restado: "la energía medida supera a la del fondo por un
margen" es literalmente eso. Restando primero, el cociente daría casi cero
siempre y no sería comparable con nada.

Los 6 dB de `MARGEN_DEF` quieren decir que el blanco tiene que aportar unas
3 veces la energía de todo el fondo. El panel muestra la energía actual en
vivo, así que ajustarlo es mirar el número y tipear.

Medido sobre una escena sintética con un eco fijo en 2,0 m y una placa que
aparece a los 40 s en 1,20 m:

| | sin fondo medido | con fondo medido |
|---|---|---|
| sala vacía | informa **1,997 m** (el eco) | `sin blanco`, +0,02 dB, traza 0/187 |
| con la placa | — | `HAY BLANCO`, +6,8 dB, pico **1,205 m** |

**Medir el fondo mueve `piso` y `techo`** a `PISO_FONDO`/`TECHO_FONDO`
(−20/+20). Cambia el significado del 0 dB, así que los límites viejos
recortaban el pico y parecía un error; `borrar fondo` los devuelve.

Cambiar `ignorar < [m]` recalcula la energía y la referencia del fondo sobre
la zona nueva (`_recalcular_fondo()`): si no, la puerta compararía dos zonas
distintas.

**La traza roja del radargrama** marca el pico de cada fila. Una fila cuyo
pico no se despega `TRAZA_MIN_DB` (3 dB) de la mediana de esa fila sale
`NaN` y la línea se corta: con la escala de dB automática, cualquier fila de
puro ruido igual tiene un máximo, y unirlos dibujaría un blanco que no
existe. Probado con un blanco sintético alejándose de 1 a 3 m: la traza lo
sigue en las 250 filas.

**El eje de distancia arranca siempre en 0**, no en `eje[0]`: con una
calibración de offset negativo el eje crudo empieza en un número negativo, y
arrancar ahí movería el cero de lugar cada vez que se recalibra.

**La triangular se dibuja PLEGADA en fase**, no como serie de tiempo. A ~188
lecturas/s son 7,5 puntos por período, que sueltos parecen ruido; plegando
los últimos `VENTANA_AJUSTE_S` se ven ~940 puntos sobre un período y la forma
(y cualquier recorte) salta a la vista. Es además la misma vista sobre la que
`ajustar_triangular()` hace el ajuste.

Los controles reagrupan TODO lo que hay en pantalla, no sólo lo que venga de
ahí en más, porque se guardan los perfiles de a UNA rampa y el agrupado se
rehace en cada refresco. Manda la ventana: la cantidad de filas sale de ella
y de rampas/col.

**El buffer de perfiles guarda el doble de lo que pide la ventana más larga.**
Antes tiraba la mitad al llenarse, y con una ventana grande la pantalla
colapsaba a la mitad del tiempo pedido y volvía a crecer, en ciclo, cada vez
que se llenaba — se veía como que el radargrama "se reinicia mucho". Ahora al
llenarse descarta sólo el excedente y siempre quedan `necesarios` perfiles, o
sea una ventana máxima entera. Medido: 120 s pedidos dan 119,8 s constantes a
lo largo de 2,5 vueltas de buffer.

## La triangular se vio recortada: era el divisor desconectado

**Resuelto el 2026-09-04.** Se había soltado una resistencia del divisor
4k7/4k7, así que GPIO3 veía la triangular ENTERA en vez de la mitad. El ADC
del C3 llega a ~2,5 V, la triangular es de 3 V, y todo lo que pasaba de 2,5
se aplastaba contra 4095.

Los números cierran solos:

| | |
|---|---|
| saturación predicha para 3,0 V entrando sin dividir | 16,7 % |
| saturación medida sobre `datos/triangular.csv` | 18,1 % |
| amplitud del generador recalculada sin divisor | 2,70 Vpp |
| pendiente real / la que asume el código | 0,90× |

O sea el generador daba sus ~3 V, el barrido es el que creemos y `alpha0`
está bien. El 0,90 es la incertidumbre de dónde satura exactamente el ADC
(se asumió 2,5 V), no un error real.

**Ojo con lo que esto NO explica.** Durante un rato la hipótesis fue que la
triangular era de 5,4 Vpp y que eso escalaba las distancias 1,8×. Era falsa:
salía de calcular los volts asumiendo el divisor que justamente no estaba.
**El error de distancia (una placa a 1 m leída en 4 m) sigue sin explicación.**
No es la BW (medida, 1 GHz), no es `T` (medido del ajuste, 40,00 ms) y no es
la amplitud del barrido. Lo que queda por descartar es si lo que se veía en
4 m era la placa o era otra cosa.

**El recorte no arruinó las capturas viejas.** El divisor alimenta sólo el
monitoreo de GPIO3; la señal de batido viene del PCM1808 por I2S y no pasa
por ahí. Y el recorte de la triangular es simétrico respecto del mínimo, así
que no sesga la fase del ajuste: el período salió 39,999 ms contra 40,00
nominal. Los límites de rampa de esas capturas son buenos.

**`Vivo.saturacion()` se queda.** Encontró una resistencia suelta a partir
del histograma, que es exactamente para lo que está. Con el divisor puesto,
GPIO3 ve 1,5 V de pico = ~2450 cuentas, con margen de sobra.

El umbral de aviso es `UMBRAL_SAT` = **5 %**, no 2 %: con la triangular sana
el vértice de abajo roza el cero y el 2 % saltaba sin motivo (se vio en el
banco, `!! TRIANGULAR RECORTADA 2%` con todo bien). Con la triangular
entrando sin dividir el recorte fue del 18 %, así que 5 % separa bien los dos
casos.

## La distancia del eje NO es de fiar sin calibrar

Medido en el banco (2026-09-04): una placa a **1 m** aparecía en **4 m**.
El eje crudo sale de `alpha0 = BW/T` con la BW nominal de la curva del VCO, y
en el banco real no da.

`vivo.py` calibra con dos blancos de distancia conocida y ajusta
`d_real = a·d_crudo + b` (`a` corrige la pendiente, o sea la BW efectiva; `b`
el retardo fijo de cables y electrónica). Queda en
`datos/calibracion_distancia.json` y se carga sola.

**Ojo con lo que la calibración tapa.** Un factor de 1,1 o 1,2 es retardo y
tolerancias. Un factor de **4 no**, y a hoy no está explicado: no es la BW
(medida, 1 GHz), no es `T` (medido, 40,00 ms) y no es la amplitud del barrido
(verificada arriba). Por eso `_calibrar()` imprime la BW efectiva que implica
la pendiente y avisa si se va lejos de 1: **es un dato de hardware, no un
número de ajuste.**

La medición que lo decide, con el panel de FFT nuevo: poner la placa a 1 m y
anotar dónde cae el pico, moverla a 2 m y anotar de nuevo. La predicción es
**346 Hz por metro** (`2·alpha0/c` con `alpha0 = 1039 MHz / 20 ms`). Si el
pico se corre 346 Hz/m, el eje está bien y lo que se veía en 4 m era otra
cosa (clutter, reflexión de la sala, un armónico). Si se corre ~4× eso,
entonces sí `alpha0` está mal y hay que buscar por qué. Acordarse de poner
`ignorar < [m]` por encima del acoplamiento directo TX->RX, que vive cerca de
cero y se lleva puesto cualquier `argmax`.

**El timer tiene que terminar en `draw_idle()`.** Mutar los artistas
(`set_data`, `set_title`) no repinta por sí solo: sin esa llamada la pantalla
se queda congelada y lo único que la despierta es mover un slider, así que
parece que el programa anda pero la imagen no avanza. Está en un `finally`
para que una excepción adentro del refresco no congele la ventana para
siempre.

**La FFT de cada rampa va con relleno ×8**, igual que `graficar_captura.py`.
Sin relleno, 120 muestras por rampa dan 61 bins para todo el eje y el
radargrama sale en bandas gruesas. El relleno **no agrega resolución** — el
ancho de bin real vale `c/(2·BW)` = 14,4 cm y eso no lo cambia nada, sólo más
ancho de banda del VCO — pero interpola y deja ver la forma de los picos.

Los perfiles van a un buffer numpy preasignado, no a una lista: con relleno
×8 son ~500 números por perfil y la ventana puede pedir miles, así que armar
un array nuevo en cada refresco sería copiar decenas de MB cinco veces por
segundo.

**El ajuste de la triangular se rehace cada `REAJUSTE_S` (2 s).** No es por
la deriva de reloj entre el generador y el ESP32: una diferencia constante
de reloj le da al C3 un período constante, y el ajuste lo mide igual de
bien. Es porque el período medido tiene un error residual y cada rampa se
ubica multiplicando ese período por su índice, así que el error de los
límites crece lineal con el tiempo desde el ajuste. Medido con 200 ppm de
deriva contra los vértices verdaderos:

| | error del límite de rampa |
|---|---|
| con reajuste cada 2 s | 9 µs = 0,05 % de la rampa |
| sin reajuste, a los 60 s | 1095 µs = **5,40 %** |

Probado de punta a punta contra un stream sintético (blanco a 1,20 m,
triangular de 40,6 ms, 200 ppm de deriva, 60 s): el período sale con 1 ppm
de error, los límites con menos de 0,1 muestra, y el pico se queda quieto en
el bin correcto con cualquier valor del slider.

## `fs_theta()`: la fs de la señal remuestreada no es `FS_CSV` ni `n/span`

`remuestrear()` arma la grilla con `linspace(theta[0], theta[-1], n)`: son
`n` puntos y `n-1` pasos. La fs efectiva es `(n-1)/(theta[-1]-theta[0])`, y
eso es lo que devuelve `fs_theta()`. Las dos versiones que había escalaban
todas las distancias, igual que el problema de `T_SWEEP` de la sección de
abajo, sólo que menos:

| | error de escala |
|---|---|
| `graficar_captura.py` usaba `n/(th[-1]-th[0])` | +0,83 % |
| `waterfall.py` usaba `FS_CSV` | +0,27 % |

`theta` no termina en `T` sino en `(f(t_ultimo)-f(0))/alpha0`, y la curva del
VCO no es lineal, así que ninguna de las dos aproximaciones sale bien sola.

## `eje_theta()` ya no lee `T_SWEEP`: saca la duración de su propio `t`

Cambiado el 2026-09-04, antes de las primeras mediciones reales.

`eje_theta()` calculaba `alpha0 = bw / T_SWEEP` leyendo la constante global,
y `extraer_rampas()` cortaba siempre `n = round(T_SWEEP * FS)` muestras aunque
midiera la distancia real entre reinicios de sync. Con un generador de
laboratorio la rampa dura lo que dura, y esa diferencia escalaba `alpha0` y
corría TODAS las distancias sin que nada avisara. La tolerancia del 10 % de
`extraer_rampas()` se tragaba el error en silencio.

Medido, con un blanco sintético a 1,20 m y `T_SWEEP` nominal de 20 ms:

| rampa real | con la constante | con el largo medido |
|---|---|---|
| 20,00 ms | −0,8 % | −0,8 % |
| 20,60 ms | **−3,8 %** | −0,8 % |
| 21,60 ms | **−8,3 %** | −0,8 % |

El error seguía uno a uno al desajuste. El −0,8 % que queda es cuantización
del bin de la FFT, no del método.

Ahora:

- **`eje_theta(curva, t)` deduce `T` de `t`** (`T = t[-1] + paso`), no de la
  global. Los llamadores ya armaban `t` con `linspace(0, T, n,
  endpoint=False)`, así que la duración real siempre estuvo ahí adentro. Si
  le pasás un `t` con `endpoint=True` te va a sobrestimar `T` en un paso.
- **`medir_rampa(sync, n_nominal)`** (nueva) devuelve el largo real de la
  rampa en muestras, de la mediana de las distancias entre reinicios.
  Compara contra `n` y contra `2n` para no tener que saber si el generador
  marca por rampa o por ciclo, igual que `extraer_rampas()`. Devuelve `None`
  y avisa si la medición difiere más del 20 % de la nominal.
- `graficar_captura.py`, `waterfall.py` y `correr_csv()` la usan y con eso
  arman `t`. `correr_sintetico()` sigue con la nominal, que ahí es correcto.

`T_SWEEP` pasa a ser sólo el valor **nominal**, para dimensionar y para
detectar que algo está muy lejos de lo esperado. El que manda es el medido.

## El generador de laboratorio es TRIANGULAR, no diente de sierra - ya manejado

Confirmado (2026-09-02): el generador real usa triangular, no diente de
sierra como el banco casero de Martin. `extraer_rampas()` en
`correccion_no_linealidad.py` resuelve el pendiente que Martin había dejado
anotado ("hay que dar vuelta la bajada en el tiempo antes de aplicarle el
mismo mapa θ"):

- Mide la distancia real entre reinicios de `sync`, sin asumir si el
  generador marca una vez por rampa de subida o una vez por ciclo completo.
- Si la distancia es ~`n` (una subida sola): la usa tal cual.
- Si es ~`2n` (ciclo completo subida+bajada): usa la subida tal cual Y
  ADEMÁS la bajada, invertida en el tiempo (`[::-1]`) - el batido de una
  bajada simétrica leído al revés es igual al de una subida, así que se le
  puede aplicar el mismo mapa θ. Esto además DUPLICA la cantidad de rampas
  utilizables por segundo.
- Cualquier otra distancia (sync perdido o irregular) se descarta y se
  cuenta aparte.

Validado con dos triangulares sintéticas (sync una vez por rampa, y una vez
por ciclo completo con bajada invertida): el pico cae en la distancia
correcta en los dos casos, en las 100% de las rampas de la prueba.

`graficar_captura.py` y `waterfall.py` ya usan `extraer_rampas()` en vez de
cortar a ciegas. **Lo único que sigue siendo necesario verificar en el
banco real**: que el reinicio de `sync` efectivamente caiga al PRINCIPIO de
la subida (no en la bajada ni en un punto arbitrario del ciclo) - mirar el
panel 1 de `graficar_captura.py` (señal cruda + sync superpuestos) y
confirmar que el tramo justo después de cada reinicio se ve como un barrido
limpio ascendente. Si en cambio se ve una bajada ahí, el sync del generador
está desfasado medio ciclo respecto de lo asumido, y hay que correrlo (ese
caso puntual todavía no está cubierto).

## Estado del banco — 2026-09-01

| | Valor | Dónde vive |
|---|---|---|
| Rampa | **10 ms** (PRF 100 Hz) | `T_SWEEP` en `analisis/correccion_no_linealidad.py` |
| Salida por serie | **4000 sps** | `SPS_SALIDA` en `firmware/adquisicion/` y `FS_CSV` en los scripts |
| Formato del CSV | **`L,sync`** | `firmware/adquisicion/adquisicion.ino` |
| Blancos simulados | 0,60 y 1,20 m → 416 y 832 Hz | `BLANCOS` en `analisis/generar_tabla_chirp.py` |
| SNR | −11,6 dB crudo, +5,2 dB en el pico | `AMPLITUD` y `RUIDO` |

## Lo que cambió el 2026-09-01, y por qué

Se pasó el banco de casa de 50 ms de rampa a 10 ms, y se subió mucho el ruido
para simular el laboratorio. Tres cosas dejaron de valer:

1. **`T_SWEEP` pasó de 50e-3 a 10e-3** en `correccion_no_linealidad.py`.
   A 50 ms el blanco de 0,6 m da 83 Hz de batido; a 10 ms da 416 Hz, bien
   arriba del corte de 19 Hz del pasabajos post-mezclador del laboratorio.
   Con 50 ms se estaba simulando algo que allá no se puede medir.

2. **`FS_CSV` pasó de 2000 a 4000** en `correccion_no_linealidad.py` y en
   `waterfall.py`. El batido llega ahora a 1096 Hz y con 2000 sps el Nyquist
   quedaba en 1000.

3. **El CSV perdió la columna R.** Antes era `L,R,sync`, ahora es `L,sync`.
   VINR está al aire y esos bytes eran caudal tirado, que a 4000 sps hacía
   falta. `.iloc[:, 0]` sigue dando el canal L, así que `correr_csv()` y
   `waterfall.py` no se rompen por esto; pero cualquier código que lea la
   columna 2 esperando el sync ahora tiene que leer la 1.

**Si volvés a medir con rampa de 50 ms**, hay que revertir 1 y 2. Son
constantes del banco, no del algoritmo.

## Cosas que conviene no volver a descubrir

- **El ancho de bin de la FFT vale `c/(2·BW)` sea cual sea `fs`.** Diezmar no
  cuesta resolución en distancia; lo único que `fs` fija es el alcance no
  ambiguo. Medido: 14,4 cm de bin a 48000, 16000 y 2000 sps por igual.
- **`perfil_distancia()` no rellena con ceros.** Con rampas cortas quedan
  pocos puntos por pico y no se ve la forma. `graficar_captura.py` hace su
  propia FFT con relleno ×8 justamente por eso.
- **Las rutas de `correccion_no_linealidad.py` y `waterfall.py` son relativas
  al directorio actual**, no al archivo: sólo corren parados en
  `GPRv2/analisis/`. Los archivos nuevos usan `os.path.dirname(__file__)`.
- **No abras el puerto del ESP32-C3 con DTR/RTS afirmados.** pyserial los
  afirma a los dos por defecto en `serial.Serial(puerto, ...)`, y en el USB
  nativo del C3 esa combinacion es la de reset: el chip se reinicia, el USB se
  re-enumera y el handle queda invalido. El `open()` parece andar y el `write()`
  posterior falla con `WriteFile failed (PermissionError(13, 'El dispositivo no
  reconoce el comando.', None, 22))`. Hay que construir el `Serial()` vacio,
  poner `dtr = False` y `rts = False`, y recien ahi `open()` - como hace
  `grabar_rampa.py`.
- **`pandas` hace falta** y no venía en el venv `gpr-win`. Ya está instalado.
- **No cambies el interpolador de `remuestrear()` buscando SNR.** Medido sobre
  señal limpia, el error contra el resultado analítico es el mismo para
  cúbica, lineal, gaussiana angosta y Lanczos: −8,2 a −8,4 dB. Con 40
  muestras por rampa el límite es información, no método.

  Cuidado con la métrica de pico sobre piso: **mejora con cualquier cosa que
  filtre**, aunque la medición empeore. Una gaussiana de σ=1,0 muestra de
  lejos el mejor número (22,8 dB contra 5,2 del cúbico) y al mismo tiempo
  pierde el blanco de 1,2 m, devolviendo 611 Hz en vez de 832. El cúbico da
  el número más bajo justamente porque es el que menos suaviza.

  Si hace falta atenuar ruido arriba de la banda útil, **hacelo con un
  pasabajos explícito y verificá con las posiciones de los picos**, no
  cambiando el interpolador. Un filtro escondido adentro del remuestreo no se
  puede auditar.

  `AMPLITUD` y `RUIDO` están calibrados contra el pipeline completo tal como
  está; si se cambia el remuestreo, hay que recalibrarlos.
- El generador del banco emite un **diente de sierra**, no una triangular.
  Con triangular el sync viene a la mitad de frecuencia (un pulso por
  período, o sea dos rampas) y la rampa de bajada barre al revés: hay que
  darla vuelta en el tiempo antes de aplicarle el mismo mapa θ.
