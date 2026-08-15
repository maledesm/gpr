#define ADC_PIN 0            // GPIO 0 (ADC1_CH0) para el Emisor del BC548
#define LED_PIN 8            // Pin del LED azul integrado en el ESP32-C3 Super Mini
#define SAMPLE_RATE_HZ 1000  // Frecuencia de muestreo deseada

const unsigned long SAMPLE_PERIOD_US = 1000000 / SAMPLE_RATE_HZ;
unsigned long next_sample_time = 0;

// Variables para el parpadeo no bloqueante del LED
unsigned long last_led_toggle = 0;
const unsigned long LED_INTERVAL_MS = 500; // El LED cambiará de estado cada 500 ms (Medio segundo)
bool led_state = false;

void setup() {
  Serial.begin(115200);
  
  // Configuración del LED
  pinMode(LED_PIN, OUTPUT);
  
  // Configuración del ADC (12 bits, atenuación 11dB para rango hasta ~2.5V)
  analogReadResolution(12);
  analogSetPinAttenuation(ADC_PIN, ADC_11db);
  pinMode(ADC_PIN, INPUT);

  delay(1000); // Pequeña pausa inicial

  // Parpadeo rápido inicial para avisar que acaba de reiniciar
  for(int i = 0; i < 6; i++) {
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    delay(100);
  }

  Serial.println("Timestamp_us,Raw_ADC,Voltage_V");
  next_sample_time = micros();
}

void loop() {
  unsigned long current_micros = micros();
  unsigned long current_millis = millis();

  // 1. Tarea del LED: Parpadear de forma independiente y asíncrona
  if (current_millis - last_led_toggle >= LED_INTERVAL_MS) {
    last_led_toggle = current_millis;
    led_state = !led_state;
    digitalWrite(LED_PIN, led_state);
  }

  // 2. Tarea del Muestreo: Ejecutar solo cuando toque
  if (current_micros >= next_sample_time) {
    // Registrar el tiempo exacto
    unsigned long sample_time = micros();
    
    // Leer el ADC
    int raw_value = analogRead(ADC_PIN);
    
    // Convertir a voltaje
    float voltage = (raw_value / 4095.0) * 3.3;

    // Enviar datos CSV
    Serial.print(sample_time);
    Serial.print(",");
    Serial.print(raw_value);
    Serial.print(",");
    Serial.println(voltage, 4);

    // Calcular próximo instante absoluto
    next_sample_time += SAMPLE_PERIOD_US;
  }
}