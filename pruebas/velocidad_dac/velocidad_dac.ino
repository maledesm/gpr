/*
 * velocidad_dac.ino
 * -----------------
 * Cuanto tarda REALMENTE una escritura al MCP4725, y que relacion impone eso
 * entre el PRF y la cantidad de escalones de la rampa.
 *
 * Es un sketch de MEDICION, aislado a proposito:
 *   - No toca el I2S ni el PCM1808.
 *   - No usa la tabla de predistorsion: los codigos van lineales.
 *   - No guarda nada en flash.
 * Todo lo que hace es escribirle al DAC y contar el tiempo. Si algo no cierra,
 * el problema esta en estas 250 lineas y en ningun otro lado.
 *
 * CABLEADO
 *   GPIO0 -> SDA      GPIO1 -> SCL      3V3 -> VCC      GND -> GND
 *   GPIO3 -> canal 2 del osciloscopio (marca: sube DURANTE la escritura I2C)
 *   OUT   -> canal 1 del osciloscopio
 *
 * COMPILACION
 *   Placa "Nologo ESP32C3 Super Mini", o "ESP32C3 Dev Module" con
 *   USB CDC On Boot = Enabled. Si no, el monitor serie queda mudo.
 *
 * LAS TRES MEDICIONES QUE IMPORTAN
 *   sq              cuadrada a maxima velocidad. Medi la FRECUENCIA en el
 *                   osciloscopio: t_escritura = 1 / (2 * f). Es la medicion
 *                   mas confiable porque no depende del reloj del ESP32.
 *   rampa <pasos>   triangular a maxima velocidad con esa cantidad de
 *                   escalones. Te dice el PRF minimo alcanzable, que es
 *                   justo la relacion PRF <-> pasos que buscamos.
 *   barrido         repite la medicion a 100k, 200k, 400k, 800k y 1M de
 *                   reloj I2C y arma la tabla.
 */

#include <Wire.h>

#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT == 0
#warning "Compilalo con USB CDC On Boot = Enabled o no vas a ver nada en el monitor."
#endif

// --------------------------------------------------------------------------
//  Configuracion
// --------------------------------------------------------------------------
#define PIN_SDA     0
#define PIN_SCL     1
#define PIN_MARCA   3        // sube durante la escritura: canal 2 del osciloscopio

#define DAC_MAX  4095        // 12 bits

// Ancho de banda del VCO, de firmware/gpr_barrido/tabla_vco.h (943 a 1981.7 MHz).
// Esta a mano y no incluido a proposito: este sketch no depende de nada.
#define BW_MHZ   1038.7f

#define C_LUZ    3.0e8f

static uint8_t  g_addr = 0x60;
static bool     g_ok   = false;
static uint32_t g_clk  = 400000;
static float    g_tesc = 0.0f;      // us por escritura, ultimo valor medido

// --------------------------------------------------------------------------
//  Escritura al DAC
// --------------------------------------------------------------------------
//
// Fast Mode Write: dos bytes, sin tocar la EEPROM. El nibble alto del primer
// byte lleva C2=0 C1=0 PD1=0 PD0=0, o sea que alcanza con enmascarar.
// NUNCA usar el comando de EEPROM: aguanta ~1e6 ciclos y tarda 25-50 ms.
//
static inline bool escribir(uint16_t v) {
  if (v > DAC_MAX) v = DAC_MAX;
  digitalWrite(PIN_MARCA, HIGH);
  Wire.beginTransmission(g_addr);
  Wire.write((uint8_t)((v >> 8) & 0x0F));
  Wire.write((uint8_t)(v & 0xFF));
  bool ok = (Wire.endTransmission() == 0);
  digitalWrite(PIN_MARCA, LOW);
  return ok;
}

static bool buscarDAC() {
  for (uint8_t a = 0x60; a <= 0x67; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { g_addr = a; g_ok = true; return true; }
  }
  g_ok = false;
  return false;
}

// --------------------------------------------------------------------------
//  Medicion por software
// --------------------------------------------------------------------------
//
// Mide el lazo completo: transaccion en el bus MAS el overhead de la libreria
// Wire. Ese es el numero que importa, porque es el que limita la rampa.
// La cuenta de bus puro seria ~30 bits a g_clk; la diferencia es el driver.
//
static float medir(uint32_t n) {
  uint32_t t0 = micros();
  for (uint32_t i = 0; i < n; i++) escribir((uint16_t)(i & DAC_MAX));
  uint32_t dt = micros() - t0;
  return (float)dt / (float)n;
}

static void mostrarUna(uint32_t clk, float us) {
  float bus = 30.0f * 1e6f / (float)clk;      // ~30 bits: start + 3 bytes + acks + stop
  Serial.printf("  %7lu Hz  %8.1f us/escritura   bus ~%.1f us   overhead ~%.1f us\n",
                (unsigned long)clk, us, bus, us - bus);
}

// --------------------------------------------------------------------------
//  Tabla PRF <-> pasos
// --------------------------------------------------------------------------
//
// Con N niveles hay N-1 intervalos, y una triangular completa los recorre dos
// veces: subida y bajada. O sea 2*(N-1) escrituras por periodo de PRF.
//
//   PRF_min = 2 * (N-1) * t_escritura
//   N_max   = 1 + PRF / (2 * t_escritura)
//
// La fisica que cuelga de N:
//   df    = BW / (N-1)                salto de frecuencia por escalon
//   R_amb = c / (4*df)                alcance no ambiguo, UN canal real
//                                     (con I/Q seria c/(2*df))
//
static void tablaPrf() {
  if (g_tesc <= 0.0f) {
    Serial.println("[error] primero corre 'mide' o 'sq' para tener t_escritura");
    return;
  }
  float dr_cm = C_LUZ / (2.0f * BW_MHZ * 1e6f) * 100.0f;

  Serial.println();
  Serial.printf("  t_escritura medida : %.1f us\n", g_tesc);
  Serial.printf("  Ancho de banda     : %.0f MHz\n", BW_MHZ);
  Serial.printf("  Resolucion         : %.1f cm  (la fija BW, no los pasos)\n", dr_cm);
  Serial.println();
  Serial.println("  PRF [ms]   pasos max   df [MHz]   R_amb [m]");
  Serial.println("  ---------------------------------------------");

  const float prfs[] = {5, 10, 20, 37, 50, 100, 200, 500};
  for (uint8_t i = 0; i < sizeof(prfs) / sizeof(prfs[0]); i++) {
    float n = 1.0f + prfs[i] * 1000.0f / (2.0f * g_tesc);
    if (n < 2.0f) {
      Serial.printf("  %7.0f      -- no alcanza ni para 2 escalones --\n", prfs[i]);
      continue;
    }
    uint32_t N = (uint32_t)n;
    float df = BW_MHZ / (float)(N - 1);
    float ramb = C_LUZ / (4.0f * df * 1e6f);
    Serial.printf("  %7.0f   %9lu   %8.2f   %9.2f\n",
                  prfs[i], (unsigned long)N, df, ramb);
  }
  Serial.println();
  Serial.println("  Leelo al reves si lo que te importa es el alcance: elegis");
  Serial.println("  R_amb, eso te fija los pasos, y los pasos te fijan el PRF.");
  Serial.println();
}

// --------------------------------------------------------------------------
//  Cuadrada a maxima velocidad
// --------------------------------------------------------------------------
//
// El DAC alterna entre dos codigos lo mas rapido que puede. En el osciloscopio
// sale una cuadrada de periodo 2*t_escritura. Medir una frecuencia es facil
// hasta en un osciloscopio malo, y ademas se ve si la salida ALCANZA a
// establecerse: si en vez de cuadrada ves trapecio, el DAC no llega.
//
static void cuadrada(uint16_t bajo, uint16_t alto) {
  Serial.printf("\n  Cuadrada entre %u y %u a maxima velocidad.\n", bajo, alto);
  Serial.println("  Medi la FRECUENCIA en el osciloscopio:");
  Serial.println("      t_escritura = 1 / (2 * f)");
  Serial.println("  Cualquier tecla para parar.\n");

  uint32_t n = 0;
  uint32_t t0 = micros();
  bool arriba = false;
  while (!Serial.available()) {
    escribir(arriba ? alto : bajo);
    arriba = !arriba;
    n++;
  }
  uint32_t dt = micros() - t0;
  while (Serial.available()) Serial.read();

  g_tesc = (float)dt / (float)n;
  Serial.printf("  %lu escrituras en %.3f s  ->  %.1f us/escritura\n",
                (unsigned long)n, dt / 1e6f, g_tesc);
  Serial.printf("  La cuadrada deberia verse en %.0f Hz. Compara con el osciloscopio.\n\n",
                1e6f / (2.0f * g_tesc));
}

// --------------------------------------------------------------------------
//  Triangular a maxima velocidad
// --------------------------------------------------------------------------
//
// Esta es la medicion que responde la pregunta directamente: con N escalones,
// cual es el PRF mas rapido posible. No se le pide un PRF: se corre a fondo y
// se mide el que sale.
//
static void rampaMax(uint16_t pasos) {
  if (pasos < 2) { Serial.println("[error] pasos >= 2"); return; }

  Serial.printf("\n  Triangular de %u escalones a maxima velocidad.\n", pasos);
  Serial.println("  Medi el PERIODO en el osciloscopio. Cualquier tecla para parar.\n");

  uint32_t n = 0;
  int32_t idx = 0;
  int8_t  dir = 1;
  uint32_t t0 = micros();
  while (!Serial.available()) {
    escribir((uint16_t)((uint32_t)DAC_MAX * (uint32_t)idx / (uint32_t)(pasos - 1)));
    n++;
    idx += dir;
    if (idx >= (int32_t)pasos - 1) { idx = pasos - 1; dir = -1; }
    else if (idx <= 0)             { idx = 0;         dir = +1; }
  }
  uint32_t dt = micros() - t0;
  while (Serial.available()) Serial.read();

  g_tesc = (float)dt / (float)n;
  float prf_ms = 2.0f * (pasos - 1) * g_tesc / 1000.0f;
  float df = BW_MHZ / (float)(pasos - 1);
  float ramb = C_LUZ / (4.0f * df * 1e6f);

  Serial.printf("  %lu escrituras en %.3f s  ->  %.1f us/escritura\n",
                (unsigned long)n, dt / 1e6f, g_tesc);
  Serial.println();
  Serial.printf("  PRF minimo         : %.3f ms  (%.1f Hz)\n", prf_ms, 1000.0f / prf_ms);
  Serial.printf("  Rampa (media onda) : %.3f ms\n", prf_ms / 2.0f);
  Serial.printf("  Salto de frecuencia: %.2f MHz por escalon\n", df);
  Serial.printf("  Alcance no ambiguo : %.2f m  (canal real, c/4df)\n", ramb);
  Serial.printf("  Batido por metro   : %.0f Hz/m\n",
                2.0f * BW_MHZ * 1e6f / (C_LUZ * prf_ms / 2000.0f));
  Serial.println();
}

// --------------------------------------------------------------------------
//  Consola
// --------------------------------------------------------------------------
static void ayuda() {
  Serial.println();
  Serial.println("  sq [bajo alto]  cuadrada a maxima velocidad (osciloscopio: frecuencia)");
  Serial.println("  rampa <pasos>   triangular a maxima velocidad (osciloscopio: periodo)");
  Serial.println("  mide [n]        mide t_escritura por software (default 2000 escrituras)");
  Serial.println("  barrido         mide a 100k / 200k / 400k / 800k / 1M");
  Serial.println("  tabla           PRF vs pasos maximos, con df y alcance no ambiguo");
  Serial.println("  clk <hz>        reloj del I2C");
  Serial.println("  dc <codigo>     tension fija, 0..4095 (para el tester)");
  Serial.println("  dac             re-escanea 0x60..0x67");
  Serial.println("  info            estado");
  Serial.println("  help            esto");
  Serial.println();
}

static void info() {
  Serial.println();
  Serial.println("  ---------------- ESTADO ----------------");
  if (g_ok) Serial.printf("  MCP4725           : 0x%02X\n", g_addr);
  else      Serial.println("  MCP4725           : NO CONECTADO");
  Serial.printf("  Reloj I2C         : %lu Hz\n", (unsigned long)g_clk);
  if (g_tesc > 0.0f) {
    Serial.printf("  t_escritura       : %.1f us  (medida)\n", g_tesc);
    Serial.printf("  Cuadrada esperada : %.0f Hz\n", 1e6f / (2.0f * g_tesc));
  } else {
    Serial.println("  t_escritura       : sin medir  ('mide' o 'sq')");
  }
  Serial.printf("  BW asumido        : %.0f MHz\n", BW_MHZ);
  Serial.println("  ----------------------------------------");
  Serial.println();
}

static void procesar(String s) {
  s.trim();
  int e = s.indexOf(' ');
  String cmd = (e < 0) ? s : s.substring(0, e);
  String arg = (e < 0) ? "" : s.substring(e + 1);
  arg.trim();
  cmd.toLowerCase();

  if (cmd == "help" || cmd == "?") { ayuda(); return; }
  if (cmd == "info")               { info();  return; }

  if (cmd == "dac") {
    if (buscarDAC()) Serial.printf("[ok] MCP4725 en 0x%02X\n", g_addr);
    else             Serial.println("[aviso] no lo encuentro en 0x60..0x67");
    return;
  }

  if (!g_ok && (cmd == "sq" || cmd == "rampa" || cmd == "mide" ||
                cmd == "barrido" || cmd == "dc")) {
    Serial.println("[error] no hay DAC. Revisa SDA=GPIO0, SCL=GPIO1, VCC=3V3, GND.");
    Serial.println("        'dac' para volver a escanear.");
    return;
  }

  if (cmd == "clk") {
    long v = arg.toInt();
    if (v < 10000 || v > 1000000) { Serial.println("[error] clk entre 10000 y 1000000"); return; }
    g_clk = (uint32_t)v;
    Wire.setClock(g_clk);
    Serial.printf("[ok] reloj I2C = %lu Hz\n", (unsigned long)g_clk);
    return;
  }

  if (cmd == "dc") {
    long v = arg.toInt();
    if (v < 0 || v > DAC_MAX) { Serial.println("[error] 0..4095"); return; }
    escribir((uint16_t)v);
    Serial.printf("[ok] DAC = %ld  (%.3f V con VDD 3.300)\n", v, 3.3f * v / (float)DAC_MAX);
    return;
  }

  if (cmd == "mide") {
    uint32_t n = arg.length() ? (uint32_t)arg.toInt() : 2000;
    if (n < 100) n = 100;
    g_tesc = medir(n);
    Serial.println();
    mostrarUna(g_clk, g_tesc);
    Serial.printf("  -> con %lu escalones el PRF minimo es %.2f ms\n\n",
                  75UL, 2.0f * 74.0f * g_tesc / 1000.0f);
    return;
  }

  if (cmd == "barrido") {
    const uint32_t clks[] = {100000, 200000, 400000, 800000, 1000000};
    Serial.println();
    Serial.println("  Reloj I2C    t_escritura        desglose");
    Serial.println("  ---------------------------------------------------------");
    for (uint8_t i = 0; i < 5; i++) {
      Wire.setClock(clks[i]);
      delay(5);
      float us = medir(1500);
      mostrarUna(clks[i], us);
      if (clks[i] == g_clk) g_tesc = us;
    }
    Wire.setClock(g_clk);
    Serial.println();
    Serial.println("  Si el overhead no baja al subir el reloj, el techo lo pone");
    Serial.println("  la libreria Wire y no el bus: ahi ya no sirve acelerar mas.");
    Serial.println();
    return;
  }

  if (cmd == "sq") {
    uint16_t bajo = 0, alto = DAC_MAX;
    int e2 = arg.indexOf(' ');
    if (e2 > 0) {
      bajo = (uint16_t)arg.substring(0, e2).toInt();
      alto = (uint16_t)arg.substring(e2 + 1).toInt();
    }
    cuadrada(bajo, alto);
    return;
  }

  if (cmd == "rampa") {
    uint16_t p = (uint16_t)arg.toInt();
    if (p == 0) p = 75;
    rampaMax(p);
    return;
  }

  if (cmd == "tabla") { tablaPrf(); return; }

  Serial.printf("[error] comando desconocido: '%s'. Escribi 'help'.\n", cmd.c_str());
}

// --------------------------------------------------------------------------
void setup() {
  pinMode(PIN_MARCA, OUTPUT);
  digitalWrite(PIN_MARCA, LOW);

  Serial.begin(115200);
  uint32_t t = millis();
  while (!Serial && millis() - t < 2500) delay(10);
  delay(300);

  Serial.println();
  Serial.println("==========================================");
  Serial.println("  velocidad_dac  --  cuanto tarda el MCP4725");
  Serial.println("==========================================");

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(g_clk);

  if (buscarDAC()) {
    Serial.printf("  MCP4725 en 0x%02X\n", g_addr);
    escribir(0);
  } else {
    Serial.println("  [AVISO] No encuentro el MCP4725 en 0x60..0x67.");
    Serial.println("          SDA=GPIO0, SCL=GPIO1, VCC=3V3, GND comun,");
    Serial.println("          y pull-ups de 4k7 si el modulo no las trae.");
  }

  Serial.println();
  Serial.println("  Canal 1 del osciloscopio -> OUT del DAC");
  Serial.printf("  Canal 2 del osciloscopio -> GPIO%d (sube durante la escritura)\n", PIN_MARCA);
  ayuda();
  Serial.println("  Empeza por 'barrido', despues 'sq' y 'rampa 75'.");
  Serial.println();
}

void loop() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) { procesar(buf); buf = ""; }
    } else if (buf.length() < 40) {
      buf += c;
    }
  }
  delay(2);
}
