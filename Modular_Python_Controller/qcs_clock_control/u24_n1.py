"""Runtime controls for the commissioned U24 N1 -> OUT9 path only."""
from fractions import Fraction

from .actuator import ActuatorError, NUM_ADDRS, build_n1_register_plan
from .pcie_i2c import EXPECTED_ID, REG_ID, PcieI2cClient, FileMmio
from .u24_cbpro import (EXPECTED_DEVICE_ID, OUT_CONTROL_ADDRS, U24_ADDRESS,
                        U24_MUX_MASK, _u24_command)


NOMINAL_NUMERATOR = 0x004550000000
N1_DENOMINATOR = 0xA0000000
N1_STEP_WORD = 14885  # CBPro: 50.0008556 ppb per direct N1 word step.
MAX_ABSOLUTE_PPM = Fraction(200, 1)
EXPECTED_STATIC = {
    0x000B: 0x74, 0x0021: 0x0F,
    0x013A: 0x02, 0x013B: 0x09, 0x013C: 0x33, 0x013D: 0x09,
    0x0313: 0x00, 0x0314: 0x00, 0x0315: 0x00, 0x0316: 0xA0,
    0x0A03: 0x02, 0x0A04: 0x00, 0x0A05: 0x02, 0x0B4A: 0x1D,
}
for _address in OUT_CONTROL_ADDRS[:-1]:
    EXPECTED_STATIC[_address] = 0x01


def _round_nearest(value):
    value = Fraction(value)
    quotient, remainder = divmod(abs(value.numerator), value.denominator)
    rounded = quotient + (1 if 2 * remainder >= value.denominator else 0)
    return rounded if value >= 0 else -rounded


def calculate_u24_n1_ppm(requested_ppm):
    """Return a step-word-aligned N1 numerator for ppm relative to CBPro nominal.

    Positive ppm means a faster OUT9 clock, therefore a smaller N1 numerator.
    The output is quantized to the 14885-count CBPro DCO word.
    """
    ppm = Fraction(str(requested_ppm))
    if abs(ppm) > MAX_ABSOLUTE_PPM:
        raise ValueError("U24 correction is limited to +/-200 ppm")
    desired = ppm / 1000000
    raw_target = Fraction(NOMINAL_NUMERATOR, 1) / (1 + desired)
    steps = _round_nearest((Fraction(NOMINAL_NUMERATOR, 1) - raw_target) /
                           N1_STEP_WORD)
    target = NOMINAL_NUMERATOR - steps * N1_STEP_WORD
    if not 0 < target < (1 << 44):
        raise ValueError("requested N1 numerator is outside the 44-bit range")
    actual_ppm = (Fraction(NOMINAL_NUMERATOR, target) - 1) * 1000000
    if abs(actual_ppm) > MAX_ABSOLUTE_PPM:
        raise ValueError("nearest DCO step exceeds the +/-200 ppm range")
    return {
        "requested_ppm": str(ppm),
        "representable_ppm": float(actual_ppm),
        "steps_from_nominal": steps,
        "step_word": N1_STEP_WORD,
        "numerator": target,
        "numerator_hex": "0x%012X" % target,
        "nominal_hz": 20000000,
        "representable_hz_from_nominal": 20000000.0 *
            (1.0 + float(actual_ppm) / 1000000.0),
        "register_bytes_lsb_first": [
            {"address": "0x%04X" % address,
             "value": "0x%02X" % ((target >> (8 * index)) & 0xFF)}
            for index, address in enumerate(NUM_ADDRS)],
    }


def _read(client, register, page_select=True):
    return client.transact(_u24_command(register, read=True,
                                        page_select=page_select))


def _write(client, register, value):
    return client.transact(_u24_command(register, value=value))


def _restore_page(client, page):
    _read(client, (int(page) << 8), page_select=True)
    actual = _read(client, 1, page_select=False)
    if actual != page:
        raise ActuatorError("U24 page restore readback mismatch")


def read_u24_state(client):
    """Read and validate the active U24 profile; restore the original page."""
    with client:
        page = _read(client, 1, page_select=False)
        try:
            identity = {address: _read(client, address)
                        for address in EXPECTED_DEVICE_ID}
            if identity != EXPECTED_DEVICE_ID:
                raise ActuatorError("U24 Si5341 identity/readiness mismatch: %r" % identity)
            addresses = set(EXPECTED_STATIC) | set(NUM_ADDRS)
            addresses.update(range(0x0313, 0x0317))
            registers = {address: _read(client, address)
                         for address in sorted(addresses)}
            mismatches = [(address, expected, registers.get(address))
                          for address, expected in EXPECTED_STATIC.items()
                          if registers.get(address) != expected]
            if mismatches:
                raise ActuatorError("U24 profile precondition mismatch: %s" %
                                    "; ".join("0x%04X expected 0x%02X got 0x%02X" % x
                                              for x in mismatches))
            denominator = sum(registers[address] << (8 * index)
                              for index, address in enumerate(range(0x0313, 0x0317)))
            if denominator != N1_DENOMINATOR:
                raise ActuatorError("U24 N1 denominator is not the reviewed 0x%08X" %
                                    N1_DENOMINATOR)
            numerator = sum(registers[address] << (8 * index)
                            for index, address in enumerate(NUM_ADDRS))
            correction = (Fraction(NOMINAL_NUMERATOR, numerator) - 1) * 1000000
            if abs(correction) > MAX_ABSOLUTE_PPM:
                raise ActuatorError("live U24 N1 is outside +/-200 ppm")
            return {"identity": identity, "registers": registers,
                    "numerator": numerator, "denominator": denominator,
                    "correction_ppm": float(correction),
                    "original_page": page}
        finally:
            _restore_page(client, page)


def apply_u24_n1_numerator(client, target_numerator):
    """Stage/latch only U24 N1 NUM; verify static state and DEN are unchanged."""
    before = read_u24_state(client)
    expected_num = before["numerator"]
    plan = build_n1_register_plan(target_numerator, before["registers"])
    with client:
        page = _read(client, 1, page_select=False)
        try:
            # Close the read/apply race by rechecking path, denominator, and NUM.
            current = {address: _read(client, address)
                       for address in sorted(set(EXPECTED_STATIC) | set(NUM_ADDRS) |
                                             set(range(0x0313, 0x0317)))}
            for address, expected in EXPECTED_STATIC.items():
                if current[address] != expected:
                    raise ActuatorError("U24 state changed before write at 0x%04X" % address)
            if sum(current[a] << (8 * i) for i, a in enumerate(NUM_ADDRS)) != expected_num:
                raise ActuatorError("U24 N1 numerator changed before write")
            if sum(current[a] << (8 * i) for i, a in enumerate(range(0x0313, 0x0317))) != N1_DENOMINATOR:
                raise ActuatorError("U24 N1 denominator changed before write")
            for address, value in plan["staged_writes"]:
                _write(client, address, value)
            for address, value in plan["staged_writes"]:
                if _read(client, address) != value:
                    raise ActuatorError("staged U24 N1 readback mismatch at 0x%04X" % address)
            update = _read(client, 0x0317)
            _write(client, 0x0317, update | 1)
            deadline = __import__("time").monotonic() + 2.0
            while __import__("time").monotonic() < deadline:
                if not (_read(client, 0x0317) & 1):
                    break
                __import__("time").sleep(0.01)
            else:
                raise ActuatorError("U24 N1 update bit did not self-clear")
            final_num = sum(_read(client, address) << (8 * index)
                            for index, address in enumerate(NUM_ADDRS))
            final_den = sum(_read(client, address) << (8 * index)
                            for index, address in enumerate(range(0x0313, 0x0317)))
            if final_num != int(target_numerator):
                raise ActuatorError("latched U24 N1 numerator readback mismatch")
            if final_den != N1_DENOMINATOR:
                raise ActuatorError("U24 N1 denominator changed during update")
            for address, expected in EXPECTED_STATIC.items():
                if _read(client, address) != expected:
                    raise ActuatorError("protected U24 state changed at 0x%04X" % address)
        finally:
            _restore_page(client, page)
    return {"acknowledged": True, "numerator": int(target_numerator),
            "previous_numerator": expected_num, "page_restored": page,
            "transport": "xdma0_user_mmio U24@0x75 mux 0x02"}

