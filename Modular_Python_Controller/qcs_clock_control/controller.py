"""Pure clock estimator/controller math; no instrument or hardware access."""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ControllerConfig:
    pair_id: str = "nodeA-nodeB"
    max_measurement_age_s: float = 5.0
    max_future_skew_s: float = 0.001
    max_uncertainty_ps: float = 1000.0
    drift_window: int = 8
    phase_slew_tau_s: float = 20.0
    max_correction_ppb: float = 100000.0
    max_command_slew_ppb_per_update: float = 50000.0
    holdover_decay_per_update: float = 0.0
    reacquire_after_s: float = 10.0


class ClockController:
    """For e=node-reference, command node frequency to reduce e.

    Relative drift is the least-squares slope of e over recent accepted samples.
    Command is the absolute frequency correction which cancels estimated
    free-running drift and slews phase: u=-(y_free + e/tau). The measured slope
    includes past actuator corrections, so callers pass the modeled/observed
    accumulated phase contributed by actuation at the measurement time. The
    estimator fits free drift to (measured phase - applied phase). Strict shadow
    mode passes zero because hypothetical commands were not physically applied.
    A stale/missing measurement holds the previous command (optionally decayed).
    After a long gap, the slope history is discarded and reacquisition starts
    from phase only rather than extrapolating an old frequency estimate.
    """
    def __init__(self, config=None):
        self.config = config or ControllerConfig()
        self.samples = deque(maxlen=max(2, int(self.config.drift_window)))
        # Commands are proposals until an actuator acknowledges them. Keeping
        # these separate prevents a failed I2C transaction from influencing
        # the next slew limit or being logged as applied.
        self.last_command_ppb = 0.0
        self.last_applied_ppb = 0.0
        self.last_accepted_arrival_ns = None
        self.last_pair_id = None
        self.mode = "acquiring"

    @staticmethod
    def _fit_slope_ppb(samples, phase_index=1):
        if len(samples) < 2:
            return None
        origin_ns = samples[0][0]
        xs = [(s[0] - origin_ns) * 1e-9 for s in samples]
        y_origin = samples[0][phase_index]
        ys = [float(s[phase_index] - y_origin) for s in samples]
        xm = sum(xs) / len(xs)
        ym = sum(ys) / len(ys)
        denom = sum((x - xm) ** 2 for x in xs)
        if denom <= 0:
            return None
        slope_ps_per_s = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denom
        # 1 ps/s is a 1e-12 fractional frequency = 0.001 ppb.
        return slope_ps_per_s * 0.001

    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))

    def update(self, record, now_ns=None, applied_phase_ps=0.0):
        now_ns = record.arrival_time_ns if now_ns is None else int(now_ns)
        cfg = self.config
        if record.pair_id != cfg.pair_id:
            return self._result("rejected_pair", record, now_ns, None, None)
        if not record.valid:
            return self._result("rejected_invalid", record, now_ns, None, None)
        if record.quality.strip().lower() in ("bad", "failed", "invalid", "poor", "unusable"):
            return self._result("rejected_quality", record, now_ns, None, None)
        if record.uncertainty_ps is not None and float(record.uncertainty_ps) > cfg.max_uncertainty_ps:
            return self._result("rejected_quality", record, now_ns, None, None)
        age_ns = now_ns - record.measurement_time_ns
        if age_ns < -int(cfg.max_future_skew_s * 1e9):
            return self._result("rejected_future", record, now_ns, None, None)
        if age_ns > int(cfg.max_measurement_age_s * 1e9):
            return self._result("rejected_stale", record, now_ns, None, None)
        if record.arrival_time_ns > now_ns:
            return self._result("rejected_not_arrived", record, now_ns, None, None)
        if self.samples and record.measurement_time_ns <= self.samples[-1][0]:
            return self._result("rejected_out_of_order", record, now_ns, None, None)

        if (self.last_accepted_arrival_ns is not None and
                (record.measurement_time_ns - self.samples[-1][0]) * 1e-9 > cfg.reacquire_after_s):
            self.samples.clear()
            self.mode = "reacquiring"

        # Extrapolate measurement from its effective time to command time using
        # current measured slope. For the first sample the phase is held.
        net_drift_ppb = self._fit_slope_ppb(self.samples, 1)
        predicted_ps = record.offset_ps
        if net_drift_ppb is not None:
            predicted_ps += (Decimal(str(net_drift_ppb)) * Decimal(1000) *
                             Decimal(max(0, age_ns)) / Decimal(1000000000))

        self.samples.append((record.measurement_time_ns, record.offset_ps,
                             Decimal(str(applied_phase_ps))))
        net_drift_ppb = self._fit_slope_ppb(self.samples, 1)
        free_samples = [(s[0], s[1] - s[2]) for s in self.samples]
        drift_ppb = self._fit_slope_ppb(free_samples, 1)
        # Phase term is ps/s; convert to ppb using 1 ps/s = 0.001 ppb.
        phase_term_ppb = float(predicted_ps * Decimal("0.001") /
                                Decimal(str(max(cfg.phase_slew_tau_s, 1e-9))))
        free_fraction = 0.0 if drift_ppb is None else drift_ppb * 1e-9
        desired = ((1.0 - phase_term_ppb * 1e-9) / (1.0 + free_fraction) - 1.0) * 1e9
        desired = self._clamp(desired, -cfg.max_correction_ppb, cfg.max_correction_ppb)
        step = cfg.max_command_slew_ppb_per_update
        command = self._clamp(desired, self.last_applied_ppb - step, self.last_applied_ppb + step)
        self.last_command_ppb = command
        self.last_accepted_arrival_ns = now_ns
        self.last_pair_id = record.pair_id
        self.mode = "tracking" if len(self.samples) >= 2 else "acquiring"
        status = "accepted" if age_ns <= int(cfg.max_measurement_age_s * 1e9) else "rejected_stale"
        return self._result(status, record, now_ns, float(predicted_ps), drift_ppb,
                            command=command, age_ns=age_ns)

    def confirm_applied(self, command_ppb):
        """Commit an acknowledged actuator value as the new slew reference."""
        self.last_applied_ppb = float(command_ppb)

    def holdover(self, now_ns):
        decay = min(1.0, max(0.0, self.config.holdover_decay_per_update))
        self.last_command_ppb = self.last_applied_ppb * (1.0 - decay)
        if decay:
            # A live caller must explicitly apply this holdover proposal before
            # confirming it; pure shadow users only observe it.
            pass
        self.mode = "holdover"
        return {"status": "holdover", "now_ns": int(now_ns), "command_ppb": self.last_command_ppb,
                "requested_correction_ppb": self.last_command_ppb,
                "last_applied_ppb": self.last_applied_ppb,
                "estimated_offset_ps": None, "estimated_drift_ppb": None,
                "measurement_age_ms": None, "samples": len(self.samples)}

    def _result(self, status, record, now_ns, predicted_ps, drift_ppb, command=None, age_ns=None):
        if status.startswith("rejected"):
            return {"status": status, "measurement_time_ns": record.measurement_time_ns,
                    "arrival_time_ns": record.arrival_time_ns, "now_ns": int(now_ns),
                    "pair_id": record.pair_id, "command_ppb": self.last_applied_ppb,
                    "last_applied_ppb": self.last_applied_ppb,
                    "mode": self.mode, "samples": len(self.samples)}
        return {"status": status, "measurement_time_ns": record.measurement_time_ns,
                "arrival_time_ns": record.arrival_time_ns, "now_ns": int(now_ns),
                "pair_id": record.pair_id, "measurement_age_ms": age_ns / 1e6,
                "estimated_offset_ps": predicted_ps,
                "estimated_drift_ppb": drift_ppb,
                "requested_correction_ppb": command,
                "command_ppb": command, "last_applied_ppb": self.last_applied_ppb,
                "mode": self.mode,
                "samples": len(self.samples)}
