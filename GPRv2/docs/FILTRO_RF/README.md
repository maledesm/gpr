# Pasabajos de RF impreso para el 2.º armónico del VCO

Bitácora del diseño, con las decisiones, los porqués y los problemas encontrados, para
pasar después al escrito de la tesis. Empezado el 2026-11-09. El diseño lo hace Martín
paso a paso, siguiendo **estrictamente** a Hong y Lancaster, *Microstrip Filters for
RF/Microwave Applications* (Wiley, 1.ª ed., 2001), que está en
`referencias/Microstrip Filters for RF-Microwave Applications.pdf` (página del PDF =
página del libro + 12).

## 1. Para qué

Con el generador de triangular propio barriendo el VCO, el analizador mostró un **2.º
armónico a −8/−9 dBc** (ver `docs/PWM/` y la sección de armónicos de `GPRv2/CLAUDE.md`).
El radar es homodino, así que el armónico de TX batiendo con el armónico del LO da un
**fantasma al doble de la distancia aparente** (2·fd, con fase 2φ).

- **La banda y su armónico se tocan.** El VCO barre 983–1999 MHz y el 2.º armónico va de
  1966 a 3998 MHz. Como f_max > 2·f_min, ningún pasabajos separa todo. Con el rechazo
  desde ~2,3 GHz se escapa el armónico de la fundamental entre 983 y ~1150 MHz, que es
  el ~15 % de cada rampa (principio de la subida y final de la bajada).
- **Lo que se escapa cae en el borde de la rampa**, donde la ventana de Hann pesa ~2 %.
  Estimación rápida (fantasma parejo a lo largo de la rampa) de ~30 dB menos de
  fantasma. Falta confirmarlo con `simulaciones_meep/armonicos/`.
- **Dónde va: antes del splitter** (decidido 2026-11-10, como dice la tesis en
  `sub:armonicos_requisitos`). Así su retardo de grupo es común al LO y al eco y se
  cancela en el mezclador, y la atenuación cuenta dos veces (LO y eco). Al principio
  (2026-11-09) se había pensado en la rama de TX después del PA; quedó descartado.
  El límite que queda es el espurio 2×2 del propio mezclador (típicamente −60 dBc o
  menos en un doblemente balanceado).

Antes de esto se descartó el filtrado en banda base, porque entre fd y 2·fd hay una
sola octava y porque el ADC no satura (ver `docs/PWM/README.md`, 2026-11-09). Sacar el
fantasma en software sigue siendo una opción complementaria.

## 2. Decisiones de entrada (2026-11-09)

| | decisión | por qué |
|---|---|---|
| topología | impedancia escalonada + stubs resonantes (pasabajos elíptico, cuasi-elíptico en la placa) | los stubs ponen ceros de transmisión sobre la banda del armónico. Un Chebyshev de n = 9 no llega ni a 20 dB a 2,3 GHz |
| componentes | ninguno, solo pistas | pedido de Martín. A 2 GHz los valores son de nH y fracciones de pF, del tamaño de pistas de milímetros |
| placa | FR4 de 1,6 mm, **bifaz** (pistas arriba, masa entera abajo) | Rogers no se consigue en Argentina. Con 1,6 mm las pistas son más anchas y la tolerancia absoluta del fabricante pesa menos en porcentaje |
| conectores | SMA | |
| banda de paso | hasta **fc = 2,05 GHz**, ripple 0,1 dB | el VCO llega a 1999 MHz, el margen cubre la incertidumbre del FR4 |
| rechazo | desde **~2,35 GHz**, ≥ 20–25 dB, hasta ≥ 4 GHz (ideal 6) | 2.º armónico hasta 4 GHz, 3.º de 2,95 a 6 GHz |
| εr | **4,4** nominal en todo | el FR4 es genérico y el fabricante no da εr. CST usa 4,3 para su "FR-4 (lossy)", pero se decidió no rediseñar |

**Libros consultados.** Hong (el que manda), Pozar *Microwave Engineering* (cap. de
filtros, el más didáctico), Matthaei-Young-Jones (tablas clásicas) y Zverev (tablas de
elípticos).

## 3. Diseño según Hong (`diseno_hong.py` → `diseno_hong.json`)

Cada paso del script cita su ecuación. Se validó contra el ejemplo resuelto de la
sección 5.1.3, que da lL2 = 2,96 mm y lC2 = 5,62 mm contra 2,98 y 5,61 del libro (el
libro redondea λg a milímetros enteros en su Tabla 5.3).

### Paso 2. Prototipo (Tabla 3.3, p. 45, y Figura 3.11b)

La Tabla 3.3 es para LAr = 0,1 dB y g0 = g(n+1) = 1. Cómo se usa:

1. Se normaliza Ωs = fs/fc. Para nosotros 2,35/2,05 = 1,146.
2. Para cada n la tabla trae varias filas (Ωs, LAs). Ωs más chico da un corte más
   abrupto pero menos atenuación. Se toma la fila más cercana, que es **Ωs = 1,1494**
   (rechazo desde 2,356 GHz, 6 MHz arriba de lo pedido, aceptado).
3. En la red de la Figura 3.11(b) los g impares son L en serie, los g pares son la C de
   cada rama a masa y los primados la L en serie con esa C. Cada rama pone un cero en
   Ω = 1/√(g·g').
4. Se verifican siempre los ceros (así apareció la errata de n = 7).

Antes de tener el libro se sintetizó el prototipo numéricamente (scipy, transferencia
elíptica exacta y ajuste de la escalera). Para Ωs = 1,20 da los mismos g que la tabla
hasta el 4.º decimal, en orden inverso (es el mismo filtro dado vuelta). Eso validó el
método, pero desde ahí se usan solo los valores del libro.

| diseño | n | Ωs | LAs | g |
|---|---|---|---|---|
| **A** | 5 | 1,1494 | 24,5 dB | 0,8726 · 1,0084 / 0,3845 · 1,3097 · 0,4991 / 1,4450 · 0,4302 |
| **B** | 7 | 1,1494 | 45,7 dB | 1,0252 · 1,2157 / 0,1940 · 1,5811 · 0,9939 / 0,5816 · 1,2382 · 0,5243 / **1,4096** · 0,4369 |

### Paso 3. Escalado (ec. 5.6) y ceros (ec. 5.8)

L = g·Z0/ωc = g × 3,882 nH y C = g/(Z0·ωc) = g × 1,553 pF, con Z0 = 50 Ω y fc = 2,05 GHz.

| diseño | ceros (un stub cada uno, de entrada a salida) |
|---|---|
| A | 3,29 GHz y 2,41 GHz |
| B | 4,22 GHz, 2,70 GHz y 2,39 GHz |

El tercer cero del B (4,22 GHz) cae justo donde el A empieza a reabrir.

### Paso 4.1. Impedancias de línea, elegidas con peor caso de tolerancia

Hong (p. 110) da los criterios. Z0L alta se parece más a una L pero la pista es fina.
Z0C baja se parece más a una C pero el parche se ensancha y puede resonar a lo ancho.
Además el filtro reabre cerca de 2,8·fc (Figura 5.7), y subir Z0L acorta los tramos
finos y corre esa reapertura hacia arriba.

Martín pidió elegir con **la peor tolerancia posible**. Se armó el filtro con líneas de
transmisión, se ajustaron los largos al prototipo y se evaluaron las 8 esquinas de
ancho ±0,15 mm, εr 4,2–4,8 y h ±10 %.

| Z0L / Z0C | rechazo 2,41–4 GHz nominal | peor caso | reapertura > 4 GHz, peor caso |
|---|---|---|---|
| 90 / 25 | −12 dB | −8 dB | ~0 dB |
| 100 / 25 | −16,5 dB | −10,5 dB | −2 dB |
| 110 / 25 | −20,5 dB | −13,4 dB | −5 dB |
| **110 / 30** | **−20,4 dB** | **−13,8 dB** | **−5 dB** |

- **Elegido Z0L = 110 Ω (0,536 mm) y Z0C = 30 Ω (6,577 mm).** La línea de 50 Ω mide 3,066 mm.
- **La tolerancia que manda es el εr, no el ancho.** ±0,15 mm mueve el rechazo menos de
  0,5 dB, porque la inductancia la fija sobre todo el largo, que el grabado no cambia.
  εr de 4,2 a 4,8 corre los ceros ±3 % y empeora el rechazo ~4 dB.
- Impresa, la n = 5 no llega a los 24,5 dB del prototipo (~20 dB nominal, ~14 dB peor
  caso). De ahí salió la decisión de hacer **dos diseños**, A (n = 5 con stubs
  recortables con trincheta, midiendo con el tracking generator) y B (n = 7). Se
  piensan mandar a fabricar los dos.

### Paso 4.2 y 4.3. Largos (ec. 5.9) y corrección de las uniones (ec. 5.11)

La ec. 5.9 convierte cada L y C en un tramo de línea. La ec. 5.11 suma la capacidad que
aportan en cada unión las puntas de los tramos finos vecinos (ΔB123) y se resuelve en fc
y en el polo de cada stub. Los tramos serie quedan fijos, como en el libro. La ec. 5.10
no aplica (corrige un C final que los prototipos de n impar no tienen).

- **B usa Z0C = 20 Ω (11,113 mm).** Con 30 Ω la ec. 5.11 pedía un tramo fino de largo
  negativo (−1,1 mm) en el stub de 4,22 GHz, y con 25 Ω casi cero. Ese stub necesita
  mucha C (1,89 pF) y poca L' (0,75 nH), y un parche de 30 Ω para esa C ya aporta más L
  que la pedida. Se siguió el criterio del libro de bajar Z0C.
- **B alterna los stubs de lado** (+, −, +). Sus parches miden 11,1 mm y los stubs están
  a 10,78 y 8,03 mm, del mismo lado se pisarían. El libro no trata este caso.

### Paso 4.4. Extremo abierto (ec. 4.40)

Se resta Δl al largo de cada parche: 0,755 mm en el A y 0,812 mm en el B.

### Medidas finales (εr 4,4, h 1,6 mm)

| | tramos serie [mm] | stubs, fino + parche [mm] |
|---|---|---|
| **A** | 5,48 · 8,57 · 2,65 | 3,29 GHz: 1,04 + 7,91 · 2,41 GHz: 8,09 + 2,36 |
| **B** | 6,52 · 10,78 · 8,03 · 2,69 | 4,22 GHz: 0,44 + 6,25 · 2,70 GHz: 2,72 + 4,50 · 2,39 GHz: 8,35 + 1,26 |

Tramos finos de 0,536 mm. Parches de 6,577 mm (A) y 11,113 mm (B).

## 4. Erratas del libro

1. **Tabla 3.3, n = 7.** La columna g6' repite a g4' en todas las filas. Para
   Ωs = 1,1494 el valor correcto es **g6' = 1,4096**. Con el de la tabla (0,5816) el
   cero cae en Ω = 1,811, que no es cero de la función elíptica. Con 1,4096 cae en
   1,1633, que sí lo es. Detectado con la síntesis numérica y la verificación de ceros.
2. **Ec. 4.40, extremo abierto.** ξ1 está impreso como un solo cociente. El original es
   el producto (εre^0,81 + 0,26)/(εre^0,81 − 0,189) · (u^0,8544 + 0,236)/(u^0,8544 + 0,87).
   Así se reproduce el Δl = 0,54 mm del ejemplo (0,535 calculado). Con la versión
   impresa da 0,707 mm.

## 5. Verificación electromagnética (paso 4.5)

### Herramientas (2026-11-09)

- **openEMS 0.37.0**, nativo en Windows (`D:\openEMS`), con Python 3.13
  (`C:\Users\tinch\venvs\openems`). FDTD como el Transient de CST.
- **MEEP 1.35.1** en WSL (Ubuntu 24.04 en `D:\WSL\Ubuntu`), con MPI de 6 procesos.
- Plan de Martín, armado "como en CST", de lo ideal a lo complicado.

### Modelo openEMS (`openems/simular_filtro.py`)

| | |
|---|---|
| solver | FDTD, pulso gaussiano 1–7,5 GHz (a −20 dB) desde el puerto 1, fin a −50 dB de energía o al estancarse (< 0,5 dB en 2 min) |
| geometría | leída de `diseno_hong.json`, 10 mm de línea de 50 Ω a cada lado |
| masa | borde PEC en z = 0 |
| bordes | PML de 8 celdas en x (puntas de las líneas), MUR en y y arriba, 15 mm de aire |
| puertos | MSL de 50 Ω terminados en 50 Ω (`Feed_R`), plano de referencia en el borde del filtro |
| malla | λ/N a 7 GHz, ~0,13 mm en bordes de pista (regla de los tercios), 4 celdas a lo ancho de la línea fina y 4 en el sustrato |
| conductor | `pec` (espesor cero), `sheet` (lámina de cobre σ = 5,8·10⁷, t = 72 µm, geometría plana) o `thick` (bloque 3D de 72 µm, 2 celdas de 36 µm) |
| FR4 con pérdidas | tanδ = 0,025 como el "FR-4 (lossy)" de CST (εr 4,3, tanδ 0,025 a 10 GHz, const fit). openEMS lo modela como conductividad fija, así que se clavó tanδ en 2,05 GHz y varía como 1/f (a 4 GHz equivale a ~0,013) |

El cobre de 0,072 mm y el FR4 con pérdidas los pidió Martín para que sea como lo
correría en CST. El bloque de 72 µm obliga a celdas de 36 µm en vertical, y en FDTD la
celda más chica fija el paso de tiempo. Por eso el orden PEC → lámina → bloque, con malla
gruesa en el bloque y un tope de **2 h por corrida**.

**Convergencia de malla.** El mismo filtro a λ/20, λ/30 y λ/40. Si entre las dos más
finas los ceros se mueven menos de ~5 MHz y el rechazo menos de ~0,5 dB, la malla está
convergida.

**Dashboard.** `openems/dashboard.py` arma un solo `dashboard.html` acumulativo, con todo
leído del `modelo.xml` que recibe el motor (bordes, PML, malla, cortes, puertos, sondas,
materiales) más los parámetros S contra el prototipo ideal y las señales temporales.
Arriba, un resumen con la tabla de todas las corridas, la convergencia, PEC contra lámina
contra bloque y openEMS contra MEEP.

### Modelo MEEP (`meep/simular_filtro_meep.py`)

Malla uniforme de 8 px/mm, metal perfecto de 1 píxel (0,125 mm), FR4 sin pérdidas,
fuente Ez bajo la línea, parámetros S por flujo de potencia con una corrida de
referencia (solo módulo). Por esas diferencias se espera que no coincida exacto con
openEMS. Si coinciden la forma y los ceros, el resultado es confiable.

### Problemas de la simulación y cómo se resolvieron

| fecha | problema | causa | arreglo |
|---|---|---|---|
| 11-09 | el motor no escribía el modelo | el C++ de openEMS no acepta la "ñ" de la ruta (`6to año`) | se simula en `D:\sim_filtro\<corrida>` y se copia al repo |
| 11-09 | la línea de prueba daba S21 de −7 dB | puertos mal armados | se rearmaron como en el tutorial `MSL_NotchFilter` de openEMS |
| 11-10 | **la B PEC λ/20 divergió** (5,5 h perdidas). La señal de los puertos bajaba a 10⁻⁸ y desde ~80 ns crecía ×10 cada 20 ns | **malla con saltos de ×15 a ×19 entre celdas vecinas** (y una celda de 0,021 mm). `SmoothMeshLines` solo rellena huecos mayores que la resolución y no mira la relación entre celdas vecinas | función propia `suavizar()`. Junta líneas a menos de fino/4, agranda las celdas con crecimiento geométrico ≤ 1,5 y el script no corre si algún salto pasa de 1,5. La A pasa de 0,27 a 0,35 M celdas y la B de 0,54 a 0,57 M |
| 11-10 | con la malla arreglada **la B se estancó en −30,15 dB** de energía (plano durante 15 min, ni sube ni baja) | hipótesis inicial: continua del pulso gaussiano atrapada en las pistas, porque los puertos no tenían terminación y la PML no absorbe campos estáticos | se agregó `Feed_R=50` a los dos puertos (quedó, es lo realista). **No alcanzó**: la B se volvió a estancar en −31,5 dB con **la misma energía absoluta (3,15·10⁻¹⁴)**, así que lo atrapado no se descargaba por los puertos |
| 11-10 | (sigue el anterior) | **continua del pulso depositada en el sustrato.** El pulso gaussiano con centro = ancho = 3,5 GHz tiene una componente de continua de exp(−(1,5·f0/fc)²) = −20 dB respecto del pico | prueba con pulso de 1 a 7,5 GHz (continua a −33 dB): la B **terminó sola** en 6,5 min. Se dejó **0,5 a 7,5 GHz** (f0 = 4, fc = 3,5 GHz, continua a −25,5 dB), a pedido de Martín, para tener margen abajo de la banda (1 GHz quedaba justo) |
| 11-10 | con 0,5–7,5 GHz la B se aplanó en −37,3 dB | todavía queda algo de continua (−25,5 dB) | se volvió a **1–7,5 GHz** (f0 = 4,25, fc = 3,25 GHz, continua a −33 dB). A 500 MHz el pulso está a −26 dB, de sobra para un cociente como S21 (ver la fila siguiente) |
| 11-10 | ¿el pulso de 1 GHz da bien la banda baja? Con corte en −40 dB los dos pulsos diferían 0,2–0,6 dB en S21 y hasta 20 dB en S11 debajo de 1,5 GHz | **cortar en −40 dB era poco**, no el pulso. Referencia de la A cortada en −50 dB con los dos pulsos: coinciden en **0,04 dB** en S21 (0,05–2 GHz) y 0,6 dB en S11 (0,5–1 GHz). Las de −40 dB se apartan 0,2–0,4 dB en S21 | **criterio de fin en −50 dB** (la A pasa de 3 a 3,5 min). Si la energía no baja al menos 0,5 dB en 2 min, `cola.py` crea el archivo `ABORT`, el motor para limpio y se calculan los S con lo que hay. La energía final queda en `metricas.json` y en el dashboard |
| 11-10 | la B informaba 18 "ceros" | la detección tomaba cualquier mínimo local bajo −25 dB, o sea cada ondita del rechazo | ahora un cero es un mínimo que se despega ≥ 6 dB (`find_peaks` con prominencia) |

Las reglas prácticas que quedaron. En FDTD una celda no debe medir más de ~1,5 veces su
vecina. Hay que mirar la energía en el log, si sube es divergencia y si se aplana es
energía atrapada. Y el pulso de excitación no tiene que traer continua, o sea su centro
tiene que estar lejos de 0 comparado con su ancho.

**Primera B que terminó** (PEC, λ/20, pulso 1–7,5 GHz, 2026-11-10). Borde −1 dB en
1,94 GHz (cae ~110 MHz antes que el A y pierde 3,4 dB en 2 GHz, con S11 de −4,7 dB),
ceros marcados en 2,28 y 2,96 GHz (más mínimos en 2,20 y 2,69), **≥ 28,8 dB entre 2,36 y
4 GHz**, ~−33 dB hasta 5,3 GHz y reapertura arriba de 6 GHz (−5,7 dB en 7 GHz). Queda
guardada aparte y se repite con el pulso definitivo.

### Convergencia de malla (diseño A, PEC, fin a −50 dB, 2026-11-10)

| | λ/20 | λ/30 | λ/40 |
|---|---|---|---|
| celdas / tiempo | 0,35 M / 3,4 min | 0,56 M / 4,7 min | 0,90 M / 6,0 min |
| borde −1 dB | 2,051 GHz | 2,046 GHz | 2,036 GHz |
| ceros | 2,482 · 3,679 GHz | 2,482 · 3,674 GHz | 2,468 · 3,649 GHz |
| atenuación mín. 2,36–4 GHz | 19,0 dB | 19,3 dB | 21,0 dB |
| máximo 4–7 GHz | −2,9 dB | −2,9 dB | −3,0 dB |

De λ/20 a λ/40 los ceros se mueven 0,6–0,8 % y el rechazo ~2 dB. El salto mayor aparece
en λ/40 porque ahí también se achica la celda de los bordes de las pistas (0,128 contra
0,134 mm). Es menos que lo que mueve la tolerancia del εr del FR4 (±3 % en los ceros y
~4 dB en el rechazo), así que **se decidió hacer todo lo demás en λ/20** (Martín). Las
comparaciones entre modelos (PEC, lámina, bloque, MEEP) se hacen con la misma malla. La
incertidumbre por malla de λ/20 queda en ~1 % en frecuencia y ~2 dB en el rechazo.

### Resultados hasta ahora (diseño A, PEC, λ/20)

| | prototipo (libro) | malla vieja (saltos ×19) | malla suavizada | malla suavizada + Feed_R 50 Ω |
|---|---|---|---|---|
| borde −1 dB | 2,05 GHz | 2,046 GHz | 2,046 GHz | 2,046 GHz |
| pérdida máx. hasta 2 GHz | 0,1 dB | 0,43 dB | 0,37 dB | 0,37 dB |
| S11 peor en banda | −16,4 dB | −10,9 dB | −11,2 dB | −11,2 dB |
| ceros | 2,414 · 3,292 GHz | 2,458 · 3,644 GHz | 2,473 · 3,714 GHz | 2,473 · 3,704 GHz |
| atenuación mín. 2,36–4 GHz | 24,5 dB | 20,4 dB | 18,9 dB | 18,9 dB |
| máximo 4–7 GHz | ~−25 dB | −2,8 dB (6,86 GHz) | −2,8 dB (6,92 GHz) | −2,8 dB (6,95 GHz) |
| duración | | 7 min | 2,6 min | 3,3 min |

- **La banda de paso funciona.** El borde cae en 2,05 GHz y la pérdida no pasa de 0,4 dB.
- **El cero de 2,41 GHz cae casi justo.** Ese stub (fino largo, parche chico) se parece a
  la rama ideal y la corrección 5.11 funciona bien.
- **El cero de 3,29 GHz se corre a ~3,7 GHz (+13 %).** Ese stub es casi todo parche
  (7,9 mm de largo con 1 mm de fino) y el modelo de L y C concentradas deja de valer,
  porque el parche ya es una fracción importante de λ. Por eso el rechazo mínimo queda
  en ~19 dB.
- **Reabre arriba de ~4,5 GHz** (−2,8 dB cerca de 6,9 GHz). Es el pico espurio de la
  Figura 5.7 de Hong. El 2.º armónico queda filtrado, el 3.º solo en su parte baja.

### Ajuste de la B: stubs recortados ×0,935 (2026-11-10)

Con la simulación, la B quedó corrida hacia abajo entera. Su primer cero cayó en 2,229 GHz
contra 2,385 de diseño (−7 %) y con él el borde de la banda de paso (−1 dB en 1,95 GHz, 3,2 dB
de pérdida y S11 de −3,7 dB en 2 GHz en PEC). La hipótesis es que los parches de 20 Ω
(11,1 mm de ancho) ya no se comportan como capacitores concentrados y se ven eléctricamente
más largos de lo que dan las fórmulas. Siguiendo la idea del libro de cerrar el diseño con
la simulación EM, se acortaron **todos los stubs de la B (tramo fino y parche) por
2,229/2,385 = 0,935**. El diseño del libro (`diseno_hong.json`) no se tocó, el recorte es
la opción `--recorte` de los scripts y queda en el nombre de la corrida (`_rec0.935`).

| λ/20 | A, PEC | B orig., PEC | **B rec., PEC** | A, pérdidas | B orig., pérdidas | **B rec., pérdidas** |
|---|---|---|---|---|---|---|
| S21 en 1,0 / 1,5 GHz | 0 / −0,25 | −0,08 / −0,04 | −0,06 / −0,04 | −0,33 / −0,64 | −0,66 / −1,0 | −0,62 / −0,87 |
| S21 en 1,9 / 2,0 GHz | −0,02 / −0,36 | −0,61 / −3,2 | **−0,61 / −0,59** | −0,97 / −1,75 | −2,9 / −6,9 | **−2,1 / −3,0** |
| borde −1 dB [GHz] | 2,051 | 1,951 | **2,046** | 1,912 | 1,50 | 1,59 |
| S21 en 2,2 / 2,3 GHz | −6 / −13 | −32 / −35 | −14 / −30 | −8 / −14 | −33 / −33 | −17 / −31 |
| atenuación mín. 2,36–4 GHz | 19 dB | 30,6 dB | **31,3 dB** | 20,3 dB | 31,5 dB | **32,0 dB** |
| S21 en 5 / 6 GHz | −14 / −6 | −34 / −27 | −31 / −30 | −14 / −6 | −35 / −26 | −31 / −31 |

Valores en dB salvo donde se indica. El recorte llevó el borde de la B a 2,05 GHz en PEC
sin perder rechazo. Con FR4 con pérdidas la B recortada pierde ~1,2 dB más que la A en el
tope de la banda (1,9–2 GHz) y 0,2–0,3 dB más de 1 a 1,5 GHz, a cambio de **12 dB más de
rechazo** en todo el 2.º armónico, mucho más corte en 2,0–2,35 GHz (la parte que se escapa)
y −30 dB sostenidos hasta 6 GHz (la A reabre desde 4 GHz). En un primer momento se eligió la B
recortada como diseño principal. **Decisión final (2026-11-10): se fabrica solo el A.** B
rechaza más pero no aporta tanto, y A, al ser de menor orden, tiene pendiente más suave,
así que sus polos se pueden mover (por el εr real o recortando stubs) sin afectar las
frecuencias útiles. Con A el fantasma pesimista que se cuela por el borde de la rampa queda
en −50/−43 dB (con B, −61/−54 dB). Queda abierto recortar algo más (por ejemplo
×0,92, su primer cero está en 2,35 GHz y no en 2,39) para tener margen contra un εr alto.

La B se estanca siempre cerca de −42/−44 dB, también con el sustrato con pérdidas, así que
lo que queda atrapado no parece estar en el sustrato (quizás en el aire). Con −42 dB los
resultados ya son buenos.

### Modelo del conductor: PEC, lámina y bloque de 72 µm (2026-11-10)

Todas en λ/20. Lámina = cobre σ 5,8·10⁷ S/m con 72 µm solo para las pérdidas (geometría
plana). Bloque = cobre 3D de 72 µm (2 celdas de 36 µm), lo más parecido a CST. En las dos,
FR4 con tanδ 0,025 en 2,05 GHz.

| | A PEC | A lámina | A bloque | B rec. PEC | B rec. lámina | B rec. bloque |
|---|---|---|---|---|---|---|
| S21 en 1,0 / 1,5 GHz [dB] | 0 / −0,25 | −0,33 / −0,64 | −0,22 / −0,38 | −0,06 / −0,04 | −0,62 / −0,87 | −0,61 / −0,87 |
| S21 en 1,9 / 2,0 GHz [dB] | −0,02 / −0,36 | −0,97 / −1,75 | −0,80 / −1,48 | −0,61 / −0,59 | −2,1 / −3,0 | −1,2 / −2,9 |
| borde −1 dB [GHz] | 2,051 | 1,912 | 1,946 | 2,046 | 1,594 | 1,728 |
| ceros [GHz] | 2,48 · 3,68 | 2,47 · 3,68 | 2,46 · 3,60 | 2,35 · 3,07 | (2,35) · 3,06 | 2,41 · 3,03 |
| atenuación mín. 2,36–4 GHz | 19,0 dB | 20,3 dB | 21,5 dB | 31,3 dB | 32,0 dB | 31,1 dB |
| energía final | −50,9 dB | −52,1 dB | −50,5 dB | −44,0* | −44,5* | −36,9* |

(*) estancada y cortada por la cola. En la lámina de la B el primer cero quedó poco
profundo y la detección no lo marca. Las pérdidas no mueven los ceros, los vuelven menos
profundos, y suman de 0,2 a 3 dB de pérdida en la banda del VCO (casi toda del FR4). El
bloque pierde 0,1–0,3 dB menos que la lámina y corre los ceros ~1–2 % hacia abajo. Las
diferencias entre lámina y bloque son del orden de la incertidumbre de malla, así que la
lámina alcanza para este filtro.

### openEMS contra MEEP (2026-11-10)

MEEP a 8 px/mm (grilla uniforme de 0,125 mm), 6 procesos MPI, metal perfecto de 1 píxel de
espesor, FR4 sin pérdidas, fuente de campo bajo la línea y parámetros S por flujo de
potencia (solo módulo). Cada diseño son dos pasadas, la línea recta de referencia y el
filtro. La A tardó 39 min (referencia 7062 pasos, filtro 15 087 pasos).

| A, sin pérdidas | openEMS (PEC, λ/20) | MEEP (8 px/mm) | diferencia |
|---|---|---|---|
| ceros | 2,48 · 3,68 GHz | 2,24 · 3,36 GHz | −10 % / −9 % |
| borde −1 dB | 2,05 GHz | 1,84 GHz | −10 % |
| S21 en 1,5 / 1,9 / 2,0 GHz | −0,25 / −0,02 / −0,36 dB | −0,44 / −2,7 / −6,6 dB | |
| atenuación mín. 2,36–4 GHz | 19,0 dB | 21,8 dB | |
| S21 en 5 / 6 GHz | −14 / −5,9 dB | −12 / −4,4 dB | |

Los dos programas ven la misma forma (dos ceros, ~20 dB de rechazo en la zona del
armónico, la misma reapertura arriba de 4,5 GHz), lo que confirma la topología con un
programa independiente. Pero MEEP corre toda la respuesta ~9 % hacia abajo. Debajo de
~1 GHz MEEP da artefactos (S21 por encima de 0 dB) porque la caja y las PML son chicas
comparadas con la longitud de onda, no es el filtro.

Causas probables, en orden: la grilla uniforme de 0,125 mm (la línea de 0,54 mm queda con
~4 píxeles y todo se redondea a múltiplos de 0,125 mm, contra celdas de 0,045 mm en los
bordes en openEMS), el metal de 1 píxel = 0,125 mm de espesor (más capacidad de borde, baja
las resonancias) y la falta de un puerto microstrip. Para separar el efecto del espesor se
corrió en openEMS la A con PEC de 0,125 mm (`--metal pec125`).

| A, openEMS λ/20 | PEC espesor 0 | PEC 0,125 mm (control) | cobre 72 µm + pérdidas | MEEP |
|---|---|---|---|---|
| ceros [GHz] | 2,482 · 3,679 | 2,497 · 3,649 | 2,458 · 3,599 | 2,24 · 3,36 |
| borde −1 dB [GHz] | 2,051 | 2,070 | 1,946 | 1,84 |
| atenuación mín. 2,36–4 GHz | 19,0 dB | 16,8 dB | 21,5 dB | 21,8 dB |

**El espesor no explica la diferencia.** Con 0,125 mm de metal los ceros se mueven +0,6 % y
−0,8 % (y el borde sube 1 %), contra −9/−10 % de MEEP. La diferencia viene entonces del
modelo de MEEP (grilla uniforme de 0,125 mm sin promediado de subpíxel, anchos y largos
redondeados a la grilla, excitación por fuente de campo y S por flujo). openEMS tiene la
malla refinada en los bordes, su estudio de convergencia (~1 % de λ/20 a λ/40) y tres modelos
de conductor que coinciden entre sí, así que **para las frecuencias absolutas manda
openEMS**. MEEP queda como confirmación cualitativa de la respuesta (forma, rechazo y
reapertura). Cerrar la diferencia pediría MEEP a 12–16 px/mm (de ~3 a ~10 h por diseño).

**B recortado en MEEP** (76 min, más lento porque compartió el procesador con el control):

| sin pérdidas | A openEMS | A MEEP | B rec. openEMS | B rec. MEEP |
|---|---|---|---|---|
| ceros [GHz] | 2,48 · 3,68 | 2,24 · 3,36 | 2,35 · 3,07 | 2,08 · 2,26 · 2,68 |
| borde −1 dB [GHz] | 2,051 | 1,84 | 2,046 | 1,82 |
| S21 en 2,2 / 2,3 GHz [dB] | −6,1 / −12,8 | −24,7 / −26,4 | −14,3 / −30,0 | −31,4 / −33,7 |
| atenuación mín. 2,36–4 GHz | 19,0 dB | 21,8 dB | 31,3 dB | 31,5 dB |
| S21 en 5 / 6 GHz [dB] | −14,0 / −5,9 | −12,2 / −4,4 | −30,8 / −29,6 | −24,6 / −18,7 |

En la B pasa lo mismo que en la A, toda la respuesta ~10 % más abajo en MEEP (borde, ceros
y también la reapertura, que pasa de ~6,2 a ~5,5 GHz). **La comparación entre diseños da
igual en los dos programas**: la B recortada rechaza ~10 dB más que la A en todo el 2.º
armónico (31,5 contra 21,8 dB en MEEP, 31,3 contra 19,0 en openEMS) y sostiene el rechazo
hasta más arriba. O sea, la elección de la B no depende del simulador.

**Métricas unificadas (2026-11-10).** El script de MEEP calculaba sus métricas con otro
criterio y con la ondulación de ±1 dB de su banda de paso daba "borde en 1,02 GHz" y doce
"ceros". Ahora todas las corridas (openEMS y MEEP) se miden con la misma función
(`metricas()` de `openems/simular_filtro.py`). Ceros: mínimos arriba de 2 GHz que se despegan
≥ 6 dB. Borde de −1 dB: última frecuencia antes del primer cero en que S21 sigue arriba de
−1 dB. Pérdida y S11 máximos: dentro de la banda del VCO (0,983–1,999 GHz). En openEMS los
valores no cambiaron.

## 6. Pendientes

- MEEP terminado (A y B recortada, 2026-11-10). `meep/progreso_meep.py` abre una ventana
  con la barra de progreso de la cola. El `mpirun` es MPICH, no lleva `--allow-run-as-root`.
- Opcional: MEEP a 12–16 px/mm para cerrar la diferencia de ~10 % con openEMS.
- Capítulo preliminar de la tesis escrito (2026-11-10): `redaccion/filtro_rf.tex`
  (`ch:filtro_rf`, después del capítulo del VCO). Figuras con `figuras_tesis.py` →
  `redaccion/figuras/filtro_rf/`.
- Esquinas de εr (4,2 y 4,8).
- Margen de recorte de los stubs del A: cuántos MHz sube cada cero por milímetro
  recortado, sacado de la simulación.
- Placa en KiCad con A, B, una línea de paso de 50 Ω del mismo largo (para restar
  conectores y línea) y un resonador λ/4 de prueba para medir el εr de la tirada.
- Medición con el tracking generator del SSA3032X (hasta 3,2 GHz) o el VNA.
- Confirmar con `simulaciones_meep/armonicos/` cuánto atenúa la ventana de Hann el
  armónico que se escapa por debajo de 2,35 GHz.

## Archivos

| archivo | qué es |
|---|---|
| `diseno_hong.py` | pasos 2 a 4.4 del libro, con la validación contra el ejemplo 5.1.3 y las erratas |
| `diseno_hong.json` | todas las medidas, lo leen las simulaciones |
| `openems/simular_filtro.py` | `python simular_filtro.py A\|B --metal pec\|sheet\|thick --malla N [--solo-modelo]` |
| `openems/cola.py` | corre la lista de trabajos de a uno, con tope de 2 h, log en `resultados/<corrida>/log.txt` y estado en `cola_estado.txt` |
| `openems/dashboard.py` → `dashboard.html` | dashboard acumulativo de todas las corridas |
| `meep/simular_filtro_meep.py`, `meep/cola_meep.py` | lo mismo en MEEP (WSL, MPI) |

Los datos pesados de openEMS quedan en `D:\sim_filtro`, fuera del repo.
