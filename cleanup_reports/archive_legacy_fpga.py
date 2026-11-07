from pathlib import Path
import os,json,subprocess
from datetime import datetime
qcs=Path('/home/zyc/QCS');repo=qcs/'QCS_integrated_controller';fpga=repo/'FPGA_HH_QSFP'
names=['temporary_tx0_rx0_20261016','normal_cdrhold_7ms_20261016','normal_guard_timer_20261016','prbs_validation_20261019','prbs_retry_compare_20261019','rx_restart_experiment_20261020','pcie_clock_reset_diagnostic_20261104','rx_squelch_comparison_20261019','local_retry_comparison_20261019','prbs_burst_comparison_20261019','tx_squelch_audit_20261019','research_burst_20261018']
sources=[fpga/n for n in names if (fpga/n).is_dir()]
sources+=sorted(p for p in repo.glob('vivado*') if p.is_file() and p.suffix in {'.log','.jou'})
tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=str(repo)).decode().split('\0'))
skipped=[];eligible=[]
for src in sources:
 rel=str(src.relative_to(repo))
 if any(t==rel or t.startswith(rel+'/') for t in tracked if t):skipped.append(str(src))
 else:eligible.append(src)
archive=qcs/'garbage'/('legacy_fpga_'+datetime.now().strftime('%Y%m%d_%H%M%S'));archive.mkdir(parents=True)
def inventory(path):
 items=[path] if path.is_file() else path.rglob('*')
 total=0;files=0;bits=0
 for p in items:
  if not p.is_symlink() and p.is_file():
   files+=1;total+=p.stat().st_size;bits+=int(p.suffix=='.bit')
 return {'files':files,'bytes':total,'bitstreams':bits}
m={'reason':'Reversible archive; no files deleted.','skipped_tracked_paths':skipped,'moves':[]}
mp=archive/'manifest.json'
for src in eligible:
 m['moves'].append({'source':str(src),'destination':str(archive/src.relative_to(qcs)),'inventory':inventory(src),'moved':False})
mp.write_text(json.dumps(m,indent=2)+'\n')
for e in m['moves']:
 src=Path(e['source']);dst=Path(e['destination']);dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.exists():raise RuntimeError('Destination exists: '+str(dst))
 os.rename(src,dst);e['moved']=True
 e['verified']=inventory(dst)==e['inventory'] and not src.exists()
 mp.write_text(json.dumps(m,indent=2)+'\n')
 if not e['verified']:raise RuntimeError('Verification failed: '+str(dst))
(archive/'restore.py').write_text('''#!/usr/bin/env python3
"""Preview restoration, or restore all moved paths with --apply."""
import argparse,json,os
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');a=p.parse_args()
m=json.loads(Path(__file__).with_name('manifest.json').read_text())
moves=[e for e in reversed(m['moves']) if e['moved']]
for e in moves:
 src=Path(e['destination']);dst=Path(e['source'])
 if not src.exists():raise SystemExit('Archive missing: '+str(src))
 if dst.exists() or dst.is_symlink():raise SystemExit('Original path occupied: '+str(dst))
for e in moves:
 print(e['destination']+' -> '+e['source'])
 if a.apply:
  Path(e['source']).parent.mkdir(parents=True,exist_ok=True)
  os.rename(e['destination'],e['source'])
''')
(archive/'README.md').write_text('# Historical FPGA experiment archive\n\nNo files were deleted. manifest.json records original paths and verified file counts/sizes. Old experiments may require restoration before rebuilding.\n\nPreview: `python3 restore.py`\n\nRestore: `python3 restore.py --apply`\n\nCurrent clock control, controller_modes, burst_guard, buffered_guard, base sources, recovery images and production Python remain at their original paths.\n')
print(json.dumps({'archive':str(archive),'directories_moved':sum(Path(e['destination']).is_dir() for e in m['moves']),'entries_moved':len(eligible),'GiB_moved':round(sum(e['inventory']['bytes'] for e in m['moves'])/1024**3,3),'bitstreams_moved':sum(e['inventory']['bitstreams'] for e in m['moves']),'all_verified':all(e['verified'] for e in m['moves']),'skipped_tracked':len(skipped)},indent=2))
