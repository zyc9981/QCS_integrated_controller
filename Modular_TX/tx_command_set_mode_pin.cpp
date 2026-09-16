#include "tx_command_set_mode_pin.h"

#include "tx_controller_shared.h"
#include "tx_serial.h"

void handleSetModePinCommand() {
  using namespace TxControllerShared;
  Stream& stream = activeSerial();

  String levelText = waitForSerialCommand();
  levelText.trim();

  if (levelText == "1" || levelText.equalsIgnoreCase("HIGH")) {
    digitalWrite(kTxModePin, HIGH);
    stream.println("Done");
  } else if (levelText == "0" || levelText.equalsIgnoreCase("LOW")) {
    digitalWrite(kTxModePin, LOW);
    stream.println("Done");
  } else {
    stream.println("ERR expected 0/1");
  }
}
