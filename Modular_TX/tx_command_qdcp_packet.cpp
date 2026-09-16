#include "tx_command_qdcp_packet.h"

#include <stdlib.h>

#include "tx_controller_shared.h"
#include "tx_command_send_message.h"
#include "tx_serial.h"

namespace {

using namespace TxControllerShared;

struct QdcpSlipStats {
  uint32_t slipFrames;
  uint32_t rawQdcpFrames;
  uint32_t ipv4Frames;
  uint32_t udpPayloads;
  uint32_t qdcpAccepted;
  uint32_t qdcpInvalid;
  uint32_t tooLong;
  uint32_t txOk;
  uint32_t txFailed;
  size_t lastFrameLength;
  size_t lastPayloadLength;
};

QdcpSlipStats qdcpSlipStats = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

uint16_t readU16Be(const uint8_t* bytes) {
  return (static_cast<uint16_t>(bytes[0]) << 8) | static_cast<uint16_t>(bytes[1]);
}

bool qdcpLengthLooksValid(const uint8_t* packet, size_t packetLength) {
  return packet != nullptr &&
         packetLength >= 4 &&
         ((packet[0] >> 4) == 1) &&
         readU16Be(packet + 1) == packetLength;
}

bool extractUdpPayloadFromIpv4(
  const uint8_t* frame,
  size_t frameLength,
  const uint8_t** payload,
  size_t* payloadLength
) {
  *payload = nullptr;
  *payloadLength = 0;

  if (frameLength < 20 || (frame[0] >> 4) != 4) {
    return false;
  }

  uint8_t headerLength = static_cast<uint8_t>((frame[0] & 0x0F) * 4);
  if (headerLength < 20 || headerLength > frameLength) {
    return true;
  }

  uint16_t totalLength = readU16Be(frame + 2);
  if (totalLength < headerLength || totalLength > frameLength) {
    return true;
  }

  uint16_t fragmentInfo = readU16Be(frame + 6);
  bool moreFragments = (fragmentInfo & 0x2000u) != 0;
  uint16_t fragmentOffset = fragmentInfo & 0x1FFFu;
  if (moreFragments || fragmentOffset != 0) {
    return true;
  }

  if (frame[9] != 17) {
    return true;
  }

  if (static_cast<size_t>(headerLength) + 8 > totalLength) {
    return true;
  }

  const uint8_t* udp = frame + headerLength;
  uint16_t sourcePort = readU16Be(udp);
  uint16_t destPort = readU16Be(udp + 2);
  (void)sourcePort;
  (void)destPort;
  uint16_t udpLength = readU16Be(udp + 4);
  if (udpLength < 8 || static_cast<size_t>(headerLength) + udpLength > totalLength) {
    return true;
  }

  *payload = udp + 8;
  *payloadLength = static_cast<size_t>(udpLength - 8);
  return true;
}

size_t readLineFromStream(Stream& stream, char* buffer, size_t maxLen) {
  if (maxLen == 0) return 0;

  size_t index = 0;
  unsigned long startMillis = millis();

  while (millis() - startMillis < 5000) {
    while (stream.available()) {
      char current = static_cast<char>(stream.read());

      if (current == '\r') continue;
      if (current == '\n') {
        buffer[index] = '\0';
        return index;
      }

      if (index < maxLen - 1) {
        buffer[index++] = current;
      }
    }
  }

  buffer[index] = '\0';
  return index;
}

bool readExactFromStream(Stream& stream, uint8_t* buffer, size_t byteCount, unsigned long timeoutMs) {
  size_t bytesRead = 0;
  unsigned long startMillis = millis();

  while (bytesRead < byteCount && (millis() - startMillis < timeoutMs)) {
    while (stream.available() && bytesRead < byteCount) {
      buffer[bytesRead++] = static_cast<uint8_t>(stream.read());
    }
  }

  return bytesRead == byteCount;
}

}  // namespace

void handleQdcpPacketCommand() {
  Stream& stream = activeSerial();
  stream.println("READY_FOR_QDCP");

  char lengthBuffer[24];
  size_t lengthSize = readLineFromStream(stream, lengthBuffer, sizeof(lengthBuffer));
  if (lengthSize == 0) {
    stream.println("ERR_NO_LENGTH");
    return;
  }

  long packetLength = atol(lengthBuffer);
  if (packetLength <= 0 || packetLength > static_cast<long>(TxControllerShared::kMaxInput)) {
    stream.println("ERR_BAD_LENGTH");
    return;
  }

  stream.println("SEND_QDCP_BYTES");

  uint8_t* packet = static_cast<uint8_t*>(malloc(static_cast<size_t>(packetLength)));
  if (packet == nullptr) {
    stream.println("ERR_ALLOC");
    return;
  }

  bool ok = readExactFromStream(stream, packet, static_cast<size_t>(packetLength), 5000);
  if (!ok) {
    free(packet);
    stream.println("ERR_READ_TIMEOUT");
    return;
  }

  bool txOk = transmitPhotonPayload(packet, static_cast<size_t>(packetLength), stream);
  stream.println(txOk ? F("QDCP_TX_DONE") : F("QDCP_TX_FAILED"));

  free(packet);
}

void handleQdcpSlipFrame(const uint8_t* packet, size_t packetLength, Stream& stream) {
  qdcpSlipStats.slipFrames++;
  qdcpSlipStats.lastFrameLength = packetLength;
  qdcpSlipStats.lastPayloadLength = 0;

  if (packet == nullptr || packetLength == 0) {
    stream.println(F("ERR_EMPTY_QDCP_SLIP"));
    qdcpSlipStats.qdcpInvalid++;
    return;
  }

  const uint8_t* qdcpPayload = packet;
  size_t qdcpLength = packetLength;
  bool ipOverSlip = false;

  if (extractUdpPayloadFromIpv4(packet, packetLength, &qdcpPayload, &qdcpLength)) {
    ipOverSlip = true;
    qdcpSlipStats.ipv4Frames++;
    if (qdcpPayload == nullptr) {
      qdcpSlipStats.qdcpInvalid++;
      return;
    }
    qdcpSlipStats.udpPayloads++;
  } else {
    qdcpSlipStats.rawQdcpFrames++;
  }

  qdcpSlipStats.lastPayloadLength = qdcpLength;

  if (qdcpLength > TxControllerShared::kMaxInput) {
    qdcpSlipStats.tooLong++;
    if (!ipOverSlip) stream.println(F("ERR_QDCP_PAYLOAD_TOO_LONG"));
    return;
  }

  size_t transmitLength = ipOverSlip ? packetLength : qdcpLength;
  const uint8_t* transmitPayload = ipOverSlip ? packet : qdcpPayload;
  if (transmitLength > TxControllerShared::kMaxInput) {
    qdcpSlipStats.tooLong++;
    return;
  }

  if (!qdcpLengthLooksValid(qdcpPayload, qdcpLength)) {
    qdcpSlipStats.qdcpInvalid++;
    if (!ipOverSlip) stream.println(F("ERR_QDCP_BAD_PACKET"));
    return;
  }

  qdcpSlipStats.qdcpAccepted++;
  bool ok = transmitPhotonPayload(transmitPayload, transmitLength, stream, !ipOverSlip);
  if (ok) {
    qdcpSlipStats.txOk++;
  } else {
    qdcpSlipStats.txFailed++;
  }
  if (!ipOverSlip) {
    stream.println(ok ? F("QDCP_TX_DONE") : F("QDCP_TX_FAILED"));
  }
}

void handleQdcpSlipStatusCommand() {
  Stream& stream = activeSerial();

  stream.println(F("QDCP_STATUS_BEGIN"));
  stream.print(F("slip_frames="));
  stream.println(qdcpSlipStats.slipFrames);
  stream.print(F("raw_qdcp_frames="));
  stream.println(qdcpSlipStats.rawQdcpFrames);
  stream.print(F("ipv4_frames="));
  stream.println(qdcpSlipStats.ipv4Frames);
  stream.print(F("udp_payloads="));
  stream.println(qdcpSlipStats.udpPayloads);
  stream.print(F("qdcp_accepted="));
  stream.println(qdcpSlipStats.qdcpAccepted);
  stream.print(F("qdcp_invalid="));
  stream.println(qdcpSlipStats.qdcpInvalid);
  stream.print(F("too_long="));
  stream.println(qdcpSlipStats.tooLong);
  stream.print(F("tx_ok="));
  stream.println(qdcpSlipStats.txOk);
  stream.print(F("tx_failed="));
  stream.println(qdcpSlipStats.txFailed);
  stream.print(F("last_frame_len="));
  stream.println(qdcpSlipStats.lastFrameLength);
  stream.print(F("last_payload_len="));
  stream.println(qdcpSlipStats.lastPayloadLength);
  stream.println(F("QDCP_STATUS_END"));
}

void handleQdcpSlipResetStatsCommand() {
  qdcpSlipStats = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
  activeSerial().println(F("QDCP_STATUS_RESET"));
}
