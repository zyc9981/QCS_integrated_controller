#include "tx_controller_shared.h"

#include <math.h>

namespace TxControllerShared {

DACX1416* dac0 = nullptr;
DACX1416* dac1 = nullptr;
DueAdcFast dueAdcFast(1024);

float txHighVoltage = 0.0f;
float txLowVoltage = 0.0f;
uint8_t txOutputChipId = 1;
uint8_t txOutputPin = 10;
int dataIndex = 0;
int txIndex = 0;
float txVoltage = 0.0f;
unsigned long txStartMicros = 0;

float clampVoltage(float voltage) {
  if (voltage < kMinVoltage) voltage = kMinVoltage;
  if (voltage > kMaxVoltage) voltage = kMaxVoltage;
  return voltage;
}

uint16_t voltageToCode(float voltage) {
  float clampedVoltage = clampVoltage(voltage);
  float ratio = clampedVoltage / static_cast<float>(kAllRange);

  if (ratio < 0.0f) ratio = 0.0f;
  if (ratio > 1.0f) ratio = 1.0f;

  // Serial.println(static_cast<uint16_t>(roundf(ratio * kOutMax)));

  return static_cast<uint16_t>(roundf(ratio * kOutMax));
}

bool setDacVoltage(uint8_t chipId, uint8_t pin, float voltage) {
  DACX1416* dac = getDacForChip(chipId);
  if (dac == nullptr) {
    return false;
  }

  dac->set_out(pin, voltageToCode(voltage));
  return true;
}

DACX1416* getDacForChip(uint8_t chipId) {
  if (chipId == 0) {
    return dac0;
  }

  if (chipId == 1) {
    return dac1;
  }

  return nullptr;
}

int pdIndexToPin(uint8_t pdIndex) {
  switch (pdIndex) {
    case 0: return kPd0Pin;
    case 1: return kPd1Pin;
    case 2: return kPd2Pin;
    case 3: return kPd3Pin;
    case 4: return kPd4Pin;
    case 5: return kPd5Pin;
    case 6: return kPd6Pin;
    case 7: return kPd7Pin;
    case 8: return kPd8Pin;
    default: return kPd0Pin;
  }
}

uint16_t readPd(int pin) {
  return static_cast<uint16_t>(dueAdcFast.ReadAnalogPin(pin));
}

}  // namespace TxControllerShared
