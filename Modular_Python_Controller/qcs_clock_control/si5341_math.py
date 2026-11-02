"""Descriptive Si5341 N1 numerator arithmetic; deliberately no writer backend."""

from fractions import Fraction
from decimal import Decimal


def _round_fraction_nearest(value):
    value = Fraction(value)
    q, r = divmod(value.numerator, value.denominator)
    return q + (1 if 2 * r >= value.denominator else 0)


class Si5341N1Model:
    """Candidate plan from commissioning/register_plan.json, not live state.

    Si5341 N output is Fvco * DEN / (NUM * R). Reducing NUM raises output.
    `describe()` returns an inert record; this class has no transport methods.
    """
    def __init__(self, vco_hz, numerator, denominator, r_divider=2):
        self.vco_hz = Fraction(vco_hz)
        self.numerator = int(numerator)
        self.denominator = int(denominator)
        self.r_divider = int(r_divider)
        if not (10 <= self.numerator / self.denominator <= 4095):
            raise ValueError("N divider ratio outside documented 10..4095 range")
        if not (0 < self.numerator < (1 << 44)):
            raise ValueError("N numerator does not fit 44 bits")
        if not (0 < self.denominator < (1 << 32)):
            raise ValueError("N denominator does not fit 32 bits")
        if self.r_divider <= 0:
            raise ValueError("R divider must be positive")

    @property
    def nominal_hz(self):
        return self.vco_hz * self.denominator / (self.numerator * self.r_divider)

    def quantize_ppb(self, requested_ppb):
        """Return exact representable fractional correction as a Fraction."""
        req = Fraction(Decimal(str(requested_ppb))) / 1000000000
        if req <= -1:
            raise ValueError("requested frequency correction must exceed -1e9 ppb")
        new_num = _round_fraction_nearest(Fraction(self.numerator, 1) / (1 + req))
        if not (1 <= new_num < (1 << 44)):
            raise ValueError("requested correction yields numerator outside 44-bit range")
        if not (Fraction(10, 1) <= Fraction(new_num, self.denominator) <= Fraction(4095, 1)):
            raise ValueError("requested correction yields N divider outside documented 10..4095 range")
        return (Fraction(self.numerator, new_num) - 1) * 1000000000

    def describe(self, requested_ppb):
        """Convert frequency correction (ppb) to candidate NUM bytes only."""
        req = Fraction(Decimal(str(requested_ppb))) / 1000000000
        if req <= -1:
            raise ValueError("requested frequency correction must exceed -1e9 ppb")
        target_ratio = 1 + req
        target_num = Fraction(self.numerator, 1) / target_ratio
        new_num = _round_fraction_nearest(target_num)
        if not (1 <= new_num < (1 << 44)):
            raise ValueError("requested correction yields numerator outside 44-bit range")
        if not (Fraction(10, 1) <= Fraction(new_num, self.denominator) <= Fraction(4095, 1)):
            raise ValueError("requested correction yields N divider outside documented 10..4095 range")
        actual_hz = self.vco_hz * self.denominator / (new_num * self.r_divider)
        actual_ratio = actual_hz / self.nominal_hz
        actual_ppb = (actual_ratio - 1) * 1000000000
        quant_error_ppb = actual_ppb - req * 1000000000
        data = [(new_num >> (8 * i)) & 0xff for i in range(6)]
        if data[5] & 0xf0:
            raise AssertionError("high reserved numerator bits unexpectedly set")
        return {
            "kind": "descriptive_only_no_hardware_io",
            "requested_correction_ppb": str(Decimal(str(requested_ppb))),
            "nominal_output_hz": float(self.nominal_hz),
            "requested_output_hz": float(self.nominal_hz * target_ratio),
            "representable_output_hz": float(actual_hz),
            "representable_correction_ppb": float(actual_ppb),
            "quantization_error_ppb": float(quant_error_ppb),
            "numerator": new_num,
            "denominator_unchanged": self.denominator,
            "registers": [
                {"address": "0x%04X" % (0x030d + i), "mask": "0x0F" if i == 5 else "0xFF",
                 "value": "0x%02X" % data[i]}
                for i in range(6)
            ],
            "activation_or_reset_operations": [],
        }
