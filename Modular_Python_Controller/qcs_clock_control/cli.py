"""Command line for simulation, shadow/replay, TCP measurements and guarded live mode."""

import argparse
import json
from pathlib import Path
import sys

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
    parser = argparse.ArgumentParser(description="QCS clock controller; dry-run by default, live writes are gated")
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
    listen = sub.add_parser("listen", help="receive distributed JSONL offset measurements over TCP")
    listen.add_argument("--bind", default="127.0.0.1")
    listen.add_argument("--port", type=int, default=9876)
    listen.add_argument("--pair", default="nodeA-nodeB")
    listen.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    listen.add_argument("--commissioning-manifest")
    listen.add_argument("--allow-live-writes", action="store_true")
    listen.add_argument("--actuator-transport", choices=("vivado", "pcie"), default="vivado",
                        help="explicit physical I/O path for live mode; PCIe requires the dedicated control image")
    listen.add_argument("--log", default="clock_control_node.jsonl")
    listen.add_argument("--config")
    listen.add_argument("--max-age-s", type=float, default=5.0)
    listen.add_argument("--max-utc-uncertainty-ms", type=float, default=10.0)
    listen.add_argument("--auth-token-file")
    wire = sub.add_parser("consume-wire", help="consume protocol JSONL from file or stdin")
    wire.add_argument("input", help="JSONL file, or - for stdin")
    wire.add_argument("--pair", default="nodeA-nodeB")
    wire.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    wire.add_argument("--commissioning-manifest")
    wire.add_argument("--allow-live-writes", action="store_true")
    wire.add_argument("--actuator-transport", choices=("vivado", "pcie"), default="vivado",
                      help="explicit physical I/O path for live mode; PCIe requires the dedicated control image")
    wire.add_argument("--log", default="clock_control_node.jsonl")
    wire.add_argument("--config")
    wire.add_argument("--max-age-s", type=float, default=5.0)
    wire.add_argument("--max-utc-uncertainty-ms", type=float, default=10.0)
    wire.add_argument("--auth-token-file")
    mock = sub.add_parser("mock-server", help="send a synthetic JSONL measurement stream to a node")
    mock.add_argument("--host", default="127.0.0.1")
    mock.add_argument("--port", type=int, default=9876)
    mock.add_argument("--node", default="nodeA")
    mock.add_argument("--reference", default="nodeB")
    mock.add_argument("--count", type=int, default=5)
    mock.add_argument("--interval-s", type=float, default=1.0)
    mock.add_argument("--initial-offset-ps", type=float, default=1000.0)
    mock.add_argument("--drift-ppb", type=float, default=1.0)
    mock.add_argument("--measurement-age-ms", type=float, default=100.0)
    mock.add_argument("--auth-token-file")
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
    if args.command in ("listen", "consume-wire"):
        token = (Path(args.auth_token_file).read_bytes().strip()
                 if args.auth_token_file else None)
        mmio = None
        if args.mode == "live":
            if not args.allow_live_writes or not args.commissioning_manifest:
                parser.error("live mode requires --allow-live-writes and --commissioning-manifest")
            if not args.auth_token_file:
                parser.error("live mode requires --auth-token-file for HMAC-authenticated measurements")
            if not token:
                parser.error("authentication token file is empty")
            from .actuator import Si5341N1Actuator, VivadoSi5341Transport
            if args.actuator_transport == "pcie":
                from .pcie_i2c import FileMmio, PcieI2cClient, PcieSi5341Transport
                mmio = FileMmio()
                transport = PcieSi5341Transport(PcieI2cClient(mmio))
            else:
                transport = VivadoSi5341Transport()
            actuator = Si5341N1Actuator(args.commissioning_manifest, transport)
            actuator.verify()
            print("LIVE_PRECONDITIONS_READBACK_VERIFIED; no clock write has occurred", flush=True)
        else:
            actuator = None
        from .network import MeasurementReceiver, serve_jsonl
        from .node import consume_lines, load_candidate, run_node
        config = load_config(args.config, args.pair)
        callback = run_node(None, args.pair, load_candidate(), args.mode,
                            actuator=actuator, output=args.log, config=config)
        receiver = MeasurementReceiver(callback, max_age_s=args.max_age_s,
                                       max_clock_uncertainty_ms=args.max_utc_uncertainty_ms,
                                       auth_token=token, require_auth=(args.mode == "live"))
        try:
            if args.command == "listen":
                print("Listening on %s:%d mode=%s pair=%s" %
                      (args.bind, args.port, args.mode, args.pair), flush=True)
                serve_jsonl(args.bind, args.port, receiver)
            else:
                stream = sys.stdin if args.input == "-" else open(args.input, "r", encoding="utf-8")
                try:
                    consume_lines(stream, receiver)
                finally:
                    if stream is not sys.stdin:
                        stream.close()
        except KeyboardInterrupt:
            pass
        finally:
            callback.close()
            if mmio is not None:
                mmio.close()
        return 0
    if args.command == "mock-server":
        from .node import mock_server
        token = (Path(args.auth_token_file).read_bytes().strip()
                 if args.auth_token_file else None)
        return mock_server(args.host, args.port, args.node, args.reference,
                           args.count, args.interval_s, args.initial_offset_ps,
                           args.drift_ppb, args.measurement_age_ms, token)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
