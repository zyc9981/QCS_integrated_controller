#ifndef TX_CONTROLLER_SHARED_H
#define TX_CONTROLLER_SHARED_H

#include <Arduino.h>

#include "DueAdcFastCompat.h"
#include "dacx1416.h"

namespace TxControllerShared {

constexpr int kBaudRate = 115200;
constexpr int kSerialTimeoutMs = 200;
constexpr uint16_t kTxPeriodUs = 100;
constexpr uint32_t kMaxInput = 2048;

constexpr int kDac0Cs = 13;
constexpr int kDac1Cs = 24;
constexpr int kDac0Reset = 28;
constexpr int kDac1Reset = 26;
constexpr int kDacLdac = 12;
constexpr int kSpiSpeed = 21000000;

constexpr int kOutMax = 65535;
constexpr uint8_t kAllRange = 40;
constexpr float kMinVoltage = 0.0f;
constexpr float kMaxVoltage = 30.0f;

constexpr int kPd0Pin = A0;
constexpr int kPd1Pin = A1;
constexpr int kPd2Pin = A2;
constexpr int kPd3Pin = A3;
constexpr int kPd4Pin = A4;
constexpr int kPd5Pin = A5;
constexpr int kPd6Pin = A6;
constexpr int kPd7Pin = A7;
constexpr int kPd8Pin = A8;
constexpr int kTxModePin = 53;
constexpr int kTriggerPin = 8;

extern DACX1416* dac0;
extern DACX1416* dac1;
extern DueAdcFast dueAdcFast;

extern float txHighVoltage;
extern float txLowVoltage;
extern uint8_t txOutputChipId;
extern uint8_t txOutputPin;
extern int dataIndex;
extern int txIndex;
extern float txVoltage;
extern unsigned long txStartMicros;

float clampVoltage(float voltage);
uint16_t voltageToCode(float voltage);
bool setDacVoltage(uint8_t chipId, uint8_t pin, float voltage);
DACX1416* getDacForChip(uint8_t chipId);
int pdIndexToPin(uint8_t pdIndex);
uint16_t readPd(int pin);

}  // namespace TxControllerShared

#endif
