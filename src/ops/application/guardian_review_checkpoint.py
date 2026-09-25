"""Resume completed retrospective work only for the same facts, settings and code."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def review_fingerprint(cfg: dict, facts: dict) -> str:
    from src.ops.application.guardian_review_agent import review_output_contract, review_system
    from src.ops.application.guardian_memory import MEMORY_NOTE

    snapshot = deepcopy(facts)
    for clock in ('created_at', 'reference_pool_as_of', 'previous_reviews_as_of'):
        snapshot.pop(clock, None)
    for field in ('risk_contracts', 'current_position_policy'):
        if isinstance(snapshot.get(field), dict):
            snapshot[field].pop('as_of', None)
    for position in (snapshot.get('risk_contracts') or {}).get('positions', []):
        for plan in position.get('risk_plans', []):
            if plan.get('ended_at') == facts.get('created_at'):
                # Derived expiry checks restamp ended_at; status and contract still bind the resume.
                plan.pop('ended_at', None)
    root = Path(__file__).parent
    code = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
            ('guardian_review_agent.py', 'guardian_review_prompts.py', 'guardian_weekly_prompt.py',
             'guardian_review_checkpoint.py', 'guardian_output.py', 'report_writing.py')}
    # Bind the effective instructions, including shared imports and nested schemas.
    # A checkpoint can contain an experience repair, but never a completed forward plan.
    prompts = {stage: review_system(cfg, facts.get('period', 'daily'), review_output_contract(stage)[1], stage=stage)
               for stage in ('retrospective', 'experience')}
    return hashlib.sha256(json.dumps({'facts': snapshot, 'config': cfg, 'code': code,
                                    'prompts': prompts, 'memory_note': MEMORY_NOTE},
                                    sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
