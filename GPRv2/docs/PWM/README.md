# Generador de triangular (reemplazo del SDG830)

Schmitt + integrador que barre el VCO: triangular de ~0 a 3 V (medida 0,36–3,36 V)
de 20 a 275 ms de período, con la cuadrada como sync hacia GPIO10 del ESP32-C3.
Hoy está armado con **LM324** (680k ∥ R5 y 2 × 680k ∥ R2) a 12 V.

```
PWM/
  simulacion/   LTspice: circuitos, modelos y figuras
  pcb/          proyecto KiCad 10 de la placa
  mediciones/   capturas del osciloscopio y del analizador de espectro, con sus análisis
```

Python: `C:\Users\tinch\venvs\gpr-win\Scripts\python.exe`. LTspice 24:
`C:\Program Files\LTC\LTspice.exe`.

## `simulacion/`

**Los modelos están al lado de los `.asc` a propósito**: los símbolos (`.asy`) traen
su `SpiceModel` sin ruta y LTspice los busca en la carpeta del circuito. No moverlos.

| circuito | qué es |
|---|---|
| `PWM.asc` | el PWM original de Circuitos II (~135 kHz), base del resto |
| `triangular.asc` | paso 1: Schmitt TL072 + integrador llevado a ~10 Hz |
| `triangular2.asc` | paso 2: restador a 0–3 V y buffer del sync (UniversalOpAmp2) |
| `triangular3.asc` | paso 3: con TLC2272 real y zener 1N4729A en la salida |
| `triangular3_LM324.asc` | lo que está armado: LM324 con los paralelos de R5 y R2 |

| modelo | |
|---|---|
| `TLC2272.lib/.asy`, `TLC2262.lib/.asy`, `TL072.sub/.asy`, `LM324.sub/.asy` | operacionales |
| `zener_1N472xA.lib`, `1N4729A.asy` | zeners de Diodes Inc. |

Scripts: `graficar_triangular2.py` y `graficar_triangular3.py` leen el `.raw` y arman la
figura del paso. `zener.bat` corre `simular_zener.py` (variantes del netlist de la placa,
a `zener/`), `graficar_zener.py` y `tolerancias.py`. `ruido_opamp.py` compara el ruido de
los modelos.

Para simular en batch sin que se cuelgue: `LTspice.exe -netlist x.asc` y después
`LTspice.exe -b x.net`.

## `pcb/`

Abrir `triangular.kicad_pro`. Las huellas propias (llave, puente de cable) están en
`triangular.pretty/`, que el `fp-lib-table` busca con `${KIPRJMOD}`: tiene que quedar al
lado del proyecto. Verificado con `kicad-cli`: ERC sin errores, DRC sin pads sin conectar
y sin diferencias con el esquemático (queda solo un aviso de que RV1 no coincide con la
huella de la biblioteca, que ya estaba).

`simular_kicad.bat` exporta el netlist del esquemático y lo simula en LTspice
(`triangular_kicad.cir`, con los modelos de `../simulacion/`). Es la base de
`simulacion/simular_zener.py`.

## `mediciones/`

| carpeta | qué hay |
|---|---|
| `2026-11-02_tanda1/` | osciloscopio, 20 / 100 / 275 ms, pocos períodos por captura |
| `2026-11-02_tanda2/` | osciloscopio, 20 / 101 / 273 ms, más períodos (81 / 15 / 30) |
| `2026-11-02_vco_maxhold/` | salida del VCO en el SSA3032X, Max Hold de 0,8 a 3 GHz |
| `2026-11-06-tektronix_triangular/` | Tektronix TBS1102B a 0,5 V/div: 20, 100 y 273 ms. La medición buena de la triangular |
| `2026-11-06-siglent_vco+triangular/` | zero span del VCO cada 25 MHz (995 a 1995 MHz), disparado por el sync, más un Max Hold |

- `analizar_tektronix.py [carpeta]` — una figura por captura del Tek (`ALL000x_analisis.png`).
- `analizar_zerospan.py [carpeta]` — f(t), df/dt, f(V) contra la curva estática y desvío de
  una recta; los puntos medidos quedan en `zerospan_puntos.csv` (base del mapa θ).

**Resultados del 2026-11-06:** triangular de 0,12 a 3,06 V con no linealidad de 0,1–0,3 %
(el ~1 % y el escalón de 0,95 V que mostraba el Siglent eran del osciloscopio), subida y
bajada con ~3 % de diferencia de pendiente. El VCO barre **983 a 1999 MHz** (1016 MHz),
la subida dura 50,5 ms y la bajada 49,4 ms, df/dt va de ~14 a ~27 MHz/ms y f(t) se aparta
hasta ~78 MHz de una recta.

- `analizar_mediciones.py [carpeta]` — período, ciclo útil, linealidad, espectro contra una
  triangular ideal y huecos en el registro. Cada carpeta tiene su asignación
  archivo → posición del pote en `CARPETAS`, adentro del script. Escribe las figuras y
  `mediciones_triangular.json` en la carpeta de la tanda.
- `analizar_vco_maxhold.py [carpeta]` — banda que barre el VCO y su 2º armónico.

**Lo que conviene saber de las capturas:**

- Las dos tandas están a **1 V/div**: el escalón del osciloscopio es de 40 mV. Para la
  próxima, 0,5 V/div con −1,7 V de offset.
- Las "conmutaciones antes de tiempo" que se veían con el pote al máximo **eran huecos en
  el registro del osciloscopio**, no el generador: la triangular sigue como si se hubiera
  cortado un pedazo de señal y los flancos siguientes llegan adelantados justo ese tiempo
  (49 ms medidos contra 52 predichos, 15,2 contra 15,7). Aparecen a 100 ms/div y más
  lento; a 50 ms/div o más rápido, ninguno. La figura es `huecos_registro.png`.
- La triangular de la tanda 2 está ~0,15 V más alta que la de la tanda 1. Se usa así y se
  corrige en el código.
- **Armónicos del VCO**: ver la sección "Pendiente: armónicos del VCO" en `GPRv2/CLAUDE.md`.

## Conclusiones y decisiones (2026-11-07 al 2026-11-09)

Notas para el escrito de la tesis.

**El 2.º armónico se sacó de las figuras del zero span** (2026-11-07). `analizar_zerospan.py`
descarta los pulsos de arriba de 1950 MHz que caen cerca del vértice de abajo
(`es_armonico()`), y en las trazas los tapa con la mediana. Quedan 91 puntos, todos de la
fundamental. Como esos puntos marcaban el borde de abajo, `f_min` sale del ajuste y pasa
de 985 a **983 MHz**. El resto no cambió. El Max Hold (`vco_maxhold.png`) queda con el
armónico, porque ahí es lo que se mide.

**Lo que muestran las mediciones del 2026-11-06.**

- La triangular es muy lineal (0,1–0,3 % con el Tek) y sus armónicos impares caen donde
  los pone una triangular ideal. El ~1 % y el escalón de 0,95 V eran del Siglent, aunque
  también pesó haber medido a 1 V/div y en modo scan.
- La no linealidad del chirp es casi toda del VCO. f(V) en barrido coincide con la curva
  estática con 10–20 MHz de diferencia entre 1,5 y 2,6 V. Los ~80 MHz de desvío de una
  recta y el df/dt de 14 a 27 MHz/ms son de la curva del VCO, que es lo que corrige el
  remuestreo.
- No hay recorte en los extremos y el período es estable (46 trazas que cierran en una
  curva continua con ~4 MHz rms de residuo).
- Subida y bajada difieren ~3 % en pendiente (50,5 y 49,4 ms). Cada rampa necesita su
  propio mapa θ.
- La resolución del zero span es acotada (cada 25 MHz, ~2,7 MHz por punto de traza), así
  que los picos puntuales de df/dt tienen bastante incertidumbre. f(t) está bien
  determinada.

**Repetibilidad.** Se da por demostrada para la **curva del VCO**, con tres mediciones en
días distintos que dan casi lo mismo (la primera, una en un día de mucho calor y la del
2026-11-06 en barrido). Lo que no está demostrado es el **nivel de continua de la
triangular**, que se corrió ~0,15 V entre la tanda 1 y la 2 con el mismo osciloscopio
(en la zona media del VCO son ~50 MHz). Se compensa en el código. Para cerrarlo alcanza
con medir los vértices con el Tek en dos o tres encendidos.

**Las capturas del ADC no saturan** (2026-11-09). Revisadas las 10 capturas del PCM1808 en
`GPRv2/datos/` (18/9 y 28/9), fondo de escala ±8 388 608 cuentas (±1,5 V).

| captura | pico | margen hasta saturar | rms | piso 2,5–2,9 kHz |
|---|---|---|---|---|
| 18/9 (6 capturas) | 37–46 % FS | 6,7–8,7 dB | −16 a −20 dBFS | −61 a −74 dBFS |
| 28/9 17:37 y 17:42 | 30 % FS | 10,5 dB | −20 dBFS | −69,5 dBFS |
| 28/9 17:53:54 | 43 % FS | 7,4 dB | −17 dBFS | −62,5 dBFS |
| 28/9 17:53:18 (casi sin señal) | 0,2 % FS | 56 dB | −64 dBFS | −105 dBFS |

- Ninguna muestra pasa del 95 % del fondo de escala. Quedan 7 a 10 dB de margen, así que
  una ganancia de ×2 ya las dejaría al borde. Lo que domina la amplitud es el
  acoplamiento directo entre antenas (pico de 380–620 Hz, a −19/−25 dBFS).
- **La ganancia no mejoraría la relación señal/ruido.** El piso propio del ADC y la IF es
  ~−105 dBFS por bin (captura casi sin señal, probablemente con la RF apagada). Con el
  radar andando el piso está 30 a 40 dB más arriba, o sea que viene de antes del ADC
  (mezclador, ruido de fase, clutter, desparramo del chirp no lineal). Un amplificador
  sube señal y piso por igual. El espectro se calculó en bloques de 300 muestras sin
  alinear con las rampas, así que parte del piso puede ser desparramo de los vértices.
- Si hiciera falta más ganancia (blancos lejanos y débiles), el lugar es la RF, no la IF.

**Pasabajos de audio con potenciómetro (500 Hz a 2 kHz), descartado por ahora**
(2026-11-09). La idea era cortar todo lo que está "fuera de rango" para sacar el fantasma
en 2·fd que deja el 2.º armónico. No conviene en analógico.

- Entre fd y 2·fd hay una sola octava. Una octava arriba de fc un RC atenúa ~7 dB, un
  Butterworth de orden 2 ~12 dB y uno de orden 4 ~24 dB. Como fc tiene que quedar algo
  arriba de fd, en 2·fd es todavía menos. Solo un elíptico de orden 8 (por ejemplo el
  MAX7400 de capacitor conmutado, con fc fijada por un clock del ESP32) separa bien una
  octava.
- Como el ADC no satura, el fantasma entra digitalizado sin comerse rango dinámico.
  **Sacarlo en software alcanza y es mejor** (corte de distancia ajustable en `vivo.py`,
  o restarlo, porque su posición y su fase se conocen).
- En los dos casos, si hay un blanco real más lejos, el corte también lo borra.

Por eso se pasó a filtrar el armónico en RF, en la rama de TX. Ver
[`../FILTRO_RF/README.md`](../FILTRO_RF/README.md).
