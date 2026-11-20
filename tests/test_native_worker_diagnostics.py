"""Linux supervisor safety checks using tiny synthetic children, never a solver."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == 'linux', 'native supervisor runs inside Linux/WSL')
class DiagnosticSupervisorTests(unittest.TestCase):
    def launch(self, directory, body):
        root = Path(__file__).resolve().parents[1]
        binary = directory / 'synthetic binary with spaces'
        binary.write_text('#!/usr/bin/env python3\nimport json, sys, time\njson.load(sys.stdin)\n' + body)
        binary.chmod(0o700)
        job = directory / 'job'
        command = [sys.executable, str(root / 'scripts/native_worker.py'), str(job),
                   '--binary', str(binary), '--diagnostics']
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return process, job, binary

    def test_explicit_binary_hash_metrics_budget_and_reap(self):
        with tempfile.TemporaryDirectory(prefix='pokerlab-worker-test-') as name:
            process, job, binary = self.launch(Path(name), 'time.sleep(.2)\nprint(json.dumps({"synthetic": True}))\n')
            out, err = process.communicate(json.dumps({'memory_budget_mb': 256}), timeout=10)
            self.assertEqual(process.returncode, 0, err)
            result = json.loads(out)
            self.assertTrue(result['synthetic'])
            worker = json.loads((job / 'worker.json').read_text())
            self.assertEqual(worker['state'], 'completed')
            self.assertEqual(worker['binary_sha256'], hashlib.sha256(binary.read_bytes()).hexdigest())
            self.assertLessEqual(worker['limit_bytes'], 256 * 1024**2)
            self.assertTrue(worker['process_reaped'])
            self.assertEqual(worker['exit_code'], 0)
            self.assertGreaterEqual(worker['diagnostic_sample_count'], 1)
            self.assertGreater(worker['final_native_usage']['max_rss_bytes'], 0)
            self.assertGreaterEqual(worker['final_native_usage']['user_cpu_seconds'], 0)
            self.assertTrue((job / 'native-metrics.jsonl').exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(worker['native_pid'], 0)

    def test_cancel_reaps_the_synthetic_process_group(self):
        with tempfile.TemporaryDirectory(prefix='pokerlab-worker-cancel-') as name:
            process, job, _ = self.launch(Path(name), 'while True: time.sleep(.05)\n')
            process.stdin.write(json.dumps({'memory_budget_mb': 256}))
            process.stdin.close()
            process.stdin = None
            try:
                deadline = time.monotonic() + 10
                while not (job / 'worker.json').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((job / 'worker.json').exists())
                (job / 'cancel').touch()
                process.communicate(timeout=10)
                worker = json.loads((job / 'worker.json').read_text())
                self.assertEqual(worker['state'], 'cancelled')
                self.assertTrue(worker['process_reaped'])
                self.assertNotEqual(process.returncode, 0)
                self.assertIn('final_native_usage', worker)
                with self.assertRaises(ProcessLookupError):
                    os.kill(worker['native_pid'], 0)
            finally:
                if process.poll() is None:
                    (job / 'cancel').touch()
                    try:
                        process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        status_file = job / 'worker.json'
                        if status_file.exists():
                            pid = json.loads(status_file.read_text()).get('native_pid')
                            if pid:
                                try:
                                    os.killpg(pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                        process.kill()
                        process.communicate()

    def test_failed_native_is_reaped_and_reported(self):
        with tempfile.TemporaryDirectory(prefix='pokerlab-worker-failure-') as name:
            process, job, _ = self.launch(Path(name), 'print("fixture failure", file=sys.stderr)\nsys.exit(7)\n')
            _, err = process.communicate(json.dumps({'memory_budget_mb': 256}), timeout=10)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('fixture failure', err)
            worker = json.loads((job / 'worker.json').read_text())
            self.assertEqual(worker['state'], 'failed')
            self.assertEqual(worker['exit_code'], 7)
            self.assertTrue(worker['process_reaped'])
            self.assertIn('final_native_usage', worker)


if __name__ == '__main__':
    unittest.main()
