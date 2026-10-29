"""Decode cumulative Gray-counter snapshots; these are digital interface observations.

RXHEADERVALID is interface validity. Legal 01/10 headers can occur in random
noise. Neither quantity alone establishes valid optical data or analog CDR lock.
"""
from pathlib import Path
import csv
import json

COUNTERS = (
    'rx_clock_cycles', 'data_valid_cycles', 'header_valid_cycles',
    'legal_header_cycles', 'illegal_header_cycles', 'gearbox_slip_edges',
    'block_sync_cycles', 'block_sync_rises', 'fsm_reset_cycles',
    'state_begin_cycles', 'state_test_sh_cycles', 'state_sh_valid_cycles',
    'state_sh_invalid_cycles', 'state_slip_cycles', 'state_sync_done_cycles',
    'fsm_reset_rises',
)


def decode_counts(hex_value):
    value = int(hex_value, 16)
    return [(value >> (32 * index)) & 0xffffffff for index in range(16)]


def summarize_header_activity(directory):
    directory = Path(directory)
    source = directory / 'header_activity_raw.csv'
    if not source.exists():
        return None
    with (directory / 'plan.csv').open(newline='') as stream:
        plans = {row['id']: row for row in csv.DictReader(stream)}
    rows, previous, totals = [], {}, {}
    with source.open(newline='') as stream:
        for raw in csv.DictReader(stream):
            meta = int(raw['metadata_hex'], 16)
            if meta >> 96 != 0x48445231:
                raise ValueError('Header recorder signature mismatch')
            trial = raw['id']
            for port, shift in ((3, 64), (4, 73)):
                if int(raw['index']) >= ((meta >> shift) & 511):
                    continue
                counts = decode_counts(raw[f'q{port}_counts_hex'])
                ticks = int(raw[f'q{port}_ticks'])
                key = trial, port
                if key in previous:
                    old_ticks, old_counts = previous[key]
                    delta = [(new - old) & 0xffffffff for new, old in zip(counts, old_counts)]
                    duration = ((ticks - old_ticks) & 0xffffffff) / 200.0
                    # A Gray CDC sample can differ by a few clocks across metrics.
                    if any(v > duration * 500 + 100 for i, v in enumerate(delta)
                           if i not in (5, 7, 15)):
                        raise ValueError(f'Implausible header counter delta in trial {trial}, Q{port}')
                    row = dict(id=trial, kind=plans[trial]['kind'], port=port,
                               index=raw['index'], start_us=old_ticks / 200.0,
                               end_us=ticks / 200.0, duration_us=duration,
                               overflow=(meta >> (84 + port - 3)) & 1)
                    row.update(zip(COUNTERS, delta))
                    row['illegal_header_fraction'] = delta[4] / delta[2] if delta[2] else ''
                    row['header_valid_fraction'] = delta[2] / delta[0] if delta[0] else ''
                    row['block_sync_fraction'] = delta[6] / delta[0] if delta[0] else ''
                    rows.append(row)
                    total = totals.setdefault(key, dict(id=trial, kind=plans[trial]['kind'], port=port,
                        first_block_sync_window_end_us=None, first_clean_header_window_end_us=None,
                        native_clock_stalled_windows=0, gearbox_slip_edges=0,
                        fsm_reset_rises=0, overflow=0, windows=0))
                    total['windows'] += 1
                    total['native_clock_stalled_windows'] += int(delta[0] == 0)
                    total['gearbox_slip_edges'] += delta[5]
                    total['fsm_reset_rises'] += delta[15]
                    total['overflow'] |= row['overflow']
                    if delta[6] and total['first_block_sync_window_end_us'] is None:
                        total['first_block_sync_window_end_us'] = row['end_us']
                    # Strong digital-header evidence, still not payload verification.
                    if delta[2] > 100 and delta[4] == 0 and total['first_clean_header_window_end_us'] is None:
                        total['first_clean_header_window_end_us'] = row['end_us']
                previous[key] = ticks, counts
    if rows:
        with (directory / 'header_activity.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = dict(window_us=100, clock_tick_ns=5,
        caveats=[
            'Gray counters are sampled independently; expect a few native cycles of cross-counter uncertainty.',
            'RXHEADERVALID indicates interface validity, not error-free data.',
            'Random sync-header bits are legal approximately half the time.',
            'Native cycles can stop during reset; fractions use observed native cycles.',
            'Counters wrap modulo 2^32; intervals must be shorter than a counter wrap.',
            'This measures digital alignment, not laser power or analog CDR lock.',
        ], trials=list(totals.values()))
    (directory / 'header_activity_summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Header/alignment windows: {directory / "header_activity.csv"}')
    return report


if __name__ == '__main__':
    import sys
    summarize_header_activity(sys.argv[1])
