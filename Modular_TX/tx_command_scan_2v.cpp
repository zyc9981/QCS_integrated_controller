#include "tx_command_scan_2v.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "tx_controller_shared.h"
#include "tx_serial.h"

namespace {

using namespace TxControllerShared;

struct ScanAxis {
  uint8_t chip;
  uint8_t pin;
  float v_init;
  float v_start;
  float v_stop;
  uint16_t N;
};

bool parseAxisLine(const String& line, ScanAxis& axis) {
  int chip = 0;
  int pin = 0;
  float initialVoltage = 0.0f;
  float startVoltage = 0.0f;
  float stopVoltage = 0.0f;
  int count = 0;

  int parsed = sscanf(
    line.c_str(),
    "%d %d %f %f %f %d",
    &chip,
    &pin,
    &initialVoltage,
    &startVoltage,
    &stopVoltage,
    &count
  );

  if (parsed != 6 || count < 1 || count > 65535) {
    return false;
  }

  axis.chip = static_cast<uint8_t>(chip);
  axis.pin = static_cast<uint8_t>(pin);
  axis.v_init = clampVoltage(initialVoltage);
  axis.v_start = clampVoltage(startVoltage);
  axis.v_stop = clampVoltage(stopVoltage);
  axis.N = static_cast<uint16_t>(count);
  return true;
}

float axisValueVsq(const ScanAxis& axis, uint16_t index) {
  float startVoltage = clampVoltage(axis.v_start);
  float stopVoltage = clampVoltage(axis.v_stop);

  float startSquared = startVoltage * startVoltage;
  float stopSquared = stopVoltage * stopVoltage;
  float t = (axis.N <= 1) ? 0.0f : (static_cast<float>(index) / static_cast<float>(axis.N - 1));
  float squaredVoltage = startSquared + t * (stopSquared - startSquared);

  if (squaredVoltage < 0.0f) squaredVoltage = 0.0f;
  return clampVoltage(sqrtf(squaredVoltage));
}

}  // namespace

void handleScan2VCommand() {
  using namespace TxControllerShared;
  Stream& stream = activeSerial();

  delay(50);
  stream.println("ACK");

  ScanAxis axis1;
  ScanAxis axis2;
  int pd1Pin = kPd0Pin;
  int pd2Pin = kPd1Pin;

  String line = waitForSerialCommand();
  if (!parseAxisLine(line, axis1)) {
    stream.println("ERR axis1");
    return;
  }

  line = waitForSerialCommand();
  if (!parseAxisLine(line, axis2)) {
    stream.println("ERR axis2");
    return;
  }

  line = waitForSerialCommand();
  int pdIndex1 = 0;
  int pdIndex2 = 0;
  if (sscanf(line.c_str(), "%d %d", &pdIndex1, &pdIndex2) != 2) {
    stream.println("ERR pds");
    return;
  }

  if (pdIndex1 < 0 || pdIndex1 > 8 || pdIndex2 < 0 || pdIndex2 > 8) {
    stream.println("ERR pds");
    return;
  }

  pd1Pin = pdIndexToPin(static_cast<uint8_t>(pdIndex1));
  pd2Pin = pdIndexToPin(static_cast<uint8_t>(pdIndex2));

  line = waitForSerialCommand();
  if (!line.equals("END")) {
    stream.println("ERR no END");
    return;
  }

  stream.println("ACK");

  uint16_t axis1Count = axis1.N;
  uint16_t axis2Count = axis2.N;
  uint32_t pointCount = static_cast<uint32_t>(axis1Count) * static_cast<uint32_t>(axis2Count);

  uint16_t* pd1Values = static_cast<uint16_t*>(malloc(pointCount * sizeof(uint16_t)));
  uint16_t* pd2Values = static_cast<uint16_t*>(malloc(pointCount * sizeof(uint16_t)));
  if (pd1Values == nullptr || pd2Values == nullptr) {
    if (pd1Values != nullptr) free(pd1Values);
    if (pd2Values != nullptr) free(pd2Values);
    stream.println("ERR alloc");
    return;
  }

  setDacVoltage(axis1.chip, axis1.pin, axis1.v_init);
  setDacVoltage(axis2.chip, axis2.pin, axis2.v_init);
  dac0->sync(1);
  dac1->sync(1);
  delayMicroseconds(50);

  const uint16_t settleTimeUs = 100;
  uint32_t valueIndex = 0;

  for (uint16_t axis1Index = 0; axis1Index < axis1Count; ++axis1Index) {
    float axis1Voltage = axisValueVsq(axis1, axis1Index);
    setDacVoltage(axis1.chip, axis1.pin, axis1Voltage);

    for (uint16_t axis2Index = 0; axis2Index < axis2Count; ++axis2Index) {
      float axis2Voltage = axisValueVsq(axis2, axis2Index);
      setDacVoltage(axis2.chip, axis2.pin, axis2Voltage);

      dac0->sync(1);
      dac1->sync(1);
      delayMicroseconds(settleTimeUs);

      pd1Values[valueIndex] = readPd(pd1Pin);
      pd2Values[valueIndex] = readPd(pd2Pin);
      valueIndex++;
    }
  }

  setDacVoltage(axis1.chip, axis1.pin, axis1.v_init);
  setDacVoltage(axis2.chip, axis2.pin, axis2.v_init);
  dac0->sync(1);
  dac1->sync(1);
  delayMicroseconds(50);

  stream.println("Scan2V Finished");
  stream.print("BEGIN ");
  stream.print(axis1Count);
  stream.print(" ");
  stream.println(axis2Count);

  stream.write(reinterpret_cast<uint8_t*>(pd1Values), pointCount * sizeof(uint16_t));
  stream.write(reinterpret_cast<uint8_t*>(pd2Values), pointCount * sizeof(uint16_t));
  stream.println("DONE");

  free(pd1Values);
  free(pd2Values);
}
