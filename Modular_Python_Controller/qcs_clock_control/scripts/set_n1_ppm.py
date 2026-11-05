"""Set N1 frequency correction relative to nominal; dry-run by default."""
import argparse
import json
import subprocess
import statistics
import tempfile
from fractions import Fraction
from pathlib import Path
from pcie_n1_step_smoke import (NOMINAL, FIXED, NUM_ADDRS, take_snapshot, checks,
                               FileMmio, PcieI2cClient, PcieSi5341Transport)


def calculate(ppm):
    correction = Fraction(ppm) / 1000000
    if correction <= -1:
        raise ValueError('correction must be greater than -1000000 ppm')
    exact = Fraction(NOMINAL) / (1 + correction)
    numerator = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
    if not 0 < numerator < 2**44 or not 10 <= Fraction(numerator, 4250000000) <= 4095:
        raise ValueError('requested N1 divider is outside the supported range')
    return numerator, float((Fraction(NOMINAL, numerator) - 1) * 1000000)


def measure_frequency(vivado, ltx, seconds=3):
    script = Path(__file__).with_name('read_out8_frequency.tcl')
    with tempfile.TemporaryDirectory(prefix='qcs_frequency_') as work:
        proc = subprocess.run([vivado, '-mode', 'batch', '-nolog', '-nojournal',
                               '-source', str(script), '-tclargs', ltx, str(seconds)],
                              cwd=work, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True,
                              timeout=seconds+90)
    samples = []
    for line in proc.stdout.splitlines():
        if line.startswith('QCS_FREQ '):
            _, sequence, edges, gate = line.split()
            samples.append({'sequence': int(sequence), 'edges': int(edges),
                            'reference_ticks': int(gate),
                            'frequency_hz': int(edges) * 200000000.0 / int(gate)})
    if proc.returncode or len(samples) != seconds:
        raise RuntimeError('OUT8 measurement failed: ' + proc.stdout[-4000:])
    for previous, current in zip(samples, samples[1:]):
        if current['sequence'] != ((previous['sequence'] + 1) & 0xffffffff):
            raise RuntimeError('nonconsecutive frequency windows')
    total_edges = sum(s['edges'] for s in samples)
    total_ticks = sum(s['reference_ticks'] for s in samples)
    return {'frequency_hz': total_edges * 200000000.0 / total_ticks,
            'measurement_seconds': total_ticks / 200000000.0,
            'total_edges': total_edges,
            'median_hz': statistics.median(s['frequency_hz'] for s in samples),
            'samples': samples, 'reference_nominal_hz': 200000000,
            'counter_resolution_hz': 200000000.0 / total_ticks,
            'note': 'Relative to uncalibrated onboard reference; not absolute frequency accuracy.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ppm', required=True, help='signed ppm relative to nominal; positive means faster')
    parser.add_argument('--live', action='store_true', help='apply and leave the requested correction active')
    parser.add_argument('--device', default='/dev/xdma0_user')
    parser.add_argument('--output', help='optional JSON result file')
    parser.add_argument('--vivado', default='/home/alzhu/vivado_dl/2025.2/Vivado/bin/vivado')
    parser.add_argument('--ltx', default=str(Path(__file__).resolve().parents[3] /
        'FPGA_HH_QSFP/clock_circuit_audit_20261101/commissioning/pci_clock_control/artifacts/20261104/hh_qsfp_pcie_clock_control_bar_enabled.ltx'))
    parser.add_argument('--measure-seconds', type=int, default=3,
                        help='consecutive one-second windows per before/after measurement (default: 3)')
    args = parser.parse_args()
    if args.measure_seconds < 1:
        parser.error('--measure-seconds must be positive')
    try:
        target, actual = calculate(args.ppm)
    except (ValueError, ZeroDivisionError) as exc:
        parser.error(str(exc))
    result = {'requested_ppm': args.ppm, 'representable_ppm': actual,
              'numerator': '0x%012X' % target, 'applied': False}
    if args.live:
        mmio = FileMmio(args.device)
        try:
            transport = PcieSi5341Transport(PcieI2cClient(mmio))
            # Verify chip identity before accepting any clock configuration.
            transport.verify_state(FIXED)
            before = take_snapshot(transport, FIXED)
            normalized = dict(before)
            for i, address in enumerate(NUM_ADDRS):
                normalized[address] = (NOMINAL >> (8 * i)) & 255
            checks(normalized)
            current = sum(before[a] << (8*i) for i, a in enumerate(NUM_ADDRS))
            if not 0 < current < 2**44 or not 10 <= Fraction(current, 4250000000) <= 4095:
                raise ValueError('current N1 numerator is invalid')
            result['frequency_before'] = measure_frequency(args.vivado, args.ltx, args.measure_seconds)
            result['transaction'] = transport.apply_n1(target, before)
            after = take_snapshot(transport, FIXED)
            expected = dict(before)
            for i, address in enumerate(NUM_ADDRS):
                expected[address] = (target >> (8*i)) & 255
            if after != expected:
                raise RuntimeError('post-update register verification failed')
            result['applied'] = True
            result['previous_numerator'] = '0x%012X' % current
            try:
                result['frequency_after'] = measure_frequency(args.vivado, args.ltx, args.measure_seconds)
                f_before = result['frequency_before']['frequency_hz']
                f_after = result['frequency_after']['frequency_hz']
                result['measured_change_hz'] = f_after - f_before
                result['measured_change_ppm'] = (f_after / f_before - 1) * 1000000
                result['expected_change_ppm_from_previous'] = (current / target - 1) * 1000000
            except Exception as exc:
                result['frequency_measurement_error'] = str(exc)
                # The verified command remains applied even if telemetry fails.
        finally:
            mmio.close()
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    summary = dict(result)
    for name in ('frequency_before', 'frequency_after'):
        if name in summary:
            summary[name] = {key: value for key, value in summary[name].items()
                             if key != 'samples'}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
