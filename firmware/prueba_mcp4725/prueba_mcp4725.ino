/*
 * ============================================================================
 *  Prueba del MCP4725  --  generacion de la triangular, aislada
 * ============================================================================
 *
 *  Sketch INDEPENDIENTE: no toca el PCM1808 ni el I2S. Sirve para verificar el
 *  DAC solo, con el osciloscopio, antes de integrarlo al firmware del radar.
 *
 *  El MCP4725 es I2C, no I2S. Son buses distintos y el ESP32-C3 tiene uno de
 *  cada uno, asi que conviven sin conflicto: el PCM1808 se queda en GPIO4-7 y
 *  el DAC entra por dos pines libres.
 *
 *  ---------------------------------------------------------------------------
 *  CONEXIONADO
 *  ---------------------------------------------------------------------------
 *      ESP32-C3 SuperMini        Modulo MCP4725
 *      ------------------        --------------
 *      GPIO0    <---------->     SDA
 *      GPIO1    <---------->     SCL
 *      3V3      ----------->     VCC     <-- 3.3 V, NO 5 V (ver abajo)
 *      GND      ----------->     GND
 *                                OUT  --> osciloscopio
 *
 *  Por que 3.3 V y no 5 V: la salida del MCP4725 va de 0 a VCC. A 3.3 V tus
 *  0-3 V ocupan el 91 % de la escala; a 5 V ocuparian el 60 % y perderias
 *  resolucion. Y sobre todo, a 5 V un error de software podria poner 5 V en la
 *  entrada del amplificador que maneja el VCO.
 *
 *  La mayoria de los modulos ya traen las resistencias de pull-up del bus.
 *
 *  ---------------------------------------------------------------------------
 *  ⚠ NUNCA ESCRIBIR LA EEPROM
 *  ---------------------------------------------------------------------------
 *  El MCP4725 tiene dos comandos de escritura: uno al registro volatil y otro
 *  que ademas graba en EEPROM. La EEPROM aguanta ~1 millon de ciclos y cada
 *  escritura tarda 25-50 ms. A 10.000 escalones por segundo, el comando
 *  equivocado la destruye en un minuto.
 *
 *  Aca se usa "Fast Mode Write" a mano en vez de una libreria, justamente para
 *  que quede a la vista que solo se escribe el registro volatil.
 *
 *  ---------------------------------------------------------------------------
 *  COMANDOS (Monitor Serie)
 *  ---------------------------------------------------------------------------
 *      t <ms>     duracion de UNA rampa (subida o bajada), acepta decimales
 *      prf <ms>   periodo completo de la triangular (= 2 x rampa)
 *      n <pasos>  escalones por rampa
 *      max <cod>  codigo maximo, 0..4095  (3723 = 3.00 V con VCC de 3.3 V)
 *      clk <hz>   velocidad del bus I2C (100000 / 400000 / 1000000)
 *      dc <cod>   salida fija en ese codigo, para medir con el tester
 *      run        vuelve a la triangular
 *      info       estado y medicion de tiempos
 * ============================================================================
 */

#include <Arduino.h>
#include <Wire.h>

#define PIN_SDA   0
#define PIN_SCL   1

static uint8_t  g_addr    = 0x60;      // se detecta al arrancar
static uint32_t g_rampa_us = 2500;     // duracion de UNA rampa, en us
static uint16_t g_pasos   = 200;       // escalones por rampa
static uint16_t g_max     = 3723;      // codigo maximo (3723 = 3.00 V @ 3.3 V)
static uint32_t g_clk     = 400000;    // velocidad del bus
static bool     g_corriendo = true;

static uint32_t paso_us   = 100;       // periodo de escalon, derivado
static uint32_t proximo   = 0;
static int32_t  indice    = 0;
static int8_t   sentido   = +1;

// Estadisticas
static uint32_t escalones = 0;
static uint32_t atrasos   = 0;
static uint32_t peor_us   = 0;
static uint32_t t_escritura_us = 0;
static uint32_t ciclos    = 0;
static uint32_t t_reporte = 0;


// ---------------------------------------------------------------------------
//  Escritura al DAC
// ---------------------------------------------------------------------------
//
//  Fast Mode Write: 2 bytes, solo al registro volatil.
//
//     byte 1:  0 0 PD1 PD0 D11 D10 D9 D8
//     byte 2:  D7 D6 D5 D4 D3  D2  D1 D0
//
//  Los dos bits altos en 00 seleccionan el comando rapido, y PD=00 es
//  operacion normal. Como 'valor' es de 12 bits, (valor >> 8) ya deja el
//  nibble alto en cero, o sea que el comando sale correcto solo.
//
static inline bool escribirDAC(uint16_t valor) {
  if (valor > 4095) valor = 4095;
  Wire.beginTransmission(g_addr);
  Wire.write((uint8_t)(valor >> 8));
  Wire.write((uint8_t)(valor & 0xFF));
  return Wire.endTransmission() == 0;
}


static void recalcular() {
  if (g_pasos < 2) g_pasos = 2;
  paso_us = g_rampa_us / g_pasos;
  if (paso_us < 20) paso_us = 20;        // ni el bus mas rapido baja de esto
  indice  = 0;
  sentido = +1;
  proximo = micros();
  escalones = atrasos = peor_us = ciclos = 0;
}


static bool buscarDAC() {
  // Los modulos suelen venir en 0x60..0x67 segun el pin A0
  for (uint8_t a = 0x60; a <= 0x67; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      g_addr = a;
      return true;
    }
  }
  return false;
}


static void medirEscritura() {
  // Tiempo real de una escritura, promediado sobre 200 intentos.
  // Es el numero que decide cuantos escalones por segundo se pueden.
  uint32_t t0 = micros();
  for (int i = 0; i < 200; i++) escribirDAC(2048);
  t_escritura_us = (micros() - t0) / 200;
}


static void mostrarInfo() {
  float periodo = 2.0f * g_rampa_us / 1000.0f;
  Serial.println();
  Serial.println("---------------- ESTADO ----------------");
  Serial.printf("  Direccion I2C     : 0x%02X\n", g_addr);
  Serial.printf("  Bus               : %lu Hz\n", (unsigned long)g_clk);
  Serial.printf("  Escritura medida  : %lu us  -> maximo %lu escalones/s\n",
                (unsigned long)t_escritura_us,
                (unsigned long)(t_escritura_us ? 1000000UL / t_escritura_us : 0));
  Serial.println();
  Serial.printf("  Rampa (media onda): %.3f ms\n", g_rampa_us / 1000.0f);
  Serial.printf("  Periodo triangular: %.1f ms  (%.1f Hz)\n",
                periodo, 1000.0f / periodo);
  Serial.printf("  Escalones/rampa   : %u\n", g_pasos);
  Serial.printf("  Periodo escalon   : %lu us\n", (unsigned long)paso_us);
  Serial.printf("  Codigo maximo     : %u  (%.3f V con VCC=3.3 V)\n",
                g_max, 3.3f * g_max / 4095.0f);
  Serial.printf("  Escalon en tension: %.2f mV\n", 3300.0f * g_max / 4095.0f / g_pasos);
  Serial.println();
  if (paso_us < t_escritura_us + 5) {
    Serial.println("  [AVISO] El escalon pedido es mas corto que la escritura I2C.");
    Serial.println("          Subi 't', baja 'n', o subi 'clk'.");
  }
  Serial.println("----------------------------------------");
}


static void procesar(String s) {
  s.trim();
  s.toLowerCase();
  int e = s.indexOf(' ');
  String cmd = (e < 0) ? s : s.substring(0, e);
  long  arg  = (e < 0) ? 0 : s.substring(e + 1).toInt();
  // 't' se acepta con decimales: una PRF de 5 ms son 2.5 ms por rampa, y con
  // enteros no se podria pedir.
  float argf = (e < 0) ? 0 : s.substring(e + 1).toFloat();

  if (cmd == "t" && argf > 0.05f) {
    g_rampa_us = (uint32_t)(argf * 1000.0f + 0.5f);
    recalcular();
    Serial.printf("[OK] rampa = %.3f ms (PRF %.3f ms), escalon = %lu us\n",
                  g_rampa_us / 1000.0f, 2.0f * g_rampa_us / 1000.0f,
                  (unsigned long)paso_us);
  } else if (cmd == "prf" && argf > 0.1f) {
    // Atajo: se pide el periodo completo de la triangular
    g_rampa_us = (uint32_t)(argf * 500.0f + 0.5f);
    recalcular();
    Serial.printf("[OK] PRF = %.3f ms (rampa %.3f ms), escalon = %lu us\n",
                  2.0f * g_rampa_us / 1000.0f, g_rampa_us / 1000.0f,
                  (unsigned long)paso_us);
  } else if (cmd == "n" && arg >= 2) {
    g_pasos = arg; recalcular();
    Serial.printf("[OK] %u escalones, escalon = %lu us\n",
                  g_pasos, (unsigned long)paso_us);
  } else if (cmd == "max" && arg >= 0 && arg <= 4095) {
    g_max = arg;
    Serial.printf("[OK] maximo = %u (%.3f V)\n", g_max, 3.3f * g_max / 4095.0f);
  } else if (cmd == "clk" && arg >= 100000) {
    g_clk = arg; Wire.setClock(g_clk); medirEscritura();
    Serial.printf("[OK] bus a %lu Hz, escritura %lu us\n",
                  (unsigned long)g_clk, (unsigned long)t_escritura_us);
  } else if (cmd == "dc") {
    g_corriendo = false;
    escribirDAC((uint16_t)arg);
    Serial.printf("[OK] salida fija en %ld (%.3f V)\n", arg, 3.3f * arg / 4095.0f);
  } else if (cmd == "run") {
    g_corriendo = true; recalcular();
    Serial.println("[OK] triangular");
  } else if (cmd == "info") {
    mostrarInfo();
  } else {
    Serial.println("X");
  }
}


void setup() {
  Serial.begin(115200);
  uint32_t t = millis();
  while (!Serial && millis() - t < 2500) delay(10);
  delay(300);

  Serial.println();
  Serial.println("========================================================");
  Serial.println(" Prueba del MCP4725 - triangular aislada");
  Serial.println("========================================================");

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(g_clk);

  if (!buscarDAC()) {
    Serial.println();
    Serial.println("[ERROR] No encuentro el MCP4725 en 0x60..0x67.");
    Serial.printf("  - Revisa SDA en GPIO%d y SCL en GPIO%d\n", PIN_SDA, PIN_SCL);
    Serial.println("  - Revisa VCC (3.3 V) y GND");
    Serial.println("  - Si el modulo no trae pull-ups, agrega 4k7 de SDA y SCL a 3.3 V");
    while (true) delay(500);
  }
  Serial.printf("\n  MCP4725 encontrado en 0x%02X\n", g_addr);

  medirEscritura();
  recalcular();
  mostrarInfo();
  Serial.println("\nEscribi 'info' para ver el estado, o 'dc 2048' para una continua.");
  t_reporte = millis();
}


void loop() {
  while (Serial.available()) {
    static String buf;
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) { procesar(buf); buf = ""; }
    } else if (buf.length() < 40) {
      buf += c;
    }
  }

  if (!g_corriendo) return;

  uint32_t ahora = micros();
  if ((int32_t)(ahora - proximo) >= 0) {
    // Cuanto se atraso este escalon respecto de lo programado. Es la medida
    // honesta del jitter: si crece, el bus no da abasto.
    uint32_t retraso = ahora - proximo;
    if (retraso > peor_us) peor_us = retraso;
    if (retraso > paso_us / 2) atrasos++;

    escribirDAC((uint32_t)g_max * indice / (g_pasos - 1));
    escalones++;

    indice += sentido;
    if (indice >= (int32_t)g_pasos - 1) { indice = g_pasos - 1; sentido = -1; ciclos++; }
    else if (indice <= 0)               { indice = 0;           sentido = +1; }

    // Instante absoluto: el error no se acumula aunque un escalon salga tarde
    proximo += paso_us;
    if ((int32_t)(micros() - proximo) > (int32_t)(paso_us * 4)) {
      proximo = micros();          // nos quedamos muy atras: resincronizar
    }
  }

  if (millis() - t_reporte >= 2000) {
    float seg = (millis() - t_reporte) / 1000.0f;
    Serial.printf("%7lu escalones (%6.0f/s) | %5lu ciclos (%.2f Hz) | "
                  "atrasos %lu | peor %lu us\n",
                  (unsigned long)escalones, escalones / seg,
                  (unsigned long)ciclos, ciclos / seg / 2.0f,
                  (unsigned long)atrasos, (unsigned long)peor_us);
    escalones = atrasos = peor_us = ciclos = 0;
    t_reporte = millis();
  }
}
