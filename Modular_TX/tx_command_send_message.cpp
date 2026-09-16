#include "tx_command_send_message.h"

#include <stdlib.h>

#include "modem.h"
#include "tx_controller_shared.h"
#include "tx_serial.h"

namespace {

using namespace TxControllerShared;

constexpr uint8_t kPrefixCount = 5;
constexpr uint8_t kPrefixByte = 'U';

constexpr uint8_t calcLenBytesU32(uint32_t value) {
  return (value <= 0xFFu) ? 1
       : (value <= 0xFFFFu) ? 2
       : (value <= 0xFFFFFFu) ? 3
       : 4;
}

constexpr uint8_t kLenBytes = calcLenBytesU32(kMaxInput);

}  // namespace

bool transmitPhotonPayload(const uint8_t* payload, size_t payloadLength, Stream& stream, bool printStatus) {
  using namespace TxControllerShared;

  DACX1416* txDac = getDacForChip(txOutputChipId);
  if (txDac == nullptr || txOutputPin > 15) {
    if (printStatus) stream.println("ERR invalid TX output");
    return false;
  }

  if (payload == nullptr || payloadLength > kMaxInput) {
    if (printStatus) stream.println("ERR invalid payload");
    return false;
  }

  size_t totalLength = kPrefixCount + kLenBytes + payloadLength;
  if (printStatus) stream.println(totalLength);

  uint8_t* packet = static_cast<uint8_t*>(malloc(totalLength));
  if (packet == nullptr) {
    if (printStatus) stream.println("ERR alloc");
    return false;
  }

  size_t packetIndex = 0;
  for (uint8_t prefixIndex = 0; prefixIndex < kPrefixCount; ++prefixIndex) {
    packet[packetIndex++] = kPrefixByte;
  }

  for (uint8_t lengthIndex = 0; lengthIndex < kLenBytes; ++lengthIndex) {
    packet[packetIndex++] = static_cast<uint8_t>((payloadLength >> (8 * lengthIndex)) & 0xFF);
  }

  for (size_t payloadIndex = 0; payloadIndex < payloadLength; ++payloadIndex) {
    packet[packetIndex++] = payload[payloadIndex];
  }

  bool* packetBits = static_cast<bool*>(malloc(totalLength * 8 * sizeof(bool)));
  if (packetBits == nullptr) {
    free(packet);
    if (printStatus) stream.println("ERR alloc");
    return false;
  }

  Encoder(reinterpret_cast<char*>(packet), static_cast<int>(totalLength), packetBits);

  txStartMicros = micros();
  txIndex = 0;
  dataIndex = 0;

  while (true) {
    if (micros() - txStartMicros >= static_cast<unsigned long>(txIndex) * kTxPeriodUs) {
      if (txIndex < static_cast<int>(totalLength * 8)) {
        txVoltage = (packetBits[dataIndex] == 0) ? txLowVoltage : txHighVoltage;
        dataIndex++;
        txDac->set_out(txOutputPin, voltageToCode(txVoltage));
        txDac->sync(1);
        txIndex++;
        delayMicroseconds(30);
      } else {
        txDac->set_out(txOutputPin, voltageToCode(txLowVoltage));
        txDac->sync(1);
        break;
      }
    }
  }

  free(packetBits);
  free(packet);
  return true;
}

void handleSendMessageCommand() {
  using namespace TxControllerShared;
  Stream& stream = activeSerial();

  while (!stream.available()) {
  }

  uint8_t inputBuffer[kMaxInput + 1];
  size_t payloadLength = stream.readBytesUntil('\n', reinterpret_cast<char*>(inputBuffer), kMaxInput);
  inputBuffer[payloadLength] = '\0';

  (void)transmitPhotonPayload(inputBuffer, payloadLength, stream);
  stream.println("Done");
}
