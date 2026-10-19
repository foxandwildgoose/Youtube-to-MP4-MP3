#!/usr/bin/env python3
"""Create synthetic media for an explicitly isolated fixture deployment only."""
from __future__ import annotations
import argparse
import importlib.util
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--container-root', default='/fixtures')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('output must be absent or empty; existing fixtures are never overwritten')
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / 'backend'))
    spec = importlib.util.spec_from_file_location('seorap_fixture_factory', ROOT / 'backend/tests/conftest.py')
    fixtures = importlib.util.module_from_spec(spec)
    # conftest imports the app's global instance. Its import-time state belongs
    # only to this synthetic generator, never the operator's personal library.
    previous_data = os.environ.get('DATA_DIR')
    with tempfile.TemporaryDirectory(prefix='seorap-fixture-import-') as import_state:
        os.environ['DATA_DIR'] = import_state
        try:
            spec.loader.exec_module(fixtures)
        except ImportError as error:
            raise SystemExit('Install backend/requirements-test.txt first: ' + str(error)) from error
        finally:
            if previous_data is None:
                os.environ.pop('DATA_DIR', None)
            else:
                os.environ['DATA_DIR'] = previous_data
    class Factory:
        def mktemp(self, name):
            path = output / name
            path.mkdir()
            return path
    media = fixtures.media_root.__wrapped__(Factory())
    catalog = fixtures.write_catalog(output, Path(args.container_root) / media.name)
    for path in [output, *output.rglob('*')]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    print(f'Synthetic fixture catalog: {catalog}; mount read-only at {args.container_root}. No provider contacted.')


if __name__ == '__main__':
    main()
