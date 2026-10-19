"""CLI for the same safe orchestration used by the native plugin."""
import argparse
import json
from .core import inspect, preview, status
from .safety import ReaError


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hermes-rea-team', description='Pinned, static-only REA + optional three-role MiniMax team.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='Passive pin/runtime check; no auth resolution or paid calls.')
    for name in ('inspect', 'team', 'prepare'):
        p = sub.add_parser(name)
        p.add_argument('target')
        p.add_argument('--kind', choices=('binary', 'javascript'), required=True)
        p.add_argument('--question', required=name == 'team')
        if name != 'prepare':
            p.add_argument('--preview', action='store_true', help='No REA/model execution.')
    args = parser.parse_args(argv)
    if args.command == 'inspect' and args.question is not None:
        parser.error('inspect does not accept --question; use team')
    try:
        if args.command == 'status':
            result = status()
        elif args.command == 'prepare':
            result = preview(args.target, args.kind, args.question)
        else:
            result = inspect(args.target, args.kind, question=args.question if args.command == 'team' else None,
                             prepare=args.preview)
    except ReaError as exc:
        result = {'ok': False, 'error': exc.code}
    except Exception:
        result = {'ok': False, 'error': 'rea_integration_failed'}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('ok') else 1
