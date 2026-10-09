# HTG-930 IBERT TX swing optimization — 2026-10-08

## Final live IBERT TX swing settings

| GTY TX | Swing |
|---|---:|
| X1Y48 | 490 mV |
| X1Y49 | 430 mV |
| X1Y50 | 490 mV |
| X1Y51 | 490 mV |
| X1Y56 | 490 mV |
| X1Y57 | 490 mV |
| X1Y58 | 490 mV |
| X1Y59 | 490 mV |

TXPRE/TXPOST were left at their original 0.01 dB / 0.00 dB values. All RX lanes acquired PRBS31 and stayed linked during the final 60-second measurement.

## Final simultaneous RX BER check

| GTY RX | Errors | Bits checked | Measured BER |
|---|---:|---:|---:|
| X1Y48 | 0 | 1,565,481,857,520 | 0 observed |
| X1Y49 | 0 | 1,565,528,757,040 | 0 observed |
| X1Y50 | 0 | 1,565,445,465,360 | 0 observed |
| X1Y51 | 0 | 1,565,468,894,160 | 0 observed |
| X1Y56 | 0 | 1,565,427,266,720 | 0 observed |
| X1Y57 | 0 | 1,565,437,999,920 | 0 observed |
| X1Y58 | 1,371 | 1,565,389,321,120 | 8.76e-10 |
| X1Y59 | 0 | 1,565,370,172,960 | 0 observed |

For zero-error lanes, zero was observed in the sample; it is not a claim of mathematically zero BER. The approximate 95% upper bound is 3/N, about 1.92e-12 for these sample sizes.

X1Y49 was fine-swept against X1Y58. The best 10-second point was 430 mV (62 errors / 258,599,415,440 bits = 2.40e-10). A 60-second confirmation at 430 mV measured 366 errors / 1,547,527,655,520 bits = 2.37e-10. In the final all-lane 60-second run, X1Y58 measured 8.76e-10. This variation means the low-rate result is not perfectly repeatable yet, although it is dramatically below the all-950-mV baseline.

## Data files

- `ibert_swing_sweep_20261008_195104.csv`: seven-point swing sweep for each of eight TX lanes, with all RX counters recorded per point.
- `verify_all_lanes_490mV_60s.csv`: simultaneous 60-second validation with every TX at 490 mV.
- `tx49_rx58_fine_20261008_200207.csv`: fine swing sweep and 60-second confirmation for X1Y49 TX to X1Y58 RX.
- `final_all_lane_60s.csv`: final simultaneous 60-second validation at X1Y49=430 mV and all other TX=490 mV.

The settings are live IBERT register values. They are volatile and will be lost when a different bitstream is programmed or the FPGA is reset; they are not yet encoded in the HH/QSFP streaming bitstream.
