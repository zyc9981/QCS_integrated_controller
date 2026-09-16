#include "rx_command_stream.h"

#include "rx_controller_shared.h"
#include "rx_serial.h"

namespace {

using namespace RxControllerShared;

void printDetectorHeader() {
  Serial.print("  ");
  for (size_t detectorIndex = 0; detectorIndex < kDetectorCount; ++detectorIndex) {
    if (detectorIndex > 0) {
      Serial.print("   ");
    }
    Serial.print(F("PD"));
    Serial.print(detectorIndex);
  }
  Serial.println();
}

void printPaddedPdValue(uint16_t value) {
  if (value < 10000) Serial.print(' ');
  if (value < 1000) Serial.print(' ');
  if (value < 100) Serial.print(' ');
  if (value < 10) Serial.print(' ');
  Serial.print(value);
}

void streamPdLoop() {
  for (;;) {
    if (Serial.available()) {
      String command = Serial.readStringUntil('\n');
      command.trim();
      if (command == "STREAM_STOP") {
        Serial.println("Done");
        return;
      } else if (command == "SET_DECODE_PD") {
        String pdIndexLine = waitForLine();
        decodePdIndex = clampDecodePdIndex(pdIndexLine.toInt());
        Serial.println("Done");
      } else if (command == "SET_THRESHOLD") {
        String thresholdLine = waitForLine();
        long parsedThreshold = thresholdLine.toInt();
        if (parsedThreshold < 0) {
          parsedThreshold = 0;
        }
        if (parsedThreshold > 4095) {
          parsedThreshold = 4095;
        }

        kThreshold = static_cast<uint16_t>(parsedThreshold);
        Serial.println("Done");
      }
    }

    uint32_t detectorAccumulators[kDetectorCount] = {};

    for (int sampleIndex = 0; sampleIndex < pdRepeat; ++sampleIndex) {
      for (size_t detectorIndex = 0; detectorIndex < kDetectorCount; ++detectorIndex) {
        detectorAccumulators[detectorIndex] +=
          static_cast<uint32_t>(dueAdcFast.ReadAnalogPin(kDetectorPins[detectorIndex]));
      }
    }

    for (size_t detectorIndex = 0; detectorIndex < kDetectorCount; ++detectorIndex) {
      uint16_t detectorValue = static_cast<uint16_t>(
        detectorAccumulators[detectorIndex] / static_cast<uint32_t>(pdRepeat)
      );
      printPaddedPdValue(detectorValue);
      if (detectorIndex + 1 < kDetectorCount) {
        Serial.print(' ');
      }
    }
    Serial.print("\r\n");

    if (delayMs) {
      delay(delayMs);
    }
    yield();
  }
}

}  // namespace

void handleStreamStartCommand() {
  Serial.println("ACK");
  printDetectorHeader();
  streamPdLoop();
}
