#ifndef TX_COMMAND_SEND_MESSAGE_H
#define TX_COMMAND_SEND_MESSAGE_H

#include <Arduino.h>

void handleSendMessageCommand();
bool transmitPhotonPayload(
  const uint8_t* payload,
  size_t payloadLength,
  Stream& stream,
  bool printStatus = true
);

#endif
