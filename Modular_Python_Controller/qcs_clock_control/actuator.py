"""Fail-closed Si5341 N1 actuator. Live I/O is never selected implicitly."""

import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
from fractions import Fraction

from .si5341_math import Si5341N1Model


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]
DEFAULT_TCL = PACKAGE / "vivado_si5341_bridge.tcl"
DEFAULT_VIVADO = "/home/alzhu/vivado_dl/2025.2/Vivado/bin/vivado"
LEASE = Path.home() / ".cache/qcs/qsfp/control.lock"
NUM_ADDRS = tuple(range(0x030D, 0x0313))
DEN_ADDRS = tuple(range(0x0313, 0x0317))
REQUIRED_STATE_ADDRS = (0x0130, 0x0131, 0x0132, 0x0133) + NUM_ADDRS + DEN_ADDRS + (
    0x0A03, 0x0A04, 0x0A05, 0x0B4A)
EXPECTED_FIXED = {0x0130: 0x06, 0x0131: 0x09, 0x0132: 0x33, 0x0133: 0x09,
                  0x0313: 0x80, 0x0314: 0xDA, 0x0315: 0x51, 0x0316: 0xFD,
                  0x0A03: 0x03, 0x0A04: 0x01, 0x0A05: 0x03, 0x0B4A: 0x1C}
STATIC_STATE_ADDRS = tuple(a for a in REQUIRED_STATE_ADDRS if a not in NUM_ADDRS)


class ActuatorError(RuntimeError):
    pass


class PartialClockWrite(ActuatorError):
    """A staged numerator write failed before/while the N1 update latch."""


def build_n1_register_plan(target_num, expected_registers):
    """Canonical six-byte staging plan shared by live and mock transports."""
    writes = []
    for i, address in enumerate(NUM_ADDRS):
        value = (int(target_num) >> (8 * i)) & 0xFF
        if i == 5:
            value = (value & 0x0F) | (int(expected_registers[address]) & 0xF0)
        writes.append((address, value))
    return {"staged_writes": writes, "latch_register": 0x0317,
            "latch_mask": 0x01, "target_num": int(target_num)}


def parse_commissioning_manifest(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("status") != "commissioned" or not data.get("approval_id"):
        raise ActuatorError("live mode requires a completed commissioning manifest")
    gates = data.get("physical_preconditions", {})
    required_gates = ("vadj_1v8_verified", "out8_transient_approved",
                      "n1_activation_vendor_validated", "diagnostic_clock_verified")
    missing = [key for key in required_gates if gates.get(key) is not True]
    if missing:
        raise ActuatorError("commissioning gates incomplete: " + ", ".join(missing))
    if data.get("device") != "Si5341 Rev D" or data.get("output_path") != "N1->OUT8->bank71":
        raise ActuatorError("manifest must identify commissioned Si5341 Rev D N1->OUT8 path")
    if data.get("target_serial") != "210249AE83E1":
        raise ActuatorError("manifest target serial must match the verified HTG-930")
    if int(data.get("denominator", -1)) != 4250000000 or int(data.get("r_divider", -1)) != 2:
        raise ActuatorError("manifest denominator/R divider differs from audited candidate")
    expected = {int(k, 0): int(v, 0) for k, v in data.get("expected_registers", {}).items()}
    if set(expected) != set(REQUIRED_STATE_ADDRS):
        raise ActuatorError("manifest must provide exact expected readbacks for all protected runtime fields")
    if any(expected.get(addr) != value for addr, value in EXPECTED_FIXED.items()):
        raise ActuatorError("manifest does not match the isolated commissioned N1/OUT8 profile")
    numerator = sum(expected[a] << (8 * i) for i, a in enumerate(NUM_ADDRS))
    if (numerator < 1 or numerator >= (1 << 44) or expected[0x0312] & 0xF0 or
            not (Fraction(10) <= Fraction(numerator, 4250000000) <= Fraction(4095))):
        raise ActuatorError("invalid commissioned N1 numerator readback")
    if numerator != int(data.get("numerator", -1)):
        raise ActuatorError("manifest numerator does not match its register readback")
    return data, expected, numerator


class MockI2CDevice(object):
    """Register-level test device; mirrors ACK/readback and N1 update semantics."""
    def __init__(self, registers, fail_after=None):
        self.registers = {int(k): int(v) for k, v in registers.items()}
        self.fail_after = fail_after
        self.writes = []
        self.operations = 0
        self.latched_num = sum(self.registers.get(a, 0) << (8 * i)
                               for i, a in enumerate(NUM_ADDRS))

    def read_register(self, address):
        self._tick()
        return self.registers.get(int(address), 0)

    def verify_state(self, expected):
        values = {address: self.read_register(address) for address in expected}
        for address in NUM_ADDRS:
            values[address] = self.read_register(address)
        return {"registers": values, "acknowledged": True}

    def write_register(self, address, value):
        self._tick()
        address, value = int(address), int(value)
        self.writes.append((address, value))
        self.registers[address] = value
        if address == 0x0317 and value & 1:
            self.latched_num = sum(self.registers.get(a, 0) << (8 * i)
                                   for i, a in enumerate(NUM_ADDRS))
            self.registers[address] = value & ~1

    def _tick(self):
        self.operations += 1
        if self.fail_after is not None and self.operations >= self.fail_after:
            raise IOError("injected mock I2C transaction failure")

    def apply_n1(self, target_num, expected, plan=None):
        plan = plan or build_n1_register_plan(target_num, expected)
        for address, value in expected.items():
            if self.read_register(address) != value:
                raise ActuatorError("mock precondition mismatch at 0x%04X" % address)
        try:
            for address, byte in plan["staged_writes"]:
                self.write_register(address, byte)
            for i, address in enumerate(NUM_ADDRS):
                wanted = (target_num >> (8 * i)) & 0xFF
                if i == 5:
                    wanted = (wanted & 0x0F) | (expected[address] & 0xF0)
                if self.read_register(address) != wanted:
                    raise ActuatorError("mock staged readback mismatch")
            self.write_register(0x0317, self.read_register(0x0317) | 1)
            if self.read_register(0x0317) & 1:
                raise ActuatorError("mock N1 update bit did not clear")
            return {"applied_num": target_num, "register_writes": list(self.writes),
                    "acknowledged": True}
        except Exception as exc:
            raise PartialClockWrite(str(exc))


class VivadoSi5341Transport(object):
    """Use the already-loaded controller VIO; never programs FPGA or loads a bitstream."""
    def __init__(self, vivado=DEFAULT_VIVADO, tcl_path=DEFAULT_TCL, timeout_s=45):
        self.vivado = str(vivado)
        self.tcl_path = Path(tcl_path)
        self.timeout_s = float(timeout_s)

    def _preflight_exclusive(self):
        LEASE.parent.mkdir(parents=True, exist_ok=True)
        lease = LEASE.open("a+")
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            lease.close()
            raise ActuatorError("QCS hardware-control lease is already held")
        try:
            ps = subprocess.check_output(["ps", "-eo", "pid,comm,args"], text=True)
            own = os.getpid()
            for line in ps.splitlines()[1:]:
                m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", line)
                if not m or int(m.group(1)) == own:
                    continue
                comm, args = m.group(2), m.group(3)
                if comm.startswith("vivado") or (comm.startswith("python") and
                        any(x in args for x in ("python_controller.py", "qsfp_mode_control",
                                                "guard_sweep", "clock_probe"))):
                    raise ActuatorError("competing hardware-control process: " + line.strip())
            try:
                connections = subprocess.check_output(
                    ["ss", "-tnp", "( sport = :3121 or dport = :3121 )"],
                    text=True, stderr=subprocess.DEVNULL)
            except Exception as exc:
                raise ActuatorError("cannot establish exclusive hw_server access: %s" % exc)
            active = [line for line in connections.splitlines() if "ESTAB" in line]
            if active:
                raise ActuatorError("another active hw_server client exists: " + " | ".join(active))
            return lease
        except Exception:
            lease.close()
            raise

    def _run(self, operation, expected, target_num=None, plan=None):
        if not Path(self.vivado).is_file() or not self.tcl_path.is_file():
            raise ActuatorError("Vivado executable or restricted Tcl bridge is missing")
        lease = self._preflight_exclusive()
        args = [self.vivado, "-mode", "batch", "-nolog", "-nojournal", "-source",
                str(self.tcl_path), "-tclargs", operation, str(len(expected))]
        for address, value in sorted(expected.items()):
            args.extend((str(int(address)), str(int(value))))
        if target_num is not None:
            args.append(str(int(target_num)))
            args.extend(str(value) for _address, value in plan["staged_writes"])
        env = dict(os.environ)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        try:
            result = subprocess.run(args, cwd=str(REPO), env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=self.timeout_s)
        except Exception as exc:
            raise ActuatorError("Vivado I2C transaction did not complete: %s" % exc)
        finally:
            lease.close()
        if result.returncode != 0 or "QCS_RESULT" not in result.stdout:
            raise ActuatorError("Vivado/I2C operation failed (exit=%s): %s" %
                                (result.returncode, result.stdout[-3000:]))
        regs = {}
        for match in re.finditer(r"QCS_I2C read page=([0-9A-F]{2}) reg=([0-9A-F]{2}) value=([0-9A-F]{2})", result.stdout):
            regs[(int(match.group(1), 16) << 8) | int(match.group(2), 16)] = int(match.group(3), 16)
        applied_utc_us = None
        m = re.search(r"QCS_APPLIED_UTC_US=(\d+)", result.stdout)
        if m:
            applied_utc_us = int(m.group(1))
        return {"registers": regs, "output": result.stdout,
                "applied_utc_us": applied_utc_us, "acknowledged": True}

    def verify_state(self, expected):
        return self._run("read", expected)

    def apply_n1(self, target_num, expected, plan=None):
        plan = plan or build_n1_register_plan(target_num, expected)
        return self._run("update", expected, target_num, plan)


class AppliedCorrectionHistory(object):
    """Integrate only acknowledged frequency changes on the host monotonic axis."""
    def __init__(self, start_ns, initial_ppb=0):
        self.events = [(int(start_ns), Fraction(str(initial_ppb)))]

    def record(self, when_ns, actual_ppb):
        when_ns = int(when_ns)
        if when_ns < self.events[-1][0]:
            raise ValueError("applied-command event time moved backwards")
        self.events.append((when_ns, Fraction(actual_ppb)))

    def phase_at(self, when_ns):
        when_ns = int(when_ns)
        phase = Fraction(0)
        for index, (start, ppb) in enumerate(self.events):
            stop = when_ns
            if index + 1 < len(self.events):
                stop = min(stop, self.events[index + 1][0])
            if stop > start:
                phase += Fraction((stop - start), 1000000) * ppb
            if when_ns <= start:
                break
        return phase


class Si5341N1Actuator(object):
    """N1 numerator-only actuator; requires explicit commissioning authorization."""
    def __init__(self, manifest_path, transport, model=None):
        self.manifest, expected, self.current_num = parse_commissioning_manifest(manifest_path)
        self.expected = {a: expected[a] for a in STATIC_STATE_ADDRS}
        self.transport = transport
        nominal_num = int(self.manifest.get("nominal_numerator", 1452136671315))
        self.model = model or Si5341N1Model("13667168671.2", nominal_num,
                                            4250000000, 2)
        self.initial_correction_ppb = self.model.correction_for_numerator_ppb(self.current_num)
        self.faulted = False

    def verify(self):
        result = self.transport.verify_state(self.expected)
        if result.get("acknowledged") is not True:
            raise ActuatorError("state readback was not acknowledged")
        registers = result.get("registers", {})
        if any(registers.get(a) != value for a, value in self.expected.items()):
            raise ActuatorError("commissioned static-state readback mismatch")
        if not all(a in registers for a in NUM_ADDRS):
            raise ActuatorError("N1 numerator readback incomplete")
        current_num = sum(int(registers[a]) << (8*i) for i, a in enumerate(NUM_ADDRS))
        if not (1 <= current_num < (1 << 44)):
            raise ActuatorError("live N1 numerator is zero or outside 44-bit range")
        if not (Fraction(10) <= Fraction(current_num, 4250000000) <= Fraction(4095)):
            raise ActuatorError("live N1 divider ratio outside documented 10..4095 range")
        correction = self.model.correction_for_numerator_ppb(current_num)
        limit = Fraction(str(self.manifest.get("max_total_correction_ppb", 100000.0)))
        if abs(correction) > limit:
            raise ActuatorError("live N1 is outside commissioned total-correction envelope")
        self.current_num = current_num
        self.initial_correction_ppb = correction
        return result

    def apply(self, requested_ppb):
        if self.faulted:
            raise ActuatorError("actuator latched faulted after a failed/partial transaction")
        limit = float(self.manifest.get("max_total_correction_ppb", 100000.0))
        if abs(float(requested_ppb)) > limit:
            raise ActuatorError("requested correction exceeds commissioned total-correction envelope")
        description = self.model.describe(requested_ppb)
        target = int(description["numerator"])
        if target == self.current_num:
            return {"status": "acknowledged_no_change", "requested_ppb": str(requested_ppb),
                    "actual_ppb": self.model.quantize_ppb(requested_ppb),
                    "numerator": target, "registers": [], "applied": True}
        expected = dict(self.expected)
        for i, address in enumerate(NUM_ADDRS):
            expected[address] = (self.current_num >> (8 * i)) & 0xFF
        plan = build_n1_register_plan(target, expected)
        try:
            result = self.transport.apply_n1(target, expected, plan)
        except Exception:
            self.faulted = True
            raise
        if result.get("acknowledged") is not True:
            self.faulted = True
            raise ActuatorError("transport did not acknowledge full N1 latch/readback")
        self.current_num = target
        actual = self.model.correction_for_numerator_ppb(target)
        return {"status": "applied_and_readback_verified", "requested_ppb": str(requested_ppb),
                "actual_ppb": str(actual), "numerator": target,
                "registers": description["registers"], "applied": True,
                "transaction": result}


def utc_event_to_monotonic_ns(event_utc_us, wall_start_ns, mono_start_ns):
    """Map a same-host Tcl UTC event to Python monotonic time for phase history."""
    if event_utc_us is None:
        return time.monotonic_ns()
    return int(mono_start_ns + (int(event_utc_us) * 1000 - int(wall_start_ns)))
