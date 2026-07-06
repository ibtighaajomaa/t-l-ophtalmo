#!/usr/bin/env python3
"""
Find and optionally remove duplicate DICOM-SEG series in Orthanc.

Usage:
  python orthanc_cleanup_duplicates.py [--apply]

By default runs in dry-run mode and prints candidate duplicate groups.
With --apply it will delete all but one series in each duplicate group (keeps the largest by instance count).
"""
import os
import requests
import sys
from collections import defaultdict

ORTHANC = os.environ.get('ORTHANC_URL', 'http://orthanc-container:8042')


def list_seg_series():
    series = requests.get(f"{ORTHANC}/series", timeout=30).json()
    segs = []
    for sid in series:
        try:
            sr = requests.get(f"{ORTHANC}/series/{sid}", timeout=10)
            if sr.status_code != 200:
                continue
            s = sr.json()
            if s.get('MainDicomTags', {}).get('Modality') != 'SEG':
                continue
            desc = s.get('MainDicomTags', {}).get('SeriesDescription')
            study = s.get('MainDicomTags', {}).get('StudyInstanceUID')
            insts = s.get('Instances', []) or []
            refs = []
            if insts:
                tags = requests.get(f"{ORTHANC}/instances/{insts[0]}/tags?simplify", timeout=10).json()
                refs = [item.get('SeriesInstanceUID') for item in tags.get('ReferencedSeriesSequence', []) if item.get('SeriesInstanceUID')]
            key = (study, desc, tuple(sorted(refs)))
            segs.append({'sid': sid, 'study': study, 'desc': desc, 'refs': tuple(sorted(refs)), 'n_instances': len(insts)})
        except Exception:
            continue
    return segs


def find_duplicates(segs):
    groups = defaultdict(list)
    for s in segs:
        groups[(s['study'], s['desc'], s['refs'])].append(s)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    return dups


def delete_series(sid):
    resp = requests.delete(f"{ORTHANC}/series/{sid}", timeout=30)
    return resp.status_code


def main():
    apply_mode = '--apply' in sys.argv
    segs = list_seg_series()
    dups = find_duplicates(segs)
    if not dups:
        print('No duplicate SEG groups found.')
        return 0

    print(f'Found {len(dups)} duplicate groups:')
    for key, items in dups.items():
        study, desc, refs = key
        print('\nGroup:')
        print('  StudyUID:', study)
        print('  SeriesDescription:', desc)
        print('  ReferencedSeriesUIDs:', refs)
        for it in items:
            print(f"   - {it['sid']}  instances={it['n_instances']}")

        # decide which to keep: keep series with max instances
        keep = max(items, key=lambda x: x['n_instances'])
        to_delete = [it for it in items if it['sid'] != keep['sid']]
        print(f"  Keeping: {keep['sid']} (instances={keep['n_instances']})")
        if to_delete:
            print('  Candidates for deletion:')
            for it in to_delete:
                print(f"    -> {it['sid']} (instances={it['n_instances']})")
            if apply_mode:
                for it in to_delete:
                    code = delete_series(it['sid'])
                    if code in (200, 204):
                        print(f"    Deleted {it['sid']}")
                    else:
                        print(f"    Failed to delete {it['sid']}: HTTP {code}")
        else:
            print('  No series to delete in this group')

    return 0


if __name__ == '__main__':
    sys.exit(main())
