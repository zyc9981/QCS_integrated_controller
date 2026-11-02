"""Command line entry points for offline simulation and read-only shadow mode."""

import argparse
import json
from pathlib import Path

from .controller import ControllerConfig
from .shadow import replay_closed_loop, shadow_file
from .si5341_math import Si5341N1Model
from .simulation import run_suite


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "FPGA_HH_QSFP" / "clock_circuit_audit_20261101" / "commissioning" / "register_plan.json"


def load_candidate_model():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    # Candidate profile is documented in REGISTER_SEQUENCE.md. It is a
    # proposed N1 plan, not an assertion that N1/OUT8 is active.
    vco = "13667168671.2"
    return Si5341N1Model(vco_hz=vco, numerator=plan["numerator"],
                         denominator=plan["denominator"], r_divider=2)


def load_config(path, pair_id):
    allowed = set(ControllerConfig.__dataclass_fields__.keys())
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        values = {key: value for key, value in data.items() if key in allowed}
        values.setdefault("pair_id", pair_id)
        return ControllerConfig(**values)
    return ControllerConfig(pair_id=pair_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline QCS clock controller; no hardware writer exists")
    sub = parser.add_subparsers(dest="command")
    sim = sub.add_parser("simulate", help="run reproducible model scenarios")
    sim.add_argument("--out", default="clock_control_results/simulation")
    shadow = sub.add_parser("shadow", help="process saved estimates, never apply commands")
    shadow.add_argument("input")
    shadow.add_argument("--out", default="clock_control_shadow.jsonl")
    shadow.add_argument("--pair", default="nodeA-nodeB")
    shadow.add_argument("--max-age-s", type=float)
    shadow.add_argument("--config")
    replay = sub.add_parser("replay", help="closed-loop model replay of free-running records")
    replay.add_argument("input")
    replay.add_argument("--out", default="clock_control_replay.jsonl")
    replay.add_argument("--pair", default="nodeA-nodeB")
    replay.add_argument("--command-delay-s", type=float, default=0.25)
    replay.add_argument("--config")
    npz = sub.add_parser("npz-export", help="export saved analyzer epsilon only after explicit calibration/sign confirmation")
    npz.add_argument("input")
    npz.add_argument("--out", required=True)
    npz.add_argument("--pair", required=True)
    npz.add_argument("--offset-field", default="epsilon")
    npz.add_argument("--arrival-latency-ms", type=float, required=True,
                      help="archive has no arrival time; this is an explicit modeling assumption")
    npz.add_argument("--calibration-note", required=True,
                      help="document propagation calibration and node-reference sign mapping")
    npz.add_argument("--confirm-calibrated-clock-offset", action="store_true",
                      help="assert the selected field is a propagation-corrected clock offset")
    args = parser.parse_args(argv)
    if args.command == "simulate":
        print(json.dumps(run_suite(args.out), indent=2))
        return 0
    if args.command in ("shadow", "replay"):
        model = load_candidate_model()
        config = load_config(args.config, args.pair)
        if args.command == "shadow":
            if args.max_age_s is not None:
                config.max_measurement_age_s = args.max_age_s
            result = shadow_file(args.input, args.out, args.pair, model, config)
        else:
            result = replay_closed_loop(args.input, args.out, args.pair, model,
                                        args.command_delay_s, config)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "npz-export":
        from .npz_adapter import export_qcs_npz
        result = export_qcs_npz(args.input, args.out, args.pair, args.offset_field,
                                args.arrival_latency_ms, args.calibration_note,
                                args.confirm_calibrated_clock_offset)
        print(json.dumps(result, indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
