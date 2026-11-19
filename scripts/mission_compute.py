"""Owned JSONL worker for the C++ mission algorithms."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess


class Compute:
    def __init__(self, binary: Path, model: Path):
        self.process = subprocess.Popen([str(binary), '--model', str(model)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def call(self, **request):
        if self.process.poll() is not None:
            raise RuntimeError('mission compute worker exited')
        self.process.stdin.write(json.dumps(request, allow_nan=False)+'\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('mission compute worker closed the connection')
        response = json.loads(line)
        if not response.get('ok'):
            raise ValueError(response.get('error', 'compute_failed'))
        return response

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()
