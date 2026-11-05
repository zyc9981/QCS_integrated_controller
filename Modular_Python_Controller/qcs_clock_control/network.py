"""Strict JSON-lines measurement protocol and TCP endpoint.

Sender/receiver monotonic clocks are never compared. Age at the receiver is
reconstructed from sender-reported age at send plus UTC transit age, and only
accepted when sender/receiver UTC uncertainty is within the configured bound.
"""

import json
import hashlib
import hmac
import socketserver
import threading
import time
from decimal import Decimal

from .records import MeasurementRecord


PROTOCOL = "qcs-offset-v1"


class SequenceGate(object):
    def __init__(self):
        self.last = {}
        self.lock = threading.Lock()

    def check(self, key, sequence):
        sequence = int(sequence)
        with self.lock:
            previous = self.last.get(key)
            if previous is not None and sequence <= previous:
                raise ValueError("duplicate_or_out_of_order_sequence")
            self.last[key] = sequence


def decode_wire_line(line, receive_monotonic_ns=None, receive_utc_ns=None,
                     max_clock_uncertainty_ms=10.0, max_age_s=5.0,
                     auth_token=None, require_auth=False):
    """Decode one measurement to a local-monotonic ``MeasurementRecord``.

    Required calibration assertions are intentional: a raw g2 epsilon/peak
    cannot enter the actuator path until channel sign and propagation delay
    have been calibrated by the caller that produces the message.
    """
    obj = json.loads(line)
    supplied_auth = obj.get("auth_hmac_sha256")
    if require_auth and not supplied_auth:
        raise ValueError("message_authentication_required")
    if supplied_auth:
        if auth_token is None:
            raise ValueError("message_authentication_key_unavailable")
        signed = dict(obj)
        signed.pop("auth_hmac_sha256", None)
        payload = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected_auth = hmac.new(auth_token, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(supplied_auth), expected_auth):
            raise ValueError("message_authentication_failed")
    required = ("protocol", "node_id", "reference_id", "sequence", "pair_id",
                "offset_ps", "offset_kind", "sign_convention", "valid",
                "quality", "effective_time_utc_ns", "sent_utc_ns",
                "age_ms_at_send", "utc_uncertainty_ms", "calibration", "timebase")
    missing = [key for key in required if key not in obj]
    if missing:
        raise ValueError("missing_fields:" + ",".join(missing))
    if obj["protocol"] != PROTOCOL:
        raise ValueError("unsupported_protocol")
    if obj["timebase"] != "utc_epoch_ns":
        raise ValueError("unsupported_measurement_timebase")
    if not isinstance(obj["valid"], bool):
        raise ValueError("valid_must_be_boolean")
    if not str(obj["node_id"]).strip() or not str(obj["reference_id"]).strip():
        raise ValueError("node_and_reference_identity_required")
    if obj["offset_kind"] != "calibrated_clock_offset":
        raise ValueError("uncalibrated_offset_rejected")
    if obj["sign_convention"] != "node_time_minus_reference_time":
        raise ValueError("unsupported_sign_convention")
    calibration = obj["calibration"]
    if not isinstance(calibration, dict) or calibration.get("status") != "propagation_corrected":
        raise ValueError("propagation_calibration_not_confirmed")
    try:
        source_ps = Decimal(str(calibration["source_estimate_ps"]))
        path_correction_ps = Decimal(str(calibration["path_delay_correction_ps"]))
        sign = int(calibration["epsilon_sign_multiplier"])
    except Exception:
        raise ValueError("calibration_mapping_fields_required")
    if (sign not in (-1, 1) or not source_ps.is_finite() or
            not path_correction_ps.is_finite() or
            not str(calibration.get("calibration_id", "")).strip()):
        raise ValueError("invalid_calibration_mapping")
    if Decimal(str(obj["offset_ps"])) != sign * source_ps - path_correction_ps:
        raise ValueError("offset_does_not_match_declared_calibration_mapping")
    pair_expected = "%s-%s" % (obj["node_id"], obj["reference_id"])
    if obj["pair_id"] != pair_expected:
        raise ValueError("pair_identity_mismatch")
    uncertainty = Decimal(str(obj["utc_uncertainty_ms"]))
    age_send = Decimal(str(obj["age_ms_at_send"]))
    if (not uncertainty.is_finite() or not age_send.is_finite() or
            uncertainty < 0 or age_send < 0 or
            uncertainty > Decimal(str(max_clock_uncertainty_ms))):
        raise ValueError("utc_timebase_uncertainty_exceeds_limit")
    mono_now = time.monotonic_ns() if receive_monotonic_ns is None else int(receive_monotonic_ns)
    utc_now = time.time_ns() if receive_utc_ns is None else int(receive_utc_ns)
    sent_utc = int(obj["sent_utc_ns"])
    effective_utc = int(obj["effective_time_utc_ns"])
    age_at_send_ns = int(age_send * Decimal(1000000))
    transit_ns = utc_now - sent_utc
    # A modest negative transit can result from UTC uncertainty; clamp to zero
    # but never use sender and receiver monotonic values against each other.
    if transit_ns < -int(uncertainty * Decimal(1000000)):
        raise ValueError("sender_utc_is_in_future")
    transit_ns = max(0, transit_ns)
    age_ns = age_at_send_ns + transit_ns + int(uncertainty * Decimal(1000000))
    if age_ns > int(max_age_s * 1e9):
        raise ValueError("stale_measurement")
    # Timestamp is expressed on a local monotonic axis by subtraction from the
    # local receive time. effective_utc is cross-checked against age metadata.
    utc_age_ns = utc_now - effective_utc
    if abs(utc_age_ns - age_ns) > int((float(uncertainty) + 2.0) * 1e6):
        raise ValueError("inconsistent_measurement_time_and_age")
    measurement_mono_ns = mono_now - age_ns
    interval_fields = ("acquisition_start_utc_ns", "acquisition_end_utc_ns")
    if (obj.get(interval_fields[0]) is None) != (obj.get(interval_fields[1]) is None):
        raise ValueError("both_acquisition_interval_bounds_required")
    acquisition_start_mono = acquisition_end_mono = None
    if obj.get(interval_fields[0]) is not None:
        start_utc = int(obj[interval_fields[0]])
        end_utc = int(obj[interval_fields[1]])
        if start_utc > end_utc or not (start_utc <= effective_utc <= end_utc):
            raise ValueError("invalid_acquisition_interval_or_effective_time")
        acquisition_start_mono = mono_now - (utc_now - start_utc)
        acquisition_end_mono = mono_now - (utc_now - end_utc)
    record = MeasurementRecord(
        measurement_time_ns=measurement_mono_ns,
        arrival_time_ns=mono_now,
        offset_ps=obj["offset_ps"],
        pair_id=obj["pair_id"],
        valid=bool(obj["valid"]), quality=str(obj["quality"]),
        uncertainty_ps=obj.get("uncertainty_ps"),
        offset_kind=obj["offset_kind"],
        acquisition_start_ns=acquisition_start_mono,
        acquisition_end_ns=acquisition_end_mono,
        metadata={"node_id": obj["node_id"], "reference_id": obj["reference_id"],
                  "sequence": int(obj["sequence"]), "effective_time_utc_ns": effective_utc,
                  "utc_uncertainty_ms": str(uncertainty),
                  "calibration": obj.get("calibration", {})})
    if not record.offset_ps.is_finite():
        raise ValueError("offset_ps_must_be_finite")
    if record.uncertainty_ps is not None and not record.uncertainty_ps.is_finite():
        raise ValueError("uncertainty_ps_must_be_finite")
    if int(obj["sequence"]) < 0:
        raise ValueError("sequence_must_be_nonnegative")
    return record


class MeasurementReceiver(object):
    """JSONL receiver. Callback receives (record, wire_object)."""
    def __init__(self, callback, max_age_s=5.0, max_clock_uncertainty_ms=10.0,
                 auth_token=None, require_auth=False):
        self.callback = callback
        self.max_age_s = max_age_s
        self.max_clock_uncertainty_ms = max_clock_uncertainty_ms
        self.auth_token = auth_token
        self.require_auth = bool(require_auth)
        self.sequences = SequenceGate()
        self.errors = []
        self.lock = threading.Lock()

    def process_line(self, line, mono_ns=None, utc_ns=None):
        obj = json.loads(line)
        key = (str(obj.get("node_id")), str(obj.get("reference_id")), str(obj.get("pair_id")))
        with self.lock:
            record = decode_wire_line(line, mono_ns, utc_ns,
                                      self.max_clock_uncertainty_ms, self.max_age_s,
                                      self.auth_token, self.require_auth)
            self.sequences.check(key, record.metadata["sequence"])
            return self.callback(record, obj)


def serve_jsonl(host, port, receiver, stop_event=None):
    """Serve one JSON object per line; malformed lines are returned as errors."""
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for raw in self.rfile:
                try:
                    result = receiver.process_line(raw.decode("utf-8").strip())
                    response = {"status": result.get("status", "accepted"), "result": result}
                except Exception as exc:
                    receiver.errors.append(str(exc))
                    response = {"status": "rejected", "error": str(exc)}
                self.wfile.write((json.dumps(response, default=str) + "\n").encode("utf-8"))
                self.wfile.flush()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server((host, int(port)), Handler)
    server.timeout = 0.25
    while stop_event is None or not stop_event.is_set():
        server.handle_request()
    server.server_close()
    return server.server_address


def make_wire_measurement(node_id, reference_id, sequence, offset_ps,
                          measurement_age_ms=0.0, uncertainty_ps=2.0,
                          quality="good", valid=True, utc_uncertainty_ms=0.1,
                          now_utc_ns=None, auth_token=None,
                          acquisition_interval_ms=None):
    """Convenience protocol encoder used by the example/mock server."""
    now = time.time_ns() if now_utc_ns is None else int(now_utc_ns)
    age_ns = int(float(measurement_age_ms) * 1e6)
    obj = {"protocol": PROTOCOL, "node_id": node_id, "reference_id": reference_id,
            "sequence": int(sequence), "pair_id": "%s-%s" % (node_id, reference_id),
            "timebase": "utc_epoch_ns",
            "offset_ps": str(offset_ps), "offset_kind": "calibrated_clock_offset",
            "sign_convention": "node_time_minus_reference_time", "valid": bool(valid),
            "quality": quality, "uncertainty_ps": str(uncertainty_ps),
            "effective_time_utc_ns": now - age_ns, "sent_utc_ns": now,
            "age_ms_at_send": float(measurement_age_ms),
            "utc_uncertainty_ms": float(utc_uncertainty_ms),
            "calibration": {"status": "propagation_corrected",
                            "calibration_id": "synthetic-mock-defined",
                            "source_estimate_ps": str(offset_ps),
                            "epsilon_sign_multiplier": 1,
                            "path_delay_correction_ps": "0",
                            "note": "synthetic only; mapping defined by mock"}}
    if acquisition_interval_ms is not None:
        half = int(float(acquisition_interval_ms) * 500000)
        obj["acquisition_start_utc_ns"] = now - age_ns - half
        obj["acquisition_end_utc_ns"] = now - age_ns + half
    if auth_token is not None:
        payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        obj["auth_hmac_sha256"] = hmac.new(auth_token, payload, hashlib.sha256).hexdigest()
    return obj
