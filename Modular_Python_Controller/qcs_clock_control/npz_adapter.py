"""Optional adapter for saved QCS Analyzer NPZ estimates (requires NumPy).

Old result archives do not store estimator arrival timestamps. Export therefore
requires an explicit latency assumption and an explicit assertion that the
chosen estimate has already been calibrated/mapped to a clock offset.
"""

import json
from pathlib import Path

from .records import MeasurementRecord


def export_qcs_npz(input_path, output_path, pair_id, offset_field,
                   arrival_latency_ms, calibration_note,
                   confirmed_calibrated_clock_offset=False):
    if not confirmed_calibrated_clock_offset:
        raise ValueError("refusing raw/unverified correlation output; confirm propagation-corrected clock-offset semantics")
    if not calibration_note or not str(calibration_note).strip():
        raise ValueError("provide a calibration/channel-mapping note")
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NumPy is required only for this NPZ adapter") from exc

    # The established `010_1s.npz` analyzer archive stores `data_dict` as a
    # Python-object array with Matplotlib figures. Only load trusted local files.
    with np.load(input_path, allow_pickle=True) as archive:
        if "data_dict" in archive.files:
            data = archive["data_dict"].item()
        else:
            data = {key: archive[key] for key in archive.files}
    if "center" not in data or offset_field not in data:
        raise ValueError("archive must contain center and requested offset field")
    centers = np.asarray(data["center"], dtype=float).ravel()
    offsets = np.asarray(data[offset_field], dtype=float).ravel()
    if len(centers) != len(offsets) or len(centers) == 0:
        raise ValueError("center and offset arrays must be nonempty and equal length")
    if not np.all(np.isfinite(centers)) or not np.all(np.isfinite(offsets)):
        raise ValueError("archive contains nonfinite time/offset values")
    if np.any(np.diff(centers) <= 0):
        raise ValueError("center timestamps must be strictly increasing")

    # Center values are in ps. Subtract the origin in the original units before
    # converting; the source archive already stores center as float64.
    origin_ps = float(centers[0])
    latency_ns = int(round(float(arrival_latency_ms) * 1e6))
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for i, (center_ps, offset_ps) in enumerate(zip(centers, offsets)):
            measure_ns = int(round((float(center_ps) - origin_ps) * 1e-3))
            record = MeasurementRecord(
                measurement_time_ns=measure_ns,
                arrival_time_ns=measure_ns + latency_ns,
                offset_ps="%.12g" % float(offset_ps), pair_id=pair_id,
                valid=True, quality="saved_qcs_analyzer_fit",
                uncertainty_ps=None,
                offset_kind="calibrated_clock_offset",
                metadata={
                    "source": "saved_qcs_analyzer_npz",
                    "source_path": str(input_path),
                    "source_field": offset_field,
                    "source_index": i,
                    "time_origin_ps": "%.12g" % origin_ps,
                    "arrival_timestamp_present_in_archive": False,
                    "arrival_latency_assumption_ms": float(arrival_latency_ms),
                    "formal_offset_uncertainty_present": False,
                    "calibration_and_sign_assertion": str(calibration_note),
                })
            stream.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    return {"records": len(centers), "output": str(out_path),
            "offset_field": offset_field,
            "arrival_latency_assumed_ms": float(arrival_latency_ms),
            "clock_offset_semantics_explicitly_asserted": True,
            "hardware_io": False}
