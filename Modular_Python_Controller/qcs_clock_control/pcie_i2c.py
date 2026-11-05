"""Host MMIO transport for the isolated XDMA PCIe-to-I2C bridge.

The default package still uses dry-run/Vivado transports. This class is used
only when a commissioned PCIe-control bitstream is explicitly selected.
"""
import fcntl
import os
import time
from pathlib import Path

from .actuator import ActuatorError, NUM_ADDRS, build_n1_register_plan


REG_ID = 0x00
REG_STATUS = 0x04
REG_LOCK = 0x08
REG_COMMAND_LOW = 0x0C
REG_COMMAND_HIGH = 0x10
REG_START = 0x14
START_MAGIC = 0x0000C10C
EXPECTED_ID = 0x51434C4B
I2C_ADDRESS = 0x77
MUX_MASK = 0x40


class FileMmio(object):
    """32-bit little-endian MMIO over the Linux XDMA user BAR character node."""
    def __init__(self, path="/dev/xdma0_user"):
        self.path = str(path)
        self.fd = os.open(self.path, os.O_RDWR | getattr(os, "O_SYNC", 0))

    def read32(self, offset):
        raw = os.pread(self.fd, 4, int(offset))
        if len(raw) != 4:
            raise IOError("short MMIO read at 0x%X" % offset)
        return int.from_bytes(raw, "little")

    def write32(self, offset, value):
        raw = int(value).to_bytes(4, "little")
        if os.pwrite(self.fd, raw, int(offset)) != 4:
            raise IOError("short MMIO write at 0x%X" % offset)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def make_i2c_command(address, register, *, page=0, read=False, value=0, page_select=True):
    """Build the burst_i2c payload (request toggle is created in FPGA logic)."""
    address, register, page, value = map(int, (address, register, page, value))
    if not (0 <= address < 128 and 0 <= register <= 255 and 0 <= page < 32):
        raise ValueError("invalid I2C address/register/page")
    if not 0 <= value <= 255:
        raise ValueError("I2C data byte must be 0..255")
    command = (MUX_MASK << 16) | (address << 8) | register
    if page_select:
        command |= (1 << 30) | (page << 25)
    if read:
        command |= 1 << 24
    else:
        command |= (1 << 15) | (value << 32)
    return command


class PcieI2cClient(object):
    """Serialized lock/transaction API; can also be given a mock MMIO object."""
    def __init__(self, mmio, timeout_s=5.0, poll_s=0.0001, lock_path=None):
        self.mmio = mmio
        self.timeout_s = float(timeout_s)
        self.poll_s = float(poll_s)
        self.lock_path = Path(lock_path or (Path.home() / ".cache/qcs/si5341-pcie.lock"))
        self._lease = None
        if self.mmio.read32(REG_ID) != EXPECTED_ID:
            raise ActuatorError("PCIe clock bridge signature mismatch; wrong image or BAR")

    def acquire(self):
        if self._lease:
            raise ActuatorError("PCIe I2C lease already held by this client")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lease = self.lock_path.open("a+")
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            lease.close()
            raise ActuatorError("another local Si5341 PCIe controller holds the lock")
        try:
            status = self.mmio.read32(REG_STATUS)
            if status & 1:
                raise ActuatorError("FPGA I2C bridge reports busy before lock request")
            self.mmio.write32(REG_LOCK, 1)
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                status = self.mmio.read32(REG_STATUS)
                if status & 0x8:
                    raise ActuatorError(
                        "FPGA denied I2C ownership: QSFP3 is not selected (module_select_n != 0b10)"
                    )
                if status & 2:
                    self._lease = lease
                    return status
                time.sleep(self.poll_s)
            raise ActuatorError("timed out acquiring FPGA I2C ownership")
        except Exception:
            # The FPGA may have accepted LOCK just before a timeout or bus
            # error. Always request release before dropping the host lease.
            try:
                self.mmio.write32(REG_LOCK, 0)
            except Exception:
                pass
            lease.close()
            raise

    def release(self):
        if self._lease is None:
            return
        try:
            if self.mmio.read32(REG_STATUS) & 1:
                raise ActuatorError("cannot release PCIe I2C ownership during a transaction")
            self.mmio.write32(REG_LOCK, 0)
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                if not (self.mmio.read32(REG_STATUS) & 2):
                    return
                time.sleep(self.poll_s)
            raise ActuatorError("FPGA did not release I2C ownership")
        finally:
            fcntl.flock(self._lease.fileno(), fcntl.LOCK_UN)
            self._lease.close()
            self._lease = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()

    def transact(self, command):
        if self._lease is None:
            raise ActuatorError("acquire PCIe I2C ownership before a transaction")
        command = int(command)
        low = command & 0x7FFFFFFF
        high = (command >> 32) & 0xFF
        before = (self.mmio.read32(REG_STATUS) >> 16) & 0xFFFF
        if self.mmio.read32(REG_STATUS) & 1:
            raise ActuatorError("FPGA I2C bridge is already busy")
        self.mmio.write32(REG_COMMAND_LOW, low)
        self.mmio.write32(REG_COMMAND_HIGH, high)
        self.mmio.write32(REG_START, START_MAGIC)
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            status = self.mmio.read32(REG_STATUS)
            count = (status >> 16) & 0xFFFF
            if count != before and not (status & 1):
                if count != ((before + 1) & 0xFFFF):
                    raise ActuatorError("unexpected FPGA I2C completion sequence")
                if not (status & 4):
                    raise ActuatorError("Si5341 I2C transaction NACK/error=0x%X" % ((status >> 4) & 0xF))
                return (status >> 8) & 0xFF
            time.sleep(self.poll_s)
        raise ActuatorError("timed out waiting for FPGA I2C completion")


class PcieSi5341Transport(object):
    """Si5341 N1 operations through the PCIe MMIO bridge; no generic writes."""
    def __init__(self, client):
        self.client = client

    @staticmethod
    def _page(address):
        return int(address) >> 8

    def _read(self, address):
        return self.client.transact(make_i2c_command(I2C_ADDRESS, int(address) & 0xFF,
                                                     page=self._page(address), read=True))

    def _write(self, address, value):
        self.client.transact(make_i2c_command(I2C_ADDRESS, int(address) & 0xFF,
                                              page=self._page(address), value=value))

    def _save_page(self):
        return self.client.transact(make_i2c_command(I2C_ADDRESS, 1, read=True,
                                                      page_select=False))

    def _restore_page(self, page):
        # Selecting a page is part of each FPGA I2C command. A harmless read
        # on the original page leaves the chip's page selector restored.
        self.client.transact(make_i2c_command(I2C_ADDRESS, 0x00, page=page, read=True))

    def verify_state(self, expected):
        with self.client:
            original_page = self._save_page()
            regs = {}
            failure = None
            try:
                ident = {0x00FE: self._read(0x00FE), 0x0002: self._read(0x0002),
                         0x0003: self._read(0x0003), 0x0004: self._read(0x0004),
                         0x0005: self._read(0x0005)}
                if ident != {0x00FE: 0x0F, 0x0002: 0x41, 0x0003: 0x53,
                             0x0004: 0x00, 0x0005: 0x03}:
                    raise ActuatorError("U7 Si5341 identity/readiness check failed: %r" % ident)
                regs.update({int(a): self._read(a) for a in expected})
                regs.update({a: self._read(a) for a in NUM_ADDRS})
            except Exception as exc:
                failure = exc
            finally:
                try:
                    self._restore_page(original_page)
                except Exception as exc:
                    raise ActuatorError("failed to restore Si5341 page: %s" % exc)
            if failure:
                raise failure
            return {"registers": regs, "acknowledged": True,
                    "device_id": ident, "page_restored": original_page}

    def apply_n1(self, target_num, expected, plan=None):
        plan = plan or build_n1_register_plan(target_num, expected)
        with self.client:
            original_page = self._save_page()
            try:
                for address, wanted in expected.items():
                    if self._read(address) != wanted:
                        raise ActuatorError("N1 precondition mismatch at 0x%04X" % address)
                for address in NUM_ADDRS:
                    if self._read(address) != expected[address]:
                        raise ActuatorError("current N1 numerator changed at 0x%04X" % address)
                for address, value in plan["staged_writes"]:
                    self._write(address, value)
                for address, value in plan["staged_writes"]:
                    if self._read(address) != value:
                        raise ActuatorError("staged N1 readback mismatch at 0x%04X" % address)
                update = self._read(0x0317)
                self._write(0x0317, update | 1)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if not (self._read(0x0317) & 1):
                        break
                    time.sleep(0.01)
                else:
                    raise ActuatorError("Si5341 N1 update bit did not self-clear")
                for address, value in plan["staged_writes"]:
                    if self._read(address) != value:
                        raise ActuatorError("latched N1 readback mismatch at 0x%04X" % address)
            finally:
                self._restore_page(original_page)
        return {"acknowledged": True, "applied_num": int(target_num),
                "page_restored": original_page, "transport": "xdma0_user_mmio"}
