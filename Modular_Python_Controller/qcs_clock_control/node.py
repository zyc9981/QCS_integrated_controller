"""Measurement-to-command node pipeline; live mode is opt-in and gated."""

import json
import socket
import time
from fractions import Fraction
from pathlib import Path

from .actuator import (AppliedCorrectionHistory, Si5341N1Actuator,
                       VivadoSi5341Transport, utc_event_to_monotonic_ns)
from .controller import ClockController, ControllerConfig
from .network import MeasurementReceiver, make_wire_measurement
from .si5341_math import Si5341N1Model


def run_node(receiver, pair_id, model, mode="dry-run", actuator=None, output=None,
             config=None):
    """Return a callback suitable for MeasurementReceiver."""
    cfg = config or ControllerConfig(pair_id=pair_id)
    cfg.pair_id = pair_id
    ctl = ClockController(cfg)
    now_mono = time.monotonic_ns()
    initial_ppb = (float(actuator.initial_correction_ppb) if actuator is not None else 0.0)
    ctl.confirm_applied(initial_ppb)
    history = AppliedCorrectionHistory(now_mono, initial_ppb)
    out = open(output, "a", encoding="utf-8") if output else None

    def process(record, wire):
        # The input's age is independently bounded by the receiver. If the
        # midpoint predates node startup by a small amount, no in-session
        # correction has yet accumulated there; the history returns zero.
        applied_phase = history.phase_at(record.measurement_time_ns)
        now = time.monotonic_ns()
        result = ctl.update(record, now_ns=now,
                            applied_phase_ps=Fraction(applied_phase))
        result["sequence"] = record.metadata.get("sequence")
        result["node_id"] = record.metadata.get("node_id")
        result["reference_id"] = record.metadata.get("reference_id")
        result["measurement_age_ms"] = (now-record.measurement_time_ns)/1e6
        result["offset_ps"] = str(record.offset_ps)
        result["calibration"] = record.metadata.get("calibration")
        result["actuator_mode"] = mode
        result["requested_command"] = None
        result["actuator_result"] = "not_applied"
        if result.get("status") == "accepted":
            requested = float(result["requested_correction_ppb"])
            description = model.describe(requested)
            result["requested_command"] = description
            result["divider_command"] = description
            if mode == "live":
                wall_start = time.time_ns()
                mono_start = time.monotonic_ns()
                try:
                    applied = actuator.apply(requested)
                except Exception as exc:
                    result["status"] = "actuation_failed"
                    result["actuator_result"] = "failed_not_applied"
                    result["actuator_error"] = str(exc)
                    _emit(result)
                    return result
                transaction = applied.get("transaction", {})
                event_utc_us = transaction.get("applied_utc_us")
                finished_ns = time.monotonic_ns()
                event_ns = utc_event_to_monotonic_ns(event_utc_us,
                                                     wall_start, mono_start)
                if event_utc_us is not None and not (mono_start <= event_ns <= finished_ns):
                    event_ns = finished_ns
                    result["applied_event_time_fallback"] = "outside_host_transaction_interval"
                if event_ns < history.events[-1][0]:
                    event_ns = history.events[-1][0]
                    result["applied_event_time_fallback"] = "nonmonotonic_host_wall_clock"
                actual = Fraction(applied["actual_ppb"])
                history.record(event_ns, actual)
                ctl.confirm_applied(float(actual))
                result["actuator_result"] = applied["status"]
                result["applied_correction_ppb"] = str(actual)
                result["applied_event_monotonic_ns"] = event_ns
            else:
                # Dry-run is a virtual plant assumption, never a physical write.
                actual = model.quantize_ppb(requested)
                history.record(now, actual)
                ctl.confirm_applied(float(actual))
                result["actuator_result"] = "simulated_only_not_hardware_applied"
                result["simulated_correction_ppb"] = str(actual)
        _emit(result)
        return result

    def _unused():
        return None

    def _emit(obj):
        line = json.dumps(obj, sort_keys=True, default=str)
        print(line, flush=True)
        if out:
            out.write(line + "\n")
            out.flush()

    process.close = lambda: out.close() if out else None
    return process


def consume_lines(stream, receiver):
    count = 0
    for line_number, line in enumerate(stream, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            receiver.process_line(line.strip())
            count += 1
        except Exception as exc:
            print(json.dumps({"status": "rejected", "line": line_number,
                              "error": str(exc)}), flush=True)
    return count


def mock_server(host, port, node_id="nodeA", reference_id="nodeB", count=5,
                interval_s=1.0, initial_offset_ps=1000.0, drift_ppb=1.0,
                measurement_age_ms=100.0, auth_token=None):
    """Small TCP source for protocol and dry-run demonstrations."""
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        stream = sock.makefile("rwb", buffering=0)
        start = time.monotonic()
        for seq in range(int(count)):
            elapsed = seq * float(interval_s)
            offset = float(initial_offset_ps) + elapsed * float(drift_ppb) * 1000.0
            wire = make_wire_measurement(node_id, reference_id, seq, offset,
                                         measurement_age_ms=measurement_age_ms,
                                         auth_token=auth_token)
            stream.write((json.dumps(wire) + "\n").encode("utf-8"))
            reply = stream.readline()
            if not reply:
                raise ConnectionError("measurement node closed the connection")
            print("response", reply.decode("utf-8").strip())
            remaining = start + (seq + 1) * float(interval_s) - time.monotonic()
            if seq + 1 < int(count) and remaining > 0:
                time.sleep(remaining)
    return 0


def load_candidate():
    root = Path(__file__).resolve().parents[2]
    plan = json.loads((root / "FPGA_HH_QSFP/clock_circuit_audit_20261101/commissioning/register_plan.json").read_text())
    return Si5341N1Model("13667168671.2", plan["numerator"], plan["denominator"], 2)

