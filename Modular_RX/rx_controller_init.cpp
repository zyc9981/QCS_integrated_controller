#include "rx_controller_init.h"

#include "rx_controller_shared.h"

using namespace RxControllerShared;

void initializeRxController() {
  Serial.begin(kBaudRate);
  Serial.setTimeout(kSerialTimeoutMs);

  for (size_t detectorIndex = 0; detectorIndex < kDetectorCount; ++detectorIndex) {
    dueAdcFast.EnablePin(kDetectorPins[detectorIndex]);
  }
  dueAdcFast.Start1Mhz();

  Serial.println("RX Ready.");
}

extern "C" void ADC_Handler(void) {
  dueAdcFast.adcHandler();
}
