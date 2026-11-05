"""One bounded PCIe->FPGA->I2C N1 steering test; nominal is restored in finally.

This is intentionally not a general register writer. It permits only the
commissioned +1 ppm numerator and exact nominal return. Run with --live only
after loading the isolated PCIe-control FPGA image and confirming OUT8 is
already active at nominal frequency.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from qcs_clock_control.pcie_i2c import FileMmio, PcieI2cClient, PcieSi5341Transport
from qcs_clock_control.actuator import ActuatorError, NUM_ADDRS

NOMINAL = 0x01521A172853
PLUS_1PPM = 0x01521A00FFEC
FIXED = {
    0x0130: 0x06, 0x0131: 0x09, 0x0132: 0x33, 0x0133: 0x09,
    0x0313: 0x80, 0x0314: 0xDA, 0x0315: 0x51, 0x0316: 0xFD,
    0x0A03: 0x03, 0x0A04: 0x01, 0x0A05: 0x03, 0x0B4A: 0x1C,
}
PROTECTED = tuple(range(0x0235, 0x023F)) + tuple(range(0x0302, 0x030C))
EXPECTED_M = (128, 86, 194, 182, 169, 0, 0, 128, 150, 152)
EXPECTED_N0 = (0, 0, 0, 0, 22, 0, 0, 0, 0, 128)


def pack(registers, addresses):
    return tuple(registers[a] for a in addresses)


def take_snapshot(transport, fixed):
    client = transport.client
    with client:
        original_page = transport._save_page()
        try:
            addresses = set(fixed) | set(NUM_ADDRS) | set(range(0x0313, 0x0317)) | set(PROTECTED)
            registers = {address: transport._read(address) for address in sorted(addresses)}
        finally:
            transport._restore_page(original_page)
    return registers


def checks(registers):
    failures = []
    for address, expected in FIXED.items():
        if registers.get(address) != expected:
            failures.append("0x%04X expected 0x%02X got %r" % (address, expected, registers.get(address)))
    if pack(registers, NUM_ADDRS) != tuple((NOMINAL >> (8 * i)) & 0xFF for i in range(6)):
        failures.append("N1 numerator is not nominal 0x%012X" % NOMINAL)
    if pack(registers, range(0x0313, 0x0317)) != (0x80, 0xDA, 0x51, 0xFD):
        failures.append("N1 denominator does not match the verified fixed value")
    if pack(registers, range(0x0235, 0x023F)) != EXPECTED_M:
        failures.append("shared M registers differ from the previously verified state")
    if pack(registers, range(0x0302, 0x030C)) != EXPECTED_N0:
        failures.append("N0 registers differ from the previously verified state")
    if failures:
        raise ActuatorError("hardware preflight rejected: " + "; ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/xdma0_user")
    parser.add_argument("--output", required=True, help="JSON evidence path")
    parser.add_argument("--live", action="store_true", help="perform +1 ppm, then restore nominal")
    args = parser.parse_args()
    result = {"timestamp_unix": time.time(), "mode": "live" if args.live else "dry-run",
              "nominal": "0x%012X" % NOMINAL, "plus_1ppm": "0x%012X" % PLUS_1PPM,
              "device": args.device, "steps": []}
    mmio = FileMmio(args.device)
    try:
        client = PcieI2cClient(mmio)
        transport = PcieSi5341Transport(client)
        before = take_snapshot(transport, FIXED)
        checks(before)
        result["preflight"] = "PASS"
        result["before"] = {"fixed": {"0x%04X" % k: "0x%02X" % before[k] for k in sorted(FIXED)},
                            "n1_num": "0x%012X" % NOMINAL,
                            "n1_den": "0x%08X" % sum(before[a] << (8 * (a - 0x0313)) for a in range(0x0313, 0x0317)),
                            "M": list(pack(before, range(0x0235, 0x023F))),
                            "N0": list(pack(before, range(0x0302, 0x030C)))}
        if args.live:
            changed = False
            try:
                applied = transport.apply_n1(PLUS_1PPM, before)
                changed = True
                step = take_snapshot(transport, FIXED)
                expected_plus = tuple((PLUS_1PPM >> (8 * i)) & 0xFF for i in range(6))
                if pack(step, NUM_ADDRS) != expected_plus:
                    raise ActuatorError("+1 ppm N1 numerator readback mismatch")
                if pack(step, range(0x0313, 0x0317)) != pack(before, range(0x0313, 0x0317)):
                    raise ActuatorError("N1 denominator changed during update")
                if pack(step, PROTECTED) != pack(before, PROTECTED):
                    raise ActuatorError("M/N0 protected registers changed during update")
                result["steps"].append({"target": "+1 ppm", "transport": applied,
                                        "n1_num_readback": "0x%012X" % PLUS_1PPM,
                                        "denominator_unchanged": True, "M_N0_unchanged": True})
            finally:
                # Even a post-write verification failure triggers an exact return.
                current = take_snapshot(transport, FIXED)
                current_num = sum(current[a] << (8 * i) for i, a in enumerate(NUM_ADDRS))
                if current_num != NOMINAL:
                    # A failed update may leave only the shadow N1 numerator
                    # bytes staged. Permit overwrite of those six bytes only;
                    # all OUT8, divider, shared-M and N0 preconditions remain
                    # pinned to the original snapshot.
                    recovery_expected = dict(before)
                    for address in NUM_ADDRS:
                        recovery_expected[address] = current[address]
                    restored = transport.apply_n1(NOMINAL, recovery_expected)
                    result["steps"].append({"target": "nominal restore", "transport": restored})
                    changed = True
            final = take_snapshot(transport, FIXED)
            checks(final)
            if pack(final, PROTECTED) != pack(before, PROTECTED):
                raise ActuatorError("protected M/N0 readback differs after nominal restore")
            result["final"] = {"n1_num": "0x%012X" % NOMINAL,
                               "all_preconditions_restored": True,
                               "protected_M_N0_restored": True}
            result["status"] = "PASS"
        else:
            result["status"] = "DRY_RUN_PREFLIGHT_PASS"
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        mmio.close()


if __name__ == "__main__":
    main()
