# GPRv2 — notas para Claude

Este archivo se carga solo al trabajar en `GPRv2/`. Está para que ninguna
sesión trabaje con parámetros viejos.

`GPRv2/CONTEXTO.md` sigue siendo el documento que manda. Esto es sólo el
estado actual del banco, que cambia más seguido.

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
