#include <Arduino.h>
#include "rx_controller_init.h"
#include "rx_serial.h"
#include "rx_command_stream.h"
#include "rx_command_decode_mode.h"
#include "rx_command_set_decode_pd.h"
#include "rx_command_set_threshold.h"

void setup() {
  initializeRxController();
}

void loop() {
  String command = waitForLine();

  if (command == "STREAM_START") {
    handleStreamStartCommand();
  } else if (command == "DECODE_MODE") {
    handleDecodeModeCommand();
  } else if (command == "QDCP_DECODE_MODE") {
    handleQdcpDecodeModeCommand();
  } else if (command == "SET_DECODE_PD") {
    handleSetDecodePdCommand();
  } else if (command == "SET_THRESHOLD") {
    handleSetThresholdCommand();
  }
}
