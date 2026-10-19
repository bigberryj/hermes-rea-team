"""Reviewed REA build pin and version-coupled Hermes runtime discovery."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from .safety import ReaError

ROOT = Path('/home/byron/projects/rea-review')
REA = ROOT / 'scripts/rea.mjs'
NODE = Path('/usr/sbin/node')
HERMES = Path('/home/byron/.hermes/hermes-agent')
REASONER = Path('/home/byron/.hermes/profiles/reasoner')
COMMIT = '1c2c2f1e78a74cdf5e4909ab8e775b090998a51f'
MANIFEST = Path(__file__).with_name('pins.json')


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReaError('pin_file_unavailable')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def check_pins() -> dict:
    pin = json.loads(MANIFEST.read_text())
    if pin['commit'] != COMMIT or pin['version'] != '6.7.0':
        raise ReaError('invalid_pin_manifest')
    # No Git subprocess/config/hooks; restrict symbolic HEAD to a canonical ref.
    git = ROOT / '.git'
    head = (git / 'HEAD').read_text().strip()
    if head.startswith('ref: '):
        ref = head[5:]
        if not re.fullmatch(r'refs/[a-zA-Z0-9_./-]+', ref) or '..' in ref:
            raise ReaError('invalid_git_ref')
        refpath = git / ref
        if refpath.is_file():
            head = refpath.read_text().strip()
        else:
            matches = [line.split()[0] for line in (git / 'packed-refs').read_text().splitlines()
                       if line and not line.startswith(('#', '^')) and line.split()[-1] == ref]
            head = matches[0] if len(matches) == 1 else ''
    if head != COMMIT:
        raise ReaError('rea_commit_changed')
    observed = set()
    for dirname in pin['directories']:
        for file in (ROOT / dirname).rglob('*'):
            if file.is_symlink():
                raise ReaError('rea_build_symlink')
            if file.is_file():
                observed.add(file.relative_to(ROOT).as_posix())
    observed.update(pin['root_files'])
    if observed != set(pin['files']):
        raise ReaError('rea_build_inventory_changed')
    for rel, expected in pin['files'].items():
        if digest(ROOT / rel) != expected:
            raise ReaError('rea_build_digest_changed')
    if digest(NODE.resolve()) != pin['node_sha256']:
        raise ReaError('node_runtime_changed')
    return {'version': pin['version'], 'commit': COMMIT, 'build_sha256': digest(MANIFEST),
            'rea': str(REA), 'node': str(NODE)}


def worker_command() -> list[str]:
    """Discover installed Python from its known launcher, never guess an env path.

    Uses the exact hermes_bootstrap entry from that installed launcher; no install,
    repair, launcher invocation, token reads or provider resolution at discovery.
    """
    pin = json.loads(MANIFEST.read_text())
    for rel, expected in pin['hermes_api_files'].items():
        if digest(HERMES / rel) != expected:
            raise ReaError('hermes_api_changed_reaudit_required')
    launcher = HERMES / '.hermes/bin/hermes'
    text = launcher.read_text()
    match = re.search(r'^exec (/[^\n ]+/python3) -I -c ', text, re.M)
    if not match or 'import hermes_bootstrap' not in text:
        raise ReaError('hermes_runtime_discovery_failed')
    python = Path(match[1])
    if not python.is_file() or not os.access(python, os.X_OK) or not REASONER.is_dir():
        raise ReaError('hermes_reasoner_runtime_unavailable')
    worker = Path(__file__).with_name('worker.py').resolve()
    bootstrap = ("import os,sys,runpy; "
                 "sys.path.insert(0," + repr(str(HERMES)) + "); "
                 "import hermes_bootstrap; "
                 "sys.argv=[" + repr(str(worker)) + "]+sys.argv[1:]; "
                 "runpy.run_path(" + repr(str(worker)) + ",run_name='__main__')")
    return [str(python), '-I', '-c', bootstrap]
