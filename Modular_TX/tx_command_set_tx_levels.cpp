#include "tx_command_set_tx_levels.h"

#include "tx_serial.h"
#include "tx_controller_shared.h"

using namespace TxControllerShared;

void handleSetTxLevelsCommand() {
  Stream& stream = activeSerial();
  delay(20);

  String chipLine = waitForSerialCommand();
  String pinLine = waitForSerialCommand();
  String lowLine = waitForSerialCommand();
  String highLine = waitForSerialCommand();

  int newChipId = chipLine.toInt();
  int newPin = pinLine.toInt();

  DACX1416* txDac = getDacForChip(static_cast<uint8_t>(newChipId));
  if (txDac == nullptr || newPin < 0 || newPin > 15) {
    stream.println("ERR invalid TX output");
    return;
  }

  float newLowVoltage = clampVoltage(lowLine.toFloat());
  float newHighVoltage = clampVoltage(highLine.toFloat());

  txLowVoltage = newLowVoltage;
  txHighVoltage = newHighVoltage;
  txOutputChipId = static_cast<uint8_t>(newChipId);
  txOutputPin = static_cast<uint8_t>(newPin);

  txDac->set_out(txOutputPin, voltageToCode(txLowVoltage));
  txDac->sync(1);

  delayMicroseconds(50);
  stream.println("Done");
}
