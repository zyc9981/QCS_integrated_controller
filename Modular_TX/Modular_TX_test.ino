#include "tx_controller_init.h"
#include "tx_serial.h"
#include "tx_command_update_voltages.h"
#include "tx_command_set_tx_levels.h"
#include "tx_command_tx_shutdown.h"
#include "tx_command_qdcp_packet.h"
#include "tx_command_send_message.h"
#include "tx_command_scan_2v.h"
#include "tx_command_init_voltages.h"
#include "tx_command_set_mode_pin.h"
#include "tx_controller_shared.h"

// The AWG gated-burst input needs a sustained logic level, not a short pulse.
// Each TRIGGER command toggles this retained gate state.
bool triggerLevelHigh = false;

void setup() {
  initializeTxController();
}

void loop() {
  TxInput input;
  waitForTxInput(input);

  if (input.type == TX_INPUT_QDCP_SLIP) {
    handleQdcpSlipFrame(input.payload, input.payloadLength, *input.stream);
    return;
  }

  String command = input.command;
  if (command == "UPDATE_VOLTAGES") {
    handleUpdateVoltagesCommand();
  } else if (command == "INIT_VOLTAGES") {
    handleInitVoltagesCommand();
  } else if (command == "SET_TX_LEVELS") {
    handleSetTxLevelsCommand();
  } else if (command == "TX_SHUT_DOWN") {
    handleTxShutdownCommand();
  } else if (command == "QDCP_PACKET") {
    handleQdcpPacketCommand();
  } else if (command == "QDCP_SLIP_STATUS") {
    handleQdcpSlipStatusCommand();
  } else if (command == "QDCP_SLIP_RESET_STATS") {
    handleQdcpSlipResetStatsCommand();
  } else if (command == "SEND_MESSAGE_d") {
    handleSendMessageCommand();
  } else if (command == "SET_TX_MODE_PIN") {
    handleSetModePinCommand();
  } else if (command == "SCAN_2V") {
    handleScan2VCommand();
  } else if (command == "TRIGGER") {
    triggerLevelHigh = !triggerLevelHigh;
    digitalWrite(
      TxControllerShared::kTriggerPin,
      triggerLevelHigh ? HIGH : LOW
    );
    activeSerial().println("Trigger Done");
  }
}
