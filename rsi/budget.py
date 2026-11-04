"""Conservative project budget reservations; no remote jobs without a reservation.

Reservations remain charged against the planning budget after success or failure.
This avoids treating runtime estimates as authoritative billing measurements.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import math
from pathlib import Path
import uuid

from .config import ROOT


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.policy_path = self.root / 'config/budget.json'
        self.ledger_path = self.root / 'budget/ledger.json'

    @contextmanager
    def locked(self):
        lock = self.root / '.cache/budget.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read(self):
        return json.loads(self.policy_path.read_text()), json.loads(self.ledger_path.read_text())

    def _write(self, ledger):
        temporary = self.ledger_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(ledger, indent=2) + '\n')
        temporary.replace(self.ledger_path)

    def reserve(self, stage, amount=5.0):
        with self.locked():
            policy, ledger = self._read()
            if not math.isfinite(amount) or not 0 < amount <= policy['max_stage_reservation']:
                raise ValueError('Invalid stage reservation')
            committed = sum(item['reserved_usd'] for item in ledger['reservations'])
            if committed + amount + policy['overhead_reserve'] > policy['project_cap']:
                raise BudgetExceeded('Project budget exhausted; no remote job started')
            for prefix, cap in policy.get('prefix_reservation_caps', {}).items():
                if stage.startswith(prefix):
                    subtotal = sum(x['reserved_usd'] for x in ledger['reservations'] if x['stage'].startswith(prefix))
                    if subtotal + amount > cap:
                        raise BudgetExceeded(f'Study reservation envelope exhausted for {prefix}')
            item = {'id': uuid.uuid4().hex, 'stage': stage, 'reserved_usd': amount,
                    'status': 'reserved', 'started_at': datetime.now(timezone.utc).isoformat()}
            ledger['reservations'].append(item)
            self._write(ledger)
            return item['id']

    def finish(self, reservation_id, status, details=None):
        if status not in {'completed', 'failed', 'interrupted'}:
            raise ValueError('Invalid status')
        with self.locked():
            _, ledger = self._read()
            item = next(item for item in ledger['reservations'] if item['id'] == reservation_id)
            if item['status'] != 'reserved':
                raise ValueError('Reservation has already been finalized')
            item.update(status=status, finished_at=datetime.now(timezone.utc).isoformat(),
                        details=details or {})
            self._write(ledger)

    def summary(self):
        with self.locked():
            policy, ledger = self._read()
        committed = sum(item['reserved_usd'] for item in ledger['reservations'])
        return {'project_cap_usd': policy['project_cap'], 'reserved_for_jobs_usd': committed,
                'overhead_reserve_usd': policy['overhead_reserve'],
                'available_for_jobs_usd': policy['project_cap'] - policy['overhead_reserve'] - committed,
                'invoice_total_usd': None}
