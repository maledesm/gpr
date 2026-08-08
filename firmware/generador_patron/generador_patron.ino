/*
 * Generador de patrón de prueba — Arduino Uno
 * Valida la cadena ESP32-C3 + PCM1808 sin necesitar el circuito de RF.
 *
 * Salida en D9. Cuadro de 10 ms que se repite a 100 Hz:
 *
 *     ALTO 1 ms → BAJO 2 ms → ALTO 3 ms → BAJO 4 ms
 *
 * Asimétrico y creciente a propósito: si en el plotter lo ves 1-2-3-4, la
 * cadena respeta amplitud y orden temporal. Si lo vieras 4-3-2-1 o simétrico,
 * algo está mal.
 *
 * Los tiempos van en MILISEGUNDOS, no en cientos de ms: el PCM1808 está
 * acoplado en alterna con tau entre 60 y 175 ms, así que escalones largos se
 * verían como picos que decaen en vez de mesetas planas.
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
 *     Vpp ≈ 1500 mV · DC ≈ 0 · meseta alta +900 mV · meseta baja −600 mV
 * Las mesetas son asimétricas porque el ciclo de trabajo es 40 % y la entrada
 * acoplada en alterna se autocentra en su valor medio.
 *
 * Para verlo:  n 50  →  win 10  →  plot
 */

void setup() {
  pinMode(9, OUTPUT);
}

void loop() {
  digitalWrite(9, HIGH); delay(1);
  digitalWrite(9, LOW);  delay(2);
  digitalWrite(9, HIGH); delay(3);
  digitalWrite(9, LOW);  delay(4);
}
