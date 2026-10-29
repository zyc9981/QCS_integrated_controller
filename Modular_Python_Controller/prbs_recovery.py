"""Summarize native GTY PRBS acquisition, without treating sticky lock as health.

RXPRBSERR is an error indication per native cycle, not a precise bit-error count.
A quiet interval is a finite observation, not a guarantee for future packets.
"""
from pathlib import Path
import csv
import json
from statistics import median
from collections import defaultdict


def distribution(values):
    values = [v for v in values if v is not None]
    return dict(min=min(values), median=median(values), max=max(values)) if values else None


def summarize_prbs_recovery(directory):
    directory = Path(directory)
    source = directory / 'prbs_trials.csv'
    if not source.exists():
        return None
    with source.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    with (directory / 'plan.csv').open(newline='') as stream:
        plans = {r['id']: r for r in csv.DictReader(stream)}
    groups = defaultdict(list)
    details = []
    for raw in rows:
        first_lock = float(raw['first_lock_us'])
        last_error = float(raw['last_error_us'])
        elapsed = float(raw['elapsed_us'])
        quiet = float(raw['quiet_us'])
        planned_release = float(plans[raw['id']].get('rx_release_us', -1))
        planned_restart = raw['kind'] == 'prbs_burst_restart'
        hold_mode = plans[raw['id']].get('hold_mode', 'none')
        hold_release = float(plans[raw['id']].get('hold_release_us', -1))
        # An intentional hold makes RX reset-done low early in the window.
        # Qualification itself still requires RX ready and an active clock.
        bad = bool(int(raw['rx_notready']) or int(raw['clock_stall'])) and not planned_restart
        candidate = max(first_lock, last_error + .005 if last_error >= 0 else first_lock)
        longest = float(raw['longest_quiet_us'])
        settled = candidate if first_lock >= 0 and elapsed - candidate >= quiet and not bad and longest >= elapsed - candidate - .01 else None
        item = dict(id=raw['id'], kind=raw['kind'], port=int(raw['port']), rx_release_us=planned_release,
                    hold_mode=hold_mode, hold_release_us=hold_release,
                    first_lock_us=first_lock if first_lock >= 0 else None,
                    first_quiet_start_us=float(raw['first_quiet_start_us']) if float(raw['first_quiet_start_us']) >= 0 else None,
                    first_quiet_end_us=float(raw['first_quiet_end_us']) if float(raw['first_quiet_end_us']) >= 0 else None,
                    settled_start_us=settled, elapsed_us=elapsed, quiet_us=quiet,
                    last_error_us=last_error if last_error >= 0 else None, longest_quiet_us=longest,
                    error_indicated_cycles=int(raw['error_indicated_cycles']),
                    native_cycles=int(raw['native_cycles']),
                    post_qualification_error_cycles=int(raw['post_qualification_error_cycles']),
                    rx_notready=bool(int(raw['rx_notready'])), clock_stall=bool(int(raw['clock_stall'])))
        item['pre_release_qualification'] = bool(planned_restart and item['first_quiet_start_us'] is not None
                                                  and item['first_quiet_start_us'] < planned_release)
        if item['pre_release_qualification']:
            item['first_quiet_start_us'] = None
            item['first_quiet_end_us'] = None
            item['settled_start_us'] = None
        details.append(item)
        groups[(item['kind'], item['port'], planned_release, hold_mode, hold_release)].append(item)
    summaries = []
    for (kind, port, release, hold_mode, hold_release), items in groups.items():
        summaries.append(dict(kind=kind, port=port, rx_release_us=release, trials=len(items),
            hold_mode=hold_mode, hold_release_us=hold_release,
            qualified=sum(r['first_quiet_end_us'] is not None for r in items),
            pre_release_qualification_trials=sum(r['pre_release_qualification'] for r in items),
            settled_to_end=sum(r['settled_start_us'] is not None for r in items),
            first_lock_us=distribution([r['first_lock_us'] for r in items]),
            first_quiet_start_us=distribution([r['first_quiet_start_us'] for r in items]),
            settled_start_us=distribution([r['settled_start_us'] for r in items]),
            error_indicated_cycles=sum(r['error_indicated_cycles'] for r in items),
            post_qualification_error_cycles=sum(r['post_qualification_error_cycles'] for r in items)))
    aurora = {}
    if (directory / 'trials.csv').exists():
        with (directory / 'trials.csv').open(newline='') as stream:
            for raw in csv.DictReader(stream):
                if raw['kind'] == 'burst':
                    aurora[plans[raw['id']]['seed_hex']] = raw
    header_clean = {}
    if (directory / 'header_activity_summary.json').exists():
        header_report = json.loads((directory / 'header_activity_summary.json').read_text())
        header_clean = {r['id']: r['first_clean_header_window_end_us']
                        for r in header_report['trials'] if r['port'] == 4}
    pairs = []
    for item in details:
        if item['kind'] != 'prbs_burst' or item['port'] != 4:
            continue
        other = aurora.get(plans[item['id']]['seed_hex'])
        if other:
            ready = float(other['ready_us'])
            pairs.append(dict(prbs_id=item['id'], aurora_id=other['id'],
                              prbs_first_quiet_start_us=item['first_quiet_start_us'],
                              prbs_settled_start_us=item['settled_start_us'],
                              aurora_ready_us=ready if ready >= 0 else None,
                              aurora_first_clean_header_window_end_us=header_clean.get(other['id']),
                              aurora_result_code=int(other['result_code'])))
    report = dict(
        scope='Native GTY PRBS31 on QSFP3 TX2 -> QSFP4 RX2; Q3 observes reverse direction or local loopback.',
        origin='Burst: QSFP3 TX-enable I2C STOP; baseline: hardware release of freshly reset checker.',
        clock_tick_ns=5,
        clock_domain_uncertainty='Several FPGA cycles, plus native PRBS acquisition criterion and counter CDC latency.',
        caveats=[
            'Native PRBS lock is sticky; every trial resets the checker before the time origin.',
            'Error-indicated native cycles are not exact bit-error counts or BER.',
            'Quiet intervals require lock, RX reset-done and a running native clock; stalled clocks are flagged.',
            'Settled start is the last observed error/first lock boundary followed by a quiet tail through the capture end.',
            'PRBS mode suppresses Aurora-driven RX restarts, gearbox slips and automatic polarity changes.',
            'Comparing PRBS with Aurora changes the serial pattern and automatic reset policy as well as framing.',
            'This comparison cannot separate laser, optical-module receiver/retimer and GTY CDR settling.',
            'Timed RX holds schedule reset REQUEST release; GTY reset execution follows that release.',
            'Qualification before a scheduled reset is excluded from post-reset acquisition timing.',
            'A finite quiet capture does not guarantee future error-free communication.',
        ], results=summaries, pairs=pairs, trials=details)
    (directory / 'prbs_summary.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Native PRBS recovery comparison', '', report['scope'], '',
             '| Condition | RX | Trials | Qualified | Quiet through end | Median first quiet start (us) | Median settled start (us) | Error-indicated cycles |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    print('\nNative PRBS recovery summary (error cycles, not bit BER):')
    for item in summaries:
        def med(field):
            return f"{item[field]['median']:.3f}" if item[field] else 'unavailable'
        label = f"{item['kind']} release={item['rx_release_us']:g} us"
        if item['hold_release_us'] >= 0:
            label = f"{item['kind']} hold={item['hold_mode']} release={item['hold_release_us']:g} us"
        lines.append(f"| {label} | {item['port']} | {item['trials']} | {item['qualified']} | "
                     f"{item['settled_to_end']} | {med('first_quiet_start_us')} | {med('settled_start_us')} | {item['error_indicated_cycles']} |")
        print(f"  {label} Q{item['port']}: qualified {item['qualified']}/{item['trials']}; "
              f"median first quiet start={med('first_quiet_start_us')} us; settled={med('settled_start_us')} us; pre-reset excluded={item['pre_release_qualification_trials']}")
    lines += ['', '## Interpretation limits', ''] + ['- ' + text for text in report['caveats']]
    lines += ['', 'Raw results: `prbs_trials.csv`; paired Aurora payload results: `trials.csv`.',
              'See `vivado.log` for checker validation failures and FPGA/module restoration.']
    (directory / 'PRBS_README.md').write_text('\n'.join(lines) + '\n')
    if (directory / 'hold_trials.csv').exists():
        from receiver_hold_analysis import summarize_receiver_holds
        summarize_receiver_holds(directory, report)
    return report


if __name__ == '__main__':
    import sys
    summarize_prbs_recovery(sys.argv[1])
