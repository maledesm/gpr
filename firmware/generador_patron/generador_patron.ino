/*
 * Generador de patrón de prueba — Arduino Uno
 * Valida la cadena ESP32-C3 + PCM1808 sin necesitar el circuito de RF.
 *
 * Salida en D9: cuadrada simétrica de 100 Hz (5 ms alto, 5 ms bajo).
 *
 * ── POR QUÉ 100 Hz ─────────────────────────────────────────────────────────
 * Por abajo lo limita el pasa-altos del PCM1808 (τ ≈ 308 ms a fs = 8 kHz):
 * a 100 Hz el techo cae solo 1.6 %, o sea que se ve plano. A 10 Hz caería
 * un 15 % y las mesetas saldrían inclinadas.
 *
 * Por arriba lo limitan los armónicos: una cuadrada son armónicos impares, y
 * con fs_eff = 2 kHz entran hasta el 9° a 100 Hz. A 200 Hz solo entrarían
 * hasta el 5° y se vería redondeada.
 *
 * De paso, 100 Hz da 20 puntos por período a fs_eff = 2 kHz, y sale exacta
 * con delay(5) sin fracciones de milisegundo.
 *
 * ── DIVISOR OBLIGATORIO ────────────────────────────────────────────────────
 * El Uno saca 5 Vpp y el fondo de escala del PCM1808 son 3.0 Vpp. Conectarlo
 * directo lo satura, y un delta-sigma saturado se vuelve inestable.
 *
 *     D9 ──── 10k ──┬──── entrada VINL del módulo      → ~1.5 Vpp (−5.9 dBFS)
 *                   │
 *                  4k7
 *                   │
 *     GND ──────────┴──── GND del ESP32 y del módulo   ← masa común, sí o sí
 *
 * ── QUÉ ESPERAR EN 'stats' DEL ESP32 ───────────────────────────────────────
 *     Vpp ≈ 1400 mV · DC ≈ 0 · mesetas simétricas en ±700 mV · f = 100.0 Hz
 *
 * Las mesetas son simétricas porque el ciclo de trabajo es 50 %. (Con la
 * escalera asimétrica anterior no lo eran: la entrada acoplada en alterna se
 * autocentra en el valor medio, y con 40 % de duty eso corría los niveles.)
 *
 * El ATmega328P del Uno usa un RESONADOR CERÁMICO, no un cristal: ±0.5 % de
 * tolerancia. Sirve para verificar que la cadena funciona, pero no lo tomes
 * como patrón de frecuencia.
 */

void setup() {
  pinMode(9, OUTPUT);
}

void loop() {
  digitalWrite(9, HIGH); delay(5);
  digitalWrite(9, LOW);  delay(5);
}
