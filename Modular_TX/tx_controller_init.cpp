#include "tx_controller_init.h"

#include "tx_controller_shared.h"

using namespace TxControllerShared;

void initializeTxController() {
  Serial.begin(kBaudRate);
  Serial.setTimeout(kSerialTimeoutMs);
  SerialUSB.begin(kBaudRate);
  SerialUSB.setTimeout(kSerialTimeoutMs);

  pinMode(kTxModePin, OUTPUT);
  digitalWrite(kTxModePin, LOW);

  pinMode(kTriggerPin, OUTPUT);
  digitalWrite(kTriggerPin, LOW);

  analogWriteResolution(12);
  pinMode(DAC0, OUTPUT);
  analogWrite(DAC0, 990);

  dac0 = new DACX1416(kDac0Cs, kDac0Reset, kDacLdac, &SPI, kSpiSpeed);
  dac1 = new DACX1416(kDac1Cs, kDac1Reset, kDacLdac, &SPI, kSpiSpeed);

  dac0->read_reg(R_DEVICEID);
  dac1->read_reg(R_DEVICEID);
  int result0 = dac0->init();
  int result1 = dac1->init();
  (void)result0;
  (void)result1;

  dac0->set_int_reference(false);
  dac1->set_int_reference(false);

  for (int channel = 0; channel < 16; ++channel) {
    dac0->set_ch_enabled(channel, true);
    dac0->set_range(channel, DACX1416::U_40);
    dac0->set_ch_sync(channel, true);

    dac1->set_ch_enabled(channel, true);
    dac1->set_range(channel, DACX1416::U_40);
    dac1->set_ch_sync(channel, true);
  }

  Serial.println("TX Ready.");
  SerialUSB.println("TX Ready.");

  dueAdcFast.EnablePin(kPd0Pin);
  dueAdcFast.EnablePin(kPd1Pin);
  dueAdcFast.EnablePin(kPd2Pin);
  dueAdcFast.EnablePin(kPd3Pin);
  dueAdcFast.EnablePin(kPd4Pin);
  dueAdcFast.EnablePin(kPd5Pin);
  dueAdcFast.EnablePin(kPd6Pin);
  dueAdcFast.EnablePin(kPd7Pin);
  dueAdcFast.EnablePin(kPd8Pin);
  dueAdcFast.Start1Mhz();
}

extern "C" void ADC_Handler(void) {
  dueAdcFast.adcHandler();
}
