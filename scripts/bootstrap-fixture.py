#!/usr/bin/env python3
"""CLI-bootstrap only an explicitly isolated, authenticated synthetic fixture stack."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='seorap-fixture')
    parser.add_argument('--password-file', required=True, type=Path)
    parser.add_argument('--compose-files', default='docker-compose.yml,docker-compose.fixture.yml')
    args = parser.parse_args()
    if not any(marker in args.project for marker in ('fixture', 'packaging')):
        parser.error('refusing a project name that is not explicitly fixture/packaging scoped')
    command = ['docker', 'compose', '-p', args.project]
    for path in args.compose_files.split(','):
        command += ['-f', path]
    check = subprocess.run([*command, 'exec', '-T', 'app', 'python', '-c', "from app.config import load_settings; s=load_settings(); assert s.media_adapter=='fixture' and s.allow_fixture_urls and s.require_password and not s.allow_http_bootstrap, 'not an isolated protected fixture profile'"], capture_output=True, text=True)
    if check.returncode:
        raise SystemExit('Fixture profile verification failed; password setup was not attempted.')
    args.password_file.parent.mkdir(parents=True, exist_ok=True)
    if not args.password_file.exists():
        descriptor = os.open(args.password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(secrets.token_urlsafe(24))
    password = args.password_file.read_text().strip()
    if len(password) < 12:
        raise SystemExit('The test-only password file must contain at least 12 characters.')
    result = subprocess.run([*command, 'exec', '-T', 'app', 'python', '-m', 'app.cli', 'bootstrap'], input=password + '\n' + password + '\n', capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Fixture CLI bootstrap failed. No existing password was reset.')
    print('Protected fixture stack bootstrapped through the real CLI. Test password is stored only in the requested local file.')


if __name__ == '__main__':
    main()
