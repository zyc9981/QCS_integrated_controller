#include "tx_serial.h"

#include "tx_controller_shared.h"

namespace {

using namespace TxControllerShared;

constexpr uint8_t kSlipEnd = 0xC0;
constexpr uint8_t kSlipEsc = 0xDB;
constexpr uint8_t kSlipEscEnd = 0xDC;
constexpr uint8_t kSlipEscEsc = 0xDD;
constexpr size_t kLineBufferSize = 96;

struct PortState {
  Stream* stream;
  char line[kLineBufferSize];
  size_t lineLength;
  bool inSlipFrame;
  bool slipEscaped;
  uint8_t slipBuffer[kMaxInput];
  size_t slipLength;
};

PortState serialState = {&Serial, "", 0, false, false, {0}, 0};
PortState serialUsbState = {&SerialUSB, "", 0, false, false, {0}, 0};
Stream* currentStream = nullptr;

String readLineFromStream(Stream& stream) {
  String input = stream.readStringUntil('\n');
  input.trim();
  return input;
}

bool pollPort(PortState& state, TxInput& input) {
  while (state.stream->available()) {
    uint8_t byte = static_cast<uint8_t>(state.stream->read());

    if (state.inSlipFrame) {
      if (byte == kSlipEnd) {
        state.inSlipFrame = false;
        state.slipEscaped = false;

        if (state.slipLength > 0) {
          input.type = TX_INPUT_QDCP_SLIP;
          input.stream = state.stream;
          input.command = "";
          input.payload = state.slipBuffer;
          input.payloadLength = state.slipLength;
          currentStream = state.stream;
          return true;
        }
        continue;
      }

      if (state.slipEscaped) {
        if (byte == kSlipEscEnd) {
          byte = kSlipEnd;
        } else if (byte == kSlipEscEsc) {
          byte = kSlipEsc;
        } else {
          state.slipEscaped = false;
          state.slipLength = 0;
          state.inSlipFrame = false;
          continue;
        }
        state.slipEscaped = false;
      } else if (byte == kSlipEsc) {
        state.slipEscaped = true;
        continue;
      }

      if (state.slipLength < kMaxInput) {
        state.slipBuffer[state.slipLength++] = byte;
      } else {
        state.slipLength = 0;
        state.inSlipFrame = false;
        state.slipEscaped = false;
      }
      continue;
    }

    if (byte == kSlipEnd) {
      state.lineLength = 0;
      state.inSlipFrame = true;
      state.slipEscaped = false;
      state.slipLength = 0;
      continue;
    }

    if (byte == '\r') {
      continue;
    }

    if (byte == '\n') {
      state.line[state.lineLength] = '\0';
      input.type = TX_INPUT_COMMAND;
      input.stream = state.stream;
      input.command = String(state.line);
      input.command.trim();
      input.payload = nullptr;
      input.payloadLength = 0;
      state.lineLength = 0;
      currentStream = state.stream;
      return true;
    }

    if (state.lineLength < kLineBufferSize - 1) {
      state.line[state.lineLength++] = static_cast<char>(byte);
    } else {
      state.lineLength = 0;
    }
  }

  return false;
}

}  // namespace

Stream& activeSerial() {
  return currentStream == nullptr ? Serial : *currentStream;
}

String waitForSerialCommand() {
  if (currentStream != nullptr) {
    return readLineFromStream(*currentStream);
  }

  TxInput input;
  while (true) {
    if (waitForTxInput(input) && input.type == TX_INPUT_COMMAND) {
      return input.command;
    }
  }
}

bool waitForTxInput(TxInput& input) {
  while (true) {
    if (pollPort(serialState, input)) {
      return true;
    }
    if (pollPort(serialUsbState, input)) {
      return true;
    }
  }
}
