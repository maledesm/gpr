/*
 * ============================================================================
 *  Generador de patrones de prueba  --  Arduino Uno
 * ============================================================================
 *
 *  Señal de referencia para validar la cadena de adquisición
 *  ESP32-C3 + PCM1808 sin necesitar el circuito de RF.
 *
 *  El Uno NO tiene DAC: analogWrite() es PWM, no una salida analógica. Para
 *  este test no hace falta, y de hecho la cuadrada digital es mejor: los
 *  flancos son exactos y lo que se quiere validar es tiempo y amplitud.
 *
 *  ---------------------------------------------------------------------------
 *  POR QUÉ ESTOS TIEMPOS Y NO OTROS
 *  ---------------------------------------------------------------------------
 *  El PCM1808 está acoplado en alterna y tiene un pasa-altos que no se puede
 *  desactivar (HPF digital interno = 1.9e-5*fs, más el capacitor de acople del
 *  módulo contra 60 kohm). La constante de tiempo resultante está entre
 *  60 y 175 ms según el capacitor que traiga el módulo.
 *
 *  Consecuencia: un escalón que dure una fracción apreciable de esa constante
 *  NO se ve como un escalón plano, se ve como un pico que decae. Por eso los
 *  segmentos son de 1 a 5 ms y no de cientos de ms:
 *
 *      caída del techo = 1 - exp(-t_segmento / tau)
 *      con t = 4 ms y tau = 60 ms  ->  6.5 %   (peor caso)
 *      con t = 4 ms y tau = 175 ms ->  2.3 %   (mejor caso)
 *
 *  O sea: techos visualmente planos, con una inclinación apenas perceptible
 *  que además sirve para MEDIR la constante de tiempo real de tu módulo
 *  (ver PATRON 4).
 *
 *  El límite por el otro lado lo pone la pantalla: el Serial Plotter del
 *  Arduino IDE muestra 50 puntos. Con los segmentos en relación 1:2:3:4 y un
 *  cuadro entero ocupando la ventana, cada segmento recibe 5, 10, 15 y 20
 *  puntos respectivamente. Suficiente para distinguirlos de un vistazo.
 *
 *  ---------------------------------------------------------------------------
 *  CONEXIONADO  --  ¡EL DIVISOR NO ES OPCIONAL!
 *  ---------------------------------------------------------------------------
 *  El Uno saca 0-5 V. El fondo de escala del PCM1808 es 3.0 Vpp: conectarlo
 *  directo lo satura, y un delta-sigma saturado no recorta suave como un SAR,
 *  se vuelve inestable y escupe basura.
 *
 *      Uno D9 ──── R1 10k ──┬──────────► entrada VINL del módulo PCM1808
 *                           │
 *                          R2 4k7
 *                           │
 *      Uno GND ─────────────┴──────────► GND del ESP32 Y del módulo
 *
 *  Cuentas:
 *      divisor sin carga     = 4.7 / 14.7           = 0.320  -> 1.60 Vpp
 *      impedancia de salida  = 10k || 4k7           = 3.2 kohm
 *      carga del módulo      = 60 / (60 + 3.2)      = 0.949
 *      amplitud en el ADC    = 5 V * 0.320 * 0.949  = 1.52 Vpp   (-5.9 dBFS)
 *
 *  Ese 1.5 Vpp es el número que tenés que ver en el modo 'stats' del ESP32.
 *  Esperá entre 1.4 y 1.6 V: el nivel alto del AVR no es exactamente 5.00 V
 *  y el 5 V del USB tampoco.
 *
 *  LA MASA TIENE QUE SER COMÚN entre Uno, ESP32 y módulo. Sin eso no medís
 *  nada coherente.
 *
 *  ---------------------------------------------------------------------------
 *  PATRONES  (se cambian mandando 1, 2, 3 o 4 por el Monitor Serie del Uno)
 *  ---------------------------------------------------------------------------
 *   1  ESCALERA     1-2-3-4 ms. El de diagnóstico. Asimétrico y creciente:
 *                   si lo ves al derecho, la cadena respeta el orden temporal.
 *   2  CUADRADA 1k  500/500 us. Para verificar fs: 'stats' del ESP32 tiene que
 *                   reportar 1000.0 Hz.
 *   3  CUADRADA 100 5/5 ms. Lo mismo pero más lento, para mirar los techos.
 *   4  PULSO        0.5 ms alto cada 10 ms. Mide la constante de tiempo del
 *                   pasa-altos: el nivel bajo se recupera exponencialmente
 *                   hacia cero y de esa curva sale tau.
 *
 *  ---------------------------------------------------------------------------
 *  ADVERTENCIA SOBRE PRECISIÓN
 *  ---------------------------------------------------------------------------
 *  El ATmega328P del Uno corre con un RESONADOR CERÁMICO, no un cristal:
 *  tolerancia típica +-0.5 %. Sirve de sobra para verificar que la cadena
 *  funciona, pero NO lo uses como patrón de frecuencia. Si necesitás validar
 *  la fs del ESP32 mejor que 0.5 %, hace falta un generador de verdad.
 * ============================================================================
 */

// Pin 9 = PB1, pin 13 = PB5 (LED integrado). Los dos viven en PORTB, así que
// se escriben de una sola vez: una instrucción, sin el ~4 us que costarían
// dos digitalWrite(). El LED espeja la señal y sirve de testigo de que el
// sketch está corriendo (a estas velocidades se ve encendido a media luz).
#define PIN_SALIDA 9
#define PIN_LED    13
#define MASCARA_PB ((1 << PB1) | (1 << PB5))
#define PONER(nivel) (PORTB = (nivel) ? (PORTB | MASCARA_PB) : (PORTB & ~MASCARA_PB))

struct Segmento {
  bool     nivel;
  uint16_t us;
};

// --- Patrón 1: escalera asimétrica -----------------------------------------
// Segmentos en relación 1:2:3:4. Es direccional: si lo vieras invertido en el
// tiempo darías con 4-3-2-1, que se distingue al instante.
// Ciclo de trabajo = 4 ms alto / 10 ms total = 40 %. Como la entrada está
// acoplada en alterna, la señal se autocentra en su valor medio, así que el
// nivel alto queda en +0.6*Vpp y el bajo en -0.4*Vpp. Con 1.5 Vpp:
// mesetas en +900 mV y -600 mV. No esperes +-750 mV: eso sería con 50 %.
const Segmento ESCALERA[] = {
  {HIGH, 1000}, {LOW, 2000}, {HIGH, 3000}, {LOW, 4000}
};

// --- Patrón 2: cuadrada de 1 kHz exacta ------------------------------------
const Segmento CUADRADA_1K[] = {
  {HIGH, 500}, {LOW, 500}
};

// --- Patrón 3: cuadrada de 100 Hz ------------------------------------------
const Segmento CUADRADA_100[] = {
  {HIGH, 5000}, {LOW, 5000}
};

// --- Patrón 4: pulso angosto, para medir el pasa-altos ---------------------
// 0.5 ms alto cada 10 ms. Los 9.5 ms de nivel bajo dejan ver la recuperación
// exponencial hacia cero. Midiendo cuánto tarda en recuperar el 63 % tenés
// tau directo, y de ahí fc = 1/(2*pi*tau).
const Segmento PULSO[] = {
  {HIGH, 500}, {LOW, 9500}
};

struct Patron {
  const Segmento *seg;
  uint8_t         n;
  const char     *nombre;
};

const Patron PATRONES[] = {
  {ESCALERA,     4, "1: ESCALERA 1-2-3-4 ms (cuadro de 10 ms, 40% alto)"},
  {CUADRADA_1K,  2, "2: CUADRADA 1000 Hz exacta (50% alto)"},
  {CUADRADA_100, 2, "3: CUADRADA 100 Hz exacta (50% alto)"},
  {PULSO,        2, "4: PULSO 0.5 ms cada 10 ms (para medir el pasa-altos)"},
};
const uint8_t N_PATRONES = sizeof(PATRONES) / sizeof(PATRONES[0]);

uint8_t  actual   = 0;   // patrón en curso
uint8_t  idx      = 0;   // segmento dentro del patrón
uint32_t proximo  = 0;   // instante absoluto del próximo flanco

void anunciar() {
  Serial.println();
  Serial.print(F("Patron activo -> "));
  Serial.println(PATRONES[actual].nombre);
  uint32_t total = 0;
  for (uint8_t i = 0; i < PATRONES[actual].n; i++) total += PATRONES[actual].seg[i].us;
  Serial.print(F("Cuadro completo: "));
  Serial.print(total / 1000.0, 3);
  Serial.print(F(" ms  ->  "));
  Serial.print(1000000.0 / total, 2);
  Serial.println(F(" Hz de repeticion"));
  Serial.println(F("En el ESP32 mira este cuadro con:  n 50   |   win <ms>   |   plot"));
}

void seleccionar(uint8_t nuevo) {
  if (nuevo >= N_PATRONES) return;
  actual  = nuevo;
  idx     = 0;
  proximo = micros();      // arranca de cero, sin arrastrar el desfasaje viejo
  anunciar();
}

void setup() {
  pinMode(PIN_SALIDA, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  PONER(LOW);

  Serial.begin(115200);
  delay(200);
  Serial.println(F("========================================================"));
  Serial.println(F(" Generador de patrones -- validacion ESP32-C3 + PCM1808"));
  Serial.println(F("========================================================"));
  Serial.println(F("Salida: pin D9, a traves del divisor 10k / 4k7 -> ~1.5 Vpp"));
  Serial.println(F("OJO: sin el divisor saturas el PCM1808 (fondo 3.0 Vpp)."));
  Serial.println(F("Masa comun entre Uno, ESP32 y modulo, si o si."));
  Serial.println();
  Serial.println(F("Manda 1, 2, 3 o 4 para cambiar de patron:"));
  for (uint8_t i = 0; i < N_PATRONES; i++) {
    Serial.print(F("  "));
    Serial.println(PATRONES[i].nombre);
  }

  seleccionar(0);
}

void loop() {
  // Cambio de patrón por consola
  while (Serial.available()) {
    char c = Serial.read();
    if (c >= '1' && c <= '0' + N_PATRONES) seleccionar(c - '1');
  }

  uint32_t ahora = micros();

  // Si nos atrasamos mucho (por ejemplo por los Serial.print de un cambio de
  // patron), resincronizamos en vez de disparar en rafaga todos los segmentos
  // atrasados, que dejaria un glitch feo en la señal.
  if ((int32_t)(ahora - proximo) > 20000) proximo = ahora;

  // Comparacion en aritmetica con signo: sobrevive al desborde de micros()
  // cada 71.6 minutos sin ningun caso especial.
  if ((int32_t)(ahora - proximo) >= 0) {
    const Segmento &s = PATRONES[actual].seg[idx];
    PONER(s.nivel);
    proximo += s.us;                       // instante absoluto: el error no se
    idx++;                                 // acumula aunque el loop se demore
    if (idx >= PATRONES[actual].n) idx = 0;
  }
}
