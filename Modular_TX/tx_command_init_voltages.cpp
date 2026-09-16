#include "tx_command_init_voltages.h"

#include <stdio.h>

#include "tx_controller_shared.h"
#include "tx_serial.h"

using namespace TxControllerShared;

struct InitVoltageEntry {
  const char* name;
  uint8_t chipId;
  uint8_t pin;
  float voltage;
};

static const InitVoltageEntry kInitVoltages[] = {
  {"CQS",    1,  2, 15.0f},
  {"QS1",    1, 12,  0.0f},
  {"QS2top", 0,  5,  0.0f},
  {"QS2bot", 0, 15,  0.0f},
  {"IntSec", 0,  2,  0.0f},

  {"RTRtop", 0, 12,  0.0f},
  {"RTRbot", 1, 13,  0.0f},

  {"QF11",   0, 13,  0.0f},
  {"QF12",   0, 14,  0.0f},
  {"QF21",   0,  1,  0.0f},
  {"QF22",   0,  0,  0.0f},
  {"QF31",   0,  3,  0.0f},
  {"QF32",   0,  4,  0.0f},
  {"QF41",   0,  7,  0.0f},
  {"QF42",   0,  6,  0.0f},

  {"MUXa",   1, 15,  0.0f},
  {"PCa1",   1,  1,  0.0f},
  {"PCa2",   1,  4, 14.0f},
  {"PCa3",   1,  6, 14.0f},

  {"MUXb",   1, 14,  0.0f},
  {"PCb1",   1,  0,  0.0f},
  {"PCb2",   1,  3,  0.0f},
  {"PCb3",   1,  5,  0.0f},

  {"MUXc",   0, 11,  0.0f},
  {"PCc1",   0,  9,  0.0f},
  {"PCc2",   1, 11,  0.0f},
  {"PCc3",   1,  9,  0.0f},

  {"MUXd",   0, 10,  0.0f},
  {"PCd1",   0,  8,  0.0f},
  {"PCd2",   1, 10,  0.0f},
  {"PCd3",   1,  8,  0.0f},
};

void handleInitVoltagesCommand() {
  Stream& stream = activeSerial();
  delay(200);

  const size_t numEntries = sizeof(kInitVoltages) / sizeof(kInitVoltages[0]);

  for (size_t i = 0; i < numEntries; ++i) {
    uint8_t chipId = kInitVoltages[i].chipId;
    uint8_t pin = kInitVoltages[i].pin;
    float voltage = clampVoltage(kInitVoltages[i].voltage);

    if (!setDacVoltage(chipId, pin, voltage)) {
      stream.print(F("ERR bad chip for "));
      stream.println(kInitVoltages[i].name);
      continue;
    }
  }

  dac0->sync(1);
  dac1->sync(1);
  delayMicroseconds(50);

  stream.println("Done.");
}
