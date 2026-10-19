"""Network-free preview restart and bounded process-log regression harness."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module('preview_runtime', 'preview-runtime.py')
logger = module('run_logged', 'run-logged.py')


class PreviewRuntimeTests(unittest.TestCase):
    def test_independent_api_worker_and_web_recovery_and_repeatability(self):
        for api, worker in ((True, True), (True, False), (False, True), (False, False)):
            with self.subTest(api=api, worker=worker):
                alive = {name for name, healthy in [('api', api), ('worker', worker), ('web', True)] if healthy}
                spawned = []
                states = {name: 'ready' if name in alive else 'stopped' for name in ('api', 'worker', 'web')}
                def launch(name):
                    self.assertNotIn(name, alive)
                    alive.add(name)
                    spawned.append(name)
                runtime.ensure_components(states, lambda name: name in alive, launch)
                runtime.ensure_components(states, lambda name: name in alive, launch)
                self.assertEqual(set(spawned), {'api', 'worker'} - ({'api'} if api else set()) - ({'worker'} if worker else set()))
                self.assertEqual(len(spawned), len(set(spawned)))

    def test_held_but_stale_worker_never_starts_second_owner(self):
        spawned = []
        runtime.ensure_components({'api': 'ready', 'worker': 'degraded', 'web': 'ready'}, lambda _: False, spawned.append)
        self.assertEqual(spawned, [])

    def test_pid_file_is_not_worker_liveness(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'worker.pid').write_text(str(os.getpid()))
            self.assertEqual(runtime.worker_state(data), 'stopped')

    def test_real_worker_lock_heartbeat_and_worker_only_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'state').mkdir()
            code = """import datetime,fcntl,os,pathlib,sqlite3,sys,time
root=pathlib.Path(sys.argv[1]); handle=(root/'worker.lock').open('w+')
fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB); handle.write(str(os.getpid())); handle.flush()
conn=sqlite3.connect(root/'state/app.db'); conn.execute('CREATE TABLE IF NOT EXISTS worker_heartbeat(id INTEGER PRIMARY KEY, beat_at TEXT, pid INTEGER)')
conn.execute('INSERT OR REPLACE INTO worker_heartbeat VALUES(1,?,?)',(datetime.datetime.now(datetime.timezone.utc).isoformat(),os.getpid())); conn.commit();conn.close()
print('ready',flush=True);time.sleep(20)
"""
            children = []
            def launch(name):
                self.assertEqual(name, 'worker')
                child = subprocess.Popen([sys.executable, '-c', code, str(data), 'app.worker'], stdout=subprocess.PIPE, text=True)
                children.append(child)
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            try:
                launch('worker')
                self.assertEqual(runtime.worker_state(data), 'ready')
                # The API remains healthy while its independent worker exits.
                children[0].terminate(); children[0].wait(timeout=3)
                self.assertEqual(runtime.worker_state(data), 'stopped')
                runtime.ensure_components({'api': 'ready', 'worker': runtime.worker_state(data), 'web': 'ready'}, lambda _: False, launch)
                self.assertEqual(len(children), 2)
                self.assertEqual(runtime.worker_state(data), 'ready')
                spawned = []
                runtime.ensure_components({'api': 'stopped', 'worker': runtime.worker_state(data), 'web': 'ready'}, lambda _: False, spawned.append)
                self.assertEqual(spawned, ['api'])
                runtime.ensure_components({'api': 'ready', 'worker': runtime.worker_state(data), 'web': 'ready'}, lambda _: False, spawned.append)
                self.assertEqual(spawned, ['api'])
            finally:
                for child in children:
                    if child.poll() is None:
                        child.terminate(); child.wait(timeout=3)
                    child.stdout.close()

    def test_foreign_or_reused_pid_does_not_establish_runner_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            import json, os
            record = Path(folder) / 'runner.json'
            record.write_text(json.dumps({'pid': os.getpid(), 'start_ticks': logger.start_ticks(os.getpid())}))
            self.assertFalse(runtime.owned_runner(record))
            record.write_text(json.dumps({'pid': os.getpid(), 'start_ticks': 'stale-pid'}))
            self.assertFalse(runtime.owned_runner(record))

    def test_live_log_rotation_bounds_current_and_two_backups(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'worker.log'
            # Old unbounded logs are normalized on the first collection.
            log.write_bytes(b'old' * 2000)
            logger.append_bounded(log, b'A' * 9000 + b'last diagnostic\n', 1024)
            files = sorted(Path(folder).glob('worker.log*'))
            self.assertEqual(len(files), 3)
            self.assertLessEqual(sum(path.stat().st_size for path in files), 3 * 1024)
            self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
            self.assertTrue(log.read_bytes().endswith(b'last diagnostic\n'))

    def test_logger_setup_failure_reaps_spawned_child(self):
        import signal
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            bad_record = Path(folder) / 'directory-not-a-file'
            bad_record.mkdir()
            launched = []
            real_popen = subprocess.Popen
            def spawn(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                launched.append(child)
                return child
            handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
            try:
                with patch.object(sys, 'argv', ['run-logged.py', '--log', str(Path(folder) / 'failure.log'), '--pid', str(bad_record), '--', sys.executable, '-c', 'import time;time.sleep(60)']), patch.object(logger.subprocess, 'Popen', side_effect=spawn):
                    with self.assertRaises(IsADirectoryError):
                        logger.main()
                self.assertEqual(len(launched), 1)
                self.assertIsNotNone(launched[0].poll())
                self.assertFalse(Path(f'/proc/{launched[0].pid}').exists())
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
                for child in launched:
                    if child.poll() is None:
                        child.terminate(); child.wait(timeout=5)

    def test_foreign_http200_listener_is_not_preview_readiness(self):
        import http.server, threading
        class Foreign(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'foreign server')
            def log_message(self, *_args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Foreign)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                url = f'http://127.0.0.1:{server.server_port}/'
                self.assertTrue(runtime.http_ready(url))
                self.assertFalse(runtime.component_ready('api', url, Path(folder)))
                spawned = []
                runtime.ensure_components({'api': 'foreign', 'web': 'foreign', 'worker': 'ready'}, lambda _: False, spawned.append)
                self.assertEqual(spawned, [])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_stop_helper_stops_only_owned_runner_and_child(self):
        import json, time
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'state').mkdir()
            record = data / 'state/preview-api.json'
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run-logged.py'), '--log', str(data / 'api.log'), '--pid', str(record), '--max-bytes', '256', '--', sys.executable, '-c', "import time; print('owned',flush=True); time.sleep(60)"], start_new_session=True)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not record.exists():
                    time.sleep(.02)
                self.assertTrue(runtime.owned_runner(record))
                child_pid = json.loads(record.read_text())['child_pid']
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/stop-preview.py')], env={**os.environ, 'DATA_DIR': folder}, timeout=15, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                process.wait(timeout=3)
                self.assertEqual(process.returncode, 143)
                self.assertFalse(record.exists())
                self.assertFalse(Path(f'/proc/{child_pid}').exists())
            finally:
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=5)

    def test_process_logger_executes_command_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'api.log'
            pid = Path(folder) / 'api.json'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/run-logged.py'), '--log', str(log), '--pid', str(pid), '--max-bytes', '256', '--', sys.executable, '-c', "print('x' * 2000); print('controlled failure'); raise SystemExit(7)"], timeout=15)
            self.assertEqual(result.returncode, 7)
            self.assertFalse(pid.exists())
            self.assertTrue(log.read_text().endswith('controlled failure\n'))
            self.assertLessEqual(sum(path.stat().st_size for path in Path(folder).glob('api.log*')), 768)


if __name__ == '__main__':
    unittest.main()
