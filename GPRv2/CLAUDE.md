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
