/*
 * GPR IF Signal Sampler — ESP32
 * ==============================
 * Muestrea la señal IF (salida del LPF + Amplificador) y la envía al PC
 * por USB-Serial usando el protocolo ASCII:
 *
 *   SWEEP_START,<N_muestras>,<sample_rate_Hz>
 *   <valor_ADC>          ← repetido N veces
 *   SWEEP_END
 *
 * Cada paquete corresponde a un sweep completo del VCO (1→2 GHz).
 *
 * Conexión del ADC:
 *   Señal IF ──[Circuito DC-bias]──► GPIO34 (ADC1_CH6)
 *
 * Sincronismo (opcional):
 *   Rampa VCO ──► GPIO35  (flanco ascendente = inicio de sweep)
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * IMPORTANTE: usar siempre ADC1 (GPIO32–39).
 * ADC2 (GPIO0,2,4,12-15,25-27) comparte hardware con el driver WiFi
 * y da lecturas erróneas aunque WiFi esté deshabilitado.
 * ─────────────────────────────────────────────────────────────────────────────
 */

#include <Arduino.h>

// ══════════════════════════════════════════════ CONFIGURACIÓN ══════════════════

// ── Pin ADC ──────────────────────────────────────────────────────────────────
const int ADC_PIN  = 34;    // GPIO34 = ADC1_CH6  (input-only, ideal para ADC)

// ── Sincronismo externo (opcional) ───────────────────────────────────────────
// Conectar el pin de "inicio de rampa" del generador de barrido aquí.
// Si no tenés sync hardware, dejar USE_SYNC = false → el ESP32 genera
// sus propios sweeps temporizados.
const bool USE_SYNC = false;
const int  SYNC_PIN = 35;   // GPIO35 = ADC1_CH7  (input-only)

// ── LED de actividad ─────────────────────────────────────────────────────────
const int LED_PIN = 2;      // LED interno en la mayoría de los ESP32 DevKit

// ── Parámetros de muestreo ───────────────────────────────────────────────────
//
// SWEEP_TIME_S:  debe coincidir con el tiempo de barrido real del VCO.
//                Ajustarlo cuando se defina el tiempo de sweep definitivo.
//
// SAMPLE_RATE:   para 5 m de alcance máximo con T=1s y BW=1GHz, la frecuencia
//                beat máxima es ~33 Hz → alcanza con 200 Hz.
//                Usar 1000 Hz da buena resolución espectral y margen de sobra.
//                Actualizar también spin_fs en la GUI del PC.
//
// BAUD_RATE:     921600 es necesario para enviar 1000 muestras/s en ASCII
//                sin que el buffer se llene. No bajar de 115200.
//
const float SWEEP_TIME_S = 1.0f;
const int   SAMPLE_RATE  = 1000;     // Hz
const int   BAUD_RATE    = 921600;

// ── Derivados (no modificar) ─────────────────────────────────────────────────
const int           N_SAMPLES  = (int)(SWEEP_TIME_S * SAMPLE_RATE);
const unsigned long SAMPLE_US  = 1000000UL / SAMPLE_RATE;

// ══════════════════════════════════════════════ SETUP ═════════════════════════

void setup() {
    Serial.begin(BAUD_RATE);

    // Resolución y atenuación del ADC
    // ADC_11db → rango de entrada 0–3.1 V (aprox 3.3 V con cierta no-linealidad)
    // Si la señal IF tiene amplitud pequeña (<1 V), cambiar a ADC_6db (0–2.2 V)
    // o ADC_2_5db (0–1.5 V) para mejorar la resolución efectiva.
    analogReadResolution(12);
    analogSetPinAttenuation(ADC_PIN, ADC_11db);

    // Warm-up: las primeras lecturas del ADC ESP32 suelen ser ruidosas
    for (int i = 0; i < 50; i++) analogRead(ADC_PIN);

    if (USE_SYNC) {
        pinMode(SYNC_PIN, INPUT);
    }
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    // Indicar al PC que el dispositivo está listo
    delay(100);
    Serial.println("GPR_READY");
}

// ══════════════════════════════════════════════ LOOP ══════════════════════════

void loop() {

    // ── 1. Esperar inicio de sweep ────────────────────────────────────────────
    if (USE_SYNC) {
        // Esperar flanco ascendente en SYNC_PIN (inicio de rampa del VCO)
        while (digitalRead(SYNC_PIN) == LOW) { /* busy-wait */ }
    }

    // ── 2. Cabecera del paquete ───────────────────────────────────────────────
    Serial.print("SWEEP_START,");
    Serial.print(N_SAMPLES);
    Serial.print(",");
    Serial.println(SAMPLE_RATE);

    digitalWrite(LED_PIN, HIGH);

    // ── 3. Muestreo y envío ───────────────────────────────────────────────────
    // Se usa busy-wait sobre micros() para espaciado preciso entre muestras.
    // Esto bloquea el core durante todo el sweep, lo cual es intencional:
    // cualquier interrupción (WiFi, etc.) arruinaría el timing.
    unsigned long t0 = micros();

    for (int i = 0; i < N_SAMPLES; i++) {
        // Esperar el slot de tiempo correspondiente a esta muestra
        while ((micros() - t0) < (unsigned long)i * SAMPLE_US) { /* spin */ }

        Serial.println(analogRead(ADC_PIN));
    }

    // ── 4. Cierre del paquete ─────────────────────────────────────────────────
    Serial.println("SWEEP_END");
    digitalWrite(LED_PIN, LOW);

    // ── 5. Padding de tiempo (solo sin sync externo) ──────────────────────────
    // Esperar a completar el período de sweep para que el timing sea estable
    // entre sweeps consecutivos.
    if (!USE_SYNC) {
        unsigned long elapsed = micros() - t0;
        unsigned long period  = (unsigned long)(SWEEP_TIME_S * 1000000.0f);
        if (elapsed < period) {
            delayMicroseconds(period - elapsed);
        }
    }
}
