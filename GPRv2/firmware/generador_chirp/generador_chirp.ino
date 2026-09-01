// ===========================================================================
//  GPRv2 - Generador de banco (Arduino Uno)
//
//  Sustituye a toda la cadena de RF para probar en casa. Emite:
//
//    D3  senal de batido de dos blancos, a 0.60 y 1.20 m, con la no
//        linealidad REAL del VCO, mas ruido blanco. PWM de 62.5 kHz que el
//        RC del divisor convierte en analogica.
//    D2  sync: cuadrada de 100 Hz, flanco de SUBIDA justo al principio de
//        cada rampa.
//
//  La senal va 11.6 dB POR DEBAJO del ruido. No es un error: se busca el
//  caso extremo, y las ~500 rampas que entran en 5 s la levantan a 5.2 dB
//  sobre el piso del espectro. Ese punto esta cerca del umbral: con 1 dB
//  menos los picos empiezan a fallar de a ratos.
//
//  Los dos salen del mismo timer, o sea que son coherentes: el flanco cae
//  exactamente en la muestra 0 del chirp. Eso es lo que no da un generador
//  de mano, y es lo que hace falta para verificar el alineamiento.
//
//  La tabla la calcula GPRv2/analisis/generar_tabla_chirp.py desde
//  VCO/Caracteristica VCO.csv. Se precalcula porque el ATmega no llega a
//  hacer un coseno en los 62 us que tiene por muestra.
//
//  Cableado (ver GPRv2/CONTEXTO.md):
//
//    D3 ──10k──┬────────────────► VINL del modulo PCM1808
//              │
//             4k7 ∥ 4.7nF         fc = 11 kHz. Con el beat llegando a
//              │                  1096 Hz hace falta un corte ALTO: con los
//    GND ──────┴──── GND comun    43.5nF de antes (fc 1.2 kHz) el blanco
//                                 lejano se comia 3 dB y 42 grados de fase.
//                                 Lo que este RC deja pasar del PWM cae
//                                 arriba de 8 kHz y lo mata el filtro de
//                                 diezmado del PCM1808.
//
//    D2 ──10k──┬────────────────► GPIO10 del ESP32-C3
//              │
//             15k                 3.00 V. El Uno saca 5 V y el C3 no los
//              │                  tolera: el divisor NO es opcional.
//    GND ──────┴──── GND comun
//
//  Masa comun entre Uno, ESP32 y modulo, si o si.
// ===========================================================================

#include "tabla_chirp.h"

#define PIN_SYNC   2      // PORTD bit 2
#define RUIDO     98      // amplitud del ruido, en cuentas de PWM. 0 lo apaga.

static volatile uint16_t idx = 0;

// xorshift de 32 bits, no un LFSR de 16. El de 16 tiene periodo 65535, que a
// 16 kHz son 4 segundos: con capturas de 5 s el ruido se repetiria dentro de
// la misma captura y promediar rampas dejaria de bajarlo. Este dura 3 dias.
static uint32_t rnd = 2463534242UL;

ISR(TIMER1_COMPA_vect) {
  if (idx == 0)             PORTD |=  _BV(PIN_SYNC);
  else if (idx == CHIRP_N / 2) PORTD &= ~_BV(PIN_SYNC);

  rnd ^= rnd << 13;
  rnd ^= rnd >> 17;
  rnd ^= rnd << 5;
  int16_t v = (int16_t)pgm_read_byte(&chirp[idx]) +
              (((int16_t)((rnd >> 24) & 0xFF) - 128) * RUIDO) / 128;
  if (v < 0)        v = 0;
  else if (v > 255) v = 255;
  OCR2B = (uint8_t)v;

  if (++idx >= CHIRP_N) idx = 0;
}

void setup() {
  pinMode(2, OUTPUT);
  pinMode(3, OUTPUT);

  // Timer2: PWM rapido de 62.5 kHz (16 MHz / 256) en OC2B = D3, sin
  // prescaler. Cuanto mas alta la portadora, mas facil se la filtra.
  TCCR2A = _BV(COM2B1) | _BV(WGM21) | _BV(WGM20);
  TCCR2B = _BV(CS20);
  OCR2B  = 128;

  // Timer1: CTC a CHIRP_FS exactos. 16 MHz / 8000 = 2000, sin resto.
  TCCR1A = 0;
  TCCR1B = _BV(WGM12) | _BV(CS10);
  OCR1A  = (F_CPU / CHIRP_FS) - 1;
  TIMSK1 = _BV(OCIE1A);
}

void loop() {
}
