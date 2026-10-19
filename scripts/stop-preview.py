#!/usr/bin/env python3
"""Stop only this checkout's identified preview runners and their owned groups."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('components', nargs='*', metavar='COMPONENT')
    args = parser.parse_args()
    if any(name not in ('api', 'worker', 'web') for name in args.components):
        parser.error('components must be api, worker or web')
    spec = importlib.util.spec_from_file_location('seorap_preview_runtime', ROOT / 'scripts/preview-runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    data = Path(os.environ.get('DATA_DIR', ROOT / 'data')).resolve()
    records = [data / 'state' / f'preview-{name}.json' for name in (args.components or ['api', 'worker', 'web'])]
    for record in records:
        if runtime.owned_runner(record):
            try:
                os.kill(int(json.loads(record.read_text())['pid']), signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if not any(runtime.owned_runner(record) for record in records):
            return 0
        time.sleep(0.2)
    raise SystemExit('An owned runner did not stop within 25 seconds. Inspect bounded logs before further action.')


if __name__ == '__main__':
    raise SystemExit(main())
