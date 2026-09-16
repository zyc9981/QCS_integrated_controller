#include "tx_command_tx_shutdown.h"

#include "tx_controller_shared.h"

using namespace TxControllerShared;

void handleTxShutdownCommand() {
  for (int channel = 0; channel < 16; ++channel) {
    dac0->set_out(channel, 0);
    dac1->set_out(channel, 0);
  }

  dac0->sync(1);
  delay(200);
}
