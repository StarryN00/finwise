from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Iterable

from app.db import Database, utcnow
from app.ontology.enums import RelationType
from app.ontology.errors import ScopeViolation, VersionConflict
from app.ontology.contracts import Scope


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def scope_key(scope: Scope | dict[str, Any]) -> str:
    value = scope.model_dump() if isinstance(scope, Scope) else scope
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ObjectStore:
    """Small relational persistence layer with append-only object versions."""

    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()

    def create_object(
        self,
        object_type: str,
        scope: Scope,
        data: dict[str, Any],
        *,
        status: str = "DRAFT",
        created_by: str = "system",
        object_id: str | None = None,
    ) -> dict[str, Any]:
        object_id = object_id or new_id(object_type.lower())
        now = utcnow()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM ontology_objects WHERE object_id = ?",
                (object_id,),
            ).fetchone()
            version = int(row["version"] or 0) + 1
            connection.execute(
                """INSERT INTO ontology_objects
                (object_id, object_type, version, scope_json, status, data_json, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    object_id,
                    object_type,
                    version,
                    scope_key(scope),
                    status,
                    json.dumps(data, ensure_ascii=False, sort_keys=True, default=str),
                    now,
                    created_by,
                ),
            )
        return self.get_object(object_id, scope, version)

    def create_initial_object(
        self,
        object_type: str,
        scope: Scope,
        data: dict[str, Any],
        *,
        status: str = "DRAFT",
        created_by: str = "system",
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Create version 1 only; used for deterministic aggregate identities."""
        object_id = object_id or new_id(object_type.lower())
        now = utcnow()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO ontology_objects
                (object_id, object_type, version, scope_json, status, data_json, created_at, created_by)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?)""",
                (
                    object_id,
                    object_type,
                    scope_key(scope),
                    status,
                    json.dumps(data, ensure_ascii=False, sort_keys=True, default=str),
                    now,
                    created_by,
                ),
            )
        return self.get_object(object_id, scope, 1)

    def get_object(self, object_id: str, scope: Scope, version: int | None = None) -> dict[str, Any]:
        key = scope_key(scope)
        with self.database.connect() as connection:
            if version is None:
                row = connection.execute(
                    """SELECT * FROM ontology_objects
                    WHERE object_id = ? AND scope_json = ?
                    ORDER BY version DESC LIMIT 1""",
                    (object_id, key),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT * FROM ontology_objects
                    WHERE object_id = ? AND scope_json = ? AND version = ?""",
                    (object_id, key, version),
                ).fetchone()
            if row is None:
                foreign = connection.execute(
                    "SELECT 1 FROM ontology_objects WHERE object_id = ? LIMIT 1", (object_id,)
                ).fetchone()
                if foreign:
                    raise ScopeViolation()
                raise KeyError(f"对象不存在: {object_id}")
        return self._object_from_row(row)

    def latest_version(self, object_id: str, scope: Scope) -> int:
        return int(self.get_object(object_id, scope)["version"])

    def revise_object(
        self,
        object_id: str,
        expected_version: int,
        scope: Scope,
        data: dict[str, Any],
        *,
        status: str,
        created_by: str,
    ) -> dict[str, Any]:
        current = self.get_object(object_id, scope)
        if current["version"] != expected_version:
            raise VersionConflict()
        return self.create_object(
            current["object_type"],
            scope,
            data,
            status=status,
            created_by=created_by,
            object_id=object_id,
        )

    def list_objects(
        self,
        object_type: str | None,
        scope: Scope,
        *,
        statuses: Iterable[str] | None = None,
        latest_only: bool = True,
    ) -> list[dict[str, Any]]:
        base_conditions = ["scope_json = ?"]
        base_parameters: list[Any] = [scope_key(scope)]
        if object_type:
            base_conditions.append("object_type = ?")
            base_parameters.append(object_type)
        outer_conditions = list(base_conditions)
        outer_parameters = list(base_parameters)
        if statuses:
            values = list(statuses)
            outer_conditions.append("status IN (" + ",".join("?" for _ in values) + ")")
            outer_parameters.extend(values)
        if latest_only:
            query = f"""SELECT o.* FROM ontology_objects o
                JOIN (SELECT object_id, MAX(version) AS version
                      FROM ontology_objects WHERE {' AND '.join(base_conditions)}
                      GROUP BY object_id) latest
                  ON latest.object_id = o.object_id AND latest.version = o.version
                WHERE {' AND '.join('o.' + item for item in outer_conditions)}
                ORDER BY o.created_at ASC"""
            parameters = base_parameters + outer_parameters
        else:
            query = f"SELECT * FROM ontology_objects WHERE {' AND '.join(outer_conditions)} ORDER BY created_at ASC, version ASC"
            parameters = outer_parameters
        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._object_from_row(row) for row in rows]

    def list_scope_objects(self) -> list[dict[str, Any]]:
        """List latest Scope objects for server-side portfolio discovery."""
        query = """SELECT o.* FROM ontology_objects o
            JOIN (SELECT object_id, MAX(version) AS version
                  FROM ontology_objects WHERE object_type = 'Scope'
                  GROUP BY object_id) latest
              ON latest.object_id = o.object_id AND latest.version = o.version
            WHERE o.object_type = 'Scope'
            ORDER BY o.created_at ASC"""
        with self.database.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._object_from_row(row) for row in rows]

    def add_relation(
        self,
        relation_type: str,
        from_object: dict[str, Any],
        to_object: dict[str, Any],
        *,
        evidence: list[str] | None = None,
        created_by: str = "system",
        status: str = "PROPOSED",
    ) -> dict[str, Any]:
        allowed = {item.value for item in RelationType}
        if relation_type not in allowed:
            raise ValueError(f"未声明的关系类型: {relation_type}")
        if from_object["scope"] != to_object["scope"]:
            raise ScopeViolation("关系两端 Scope 不一致")
        evidence = evidence or []
        if relation_type in {RelationType.SUPPORTS, RelationType.MATCHES} and not evidence:
            raise ValueError("支持或匹配关系必须带证据引用")
        relation_id = new_id("rel")
        now = utcnow()
        with self.database.connect() as connection:
            existing = connection.execute(
                """SELECT * FROM relations WHERE relation_type = ? AND from_id = ? AND from_version = ?
                   AND to_id = ? AND to_version = ? AND scope_json = ?""",
                (relation_type, from_object["object_id"], from_object["version"], to_object["object_id"], to_object["version"], scope_key(from_object["scope"])),
            ).fetchone()
            if existing:
                return self._relation_from_row(existing)
            connection.execute(
                """INSERT INTO relations
                (relation_id, relation_type, from_type, from_id, from_version,
                 to_type, to_id, to_version, scope_json, status, evidence_json, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    relation_id,
                    relation_type,
                    from_object["object_type"],
                    from_object["object_id"],
                    from_object["version"],
                    to_object["object_type"],
                    to_object["object_id"],
                    to_object["version"],
                    scope_key(from_object["scope"]),
                    status,
                    json.dumps(evidence, ensure_ascii=False),
                    now,
                    created_by,
                ),
            )
        return {
            "relation_id": relation_id,
            "relation_type": relation_type,
            "from": {"type": from_object["object_type"], "id": from_object["object_id"], "version": from_object["version"]},
            "to": {"type": to_object["object_type"], "id": to_object["object_id"], "version": to_object["version"]},
            "scope": from_object["scope"],
            "status": status,
            "evidence": evidence,
            "created_at": now,
        }

    def list_relations(self, scope: Scope, object_id: str | None = None) -> list[dict[str, Any]]:
        conditions = ["scope_json = ?"]
        parameters: list[Any] = [scope_key(scope)]
        if object_id:
            conditions.append("(from_id = ? OR to_id = ?)")
            parameters.extend([object_id, object_id])
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM relations WHERE {' AND '.join(conditions)} ORDER BY created_at ASC", parameters
            ).fetchall()
        return [self._relation_from_row(row) for row in rows]

    def add_audit(
        self,
        event_type: str,
        actor_id: str,
        scope: Scope,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        object_version: int | None = None,
        before: Any = None,
        after: Any = None,
        evidence: list[str] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        event = {
            "event_id": new_id("audit"),
            "event_type": event_type,
            "actor_id": actor_id,
            "object_type": object_type,
            "object_id": object_id,
            "object_version": object_version,
            "scope": scope.model_dump(),
            "before": before or {},
            "after": after or {},
            "evidence": evidence or [],
            "reason": reason,
            "created_at": utcnow(),
        }
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO audit_events
                (event_id, event_type, actor_id, object_type, object_id, object_version,
                 scope_json, before_json, after_json, evidence_json, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["event_id"], event_type, actor_id, object_type, object_id, object_version,
                    scope_key(scope), json.dumps(event["before"], ensure_ascii=False, default=str),
                    json.dumps(event["after"], ensure_ascii=False, default=str),
                    json.dumps(event["evidence"], ensure_ascii=False), reason, event["created_at"],
                ),
            )
        return event

    def list_audits(self, scope: Scope, object_id: str | None = None) -> list[dict[str, Any]]:
        conditions = ["scope_json = ?"]
        parameters: list[Any] = [scope_key(scope)]
        if object_id:
            conditions.append("object_id = ?")
            parameters.append(object_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM audit_events WHERE {' AND '.join(conditions)} ORDER BY created_at ASC", parameters
            ).fetchall()
        return [
            {
                "event_id": row["event_id"], "event_type": row["event_type"], "actor_id": row["actor_id"],
                "object_type": row["object_type"], "object_id": row["object_id"], "object_version": row["object_version"],
                "scope": json.loads(row["scope_json"]), "before": json.loads(row["before_json"]),
                "after": json.loads(row["after_json"]), "evidence": json.loads(row["evidence_json"]),
                "reason": row["reason"], "created_at": row["created_at"],
            }
            for row in rows
        ]

    def find_command(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM commands WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return self._command_from_row(row) if row else None

    def save_command(self, command: dict[str, Any]) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO commands
                (command_id, idempotency_key, action, target_id, target_version, scope_json,
                 actor_id, status, request_json, effect_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    command["command_id"], command["idempotency_key"], command["action"], command["target_id"],
                    command["target_version"], scope_key(command["scope"]), command["actor_id"], command["status"],
                    json.dumps(command.get("request", {}), ensure_ascii=False, default=str),
                    json.dumps(command.get("effect", {}), ensure_ascii=False, default=str), command["created_at"],
                ),
            )
        return command

    def create_run(self, scope: Scope, data: dict[str, Any]) -> dict[str, Any]:
        run_id = data["run_id"]
        now = utcnow()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO processing_runs
                (run_id, scope_json, status, input_fingerprint, baseline_version, rule_version,
                 model_version, schema_version, gateway_version, attempt, parent_run_id, result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, scope_key(scope), data["status"], data["input_fingerprint"], data["baseline_version"],
                    data["rule_version"], data["model_version"], data["schema_version"], data["gateway_version"],
                    data["attempt"], data.get("parent_run_id"), json.dumps(data.get("result", {}), ensure_ascii=False), now, now,
                ),
            )
        return {**data, "scope": scope.model_dump(), "created_at": now, "updated_at": now}

    def get_run(self, run_id: str, scope: Scope) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM processing_runs WHERE run_id = ? AND scope_json = ?", (run_id, scope_key(scope))
            ).fetchone()
            if row is None:
                foreign = connection.execute("SELECT 1 FROM processing_runs WHERE run_id = ?", (run_id,)).fetchone()
                if foreign:
                    raise ScopeViolation()
                raise KeyError(f"Run 不存在: {run_id}")
        return self._run_from_row(row)

    def list_runs(self, scope: Scope) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM processing_runs WHERE scope_json = ? ORDER BY created_at ASC", (scope_key(scope),)
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def update_run(self, run_id: str, scope: Scope, *, status: str, result: dict[str, Any]) -> dict[str, Any]:
        current = self.get_run(run_id, scope)
        updated_at = utcnow()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE processing_runs SET status = ?, result_json = ?, updated_at = ? WHERE run_id = ? AND scope_json = ?",
                (status, json.dumps(result, ensure_ascii=False, default=str), updated_at, run_id, scope_key(scope)),
            )
        return {**current, "status": status, "result": result, "updated_at": updated_at}

    def add_reconciliation(self, scope: Scope, item: dict[str, Any]) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO reconciliation_checks
                (check_id, scope_json, group_id, check_type, input_json, formula, tolerance, result, reason, check_version, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["check_id"], scope_key(scope), item["group_id"], item["check_type"],
                    json.dumps(item["inputs"], ensure_ascii=False, default=str), item["formula"], item["tolerance"],
                    item["result"], item["reason"], item["check_version"], item["executed_at"],
                ),
            )
        return item

    def list_reconciliation(self, scope: Scope, group_id: str | None = None) -> list[dict[str, Any]]:
        conditions = ["scope_json = ?"]
        parameters: list[Any] = [scope_key(scope)]
        if group_id:
            conditions.append("group_id = ?")
            parameters.append(group_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM reconciliation_checks WHERE {' AND '.join(conditions)} ORDER BY executed_at ASC", parameters
            ).fetchall()
        return [
            {
                "check_id": row["check_id"], "group_id": row["group_id"], "check_type": row["check_type"],
                "inputs": json.loads(row["input_json"]), "formula": row["formula"], "tolerance": row["tolerance"],
                "result": row["result"], "reason": row["reason"], "check_version": row["check_version"],
                "executed_at": row["executed_at"], "scope": json.loads(row["scope_json"]),
            }
            for row in rows
        ]

    def save_receipt(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM external_receipts WHERE payload_hash = ?", (item["payload_hash"],)
            ).fetchone()
            if existing:
                return self._receipt_from_row(existing), False
            connection.execute(
                """INSERT INTO external_receipts
                (receipt_id, export_id, package_id, voucher_version_id, payload_hash, status, payload_json, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["receipt_id"], item["export_id"], item["package_id"], item["voucher_version_id"],
                    item["payload_hash"], item["status"], json.dumps(item["payload"], ensure_ascii=False), item["received_at"],
                ),
            )
        return item, True

    def _object_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "object_id": row["object_id"], "object_type": row["object_type"], "version": row["version"],
            "scope": json.loads(row["scope_json"]), "status": row["status"], "data": json.loads(row["data_json"]),
            "created_at": row["created_at"], "created_by": row["created_by"],
        }

    def _relation_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "relation_id": row["relation_id"], "relation_type": row["relation_type"],
            "from": {"type": row["from_type"], "id": row["from_id"], "version": row["from_version"]},
            "to": {"type": row["to_type"], "id": row["to_id"], "version": row["to_version"]},
            "scope": json.loads(row["scope_json"]), "status": row["status"],
            "evidence": json.loads(row["evidence_json"]), "created_at": row["created_at"], "created_by": row["created_by"],
        }

    def _command_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "command_id": row["command_id"], "idempotency_key": row["idempotency_key"], "action": row["action"],
            "target_id": row["target_id"], "target_version": row["target_version"], "scope": json.loads(row["scope_json"]),
            "actor_id": row["actor_id"], "status": row["status"], "request": json.loads(row["request_json"]),
            "effect": json.loads(row["effect_json"]), "created_at": row["created_at"],
        }

    def _run_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "run_id": row["run_id"], "scope": json.loads(row["scope_json"]), "status": row["status"],
            "input_fingerprint": row["input_fingerprint"], "baseline_version": row["baseline_version"],
            "rule_version": row["rule_version"], "model_version": row["model_version"],
            "schema_version": row["schema_version"], "gateway_version": row["gateway_version"],
            "attempt": row["attempt"], "parent_run_id": row["parent_run_id"], "result": json.loads(row["result_json"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _receipt_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "receipt_id": row["receipt_id"], "export_id": row["export_id"], "package_id": row["package_id"],
            "voucher_version_id": row["voucher_version_id"], "payload_hash": row["payload_hash"],
            "status": row["status"], "payload": json.loads(row["payload_json"]), "received_at": row["received_at"],
        }
