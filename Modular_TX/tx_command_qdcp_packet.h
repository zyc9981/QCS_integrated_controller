#ifndef TX_COMMAND_QDCP_PACKET_H
#define TX_COMMAND_QDCP_PACKET_H

#include <Arduino.h>

void handleQdcpPacketCommand();
void handleQdcpSlipFrame(const uint8_t* packet, size_t packetLength, Stream& stream);
void handleQdcpSlipStatusCommand();
void handleQdcpSlipResetStatsCommand();

#endif
