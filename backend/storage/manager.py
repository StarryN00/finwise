"""
Storage instances for all entities - JSON file based
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Type, TypeVar, Any
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class JSONStore:
    """JSON file storage with CRUD operations"""

    def __init__(self, filename: str):
        self.file_path = DATA_DIR / filename
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save([])

    def _load(self) -> List[dict]:
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, data: List[dict]) -> None:
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _now(self) -> str:
        return datetime.utcnow().isoformat()

    def create(self, model: Type[T], **kwargs) -> T:
        data = kwargs
        data['id'] = data.get('id', str(uuid.uuid4()))
        data['created_at'] = data.get('created_at', self._now())
        data['updated_at'] = data.get('updated_at', self._now())
        records = self._load()
        records.append(data)
        self._save(records)
        return model(**data)

    def get_by_id(self, model: Type[T], record_id: str) -> Optional[T]:
        for record in self._load():
            if record.get('id') == record_id:
                return model(**record)
        return None

    def get_all(self, model: Type[T]) -> List[T]:
        return [model(**r) for r in self._load()]

    def filter(
        self, model: Type[T], limit: Optional[int] = None,
        offset: int = 0, order_by: Optional[str] = None,
        order_desc: bool = True, **filters
    ) -> List[T]:
        records = self._load()
        filtered = []
        for record in records:
            if all(record.get(k) == v for k, v in filters.items()):
                filtered.append(record)
        if order_by:
            filtered.sort(key=lambda x: x.get(order_by, ''), reverse=order_desc)
        if offset:
            filtered = filtered[offset:]
        if limit:
            filtered = filtered[:limit]
        return [model(**r) for r in filtered]

    def update(self, model: Type[T], record_id: str, **updates) -> Optional[T]:
        records = self._load()
        for i, record in enumerate(records):
            if record.get('id') == record_id:
                updates['updated_at'] = self._now()
                record.update(updates)
                self._save(records)
                return model(**record)
        return None

    def delete(self, record_id: str) -> bool:
        records = self._load()
        n = len(records)
        records = [r for r in records if r.get('id') != record_id]
        if len(records) < n:
            self._save(records)
            return True
        return False

    def count(self, **filters) -> int:
        if not filters:
            return len(self._load())
        return len(self.filter(object, **filters))

    def exists(self, **filters) -> bool:
        return self.count(**filters) > 0

    def first(self, model: Type[T], **filters) -> Optional[T]:
        results = self.filter(model, limit=1, **filters)
        return results[0] if results else None


# Per-entity store instances
enterprise_store = JSONStore('enterprises.json')
user_store = JSONStore('users.json')
invoice_store = JSONStore('invoices.json')
bank_transaction_store = JSONStore('bank_transactions.json')
financial_statement_store = JSONStore('financial_statements.json')
vat_filing_store = JSONStore('vat_filings.json')
health_report_store = JSONStore('health_reports.json')
import_batch_store = JSONStore('import_batches.json')
