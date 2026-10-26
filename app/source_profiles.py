"""来源版式（Source Profile）：把"这份文件长什么样"从代码变成数据。

设计约束：
  * 版式只描述指针与约定——字段在第几列、表头在第几行、空值怎么写、金额怎么表达。
    它绝不包含任何金额、主体名称或账号，因此 PLATFORM 级版式可以跨租户复用。
  * 查找按 ENTITY > TENANT > PLATFORM 由具体到通用，命中即返回，不调用模型。
  * 未命中不是错误：返回 None，由调用方决定是请求模型提案还是出一张待确认卡片。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from uuid import uuid4
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from app.db import utcnow

PROFILE_VERSION = "source-profile-v1"

# 各资料类型必须被版式覆盖的字段。缺一个都不算可执行版式。
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "bank_statement": ("transaction_date",),
    "purchase_invoices": ("invoice_no", "invoice_date", "net_amount", "tax"),
    "sales_invoices": ("invoice_no", "invoice_date", "net_amount", "tax"),
}

DEFAULT_NULL_TOKENS = ("-", "--", "—", "/", "N/A", "n/a")


def normalize_label(value: object) -> str:
    """表头文本归一：全角转半角、去空白与换行、去尾部注释括号、统一大小写。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", "", text)
    text = text.replace(" ", "")
    return text.casefold()


def fingerprint(labels: Iterable[object], document_kind: str) -> str:
    """版式指纹 = 归一化后的表头标签集合 + 资料类型。

    用集合而非序列，列顺序变动不会产生新指纹；只取非空标签，尾部空列不影响。
    指纹只由表头文本决定，不含任何一行业务数据。
    """
    tokens = sorted({normalize_label(x) for x in labels if str(x or "").strip()})
    payload = json.dumps([document_kind, tokens], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProfileMapping(BaseModel):
    """一份可执行的版式。字段值是列下标，永远不是业务值。"""

    model_config = ConfigDict(extra="forbid")

    header_row: StrictInt = Field(ge=1, le=20000)
    fields: dict[StrictStr, list[StrictInt]] = Field(min_length=1)
    null_tokens: list[StrictStr] = Field(default_factory=lambda: list(DEFAULT_NULL_TOKENS), max_length=20)
    # TWO_COLUMN     借贷分列（多数网银导出）
    # SIGNED_SINGLE  单列金额带正负号
    # DIRECTION_SINGLE 单列金额 + 方向列（如"来账/往账"、"收入/支出"）
    amount_model: Literal["TWO_COLUMN", "SIGNED_SINGLE", "DIRECTION_SINGLE"] = "TWO_COLUMN"
    # 余额列是交易后余额（多数网银）还是交易前余额（部分贷款/专户导出）。
    # 这个约定只影响校验口径，不影响任何一笔金额的取值。
    balance_timing: Literal["AFTER", "BEFORE"] = "AFTER"
    direction_expense: list[StrictStr] = Field(default_factory=list, max_length=20)
    direction_income: list[StrictStr] = Field(default_factory=list, max_length=20)
    sheet_name: Optional[StrictStr] = None
    notes: StrictStr = ""

    @field_validator("fields")
    @classmethod
    def columns_are_sane(cls, value: dict[str, list[int]]) -> dict[str, list[int]]:
        for field, columns in value.items():
            if not columns:
                raise ValueError(f"{field}：列下标不能为空")
            if any(index < 0 or index > 255 for index in columns):
                raise ValueError(f"{field}：列下标越界")
        return value

    def model_post_init(self, _context) -> None:
        if self.amount_model == "TWO_COLUMN":
            missing = [f for f in ("expense", "income") if f not in self.fields]
            if missing:
                raise ValueError("借贷分列版式必须同时映射 expense 与 income")
        else:
            if "amount" not in self.fields:
                raise ValueError("单列金额版式必须映射 amount")
            if self.amount_model == "DIRECTION_SINGLE":
                if "direction" not in self.fields:
                    raise ValueError("方向列版式必须映射 direction")
                if not self.direction_expense or not self.direction_income:
                    raise ValueError("方向列版式必须声明支出与收入的取值")

    def covers(self, document_kind: str) -> bool:
        required = REQUIRED_FIELDS.get(document_kind, ())
        return all(field in self.fields for field in required)

    def is_null(self, value: object) -> bool:
        if value is None:
            return True
        text = str(value).strip()
        return text == "" or text in self.null_tokens


class SourceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: StrictStr
    fingerprint: StrictStr
    document_kind: StrictStr
    scope_level: Literal["PLATFORM", "TENANT", "ENTITY"]
    tenant_id: Optional[StrictStr] = None
    legal_entity_id: Optional[StrictStr] = None
    label: StrictStr
    mapping: ProfileMapping
    origin: Literal["SEED", "AGENT", "HUMAN"]
    confidence: StrictInt = 0
    hit_count: StrictInt = 0
    confirmed_by: Optional[StrictStr] = None
    confirmed_at: Optional[StrictStr] = None
    created_at: StrictStr


# 由具体到通用；先命中即停。
_PRECEDENCE = {"ENTITY": 0, "TENANT": 1, "PLATFORM": 2}


class ProfileStore:
    """版式库。查找不写业务数据，只累加命中次数用于晋升判断。"""

    def __init__(self, database):
        self.database = database

    # ---------- 写入 ----------

    def record(
        self,
        *,
        fingerprint_value: str,
        document_kind: str,
        label: str,
        mapping: ProfileMapping,
        origin: Literal["SEED", "AGENT", "HUMAN"],
        scope_level: Literal["PLATFORM", "TENANT", "ENTITY"] = "PLATFORM",
        tenant_id: str | None = None,
        legal_entity_id: str | None = None,
        confidence: int = 0,
        confirmed_by: str | None = None,
    ) -> SourceProfile:
        if not mapping.covers(document_kind):
            required = ", ".join(REQUIRED_FIELDS.get(document_kind, ()))
            raise ValueError(f"版式未覆盖 {document_kind} 的必要字段：{required}")
        if scope_level == "PLATFORM":
            tenant_id = legal_entity_id = None
        elif scope_level == "TENANT":
            legal_entity_id = None
            if not tenant_id:
                raise ValueError("TENANT 级版式必须带 tenant_id")
        elif not (tenant_id and legal_entity_id):
            raise ValueError("ENTITY 级版式必须带 tenant_id 与 legal_entity_id")

        now = utcnow()
        # 同一秒内可能连续登记同一指纹的新版本，标识必须唯一而不是由内容派生。
        profile_id = "sp_" + uuid4().hex[:24]
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE source_profiles SET retired_at = ?
                   WHERE fingerprint = ? AND document_kind = ? AND scope_level = ?
                     AND COALESCE(tenant_id,'') = ? AND COALESCE(legal_entity_id,'') = ?
                     AND retired_at IS NULL""",
                (now, fingerprint_value, document_kind, scope_level, tenant_id or "", legal_entity_id or ""),
            )
            connection.execute(
                """INSERT INTO source_profiles
                   (profile_id, fingerprint, document_kind, scope_level, tenant_id, legal_entity_id,
                    label, mapping_json, origin, confidence, hit_count, confirmed_by, confirmed_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
                (profile_id, fingerprint_value, document_kind, scope_level, tenant_id, legal_entity_id,
                 label, mapping.model_dump_json(), origin, confidence, confirmed_by,
                 now if confirmed_by else None, now),
            )
        return self.get(profile_id)

    def confirm(self, profile_id: str, actor: str) -> SourceProfile:
        """人工确认一份 AI 提案。确认后 origin 变 HUMAN，置信度拉满。"""
        with self.database.connect() as connection:
            changed = connection.execute(
                """UPDATE source_profiles SET origin='HUMAN', confidence=100, confirmed_by=?, confirmed_at=?
                   WHERE profile_id=? AND retired_at IS NULL""",
                (actor, utcnow(), profile_id),
            ).rowcount
        if not changed:
            raise KeyError(f"版式不存在或已停用：{profile_id}")
        return self.get(profile_id)

    def retire(self, profile_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE source_profiles SET retired_at=? WHERE profile_id=? AND retired_at IS NULL",
                (utcnow(), profile_id),
            )

    # ---------- 查找 ----------

    def resolve(
        self,
        *,
        fingerprint_value: str,
        document_kind: str,
        tenant_id: str | None = None,
        legal_entity_id: str | None = None,
        count_hit: bool = True,
    ) -> SourceProfile | None:
        """按 ENTITY > TENANT > PLATFORM 查找。未命中返回 None，不是错误。"""
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM source_profiles
                   WHERE fingerprint=? AND document_kind=? AND retired_at IS NULL""",
                (fingerprint_value, document_kind),
            ).fetchall()
        candidates = []
        for row in rows:
            level = row["scope_level"]
            if level == "ENTITY" and (row["tenant_id"] != tenant_id or row["legal_entity_id"] != legal_entity_id):
                continue
            if level == "TENANT" and row["tenant_id"] != tenant_id:
                continue
            candidates.append(row)
        if not candidates:
            return None
        row = min(candidates, key=lambda r: _PRECEDENCE[r["scope_level"]])
        if count_hit:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE source_profiles SET hit_count = hit_count + 1 WHERE profile_id=?",
                    (row["profile_id"],),
                )
        return self._from_row(row)

    def get(self, profile_id: str) -> SourceProfile:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"版式不存在：{profile_id}")
        return self._from_row(row)

    def list_profiles(self, *, document_kind: str | None = None, include_retired: bool = False) -> list[SourceProfile]:
        query = "SELECT * FROM source_profiles WHERE 1=1"
        params: list[object] = []
        if document_kind:
            query += " AND document_kind=?"
            params.append(document_kind)
        if not include_retired:
            query += " AND retired_at IS NULL"
        query += " ORDER BY created_at"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    # ---------- 晋升 ----------

    def promotable(self, *, min_hits: int = 3) -> list[SourceProfile]:
        """ENTITY 级版式被人工确认且命中够多，就该升到 TENANT；
        同一指纹在两个以上租户各自确认过，就该升到 PLATFORM。"""
        ready: list[SourceProfile] = []
        with self.database.connect() as connection:
            confirmed = connection.execute(
                """SELECT fingerprint, document_kind, tenant_id FROM source_profiles
                   WHERE retired_at IS NULL AND confirmed_at IS NOT NULL AND tenant_id IS NOT NULL"""
            ).fetchall()
            # 跨租户复现只看"被确认过"，与各自的命中次数无关。
            tenants: dict[tuple[str, str], set[str]] = {}
            for row in confirmed:
                tenants.setdefault((row["fingerprint"], row["document_kind"]), set()).add(row["tenant_id"])
            rows = connection.execute(
                """SELECT * FROM source_profiles
                   WHERE retired_at IS NULL AND confirmed_at IS NOT NULL AND hit_count >= ?""",
                (min_hits,),
            ).fetchall()
            for row in rows:
                key = (row["fingerprint"], row["document_kind"])
                if row["scope_level"] == "ENTITY":
                    ready.append(self._from_row(row))
                elif row["scope_level"] == "TENANT" and len(tenants.get(key, set())) >= 2:
                    ready.append(self._from_row(row))
        return ready

    def promote(self, profile_id: str, actor: str) -> SourceProfile:
        current = self.get(profile_id)
        target = {"ENTITY": "TENANT", "TENANT": "PLATFORM"}.get(current.scope_level)
        if target is None:
            raise ValueError("PLATFORM 级版式已是最高作用域")
        return self.record(
            fingerprint_value=current.fingerprint,
            document_kind=current.document_kind,
            label=current.label,
            mapping=current.mapping,
            origin="HUMAN",
            scope_level=target,
            tenant_id=None if target == "PLATFORM" else current.tenant_id,
            legal_entity_id=None,
            confidence=current.confidence,
            confirmed_by=actor,
        )

    @staticmethod
    def _from_row(row) -> SourceProfile:
        return SourceProfile(
            profile_id=row["profile_id"], fingerprint=row["fingerprint"],
            document_kind=row["document_kind"], scope_level=row["scope_level"],
            tenant_id=row["tenant_id"], legal_entity_id=row["legal_entity_id"],
            label=row["label"], mapping=ProfileMapping.model_validate_json(row["mapping_json"]),
            origin=row["origin"], confidence=row["confidence"], hit_count=row["hit_count"],
            confirmed_by=row["confirmed_by"], confirmed_at=row["confirmed_at"], created_at=row["created_at"],
        )


def scoped_resolver(store: "ProfileStore", scope) -> object:
    """给解析引擎用的版式解析函数，按处理范围隔离。

    返回 None 表示未命中 —— 解析引擎照旧标记 UNRECOGNIZED，由上层出卡片。
    """
    tenant_id = getattr(scope, "tenant_id", None)
    legal_entity_id = getattr(scope, "legal_entity_id", None)

    def resolve(labels, document_kind):
        found = store.resolve(
            fingerprint_value=fingerprint(labels, document_kind),
            document_kind=document_kind,
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
        )
        return found.mapping if found else None

    return resolve
