"""Scope-bound human handling records. These are not balance overrides.

Review approves a proposed course of action, never financial evidence itself.
Original preparation and baseline validation intentionally do not read this store.
"""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from app.db import utcnow
from app.historical import identify, issue_key
from app.ontology.errors import PermissionDenied, PreconditionFailed, VersionConflict
from app.ontology.store import digest

TYPE = "HistoricalIssuePlan"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Anchor(StrictInput):
    region: str = Field(min_length=1, max_length=256)
    row: StrictInt = Field(ge=1, le=1000000)


class Evidence(StrictInput):
    artifact_id: str = Field(min_length=1, max_length=128)
    version: StrictInt = Field(ge=1)
    anchor: Anchor


class PlanInput(StrictInput):
    issue_key: str = Field(min_length=1, max_length=64)
    expected_plan_version: StrictInt = Field(ge=0)
    route: Literal["existing_evidence", "unavailable"]
    conclusion: str = Field(min_length=1, max_length=2000)
    action_plan: str = Field(default="", max_length=2000)
    owner: str = Field(default="", max_length=128)
    follow_up: str = Field(default="", max_length=500)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_proposal_fields(self):
        if self.route == "existing_evidence" and not all((self.action_plan, self.owner, self.follow_up)):
            raise ValueError("Existing-evidence proposals require a plan, owner and follow-up")
        return self


class ReviewInput(StrictInput):
    decision: Literal["approved", "returned"]
    note: str = Field(min_length=1, max_length=2000)


def checked_input(schema, payload):
    try:
        return schema.model_validate(payload)
    except ValidationError:
        if isinstance(payload, dict) and payload.get("route") == "unavailable":
            raise PreconditionFailed("请填写暂无法补充的原因（1–2000 字），并检查当前问题及版本")
        raise PreconditionFailed("请完整填写处理方式、说明、责任人及后续安排，并检查来源定位；不接受其他变更字段")


class HistoricalIssuePlans:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def checked_job(self, scope, job_id, version):
        job = self.service.historical.get(scope)
        if not job or job["object_id"] != job_id or job["version"] != version:
            raise VersionConflict("历史核对版本已变化，请查看最新问题后重新提交")
        if job["status"] != "NEEDS_REVIEW" or not job["data"].get("result", {}).get("issues"):
            raise PreconditionFailed("当前没有可处理的历史核对问题")
        try:
            sources = self.service.historical.checked_sources(job)
        except (OSError, KeyError) as exc:
            raise PreconditionFailed("来源无法读取，请重新核对历史账表") from exc
        return job, sources

    def checked_evidence(self, evidence, sources):
        bound = {ref["artifact_id"]: (ref, content) for ref, content in sources}
        sheets, seen, refs = {}, set(), []
        for item in evidence:
            ref, content = bound.get(item.artifact_id, ({}, None))
            if ref.get("version") != item.version:
                raise PreconditionFailed("依据必须来自本次核对绑定的原件和版本")
            if item.artifact_id not in sheets:
                try:
                    _, sheet, _, _ = identify(content)
                    sheets[item.artifact_id] = {f"{sheet['name']}!第{r['row']}行": r["row"] for r in sheet["rows"]
                                               if any(v not in (None, "") for v in r["values"])}
                except (ValueError, KeyError, TypeError) as exc:
                    raise PreconditionFailed("无法核对所选原件定位，请查看原件") from exc
            if sheets[item.artifact_id].get(item.anchor.region) != item.anchor.row:
                raise PreconditionFailed("所选来源行不存在或工作表定位不一致")
            identity = (item.artifact_id, item.version, item.anchor.region)
            if identity in seen:
                raise PreconditionFailed("同一来源行无需重复关联")
            seen.add(identity)
            refs.append({**ref, "anchor": item.anchor.model_dump()})
        return refs

    def save(self, scope, job_id, version, actor_id, payload):
        value = checked_input(PlanInput, payload)
        job, sources = self.checked_job(scope, job_id, version)
        issue = next((i for i in job["data"]["result"]["issues"] if issue_key(i) == value.issue_key), None)
        if issue is None:
            raise PreconditionFailed("问题不属于当前历史核对结果")
        if value.route == "existing_evidence" and not value.evidence:
            raise PreconditionFailed("请至少关联一处已有资料依据；无法提供依据时可记录暂无法补充")
        evidence = self.checked_evidence(value.evidence, sources)
        plan_id = "history_plan_" + digest([job_id, version, value.issue_key])[:32]
        try:
            old = self.store.get_object(plan_id, scope)
        except KeyError:
            old = None
        if value.expected_plan_version != (old["version"] if old else 0):
            raise VersionConflict("处理记录已变化，请刷新后核对最新记录")
        if old and old["data"]["submitted_by"] != actor_id:
            raise PermissionDenied("只有原提交人可以修订方案；复核人请使用复核操作")
        data = {**value.model_dump(exclude={"expected_plan_version", "evidence"}), "evidence": evidence,
                "historical_preparation": {"object_id": job_id, "version": version},
                "input_hash": job["data"]["input_hash"], "issue_snapshot": deepcopy(issue),
                "submitted_by": actor_id, "submitted_at": utcnow(),
                "effect_boundary": "仅记录处理方案；未修改原件、科目、余额或期初核对结果"}
        if value.route == "unavailable":
            # Ownership is authoritative session identity, never a client-supplied name.
            # Accept old clients' fields without carrying obsolete form requirements forward.
            data.update(owner=actor_id, action_plan="", follow_up="")
        status = "SUBMITTED" if value.route == "existing_evidence" else "UNAVAILABLE_RECORDED"
        if old:
            result = self.store.revise_object(plan_id, old["version"], scope, data, status=status, created_by=actor_id)
        else:
            result = self.store.create_initial_object(TYPE, scope, data, object_id=plan_id, status=status, created_by=actor_id)
        self.store.add_audit("HISTORICAL_ISSUE_PLAN_SAVED", actor_id, scope, object_type=TYPE,
                             object_id=plan_id, object_version=result["version"], before=old, after=result,
                             reason="方案已提交，原始核对问题及期初门禁保留")
        return result

    def review(self, scope, plan_id, version, actor_id, payload):
        value = checked_input(ReviewInput, payload)
        plan = self.store.get_object(plan_id, scope)
        if plan["version"] != version:
            raise VersionConflict()
        if plan["status"] != "SUBMITTED":
            raise PreconditionFailed("只有待复核方案可以复核，请查看最新记录")
        if plan["data"]["submitted_by"] == actor_id:
            raise PermissionDenied("请由另一位有权限的人员复核，不能复核本人提交的方案")
        ref = plan["data"]["historical_preparation"]
        job, _ = self.checked_job(scope, ref["object_id"], ref["version"])
        if job["data"]["input_hash"] != plan["data"]["input_hash"]:
            raise PreconditionFailed("方案依据已经变化，请重新提交")
        data = deepcopy(plan["data"])
        data["review"] = {**value.model_dump(), "reviewed_by": actor_id, "reviewed_at": utcnow()}
        result = self.store.revise_object(plan_id, version, scope, data,
            status="REVIEWED" if value.decision == "approved" else "RETURNED", created_by=actor_id)
        self.store.add_audit("HISTORICAL_ISSUE_PLAN_REVIEWED", actor_id, scope, object_type=TYPE,
                             object_id=plan_id, object_version=result["version"], before=plan, after=result,
                             reason="复核处理方案，不替代余额校验或期初确认")
        return result

    def view(self, scope, job):
        records = self.store.list_objects(TYPE, scope)
        # `job` is the source-validated projection, not the unverified stored status.
        current = {"object_id": job["object_id"], "version": job["version"]} if job else None
        return [{**p, "stale": not (job and job["status"] == "NEEDS_REVIEW"
                    and p["data"]["historical_preparation"] == current and p["data"]["input_hash"] == job["data"]["input_hash"]),
                 "stale_reason": "原件或历史核对版本已变化，原记录只供追溯，不沿用此前复核结论"}
                for p in records]
