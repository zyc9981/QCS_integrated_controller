# Working clock and swing settings

- FPGA: HTG-930 xcvu9p-flgb2104-2-e.
- Si5341 U7: FMC I2C branch 0x40, address 0x77.
- Register image: HTG930_U7_155M3087349-Registers.txt (exact original bytes).
- Aurora reference: 155.3087349 MHz; GTREFCLK0, quads X1Y12 / X1Y14.
- Serial line rate: 25.78125 Gb/s per active lane; one lane per Aurora instance.
- FPGA initialization clock: 200 MHz. PCIe reference: 100 MHz.
- PCIe: Gen3 x1, XDMA AXI Stream 64 bits, one H2C and one C2H channel.
- Optical payload route: QSFP3 GTY X1Y49 TX -> fiber -> QSFP4 GTY X1Y58 RX.
- Streaming bitstream TX swing: X1Y49 430 mV (00001), X1Y58 490 mV (00100).
  Confirmed in generated wrappers copied into the original build; rebuild script
  source_snapshot/create_project.tcl applies these settings during generation.
- Final live IBERT swing settings: X1Y49=430 mV; other seven lanes=490 mV.
  TXPRE/TXPOST reported 0.01 / 0.00 dB. These live IBERT settings are not
  guaranteed by merely loading the archived IBERT bitstream.
- Clock restore uses volatile registers; it does not burn Si5341 NVM.
  FPGA images are loaded through JTAG into volatile configuration, not flash.
- Controller HH configuration is preserved in source_snapshot/host/HH.ini and
  the accompanying Python snapshot. Actual external reference wiring must match.

The original optimization README in evidence contains historical statements
about settings not yet being in the stream image. The current image does encode
X1Y49=430 mV and X1Y58=490 mV. Treat the current settings above as authoritative.
