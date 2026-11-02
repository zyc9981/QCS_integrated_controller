"""Deterministic closed-loop simulations. All clock residuals are model outputs."""

import csv
import json
import random
from bisect import bisect_right
from fractions import Fraction
from pathlib import Path

from .controller import ClockController, ControllerConfig
from .records import MeasurementRecord


PPB = 1000000000


def _fraction(value):
    return Fraction(str(value))


def _fraction_decimal(value):
    from decimal import Decimal, localcontext
    value = Fraction(value)
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal(value.numerator) / Decimal(value.denominator)


class SimulatedClockActuator:
    """Exact-ratio phase model with delayed, quantized frequency commands."""
    def __init__(self, initial_offset_ps=0, free_ppb=0, command_delay_s=0.0,
                 command_quantum_ppb="0.0007", drift_changes=None,
                 command_quantizer=None):
        self.time_ns = 0
        self.phase_ps = Fraction(str(initial_offset_ps))
        self.initial_phase_ps = self.phase_ps
        self.free_ppb = Fraction(str(free_ppb))
        self.command_ppb = Fraction(0)
        self.command_delay_ns = int(round(command_delay_s * 1e9))
        self.command_quantum = _fraction(command_quantum_ppb)
        self.command_quantizer = command_quantizer
        self.pending = []
        self.history = []
        self._history_starts = []
        self.drift_changes = sorted((int(round(t * 1e9)), Fraction(str(v)))
                                    for t, v in (drift_changes or []))
        self._drift_index = 0

    def request(self, command_ppb, now_ns):
        requested = command_ppb if isinstance(command_ppb, Fraction) else _fraction(command_ppb)
        if self.command_quantizer is not None:
            requested = Fraction(self.command_quantizer(float(requested)))
        elif self.command_quantum > 0:
            steps = requested / self.command_quantum
            q = int(steps + Fraction(1, 2)) if steps >= 0 else int(steps - Fraction(1, 2))
            requested = q * self.command_quantum
        self.pending.append((int(now_ns) + self.command_delay_ns, requested))
        self.pending.sort(key=lambda item: item[0])
        return requested

    def _advance_segment(self, end_ns):
        dt_ns = end_ns - self.time_ns
        if dt_ns <= 0:
            self.time_ns = max(self.time_ns, end_ns)
            return
        # Exact multiplicative composition of node free-rate error and actuator
        # fractional correction. One ps/s is 0.001 ppb.
        total_fraction = (1 + self.free_ppb / PPB) * (1 + self.command_ppb / PPB) - 1
        phase_start = self.phase_ps
        self.phase_ps += Fraction(dt_ns * 1000, 1) * total_fraction
        self._history_starts.append(self.time_ns)
        self.history.append((self.time_ns, end_ns, total_fraction,
                             self.command_ppb, phase_start))
        self.time_ns = end_ns

    def advance_to(self, target_ns):
        target_ns = int(target_ns)
        if target_ns < self.time_ns:
            raise ValueError("simulated time cannot run backwards")
        while True:
            candidates = []
            if self.pending and self.pending[0][0] <= target_ns:
                candidates.append(self.pending[0][0])
            if self._drift_index < len(self.drift_changes):
                change_ns = self.drift_changes[self._drift_index][0]
                if change_ns <= target_ns:
                    candidates.append(change_ns)
            if not candidates:
                break
            event_ns = max(self.time_ns, min(candidates))
            self._advance_segment(event_ns)
            while self.pending and self.pending[0][0] <= self.time_ns:
                _, self.command_ppb = self.pending.pop(0)
            while (self._drift_index < len(self.drift_changes) and
                   self.drift_changes[self._drift_index][0] <= self.time_ns):
                _, self.free_ppb = self.drift_changes[self._drift_index]
                self._drift_index += 1
            if event_ns == target_ns:
                break
        self._advance_segment(target_ns)
        return self.phase_ps

    def phase_at(self, timestamp_ns):
        """Return accumulated phase at a past/current model timestamp."""
        timestamp_ns = int(timestamp_ns)
        if timestamp_ns > self.time_ns:
            raise ValueError("advance the plant before querying a future timestamp")
        if not self.history or timestamp_ns <= self.history[0][0]:
            return self.initial_phase_ps
        index = bisect_right(self._history_starts, timestamp_ns) - 1
        start_ns, end_ns, rate, _command, phase_start = self.history[index]
        stop_ns = min(timestamp_ns, end_ns)
        return phase_start + Fraction((stop_ns - start_ns) * 1000, 1) * rate

    def command_at(self, timestamp_ns):
        timestamp_ns = int(timestamp_ns)
        if self.history:
            index = bisect_right(self._history_starts, timestamp_ns) - 1
            if index >= 0:
                start_ns, end_ns, _rate, command, _phase = self.history[index]
                if start_ns <= timestamp_ns < end_ns:
                    return command
        if timestamp_ns == self.time_ns:
            return self.command_ppb
        return Fraction(0)


def _percentile(values, p):
    if not values:
        return None
    vals = sorted(float(abs(v)) for v in values)
    pos = (len(vals) - 1) * p
    lo = int(pos)
    hi = min(len(vals) - 1, lo + 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def run_scenario(name, duration_s=240, update_interval_s=1.0,
                 acquisition_s=0.8, processing_latency_s=0.15,
                 initial_offset_ps=700, free_ppb=4.0, noise_sigma_ps=1.5,
                 command_delay_s=0.25, command_quantum_ppb="0.0007",
                 drift_changes=None, dropout_ranges=None, irregular=False,
                 seed=20261101):
    rng = random.Random(seed)
    cfg = ControllerConfig(pair_id="nodeA-nodeB", phase_slew_tau_s=20.0,
                           max_correction_ppb=20000.0,
                           max_command_slew_ppb_per_update=20000.0,
                           max_measurement_age_s=5.0, drift_window=8,
                           reacquire_after_s=5.0)
    controller = ClockController(cfg)
    from .si5341_math import Si5341N1Model
    si_model = Si5341N1Model("13667168671.2", 1452136671315, 4250000000, 2)
    plant = SimulatedClockActuator(initial_offset_ps, free_ppb, command_delay_s,
                                   command_quantum_ppb, drift_changes,
                                   command_quantizer=si_model.quantize_ppb)
    open_loop = SimulatedClockActuator(initial_offset_ps, free_ppb, command_delay_s,
                                       command_quantum_ppb, drift_changes)
    dt = float(update_interval_s)
    next_s = dt
    rows = []
    while next_s <= duration_s + 1e-9:
        interval = dt
        if irregular:
            interval = dt * rng.uniform(0.75, 1.25)
        end_ns = int(round(next_s * 1e9))
        meas_ns = max(0, end_ns - int(round(acquisition_s * 0.5e9)))
        arrival_ns = end_ns + int(round(processing_latency_s * 1e9))
        if meas_ns > plant.time_ns:
            plant.advance_to(meas_ns)
        truth_ps = plant.phase_at(meas_ns)
        drop = any(start <= next_s <= stop for start, stop in (dropout_ranges or []))
        noise_ps = DecimalNoise(rng.gauss(0.0, noise_sigma_ps))
        observed = truth_ps + Fraction(noise_ps)
        # Independent open-loop truth follows the same free oscillator with no
        # corrections. Do not treat it as a measurement replay.
        if meas_ns > open_loop.time_ns:
            open_loop.advance_to(meas_ns)
        age_ns = arrival_ns - meas_ns
        result = None
        if drop:
            plant.advance_to(arrival_ns)
            result = controller.holdover(arrival_ns)
            result.update({"measurement_time_ns": meas_ns, "arrival_time_ns": arrival_ns,
                           "measurement_age_ms": age_ns / 1e6, "pair_id": cfg.pair_id})
        else:
            record = MeasurementRecord(
                measurement_time_ns=meas_ns,
                arrival_time_ns=arrival_ns,
                offset_ps=str(_fraction_decimal(observed)), pair_id=cfg.pair_id,
                valid=True, quality="synthetic", uncertainty_ps=noise_sigma_ps,
                acquisition_start_ns=end_ns - int(acquisition_s * 1e9),
                acquisition_end_ns=end_ns,
            )
            plant.advance_to(arrival_ns)
            applied_phase = plant.phase_at(meas_ns) - open_loop.phase_at(meas_ns)
            result = controller.update(record, now_ns=arrival_ns,
                                       applied_phase_ps=_fraction_decimal(applied_phase))
            applied = plant.request(result["command_ppb"], arrival_ns)
            result["applied_quantized_ppb"] = float(applied)
        # Evolve both clocks to this row's elapsed endpoint. Corrections act
        # only on the closed-loop plant; open_loop remains the baseline.
        sample_now_ns = arrival_ns
        phase_now = plant.advance_to(sample_now_ns)
        open_phase_now = open_loop.advance_to(sample_now_ns)
        rows.append({
            "time_s": sample_now_ns * 1e-9,
            "measurement_time_ns": meas_ns,
            "arrival_time_ns": arrival_ns,
            "truth_at_measurement_ps": float(truth_ps),
            "observed_offset_ps": float(observed),
            "open_loop_offset_ps": float(open_phase_now),
            "closed_loop_offset_ps": float(phase_now),
            "status": result["status"],
            "estimated_drift_ppb": result.get("estimated_drift_ppb"),
            "command_ppb": result.get("command_ppb"),
            "applied_quantized_ppb": result.get("applied_quantized_ppb"),
            "measurement_age_ms": result.get("measurement_age_ms"),
        })
        next_s += interval
    tail = rows[-min(60, len(rows)):]
    open_vals = [r["open_loop_offset_ps"] for r in tail]
    closed_vals = [r["closed_loop_offset_ps"] for r in tail]
    metrics = {
        "scenario": name,
        "model_dependent": True,
        "updates": len(rows),
        "dropout_updates": sum(1 for r in rows if r["status"] == "holdover"),
        "open_loop_final_offset_ps": rows[-1]["open_loop_offset_ps"] if rows else None,
        "closed_loop_final_offset_ps": rows[-1]["closed_loop_offset_ps"] if rows else None,
        "open_loop_tail_rms_ps": _rms(open_vals),
        "closed_loop_tail_rms_ps": _rms(closed_vals),
        "closed_loop_tail_abs_p95_ps": _percentile(closed_vals, 0.95),
        "closed_loop_tail_abs_max_ps": max((abs(v) for v in closed_vals), default=None),
        "first_5ps_held_10_updates_s": _settling_time(rows, 5.0, 10),
    }
    return rows, metrics


def DecimalNoise(value):
    # Keep deterministic decimal presentation while accepting Gaussian noise.
    from decimal import Decimal
    return Decimal("%.12f" % value)


def _rms(values):
    return (sum(float(v) ** 2 for v in values) / len(values)) ** 0.5 if values else None


def _settling_time(rows, threshold_ps, count):
    streak = 0
    for i, row in enumerate(rows):
        if abs(row["closed_loop_offset_ps"]) <= threshold_ps and row["status"] == "accepted":
            streak += 1
            if streak >= count:
                return rows[i - count + 1]["time_s"]
        else:
            streak = 0
    return None


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_svg(path, series, title):
    """Small dependency-free plot of offset vs time."""
    width, height = 960, 440
    all_y = [float(p[1]) for values in series.values() for p in values]
    ymin, ymax = (min(all_y), max(all_y)) if all_y else (-1, 1)
    if ymax == ymin:
        ymax += 1
        ymin -= 1
    pad = (ymax - ymin) * 0.08
    ymin -= pad
    ymax += pad
    xmax = max([p[0] for values in series.values() for p in values] or [1])
    colors = {"open loop": "#bb3333", "closed loop": "#1769aa"}
    def point(x, y):
        return (70 + (width - 110) * x / xmax,
                35 + (height - 90) * (ymax - y) / (ymax - ymin))
    chunks = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (width, height, width, height),
              '<rect width="100%" height="100%" fill="white"/>',
              '<text x="%d" y="22" font-family="sans-serif" font-size="16">%s</text>' % (width // 2, title),
              '<line x1="70" y1="35" x2="70" y2="%d" stroke="#333"/><line x1="70" y1="%d" x2="%d" y2="%d" stroke="#333"/>' % (height - 55, height - 55, width - 40, height - 55),
              '<text x="%d" y="%d" font-family="sans-serif" font-size="12">offset (ps)</text>' % (5, height // 2),
              '<text x="%d" y="%d" font-family="sans-serif" font-size="12">elapsed time (s)</text>' % (width // 2, height - 8)]
    for idx in range(5):
        y = ymin + (ymax - ymin) * idx / 4.0
        _, py = point(0, y)
        chunks.append('<line x1="70" y1="%.1f" x2="%d" y2="%.1f" stroke="#ddd"/>' % (py, width - 40, py))
        chunks.append('<text x="35" y="%.1f" font-family="sans-serif" font-size="10">%.2f</text>' % (py + 3, y))
    for name, values in series.items():
        coords = [point(float(x), float(y)) for x, y in values]
        poly = " ".join("%.1f,%.1f" % p for p in coords)
        chunks.append('<polyline fill="none" stroke="%s" stroke-width="1.4" points="%s"/>' % (colors.get(name, "#333"), poly))
    chunks.append('</svg>')
    Path(path).write_text("\n".join(chunks), encoding="utf-8")


def run_suite(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scenarios = [
        ("constant_offset_and_frequency", dict(duration_s=240, initial_offset_ps=700,
          free_ppb=4.0, noise_sigma_ps=1.5, seed=101)),
        ("changing_drift_noise_and_latency", dict(duration_s=300, initial_offset_ps=-350,
          free_ppb=3.0, drift_changes=[(100, -2.5), (200, 5.0)],
          noise_sigma_ps=3.0, processing_latency_s=0.45, command_delay_s=0.4,
          irregular=True, seed=202)),
        ("dropout_and_reacquisition", dict(duration_s=300, initial_offset_ps=500,
          free_ppb=-3.0, drift_changes=[(180, 2.0)], noise_sigma_ps=2.0,
          dropout_ranges=[(100, 115)], seed=303)),
    ]
    all_metrics = []
    for name, kwargs in scenarios:
        rows, metrics = run_scenario(name=name, **kwargs)
        write_csv(out / (name + ".csv"), rows)
        write_svg(out / (name + ".svg"), {
            "open loop": [(r["time_s"], r["open_loop_offset_ps"]) for r in rows],
            "closed loop": [(r["time_s"], r["closed_loop_offset_ps"]) for r in rows],
        }, name + " (simulated model residual)")
        all_metrics.append(metrics)
    (out / "metrics.json").write_text(json.dumps(all_metrics, indent=2) + "\n")
    return all_metrics
