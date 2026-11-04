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
