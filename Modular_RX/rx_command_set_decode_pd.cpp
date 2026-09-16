#include "rx_command_set_decode_pd.h"

#include "rx_controller_shared.h"
#include "rx_serial.h"

using namespace RxControllerShared;

void handleSetDecodePdCommand() {
  delay(20);

  String pdIndexLine = waitForLine();
  int parsedPdIndex = pdIndexLine.toInt();
  decodePdIndex = clampDecodePdIndex(parsedPdIndex);

  Serial.println("Done");
}
