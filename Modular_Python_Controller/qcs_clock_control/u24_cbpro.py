"""Guarded parser/loader for the HTG-930 U24 Si5341 CBPro register file.

The loader is dry-run unless the caller explicitly selects live mode.  It
uses the existing PCIe/I2C bridge at U24 address 0x75 and mux mask 0x02.
This is a full volatile register configuration, not an N1 runtime actuator.
"""
import json
import hashlib
import re
import time
from pathlib import Path

from .pcie_i2c import (EXPECTED_ID, REG_ID, PcieI2cClient, FileMmio,
                       make_i2c_command)


U24_ADDRESS = 0x75
U24_MUX_MASK = 0x02
REVIEWED_PROFILE_SHA256 = "7a38d10731157c8adc234a19635e321e8c7215216cbb027af941d3cd6ee85003"
EXPECTED_DEVICE_ID = {0x00FE: 0x0F, 0x0002: 0x41, 0x0003: 0x53,
                      0x0004: 0x00, 0x0005: 0x03}
OUT_CONTROL_ADDRS = (0x0108, 0x010D, 0x0112, 0x0117, 0x011C,
                     0x0121, 0x0126, 0x012B, 0x0130, 0x013A)
VERIFY_ADDRS = (0x000B, 0x0021, 0x013A, 0x013B, 0x013C, 0x013D,
                0x0943, 0x0949, 0x094A, 0x0A03, 0x0A04, 0x0A05,
                0x0B4A)


class ProfileError(ValueError):
    pass


def _u24_command(register, read=False, value=0, page_select=True):
    register = int(register)
    command = make_i2c_command(U24_ADDRESS, register & 0xFF,
                               page=register >> 8, read=read, value=value,
                               page_select=page_select)
    # Existing U7 helper defaults to the FMC clock mux (0x40). U24 is on
    # motherboard PCA9548 branch 1 (mask 0x02), as used by read_u24.py.
    return (command & ~(0xFF << 16)) | (U24_MUX_MASK << 16)


def parse_cbpro_register_file(path):
    """Parse CBPro's ordered Address,Data script and its documented delays."""
    path = Path(path)
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8-sig")
    metadata = {}
    events = []
    saw_header = False
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            meta = re.match(r"#\s*(Part|Design ID|Device Revision):\s*(.*?)\s*$", line)
            if meta:
                metadata[meta.group(1).lower().replace(" ", "_")] = meta.group(2)
            delay = re.match(r"#\s*Delay\s+(\d+(?:\.\d+)?)\s*(msec|ms|sec|s)\s*$", line, re.I)
            if delay:
                amount = float(delay.group(1))
                unit = delay.group(2).lower()
                seconds = amount / 1000.0 if unit in ("msec", "ms") else amount
                if seconds <= 0 or seconds > 10:
                    raise ProfileError("unreasonable delay on line %d" % line_number)
                events.append({"kind": "delay", "seconds": seconds,
                               "line": line_number})
            continue
        if line.lower() == "address,data":
            saw_header = True
            continue
        match = re.fullmatch(r"\s*(0x[0-9a-fA-F]+)\s*,\s*(0x[0-9a-fA-F]+)\s*", line)
        if not match:
            raise ProfileError("unrecognized register-script line %d: %s" %
                               (line_number, line))
        address, value = (int(match.group(1), 16), int(match.group(2), 16))
        if address > 0x0BFF or value > 0xFF:
            raise ProfileError("address/data out of range on line %d" % line_number)
        events.append({"kind": "write", "address": address,
                       "value": value, "line": line_number})
    if not saw_header or not events:
        raise ProfileError("not a CBPro Address,Data register script")
    profile = {"path": str(path), "sha256": hashlib.sha256(raw_bytes).hexdigest(),
               "metadata": metadata, "events": events,
               "writes": [e for e in events if e["kind"] == "write"]}
    validate_u24_profile(profile)
    return profile


def validate_u24_profile(profile):
    """Refuse profiles other than the reviewed crystal-input HTGU24 design."""
    metadata = profile["metadata"]
    if metadata.get("part", "").lower() != "si5341":
        raise ProfileError("profile Part must be Si5341")
    if metadata.get("device_revision", "").upper() != "D":
        raise ProfileError("profile must target Si5341 Revision D")
    if metadata.get("design_id") != "HTGU24":
        raise ProfileError("profile Design ID must be HTGU24")
    values = {}
    for event in profile["writes"]:
        values[event["address"]] = event["value"]
    required = {0x000B: 0x74, 0x0021: 0x0F, 0x0102: 0x01,
                0x013A: 0x02, 0x013B: 0x09, 0x013C: 0x33,
                0x013D: 0x09, 0x0943: 0x00, 0x0949: 0x00,
                0x094A: 0x00, 0x0A03: 0x02, 0x0A04: 0x00,
                0x0A05: 0x02}
    for address, expected in required.items():
        if values.get(address) != expected:
            raise ProfileError("reviewed U24 crystal profile mismatch at 0x%04X" % address)
    for address in OUT_CONTROL_ADDRS[:-1]:
        if values.get(address) != 0x01:
            raise ProfileError("profile must leave U24 output %d disabled (0x%04X)" %
                               (OUT_CONTROL_ADDRS.index(address), address))
    if 0x0310 not in values or values.get(0x0316, 0) == 0:
        raise ProfileError("profile does not contain the expected nonzero N1 divider")
    if not any(e["kind"] == "delay" and abs(e["seconds"] - 0.3) < 1e-9
               for e in profile["events"]):
        raise ProfileError("profile is missing CBPro's 300 ms calibration delay")
    return values


class U24ProfileTransport(object):
    """Apply a previously validated profile through an existing I2C client."""
    def __init__(self, client, sleeper=time.sleep, monotonic=time.monotonic):
        self.client = client
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.last_result = {}

    def _read(self, register, page_select=True):
        return self.client.transact(_u24_command(register, read=True,
                                                 page_select=page_select))

    def _write(self, register, value):
        return self.client.transact(_u24_command(register, value=value))

    def _identity(self):
        return {address: self._read(address) for address in EXPECTED_DEVICE_ID}

    def apply_profile(self, profile, snapshot_path):
        """Snapshot targeted registers, apply ordered writes, then verify.

        The snapshot is evidence for recovery planning, not an automatic
        rollback image. On a partial failure the device may be reconfigured;
        the method reports the exact completed write count and propagates the
        failure. It never writes NVM.
        """
        validate_u24_profile(profile)
        if profile.get("sha256") != REVIEWED_PROFILE_SHA256:
            raise ProfileError("live loading is restricted to the reviewed HTGU24 file SHA-256 %s" %
                               REVIEWED_PROFILE_SHA256)
        unique_addresses = sorted(set(e["address"] for e in profile["writes"]))
        result = {"target": "U24 Si5341 Rev D", "i2c_address": hex(U24_ADDRESS),
                  "mux_mask": hex(U24_MUX_MASK), "profile": profile["path"],
                  "nvm_written": False, "writes_acknowledged": 0,
                  "writes_requested": len(profile["writes"])}
        self.last_result = result
        with self.client:
            original_page = self._read(0x0001, page_select=False)
            result["original_page"] = original_page
            try:
                if self.client.mmio.read32(REG_ID) != EXPECTED_ID:
                    raise RuntimeError("PCIe I2C bridge signature mismatch")
                identity = self._identity()
                result["device_identity"] = {hex(k): v for k, v in identity.items()}
                if identity != EXPECTED_DEVICE_ID:
                    raise RuntimeError("U24 identity/readiness mismatch: %r" % identity)
                if self._read(0x000B) != 0x74:
                    raise RuntimeError("U24 address-base precondition mismatch")
                before = {address: self._read(address) for address in unique_addresses}
                Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
                Path(snapshot_path).write_text(json.dumps({
                    "target": "U24 Si5341 Rev D", "i2c_address": hex(U24_ADDRESS),
                    "mux_mask": hex(U24_MUX_MASK), "original_page": original_page,
                    "initial_mux": "unknown; controller returns mux to zero",
                    "registers": {"0x%04X" % k: v for k, v in before.items()},
                    "note": "Pre-write readback only; not an automatic restoration script."
                }, indent=2) + "\n")
                result["prewrite_snapshot"] = str(snapshot_path)
                for event in profile["events"]:
                    if event["kind"] == "delay":
                        self.sleeper(event["seconds"])
                    else:
                        self._write(event["address"], event["value"])
                        result["writes_acknowledged"] += 1
                        self.last_result = dict(result)
                deadline = self.monotonic() + 5.0
                while self.monotonic() < deadline:
                    if self._read(0x00FE) == 0x0F:
                        break
                    self.sleeper(0.01)
                else:
                    raise RuntimeError("U24 did not report ready after profile load")
                verify_addresses = sorted(set(VERIFY_ADDRS + OUT_CONTROL_ADDRS))
                final = {address: self._read(address) for address in verify_addresses}
                expected = validate_u24_profile(profile)
                for address in VERIFY_ADDRS:
                    if address in expected and final[address] != expected[address]:
                        raise RuntimeError("U24 readback mismatch at 0x%04X: got 0x%02X, expected 0x%02X" %
                                           (address, final[address], expected[address]))
                # Confirm only OUT9 is enabled by this profile.
                for address in OUT_CONTROL_ADDRS[:-1]:
                    if final.get(address) != 0x01:
                        raise RuntimeError("unexpected U24 output state at 0x%04X" % address)
                if final.get(0x013A) != 0x02:
                    raise RuntimeError("U24 OUT9 is not enabled as expected")
                result["verified_registers"] = {"0x%04X" % k: v for k, v in final.items()}
                result["page_restore_verified"] = False
            finally:
                self._read(original_page << 8, page_select=True)
                restored = self._read(0x0001, page_select=False)
                result["page_restored"] = restored
                result["page_restore_verified"] = restored == original_page
                self.last_result = dict(result)
                if restored != original_page:
                    raise RuntimeError("failed to restore U24 page selector")
        result["status"] = "applied_and_readback_verified"
        result["transport"] = "xdma0_user_mmio"
        return result


def dry_run_summary(profile):
    values = validate_u24_profile(profile)
    return {"mode": "dry-run", "profile": profile["path"],
            "sha256": profile.get("sha256"),
            "design_id": profile["metadata"].get("design_id"),
            "ordered_register_writes": len(profile["writes"]),
            "delay_seconds": [e["seconds"] for e in profile["events"]
                              if e["kind"] == "delay"],
            "target": "U24 address 0x75, motherboard mux mask 0x02",
            "host_io_vdd_sel": values[0x0943] & 1,
            "input_selection_register": values[0x0021],
            "out9_control": values[0x013A],
            "n1_fractional_bypass": values[0x0A04],
            "warning": "Full U24 configuration; enables OUT9, leaves OUT0-OUT8 disabled, and includes CBPro reset/preamble writes."}


def open_live_transport(device_path="/dev/xdma0_user"):
    mmio = FileMmio(device_path)
    try:
        client = PcieI2cClient(mmio)
    except Exception:
        mmio.close()
        raise
    return mmio, U24ProfileTransport(client)
