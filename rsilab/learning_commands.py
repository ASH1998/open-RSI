"""Offline deserialization helpers for verified-learning CLI operations."""
from .core import digest
from .learning import LearningPolicy,AttemptLedger,select_verified_targets


def select_from_saved_ledger(payload,excluded_tasks):
    """Replay an immutable ledger and recheck excluded split identities."""
    policy=LearningPolicy(**payload['policy'])
    ledger=AttemptLedger(payload['train_tasks'],excluded_tasks=excluded_tasks,policy=policy)
    for saved in payload['attempts']:
        actual=ledger.add(saved['record'],source_run_id=saved['source_run_id'],attempt_index=saved['attempt_index'],
                          attempt_kind=saved['attempt_kind'],parent_attempt_id=saved['parent_attempt_id'])
        if actual!=saved:raise ValueError('Saved attempt lineage/hash mismatch')
    if digest(ledger.to_dict())!=digest(payload):raise ValueError('Saved ledger identity mismatch')
    return select_verified_targets(ledger)
