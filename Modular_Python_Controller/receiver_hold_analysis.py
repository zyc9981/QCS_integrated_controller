"""Summarize Q4 adaptation holds; no claim about QSFP internals or exact BER."""
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median


def summarize_receiver_holds(directory, prbs_report):
    directory = Path(directory)
    with (directory / 'hold_trials.csv').open(newline='') as stream:
        holds = {r['id']: r for r in csv.DictReader(stream)}
    rows = [r for r in prbs_report['trials'] if r['port'] == 4 and r['id'] in holds]
    groups = defaultdict(list)
    baseline_valid = {}
    for r in rows:
        groups[(r['kind'], r['hold_mode'], r['hold_release_us'])].append(r)
    for (kind, mode, delay), items in groups.items():
        if kind == 'prbs_baseline_hold':
            baseline_valid[mode] = all(r['first_quiet_end_us'] is not None and
                r['error_indicated_cycles'] == 0 and not r['rx_notready'] and not r['clock_stall'] for r in items)
    summaries = []
    lines = ['# GTY receiver hold sweep', '',
        'Only QSFP4 RX2/GTY X1Y58 is held. Time origin is QSFP3 TX-enable I2C STOP, not measured optical onset.', '',
        '| Condition | Hold | Release (us) | Trials | Qualified | Quiet through capture end | Median first quiet start (us) | Median settled start (us) | Error-indicated native cycles | Steady-light hold control clean |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    print('\nQSFP4 GTY hold summary:')
    for (kind, mode, delay), items in groups.items():
        def med(field):
            values = [r[field] for r in items if r[field] is not None]
            return median(values) if values else None
        summary = dict(kind=kind, mode=mode, release_us=delay, trials=len(items),
            qualified=sum(r['first_quiet_end_us'] is not None for r in items),
            quiet_through_end=sum(r['settled_start_us'] is not None for r in items),
            median_first_quiet_start_us=med('first_quiet_start_us'),
            median_settled_start_us=med('settled_start_us'),
            error_indicated_cycles=sum(r['error_indicated_cycles'] for r in items),
            steady_light_control_clean=baseline_valid.get(mode))
        summaries.append(summary)
        def fmt(value): return 'unavailable' if value is None else f'{value:.3f}'
        lines.append(f"| {kind} | {mode} | {delay:g} | {len(items)} | {summary['qualified']} | {summary['quiet_through_end']} | "
            f"{fmt(summary['median_first_quiet_start_us'])} | {fmt(summary['median_settled_start_us'])} | "
            f"{summary['error_indicated_cycles']} | {baseline_valid.get(mode)} |")
        print(f"  {kind} {mode} release={delay:g}us: qualified {summary['qualified']}/{len(items)}; "
              f"settled {summary['quiet_through_end']}/{len(items)}; first quiet={fmt(summary['median_first_quiet_start_us'])}us")
    limits = [
        'A fresh clean 1 ms native PRBS check is required immediately before each hold assertion.',
        'Hold pin ACKs confirm the FPGA wiring and command timing, not hidden analog state retention.',
        'Equalizer mode holds AGC, LF, KH, CFOK, UT, VP, offset cancellation and DFE taps 2..15; all overrides remain zero.',
        'CDR hold freezes the GTY CDR loop/locks to reference; it cannot preserve phase relative to returning optical data.',
        'A mode that corrupts steady illuminated reception is not a valid clean state-preservation control.',
        'The first 100 us quiet interval may precede hold release. Later errors and the final quiet tail are recorded separately.',
        'No explicit GT RX reset is requested during the dark interval or capture; Aurora-driven RX restarts remain suppressed.',
        'The module TX-enable latency and optical/electrical waveform settling are not directly measured.',
        'No improvement cannot establish that the QSFP alone is responsible. Pattern and reset policy differ from normal Aurora.',
        'Native error-indicated cycles are not a precise bit count or BER.',
    ]
    lines += ['', '## Interpretation limits', ''] + ['- '+s for s in limits]
    lines += ['', 'Raw: `plan.csv`, `hold_trials.csv`, `prbs_trials.csv`, `vivado.log`.']
    report = dict(results=summaries, trials=rows, hold_pin_records=holds,
                  steady_light_control_clean=baseline_valid, caveats=limits)
    (directory / 'hold_summary.json').write_text(json.dumps(report, indent=2)+'\n')
    (directory / 'HOLD_README.md').write_text('\n'.join(lines)+'\n')
    return report
