#ifndef TX_SERIAL_H
#define TX_SERIAL_H

#include <Arduino.h>

enum TxInputType {
  TX_INPUT_COMMAND,
  TX_INPUT_QDCP_SLIP,
};

struct TxInput {
  TxInputType type;
  Stream* stream;
  String command;
  uint8_t* payload;
  size_t payloadLength;
};

Stream& activeSerial();
String waitForSerialCommand();
bool waitForTxInput(TxInput& input);

#endif
