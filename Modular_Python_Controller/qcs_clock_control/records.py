"""Measurement contract for shadow and simulated clock control.

Times are integer nanoseconds on one shared *software* monotonic timeline;
offsets are decimal picoseconds. Integers are subtracted before conversion to
seconds, so a large absolute timestamp never destroys ps-scale resolution.
"""

from decimal import Decimal


class MeasurementRecord(object):
    def __init__(self, measurement_time_ns, arrival_time_ns, offset_ps,
                 pair_id, valid=True, quality="good", uncertainty_ps=None,
                 offset_kind="calibrated_clock_offset", acquisition_start_ns=None,
                 acquisition_end_ns=None, metadata=None):
        self.measurement_time_ns = int(measurement_time_ns)
        self.arrival_time_ns = int(arrival_time_ns)
        self.offset_ps = Decimal(str(offset_ps))
        self.pair_id = str(pair_id)
        self.valid = bool(valid)
        self.quality = str(quality)
        self.uncertainty_ps = (None if uncertainty_ps is None
                               else Decimal(str(uncertainty_ps)))
        self.offset_kind = str(offset_kind)
        self.acquisition_start_ns = (None if acquisition_start_ns is None
                                     else int(acquisition_start_ns))
        self.acquisition_end_ns = (None if acquisition_end_ns is None
                                   else int(acquisition_end_ns))
        self.metadata = dict(metadata or {})
        if self.arrival_time_ns < self.measurement_time_ns:
            raise ValueError("arrival_time_ns precedes measurement_time_ns")
        if self.uncertainty_ps is not None and self.uncertainty_ps < 0:
            raise ValueError("uncertainty_ps must be nonnegative")
        if self.offset_kind != "calibrated_clock_offset":
            raise ValueError("offset must be propagation-corrected and mapped to the declared clock pair")
        if self.acquisition_start_ns is not None and self.acquisition_end_ns is not None:
            if self.acquisition_end_ns < self.acquisition_start_ns:
                raise ValueError("acquisition_end_ns precedes acquisition_start_ns")

    @property
    def age_ns_at_arrival(self):
        return self.arrival_time_ns - self.measurement_time_ns

    def to_dict(self):
        return {
            "measurement_time_ns": self.measurement_time_ns,
            "arrival_time_ns": self.arrival_time_ns,
            "offset_ps": str(self.offset_ps),
            "pair_id": self.pair_id,
            "valid": self.valid,
            "quality": self.quality,
            "uncertainty_ps": None if self.uncertainty_ps is None else str(self.uncertainty_ps),
            "offset_kind": self.offset_kind,
            "acquisition_start_ns": self.acquisition_start_ns,
            "acquisition_end_ns": self.acquisition_end_ns,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data):
        required = ("measurement_time_ns", "arrival_time_ns", "offset_ps", "pair_id")
        missing = [name for name in required if name not in data]
        if missing:
            raise ValueError("missing measurement fields: " + ", ".join(missing))
        return cls(**data)
