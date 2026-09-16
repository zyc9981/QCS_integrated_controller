#include "rx_controller_shared.h"

namespace RxControllerShared {

DueAdcFast dueAdcFast(1024);
volatile int pdRepeat = 5;
volatile uint16_t delayMs = 50;
volatile uint16_t kThreshold = 500;
volatile uint8_t decodePdIndex = 1;

uint16_t readPdChannel(int pin) {
  uint32_t accumulator = 0;
  for (int index = 0; index < pdRepeat; ++index) {
    accumulator += static_cast<uint32_t>(dueAdcFast.ReadAnalogPin(pin));
  }
  return static_cast<uint16_t>(accumulator / static_cast<uint32_t>(pdRepeat));
}

uint8_t clampDecodePdIndex(int pdIndex) {
  if (pdIndex < 0) {
    return 0;
  }

  if (pdIndex >= static_cast<int>(kDetectorCount)) {
    return static_cast<uint8_t>(kDetectorCount - 1);
  }

  return static_cast<uint8_t>(pdIndex);
}

}  // namespace RxControllerShared
