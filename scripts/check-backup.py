#!/usr/bin/env python3
"""Non-destructive backup/restore smoke using only a temporary synthetic library."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.config import load_settings
from app.db import init_db
with tempfile.TemporaryDirectory(prefix='seorap-backup-') as temp:
    base=Path(temp);source=base/'original';restored=base/'restored'
    previous=os.environ.get('DATA_DIR');os.environ['DATA_DIR']=str(source)
    try: settings=load_settings()
    finally:
        if previous is None:os.environ.pop('DATA_DIR',None)
        else:os.environ['DATA_DIR']=previous
    conn=init_db(settings)
    conn.execute("INSERT INTO preferences(id,language,theme,mp3_bitrate,updated_at) VALUES(1,'ko','dark',320,'2026-01-01')")
    conn.execute("INSERT INTO operator VALUES(1,'synthetic-backup-fixture','2026-01-01','2026-01-01')")
    conn.close()
    media=source/'files'/'synthetic-kept'/'output.bin';media.parent.mkdir(parents=True)
    media.write_bytes(b'Synthetic backup payload, not validated media.\n'*100)
    backup=base/'snapshot.db'
    result=subprocess.run([sys.executable,str(root/'scripts/backup.py'),str(backup)],env={**os.environ,'DATA_DIR':str(source)},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    (restored/'state').mkdir(parents=True)
    shutil.copy2(backup,restored/'state/app.db')
    shutil.copytree(source/'files',restored/'files')
    with sqlite3.connect(restored/'state/app.db') as check:
        assert check.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert check.execute('SELECT mp3_bitrate,theme FROM preferences').fetchone()==(320,'dark')
        assert check.execute('SELECT password_hash FROM operator').fetchone()[0]=='synthetic-backup-fixture'
        assert check.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]>=2
    assert hashlib.sha256(media.read_bytes()).digest()==hashlib.sha256((restored/'files/synthetic-kept/output.bin').read_bytes()).digest()
print(json.dumps({'sqlite_backup_restore':'passed','media_copy_hash':'passed','user_data_touched':False}))
