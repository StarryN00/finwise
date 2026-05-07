"""
JSON file-based storage layer for CRUD operations
Provides a simple file-based persistence layer using JSON files
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, TypeVar, Type
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)


class JSONStore:
    """
    A simple JSON file storage class for CRUD operations.
    Each collection is stored in a separate JSON file.
    """

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the JSON file if it doesn't exist"""
        if not self.file_path.exists():
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self._save([])

    def _load(self) -> List[Dict[str, Any]]:
        """Load all records from JSON file"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, data: List[Dict[str, Any]]) -> None:
        """Save all records to JSON file"""
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _generate_id(self) -> str:
        """Generate a new UUID string"""
        return str(uuid.uuid4())

    def _now(self) -> str:
        """Get current datetime as ISO string"""
        return datetime.utcnow().isoformat()

    def create(self, model: Type[T], **kwargs) -> T:
        """Create a new record and return the created model instance"""
        data = kwargs
        data['id'] = data.get('id', self._generate_id())
        data['created_at'] = data.get('created_at', self._now())
        data['updated_at'] = data.get('updated_at', self._now())

        records = self._load()
        records.append(data)
        self._save(records)

        return model(**data)

    def get_by_id(self, model: Type[T], record_id: str) -> Optional[T]:
        """Get a record by ID"""
        records = self._load()
        for record in records:
            if record.get('id') == record_id:
                return model(**record)
        return None

    def get_all(self, model: Type[T]) -> List[T]:
        """Get all records"""
        records = self._load()
        return [model(**r) for r in records]

    def filter(
        self,
        model: Type[T],
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_desc: bool = True,
        **filters
    ) -> List[T]:
        """
        Filter records by fields.
        Example: filter(User, name="John", age=30, limit=10, offset=0)
        """
        records = self._load()

        # Apply filters
        filtered = []
        for record in records:
            match = True
            for key, value in filters.items():
                if key not in ('limit', 'offset', 'order_by', 'order_desc'):
                    if record.get(key) != value:
                        match = False
                        break
            if match:
                filtered.append(record)

        # Apply ordering
        if order_by:
            filtered.sort(
                key=lambda x: x.get(order_by, ''),
                reverse=order_desc
            )

        # Apply pagination
        if offset:
            filtered = filtered[offset:]
        if limit:
            filtered = filtered[:limit]

        return [model(**r) for r in filtered]

    def update(self, model: Type[T], record_id: str, **updates) -> Optional[T]:
        """Update a record by ID and return the updated model"""
        records = self._load()
        for i, record in enumerate(records):
            if record.get('id') == record_id:
                updates['updated_at'] = self._now()
                records[i].update(updates)
                self._save(records)
                return model(**records[i])
        return None

    def delete(self, record_id: str) -> bool:
        """Delete a record by ID. Returns True if deleted, False if not found."""
        records = self._load()
        initial_len = len(records)
        records = [r for r in records if r.get('id') != record_id]
        if len(records) < initial_len:
            self._save(records)
            return True
        return False

    def count(self, **filters) -> int:
        """Count records matching filters"""
        records = self._load()
        if not filters:
            return len(records)
        count = 0
        for record in records:
            match = True
            for key, value in filters.items():
                if record.get(key) != value:
                    match = False
                    break
            if match:
                count += 1
        return count

    def exists(self, **filters) -> bool:
        """Check if a record exists matching the filters"""
        return self.count(**filters) > 0

    def first(self, model: Type[T], **filters) -> Optional[T]:
        """Get the first record matching filters"""
        results = self.filter(model, limit=1, **filters)
        return results[0] if results else None
