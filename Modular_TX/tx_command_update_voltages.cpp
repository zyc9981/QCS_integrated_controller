#include "tx_command_update_voltages.h"

#include <stdio.h>

#include "tx_controller_shared.h"
#include "tx_serial.h"

using namespace TxControllerShared;

void handleUpdateVoltagesCommand() {
  Stream& stream = activeSerial();
  delay(200);
  stream.println("ACK");

  while (true) {
    String line = waitForSerialCommand();

    if (line.length() == 0) {
      continue;
    }

    line.trim();
    if (line.equals("END")) {
      break;
    }

    uint8_t chipId = 0;
    uint8_t pin = 0;
    float voltage = 0.0f;
    int parsed = sscanf(line.c_str(), "%hhu %hhu %f", &chipId, &pin, &voltage);
    if (parsed != 3) {
      stream.println("ERR parse");
      continue;
    }

    voltage = clampVoltage(voltage);
    // Serial.println(chipId);
    // Serial.println(pin);
    // Serial.println(voltage);
    if (!setDacVoltage(chipId, pin, voltage)) {
      stream.println(F("ERR bad chip"));
    }
  }

  dac0->sync(1);
  dac1->sync(1);
  delayMicroseconds(50);
  stream.println("Done.");
}
