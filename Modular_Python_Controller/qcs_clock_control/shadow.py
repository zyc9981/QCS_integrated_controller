"""Read-only JSONL shadow/replay adapters. No network, instrument, or U7 I/O."""

import csv
import json
from decimal import Decimal, localcontext
from pathlib import Path

from .controller import ClockController, ControllerConfig
from .records import MeasurementRecord
from .si5341_math import Si5341N1Model
from .simulation import SimulatedClockActuator


def load_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                yield MeasurementRecord.from_dict(json.loads(line))
            except Exception as exc:
                raise ValueError("%s:%d: %s" % (path, line_number, exc))


def load_csv(path):
    with Path(path).open("r", newline="", encoding="utf-8") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 2):
            try:
                for key in ("valid",):
                    if key in row:
                        row[key] = str(row[key]).strip().lower() in ("1", "true", "yes", "valid")
                for key in ("acquisition_start_ns", "acquisition_end_ns"):
                    if row.get(key) in (None, ""):
                        row.pop(key, None)
                if row.get("uncertainty_ps") in (None, ""):
                    row.pop("uncertainty_ps", None)
                yield MeasurementRecord.from_dict(row)
            except Exception as exc:
                raise ValueError("%s:%d: %s" % (path, row_number, exc))


def _log_line(record, result, model):
    out = {"input": record.to_dict(), "controller": result,
           "hypothetical_si5341_command": None}
    if result.get("status") == "accepted":
        out["hypothetical_si5341_command"] = model.describe(result["command_ppb"])
    return out


def shadow_file(input_path, output_path, pair_id, model, config=None):
    """Calculate hypothetical commands for each saved estimate; never applies them."""
    controller = ClockController(config or ControllerConfig(pair_id=pair_id))
    loader = load_jsonl if str(input_path).lower().endswith((".jsonl", ".ndjson")) else load_csv
    count = accepted = rejected = 0
    with Path(output_path).open("w", encoding="utf-8") as out:
        for record in loader(input_path):
            if record.pair_id != pair_id:
                result = controller.update(record, record.arrival_time_ns)
            else:
                result = controller.update(record, record.arrival_time_ns)
            out.write(json.dumps(_log_line(record, result, model), sort_keys=True) + "\n")
            count += 1
            accepted += int(result["status"] == "accepted")
            rejected += int(result["status"].startswith("rejected"))
            print("%d %s e=%s ps drift=%s ppb age=%.3f ms command=%s ppb" % (
                count, result["status"], result.get("estimated_offset_ps", "--"),
                result.get("estimated_drift_ppb", "--"),
                result.get("measurement_age_ms", record.age_ns_at_arrival / 1e6),
                result.get("command_ppb", controller.last_command_ppb)))
    return {"records": count, "accepted": accepted, "rejected": rejected,
            "output": str(output_path), "mode": "strictly_read_only_shadow"}


def replay_closed_loop(input_path, output_path, pair_id, model, command_delay_s=0.25,
                       config=None, command_quantum_ppb="0.0007"):
    """Replay free-running offsets while adding back the simulated applied phase.

    For e_free recorded in the source, feedback sees e_free + integral(u dt).
    This avoids the invalid practice of feeding unchanged captured offsets to a
    controller after pretending corrections have been applied.
    """
    controller = ClockController(config or ControllerConfig(pair_id=pair_id))
    actuator = SimulatedClockActuator(initial_offset_ps=0, free_ppb=0,
                                      command_delay_s=command_delay_s,
                                      command_quantum_ppb=command_quantum_ppb,
                                      command_quantizer=model.quantize_ppb)
    loader = load_jsonl if str(input_path).lower().endswith((".jsonl", ".ndjson")) else load_csv
    count = accepted = 0
    with Path(output_path).open("w", encoding="utf-8") as out:
        for free_record in loader(input_path):
            if free_record.pair_id != pair_id:
                result = controller.update(free_record, free_record.arrival_time_ns)
                out.write(json.dumps(_log_line(free_record, result, model), sort_keys=True) + "\n")
                count += 1
                continue
            actuator.advance_to(max(actuator.time_ns, free_record.arrival_time_ns))
            correction_at_sample = actuator.phase_at(free_record.measurement_time_ns)
            with localcontext() as ctx:
                ctx.prec = 40
                correction_decimal = (Decimal(correction_at_sample.numerator) /
                                      Decimal(correction_at_sample.denominator))
            corrected = MeasurementRecord(
                measurement_time_ns=free_record.measurement_time_ns,
                arrival_time_ns=free_record.arrival_time_ns,
                offset_ps=str(free_record.offset_ps + correction_decimal),
                pair_id=free_record.pair_id, valid=free_record.valid,
                quality=free_record.quality, uncertainty_ps=free_record.uncertainty_ps,
                offset_kind=free_record.offset_kind,
                acquisition_start_ns=free_record.acquisition_start_ns,
                acquisition_end_ns=free_record.acquisition_end_ns,
                metadata=dict(free_record.metadata, source_offset_ps=str(free_record.offset_ps),
                              simulated_correction_phase_ps=str(correction_at_sample)))
            result = controller.update(corrected, free_record.arrival_time_ns,
                                       applied_phase_ps=correction_decimal)
            if result["status"] == "accepted":
                actuator.request(result["command_ppb"], free_record.arrival_time_ns)
                accepted += 1
            obj = _log_line(corrected, result, model)
            obj["simulated_correction_phase_ps"] = str(correction_at_sample)
            obj["model_dependent_replay"] = True
            out.write(json.dumps(obj, sort_keys=True) + "\n")
            count += 1
    return {"records": count, "accepted": accepted,
            "final_simulated_correction_phase_ps": str(actuator.phase_ps),
            "mode": "closed_loop_model_replay_not_hardware"}
