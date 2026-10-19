"""Static-only REA orchestration and one globally locked, three-role MiniMax review."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .pins import NODE, REA, REASONER, check_pins, worker_command
from .process import run_bounded
from .safety import ReaError, private_dir, snapshot, write_private, read_private_json, read_private_bytes
from .worker import ROLES

DATA = Path.home() / '.local/share/hermes-rea-team'
COMMANDS = {'binary': 'inspect-binary-layout', 'javascript': 'analyze-javascript-application'}
PROMPT_BYTES = 96000


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def scope() -> str:
    home = os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))
    return hashlib.sha256(home.encode()).hexdigest()[:16]


def validate_question(question):
    if not isinstance(question, str) or not question.strip() or len(question.encode()) > 4096:
        raise ReaError('question_required_max_4096_bytes')


def preview(target: str, kind: str, question: str | None = None) -> dict:
    if question is not None:
        validate_question(question)
    pin = check_pins()
    info = snapshot(target, kind)
    return {'ok': True, 'preview': True, 'paid_calls': 0, 'target_sha256': info['sha256'],
            'entries': info['entries'], 'bytes': info['bytes'], 'command': COMMANDS[kind],
            'provenance': pin, 'team': None if question is None else
            {'provider': 'minimax-oauth', 'model': 'MiniMax-M3', 'profile': 'reasoner',
             'roles': list(ROLES), 'max_tokens_per_role': 2048, 'tools': [], 'fallback': []}}


@contextmanager
def team_lock():
    private_dir(DATA)
    fd = os.open(DATA / 'team.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReaError('team_busy') from None
        yield
    finally:
        os.close(fd)


def public_result(directory: Path, report: dict) -> dict:
    # Deliberately do not return questions, evidence, stdout, stderr or model text.
    return {'ok': report['status'] == 'complete', 'run_id': directory.name,
            'status': report['status'], 'error': report.get('error'),
            'summary': 'Static evidence saved; no target execution. ' +
                       ('Three MiniMax role reports saved.' if len(report.get('roles', [])) == 3 else 'See private report for details.'),
            'roles_completed': len(report.get('roles', [])),
            'artifacts': {'directory': str(directory), 'report': str(directory / 'report.json'),
                          'evidence': str(directory / 'evidence.json'), 'provenance': str(directory / 'provenance.json')}}


def inspect(target: str, kind: str, *, question: str | None = None, prepare: bool = False) -> dict:
    if prepare:
        return preview(target, kind, question)
    if question is not None:
        validate_question(question)
        with team_lock():
            return _execute(target, kind, question)
    return _execute(target, kind, None)


def _execute(target: str, kind: str, question: str | None):
    pin = check_pins()
    # Preflight worker compatibility before spending time or quota on a team run.
    worker = worker_command() if question is not None else None
    runs = private_dir(private_dir(DATA / 'runs') / scope())
    work = private_dir(DATA / 'work')
    with tempfile.TemporaryDirectory(prefix='rea-', dir=work) as tmp:
        temp = Path(tmp)
        staged = temp / Path(target).name
        info = snapshot(target, kind, staged)
        identity = {'schema': 1, 'mode': 'team' if question is not None else 'inspect',
                    'target': target, 'target_sha256': info['sha256'], 'kind': kind,
                    'rea_pin': pin['build_sha256'], 'question': question,
                    'integration_version': '0.1.0', 'profile': 'reasoner' if question is not None else None}
        run_id = hashlib.sha256(canonical(identity).encode()).hexdigest()
        directory = runs / run_id
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if directory.is_symlink():
                raise ReaError('unsafe_artifact_path')
            file = directory / 'report.json'
            if not file.is_file() or file.is_symlink():
                raise ReaError('run_already_exists_incomplete')
            # A failed deterministic ID is not automatically retried (no surprise paid replay).
            cached = read_private_json(file)
            prior = read_private_json(directory / 'provenance.json', 1048576)
            if prior.get('identity') != identity or cached.get('status') not in {'complete', 'failed'}:
                raise ReaError('cached_artifact_contract_mismatch')
            if not isinstance(cached.get('roles'), list) or len(cached['roles']) > 3:
                raise ReaError('cached_artifact_contract_mismatch')
            if cached['status'] == 'complete':
                raw = read_private_bytes(directory / 'evidence.json', 2097152)
                if len(raw) > 2097152 or hashlib.sha256(raw).hexdigest() != prior.get('evidence_sha256'):
                    raise ReaError('cached_evidence_changed')
            return public_result(directory, cached)
        provenance = {'identity': identity, 'target_manifest': info, 'rea': pin,
                      'worker_route': 'native-AIAgent-resolver' if worker else None,
                      'limits': {'process_seconds': 45, 'output_bytes': 2097152,
                                 'role_seconds': 90, 'worker_wall_seconds': 120, 'prompt_bytes': PROMPT_BYTES}}
        write_private(directory / 'provenance.json', canonical(provenance))
        report = {'status': 'failed', 'roles': []}
        try:
            home = private_dir(temp / 'home')
            env = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                   'TMPDIR': str(home), 'XDG_CACHE_HOME': str(home / 'cache'),
                   'XDG_CONFIG_HOME': str(home / 'config'), 'XDG_DATA_HOME': str(home / 'data')}
            # No shell, user flags, HTTP/debug/injection commands or target execution.
            argv = [str(NODE), str(REA), COMMANDS[kind], str(staged),
                    '--format', 'json']
            if kind == 'javascript':
                argv += ['--max-heap-mb', '256', '--analysis-timeout-ms', '15000']
            result = run_bounded(argv, cwd=home, env=env, stdout=directory / 'evidence.json',
                                 stderr=directory / 'rea-stderr.txt')
            provenance['rea_process'] = result
            if result['timed_out']:
                raise ReaError('rea_timeout')
            if result['output_limited']:
                raise ReaError('rea_output_budget_exceeded')
            if result['returncode'] != 0:
                raise ReaError('rea_failed_binary_provider_unavailable_possible' if kind == 'binary' else 'rea_failed')
            raw = (directory / 'evidence.json').read_bytes()
            try:
                evidence = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ReaError('invalid_rea_json') from None
            if not isinstance(evidence, dict) or evidence.get('error') or evidence.get('ok') is False or not evidence.get('evidence_id'):
                raise ReaError('rea_error_or_invalid_evidence')
            evidence_hash = hashlib.sha256(raw).hexdigest()
            provenance['evidence_sha256'] = evidence_hash
            if question is not None:
                text = raw.decode('utf-8')
                bounded = raw[:PROMPT_BYTES].decode('utf-8', errors='ignore')
                shared = {'sha256': evidence_hash, 'full_bytes': len(raw),
                          'complete': len(raw) <= PROMPT_BYTES, 'json_text': bounded}
                provenance['model_evidence_sha256'] = hashlib.sha256(canonical(shared).encode()).hexdigest()
                for role in ROLES:
                    request = directory / (role + '-request.json')
                    output = directory / (role + '-report.json')
                    write_private(request, canonical({'role': role, 'question': question, 'evidence': shared}))
                    # Always use the EXISTING reasoner profile; never copy any auth/config.
                    model_env = {'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin',
                                 'HERMES_HOME': str(REASONER), 'LANG': 'C.UTF-8',
                                 'TMPDIR': str(home), 'PYTHONDONTWRITEBYTECODE': '1'}
                    done = run_bounded(worker + [str(request), str(output)], cwd=home, env=model_env,
                                       stdout=directory / (role + '-stdout.txt'),
                                       stderr=directory / (role + '-stderr.txt'), timeout=120, budget=65536)
                    if done['timed_out'] or done['output_limited'] or done['returncode'] != 0:
                        raise ReaError('native_worker_failed_or_timeout')
                    if not output.is_file() or output.is_symlink() or output.stat().st_size > 65536:
                        raise ReaError('invalid_worker_artifact')
                    data = json.loads(output.read_text())
                    if (data.get('ok') is not True or data.get('role') != role or
                        data.get('provider') != 'minimax-oauth' or data.get('model') != 'MiniMax-M3' or
                        data.get('tools') != [] or data.get('fallback') != [] or not data.get('text')):
                        raise ReaError('worker_contract_mismatch')
                    report['roles'].append({'role': role, 'artifact': str(output), 'provider': data['provider'],
                                            'model': data['model'], 'evidence_sha256': evidence_hash})
            report['status'] = 'complete'
        except ReaError as exc:
            report['error'] = exc.code
        except (OSError, ValueError, TypeError):
            report['error'] = 'artifact_or_protocol_error'
        finally:
            write_private(directory / 'provenance.json', canonical(provenance))
            write_private(directory / 'report.json', canonical(report))
        return public_result(directory, report)


def status() -> dict:
    try:
        pin = check_pins()
        worker_command()
        return {'ok': True, 'version': '0.1.0', 'rea': pin, 'paid_calls': 0,
                'team_route': 'native-AIAgent-resolver', 'team_live_verified': False,
                'binary_ready': False, 'binary_blocker': 'optional pwntools bridge dependencies not installed',
                'note': 'Static checks only; OAuth/model/REA execution not tested by status.'}
    except (ReaError, OSError, ValueError) as exc:
        return {'ok': False, 'paid_calls': 0, 'error': exc.code if isinstance(exc, ReaError) else 'preflight_failed'}
