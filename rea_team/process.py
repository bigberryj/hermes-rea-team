"""Bounded subprocess streaming, process-group cancellation, no shell."""
from __future__ import annotations
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from .safety import ReaError

OUTPUT_BUDGET = 2 * 1024 * 1024

def run_bounded(argv: list[str], *, cwd: Path, env: dict[str, str], stdout: Path,
                stderr: Path, timeout: float = 45, budget: int = OUTPUT_BUDGET) -> dict:
    if timeout <= 0 or budget <= 0:
        raise ReaError('invalid_process_limits')
    fds = []
    proc = None
    sel = selectors.DefaultSelector()
    result = {'returncode': None, 'timed_out': False, 'output_limited': False, 'bytes': 0}
    def kill():
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        for path in (stdout, stderr):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            fds.append(os.fdopen(fd, 'wb'))
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, close_fds=True)
        start = time.monotonic()
        for pipe, dest in zip((proc.stdout, proc.stderr), fds):
            if pipe is None:
                raise ReaError('process_pipe_unavailable')
            os.set_blocking(pipe.fileno(), False)
            sel.register(pipe, selectors.EVENT_READ, dest)
        while sel.get_map():
            if time.monotonic() - start >= timeout:
                result['timed_out'] = True
                kill()
                break
            for key, _ in sel.select(min(0.1, max(0, timeout - (time.monotonic() - start)))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                remaining = budget - result['bytes']
                key.data.write(chunk[:remaining])
                result['bytes'] += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    result['output_limited'] = True
                    kill()
                    break
            if result['output_limited']:
                break
        # Descendants may retain pipes after leader exits; never wait unbounded.
        remaining_time = max(0.01, timeout - (time.monotonic() - start))
        try:
            proc.wait(timeout=remaining_time)
        except subprocess.TimeoutExpired:
            result['timed_out'] = True
            kill()
            proc.wait(timeout=5)
        result['returncode'] = proc.returncode
        return result
    except OSError:
        raise ReaError('process_launch_failed') from None
    finally:
        kill()  # also reap/kill descendants on success, exception, KeyboardInterrupt
        if proc:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    pipe.close()
        sel.close()
        for f in fds:
            f.close()
