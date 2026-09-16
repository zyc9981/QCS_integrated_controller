#include "rx_command_set_threshold.h"

#include "rx_controller_shared.h"
#include "rx_serial.h"

using namespace RxControllerShared;

void handleSetThresholdCommand() {
  delay(20);

  String thresholdLine = waitForLine();
  long parsedThreshold = thresholdLine.toInt();
  if (parsedThreshold < 0) {
    parsedThreshold = 0;
  }
  if (parsedThreshold > 4095) {
    parsedThreshold = 4095;
  }

  kThreshold = static_cast<uint16_t>(parsedThreshold);
  Serial.println("Done");
}
