#include "rx_serial.h"

String waitForLine() {
  while (Serial.available() == 0) {
    yield();
  }

  String input = Serial.readStringUntil('\n');
  input.trim();
  return input;
}
