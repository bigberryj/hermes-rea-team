"""Fail-closed target validation and fd-relative, non-following snapshots (Linux)."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import stat

TARGET_ROOT = Path('/home/byron/projects/rea-targets')
MAX_FILE = 16 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_DEPTH = 32
SECRET = re.compile(r'(credential|private|password|passwd|secret|token|auth|key|id_rsa|id_ed25519)', re.I)
DENY = {'.git', '.ssh', '.aws', '.gnupg', '.npmrc', '.netrc', '.pypirc', 'shadow'}

class ReaError(Exception):
    """Only constant, content-free messages may cross the public tool boundary."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

def sensitive(name: str) -> bool:
    return name.lower().startswith('.env') or name.lower() in DENY or bool(SECRET.search(name)) or name.lower().endswith(('.pem', '.key', '.p12', '.pfx', '.jks', '.keystore'))

def private_dir(path: Path) -> Path:
    """Never traverse symlinks in artifact roots; enforce owned private leaf dirs."""
    path = path.absolute()
    cur = Path(path.anchor)
    for part in path.parts[1:]:
        cur /= part
        try:
            cur.mkdir(mode=0o700)
        except FileExistsError:
            pass
        st = cur.lstat()
        if not stat.S_ISDIR(st.st_mode):
            raise ReaError('unsafe_artifact_path')
    if path.stat().st_uid != os.getuid():
        raise ReaError('unsafe_artifact_owner')
    path.chmod(0o700)
    return path

def write_private(path: Path, data: str | bytes):
    raw = data.encode('utf-8') if isinstance(data, str) else data
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as f:
            f.write(raw)
    finally:
        os.close(fd)

def read_private_bytes(path: Path, limit: int = 65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid()
                or st.st_mode & 0o077 or st.st_size > limit):
            raise ReaError('unsafe_artifact_file')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            raise ReaError('artifact_budget_exceeded')
        return data
    finally:
        os.close(fd)


def read_private_json(path: Path, limit: int = 65536):
    return json.loads(read_private_bytes(path, limit))


def _open_absolute(path: Path) -> int:
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise

def snapshot(target: str, kind: str, destination: Path | None = None) -> dict:
    """Validate every entry including ignored files; never execute target material.

    Openat + O_NOFOLLOW prevents traversal races. Copies are re-statted before/after
    reading and hashed. REA only receives this private snapshot, never original paths.
    destination=None validates/hashes without writing (prepare/preview).
    """
    if kind not in {'binary', 'javascript'}:
        raise ReaError('invalid_kind')
    if not isinstance(target, str) or not target.startswith('/') or '\x00' in target:
        raise ReaError('absolute_target_required')
    if any(x in {'.', '..', ''} for x in target.split('/')[1:]):
        raise ReaError('noncanonical_target')
    path = Path(target)
    try:
        rel = path.relative_to(TARGET_ROOT)
    except ValueError:
        raise ReaError('target_outside_allowlist') from None
    if not rel.parts or any(sensitive(x) for x in rel.parts):
        raise ReaError('sensitive_or_root_target')
    records = []
    total = entries = 0
    def walk(fd, name, out, depth):
        nonlocal total, entries
        entries += 1
        if depth > MAX_DEPTH or entries > MAX_ENTRIES:
            raise ReaError('tree_budget_exceeded')
        before = os.fstat(fd)
        if stat.S_ISDIR(before.st_mode):
            if out is not None:
                out.mkdir(mode=0o700)
            records.append({'path': name, 'type': 'directory'})
            for child in sorted(os.listdir(fd)):
                if sensitive(child):
                    raise ReaError('sensitive_filename')
                if child.lower().endswith(('.asar', '.zip', '.tar', '.tgz', '.gz', '.7z', '.rar', '.jar', '.deb', '.rpm')):
                    raise ReaError('packed_input_rejected')
                # Opening FIFO/device must never block; inspect before opening too.
                s = os.stat(child, dir_fd=fd, follow_symlinks=False)
                if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
                    raise ReaError('symlink_or_special_file')
                childfd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    walk(childfd, name + '/' + child, out / child if out else None, depth + 1)
                finally:
                    os.close(childfd)
        elif stat.S_ISREG(before.st_mode):
            if before.st_nlink != 1:
                raise ReaError('hardlink_rejected')
            if before.st_size > MAX_FILE:
                raise ReaError('file_budget_exceeded')
            total += before.st_size
            if total > MAX_TREE:
                raise ReaError('tree_budget_exceeded')
            digest = hashlib.sha256()
            written = 0
            dest = None
            try:
                if out is not None:
                    dest = os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb')
                while True:
                    block = os.read(fd, 65536)
                    if not block:
                        break
                    written += len(block)
                    if written > before.st_size or written > MAX_FILE:
                        raise ReaError('target_changed')
                    digest.update(block)
                    if dest:
                        dest.write(block)
            finally:
                if dest:
                    dest.close()
            after = os.fstat(fd)
            if (written, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ReaError('target_changed')
            records.append({'path': name, 'type': 'file', 'bytes': written, 'sha256': digest.hexdigest()})
        else:
            raise ReaError('symlink_or_special_file')
    try:
        fd = _open_absolute(path)
        try:
            mode = os.fstat(fd).st_mode
            if kind == 'binary' and not stat.S_ISREG(mode):
                raise ReaError('binary_requires_file')
            # Reject packed ASAR/archive inputs: their hidden entries cannot be screened.
            if kind == 'javascript' and not stat.S_ISDIR(mode):
                raise ReaError('javascript_requires_unpacked_directory')
            walk(fd, path.name, destination, 0)
        finally:
            os.close(fd)
    except OSError:
        raise ReaError('target_unreadable_or_symlink') from None
    serial = json.dumps(records, sort_keys=True, separators=(',', ':')).encode()
    return {'target': target, 'kind': kind, 'files': records, 'bytes': total, 'entries': entries,
            'sha256': hashlib.sha256(serial).hexdigest()}
