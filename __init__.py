"""Hermes public native plugin entrypoint (no MCP, installer or global config changes)."""
import json
from pathlib import Path
from .rea_team.core import inspect
from .rea_team.safety import ReaError


def register(ctx):
    if hasattr(ctx, 'register_skill'):
        ctx.register_skill(name='rea-team', path=Path(__file__).parent / 'skills/rea-team/SKILL.md',
                           description='Static-only REA investigation and bounded MiniMax team.')
    for name, is_team in (('rea_inspect', False), ('rea_team', True)):
        properties = {
            'target': {'type': 'string', 'description': 'Explicit absolute path under /home/byron/projects/rea-targets; no symlinks/secrets/archives.'},
            'kind': {'type': 'string', 'enum': ['binary', 'javascript']},
            'preview': {'type': 'boolean', 'description': 'Validate and preview only; no Node or model calls.', 'default': False},
        }
        if is_team:
            properties['question'] = {'type': 'string', 'description': 'Review question; team sends bounded static evidence to three MiniMax roles.', 'maxLength': 4096}
        schema = {'name': name, 'description': (
            'STATIC ONLY: inspect local staged input with pinned REA. Return content-free summary and private artifact paths. '
            + ('Then review the same evidence using architecture/security/verification MiniMax-M3 roles via the reasoner profile; paid calls unless preview=true.' if is_team else 'No paid model calls.')
        ), 'parameters': {'type': 'object', 'properties': properties,
                          'required': ['target', 'kind'] + (['question'] if is_team else []), 'additionalProperties': False}}
        def handler(args, _team=is_team, **kwargs):
            try:
                allowed = {'target', 'kind', 'preview'} | ({'question'} if _team else set())
                if not isinstance(args, dict) or set(args) - allowed or not isinstance(args.get('preview', False), bool):
                    raise ReaError('invalid_arguments')
                if _team and not isinstance(args.get('question'), str):
                    raise ReaError('question_required_max_4096_bytes')
                result = inspect(args.get('target', ''), args.get('kind', ''),
                                 question=args.get('question') if _team else None, prepare=args.get('preview', False))
            except ReaError as exc:
                result = {'ok': False, 'error': exc.code}
            except Exception:
                result = {'ok': False, 'error': 'rea_integration_failed'}
            return json.dumps(result)
        ctx.register_tool(name=name, toolset='rea', schema=schema, handler=handler,
                          check_fn=lambda: True)
