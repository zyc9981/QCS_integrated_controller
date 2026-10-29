"""Decode passive FPGA startup snapshots. Times relative to Q3 enable STOP."""
import csv
from collections import defaultdict
import json
from statistics import median

SIGNALS = ('cdr_lock_raw_reserved', 'cdr_stable_helper_raw', 'rx_reset_done', 'block_sync',
           'block_sync_allowed', 'cdr_fsm_reset', 'hp_or_pma_reset', 'lane_up',
           'channel_up', 'pll_and_reset_ready', 'sys_reset', 'explicit_aurora_reset', 'hard_error',
           'soft_error', 'diagnostic_rx_reset_request', 'mmcm_not_locked')


def decode_record(value, origin):
    def time(shift):
        ticks = (value >> shift) & 0xffffffff
        return None if ticks == 0xffffffff else (ticks-origin)/200
    initial, final = (value >> 126) & 1, (value >> 127) & 1
    first, rise, fall = time(0), time(32), time(64)
    return dict(first_high_us=first, last_rise_us=rise, last_fall_us=fall,
                rises=(value >> 96) & 0x7fff, falls=(value >> 111) & 0x7fff,
                initial=initial, final=final,
                final_high_since_us=(rise if rise is not None else first) if final else None)


def summarize_startup(directory):
    source = directory/'startup_raw.csv'
    if not source.exists():
        return
    trials = {r['id']: r for r in csv.DictReader((directory/'trials.csv').open())}
    rows = []
    groups = defaultdict(list)
    with source.open() as f:
        for raw in csv.DictReader(f):
            trial = trials.get(raw['id'])
            if trial is None:
                continue
            packed, origin = int(raw['records_hex'],16), int(raw['origin_ticks'])
            for index in range(32):
                decoded = decode_record((packed >> (index*128)) & ((1<<128)-1), origin)
                row = dict(id=raw['id'], kind=trial['kind'], guard_us=trial['guard_us'],
                           reset_aurora=trial['reset_aurora'], result_code=trial['result_code'],
                           module=3+index//16, rx_release_us=trial.get('rx_release_us','-1'),
                           signal=('gt_reset' if index%16==14 and not (int(raw['metadata_hex'],16)>>66)&1 else SIGNALS[index%16]), **decoded)
                rows.append(row)
                groups[(row['kind'],row['guard_us'],row['reset_aurora'],row['module'],row['signal'],row['rx_release_us'])].append(row)
    if not rows:
        return
    with (directory/'startup_timing.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summaries=[]
    for key, values in groups.items():
        since=[r['final_high_since_us'] for r in values if r['final_high_since_us'] is not None]
        summaries.append(dict(zip(('kind','guard_us','reset_aurora','module','signal','rx_release_us'),key),
                              trials=len(values), final_high=sum(r['final'] for r in values),
                              median_final_high_since_us=median(since) if since else None,
                              max_rises=max(r['rises'] for r in values),max_falls=max(r['falls'] for r in values)))
    (directory/'startup_summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    print(f'Startup timing details: {directory / "startup_timing.csv"}',flush=True)
