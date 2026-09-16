#include "rx_command_decode_mode.h"

#include <stdlib.h>

#include "rx_controller_shared.h"

namespace {

using namespace RxControllerShared;

inline int readBit() {
  const uint8_t activePdIndex = clampDecodePdIndex(static_cast<int>(decodePdIndex));
  return (dueAdcFast.ReadAnalogPin(kDetectorPins[activePdIndex]) > kThreshold) ? 1 : 0;
}

uint16_t readU16Be(const uint8_t* bytes) {
  return (static_cast<uint16_t>(bytes[0]) << 8) | static_cast<uint16_t>(bytes[1]);
}

uint32_t readU32Be(const uint8_t* bytes) {
  return (static_cast<uint32_t>(bytes[0]) << 24) |
         (static_cast<uint32_t>(bytes[1]) << 16) |
         (static_cast<uint32_t>(bytes[2]) << 8) |
         static_cast<uint32_t>(bytes[3]);
}

float readF32Be(const uint8_t* bytes) {
  union {
    uint32_t u32;
    float f;
  } value;

  value.u32 = readU32Be(bytes);
  return value.f;
}

const __FlashStringHelper* polarizationName(uint8_t code) {
  switch (code) {
    case 0: return F("H");
    case 1: return F("V");
    case 2: return F("D");
    case 3: return F("A");
    case 4: return F("R");
    case 5: return F("L");
    default: return F("?");
  }
}

void printHex(const uint8_t* data, size_t length) {
  Serial.print(F("QDCP_HEX "));
  for (size_t index = 0; index < length; ++index) {
    if (data[index] < 16) Serial.print('0');
    Serial.print(data[index], HEX);
    if (index + 1 < length) Serial.print(' ');
  }
  Serial.println();
}

void printNamedHex(const __FlashStringHelper* label, const uint8_t* data, size_t length) {
  Serial.print(label);
  Serial.print(' ');
  for (size_t index = 0; index < length; ++index) {
    if (data[index] < 16) Serial.print('0');
    Serial.print(data[index], HEX);
    if (index + 1 < length) Serial.print(' ');
  }
  Serial.println();
}

void printIpv4Address(const uint8_t* address) {
  Serial.print(address[0]);
  Serial.print('.');
  Serial.print(address[1]);
  Serial.print('.');
  Serial.print(address[2]);
  Serial.print('.');
  Serial.print(address[3]);
}

void printQdcpTlvValue(uint8_t type, const uint8_t* value, uint16_t valueLength) {
  if (type == 0x01 && valueLength == 4) {
    Serial.print(F("QDCP_DECODE Quantum Protocol = "));
    Serial.println(readU32Be(value));
    return;
  }
  if (type == 0x02 && valueLength == 4) {
    Serial.print(F("QDCP_DECODE Polarization State = "));
    Serial.println(readF32Be(value), 6);
    return;
  }
  if (type == 0x04 && valueLength == 4) {
    Serial.print(F("QDCP_DECODE ROADM Output Port ID = "));
    Serial.println(readU32Be(value));
    return;
  }
  if (type == 0x07 && valueLength == 4) {
    Serial.print(F("QDCP_DECODE Center Frequency (GHz) = "));
    Serial.println(readF32Be(value), 6);
    return;
  }
  if (type == 0x08 && valueLength == 4) {
    Serial.print(F("QDCP_DECODE Optical Linewidth (GHz) = "));
    Serial.println(readF32Be(value), 6);
    return;
  }
  if (type == 0x09) {
    if (valueLength % 8 != 0) {
      Serial.print(F("QDCP_ERROR Polarization Correction invalid length = "));
      Serial.println(valueLength);
      return;
    }

    Serial.print(F("QDCP_DECODE Polarization Correction = "));
    for (uint16_t index = 0; index < valueLength; index += 8) {
      uint32_t durationNs = (static_cast<uint32_t>(value[index + 1]) << 16) |
                            (static_cast<uint32_t>(value[index + 2]) << 8) |
                            static_cast<uint32_t>(value[index + 3]);
      uint32_t arrivalNs = readU32Be(value + index + 4);
      Serial.print(F("(pol="));
      Serial.print(polarizationName(value[index]));
      Serial.print(F(", duration_ns="));
      Serial.print(durationNs);
      Serial.print(F(", arrival_ns="));
      Serial.print(arrivalNs);
      Serial.print(F(")"));
      if (index + 8 < valueLength) Serial.print(F(", "));
    }
    Serial.println();
    return;
  }

  Serial.print(F("QDCP_DECODE raw="));
  for (uint16_t index = 0; index < valueLength; ++index) {
    if (value[index] < 16) Serial.print('0');
    Serial.print(value[index], HEX);
  }
  Serial.println();
}

bool printQdcpDecoded(const uint8_t* packet, size_t packetLength) {
  if (packetLength < 4) {
    Serial.println(F("QDCP_ERROR Packet too short"));
    return false;
  }

  uint8_t version = (packet[0] >> 4) & 0x0F;
  uint8_t flags = packet[0] & 0x0F;
  uint16_t totalLength = readU16Be(packet + 1);
  uint8_t reserved = packet[3];

  if (version != 1) {
    Serial.print(F("QDCP_ERROR Unsupported version = "));
    Serial.println(version);
    return false;
  }
  if (totalLength != packetLength) {
    Serial.print(F("QDCP_ERROR Packet length mismatch: header="));
    Serial.print(totalLength);
    Serial.print(F(" actual="));
    Serial.println(packetLength);
    return false;
  }

  Serial.println(F("QDCP_DECODE_BEGIN"));
  Serial.print(F("QDCP_DECODE Header Version = "));
  Serial.println(version);
  Serial.print(F("QDCP_DECODE Header Flags = "));
  Serial.println(flags);
  Serial.print(F("QDCP_DECODE Header Length = "));
  Serial.println(totalLength);
  Serial.print(F("QDCP_DECODE Header Reserved = "));
  Serial.println(reserved);

  size_t offset = 4;
  uint16_t tlvIndex = 1;
  while (offset < packetLength) {
    if (offset + 4 > packetLength) {
      Serial.println(F("QDCP_ERROR Truncated TLV header"));
      Serial.println(F("QDCP_DECODE_END"));
      return false;
    }

    uint8_t type = packet[offset];
    uint8_t tlvReserved = packet[offset + 1];
    uint16_t valueLength = readU16Be(packet + offset + 2);
    offset += 4;

    if (offset + valueLength > packetLength) {
      Serial.println(F("QDCP_ERROR Truncated TLV value"));
      Serial.println(F("QDCP_DECODE_END"));
      return false;
    }

    Serial.print(F("QDCP_DECODE TLV "));
    Serial.print(tlvIndex);
    Serial.print(F(" Type = 0x"));
    if (type < 16) Serial.print('0');
    Serial.print(type, HEX);
    Serial.print(F(" Reserved = 0x"));
    if (tlvReserved < 16) Serial.print('0');
    Serial.print(tlvReserved, HEX);
    Serial.print(F(" Length = "));
    Serial.println(valueLength);
    printQdcpTlvValue(type, packet + offset, valueLength);

    offset += valueLength;
    ++tlvIndex;
  }

  Serial.println(F("QDCP_DECODE_END"));
  return true;
}

bool printIpv4UdpQdcpDecoded(const uint8_t* packet, size_t packetLength) {
  if (packetLength < 20 || (packet[0] >> 4) != 4) {
    return false;
  }

  uint8_t headerLength = static_cast<uint8_t>((packet[0] & 0x0F) * 4);
  if (headerLength < 20 || headerLength > packetLength) {
    Serial.println(F("IP_ERROR Bad IPv4 header length"));
    return true;
  }

  uint16_t totalLength = readU16Be(packet + 2);
  if (totalLength < headerLength || totalLength > packetLength) {
    Serial.print(F("IP_ERROR Bad total length: header="));
    Serial.print(totalLength);
    Serial.print(F(" actual="));
    Serial.println(packetLength);
    return true;
  }

  uint16_t fragmentInfo = readU16Be(packet + 6);
  bool moreFragments = (fragmentInfo & 0x2000u) != 0;
  uint16_t fragmentOffset = fragmentInfo & 0x1FFFu;

  printNamedHex(F("IP_PACKET_HEX"), packet, totalLength);
  Serial.println(F("IP_DECODE_BEGIN"));
  Serial.print(F("IP_DECODE Version = "));
  Serial.println((packet[0] >> 4) & 0x0F);
  Serial.print(F("IP_DECODE Header Length = "));
  Serial.println(headerLength);
  Serial.print(F("IP_DECODE Total Length = "));
  Serial.println(totalLength);
  Serial.print(F("IP_DECODE TTL = "));
  Serial.println(packet[8]);
  Serial.print(F("IP_DECODE Protocol = "));
  Serial.println(packet[9]);
  Serial.print(F("IP_DECODE Source = "));
  printIpv4Address(packet + 12);
  Serial.println();
  Serial.print(F("IP_DECODE Destination = "));
  printIpv4Address(packet + 16);
  Serial.println();

  if (moreFragments || fragmentOffset != 0) {
    Serial.println(F("IP_ERROR Fragmented IPv4 packets are not supported"));
    Serial.println(F("IP_DECODE_END"));
    return true;
  }

  if (packet[9] != 17) {
    Serial.println(F("IP_ERROR Not UDP"));
    Serial.println(F("IP_DECODE_END"));
    return true;
  }

  if (static_cast<size_t>(headerLength) + 8 > totalLength) {
    Serial.println(F("UDP_ERROR Truncated UDP header"));
    Serial.println(F("IP_DECODE_END"));
    return true;
  }

  const uint8_t* udp = packet + headerLength;
  uint16_t sourcePort = readU16Be(udp);
  uint16_t destPort = readU16Be(udp + 2);
  uint16_t udpLength = readU16Be(udp + 4);
  if (udpLength < 8 || static_cast<size_t>(headerLength) + udpLength > totalLength) {
    Serial.println(F("UDP_ERROR Bad UDP length"));
    Serial.println(F("IP_DECODE_END"));
    return true;
  }

  const uint8_t* qdcpPayload = udp + 8;
  size_t qdcpLength = static_cast<size_t>(udpLength - 8);
  Serial.print(F("UDP_DECODE Source Port = "));
  Serial.println(sourcePort);
  Serial.print(F("UDP_DECODE Destination Port = "));
  Serial.println(destPort);
  Serial.print(F("UDP_DECODE Length = "));
  Serial.println(udpLength);
  Serial.println(F("IP_DECODE_END"));

  printHex(qdcpPayload, qdcpLength);
  (void)printQdcpDecoded(qdcpPayload, qdcpLength);
  return true;
}

bool receivePayloadOnce(uint8_t** payloadOut, uint32_t* payloadLengthOut, uint32_t* bitPeriodUsOut) {
  *payloadOut = nullptr;
  *payloadLengthOut = 0;
  *bitPeriodUsOut = 0;

holdingRestart:
  while (readBit() == 0) {
  }

  if (kEdgeConfirmUs) {
    delayMicroseconds(kEdgeConfirmUs);
    if (readBit() == 0) {
      goto holdingRestart;
    }
  }

  int lastBit = 1;
  uint32_t fallingEdgeTimestamps[kFallingEdgesNeeded];
  uint16_t fallingEdgeCount = 0;

  while (fallingEdgeCount < kFallingEdgesNeeded) {
    int bit = readBit();
    if (bit == lastBit) {
      continue;
    }

    uint32_t edgeMicros = micros();

    if (kEdgeConfirmUs) {
      delayMicroseconds(kEdgeConfirmUs);
      if (readBit() != bit) {
        continue;
      }
    }

    if (lastBit == 1 && bit == 0) {
      fallingEdgeTimestamps[fallingEdgeCount] = edgeMicros;
      ++fallingEdgeCount;
    }

    lastBit = bit;
  }

  const uint16_t denominator = static_cast<uint16_t>(8u * kPrefixCount - 2u);
  if (denominator == 0) {
    Serial.println(F("Bad PREFIX_COUNT for clock recovery."));
    return false;
  }

  uint32_t bitPeriodUs =
    (fallingEdgeTimestamps[kFallingEdgesNeeded - 1] - fallingEdgeTimestamps[0]) /
    static_cast<uint32_t>(denominator);
  *bitPeriodUsOut = bitPeriodUs;
  uint32_t sampleMicros = fallingEdgeTimestamps[kFallingEdgesNeeded - 1] + 7 * bitPeriodUs / 4;

  uint32_t payloadLength = 0;
  const uint8_t lengthBits = static_cast<uint8_t>(kLenBytes * 8);

  for (uint8_t bitIndex = 0; bitIndex < lengthBits; ++bitIndex) {
    while (micros() < sampleMicros) {
    }

    int bit = readBit();
    if (bit) {
      payloadLength |= (1u << bitIndex);
    }
    sampleMicros += bitPeriodUs;
  }

  if (payloadLength > kMaxInput) {
    Serial.print(F("Bad payloadLen: "));
    Serial.println(static_cast<unsigned>(payloadLength));
    Serial.print(F("Falling edges ("));
    Serial.print(kFallingEdgesNeeded);
    Serial.println(F("):"));
    for (uint16_t index = 0; index < kFallingEdgesNeeded; ++index) {
      Serial.print(index);
      Serial.print(F(": "));
      Serial.println(fallingEdgeTimestamps[index]);
    }
    return false;
  }

  uint8_t* payload = static_cast<uint8_t*>(malloc(static_cast<size_t>(payloadLength) + 1));
  if (payload == nullptr) {
    Serial.println(F("Alloc failed; dropping packet."));
    return false;
  }

  for (uint32_t payloadIndex = 0; payloadIndex < payloadLength; ++payloadIndex) {
    uint8_t value = 0;
    for (uint8_t bitIndex = 0; bitIndex < 8; ++bitIndex) {
      while (micros() < sampleMicros) {
      }

      int bit = readBit();
      if (bit) {
        value |= (1u << bitIndex);
      }
      sampleMicros += bitPeriodUs;
    }
    payload[payloadIndex] = value;
  }
  payload[payloadLength] = '\0';

  *payloadOut = payload;
  *payloadLengthOut = payloadLength;
  return true;
}

bool receivePacketOnce() {
  uint8_t* payload = nullptr;
  uint32_t payloadLength = 0;
  uint32_t bitPeriodUs = 0;

  if (!receivePayloadOnce(&payload, &payloadLength, &bitPeriodUs)) {
    return false;
  }

  Serial.print(F("Clock="));
  Serial.print(bitPeriodUs);
  Serial.print(F("  |PayloadLen="));
  Serial.print(static_cast<unsigned>(payloadLength));
  Serial.print(F(" | Msg: "));
  Serial.println(reinterpret_cast<char*>(payload));

  free(payload);
  return true;
}

bool receiveQdcpPacketOnce() {
  uint8_t* payload = nullptr;
  uint32_t payloadLength = 0;
  uint32_t bitPeriodUs = 0;

  if (!receivePayloadOnce(&payload, &payloadLength, &bitPeriodUs)) {
    return false;
  }

  Serial.print(F("Clock="));
  Serial.print(bitPeriodUs);
  Serial.print(F("  |PayloadLen="));
  Serial.println(static_cast<unsigned>(payloadLength));
  if (!printIpv4UdpQdcpDecoded(payload, payloadLength)) {
    printHex(payload, payloadLength);
    (void)printQdcpDecoded(payload, payloadLength);
  }
  free(payload);
  return true;
}

void decodeModeForever() {
  for (;;) {
    (void)receivePacketOnce();
  }
}

void qdcpDecodeModeForever() {
  for (;;) {
    (void)receiveQdcpPacketOnce();
  }
}

}  // namespace

void handleDecodeModeCommand() {
  const uint8_t activePdIndex = clampDecodePdIndex(static_cast<int>(decodePdIndex));
  Serial.print(F("ACK PD"));
  Serial.print(static_cast<unsigned>(activePdIndex));
  Serial.print(F(" TH="));
  Serial.println(static_cast<unsigned>(kThreshold));
  decodeModeForever();
}

void handleQdcpDecodeModeCommand() {
  const uint8_t activePdIndex = clampDecodePdIndex(static_cast<int>(decodePdIndex));
  Serial.print(F("ACK QDCP PD"));
  Serial.print(static_cast<unsigned>(activePdIndex));
  Serial.print(F(" TH="));
  Serial.println(static_cast<unsigned>(kThreshold));
  qdcpDecodeModeForever();
}
