#ifndef RX_CONTROLLER_SHARED_H
#define RX_CONTROLLER_SHARED_H

#include <Arduino.h>

#include "DueAdcFastCompat.h"

namespace RxControllerShared {

constexpr int kBaudRate = 115200;
constexpr int kSerialTimeoutMs = 200;

constexpr int kPd0Pin = A0;
constexpr int kPd1Pin = A1;
constexpr int kPd2Pin = A2;
constexpr int kPd3Pin = A3;
constexpr int kPd4Pin = A4;
constexpr int kPd5Pin = A5;
constexpr int kPd6Pin = A6;
constexpr int kPd7Pin = A7;
constexpr int kPd8Pin = A8;

constexpr int kDetectorPins[] = {
  kPd0Pin,
  kPd1Pin,
  kPd2Pin,
  kPd3Pin,
  kPd4Pin,
  kPd5Pin,
  kPd6Pin,
  kPd7Pin,
  kPd8Pin
};
constexpr size_t kDetectorCount = sizeof(kDetectorPins) / sizeof(kDetectorPins[0]);

extern volatile uint16_t kThreshold;
extern volatile uint8_t decodePdIndex;

constexpr uint8_t kPrefixCount = 5;
constexpr uint16_t kEdgeConfirmUs = 2;
constexpr uint32_t kMaxInput = 2048;

constexpr uint8_t calcLenBytesU32(uint32_t value) {
  return (value <= 0xFFu) ? 1
       : (value <= 0xFFFFu) ? 2
       : (value <= 0xFFFFFFu) ? 3
       : 4;
}

constexpr uint8_t kLenBytes = calcLenBytesU32(kMaxInput);
constexpr uint16_t kFallingEdgesNeeded = static_cast<uint16_t>(4u * kPrefixCount);

extern DueAdcFast dueAdcFast;
extern volatile int pdRepeat;
extern volatile uint16_t delayMs;

uint16_t readPdChannel(int pin);
uint8_t clampDecodePdIndex(int pdIndex);

}  // namespace RxControllerShared

#endif
