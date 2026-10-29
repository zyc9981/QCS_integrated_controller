"""Host orchestration for the standalone HTG-930 optical guard diagnostic."""
from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime
import json
from pathlib import Path
import secrets
import subprocess

VIVADO = Path('/home/alzhu/vivado_dl/2025.2/Vivado/bin/vivado')
ROOT = Path(__file__).resolve().parents[1] / 'FPGA_HH_QSFP' / 'burst_guard'


def summarize(directory):
    path = directory / 'trials.csv'
    if not path.exists():
        return None
    groups = defaultdict(list)
    with path.open(newline='') as source:
        for row in csv.DictReader(source):
            reset = int(row.get('reset_aurora', '0' if row['kind'] == 'baseline' else '1'))
            release = float(row.get('rx_release_us', '-1'))
            groups[(row['kind'], float(row['guard_us']), reset, release)].append(row)
    summaries = []
    for (kind, guard, reset, release), rows in groups.items():
        acquired = [r for r in rows if int(r['result_code']) == 1 and
                    int(r['words_received']) == int(r['words_requested'])]
        bits = sum(int(r['words_received']) * 64 for r in acquired)
        errors = sum(int(r['bit_errors']) for r in acquired)
        summaries.append(dict(
            kind=kind, guard_us=guard, reset_aurora=reset, rx_release_us=release, trials=len(rows), acquired=len(acquired),
            intact=sum(int(r['bit_errors']) == 0 for r in acquired),
            not_ready=sum(int(r['result_code']) == 2 for r in rows),
            timeouts=sum(int(r['result_code']) == 3 for r in rows),
            frame_errors=sum(int(r['result_code']) == 4 for r in rows),
            compared_bits=bits, differing_bits=errors,
            ber=errors / bits if bits else None,
            acquisition_success=len(acquired) / len(rows),
            soft_error_trials=sum(bool(int(r['flags']) & ((1 << 9) | (1 << 17))) for r in rows),
            ready_us=[float(r['ready_us']) for r in rows if float(r['ready_us']) >= 0],
            first_tx_us=[float(r['first_tx_us']) for r in rows if float(r['first_tx_us']) >= 0],
        ))
    report = {
        'scope': 'FPGA-generated/checker pattern on QSFP3 TX2 -> fiber -> QSFP4 RX2; no XDMA',
        'time_origin': 'burst: QSFP3 enable STOP; illuminated reset controls: explicit request release. Engine guard starts after arming acknowledgments.',
        'reset_scope': 'Explicit reset between trials only; automatic Aurora recovery remains enabled',
        'timer_tick_ns': 5, 'clock_crossing_uncertainty': 'several FPGA clock cycles',
        'results': summaries,
    }
    (directory / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Guard-time sweep results', '', report['scope'], '',
             'Burst timestamps start at QSFP3 TX-enable STOP; illuminated-reset timestamps start at reset release. '
             'In illuminated-reset trials the engine guard starts after arming acknowledgments, so use '
             'startup_timing.csv for recovery relative to reset release. Optical turn-on was not '
             'measured. Payload launch requires both Aurora channels ready at the deadline; '
             'a missed deadline is reported as failed acquisition, not silently delayed.', '',
             '| Mode | Guard us | Trials | Acquired | Intact | Not ready | Timeout | Frame error | BER on full frames |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    print('\nGuard sweep summary:')
    for s in summaries:
        label = s['kind'] + (' explicit Aurora reset' if s['reset_aurora'] else ' no explicit Aurora reset')
        if s['rx_release_us'] >= 0: label += f" RX release={s['rx_release_us']:g} us"
        ber = f"{s['ber']:.6e}" if s['ber'] is not None else 'unavailable'
        print(f"  {label} {s['guard_us']:g} us: acquired {s['acquired']}/{s['trials']}, "
              f"intact {s['intact']}, not ready {s['not_ready']}, timeouts {s['timeouts']}, BER {ber}")
        lines.append(f"| {label} | {s['guard_us']:g} | {s['trials']} | {s['acquired']} | "
                     f"{s['intact']} | {s['not_ready']} | {s['timeouts']} | {s['frame_errors']} | {ber} |")
    baseline = next((s for s in summaries if s['kind'] == 'baseline'), None)
    if baseline and (baseline['intact'] != baseline['trials']):
        warning = ('The continuously illuminated baseline is not error-free at the current optical '
                   'setting. Burst errors cannot all be attributed to insufficient guard time.')
        print('WARNING: ' + warning)
        lines += ['', '**' + warning + '**']
    lines += ['', 'BER excludes short/malformed/incomplete frames; acquisition statistics include them. '
              'No errors in this finite sample do not establish zero BER or a deployment margin. '
              'A dark interval applies after module disable writes; it is not measured optical extinction.', '',
              'See trials.csv for per-trial flags, timing and raw status; plan.csv for seeds; power.csv '
              'for slow module DOM snapshots (raw 0.1 uW units). Module settings were saved in '
              'saved_module_settings.csv. Startup signal timestamps are in startup_timing.csv and '
              'startup_summary.json. Check vivado.log for restoration completion. PCIe rescan '
              'is required before using XDMA again.']
    from startup_timing import summarize_startup
    summarize_startup(directory)
    from header_activity import summarize_header_activity
    summarize_header_activity(directory)
    from prbs_recovery import summarize_prbs_recovery
    summarize_prbs_recovery(directory)
    (directory / 'README.md').write_text('\n'.join(lines) + '\n')
    return report


def run_sweep(*, guards_us, repeats=10, dark_ms=100, baseline_trials=20,
              block_size=65536, timeout_ms=100, output_dir=None, reset_mode="reset", test_mode="burst", rx_release_us="0,100,500,1000", header_trace=False, baseline_guard_us=0, prbs_quiet_us=100,
              hold_modes="none,equalizer,cdr,both", hold_release_us="0,10,100,500,1000,2000,5000,10000"):
    if test_mode not in ("burst", "illuminated-reset", "illuminated-rx-reset", "compare", "compare-all", "burst-restart", "compare-restart", "prbs-compare", "prbs-restart", "prbs-hold"):
        raise ValueError("invalid guard test mode")
    if reset_mode not in ("reset", "keep", "compare"):
        raise ValueError("reset mode must be reset, keep, or compare")
    guards = [float(v) for v in guards_us.split(',')]
    if not guards or any(not 0 <= g <= 10_000_000 for g in guards):
        raise ValueError('guard times must be finite values between 0 and 10,000,000 us')
    if not 0 <= baseline_guard_us <= 10_000_000:
        raise ValueError('baseline guard must be finite, from 0 to 10,000,000 us')
    if test_mode in ('prbs-compare', 'prbs-restart', 'prbs-hold'):
        if not 10 <= prbs_quiet_us <= 10000 or min(guards) <= prbs_quiet_us:
            raise ValueError('PRBS quiet interval must be 10..10000 us and shorter than observation window')
        if min(guards) < 1000:
            raise ValueError('PRBS comparison requires observation windows >=1000 us')
        if reset_mode != 'keep':
            raise ValueError('PRBS comparison requires --guard-reset-mode keep')
        baseline_guard_us = max(guards)
    releases = [float(v) for v in rx_release_us.split(',')]
    holds = hold_modes.split(',')
    hold_delays = [float(v) for v in hold_release_us.split(',')]
    if test_mode == 'prbs-hold':
        if not holds or len(set(holds)) != len(holds) or any(m not in ('none', 'equalizer', 'cdr', 'both') for m in holds):
            raise ValueError('hold modes must be unique values from none,equalizer,cdr,both')
        if not hold_delays or any(not 0 <= v < min(guards) for v in hold_delays):
            raise ValueError('hold release delays must be finite, nonnegative and shorter than capture')
    if test_mode in ('burst-restart', 'compare-restart', 'prbs-restart'):
        if not releases or any(not 0 <= v <= 80000 for v in releases):
            raise ValueError('RX release delays must be finite values from 0 to 80000 us')
        if max(releases) >= min(guards):
            raise ValueError('RX release delays must be shorter than every guard deadline')
    if repeats < 1 or baseline_trials < 1 or not dark_ms >= 100:
        raise ValueError('positive trial counts and dark interval >=100 ms are required')
    if block_size % 8 or not 8 <= block_size <= 65535 * 8:
        raise ValueError('block size must be divisible by 8, from 8 to 524280 bytes')
    # Startup observer uses 32-bit 200 MHz timestamps (21.47 s range).
    if dark_ms + max(*guards, baseline_guard_us) / 1000 + timeout_ms > 18_000:
        raise ValueError('dark + guard + receive allowance must be <=18 s for startup timestamps')
    if not 0 < timeout_ms <= 10_000:
        raise ValueError('receive timeout must be between 0 and 10,000 ms')
    bit = ROOT / 'build/burst_guard.runs/impl_1/burst_guard_top.bit'
    ltx = ROOT / 'build/burst_guard.ltx'
    timing = ROOT / 'build/timing.rpt'
    if not all(p.is_file() for p in (bit, ltx, timing)):
        raise FileNotFoundError('Build the guard diagnostic first: Vivado -mode batch -source ' +
                                str(ROOT / 'scripts/build.tcl'))
    directory = Path(output_dir).resolve() if output_dir else ROOT / 'measurements' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    directory.mkdir(parents=True, exist_ok=False)
    fields = ('id', 'kind', 'guard_us', 'dark_ms', 'words', 'seed_hex', 'timeout_ticks', 'reset_aurora', 'rx_release_us', 'header_trace', 'prbs_quiet_us', 'hold_mode', 'hold_release_us')
    with (directory / 'plan.csv').open('x', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(fields)
        index = 0
        def emit(kind, guard, seed, reset, release=-1, hold='none', hold_delay=-1):
            nonlocal index
            ticks = round(guard * 200) + round(timeout_ms * 200_000)
            writer.writerow((index, kind, guard, dark_ms, block_size // 8, seed, ticks, reset, release, int(header_trace), prbs_quiet_us, hold, hold_delay))
            index += 1
        if test_mode in ('prbs-compare', 'prbs-restart', 'prbs-hold'):
            for kind in ('prbs_loopback', 'prbs_loopback_inject'):
                emit(kind, max(guards), f'{secrets.randbits(64) or 1:016x}', 0)
            for _ in range(baseline_trials):
                emit('prbs_baseline', max(guards), f'{secrets.randbits(64) or 1:016x}', 0)
            emit('prbs_inject', max(guards), f'{secrets.randbits(64) or 1:016x}', 0)
        for _ in range(baseline_trials):
            emit('baseline', baseline_guard_us, f'{secrets.randbits(64) or 1:016x}', 0)
        if test_mode == 'prbs-hold':
            for _ in range(baseline_trials):
                for mode in holds:
                    emit('prbs_baseline_hold', max(guards), f'{secrets.randbits(64) or 1:016x}', 0,
                         hold=mode, hold_delay=0 if mode == 'none' else max(hold_delays))
        for guard in guards:
            if test_mode == 'prbs-hold':
                conditions = [(m, d) for m in holds for d in ([0] if m == 'none' else hold_delays)]
                for repetition in range(repeats):
                    seed = f'{secrets.randbits(64) or 1:016x}'
                    sequence = conditions if repetition % 2 == 0 else list(reversed(conditions))
                    for mode, delay in sequence:
                        emit('prbs_burst_hold', guard, seed, 0, hold=mode, hold_delay=delay)
                continue
            if test_mode == 'prbs-restart':
                for repetition in range(repeats):
                    seed = f'{secrets.randbits(64) or 1:016x}'
                    emit('prbs_burst', guard, seed, 0)
                    sequence = releases if repetition % 2 == 0 else list(reversed(releases))
                    for release in sequence: emit('prbs_burst_restart', guard, seed, 0, release)
                continue
            if test_mode in ('prbs-compare', 'prbs-restart'):
                for repetition in range(repeats):
                    seed = f'{secrets.randbits(64) or 1:016x}'
                    conditions = ['prbs_burst', 'burst']
                    if repetition % 2: conditions.reverse()
                    for kind in conditions: emit(kind, guard, seed, 0)
                continue
            if test_mode in ('burst-restart', 'compare-restart', 'prbs-restart'):
                for release in releases:
                    for repetition in range(repeats):
                        seed = f'{secrets.randbits(64) or 1:016x}'
                        conditions = [('burst_restart', 0, release)]
                        if test_mode == 'compare-restart':
                            conditions.insert(0, ('burst', 0, -1))
                            if repetition % 2: conditions.reverse()
                        for kind, reset, value in conditions:
                            emit(kind, guard, seed, reset, value)
                continue
            for repetition in range(repeats):
                seed = f'{secrets.randbits(64) or 1:016x}'
                conditions = []
                if test_mode in ('burst', 'compare', 'compare-all'):
                    modes = [0] if reset_mode == 'keep' else [1]
                    if reset_mode == 'compare':
                        modes = [0, 1] if repetition % 2 == 0 else [1, 0]
                    conditions += [('burst', mode) for mode in modes]
                if test_mode in ('illuminated-reset', 'compare', 'compare-all'):
                    conditions += [('illuminated_reset', 1)]
                if test_mode in ('illuminated-rx-reset', 'compare-all'):
                    conditions += [('illuminated_rx_reset', 1)]
                if test_mode in ('compare', 'compare-all') and repetition % 2:
                    conditions.reverse()
                for kind, reset in conditions:
                    emit(kind, guard, seed, reset)
    print(f'Guard sweep results: {directory}', flush=True)
    print('This temporarily replaces the FPGA image, controls both modules, and restores the '
          'working optical image afterward. Close all controller/DMA applications.', flush=True)
    command = [str(VIVADO), '-mode', 'batch', '-nojournal', '-notrace', '-log',
               str(directory / 'vivado.log'), '-source', str(ROOT / 'scripts/run_sweep.tcl'),
               '-tclargs', str(directory / 'plan.csv'), str(directory)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True, cwd=ROOT)
    interrupted = False
    try:
        while True:
            try:
                line = process.stdout.readline()
            except KeyboardInterrupt:
                interrupted = True
                (directory / 'stop.request').touch()
                print('Stop requested; waiting for the current trial and FPGA/module restoration.', flush=True)
                continue
            if not line:
                break
            if line.startswith(('TRIAL ', 'PRBS ', 'RESTORED ', 'ERROR:', 'WARNING:',
                                'Loading ', 'Restoring ', 'Stop requested')):
                print(line.rstrip(), flush=True)
        code = process.wait()
    finally:
        process.stdout.close()
        summarize(directory)
    if code:
        raise RuntimeError(f'Vivado guard sweep failed; inspect {directory / "vivado.log"}')
    if interrupted:
        raise SystemExit(130)
    print('Sweep complete. Run the documented PCIe rescan before using XDMA again.', flush=True)
    return directory
