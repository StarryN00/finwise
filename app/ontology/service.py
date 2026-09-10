from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from pydantic import ValidationError

from app.db import utcnow
from app.ontology.contracts import AgentOutput, ArtifactInput, FactInput, Scope, SourceAnchor
from app.ontology.enums import ObjectType, RelationType, RunStatus, SourceDisposition
from app.ontology.errors import (
    DomainError,
    GatewayPaused,
    PermissionDenied,
    PreconditionFailed,
    RuleConflictDetected,
    ScopeViolation,
    VersionConflict,
)
from app.ontology.store import ObjectStore, digest, new_id
from app.ontology.procurement import ENGINE_VERSION, PAYMENT_TOLERANCE, procurement_amounts
from app.ontology.baseline import VALIDATION_VERSION, previous_period, validate_confirmation
from app.ontology.readiness import build_readiness
from app.ontology.gateway import AGENT_SCHEMA_VERSION, GATEWAY_VERSION, AgentGateway, GatewayFailure
from app.tabular import ExtractionError, MAX_BYTES, PARSER_VERSION, ParseOptions, extract_workbook
from app.payroll_mapping import PayrollMappingService
from app.parse_plans import ParsePlanService, InspectRequest
from app.bank_accounts import BankAccounts
from app.historical import HistoricalPreparation
from app.historical_plans import HistoricalIssuePlans
from app.materials import MaterialReview
from app.bills import BillReview
from app.invoice_review import InvoiceAmountReview


ROLE_PERMISSIONS = {
    "operator": {"parse_artifact", "confirm_baseline", "create_procurement_group", "confirm_grouping", "suspend_group", "rerun_group", "generate_draft", "validate_draft", "revise_voucher", "release_delivery", "export_package", "ack_external_import", "archive_artifact", "reparse_fact", "split_group", "merge_groups", "reconcile_group", "retry_run", "replay_run", "cancel_run", "complete_run"},
    "accountant": {"parse_artifact", "confirm_baseline", "create_procurement_group", "approve_rule", "approve_rule_batch", "resolve_rule_conflict", "revoke_rule", "confirm_grouping", "suspend_group", "rerun_group", "generate_draft", "validate_draft", "revise_voucher", "release_delivery", "export_package", "ack_external_import", "close_period", "archive_period", "reparse_fact", "split_group", "merge_groups", "archive_artifact", "reconcile_group", "retry_run", "replay_run", "cancel_run", "complete_run"},
    "reviewer": {"approve_rule", "approve_rule_batch", "resolve_rule_conflict", "revoke_rule", "validate_draft", "revise_voucher", "release_delivery", "export_package", "ack_external_import", "archive_period", "reconcile_group", "replay_run", "complete_run"},
    "admin": {"parse_artifact", "confirm_baseline", "create_procurement_group", "approve_rule", "approve_rule_batch", "resolve_rule_conflict", "revoke_rule", "confirm_grouping", "suspend_group", "rerun_group", "generate_draft", "validate_draft", "revise_voucher", "release_delivery", "export_package", "ack_external_import", "close_period", "lock_period", "archive_period", "archive_artifact", "reparse_fact", "split_group", "merge_groups", "reconcile_group", "retry_run", "replay_run", "cancel_run", "complete_run"},
}

for _role in ("operator", "accountant", "admin"):
    ROLE_PERMISSIONS[_role].update({'save_material_opinion','retry_material_guidance','request_material_guidance'})
    ROLE_PERMISSIONS[_role].update({'confirm_bank_period','revoke_bank_period','accept_bank_period','revoke_bank_period_intake'})
    ROLE_PERMISSIONS[_role].update({'request_problem_review','retry_problem_review'})
    ROLE_PERMISSIONS[_role].update({'verify_source_values','revoke_source_verification','defer_material_issue'})
    ROLE_PERMISSIONS[_role].update({'request_payroll_mapping','apply_payroll_mapping','preview_payroll_mapping'})
    ROLE_PERMISSIONS[_role].update({'inspect_parse_plan','preview_parse_plan','apply_parse_plan'})
    ROLE_PERMISSIONS[_role].update({'register_bank_account','confirm_statement_account'})
    ROLE_PERMISSIONS[_role].update({'confirm_bill_business','revoke_bill_business'})
    ROLE_PERMISSIONS[_role].update({'confirm_invoice_amount','revoke_invoice_amount'})
    ROLE_PERMISSIONS[_role].add("prepare_historical")
    ROLE_PERMISSIONS[_role].add("save_historical_issue_plan")
for _role in ("accountant", "reviewer", "admin"):
    ROLE_PERMISSIONS[_role].add("review_historical_issue_plan")


def historical_prerequisite(job, plans, baseline_status):
    """Return the history/baseline prerequisite without changing month progress.

    Historical preparation is an input to the baseline gate, not a sixth month
    stage.  This projection deliberately keeps the actionable history work
    separate from the current-period material flow.
    """
    issues = (((job or {}).get("data") or {}).get("result") or {}).get("issues", [])
    job_ref = {"object_id": job["object_id"], "version": job["version"]} if job else None
    input_hash = (job or {}).get("data", {}).get("input_hash")
    current_plans = []
    for issue in issues:
        issue_key = issue.get("issue_key")
        current = next((plan for plan in plans
                        if not plan.get("stale")
                        and plan.get("data", {}).get("issue_key") == issue_key
                        and plan.get("data", {}).get("historical_preparation") == job_ref
                        and plan.get("data", {}).get("input_hash") == input_hash), None)
        current_plans.append(current)
    recorded = sum(plan is not None and plan.get("status") in {"SUBMITTED", "REVIEWED", "UNAVAILABLE_RECORDED"}
                   for plan in current_plans)
    deferred = sum(plan is not None and plan.get("status") == "UNAVAILABLE_RECORDED" for plan in current_plans)
    pending = max(0, len(issues) - recorded)
    status = "VALID" if baseline_status == "VALID" else "WAITING"
    summary = "期初已通过现有校验，历史资料作为已保留依据"
    if baseline_status != "VALID":
        job_status = (job or {}).get("status")
        if job_status == "READY_FOR_CONFIRMATION":
            status, summary = "ACTION_REQUIRED", "历史账表已形成期初候选，需核对完整性后确认期初"
        elif job_status == "NEEDS_REVIEW" and pending:
            status, summary = "ACTION_REQUIRED", f"历史账表有 {pending} 项核对问题待处理"
        elif job_status in {"FAILED", "STALE", "WAITING_INPUT", "NEEDS_SELECTION"}:
            status, summary = "ACTION_REQUIRED", {
                "FAILED": "历史账表处理失败，需检查原件或明确重试",
                "STALE": "历史原件或核对版本已变化，需重新检查",
                "WAITING_INPUT": "历史账表还缺少必要原件",
                "NEEDS_SELECTION": "历史账表有多个来源，需选择本次核对原件",
            }[job_status]
        elif recorded and not pending:
            summary = "历史处理意见已记录，期初余额仍待核实"
        elif job_status in {"QUEUED", "RUNNING"}:
            summary = "历史账表正在处理，处理期间可继续整理本期资料"
        else:
            summary = "期初余额仍待核实，历史账表结果尚未形成"
    return {
        "status": status,
        "summary": summary,
        "blocks": ["制证", "交付" ] if baseline_status != "VALID" else [],
        "does_not_block": ["资料整理", "资料核对"],
        "issue_count": len(issues),
        "recorded_count": recorded,
        "deferred_count": deferred,
        "pending_count": pending,
        "baseline_status": baseline_status,
    }


class OntologyService:
    def __init__(self, store: ObjectStore):
        self.store = store
        self.gateway = AgentGateway(store.database.settings)
        self.historical = HistoricalPreparation(self)
        self.historical_plans = HistoricalIssuePlans(self)
        self.materials = MaterialReview(self)
        self.bills = BillReview(self)
        self.invoice_amounts = InvoiceAmountReview(self)
        self.payroll_mapping = PayrollMappingService(self)
        self.parse_plans = ParsePlanService(self)
        self.bank_accounts = BankAccounts(self)
        from app.problem_review import ProblemReview
        self.problem_review = ProblemReview(self)
        from app.bank_periods import BankPeriods
        self.bank_periods = BankPeriods(self)
        from app.material_guidance import MaterialGuidance
        self.material_guidance = MaterialGuidance(self)

    # ---------- scope, time and immutable source ----------

    def create_scope(self, scope: Scope, actor_id: str = "system") -> dict[str, Any]:
        scope_id = self._scope_id(scope)
        existing = self.store.list_objects(ObjectType.SCOPE.value, scope)
        book_object_id = self._book_object_id(scope)
        period_object_id = self._period_object_id(scope)
        baseline_object_id = self._baseline_object_id(scope)
        scope_object = existing[-1] if existing else self.store.create_initial_object(
            ObjectType.SCOPE.value,
            scope,
            {"scope": scope.model_dump(), "scope_id": scope_id, "current_run_id": None},
            status="ACTIVE",
            created_by=actor_id,
            object_id=scope_id,
        )
        try:
            self.store.get_object(book_object_id, scope)
        except KeyError:
            self.store.create_initial_object(
                ObjectType.ACCOUNTING_BOOK.value, scope,
                {"ledger_id": scope.ledger_id, "name": "主账套", "scope_id": scope_id},
                status="OPEN", created_by=actor_id, object_id=book_object_id)
        try:
            self.store.get_object(period_object_id, scope)
        except KeyError:
            self.store.create_initial_object(
                ObjectType.ACCOUNTING_PERIOD.value, scope,
                {"period_id": scope.accounting_period_id, "period": scope.accounting_period_id, "scope_id": scope_id, "current_run_id": None},
                status="OPEN", created_by=actor_id, object_id=period_object_id)
        try:
            self.store.get_object(baseline_object_id, scope)
        except KeyError:
            self.store.create_initial_object(
                ObjectType.BASELINE.value, scope,
                {"baseline_id": scope.baseline_id, "period": scope.accounting_period_id, "opening_balance_source": None,
                 "opening_balance_verified": False, "tax_policy_version": "cn-vat-2026.1", "rules": []},
                status="DRAFT", created_by=actor_id, object_id=baseline_object_id)
        period = self.store.get_object(period_object_id, scope)
        baseline = self.store.get_object(baseline_object_id, scope)
        self.store.add_relation(RelationType.BELONGS_TO.value, baseline, period, created_by=actor_id)
        self.store.add_relation(RelationType.BELONGS_TO.value, scope_object, period, created_by=actor_id)
        if not existing:
            self.store.add_audit("SCOPE_CREATED", actor_id, scope, object_type=ObjectType.SCOPE.value, object_id=scope_id, object_version=1, after=scope.model_dump())
        else:
            self.store.add_audit("SCOPE_REPAIRED", actor_id, scope, object_type=ObjectType.SCOPE.value, object_id=scope_id, object_version=scope_object["version"], after={"period": period, "baseline": baseline}, reason="补齐历史遗留的账套、期间或基线对象")
        return scope_object

    def confirm_baseline(self, scope: Scope, *, actor_id: str, expected_version: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_period_open(scope)
        baseline_id = self._baseline_object_id(scope)
        baseline = self.store.get_object(baseline_id, scope)
        if baseline["version"] != expected_version:
            raise VersionConflict()
        historical_confirmation = (payload or {}) if "historical_preparation" in (payload or {}) else None
        if historical_confirmation is not None:
            payload = self.historical.confirmation_inputs(scope, historical_confirmation)
        inputs, totals = self._checked_baseline_inputs(scope, payload or {}, allow_historical=historical_confirmation is not None)
        data = deepcopy(baseline["data"])
        close_lines = [
            {
                "account_code": item["account_code"],
                "account_name": item["account_name"],
                "requires_auxiliary": item["requires_auxiliary"],
                "auxiliary": item.get("auxiliary", []),
                "closing_debit": item["closing_debit"],
                "closing_credit": item["closing_credit"],
                "source_anchor": item["source_anchor"],
            }
            for item in inputs["balances"]
        ]
        close_snapshot = {
            "period": inputs["prior_period"],
            "source": inputs["close_source"],
            "lines": close_lines,
            "totals": {"debit": totals["debit"], "credit": totals["credit"]},
        }
        close_snapshot["snapshot_digest"] = digest(close_snapshot)
        data.update({"confirmed_inputs": inputs, "balance_totals": totals, "validation_version": VALIDATION_VERSION,
                     "opening_balance_source": inputs["balance_source"], "prior_close_source": inputs["close_source"],
                     "prior_close_snapshot": close_snapshot})
        data["opening_balance_verified"] = True
        if historical_confirmation is not None:
            data["historical_confirmation"] = deepcopy(historical_confirmation)
        else:
            data.pop("historical_confirmation", None)
        data["confirmed_by"] = actor_id
        data["decision_time"] = utcnow()
        confirmed = self.store.revise_object(baseline_id, expected_version, scope, data, status="CONFIRMED", created_by=actor_id)
        period = self.store.get_object(self._period_object_id(scope), scope)
        self.store.add_relation(RelationType.VALIDATES.value, confirmed, period, evidence=[confirmed["object_id"]], created_by=actor_id, status="CONFIRMED")
        for ref in (inputs["balance_source"], inputs["close_source"]):
            source = self.store.get_object(ref["artifact_id"], scope, ref["version"])
            self.store.add_relation(RelationType.DERIVED_FROM.value, confirmed, source, created_by=actor_id, status="CONFIRMED")
        if historical_confirmation is not None:
            preparation = self.historical.get(scope)
            self.store.add_relation(RelationType.DERIVED_FROM.value, confirmed, preparation, created_by=actor_id, status="CONFIRMED")
            for ref in preparation["data"]["sources"]:
                source = self.store.get_object(ref["artifact_id"], scope, ref["version"])
                self.store.add_relation(RelationType.DERIVED_FROM.value, confirmed, source, created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("BASELINE_CONFIRMED", actor_id, scope, object_type=confirmed["object_type"], object_id=confirmed["object_id"], object_version=confirmed["version"], before=baseline, after=confirmed, reason="人工确认账套基线")
        return confirmed

    def create_artifact(self, value: ArtifactInput, *, actor_id: str) -> dict[str, Any]:
        self._ensure_period_open(value.scope)
        max_encoded_bytes = 4 * ((MAX_BYTES + 2) // 3)
        if len(value.content_base64) > max_encoded_bytes:
            raise DomainError("原始资料超过 16MB 大小限制，请拆分资料", "ARTIFACT_TOO_LARGE", 422)
        try:
            content = base64.b64decode(value.content_base64, validate=True)
        except Exception as exc:
            raise DomainError("原始资料不是合法 Base64 内容", "INVALID_ARTIFACT", 422) from exc
        if len(content) > MAX_BYTES:
            raise DomainError("原始资料超过 16MB 大小限制，请拆分资料", "ARTIFACT_TOO_LARGE", 422)
        file_hash = hashlib.sha256(content).hexdigest()
        existing = [item for item in self.store.list_objects(ObjectType.SOURCE_ARTIFACT.value, value.scope) if item["data"].get("sha256") == file_hash and item["status"] != "ARCHIVED"]
        if existing:
            self.store.add_audit("ARTIFACT_DEDUPLICATED", actor_id, value.scope, object_type=ObjectType.SOURCE_ARTIFACT.value, object_id=existing[0]["object_id"], object_version=existing[0]["version"], reason="同哈希资料重复上传，复用原始对象")
            if existing[0]["data"].get("source_purpose") == "historical_reference":
                self.historical.enqueue(value.scope, actor_id)
            elif value.source_purpose == "historical_reference":
                raise PreconditionFailed("同一原件已按其他用途保存，请先核对用途，不能通过重复上传暗中更改分类")
            return existing[0]
        relative_path = f"{file_hash[:2]}/{file_hash}.bin"
        file_path = self.store.database.settings.storage_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and file_path.read_bytes() != content:
            raise DomainError("文件哈希冲突，拒绝覆盖已有原始资料", "HASH_COLLISION", 409)
        file_path.write_bytes(content)
        observed_period = value.observed_period or value.scope.accounting_period_id
        artifact = self.store.create_initial_object(
            ObjectType.SOURCE_ARTIFACT.value,
            value.scope,
            {
                "filename": value.filename,
                "sha256": file_hash,
                "bytes": len(content),
                "storage_path": relative_path,
                "source_channel": value.source_channel,
                "source_purpose": value.source_purpose,
                "uploaded_by": actor_id,
                "observed_time": utcnow(),
                "observed_period": observed_period,
                "period_check": "PASS" if observed_period == value.scope.accounting_period_id else "PERIOD_EXCEPTION",
                "mime_type": value.mime_type,
                "parse_status": "RECEIVED",
                "disposition": SourceDisposition.UNASSESSED.value,
            },
            status="ACTIVE" if observed_period == value.scope.accounting_period_id else "PERIOD_EXCEPTION",
            created_by=actor_id,
        )
        self.store.add_audit("ARTIFACT_RECEIVED", actor_id, value.scope, object_type=artifact["object_type"], object_id=artifact["object_id"], object_version=1, after=artifact, reason="原始资料只追加保存")
        if value.source_purpose == "historical_reference":
            self.historical.enqueue(value.scope, actor_id)
        return artifact

    def archive_artifact(self, scope: Scope, *, artifact_id: str, actor_id: str, expected_version: int) -> dict[str, Any]:
        artifact = self.store.get_object(artifact_id, scope)
        if artifact["version"] != expected_version:
            raise VersionConflict()
        data = deepcopy(artifact["data"])
        data["disposition"] = "ARCHIVED"
        archived = self.store.revise_object(artifact_id, expected_version, scope, data, status="ARCHIVED", created_by=actor_id)
        self._invalidate_source_dependents(scope, artifact_id=artifact_id, actor_id=actor_id, reason="原始资料已归档，依赖它的校验许可失效")
        self.store.add_audit("ARTIFACT_ARCHIVED", actor_id, scope, object_type=artifact["object_type"], object_id=artifact_id, object_version=archived["version"], before=artifact, after=archived, reason="按政策归档，原始内容仍保留")
        return archived

    def parse_artifact(self, scope: Scope, *, artifact_id: str, actor_id: str, expected_version: int, payload: dict[str, Any], _mapped=None, _mapping_id=None, _plan_ref=None) -> dict[str, Any]:
        """Parse an immutable workbook into traceable facts inside one command transaction."""
        self._ensure_period_open(scope)
        artifact = self.store.get_object(artifact_id, scope)
        if artifact["object_type"] != ObjectType.SOURCE_ARTIFACT.value:
            raise PreconditionFailed("解析目标必须是原始资料")
        if artifact["version"] != expected_version:
            raise VersionConflict()
        if artifact["status"] != "ACTIVE" or artifact["data"].get("period_check") != "PASS":
            raise PreconditionFailed("只有当前期间有效原始资料可以解析")
        try:
            options = ParseOptions.model_validate(payload)
        except ValidationError as exc:
            raise PreconditionFailed("解析选项无效，客户端不能提交解析结果或未知资料类型") from exc
        root = self.store.database.settings.storage_path.resolve()
        path = (root / artifact["data"]["storage_path"]).resolve()
        if not path.is_file() or not path.is_relative_to(root) or path == root:
            raise PreconditionFailed("原始资料存储路径无效或文件缺失")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact["data"].get("sha256"):
            raise PreconditionFailed("原始资料哈希校验失败，拒绝解析被篡改内容")
        previous_options = artifact["data"].get("parse_options")
        current_options = options.model_dump(exclude_none=True)
        if previous_options is not None and previous_options != current_options:
            raise PreconditionFailed("同一原件已经按其他资料类型解析，需先通过明确的重新解析流程处理")
        rebound_plan = None
        if artifact['data'].get('plan_ref') and _plan_ref is None:
            if _mapped is None or not _mapped.get('bank_account_binding'):
                raise PreconditionFailed('原件已绑定结构方案，请通过结构方案预览及确认重新提取')
            # Account confirmation may attach identity, never replace plan rows
            # with the caller's built-in extraction.
            replayed = self.parse_plans.replay(scope,artifact)
            binding = _mapped['bank_account_binding']
            account = next((a for a in self.bank_accounts.accounts(scope) if a['object_id']==binding['account_id']),None)
            if not account or account['version']!=binding['account_version']:
                raise VersionConflict('银行账户已变化，请重新核对归属')
            _mapped = self.bank_accounts.attach(artifact,replayed,account,binding['identity'],
                binding['confirmed_by'],binding.get('automatic',False),binding.get('note',''))
            _plan_ref = deepcopy(artifact['data']['plan_ref'])
            rebound_plan = self.store.get_object(_plan_ref['plan_id'],scope)
            _plan_ref['plan_version']=rebound_plan['version']+1
        if artifact['data'].get('payroll_mapping_id') and _mapping_id is None:
            raise PreconditionFailed('原件已绑定工资字段对应，请通过工资格式方案重新提取')
        if _plan_ref is not None and (_mapped is None or _mapping_id is not None):
            raise PreconditionFailed('结构方案必须使用本地执行结果，不能混用工资绑定')
        if _mapped is None and artifact["data"].get("parse_version") == PARSER_VERSION and artifact["data"].get("parse_status") in {"PARSED", "PARSED_WITH_ISSUES"}:
            facts = [self.store.get_object(fact_id, scope) for fact_id in artifact["data"].get("parsed_fact_ids", [])]
            counts = artifact["data"].get("parse_counts", {"rows": len(facts), "parsed": 0, "needs_review": 0, "period_exception": 0})
            return {"artifact": artifact, "facts": facts, "sheets": artifact["data"].get("parse_sheets", []), "counts": counts, "errors": artifact["data"].get("parse_errors", [])}
        extracted = None
        try:
            extracted = _mapped if _mapped is not None else extract_workbook(content, options, scope.accounting_period_id)
            if _mapped is None and options.document_kind == 'bank_statement':
                extracted = self.bank_accounts.prepare(scope, artifact, extracted)
            if extracted.get('checks',{}).get('overall')=='REVIEW':
                raise ExtractionError('全量原件对账存在差异或疑似汇总行，请核对解析结构')
        except ExtractionError as exc:
            for old in self.store.list_objects(ObjectType.FACT_RECORD.value,scope):
                if old['data'].get('source_artifact_id')==artifact_id and old['status']!='SUPERSEDED':
                    self.store.revise_object(old['object_id'],old['version'],scope,{**old['data'],'superseded_by_parser':PARSER_VERSION},status='SUPERSEDED',created_by=actor_id)
            self._invalidate_source_dependents(scope,artifact_id=artifact_id,actor_id=actor_id,reason='原件重解析失败，旧校验失效')
            data = deepcopy(artifact["data"])
            data.update({"parse_status": "FAILED", "parse_version": PARSER_VERSION, "parse_options": current_options, "parse_errors": [str(exc)], "parse_sheets": [], "parse_counts": {"rows": 0, "parsed": 0, "needs_review": 0, "period_exception": 0}, "parsed_fact_ids": [], "parsed_at": utcnow()})
            if extracted is not None and extracted.get('checks',{}).get('overall')=='REVIEW':
                data.update(parse_status='RECONCILIATION_FAILED',parse_checks=extracted['checks'],parse_sheets=extracted['sheets'])
            failed = self.store.revise_object(artifact_id, expected_version, scope, data, status="ACTIVE", created_by=actor_id)
            self.store.add_audit("ARTIFACT_PARSE_FAILED", actor_id, scope, object_type=artifact["object_type"], object_id=artifact_id, object_version=failed["version"], before=artifact, after=failed, reason=str(exc))
            self.problem_review.signal(scope, actor_id)
            return {"artifact": failed, "facts": [], "sheets": [], "counts": data["parse_counts"], "errors": [str(exc)]}

        facts, fact_ids = [], []
        for record in extracted["records"]:
            parsed_input = FactInput(
                scope=scope,
                source_artifact_id=artifact_id,
                source_anchor=SourceAnchor.model_validate(record["source_anchor"]),
                record_type=record["record_type"],
                original_value=record["original_value"],
                normalized_value=record["normalized_value"],
                parser_version=PARSER_VERSION,
                extraction_confidence=record["extraction_confidence"],
                period_check=record["period_check"],
            )
            identity=digest({'sha256':artifact['data']['sha256'],'anchor':record['source_anchor'],'record_type':record['record_type']})
            existing=[f for f in self.store.list_objects(ObjectType.FACT_RECORD.value,scope) if self._fact_source_identity(scope,f)==identity]
            if len(existing)>1:
                raise PreconditionFailed('同一来源有重复事实，请先核对')
            fact=existing[0] if existing else self._create_fact_record(parsed_input,actor_id=actor_id)
            fact_data=deepcopy(fact['data'])
            fact_data.update({k:getattr(parsed_input,k) for k in ('original_value','normalized_value','parser_version','extraction_confidence','period_check')})
            fact_data.update({'field_sources':record['field_sources'],'extraction_issues':record['extraction_issues'],'source_artifact_version':expected_version+1})
            if _plan_ref is not None:
                fact_data.update({k:_plan_ref[k] for k in ('plan_id','plan_version','plan_origin')})
                fact_data['plan_provenance']=record.get('plan_provenance',{})
            status='PERIOD_EXCEPTION' if record['period_check']!='PASS' else 'NEEDS_REVIEW' if record['extraction_issues'] else 'PARSED'
            if fact_data!=fact['data'] or status!=fact['status']:
                before=fact
                fact=self.store.revise_object(fact['object_id'],fact['version'],scope,fact_data,status=status,created_by=actor_id)
                self.store.add_audit('FACT_SOURCE_REEXTRACTED',actor_id,scope,object_id=fact['object_id'],object_version=fact['version'],before=before,after=fact,reason='重新读取原件生成新版本，不覆盖原始值')
            facts.append(fact)
            fact_ids.append(fact["object_id"])
        counts = {"rows": len(extracted["records"]), "parsed": sum(f["status"] == "PARSED" for f in facts), "needs_review": sum(f["status"] == "NEEDS_REVIEW" for f in facts), "period_exception": sum(f["status"] == "PERIOD_EXCEPTION" for f in facts)}
        errors = extracted["errors"]
        for old_id in set(artifact['data'].get('parsed_fact_ids',[]))-set(fact_ids):
            old=self.store.get_object(old_id,scope)
            self.store.revise_object(old_id,old['version'],scope,{**old['data'],'superseded_by_parser':PARSER_VERSION},status='SUPERSEDED',created_by=actor_id)
        self._invalidate_source_dependents(scope,artifact_id=artifact_id,actor_id=actor_id,reason='原件已重新提取，旧依赖校验失效')
        parse_status = "PARSED" if facts and not errors and counts["needs_review"] == 0 and counts["period_exception"] == 0 else ("PARSED_WITH_ISSUES" if facts else "FAILED")
        data = deepcopy(artifact["data"])
        data.update({"parse_status": parse_status, "parse_version": PARSER_VERSION, "parse_options": current_options, "parse_errors": errors, "parse_sheets": extracted["sheets"], "parse_counts": counts, "parsed_fact_ids": fact_ids, "parsed_at": utcnow(), 'parse_checks':extracted.get('checks',{})})
        if _mapping_id:data['payroll_mapping_id']=_mapping_id
        if _plan_ref is not None:data['plan_ref']=deepcopy(_plan_ref)
        data.pop('bank_account_binding',None)
        if extracted.get('bank_account_binding'):
            data['bank_account_binding']=extracted['bank_account_binding']
        parsed_artifact = self.store.revise_object(artifact_id, expected_version, scope, data, status="ACTIVE", created_by=actor_id)
        if rebound_plan is not None:
            self.store.revise_object(rebound_plan['object_id'],rebound_plan['version'],scope,
                {**rebound_plan['data'],'applied_artifact_version':parsed_artifact['version']},status='APPLIED',created_by=actor_id)
        self.store.add_audit("ARTIFACT_PARSED", actor_id, scope, object_type=artifact["object_type"], object_id=artifact_id, object_version=parsed_artifact["version"], before=artifact, after=parsed_artifact, evidence=fact_ids, reason="确定性表格解析，保留单元格定位和人工复核缺口")
        self.problem_review.signal(scope, actor_id)
        return {"artifact": parsed_artifact, "facts": facts, "sheets": extracted["sheets"], "counts": counts, "errors": errors}

    def baseline_candidate(self, scope: Scope, *, balance_artifact_id: str, close_artifact_id: str) -> dict[str, Any]:
        """Compare two prior-period balance workbooks without creating facts.

        Baseline sources are intentionally stored as PERIOD_EXCEPTION for the
        current Scope. They must not enter current-period business facts, so
        this read-only comparison has its own path and still requires an
        explicit confirm_baseline command before any accounting action.
        """
        prior = previous_period(scope.accounting_period_id)
        opening_source, opening = self._read_baseline_workbook(scope, balance_artifact_id, prior)
        close_source, closing = self._read_baseline_workbook(scope, close_artifact_id, prior)
        issues = []
        issues.extend(self._baseline_extraction_issues("期初余额", opening))
        issues.extend(self._baseline_extraction_issues("上期结账", closing))
        opening_rows, opening_issues = self._baseline_rows(opening)
        closing_rows, closing_issues = self._baseline_rows(closing)
        issues.extend(opening_issues)
        issues.extend(closing_issues)

        all_keys = sorted(set(opening_rows) | set(closing_rows), key=lambda value: (value[0], value[1]))
        comparisons = []
        for key in all_keys:
            left = opening_rows.get(key)
            right = closing_rows.get(key)
            row_issues = []
            if left is None:
                row_issues.append("期初余额缺少该科目行")
            if right is None:
                row_issues.append("上期结账缺少该科目行")
            if left and right:
                if left["normalized_value"].get("account_name") != right["normalized_value"].get("account_name"):
                    row_issues.append("科目名称不一致")
                for field in ("opening_debit", "opening_credit"):
                    opening_value = left["normalized_value"].get(field)
                    close_field = field.replace("opening_", "closing_")
                    close_value = right["normalized_value"].get(close_field)
                    if opening_value is None or close_value is None:
                        row_issues.append(f"{field}或{close_field}缺少可核验金额")
                    elif Decimal(opening_value) != Decimal(close_value):
                        row_issues.append(f"{field}与{close_field}不一致")
            comparisons.append({
                "account_code": key[0], "auxiliary_key": key[1] or None,
                "opening": self._baseline_line_view(left), "closing": self._baseline_line_view(right),
                "status": "MATCH" if not row_issues else "REVIEW", "issues": row_issues,
            })
            issues.extend(f"{key[0]}{(' / ' + key[1]) if key[1] else ''}：{item}" for item in row_issues)

        balances = []
        for account_code in sorted({key[0] for key in all_keys}):
            account_comparisons = [item for item in comparisons if item["account_code"] == account_code]
            opening_items = [item for item in account_comparisons if item["opening"]]
            closing_items = [item for item in account_comparisons if item["closing"]]
            opening_names = {item["opening"]["account_name"] for item in opening_items}
            closing_names = {item["closing"]["account_name"] for item in closing_items}
            account_name = next(iter(opening_names or closing_names), account_code)
            opening_values = [item["opening"] for item in opening_items]
            closing_values = [item["closing"] for item in closing_items]
            auxiliary_keys = sorted({item["auxiliary_key"] for item in account_comparisons if item["auxiliary_key"]})
            requires_auxiliary = any(bool(item.get("requires_auxiliary")) for item in opening_values + closing_values)
            if requires_auxiliary and not auxiliary_keys:
                issues.append(f"{account_code}：标记需要辅助核算但没有辅助明细")
            if len(opening_names | closing_names) > 1:
                issues.append(f"{account_code}：同一科目出现多个名称")

            opening_debit = self._sum_baseline_values(opening_values, "opening_debit")
            opening_credit = self._sum_baseline_values(opening_values, "opening_credit")
            closing_debit = self._sum_baseline_values(closing_values, "closing_debit")
            closing_credit = self._sum_baseline_values(closing_values, "closing_credit")
            auxiliary = []
            for auxiliary_key in auxiliary_keys:
                item = next((item for item in account_comparisons if item["auxiliary_key"] == auxiliary_key), None)
                if not item or not item["opening"] or not item["closing"]:
                    continue
                auxiliary.append({
                    "key": auxiliary_key,
                    "closing_debit": item["closing"]["closing_debit"], "closing_credit": item["closing"]["closing_credit"],
                    "opening_debit": item["opening"]["opening_debit"], "opening_credit": item["opening"]["opening_credit"],
                    "source_anchor": item["opening"]["source_anchor"],
                })
            first_opening = opening_items[0]["opening"] if opening_items else None
            balances.append({
                "account_code": account_code, "account_name": account_name,
                "closing_debit": closing_debit, "closing_credit": closing_credit,
                "opening_debit": opening_debit, "opening_credit": opening_credit,
                "requires_auxiliary": requires_auxiliary, "auxiliary": auxiliary,
                "source_anchor": (first_opening or (closing_items[0]["closing"] if closing_items else {})).get("source_anchor", {"row": 1}),
            })

        totals = {
            "opening_debit": self._sum_baseline_values(balances, "opening_debit"),
            "opening_credit": self._sum_baseline_values(balances, "opening_credit"),
            "closing_debit": self._sum_baseline_values(balances, "closing_debit"),
            "closing_credit": self._sum_baseline_values(balances, "closing_credit"),
        }
        if totals["opening_debit"] is None or totals["opening_credit"] is None:
            issues.append("期初合计存在缺失金额，不能完成试算")
        elif totals["opening_debit"] != totals["opening_credit"]:
            issues.append("期初试算借贷不平衡")
        if totals["closing_debit"] is None or totals["closing_credit"] is None:
            issues.append("上期结账合计存在缺失金额，不能完成试算")
        elif totals["closing_debit"] != totals["closing_credit"]:
            issues.append("上期结账试算借贷不平衡")

        def source_ref(source, label):
            first = next((item for item in (opening["records"] if label == "balance" else closing["records"])), None)
            anchor = (first or {}).get("source_anchor", {"row": 1})
            return {"artifact_id": source["object_id"], "version": source["version"], "anchor": anchor}

        payload = {
            "prior_period": prior,
            "close_reference": f"artifact:{close_source['object_id']}:v{close_source['version']}",
            "balance_source": source_ref(opening_source, "balance"),
            "close_source": source_ref(close_source, "close"),
            "currency": "CNY", "completeness_confirmed": False, "balances": balances,
        }
        unique_issues = list(dict.fromkeys(issues))
        return {
            "status": "READY_FOR_CONFIRMATION" if not unique_issues and balances else "BLOCKED",
            "prior_period": prior,
            "sources": {"balance": self._baseline_source_summary(opening_source, opening), "close": self._baseline_source_summary(close_source, closing)},
            "line_count": len(comparisons), "matched_lines": sum(item["status"] == "MATCH" for item in comparisons),
            "review_lines": sum(item["status"] != "MATCH" for item in comparisons),
            "comparisons": comparisons, "totals": totals, "issues": unique_issues,
            "confirmation_payload": payload,
        }

    def _read_baseline_workbook(self, scope: Scope, artifact_id: str, prior: str):
        source = self.store.get_object(artifact_id, scope)
        if source["object_type"] != ObjectType.SOURCE_ARTIFACT.value or source["status"] not in {"ACTIVE", "PERIOD_EXCEPTION"}:
            raise PreconditionFailed("基线来源必须是当前范围内未归档的原始资料")
        if source["data"].get("observed_period") != prior:
            raise PreconditionFailed("基线来源必须属于紧邻上期")
        root = self.store.database.settings.storage_path.resolve()
        path = (root / source["data"]["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source["data"].get("sha256"):
            raise PreconditionFailed("基线来源不存在、越界或内容哈希已变化")
        try:
            extracted = extract_workbook(path.read_bytes(), ParseOptions(document_kind="opening_balance"), prior)
        except ExtractionError as exc:
            raise PreconditionFailed("基线来源无法按期初余额表解析：" + str(exc)) from exc
        return source, extracted

    @staticmethod
    def _baseline_extraction_issues(label: str, extracted: dict[str, Any]) -> list[str]:
        issues = [f"{label}：{item}" for item in extracted.get("errors", [])]
        for record in extracted.get("records", []):
            issues.extend(f"{label}第{record['source_anchor'].get('row', '?')}行：{item}" for item in record.get("extraction_issues", []))
        return issues

    @staticmethod
    def _baseline_rows(extracted: dict[str, Any]):
        rows, issues = {}, []
        for record in extracted.get("records", []):
            normalized = record["normalized_value"]
            code = normalized.get("account_code")
            auxiliary_key = normalized.get("auxiliary_key") or ""
            if not code:
                issues.append(f"第{record['source_anchor'].get('row', '?')}行：缺少科目编码")
                continue
            key = (str(code), str(auxiliary_key))
            if key in rows:
                issues.append(f"{code}{(' / ' + auxiliary_key) if auxiliary_key else ''}：来源出现重复行")
                continue
            rows[key] = record
        return rows, issues

    @staticmethod
    def _baseline_line_view(record):
        if not record:
            return None
        value = record["normalized_value"]
        return {"account_name": value.get("account_name"), "requires_auxiliary": value.get("requires_auxiliary"),
                "opening_debit": value.get("opening_debit"), "opening_credit": value.get("opening_credit"),
                "closing_debit": value.get("closing_debit"), "closing_credit": value.get("closing_credit"),
                "source_anchor": record["source_anchor"]}

    @staticmethod
    def _sum_baseline_values(items, field):
        values = [item.get(field) for item in items]
        if not values or any(value is None for value in values):
            return None
        return format(sum((Decimal(value) for value in values), Decimal(0)), ".2f")

    @staticmethod
    def _baseline_source_summary(source, extracted):
        return {"artifact_id": source["object_id"], "version": source["version"], "filename": source["data"].get("filename"),
                "observed_period": source["data"].get("observed_period"), "records": len(extracted.get("records", [])),
                "sheets": extracted.get("sheets", [])}

    def create_fact_record(self, value: FactInput, *, actor_id: str) -> dict[str, Any]:
        # Serialize lookup + insert, including calls made outside a Command transaction.
        with self.store.database.transaction():
            return self._create_fact_record(value, actor_id=actor_id)

    def create_fact_from_api(self, value: FactInput, *, actor_id: str) -> dict[str, Any]:
        """Compatibility read of an already parsed fact; new facts use parse_artifact."""
        self._ensure_period_open(value.scope)
        artifact = self.store.get_object(value.source_artifact_id, value.scope)
        if artifact["status"] != "ACTIVE" or artifact["data"].get("period_check") != "PASS":
            return self.create_fact_record(value, actor_id=actor_id)
        anchor = value.source_anchor.model_dump(exclude_none=True)
        source_identity = digest({"sha256": artifact["data"]["sha256"], "anchor": anchor, "record_type": value.record_type})
        existing = [fact for fact in self.store.list_objects(ObjectType.FACT_RECORD.value, value.scope) if self._fact_source_identity(value.scope, fact) == source_identity]
        if not existing:
            raise PermissionDenied("事实只能由原始资料解析命令创建，不能通过接口直接注入解析结果")
        return self.create_fact_record(value, actor_id=actor_id)

    def _create_fact_record(self, value: FactInput, *, actor_id: str) -> dict[str, Any]:
        self._ensure_period_open(value.scope)
        artifact = self.store.get_object(value.source_artifact_id, value.scope)
        if artifact["object_type"] != ObjectType.SOURCE_ARTIFACT.value or artifact["status"] != "ACTIVE" or artifact["data"].get("period_check") != "PASS":
            raise PreconditionFailed("来源必须为当前期间有效原始资料，归档或期间异常资料不能进入正式事实判断")
        anchor = value.source_anchor.model_dump(exclude_none=True)
        if not anchor:
            raise PreconditionFailed("缺少原始资料定位，不能进入正式业务判断")
        source_identity = digest({"sha256": artifact["data"]["sha256"], "anchor": anchor, "record_type": value.record_type})
        existing = [f for f in self.store.list_objects(ObjectType.FACT_RECORD.value, value.scope)
                    if self._fact_source_identity(value.scope, f) == source_identity]
        if len(existing) > 1:
            raise PreconditionFailed("已有重复来源事实，需先处理冲突，不能自动选择其中一条")
        if existing:
            fact = existing[0]
            fields = ("original_value", "normalized_value", "parser_version", "extraction_confidence", "period_check")
            if any(fact["data"].get(key) != getattr(value, key) for key in fields):
                raise PreconditionFailed("同一来源定位已有不同解析结果，请通过重新解析命令创建新版本")
            self.store.add_audit("FACT_DEDUPLICATED", actor_id, value.scope, object_type=fact["object_type"], object_id=fact["object_id"], object_version=fact["version"], reason="复用同一来源定位的事实记录")
            return fact
        data = {
            "source_artifact_id": artifact["object_id"],
            "source_artifact_version": artifact["version"],
            "source_identity": source_identity,
            "source_anchor": anchor,
            "original_value": value.original_value,
            "normalized_value": value.normalized_value,
            "record_type": value.record_type,
            "parser_version": value.parser_version,
            "extraction_confidence": value.extraction_confidence,
            "period_check": value.period_check,
            "observed_time": utcnow(),
        }
        fact = self.store.create_initial_object(ObjectType.FACT_RECORD.value, value.scope, data, status="PARSED" if value.period_check == "PASS" else "PERIOD_EXCEPTION", created_by=actor_id)
        self.store.add_relation(RelationType.DERIVED_FROM.value, fact, artifact, created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("FACT_PARSED", actor_id, value.scope, object_type=fact["object_type"], object_id=fact["object_id"], object_version=1, after=fact, evidence=[artifact["object_id"]], reason="保留原始值与定位")
        return fact

    def reparse_fact(self, scope: Scope, *, fact_id: str, actor_id: str, expected_version: int, parser_version: str, normalized_value: dict[str, Any]) -> dict[str, Any]:
        self._ensure_period_open(scope)
        fact = self.store.get_object(fact_id, scope)
        if fact["version"] != expected_version:
            raise VersionConflict()
        artifact = self.store.get_object(fact["data"]["source_artifact_id"], scope)
        if artifact['data'].get('parse_options',{}).get('document_kind')=='bank_statement':
            if self.bank_accounts.candidate(scope,artifact)['status']!='LINKED' or normalized_value.get('bank_account_ref')!=fact['data']['normalized_value'].get('bank_account_ref'):
                raise PreconditionFailed('不能逐条修改或绕过本方账户确认；请通过整份流水账户确认处理')
        if artifact["status"] != "ACTIVE" or fact['status']=='SUPERSEDED' or fact["data"].get("period_check") != "PASS" or artifact['data'].get('parse_status')=='FAILED' or ('parsed_fact_ids' in artifact['data'] and fact_id not in artifact['data']['parsed_fact_ids']):
            raise PreconditionFailed("失效来源或期间异常事实不能通过普通重解析变为有效")
        data = deepcopy(fact["data"])
        data.update({"normalized_value": normalized_value, "parser_version": parser_version, "reparsed_at": utcnow()})
        revised = self.store.revise_object(fact_id, expected_version, scope, data, status="PARSED", created_by=actor_id)
        self._invalidate_source_dependents(scope, fact_id=fact_id, fact_version=revised["version"], actor_id=actor_id, reason="事实重新解析，依赖它的校验许可失效")
        self.store.add_audit("FACT_REPARSED", actor_id, scope, object_type=fact["object_type"], object_id=fact_id, object_version=revised["version"], before=fact, after=revised, reason="重新解析生成新版本，不覆盖旧事实")
        return revised

    def _invalidate_source_dependents(self, scope: Scope, *, actor_id: str, reason: str,
                                      artifact_id: str | None = None, fact_id: str | None = None,
                                      fact_version: int | None = None) -> None:
        """Propagate source changes without deleting history or silently reusing permits."""
        fact_ids = set()
        for fact in self.store.list_objects(ObjectType.FACT_RECORD.value, scope):
            if fact_id and fact["object_id"] == fact_id:
                fact_ids.add(fact["object_id"])
            elif artifact_id and fact["data"].get("source_artifact_id") == artifact_id:
                fact_ids.add(fact["object_id"])
        for evidence in self.store.list_objects(ObjectType.EVIDENCE.value, scope):
            related_fact = evidence["data"].get("fact_record_id")
            if related_fact not in fact_ids:
                continue
            data = deepcopy(evidence["data"])
            data.update({"expired": True, "invalidated_at": utcnow(), "invalidated_reason": reason})
            if fact_version is not None:
                data["invalidated_by_fact_version"] = fact_version
            if evidence["status"] != "EXPIRED" or data != evidence["data"]:
                self.store.revise_object(evidence["object_id"], evidence["version"], scope, data, status="EXPIRED", created_by=actor_id)
        for group in self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope):
            members = set(group["data"].get("member_fact_ids", []))
            affected = members.intersection(fact_ids)
            if not affected or group["status"] in {"VOID", "MERGED", "ARCHIVED"}:
                continue
            data = deepcopy(group["data"])
            data.update({"reconciliation_status": "STALE", "reconciliation_invalidated_at": utcnow(),
                         "reconciliation_invalidated_reason": reason, "reconciliation_basis": None,
                         "invalidated_fact_ids": sorted(affected)})
            # Keep the business-group lifecycle status until deterministic
            # reconciliation is rerun. The stale permit is visible through
            # reconciliation_status and prevents downstream actions, while a
            # duplicate check can still return its precise diagnostic.
            revised_group = self.store.revise_object(group["object_id"], group["version"], scope, data, status=group["status"], created_by=actor_id)
            self.store.add_audit("DOWNSTREAM_PERMIT_INVALIDATED", actor_id, scope,
                                 object_type=revised_group["object_type"], object_id=revised_group["object_id"],
                                 object_version=revised_group["version"], before=group, after=revised_group,
                                 evidence=sorted(affected), reason=reason)

    # ---------- business facts, events and groups ----------

    def create_procurement_business(self, scope: Scope, *, fact_ids: list[str], business_identity: str, actor_id: str) -> dict[str, Any]:
        self._ensure_period_open(scope)
        if not fact_ids:
            raise PreconditionFailed("采购业务至少需要一条事实记录")
        if len(fact_ids) != len(set(fact_ids)):
            raise PreconditionFailed("同一事实不能重复加入业务组")
        facts = [self.store.get_object(item, scope) for item in fact_ids]
        if any(item["object_type"] != ObjectType.FACT_RECORD.value or item["status"] != "PARSED" or item["data"].get("period_check") != "PASS" for item in facts):
            raise PreconditionFailed("存在期间异常事实，不能建立正式采购业务")
        stable_identity = f"PURCHASE:{business_identity}"
        event = self._find_by_data(ObjectType.BUSINESS_EVENT.value, scope, "stable_identity", stable_identity)
        if event is None:
            event = self.store.create_initial_object(
                ObjectType.BUSINESS_EVENT.value,
                scope,
                {"stable_identity": stable_identity, "event_type": "PURCHASE", "business_identity": business_identity, "accounting_time": scope.accounting_period_id, "observed_time": utcnow(), "fact_ids": fact_ids},
                status="CANDIDATE",
                created_by=actor_id,
            )
        business_fact = self._find_by_data(ObjectType.BUSINESS_FACT.value, scope, "stable_identity", stable_identity)
        if business_fact is None:
            business_fact = self.store.create_initial_object(
                ObjectType.BUSINESS_FACT.value,
                scope,
                {"stable_identity": stable_identity, "business_type": "PURCHASE", "fact_ids": fact_ids, "accounting_period_id": scope.accounting_period_id, "status": "CANDIDATE"},
                status="CANDIDATE",
                created_by=actor_id,
            )
        self.store.add_relation(RelationType.DERIVED_FROM.value, event, business_fact, evidence=fact_ids, created_by=actor_id)
        for fact in facts:
            self.store.add_relation(RelationType.BELONGS_TO.value, fact, event, evidence=[fact["object_id"]], created_by=actor_id)
        group = self._find_by_data(ObjectType.PROCESSING_GROUP.value, scope, "stable_identity", stable_identity)
        if group is None:
            group = self.store.create_initial_object(
                ObjectType.PROCESSING_GROUP.value,
                scope,
                {"stable_identity": stable_identity, "business_identity": business_identity, "event_id": event["object_id"], "business_fact_id": business_fact["object_id"], "member_fact_ids": fact_ids, "required_fact_types": ["CONTRACT", "INVOICE", "STOCK_IN", "PAYMENT"], "source_dispositions": {item: SourceDisposition.UNASSESSED.value for item in fact_ids}, "lineage": [], "evidence_grade": "D", "missing_evidence": [], "reconciliation_status": "NOT_RUN", "delivery_status": "NOT_READY"},
                status="CANDIDATE",
                created_by=actor_id,
            )
            self.store.create_initial_object(ObjectType.PROCESSING_GROUP_REVISION.value, scope, {"group_id": group["object_id"], "revision": 1, "member_fact_ids": fact_ids, "reason": "初次候选分组", "lineage": []}, status="CURRENT", created_by=actor_id)
        else:
            current_ids = set(group["data"].get("member_fact_ids", []))
            for fact_id in fact_ids:
                if fact_id not in current_ids:
                    current_ids.add(fact_id)
            if current_ids != set(group["data"].get("member_fact_ids", [])):
                updated = deepcopy(group["data"])
                updated["member_fact_ids"] = sorted(current_ids)
                updated["business_identity"] = business_identity
                group = self.store.revise_object(group["object_id"], group["version"], scope, updated, status=group["status"], created_by=actor_id)
        return self._refresh_group(scope, group, actor_id=actor_id)

    def confirm_grouping(self, scope: Scope, *, group_id: str, actor_id: str, expected_version: int) -> dict[str, Any]:
        group = self.store.get_object(group_id, scope)
        if group["version"] != expected_version:
            raise VersionConflict()
        if group["status"] in {"BLOCKED", "SUSPENDED", "REVISED"}:
            raise PreconditionFailed("异常或已修订业务组不能直接确认分组")
        if group["data"].get("missing_evidence"):
            raise PreconditionFailed("业务组存在证据缺口，不能确认分组")
        if self._duplicate_facts(scope, group):
            raise PreconditionFailed("发现重复来源或外部业务事实，不能确认主归属")
        for other in self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope):
            if other["object_id"] != group_id and other["status"] in {"CONFIRMED", "READY"}:
                overlap = set(other["data"].get("member_fact_ids", [])) & set(group["data"].get("member_fact_ids", []))
                if overlap:
                    raise PreconditionFailed(f"事实已归属其他确认业务组: {', '.join(sorted(overlap))}")
        data = deepcopy(group["data"])
        data["confirmed_by"] = actor_id
        data["decision_time"] = utcnow()
        confirmed = self.store.revise_object(group_id, expected_version, scope, data, status="CONFIRMED", created_by=actor_id)
        data["source_dispositions"] = {key: SourceDisposition.ASSIGNED.value for key in data.get("source_dispositions", {})}
        confirmed = self.store.revise_object(group_id, confirmed["version"], scope, data, status="CONFIRMED", created_by=actor_id)
        for fact_id in data.get("member_fact_ids", []):
            fact = self.store.get_object(fact_id, scope)
            self.store.add_relation(RelationType.BELONGS_TO.value, fact, confirmed, evidence=[fact_id], created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("GROUPING_CONFIRMED", actor_id, scope, object_type=confirmed["object_type"], object_id=group_id, object_version=confirmed["version"], before=group, after=confirmed, evidence=data.get("member_fact_ids", []), reason="人工确认业务组主归属")
        return confirmed

    def suspend_group(self, scope: Scope, *, group_id: str, actor_id: str, expected_version: int, reason: str) -> dict[str, Any]:
        group = self.store.get_object(group_id, scope)
        if group["version"] != expected_version:
            raise VersionConflict()
        data = deepcopy(group["data"])
        data["suspense_reason"] = reason
        data["delivery_status"] = "BLOCKED"
        suspended = self.store.revise_object(group_id, expected_version, scope, data, status="SUSPENDED", created_by=actor_id)
        self.store.add_audit("GROUP_SUSPENDED", actor_id, scope, object_type=group["object_type"], object_id=group_id, object_version=suspended["version"], before=group, after=suspended, reason=reason)
        return suspended

    def split_group(self, scope: Scope, *, group_id: str, actor_id: str, expected_version: int, fact_ids: list[str], new_group_id: str | None = None) -> dict[str, Any]:
        group = self.store.get_object(group_id, scope)
        if group["version"] != expected_version:
            raise VersionConflict()
        if group["status"] in {"DELIVERED", "ARCHIVED", "MERGED", "VOID"} or self._group_has_active_delivery(scope, group_id):
            raise PreconditionFailed("已交付或已固定交付包的业务组不能拆分")
        if not fact_ids or not set(fact_ids).issubset(set(group["data"].get("member_fact_ids", []))):
            raise PreconditionFailed("拆分事实必须属于原业务组")
        if set(fact_ids) == set(group["data"].get("member_fact_ids", [])):
            raise PreconditionFailed("拆分必须为原业务组保留至少一条事实")
        new_data = deepcopy(group["data"])
        new_data.update({"member_fact_ids": fact_ids, "stable_identity": f"{group['data']['stable_identity']}:SPLIT:{digest(sorted(fact_ids))[:10]}", "lineage": [{"type": "SPLIT_FROM", "group_id": group_id, "version": group["version"]}]})
        new_group = self.store.create_initial_object(ObjectType.PROCESSING_GROUP.value, scope, new_data, status="CANDIDATE", created_by=actor_id, object_id=new_group_id)
        lineage = self.store.create_initial_object(ObjectType.PROCESSING_GROUP_REVISION.value, scope, {"group_id": new_group["object_id"], "revision": 1, "member_fact_ids": fact_ids, "reason": "人工拆分", "lineage": new_data["lineage"]}, status="CURRENT", created_by=actor_id)
        original_data = deepcopy(group["data"])
        original_data["member_fact_ids"] = [item for item in original_data.get("member_fact_ids", []) if item not in fact_ids]
        original_data["lineage"] = [{"type": "SPLIT_TO", "group_id": new_group["object_id"], "version": new_group["version"]}]
        original = self.store.revise_object(group_id, expected_version, scope, original_data, status="REVISED", created_by=actor_id)
        self._create_group_revision(scope, group_id, original_data["member_fact_ids"], reason="人工拆分后保留的原业务组成员", lineage=original_data["lineage"], actor_id=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, original, new_group, evidence=fact_ids, created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("GROUP_SPLIT", actor_id, scope, object_type=group["object_type"], object_id=group_id, object_version=original["version"], before=group, after={"original": original, "new_group": new_group, "lineage": lineage}, evidence=fact_ids, reason="业务组拆分生成新对象与谱系")
        return new_group

    def merge_groups(self, scope: Scope, *, group_ids: list[str], actor_id: str, new_group_id: str | None = None) -> dict[str, Any]:
        if len(group_ids) < 2:
            raise PreconditionFailed("合并至少需要两个业务组")
        groups = [self.store.get_object(item, scope) for item in group_ids]
        if any(item["status"] in {"DELIVERED", "ARCHIVED", "MERGED", "VOID"} or self._group_has_active_delivery(scope, item["object_id"]) for item in groups):
            raise PreconditionFailed("已交付业务组不能原地合并")
        fact_ids = sorted({fact_id for item in groups for fact_id in item["data"].get("member_fact_ids", [])})
        data = deepcopy(groups[0]["data"])
        data.update({"member_fact_ids": fact_ids, "stable_identity": f"MERGE:{digest(sorted(group_ids))[:16]}", "business_identity": f"MERGE:{digest(sorted(group_ids))[:16]}", "lineage": [{"type": "MERGED_FROM", "group_id": item["object_id"], "version": item["version"]} for item in groups]})
        merged = self.store.create_initial_object(ObjectType.PROCESSING_GROUP.value, scope, data, status="CANDIDATE", created_by=actor_id, object_id=new_group_id)
        self.store.create_initial_object(ObjectType.PROCESSING_GROUP_REVISION.value, scope, {"group_id": merged["object_id"], "revision": 1, "member_fact_ids": fact_ids, "reason": "人工合并", "lineage": data["lineage"]}, status="CURRENT", created_by=actor_id)
        for group in groups:
            source_data = deepcopy(group["data"])
            source_data.update({"merged_into_group_id": merged["object_id"], "merged_at": utcnow(), "delivery_status": "BLOCKED"})
            merged_source = self.store.revise_object(group["object_id"], group["version"], scope, source_data, status="MERGED", created_by=actor_id)
            self._create_group_revision(scope, group["object_id"], source_data.get("member_fact_ids", []), reason="人工合并后原业务组失效", lineage=source_data.get("lineage", []), actor_id=actor_id)
            self.store.add_relation(RelationType.GENERATES.value, merged_source, merged, evidence=group["data"].get("member_fact_ids", []), created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("GROUP_MERGED", actor_id, scope, object_type=merged["object_type"], object_id=merged["object_id"], object_version=1, before={"group_ids": group_ids}, after=merged, evidence=fact_ids, reason="业务组合并生成新对象与谱系")
        return merged

    def _create_group_revision(self, scope: Scope, group_id: str, fact_ids: list[str], *, reason: str, lineage: list[dict[str, Any]], actor_id: str) -> dict[str, Any]:
        revisions = [item for item in self.store.list_objects(ObjectType.PROCESSING_GROUP_REVISION.value, scope)
                     if item["data"].get("group_id") == group_id]
        number = max((int(item["data"].get("revision", 0)) for item in revisions), default=0) + 1
        return self.store.create_initial_object(ObjectType.PROCESSING_GROUP_REVISION.value, scope,
            {"group_id": group_id, "revision": number, "member_fact_ids": fact_ids, "reason": reason, "lineage": lineage},
            status="CURRENT", created_by=actor_id)

    def _group_has_active_delivery(self, scope: Scope, group_id: str) -> bool:
        return any(item["data"].get("group_id") == group_id and item["status"] not in {"VOID", "ARCHIVED"}
                   for item in self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope))

    def _refresh_group(self, scope: Scope, group: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        facts = [self.store.get_object(item, scope) for item in group["data"].get("member_fact_ids", [])]
        by_type = {item["data"].get("record_type"): item for item in facts}
        required = group["data"].get("required_fact_types", [])
        missing = [item for item in required if item not in by_type]
        complete = not missing and all(item["data"].get("source_anchor") for item in facts)
        grade = "A" if complete else "D"
        if complete:
            evidence_ids: list[str] = []
            for fact in facts:
                evidence = self._find_evidence_for_fact(scope, fact["object_id"])
                if evidence is None:
                    evidence = self.store.create_initial_object(
                        ObjectType.EVIDENCE.value,
                        scope,
                        {"fact_record_id": fact["object_id"], "fact_version": fact["version"], "source_artifact_id": fact["data"]["source_artifact_id"], "source_anchor": fact["data"]["source_anchor"], "claim_type": "FACT_SUPPORT", "grade": "A", "complete": True, "independent": True, "expired": False, "conflict": False, "human_confirmed": False},
                        status="VALID",
                        created_by=actor_id,
                    )
                    self.store.add_relation(RelationType.SUPPORTS.value, evidence, fact, evidence=[fact["object_id"]], created_by=actor_id, status="CONFIRMED")
                evidence_ids.append(evidence["object_id"])
                self.store.add_relation(RelationType.SUPPORTS.value, evidence, group, evidence=[fact["object_id"]], created_by=actor_id, status="PROPOSED")
        updated = deepcopy(group["data"])
        updated.update({"missing_evidence": missing, "evidence_grade": grade, "evidence_ids": evidence_ids if complete else [], "fact_type_index": sorted(by_type), "refreshed_at": utcnow()})
        if updated == group["data"]:
            return group
        return self.store.revise_object(group["object_id"], group["version"], scope, updated, status=group["status"], created_by=actor_id)

    def _find_evidence_for_fact(self, scope: Scope, fact_id: str) -> dict[str, Any] | None:
        fact = self.store.get_object(fact_id, scope)
        for item in self.store.list_objects(ObjectType.EVIDENCE.value, scope):
            evidence_version_matches = item["data"].get("fact_version") == fact["version"] or (fact["version"] == 1 and "fact_version" not in item["data"])
            if (item["data"].get("fact_record_id") == fact_id
                    and evidence_version_matches
                    and item["status"] == "VALID"
                    and not item["data"].get("expired")
                    and not item["data"].get("conflict")):
                return item
        return None

    # ---------- controlled agent gateway and rules ----------

    def agent_suggest_rule(self, scope: Scope, *, group_id: str, actor_id: str, model_output: dict[str, Any] | None, model_version: str = "unconfigured") -> dict[str, Any]:
        group = self.store.get_object(group_id, scope)
        sanitized_input = self._sanitize_agent_input(scope, group)
        fixture_output = model_output is not None
        requested_model = model_version if model_output is not None else self.gateway.configured_model
        run = self._create_agent_run(scope, group_id, actor_id, requested_model)
        try:
            model_output, resolved_model, gateway_metadata = self._resolve_agent_output(
                scope, stage="RULE_SUGGESTION", sanitized_input=sanitized_input,
                model_output=model_output, model_version=model_version,
            )
            validated = self._validate_agent_output(scope, model_output)
        except GatewayPaused as exc:
            paused = self.store.create_initial_object(
                ObjectType.MODEL_RUN.value, scope,
                {"run_id": run["run_id"], "stage": "RULE_SUGGESTION", "status": "PAUSED",
                 "reason": exc.message, "gateway": {"gateway_version": GATEWAY_VERSION,
                 "schema_version": AGENT_SCHEMA_VERSION, "mock": fixture_output,
                 "provider": "fixture" if fixture_output else self.store.database.settings.agent_provider,
                 "model_version": requested_model, "error_code": exc.gateway_code},
                 "input_summary": sanitized_input},
                status="PAUSED", created_by=actor_id,
            )
            self.store.update_run(run["run_id"], scope, status=RunStatus.PAUSED.value,
                                  result={"status": "PAUSED", "reason": exc.message,
                                          "gateway_code": exc.gateway_code})
            self.store.add_audit("AGENT_OUTPUT_REJECTED", actor_id, scope, object_type="ProcessingRun", object_id=run["run_id"], object_version=1, before=run, reason=exc.message)
            raise
        model_run = self.store.create_initial_object(ObjectType.MODEL_RUN.value, scope, {"run_id": run["run_id"], "stage": "RULE_SUGGESTION", "status": "SUCCEEDED", "model_version": resolved_model, "gateway": gateway_metadata, "input_summary": sanitized_input, "output_summary": {"summary": validated.summary, "confidence": validated.confidence, "evidence": validated.evidence}}, status="SUCCEEDED", created_by=actor_id)
        suggestion = self.store.create_initial_object(ObjectType.AGENT_SUGGESTION.value, scope, {"stage": "RULE_SUGGESTION", "model_run_id": model_run["object_id"], "group_id": group_id, "output": validated.model_dump()}, status="PROPOSED", created_by=actor_id)
        candidate = self.store.create_initial_object(ObjectType.RULE_CANDIDATE.value, scope, {"suggestion_id": suggestion["object_id"], "group_id": group_id, "rule_definition": validated.items, "risk_level": validated.risk_level, "confidence": validated.confidence, "evidence_ids": validated.evidence, "candidate_only": True}, status="PROPOSED", created_by=actor_id)
        card = self.store.create_initial_object(ObjectType.CONFIRMATION_CARD.value, scope, {"candidate_id": candidate["object_id"], "group_id": group_id, "stage": "RULE_CONFIRMATION", "evidence_ids": validated.evidence, "suggested_rule": validated.items, "differences": [], "impact_preview": {"group_id": group_id, "future_applicable_period": scope.accounting_period_id}, "reversible": True}, status="PENDING", created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, model_run, suggestion, evidence=validated.evidence, created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, suggestion, candidate, evidence=validated.evidence, created_by=actor_id)
        self.store.add_relation(RelationType.APPLIES_TO.value, candidate, group, evidence=validated.evidence, created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, candidate, card, evidence=validated.evidence, created_by=actor_id)
        self.store.update_run(run["run_id"], scope, status=RunStatus.SUCCEEDED.value, result={"status": "PROPOSED", "candidate_id": candidate["object_id"], "card_id": card["object_id"], "gateway": gateway_metadata})
        return {"model_run": model_run, "suggestion": suggestion, "candidate": candidate, "confirmation_card": card}

    def agent_suggest(self, scope: Scope, *, stage: str, actor_id: str, model_output: dict[str, Any] | None, group_id: str | None = None, model_version: str = "unconfigured") -> dict[str, Any]:
        """统一 Gateway 入口；非规则阶段也只能创建候选对象。"""
        allowed_stages = {"DOCUMENT_UNDERSTANDING", "BUSINESS_EVENT", "GROUPING", "EXCEPTION"}
        if stage == "RULE_SUGGESTION":
            if not group_id:
                raise PreconditionFailed("规则建议必须绑定业务组")
            return self.agent_suggest_rule(scope, group_id=group_id, actor_id=actor_id, model_output=model_output, model_version=model_version)
        if stage not in allowed_stages:
            raise DomainError("未知 Agent 阶段", "UNKNOWN_AGENT_STAGE", 422)
        context_id = group_id or "scope"
        sanitized_input = self._sanitize_scope_agent_input(scope, group_id=group_id)
        fixture_output = model_output is not None
        requested_model = model_version if model_output is not None else self.gateway.configured_model
        run = self._create_agent_run(scope, context_id, actor_id, requested_model)
        try:
            model_output, resolved_model, gateway_metadata = self._resolve_agent_output(
                scope, stage=stage, sanitized_input=sanitized_input,
                model_output=model_output, model_version=model_version,
            )
            validated = self._validate_agent_output(scope, model_output)
        except GatewayPaused as exc:
            paused = self.store.create_initial_object(
                ObjectType.MODEL_RUN.value, scope,
                {"run_id": run["run_id"], "stage": stage, "status": "PAUSED", "reason": exc.message,
                 "gateway": {"gateway_version": GATEWAY_VERSION, "schema_version": AGENT_SCHEMA_VERSION,
                 "mock": fixture_output, "provider": "fixture" if fixture_output else self.store.database.settings.agent_provider,
                 "model_version": requested_model, "error_code": exc.gateway_code},
                 "input_summary": sanitized_input}, status="PAUSED", created_by=actor_id,
            )
            self.store.update_run(run["run_id"], scope, status=RunStatus.PAUSED.value, result={"status": "PAUSED", "reason": exc.message, "stage": stage, "gateway_code": exc.gateway_code})
            self.store.add_audit("AGENT_OUTPUT_REJECTED", actor_id, scope, object_type=paused["object_type"], object_id=paused["object_id"], object_version=1, reason=exc.message)
            raise
        model_run = self.store.create_initial_object(ObjectType.MODEL_RUN.value, scope, {"run_id": run["run_id"], "stage": stage, "status": "SUCCEEDED", "model_version": resolved_model, "gateway": gateway_metadata, "input_summary": sanitized_input, "output_summary": validated.model_dump()}, status="SUCCEEDED", created_by=actor_id)
        suggestion = self.store.create_initial_object(ObjectType.AGENT_SUGGESTION.value, scope, {"stage": stage, "model_run_id": model_run["object_id"], "group_id": group_id, "output": validated.model_dump()}, status="PROPOSED", created_by=actor_id)
        candidate = None
        if stage == "BUSINESS_EVENT":
            identity = (validated.items[0].get("stable_identity") if validated.items else None) or f"candidate:{suggestion['object_id']}"
            candidate = self.store.create_initial_object(ObjectType.BUSINESS_EVENT.value, scope, {"stable_identity": identity, "event_type": "CANDIDATE", "candidate_only": True, "suggestion_id": suggestion["object_id"], "items": validated.items}, status="CANDIDATE", created_by=actor_id)
            self.store.add_relation(RelationType.GENERATES.value, suggestion, candidate, evidence=validated.evidence, created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, model_run, suggestion, evidence=validated.evidence, created_by=actor_id)
        self.store.update_run(run["run_id"], scope, status=RunStatus.SUCCEEDED.value, result={"status": "PROPOSED", "suggestion_id": suggestion["object_id"], "candidate_id": candidate["object_id"] if candidate else None, "stage": stage, "gateway": gateway_metadata})
        return {"model_run": model_run, "suggestion": suggestion, "candidate": candidate}

    def _resolve_agent_output(self, scope: Scope, *, stage: str, sanitized_input: dict[str, Any], model_output: dict[str, Any] | None, model_version: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
        if model_output is not None:
            if self.store.database.settings.require_auth:
                raise GatewayPaused("认证环境禁止注入 fixture 模型输出，必须通过服务端 Gateway 调用", gateway_code="FIXTURE_OUTPUT_FORBIDDEN")
            return model_output, model_version, {
                "gateway_version": GATEWAY_VERSION,
                "schema_version": AGENT_SCHEMA_VERSION,
                "provider": "fixture",
                "model_version": model_version,
                "mock": True,
                "prompt_version": "fixture",
                "input_hash": digest(sanitized_input),
                "output_hash": digest(model_output),
                "latency_ms": 0,
                "usage": {},
                "request_id": None,
            }
        try:
            result = self.gateway.complete(scope, stage=stage, sanitized_input=sanitized_input)
        except GatewayFailure as exc:
            if exc.code == "GATEWAY_DISABLED":
                raise GatewayPaused("模型不可用，任务已暂停，不能用伪造结果继续流程", gateway_code=exc.code) from exc
            raise GatewayPaused(f"{exc.message}，任务已暂停", gateway_code=exc.code) from exc
        return result.output, result.model_version, result.metadata()

    def approve_rule(self, scope: Scope, *, card_id: str, actor_id: str, expected_version: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        card = self.store.get_object(card_id, scope)
        if card["version"] != expected_version:
            raise VersionConflict()
        if card["status"] != "PENDING":
            raise PreconditionFailed("确认卡当前不在待确认状态")
        candidate = self.store.get_object(card["data"]["candidate_id"], scope)
        group = self.store.get_object(card["data"]["group_id"], scope)
        if candidate["status"] != "PROPOSED":
            raise PreconditionFailed("候选规则已失效，不能重复确认")
        if group["status"] in {"BLOCKED", "SUSPENDED"}:
            raise PreconditionFailed("异常业务组不能直接确认正式规则")
        if any(item["data"].get("group_id") == group["object_id"] for item in self.store.list_objects(ObjectType.RULE_CONFLICT.value, scope, statuses=["OPEN"])):
            raise PreconditionFailed("仍有未处理规则冲突，不能绕过冲突确认")
        definition = payload.get("rule_definition") if payload else None
        definition = definition or candidate["data"].get("rule_definition")
        conflict = bool(payload and payload.get("conflict"))
        if conflict:
            raise RuleConflictDetected(candidate, {"group_id": group["object_id"], "candidate_id": candidate["object_id"], "historical_rule": payload.get("historical_rule"), "current_candidate": definition, "reason": payload.get("reason", "本期事实与历史规则不一致")})
        data = {"rule_definition": definition, "group_id": group["object_id"], "business_type": "PURCHASE", "ledger_id": scope.ledger_id, "accounting_period_id": scope.accounting_period_id, "effective_time": utcnow(), "confirmed_by": actor_id, "conditions": payload.get("conditions", {}) if payload else {}, "exception_conditions": payload.get("exception_conditions", []) if payload else [], "priority": payload.get("priority", 100) if payload else 100, "revocation": "新确认规则或人工撤销", "source_candidate_id": candidate["object_id"]}
        rule = self.store.create_initial_object(ObjectType.RULE_INSTANCE.value, scope, data, status="ACTIVE", created_by=actor_id)
        decision = self.store.create_initial_object(ObjectType.DECISION.value, scope, {"decision_type": "APPROVE_RULE", "target_id": candidate["object_id"], "decision": "APPROVED", "decided_by": actor_id, "decision_time": utcnow(), "impact": card["data"].get("impact_preview", {})}, status="CONFIRMED", created_by=actor_id)
        card_data = deepcopy(card["data"])
        card_data.update({"decision_id": decision["object_id"], "rule_instance_id": rule["object_id"], "approved_by": actor_id, "decision_time": utcnow()})
        approved_card = self.store.revise_object(card_id, expected_version, scope, card_data, status="APPROVED", created_by=actor_id)
        candidate_data = deepcopy(candidate["data"])
        candidate_data["promoted_to_rule_instance_id"] = rule["object_id"]
        self.store.revise_object(candidate["object_id"], candidate["version"], scope, candidate_data, status="APPROVED", created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, decision, rule, evidence=candidate["data"].get("evidence_ids", []), created_by=actor_id, status="CONFIRMED")
        self.store.add_relation(RelationType.APPLIES_TO.value, rule, group, evidence=candidate["data"].get("evidence_ids", []), created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("RULE_APPROVED", actor_id, scope, object_type=rule["object_type"], object_id=rule["object_id"], object_version=1, before=card, after={"card": approved_card, "rule": rule, "decision": decision}, evidence=candidate["data"].get("evidence_ids", []), reason="候选规则经人工确认后生成 RuleInstance")
        return {"rule_instance": rule, "confirmation_card": approved_card, "decision": decision}

    def approve_rule_batch(self, scope: Scope, *, card_ids: list[str], actor_id: str, preview_only: bool = False) -> dict[str, Any]:
        if not card_ids:
            raise PreconditionFailed("批量确认至少需要一张确认卡")
        cards = [self.store.get_object(card_id, scope) for card_id in card_ids]
        if any(card["status"] != "PENDING" for card in cards):
            raise PreconditionFailed("批量确认中存在非待确认卡片")
        impacts = [{"card_id": card["object_id"], **card["data"].get("impact_preview", {})} for card in cards]
        if preview_only:
            return {"preview": True, "card_count": len(cards), "impact": impacts, "reversible": all(card["data"].get("reversible", False) for card in cards)}
        # 先完成全部前置条件检查，再逐卡生成正式 RuleInstance，避免一半进入正式状态。
        for card in cards:
            candidate = self.store.get_object(card["data"]["candidate_id"], scope)
            group = self.store.get_object(card["data"]["group_id"], scope)
            if candidate["status"] != "PROPOSED" or group["status"] in {"BLOCKED", "SUSPENDED"}:
                raise PreconditionFailed("批量确认中存在不满足门禁的候选规则")
        results = [self.approve_rule(scope, card_id=card["object_id"], actor_id=actor_id, expected_version=card["version"]) for card in cards]
        return {"preview": False, "card_count": len(results), "results": results, "impact": impacts, "reversible": True}

    def resolve_rule_conflict(self, scope: Scope, *, conflict_id: str, actor_id: str,
                              expected_version: int, resolution: str, reason: str = "") -> dict[str, Any]:
        conflict = self.store.get_object(conflict_id, scope)
        if conflict["version"] != expected_version:
            raise VersionConflict()
        if conflict["status"] != "OPEN":
            raise PreconditionFailed("规则冲突已经处理，不能重复处理")
        if resolution not in {"ACCEPT_CANDIDATE", "REJECT_CANDIDATE"}:
            raise PreconditionFailed("规则冲突处理结果必须是接受候选规则或拒绝候选规则")
        data = deepcopy(conflict["data"])
        data.update({"resolution": resolution, "resolved_by": actor_id, "resolved_at": utcnow(), "resolution_reason": reason or "人工处理规则冲突"})
        candidate_id = data.get("candidate_id")
        candidate = self.store.get_object(candidate_id, scope) if candidate_id else None
        if resolution == "REJECT_CANDIDATE" and candidate and candidate["status"] == "PROPOSED":
            candidate_data = deepcopy(candidate["data"])
            candidate_data.update({"rejected_by": actor_id, "rejected_at": utcnow(), "rejection_reason": reason or "规则冲突未通过"})
            candidate = self.store.revise_object(candidate["object_id"], candidate["version"], scope, candidate_data, status="REJECTED", created_by=actor_id)
            for card in self.store.list_objects(ObjectType.CONFIRMATION_CARD.value, scope, statuses=["PENDING"]):
                if card["data"].get("candidate_id") != candidate_id:
                    continue
                card_data = deepcopy(card["data"])
                card_data.update({"rejected_by": actor_id, "rejected_at": utcnow(), "rejection_reason": reason or "规则冲突未通过"})
                self.store.revise_object(card["object_id"], card["version"], scope, card_data, status="REJECTED", created_by=actor_id)
        status = "RESOLVED" if resolution == "ACCEPT_CANDIDATE" else "REJECTED"
        resolved = self.store.revise_object(conflict_id, expected_version, scope, data, status=status, created_by=actor_id)
        self.store.add_audit("RULE_CONFLICT_RESOLVED", actor_id, scope, object_type=conflict["object_type"], object_id=conflict_id,
                             object_version=resolved["version"], before=conflict, after={"conflict": resolved, "candidate": candidate},
                             evidence=data.get("evidence_ids", []), reason=data["resolution_reason"])
        return {"conflict": resolved, "candidate": candidate, "resolution": resolution}

    def revoke_rule(self, scope: Scope, *, rule_id: str, actor_id: str, expected_version: int, reason: str) -> dict[str, Any]:
        rule = self.store.get_object(rule_id, scope)
        if rule["version"] != expected_version:
            raise VersionConflict()
        if rule["status"] != "ACTIVE":
            raise PreconditionFailed("只有生效中的规则可以撤销")
        data = deepcopy(rule["data"])
        data.update({"revoked_by": actor_id, "revoked_at": utcnow(), "revocation_reason": reason or "人工撤销规则"})
        revoked = self.store.revise_object(rule_id, expected_version, scope, data, status="REVOKED", created_by=actor_id)
        decision = self.store.create_initial_object(ObjectType.DECISION.value, scope,
            {"decision_type": "REVOKE_RULE", "target_id": rule_id, "decision": "REVOKED", "decided_by": actor_id,
             "decision_time": utcnow(), "reason": data["revocation_reason"]}, status="CONFIRMED", created_by=actor_id)
        affected_groups = []
        group_id = rule["data"].get("group_id")
        if group_id:
            try:
                group = self.store.get_object(group_id, scope)
            except KeyError:
                group = None
            if group and group["status"] not in {"VOID", "MERGED", "ARCHIVED"}:
                group_data = deepcopy(group["data"])
                group_data.update({"rule_status": "REVOKED", "rule_revoked_at": utcnow(), "rule_revocation_reason": data["revocation_reason"]})
                if group["status"] not in {"BLOCKED", "SUSPENDED"}:
                    group_data["rule_resume_status"] = group["status"]
                    group_status = "BLOCKED"
                else:
                    group_status = group["status"]
                affected_groups.append(self.store.revise_object(group_id, group["version"], scope, group_data, status=group_status, created_by=actor_id))
        self.store.add_relation(RelationType.GENERATES.value, decision, revoked, evidence=rule["data"].get("evidence_ids", []), created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("RULE_REVOKED", actor_id, scope, object_type=rule["object_type"], object_id=rule_id,
                             object_version=revoked["version"], before=rule, after={"rule": revoked, "decision": decision, "groups": affected_groups},
                             reason=data["revocation_reason"])
        return {"rule": revoked, "decision": decision, "affected_groups": affected_groups}

    def _create_agent_run(self, scope: Scope, group_id: str, actor_id: str, model_version: str) -> dict[str, Any]:
        facts = self.store.list_objects(ObjectType.FACT_RECORD.value, scope)
        fact_summaries = []
        for fact in facts:
            value = fact["data"].get("normalized_value") or {}
            if not isinstance(value, dict):
                value = {}
            fact_summaries.append({
                "object_id": fact["object_id"], "version": fact["version"], "status": fact["status"],
                "record_type": fact["data"].get("record_type"),
                "source_artifact_id": fact["data"].get("source_artifact_id"),
                "source_anchor": fact["data"].get("source_anchor"),
                "summary": {key: value.get(key) for key in ("invoice_no", "contract_no", "stock_in_no", "transaction_date", "payment_total", "supplier", "amount") if value.get(key) is not None},
            })
        fingerprint = digest({"scope": scope.model_dump(), "group_id": group_id, "facts": [item["object_id"] + ":" + str(item["version"]) for item in facts]})
        run = {"run_id": new_id("run"), "status": RunStatus.RUNNING.value, "input_fingerprint": fingerprint, "baseline_version": self.store.get_object(self._baseline_object_id(scope), scope)["version"], "rule_version": "pending", "model_version": model_version, "schema_version": "agent-output-v1", "gateway_version": "gateway-v1", "attempt": 1, "parent_run_id": None, "result": {"stage": "RULE_SUGGESTION", "group_id": group_id}}
        created = self.store.create_run(scope, run)
        self.store.add_audit("RUN_CREATED", actor_id, scope, object_type="ProcessingRun", object_id=run["run_id"], object_version=1, after=run, reason="Agent 输入、基线和版本固定")
        return created

    def _sanitize_agent_input(self, scope: Scope, group: dict[str, Any]) -> dict[str, Any]:
        safe_fields = {"external_id", "invoice_no", "invoice_total", "net_amount", "tax", "tax_rate", "payment_total", "transaction_id", "direction", "business_date", "contract_no", "warehouse", "amount", "supplier_ref"}
        facts = []
        for fact_id in group["data"].get("member_fact_ids", []):
            fact = self.store.get_object(fact_id, scope)
            normalized = fact["data"].get("normalized_value") or {}
            if not isinstance(normalized, dict):
                normalized = {}
            safe_normalized = {key: value for key, value in normalized.items() if key in safe_fields}
            evidence = self._find_evidence_for_fact(scope, fact_id)
            facts.append({"fact_id": fact_id, "record_type": fact["data"].get("record_type"), "normalized_value": safe_normalized, "source_anchor": fact["data"].get("source_anchor"), "evidence_ids": [evidence["object_id"]] if evidence else []})
        return {"scope_period": scope.accounting_period_id, "group_id": group["object_id"], "facts": facts}

    def _sanitize_scope_agent_input(self, scope: Scope, *, group_id: str | None) -> dict[str, Any]:
        """Provide bounded, redacted facts for non-group Agent stages.

        The model gets only normalized allowlisted fields and evidence IDs that
        already exist in this Scope. Enterprise names, tax IDs and raw source
        content never enter the Gateway envelope.
        """
        safe_fields = {"external_id", "invoice_no", "invoice_total", "net_amount", "tax", "tax_rate", "payment_total", "transaction_id", "direction", "business_date", "contract_no", "warehouse", "amount", "supplier_ref"}
        facts = []
        for fact in self.store.list_objects(ObjectType.FACT_RECORD.value, scope):
            normalized = fact["data"].get("normalized_value") or {}
            if not isinstance(normalized, dict):
                normalized = {}
            evidence = self._find_evidence_for_fact(scope, fact["object_id"])
            facts.append({
                "fact_id": fact["object_id"],
                "record_type": fact["data"].get("record_type"),
                "status": fact["status"],
                "normalized_value": {key: value for key, value in normalized.items() if key in safe_fields},
                "source_anchor": fact["data"].get("source_anchor"),
                "evidence_ids": [evidence["object_id"]] if evidence else [],
            })
        return {"scope_period": scope.accounting_period_id, "group_id": group_id, "facts": facts}

    def _validate_agent_output(self, scope: Scope, output: dict[str, Any]) -> AgentOutput:
        forbidden = {"enterprise_name", "company_name", "tax_id", "unified_social_credit_code", "raw_database"}
        if forbidden.intersection(output.keys()):
            raise GatewayPaused("Agent 输出包含禁止字段，任务已暂停")
        try:
            parsed = AgentOutput.model_validate(output)
        except Exception as exc:
            raise GatewayPaused(f"Agent 输出未通过 Schema 校验，任务已暂停: {exc}") from exc
        if not parsed.evidence:
            raise GatewayPaused("Agent 输出缺少证据引用，任务已暂停")
        for evidence_id in parsed.evidence:
            try:
                evidence = self.store.get_object(evidence_id, scope)
            except (KeyError, ScopeViolation) as exc:
                raise GatewayPaused("Agent 引用的证据不存在或越界，任务已暂停") from exc
            if evidence["object_type"] != ObjectType.EVIDENCE.value:
                raise GatewayPaused("Agent 引用的对象不是 Evidence，任务已暂停")
        return parsed

    # ---------- deterministic reconciliation and voucher versions ----------

    def reconcile_group(self, scope: Scope, *, group_id: str, actor_id: str) -> list[dict[str, Any]]:
        group = self._refresh_group(scope, self.store.get_object(group_id, scope), actor_id=actor_id)
        facts = [self.store.get_object(item, scope) for item in group["data"].get("member_fact_ids", [])]
        amounts = procurement_amounts(facts)
        checks: list[dict[str, Any]] = []

        def add_check(check_type: str, inputs: dict[str, Any], formula: str, tolerance: str, result: str, reason: str) -> None:
            item = {"check_id": new_id("check"), "group_id": group_id, "check_type": check_type, "inputs": inputs, "formula": formula, "tolerance": tolerance, "result": result, "reason": reason, "check_version": ENGINE_VERSION, "executed_at": utcnow()}
            checks.append(self.store.add_reconciliation(scope, item))

        basis = self._group_basis(scope, group)
        source_valid = bool(basis["facts"]) and all(f["fact_status"] == "PARSED" and f["artifact_status"] == "ACTIVE" and f['source_current'] for f in basis["facts"])
        evidence_valid = all(e["status"] == "VALID" and not e["expired"] and not e["conflict"] for e in basis["evidence"])
        add_check("SOURCE_VALIDITY", basis, "all sources and evidence remain valid", "0", "PASS" if source_valid and evidence_valid else "BLOCKED", "来源版本及证据有效" if source_valid and evidence_valid else "来源资料或证据已失效")
        missing = group["data"].get("missing_evidence", [])
        add_check("EVIDENCE_COMPLETENESS", {"missing": missing}, "all required evidence exists", "0", "BLOCKED" if missing else "PASS", "缺少业务必需证据" if missing else "业务必需证据齐全")

        delta = amounts["delta"]
        matched = delta is not None and abs(delta) <= PAYMENT_TOLERANCE
        add_check("PAYMENT_INVOICE", {key: amounts[key] for key in ("invoices", "payments", "invoice_total", "payment_total", "delta")},
                  "sum(payment_total) - sum(invoice_total)", str(PAYMENT_TOLERANCE), "PASS" if matched else "BLOCKED",
                  "全部付款与发票金额一致" if matched else (f"付款与发票差额 {delta:.2f}" if delta is not None else "缺少有效发票或付款金额，不能按零处理"))
        add_check("INVOICE_TOTAL", {"invoices": amounts["invoices"]}, "each invoice_total == net_amount + tax and invoice_total > 0", "0",
                  "PASS" if amounts["invoice_valid"] else "BLOCKED", "逐张发票价税合计一致" if amounts["invoice_valid"] else "发票金额缺失、无效或价税合计不一致")
        add_check("TAX", {"invoices": amounts["invoices"]}, "each round_half_up(net_amount * tax_rate, 2) == tax", "0.01",
                  "PASS" if amounts["tax_valid"] else "BLOCKED", "逐张发票税额校验通过" if amounts["tax_valid"] else "存在税率缺失、无效或税额差异，详见逐张发票结果")
        periods = {item["data"].get("period_check") for item in facts}
        add_check("PERIOD", {"period_checks": sorted(periods)}, "all(period_check == PASS)", "0", "PASS" if periods == {"PASS"} else "BLOCKED", "期间一致" if periods == {"PASS"} else "存在期间异常")
        duplicates = self._duplicate_facts(scope, group)
        add_check("DUPLICATE", {"conflicts": duplicates}, "source identity and typed external identity have one primary owner", "0", "BLOCKED" if duplicates else "PASS", "发现重复来源或外部业务事实" if duplicates else "无重复事实")
        balance_delta = amounts["balance_delta"]
        balanced = balance_delta == 0 and amounts["invoice_valid"]
        add_check("BALANCE", {key: amounts[key] for key in ("net_amount", "tax", "payment_total", "balance_delta")},
                  "sum(net_amount + tax) == sum(payment_total)", "0", "PASS" if balanced else "BLOCKED",
                  "全量预计借贷平衡" if balanced else "预计借贷不平或金额无效")
        passed = all(item["result"] == "PASS" for item in checks)
        data = deepcopy(group["data"])
        data.update({"reconciliation_status": "PASS" if passed else "BLOCKED", "reconciliation_check_ids": [item["check_id"] for item in checks], "reconciliation_basis": digest(basis), "reconciled_at": utcnow()})
        latest_group = self.store.get_object(group_id, scope)
        next_status = latest_group["status"]
        if next_status not in {"SUSPENDED", "REVISED", "VOID", "MERGED", "ARCHIVED", "DELIVERED"}:
            if not passed:
                if next_status in {"CANDIDATE", "CONFIRMED", "READY"}:
                    data["reconciliation_resume_status"] = next_status
                next_status = "BLOCKED"
            elif next_status == "BLOCKED" and data.get("reconciliation_resume_status"):
                resume = data.pop("reconciliation_resume_status")
                next_status = "READY" if resume in {"CONFIRMED", "READY"} else "CANDIDATE"
            elif next_status == "CONFIRMED":
                next_status = "READY"
        revised = self.store.revise_object(group_id, latest_group["version"], scope, data, status=next_status, created_by=actor_id)
        self.store.add_audit("RECONCILIATION_EXECUTED", actor_id, scope, object_type=revised["object_type"], object_id=group_id, object_version=revised["version"], after={"group": revised, "checks": checks}, reason="确定性对账引擎执行，Agent 不可修改结果")
        return checks

    def generate_draft(self, scope: Scope, *, group_id: str, actor_id: str) -> dict[str, Any]:
        group = self.store.get_object(group_id, scope)
        self._require_current_reconciliation(scope, group)
        self._require_baseline_confirmed(scope)
        if group["status"] not in {"CONFIRMED", "READY"}:
            raise PreconditionFailed("业务组未确认，不能生成凭证草稿")
        if group["data"].get("missing_evidence"):
            raise PreconditionFailed("证据不完整，不能生成凭证草稿")
        if group["data"].get("reconciliation_status") != "PASS":
            raise PreconditionFailed("对账未通过，不能生成凭证草稿")
        rule = self._find_rule_for_group(scope, group_id)
        if rule is None:
            raise PreconditionFailed("没有已确认 RuleInstance，不能生成可交付草稿")
        existing = self._voucher_for_group(scope, group_id)
        if existing and existing["status"] != "VOID":
            if existing["data"].get("reconciliation_basis") == group["data"].get("reconciliation_basis"):
                return existing
            if any(p["data"].get("voucher_version_id") == existing["object_id"] and p["status"] != "VOID"
                   for p in self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope)):
                raise PreconditionFailed("旧凭证已固定在交付包中，须先走撤销交付或更正流程")
        facts = [self.store.get_object(item, scope) for item in group["data"].get("member_fact_ids", [])]
        amounts = procurement_amounts(facts)
        if not amounts["invoice_valid"] or not amounts["tax_valid"] or amounts["balance_delta"] != 0:
            raise PreconditionFailed("业务金额或税额未通过全量校验")
        net, tax, gross = (format(amounts[key], ".2f") for key in ("net_amount", "tax", "invoice_total"))
        source_binding = {"reconciliation_basis": group["data"]["reconciliation_basis"],
                          "fact_versions": [{"fact_id": fact["object_id"], "version": fact["version"]} for fact in facts]}
        account = rule["data"].get("rule_definition") or [{"debit_account": "库存商品", "tax_account": "应交税费-进项税额"}]
        first = account[0] if isinstance(account, list) and account else {}
        lines = [{"line_no": 1, "direction": "DEBIT", "account": first.get("debit_account", "库存商品"), "amount": net, "source_group_id": group_id}, {"line_no": 2, "direction": "DEBIT", "account": first.get("tax_account", "应交税费-进项税额"), "amount": tax, "source_group_id": group_id}, {"line_no": 3, "direction": "CREDIT", "account": first.get("credit_account", "银行存款"), "amount": gross, "source_group_id": group_id}]
        proposal = self.store.create_initial_object(ObjectType.VOUCHER_PROPOSAL.value, scope, {**source_binding, "group_id": group_id, "rule_instance_id": rule["object_id"], "lines": lines, "proposal_only": True}, status="PROPOSED", created_by=actor_id)
        draft = self.store.create_initial_object(ObjectType.VOUCHER_DRAFT.value, scope, {**source_binding, "group_id": group_id, "proposal_id": proposal["object_id"], "rule_instance_id": rule["object_id"], "lines": lines, "formal_balance_impact": False}, status="DRAFT", created_by=actor_id)
        voucher_data = {**source_binding, "group_id": group_id, "draft_id": draft["object_id"], "proposal_id": proposal["object_id"], "rule_instance_id": rule["object_id"], "lines": lines, "version_reason": "来源变化后重新生成" if existing else "由已确认业务组生成", "formal_balance_impact": False}
        if existing:
            voucher = self.store.revise_object(existing["object_id"], existing["version"], scope, voucher_data, status="REVISED", created_by=actor_id)
        else:
            voucher = self.store.create_initial_object(ObjectType.VOUCHER_VERSION.value, scope, voucher_data, status="DRAFT", created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, group, proposal, evidence=group["data"].get("evidence_ids", []), created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, proposal, draft, evidence=group["data"].get("evidence_ids", []), created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, draft, voucher, evidence=group["data"].get("evidence_ids", []), created_by=actor_id)
        self.store.add_relation(RelationType.VALIDATES.value, voucher, self.store.get_object(group["object_id"], scope), evidence=group["data"].get("reconciliation_check_ids", []), created_by=actor_id)
        self.store.add_audit("VOUCHER_DRAFT_CREATED", actor_id, scope, object_type=voucher["object_type"], object_id=voucher["object_id"], object_version=voucher["version"], before=existing, after=voucher, evidence=group["data"].get("evidence_ids", []) + group["data"].get("reconciliation_check_ids", []), reason="草稿不影响正式余额；来源变更保留旧版本并重新复核")
        return voucher

    def validate_draft(self, scope: Scope, *, voucher_id: str, actor_id: str, expected_version: int) -> dict[str, Any]:
        self._ensure_period_open(scope)
        voucher = self.store.get_object(voucher_id, scope)
        if voucher["version"] != expected_version:
            raise VersionConflict()
        if voucher["status"] not in {"DRAFT", "REVISED"}:
            raise PreconditionFailed("凭证版本当前不可复核")
        lines = voucher["data"].get("lines", [])
        debit, credit = self._voucher_totals(lines, voucher["data"]["group_id"])
        if debit != credit:
            raise PreconditionFailed(f"借贷不平：借方 {debit:.2f}，贷方 {credit:.2f}")
        self._require_baseline_confirmed(scope)
        group = self.store.get_object(voucher["data"]["group_id"], scope)
        self._require_current_reconciliation(scope, group)
        self._require_voucher_sources(group, voucher)
        if group["status"] not in {"READY", "CONFIRMED"} or group["data"].get("missing_evidence") or group["data"].get("reconciliation_status") != "PASS" or not self._find_rule_for_group(scope, group["object_id"]):
            raise PreconditionFailed("业务证据、规则或校验未通过，不能复核凭证")
        invoices = [self.store.get_object(item, scope) for item in group["data"].get("member_fact_ids", [])]
        expected = sum(Decimal(str(item["data"]["normalized_value"]["invoice_total"])) for item in invoices if item["data"].get("record_type") == "INVOICE")
        if Decimal(str(debit)) != expected:
            raise PreconditionFailed("凭证金额与业务组发票金额不一致")
        data = deepcopy(voucher["data"])
        data.update({"validated_by": actor_id, "validated_at": utcnow(), "debit_total": format(debit, ".2f"), "credit_total": format(credit, ".2f"), "formal_balance_impact": False})
        confirmed = self.store.revise_object(voucher_id, expected_version, scope, data, status="LOCALLY_CONFIRMED", created_by=actor_id)
        group = self.store.get_object(data["group_id"], scope)
        group_data = deepcopy(group["data"])
        group_data["delivery_status"] = "DELIVERABLE"
        self.store.revise_object(group["object_id"], group["version"], scope, group_data, status="READY", created_by=actor_id)
        self.store.add_audit("VOUCHER_LOCALLY_CONFIRMED", actor_id, scope, object_type=confirmed["object_type"], object_id=voucher_id, object_version=confirmed["version"], before=voucher, after=confirmed, reason="凭证复核通过，仍未等同外部导入")
        return confirmed

    def revise_voucher(self, scope: Scope, *, voucher_id: str, actor_id: str, expected_version: int, lines: list[dict[str, Any]]) -> dict[str, Any]:
        self._ensure_period_open(scope)
        voucher = self.store.get_object(voucher_id, scope)
        if voucher["version"] != expected_version:
            raise VersionConflict()
        if any(p["data"].get("voucher_version_id") == voucher_id and p["status"] != "VOID" for p in self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope)):
            raise PreconditionFailed("凭证已固定在交付包中，不能修订；需走撤销交付或更正流程")
        self._voucher_totals(lines, voucher["data"]["group_id"])
        if voucher["status"] == "LOCALLY_CONFIRMED":
            data = deepcopy(voucher["data"])
        else:
            data = deepcopy(voucher["data"])
        data.update({"lines": lines, "revised_by": actor_id, "revised_at": utcnow(), "formal_balance_impact": False})
        revised = self.store.revise_object(voucher_id, expected_version, scope, data, status="REVISED", created_by=actor_id)
        self.store.add_audit("VOUCHER_REVISED", actor_id, scope, object_type=voucher["object_type"], object_id=voucher_id, object_version=revised["version"], before=voucher, after=revised, reason="凭证修改产生新版本，旧版本只读")
        return revised

    def _find_rule_for_group(self, scope: Scope, group_id: str) -> dict[str, Any] | None:
        rules = self.store.list_objects(ObjectType.RULE_INSTANCE.value, scope)
        for rule in reversed(rules):
            if rule["data"].get("group_id") == group_id and rule["status"] == "ACTIVE":
                return rule
        return None

    def _voucher_totals(self, lines: list[dict[str, Any]], group_id: str) -> tuple[Decimal, Decimal]:
        totals = {"DEBIT": Decimal("0"), "CREDIT": Decimal("0")}
        if len(lines) < 2:
            raise PreconditionFailed("凭证至少需要有效的借方和贷方分录")
        numbers = set()
        for line in lines:
            if not isinstance(line, dict) or not isinstance(line.get("direction"), str) or line["direction"] not in totals or not isinstance(line.get("account"), str) or not line["account"].strip():
                raise PreconditionFailed("凭证分录必须包含有效科目和借贷方向")
            if line.get("source_group_id") != group_id or type(line.get("line_no")) is not int or line["line_no"] < 1 or line["line_no"] in numbers:
                raise PreconditionFailed("凭证分录必须具有唯一行号和当前业务组来源引用")
            numbers.add(line["line_no"])
            try:
                amount = Decimal(str(line.get("amount")))
                if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                raise PreconditionFailed("分录金额必须是非负、精确到分的有限金额")
            totals[line["direction"]] += amount
        if any(total <= 0 for total in totals.values()):
            raise PreconditionFailed("凭证借贷双方必须有正金额，不能复核空凭证")
        return totals["DEBIT"], totals["CREDIT"]

    # ---------- command-controlled delivery, run lifecycle and queries ----------

    def release_delivery(self, scope: Scope, *, group_id: str, actor_id: str) -> dict[str, Any]:
        self._ensure_period_open(scope)
        self._require_baseline_confirmed(scope)
        group = self.store.get_object(group_id, scope)
        self._require_current_reconciliation(scope, group)
        if group["status"] not in {"READY", "CONFIRMED"} or group["data"].get("reconciliation_status") != "PASS":
            raise PreconditionFailed("业务组未满足本地交付门禁")
        voucher = self._voucher_for_group(scope, group_id)
        if voucher is None or voucher["status"] != "LOCALLY_CONFIRMED":
            raise PreconditionFailed("凭证尚未完成本地复核")
        self._require_voucher_sources(group, voucher)
        packages = [item for item in self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope) if item["data"].get("group_id") == group_id and item["status"] not in {"VOID"}]
        if packages:
            return packages[-1]
        unresolved = [item for item in self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope) if item["object_id"] != group_id and item["status"] in {"BLOCKED", "SUSPENDED", "CANDIDATE"}]
        package = self.store.create_initial_object(ObjectType.DELIVERY_PACKAGE.value, scope, {"group_id": group_id, "voucher_version_id": voucher["object_id"], "voucher_version": voucher["version"], "group_version": group["version"], "created_time": utcnow(), "export_id": None, "external_receipt_id": None, "package_scope": [group_id], "delivery_mode": "PARTIAL_DELIVERY" if unresolved else "FULL_SCOPE", "unresolved_group_ids": [item["object_id"] for item in unresolved], "complete": not unresolved}, status="DELIVERABLE", created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, group, package, evidence=group["data"].get("evidence_ids", []), created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("DELIVERY_RELEASED", actor_id, scope, object_type=package["object_type"], object_id=package["object_id"], object_version=1, after=package, evidence=[voucher["object_id"]], reason="安全业务组独立交付")
        return package

    def export_package(self, scope: Scope, *, package_id: str, actor_id: str) -> dict[str, Any]:
        package = self.store.get_object(package_id, scope)
        if package["status"] not in {"DELIVERABLE", "EXPORT_CREATED", "EXTERNAL_IMPORTED"}:
            raise PreconditionFailed("交付包当前不可导出")
        if not package["data"].get("voucher_version"):
            raise PreconditionFailed("交付包没有固定凭证修订号，必须重新复核后建立交付包")
        if package["status"] in {"EXPORT_CREATED", "EXTERNAL_IMPORTED"}:
            try:
                export = self.store.get_object(package["data"]["export_id"], scope)
            except KeyError as exc:
                raise PreconditionFailed("既有导出记录缺失，不能重新生成替代历史记录") from exc
            self._validate_export_binding(package, export)
            return {"package": package, "export": export}
        self._ensure_period_open(scope)
        self._require_baseline_confirmed(scope)
        self._require_current_reconciliation(scope, self.store.get_object(package["data"]["group_id"], scope))
        voucher = self.store.get_object(package["data"]["voucher_version_id"], scope, package["data"]["voucher_version"])
        if voucher["status"] != "LOCALLY_CONFIRMED":
            raise PreconditionFailed("交付包中的凭证版本未复核")
        self._require_voucher_sources(self.store.get_object(package["data"]["group_id"], scope), voucher)
        export = self.store.create_initial_object(ObjectType.EXPORT.value, scope, {"package_id": package_id, "voucher_version_id": voucher["object_id"], "voucher_version": voucher["version"], "lines": voucher["data"]["lines"], "group_scope": package["data"].get("package_scope", []), "generated_at": utcnow(), "export_hash": digest({"package_id": package_id, "voucher": voucher["object_id"], "version": voucher["version"], "lines": voucher["data"]["lines"]})}, status="CREATED", created_by=actor_id)
        data = deepcopy(package["data"])
        data["export_id"] = export["object_id"]
        data["exported_at"] = utcnow()
        exported = self.store.revise_object(package_id, package["version"], scope, data, status="EXPORT_CREATED", created_by=actor_id)
        self.store.add_relation(RelationType.GENERATES.value, exported, export, evidence=[voucher["object_id"]], created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("PACKAGE_EXPORTED", actor_id, scope, object_type=export["object_type"], object_id=export["object_id"], object_version=1, after={"package": exported, "export": export}, reason="导出固定业务组与凭证版本")
        return {"package": exported, "export": export}

    def ack_external_import(self, scope: Scope, *, package_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_period_open(scope)
        status = payload.get("status")
        if status not in {"IMPORTED", "FAILED", "PARTIAL"} or not isinstance(payload.get("external_batch"), str) or not payload["external_batch"].strip():
            raise PreconditionFailed("外部回执必须明确结果状态和外部导入批次")
        if payload.get("adapter") == "yidaizhang-file-v1":
            required_file_fields = ("receipt_file_name", "receipt_file_sha256", "manifest_file_sha256", "period", "export_file_sha256")
            if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required_file_fields):
                raise PreconditionFailed("易代账文件回执缺少文件哈希、期间或 Manifest 绑定信息")
        elif payload.get("adapter") is not None:
            raise PreconditionFailed("不支持的外部回执适配器")
        package = self.store.get_object(package_id, scope)
        if package["status"] not in {"EXPORT_CREATED", "EXTERNAL_IMPORTED"}:
            raise PreconditionFailed("没有导出批次，不能接收外部回执")
        export_id = package["data"].get("export_id")
        if not export_id:
            raise PreconditionFailed("交付包缺少导出批次")
        export = self.store.get_object(export_id, scope)
        self._validate_export_binding(package, export)
        expected_binding = {"export_id": export_id, "voucher_version_id": package["data"]["voucher_version_id"], "voucher_version": package["data"]["voucher_version"]}
        if any(payload.get(key) != value for key, value in expected_binding.items()):
            raise PreconditionFailed("回执必须与当前导出批次、凭证及修订号明确一致")
        if package["status"] == "EXTERNAL_IMPORTED" and status != "IMPORTED":
            raise PreconditionFailed("已有成功回执，矛盾回执需人工调查，不能覆盖成功记录")
        payload_hash = digest({"export_id": export_id, "payload": payload})
        receipt = {"receipt_id": new_id("receipt"), "export_id": export_id, "package_id": package_id, "voucher_version_id": package["data"]["voucher_version_id"], "payload_hash": payload_hash, "status": status, "payload": payload, "received_at": utcnow()}
        saved, inserted = self.store.save_receipt(receipt)
        if not inserted:
            self.store.add_audit("EXTERNAL_RECEIPT_DEDUPLICATED", actor_id, scope, object_type=ObjectType.EXTERNAL_RECEIPT.value, object_id=saved["receipt_id"], object_version=1, after=saved, reason="相同外部回执幂等处理")
            return {"receipt": saved, "package": package, "deduplicated": True}
        receipt_object = self.store.create_initial_object(ObjectType.EXTERNAL_RECEIPT.value, scope, saved, status=saved["status"], created_by=actor_id, object_id=saved["receipt_id"])
        data = deepcopy(package["data"])
        data["external_receipt_id"] = receipt_object["object_id"]
        data["last_receipt_status"] = status
        if status == "IMPORTED":
            data["external_imported_at"] = utcnow()
        imported = self.store.revise_object(package_id, package["version"], scope, data, status="EXTERNAL_IMPORTED" if status == "IMPORTED" else "EXPORT_CREATED", created_by=actor_id)
        self.store.add_relation(RelationType.VALIDATES.value, receipt_object, imported, evidence=[export_id, package["data"]["voucher_version_id"]], created_by=actor_id, status="CONFIRMED")
        self.store.add_audit("EXTERNAL_IMPORT_ACKNOWLEDGED", actor_id, scope, object_type=receipt_object["object_type"], object_id=receipt_object["object_id"], object_version=1, after={"receipt": receipt_object, "package": imported}, reason="外部回执已记录：" + status)
        return {"receipt": receipt_object, "package": imported, "deduplicated": False}

    def close_period(self, scope: Scope, *, actor_id: str, expected_version: int) -> dict[str, Any]:
        self._ensure_period_open(scope)
        period = self.store.get_object(self._period_object_id(scope), scope)
        if period["version"] != expected_version:
            raise VersionConflict()
        self._require_baseline_confirmed(scope)
        groups = self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope)
        incomplete = [item["object_id"] for item in groups if item["status"] not in {"OUT_OF_SCOPE"} and not self._group_imported(scope, item["object_id"])]
        if incomplete:
            raise PreconditionFailed(f"仍有业务组缺少当前有效凭证的外部回执，不能完整关闭期间: {', '.join(incomplete)}")
        data = deepcopy(period["data"])
        data.update({"closed_by": actor_id, "close_time": utcnow(), "close_snapshot": {"groups": [item["object_id"] for item in groups]}})
        closed = self.store.revise_object(period["object_id"], expected_version, scope, data, status="CLOSED", created_by=actor_id)
        self.store.add_audit("PERIOD_CLOSED", actor_id, scope, object_type=period["object_type"], object_id=period["object_id"], object_version=closed["version"], before=period, after=closed, reason="所有业务组均有可核验的外部回执")
        return closed

    def archive_period(self, scope: Scope, *, actor_id: str, expected_version: int) -> dict[str, Any]:
        period = self.store.get_object(self._period_object_id(scope), scope)
        if period["version"] != expected_version or period["status"] != "CLOSED":
            raise PreconditionFailed("期间必须先关闭且版本必须为最新")
        data = deepcopy(period["data"])
        data["archived_at"] = utcnow()
        archived = self.store.revise_object(period["object_id"], expected_version, scope, data, status="ARCHIVED", created_by=actor_id)
        self.store.add_audit("PERIOD_ARCHIVED", actor_id, scope, object_type=period["object_type"], object_id=period["object_id"], object_version=archived["version"], before=period, after=archived, reason="形成期间归档包")
        return archived

    def lock_period(self, scope: Scope, *, actor_id: str, expected_version: int) -> dict[str, Any]:
        period = self.store.get_object(self._period_object_id(scope), scope)
        if period["version"] != expected_version:
            raise VersionConflict()
        if period["status"] not in {"CLOSED", "ARCHIVED"}:
            raise PreconditionFailed("期间未关闭，不能锁账")
        data = deepcopy(period["data"])
        data["locked_by"] = actor_id
        data["lock_time"] = utcnow()
        locked = self.store.revise_object(period["object_id"], expected_version, scope, data, status="LOCKED", created_by=actor_id)
        self.store.add_audit("PERIOD_LOCKED", actor_id, scope, object_type=period["object_type"], object_id=period["object_id"], object_version=locked["version"], before=period, after=locked, reason="锁账后的普通写操作全部拒绝")
        return locked

    def create_run(self, scope: Scope, *, actor_id: str, input_ids: list[str], model_version: str = "not-used") -> dict[str, Any]:
        self._ensure_period_open(scope)
        self._require_baseline_confirmed(scope)
        for item in input_ids:
            self.store.get_object(item, scope)
        runs = self.store.list_runs(scope)
        run = {"run_id": new_id("run"), "status": RunStatus.RUNNING.value, "input_fingerprint": digest({"inputs": input_ids, "scope": scope.model_dump()}), "baseline_version": self.store.get_object(self._baseline_object_id(scope), scope)["version"], "rule_version": "rules-current", "model_version": model_version, "schema_version": "processing-run-v1", "gateway_version": "gateway-v1", "attempt": 1, "parent_run_id": None, "result": {"input_ids": input_ids}}
        created = self.store.create_run(scope, run)
        self._set_current_run(scope, run["run_id"], actor_id)
        return created

    def retry_run(self, scope: Scope, *, run_id: str, actor_id: str) -> dict[str, Any]:
        old = self.store.get_run(run_id, scope)
        if old["status"] not in {RunStatus.FAILED.value, RunStatus.PAUSED.value, RunStatus.CANCELLED.value}:
            raise PreconditionFailed("只有失败、暂停或取消的任务可以重试")
        new_run = {"run_id": new_id("run"), "status": RunStatus.RUNNING.value, "input_fingerprint": old["input_fingerprint"], "baseline_version": old["baseline_version"], "rule_version": old["rule_version"], "model_version": old["model_version"], "schema_version": old["schema_version"], "gateway_version": old["gateway_version"], "attempt": old["attempt"] + 1, "parent_run_id": old["run_id"], "result": {"retry_of": old["run_id"], "retry_node": "FAILED_NODE"}}
        created = self.store.create_run(scope, new_run)
        self._set_current_run(scope, new_run["run_id"], actor_id)
        self.store.add_audit("RUN_RETRIED", actor_id, scope, object_type="ProcessingRun", object_id=new_run["run_id"], object_version=1, before=old, after=created, reason="从明确失败节点重试，旧 Run 保留")
        return created

    def cancel_run(self, scope: Scope, *, run_id: str, actor_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id, scope)
        if run["status"] != RunStatus.RUNNING.value:
            raise PreconditionFailed("只有运行中的任务可以取消")
        cancelled = self.store.update_run(run_id, scope, status=RunStatus.CANCELLED.value, result={**run["result"], "cancelled_by": actor_id, "cancelled_at": utcnow()})
        self.store.add_audit("RUN_CANCELLED", actor_id, scope, object_type="ProcessingRun", object_id=run_id, object_version=1, before=run, after=cancelled, reason="取消后迟到结果必须丢弃")
        return cancelled

    def complete_run(self, scope: Scope, *, run_id: str, actor_id: str, result: dict[str, Any]) -> dict[str, Any]:
        run = self.store.get_run(run_id, scope)
        if run["status"] != RunStatus.RUNNING.value:
            self.store.add_audit("LATE_RUN_RESULT_REJECTED", actor_id, scope, object_type="ProcessingRun", object_id=run_id, object_version=1, before=run, reason="取消或结束任务的迟到结果没有写入当前状态")
            raise PreconditionFailed("Run 已结束，迟到结果被拒绝")
        completed = self.store.update_run(run_id, scope, status=RunStatus.SUCCEEDED.value, result=result)
        self.store.add_audit("RUN_COMPLETED", actor_id, scope, object_type="ProcessingRun", object_id=run_id, object_version=1, after=completed, reason="固定输入和版本完成处理")
        return completed

    def replay_run(self, scope: Scope, *, run_id: str, actor_id: str) -> dict[str, Any]:
        source = self.store.get_run(run_id, scope)
        replay = {"run_id": new_id("run"), "status": RunStatus.RUNNING.value, "input_fingerprint": source["input_fingerprint"], "baseline_version": source["baseline_version"], "rule_version": source["rule_version"], "model_version": source["model_version"], "schema_version": source["schema_version"], "gateway_version": source["gateway_version"], "attempt": 1, "parent_run_id": source["run_id"], "result": {"replay_of": run_id, "comparison": None}}
        created = self.store.create_run(scope, replay)
        comparison = {"same_input_fingerprint": True, "source_result_digest": digest(source["result"]), "replay_result_digest": None}
        return self.store.update_run(created["run_id"], scope, status=RunStatus.SUCCEEDED.value, result={"replay_of": run_id, "comparison": comparison})

    def execute_command(self, scope: Scope, *, action: str, target_id: str, target_version: int, idempotency_key: str, actor_id: str, role: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        try:
            with self.store.database.transaction():
                if action not in ROLE_PERMISSIONS.get(role, set()):
                    raise PermissionDenied()
                existing = self.store.find_command(idempotency_key)
                if existing:
                    if existing["scope"] != scope.model_dump() or existing["actor_id"] != actor_id:
                        raise ScopeViolation("命令幂等键不属于当前操作人和处理范围")
                    expected = (action, target_id, target_version, payload)
                    recorded = (existing["action"], existing["target_id"], existing["target_version"], existing["request"])
                    if expected != recorded:
                        raise DomainError("相同幂等键不能用于不同请求", "IDEMPOTENCY_CONFLICT", 409)
                    if existing["status"] != "SUCCEEDED":
                        error = existing["effect"]
                        raise DomainError(error.get("reason", "该命令之前已被拒绝"), error.get("code", "COMMAND_REJECTED"), error.get("status_code", 409))
                    return {"idempotent": True, "command": existing, "effect": existing.get("effect", {})}
                self._assert_command_target_version(scope, action, target_id, target_version)
                reads_fixed_export = action == "export_package" and self.store.get_object(target_id, scope)["status"] in {"EXPORT_CREATED", "EXTERNAL_IMPORTED"}
                if action not in {"archive_period", "lock_period", "replay_run"} and not reads_fixed_export:
                    self._ensure_period_open(scope)
                effect = self._dispatch_command(scope, action=action, target_id=target_id, target_version=target_version, actor_id=actor_id, payload=payload)
                if self.store.database.settings.agent_mode == 'gateway' and action in {
                    'parse_artifact','reparse_fact','archive_artifact','confirm_statement_account',
                    'confirm_bill_business','revoke_bill_business','confirm_invoice_amount','revoke_invoice_amount',
                    'confirm_bank_period','revoke_bank_period','accept_bank_period','revoke_bank_period_intake',
                    'verify_source_values','revoke_source_verification','defer_material_issue','apply_parse_plan'}:
                    self.material_guidance.signal(scope,actor_id)
                command = {"command_id": new_id("cmd"), "idempotency_key": idempotency_key, "action": action, "target_id": target_id, "target_version": target_version, "scope": scope.model_dump(), "actor_id": actor_id, "status": "SUCCEEDED", "request": payload, "effect": effect, "created_at": utcnow()}
                self.store.save_command(command)
                self.store.add_audit("COMMAND_SUCCEEDED", actor_id, scope, object_id=target_id, object_version=target_version, after=effect, reason=action)
                return {"idempotent": False, "command": command, "effect": effect}
        except DomainError as exc:
            # Failed effects are rolled back before a separate rejection audit is committed.
            with self.store.database.transaction():
                if not self.store.find_command(idempotency_key):
                    if isinstance(exc, RuleConflictDetected):
                        conflict_object = self.store.create_initial_object(ObjectType.RULE_CONFLICT.value, scope, exc.conflict_data, status="OPEN", created_by=actor_id)
                        self.store.add_relation(RelationType.CONFLICTS_WITH.value, exc.candidate, conflict_object, evidence=exc.candidate["data"].get("evidence_ids", []), created_by=actor_id)
                    command = {"command_id": new_id("cmd"), "idempotency_key": idempotency_key, "action": action, "target_id": target_id, "target_version": target_version, "scope": scope.model_dump(), "actor_id": actor_id, "status": "REJECTED", "request": payload, "effect": {"code": exc.code, "reason": exc.message, "status_code": exc.status_code}, "created_at": utcnow()}
                    self.store.save_command(command)
                self.store.add_audit("COMMAND_REJECTED", actor_id, scope, object_id=target_id, object_version=target_version, reason=exc.message)
            raise

    def _dispatch_command(self, scope: Scope, *, action: str, target_id: str, target_version: int, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action=='save_material_opinion':
            if set(payload)!={'task_id','descriptor_hash','reason'}:
                raise PreconditionFailed('仅接受当前事项与处理意见，不接受改值或责任人')
            from app.material_guidance import GuidanceRequest,current_task
            try:
                request=GuidanceRequest(scope=scope,stage='MATERIAL_GUIDANCE',task_id=payload['task_id'],
                    descriptor_hash=payload['descriptor_hash'],request_id='opinion-'+digest([actor_id,payload,target_id,target_version]),user_text=payload['reason'])
            except ValidationError as exc:raise PreconditionFailed('意见字段无效') from exc
            task,_=current_task(self,request)
            if task['artifact_id']!=target_id:raise PreconditionFailed('事项与原件不匹配')
            return self.material_guidance.save_opinion(request,actor_id,'accountant')
        if action in {'retry_material_guidance','request_material_guidance'}:
            if payload:raise PreconditionFailed('建议排队与重试不接受修改内容')
            return (self.material_guidance.retry(scope,target_id,actor_id,'accountant') if action=='retry_material_guidance'
                    else self.material_guidance.enqueue(scope,actor_id))
        if action in {'confirm_bank_period','revoke_bank_period','accept_bank_period','revoke_bank_period_intake'}:
            return self.bank_periods.execute(scope,action,self.store.get_object(target_id,scope),actor_id,payload)
        if action in {'request_problem_review', 'retry_problem_review'}:
            if payload:
                raise PreconditionFailed('复核命令不接受业务值或模型结论')
            return (self.problem_review.enqueue(scope, actor_id) if action=='request_problem_review'
                    else self.problem_review.retry(scope, target_id, actor_id))
        if action=='inspect_parse_plan':
            if 'document_kind' not in payload or set(payload)-{'document_kind','row_start','page_size'}:
                raise PreconditionFailed('查看结构只接受资料类型和行窗口')
            try:
                request=InspectRequest(scope=scope,artifact_id=target_id,artifact_version=target_version,**payload)
                return self.parse_plans.inspect(request)
            except ValueError as exc:raise PreconditionFailed('原件结构暂不能读取，请核对资料类型或格式') from exc
        if action=='preview_parse_plan':
            return self.parse_plans.preview(scope,target_id,target_version,actor_id,payload)
        if action=='apply_parse_plan':
            return self.parse_plans.apply(scope,target_id,target_version,actor_id,payload)
        if action in {'confirm_invoice_amount','revoke_invoice_amount'}:
            return self.invoice_amounts.execute(scope, action, target_id, target_version, actor_id, payload)
        if action in {'confirm_bill_business', 'revoke_bill_business'}:
            return self.bills.execute(scope, action, target_id, target_version, actor_id, payload)
        if action=='register_bank_account':
            account=self.bank_accounts.register(scope,actor_id,payload)
            return {'object':account,'associated_statements':self.bank_accounts.associate_matching(scope,actor_id,account['object_id'])}
        if action=='confirm_statement_account':
            return self.bank_accounts.confirm(scope,target_id,actor_id,payload)
        if action=='request_payroll_mapping':
            return self.payroll_mapping.request(scope,target_id,target_version,actor_id,payload)
        if action=='apply_payroll_mapping':
            return self.payroll_mapping.apply(scope,target_id,target_version,actor_id,payload)
        if action=='preview_payroll_mapping':
            return self.payroll_mapping.preview(scope,target_id,target_version,actor_id,payload)
        if action in {'verify_source_values','revoke_source_verification','defer_material_issue'}:
            return self.materials.execute(scope,action,target_id,target_version,actor_id,payload)
        if action == "save_historical_issue_plan":
            return {"object": self.historical_plans.save(scope, target_id, target_version, actor_id, payload)}
        if action == "review_historical_issue_plan":
            return {"object": self.historical_plans.review(scope, target_id, target_version, actor_id, payload)}
        if action == "prepare_historical":
            if set(payload) - {"artifact_ids"}:
                raise PreconditionFailed("历史处理命令仅接受当前范围的原件选择")
            return {"object": self.historical.enqueue(scope, actor_id, retry=True, artifact_ids=payload.get("artifact_ids"))}
        if action == "parse_artifact":
            return self.parse_artifact(scope, artifact_id=target_id, actor_id=actor_id, expected_version=target_version, payload=payload)
        if action == "confirm_baseline":
            return {"object": self.confirm_baseline(scope, actor_id=actor_id, expected_version=target_version, payload=payload)}
        if action == "create_procurement_group":
            return {"object": self.create_procurement_business(scope, fact_ids=payload.get("fact_ids", []), business_identity=payload.get("business_identity", target_id), actor_id=actor_id)}
        if action == "approve_rule":
            return self.approve_rule(scope, card_id=target_id, actor_id=actor_id, expected_version=target_version, payload=payload)
        if action == "approve_rule_batch":
            return self.approve_rule_batch(scope, card_ids=payload.get("card_ids", []), actor_id=actor_id, preview_only=bool(payload.get("preview_only", False)))
        if action == "resolve_rule_conflict":
            return self.resolve_rule_conflict(scope, conflict_id=target_id, actor_id=actor_id, expected_version=target_version,
                                              resolution=payload.get("resolution", ""), reason=payload.get("reason", ""))
        if action == "revoke_rule":
            return self.revoke_rule(scope, rule_id=target_id, actor_id=actor_id, expected_version=target_version, reason=payload.get("reason", ""))
        if action == "confirm_grouping":
            return {"object": self.confirm_grouping(scope, group_id=target_id, actor_id=actor_id, expected_version=target_version)}
        if action == "suspend_group":
            return {"object": self.suspend_group(scope, group_id=target_id, actor_id=actor_id, expected_version=target_version, reason=payload.get("reason", "资料或关系待补充"))}
        if action == "generate_draft":
            return {"object": self.generate_draft(scope, group_id=target_id, actor_id=actor_id)}
        if action == "validate_draft":
            return {"object": self.validate_draft(scope, voucher_id=target_id, actor_id=actor_id, expected_version=target_version)}
        if action == "revise_voucher":
            return {"object": self.revise_voucher(scope, voucher_id=target_id, actor_id=actor_id, expected_version=target_version, lines=payload.get("lines", []))}
        if action == "release_delivery":
            return {"object": self.release_delivery(scope, group_id=target_id, actor_id=actor_id)}
        if action == "export_package":
            return self.export_package(scope, package_id=target_id, actor_id=actor_id)
        if action == "ack_external_import":
            return self.ack_external_import(scope, package_id=target_id, actor_id=actor_id, payload=payload)
        if action == "close_period":
            return {"object": self.close_period(scope, actor_id=actor_id, expected_version=target_version)}
        if action == "archive_period":
            return {"object": self.archive_period(scope, actor_id=actor_id, expected_version=target_version)}
        if action == "lock_period":
            return {"object": self.lock_period(scope, actor_id=actor_id, expected_version=target_version)}
        if action == "archive_artifact":
            return {"object": self.archive_artifact(scope, artifact_id=target_id, actor_id=actor_id, expected_version=target_version)}
        if action == "reparse_fact":
            return {"object": self.reparse_fact(scope, fact_id=target_id, actor_id=actor_id, expected_version=target_version, parser_version=payload.get("parser_version", "parser-v2"), normalized_value=payload.get("normalized_value", {}))}
        if action == "split_group":
            return {"object": self.split_group(scope, group_id=target_id, actor_id=actor_id, expected_version=target_version, fact_ids=payload.get("fact_ids", []), new_group_id=payload.get("new_group_id"))}
        if action == "merge_groups":
            return {"object": self.merge_groups(scope, group_ids=payload.get("group_ids", []), actor_id=actor_id, new_group_id=payload.get("new_group_id"))}
        if action == "rerun_group":
            old = self.store.get_object(target_id, scope)
            run = self.create_run(scope, actor_id=actor_id, input_ids=old["data"].get("member_fact_ids", []), model_version=payload.get("model_version", "not-used"))
            return {"run": run}
        if action == "retry_run":
            return {"run": self.retry_run(scope, run_id=target_id, actor_id=actor_id)}
        if action == "replay_run":
            return {"run": self.replay_run(scope, run_id=target_id, actor_id=actor_id)}
        if action == "cancel_run":
            return {"run": self.cancel_run(scope, run_id=target_id, actor_id=actor_id)}
        if action == "complete_run":
            return {"run": self.complete_run(scope, run_id=target_id, actor_id=actor_id, result=payload.get("result", {}))}
        if action == "reconcile_group":
            return {"checks": self.reconcile_group(scope, group_id=target_id, actor_id=actor_id)}
        raise DomainError(f"不支持的命令: {action}", "UNKNOWN_COMMAND", 422)

    def _assert_command_target_version(self, scope: Scope, action: str, target_id: str, target_version: int) -> None:
        if action in {"retry_run", "replay_run", "cancel_run", "complete_run"}:
            run = self.store.get_run(target_id, scope)
            if target_version != 1:
                raise VersionConflict("Run 命令版本必须为固定版本 1")
            return
        if action == "approve_rule_batch":
            if target_version != 1:
                raise VersionConflict("批量命令版本必须为固定版本 1")
            return
        if action == "create_procurement_group":
            if target_version != 1 or not target_id:
                raise PreconditionFailed("创建采购业务组必须提供稳定业务标识和固定版本 1")
            return
        if action == "merge_groups":
            if not target_id:
                raise PreconditionFailed("合并命令必须有批次目标")
            return
        current = self.store.get_object(target_id, scope)
        expected_type = {
            'confirm_invoice_amount': 'FactRecord',
            'revoke_invoice_amount': 'InvoiceAmountConfirmation',
            'confirm_bill_business': 'FactRecord',
            'revoke_bill_business': 'BillBusinessConfirmation',
            'register_bank_account':'AccountingPeriod',
            'confirm_statement_account':'SourceArtifact',
            'request_payroll_mapping':'SourceArtifact',
            'apply_payroll_mapping':'PayrollMapping',
            'preview_payroll_mapping':'PayrollMapping',
            'inspect_parse_plan':'SourceArtifact',
            'apply_parse_plan':'ParsePlan',
            'verify_source_values': 'SourceArtifact',
            'request_problem_review': 'AccountingPeriod',
            'save_material_opinion':'SourceArtifact',
            'retry_material_guidance':'MaterialGuidanceJob',
            'request_material_guidance':'AccountingPeriod',
            'confirm_bank_period':'SourceArtifact',
            'revoke_bank_period':'BankPeriodAssignment',
            'accept_bank_period':'AccountingPeriod',
            'revoke_bank_period_intake':'BankPeriodIntake',
            'retry_problem_review': 'ProblemReview',
            'defer_material_issue': 'SourceArtifact',
            'revoke_source_verification': 'SourceVerification',
            "parse_artifact": ObjectType.SOURCE_ARTIFACT.value,
            "confirm_baseline": ObjectType.BASELINE.value,
            "prepare_historical": ObjectType.BASELINE.value,
            "save_historical_issue_plan": "HistoricalPreparation",
            "review_historical_issue_plan": "HistoricalIssuePlan",
            "approve_rule": ObjectType.CONFIRMATION_CARD.value,
            "resolve_rule_conflict": ObjectType.RULE_CONFLICT.value,
            "revoke_rule": ObjectType.RULE_INSTANCE.value,
            "archive_artifact": ObjectType.SOURCE_ARTIFACT.value,
            "reparse_fact": ObjectType.FACT_RECORD.value,
            **{name: ObjectType.PROCESSING_GROUP.value for name in ("confirm_grouping", "suspend_group", "rerun_group", "generate_draft", "release_delivery", "split_group", "reconcile_group")},
            **{name: ObjectType.VOUCHER_VERSION.value for name in ("validate_draft", "revise_voucher")},
            **{name: ObjectType.DELIVERY_PACKAGE.value for name in ("export_package", "ack_external_import")},
            **{name: ObjectType.ACCOUNTING_PERIOD.value for name in ("close_period", "archive_period", "lock_period")},
        }.get(action)
        if expected_type and current["object_type"] != expected_type:
            raise PreconditionFailed("命令目标对象类型不匹配")
        if current["version"] != target_version:
            raise VersionConflict()

    def display_context(self, scope: Scope) -> dict[str, Any]:
        """Read labels separately from the immutable scope identifiers."""
        scopes = self.store.list_objects(ObjectType.SCOPE.value, scope)
        profile = scopes[-1]["data"].get("enterprise_profile", {}) if scopes else {}
        try:
            book = self.store.get_object(self._book_object_id(scope), scope)["data"]
        except KeyError:
            book = {}
        name = str(book.get("name") or "").strip()
        return {
            "company_name": profile.get("name"),
            "business_license_number": profile.get("business_license_number"),
            "ledger_name": name if name and name != scope.ledger_id else "主账套",
        }

    def workbench(self, scope: Scope, *, _problem_review: bool = True, actor_id: str | None = None) -> dict[str, Any]:
        period = self.store.get_object(self._period_object_id(scope), scope)
        baseline = self.store.get_object(self._baseline_object_id(scope), scope)
        try:
            self._require_baseline_confirmed(scope)
            baseline_validation = {"status": "VALID", "reason": None}
        except DomainError as exc:
            baseline_validation = {"status": "DRAFT" if baseline["status"] == "DRAFT" else "INVALID", "reason": str(exc)}
        groups = self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope)
        artifacts = self.store.list_objects(ObjectType.SOURCE_ARTIFACT.value, scope)
        vouchers = self.store.list_objects(ObjectType.VOUCHER_VERSION.value, scope)
        deliveries = self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope)
        cards = self.store.list_objects(ObjectType.CONFIRMATION_CARD.value, scope, statuses=["PENDING"])
        runs = self.store.list_runs(scope)
        current_run = runs[-1] if runs else None
        recon = self.store.list_reconciliation(scope)
        facts = self.store.list_objects(ObjectType.FACT_RECORD.value, scope)
        counts = {
            "source_artifacts": len(artifacts),
            "facts": len(facts),
            "groups": len(groups),
            "pending_confirmation_cards": len(cards),
            "blockers": 0,
            "reconciliation_checks": len(recon),
        }
        fact_summaries = []
        for fact in facts:
            value = fact["data"].get("normalized_value") or {}
            if not isinstance(value, dict):
                value = {}
            fact_summaries.append({
                "object_id": fact["object_id"],
                "version": fact["version"],
                "status": fact["status"],
                "record_type": fact["data"].get("record_type"),
                "source_artifact_id": fact["data"].get("source_artifact_id"),
                "source_anchor": fact["data"].get("source_anchor"),
                "summary": {
                    key: value.get(key)
                    for key in ("invoice_no", "contract_no", "stock_in_no", "transaction_date", "payment_total", "supplier", "amount")
                    if value.get(key) is not None
                },
            })
        blockers = []
        for group in groups:
            if group["status"] in {"BLOCKED", "SUSPENDED"} or group["data"].get("missing_evidence") or group["data"].get("reconciliation_status") == "BLOCKED":
                blockers.append({"group_id": group["object_id"], "status": group["status"], "missing_evidence": group["data"].get("missing_evidence", []), "reason": group["data"].get("suspense_reason") or "确定性校验未通过"})
        counts["blockers"] = len(blockers)
        deliverable = []
        if baseline_validation["status"] == "VALID":
            for item in groups:
                if item["status"] not in {"READY", "CONFIRMED"}:
                    continue
                try:
                    self._require_current_reconciliation(scope, item)
                except DomainError:
                    continue
                deliverable.append(item)
        checked_groups = []
        if baseline_validation["status"] == "VALID":
            for group in groups:
                if group["status"] in {"VOID", "MERGED", "SUSPENDED", "BLOCKED"}:
                    continue
                try:
                    self._require_current_reconciliation(scope, group)
                except (DomainError, KeyError):
                    continue
                checked_groups.append(group)
        checked_vouchers = []
        for voucher in vouchers:
            group = next((g for g in checked_groups if g["object_id"] == voucher["data"].get("group_id")), None)
            if group and voucher["status"] in {"LOCALLY_CONFIRMED", "EXPORTED", "EXTERNAL_IMPORTED"}:
                try:
                    self._require_voucher_sources(group, voucher)
                except DomainError:
                    continue
                checked_vouchers.append(voucher)
        current_artifacts = [item for item in artifacts if item["status"] != "ARCHIVED" and item["data"].get("observed_period") == scope.accounting_period_id]
        parse_statuses = [item["data"].get("parse_status", "RECEIVED") for item in current_artifacts]
        if not current_artifacts:
            source_stage = {"status": "NOT_STARTED", "summary": "尚未接收本期原始资料", "completed_count": 0, "total_count": 0}
        else:
            source_stage = {"status": "COMPLETED", "summary": f"已接收 {len(current_artifacts)} 份本期原件", "completed_count": len(current_artifacts), "total_count": len(current_artifacts)}
        parsed_current = sum(status in {"PARSED", "PARSED_WITH_ISSUES"} for status in parse_statuses)
        failed_current = sum(status == "FAILED" for status in parse_statuses)
        if not current_artifacts:
            analysis_stage = {"status": "NOT_STARTED", "summary": "等待资料进入解析", "completed_count": 0, "total_count": 0}
        elif failed_current or parsed_current < len(current_artifacts) or not counts["facts"]:
            analysis_stage = {"status": "PARTIAL" if parsed_current else "WAITING", "summary": f"已解析 {parsed_current} / {len(current_artifacts)} 份，保留待复核项", "completed_count": parsed_current, "total_count": len(current_artifacts)}
        else:
            analysis_stage = {"status": "COMPLETED", "summary": f"已形成 {counts['facts']} 条结构化事实", "completed_count": counts["facts"], "total_count": counts["facts"]}
        if not groups:
            validation_stage = {"status": "NOT_STARTED", "summary": "等待业务组进入校验", "completed_count": 0, "total_count": 0}
        elif baseline_validation["status"] != "VALID":
            validation_stage = {"status": "WAITING", "summary": "等待基线确认后继续", "completed_count": 0, "total_count": len(groups)}
        elif blockers or cards:
            validation_stage = {"status": "BLOCKED" if blockers else "WAITING", "summary": f"{len(blockers)} 组阻断，{len(cards)} 项待人工确认", "completed_count": 0, "total_count": len(groups)}
        else:
            passed_groups = len(checked_groups)
            validation_stage = {"status": "COMPLETED" if passed_groups == len(groups) else "PARTIAL", "summary": f"已通过 {passed_groups} / {len(groups)} 组校验", "completed_count": passed_groups, "total_count": len(groups)}
        confirmed_vouchers = len(checked_vouchers)
        if not vouchers:
            voucher_stage = {"status": "NOT_STARTED", "summary": "尚未生成凭证版本", "completed_count": 0, "total_count": 0}
        else:
            voucher_stage = {"status": "COMPLETED" if confirmed_vouchers == len(vouchers) else "PARTIAL", "summary": f"当前有效复核 {confirmed_vouchers} / {len(vouchers)} 个版本" + ("；其余待复核或来源已变化" if confirmed_vouchers < len(vouchers) else ""), "completed_count": confirmed_vouchers, "total_count": len(vouchers)}
        imported_deliveries = sum(item["status"] == "EXTERNAL_IMPORTED" for item in deliveries)
        delivery_stage = {"status": "COMPLETED" if deliveries and imported_deliveries == len(deliveries) else ("PARTIAL" if deliveries else "NOT_STARTED"), "summary": f"已完成 {imported_deliveries} / {len(deliveries)} 个交付包" if deliveries else "尚未形成交付包", "completed_count": imported_deliveries, "total_count": len(deliveries)}
        stage_items = [
            {"id": "source", "name": "资料接收", **source_stage},
            {"id": "analysis", "name": "资料分析", **analysis_stage},
            {"id": "validation", "name": "待确认与校验", **validation_stage},
            {"id": "voucher", "name": "凭证复核", **voucher_stage},
            {"id": "delivery", "name": "交付归档", **delivery_stage},
        ]
        completed_stages = sum(item["status"] == "COMPLETED" for item in stage_items)
        progress = {"stages": stage_items, "completed_count": completed_stages, "total_count": len(stage_items),
                    "overall_percent": int(completed_stages / len(stage_items) * 100),
                    "current_stage": next((item["id"] for item in stage_items if item["status"] != "COMPLETED"), "delivery")}
        historical_preparation = self.historical.view(scope)
        historical_issue_plans = self.historical_plans.view(scope, historical_preparation)
        progress["prerequisite"] = historical_prerequisite(
            historical_preparation, historical_issue_plans, baseline_validation["status"]
        )
        readiness = build_readiness(scope, artifacts=artifacts, facts=facts, baseline=baseline,
                                   baseline_valid=baseline_validation["status"] == "VALID",
                                   checked_groups=checked_groups, checked_vouchers=checked_vouchers,
                                   model_runs=[r for r in self.store.list_objects(ObjectType.MODEL_RUN.value, scope)
                                               if r['data'].get('stage') != 'PROBLEM_REVIEW'])
        next(c for c in readiness["categories"] if c["id"] == "purchase")["business_issues"] = blockers
        bill_review = self.bills.view(scope, artifacts, facts)
        invoice_review = self.invoice_amounts.view(scope, artifacts, facts)
        material_review = self.materials.view(scope,readiness,artifacts,facts,bill_review,invoice_review)
        review = {'jobs':[], 'counts':{}, 'system_tasks':[], 'fingerprint':''}
        if _problem_review:
            material_review, review = self.problem_review.project(scope, material_review, artifacts, facts)
            material_review = self.material_guidance.project(scope,material_review,actor_id=actor_id)
        return {
            "scope": scope.model_dump(), "display_context": self.display_context(scope), "period": period, "baseline": baseline,
            "baseline_validation": baseline_validation, "current_run": current_run, "latest_run_only": True,
            "historical_preparation": historical_preparation,
            "historical_issue_plans": historical_issue_plans,
            "counts": counts, "data_readiness": readiness,
            "material_review": material_review,
            "bank_periods": self.bank_periods.view(scope),
            "problem_review": review,
            "invoice_amount_review": invoice_review,
            "bill_review": bill_review,
            "payroll_mappings": self.payroll_mapping.view(scope),
            "parse_plans": self.parse_plans.view(scope),
            "material_guidance": [r for r in self.store.list_objects(ObjectType.MODEL_RUN.value, scope)
                                  if r['data'].get('stage') == 'MATERIAL_GUIDANCE'
                                  and (r['data'].get('opinion_status','NONE') == 'NONE'
                                       or (actor_id is not None and r['data'].get('requested_by') == actor_id))],
            "bank_accounts": self.bank_accounts.view(scope,artifacts),
            "artifacts": artifacts, "fact_summaries": fact_summaries, "vouchers": vouchers, "deliveries": deliveries, "progress": progress,
            "groups": groups, "pending_confirmation_cards": cards, "blockers": blockers,
            "deliverable_groups": deliverable, "history_runs": runs,
        }

    def portfolio(self, scopes: list[Scope]) -> dict[str, Any]:
        """Build a read-only multi-scope operator summary after auth filtering."""
        items = []
        for scope in scopes:
            overview = self.workbench(scope)
            counts = overview["counts"]
            if counts["blockers"]:
                next_action = "查看阻断证据"
            elif counts["pending_confirmation_cards"]:
                next_action = "处理待确认规则"
            elif overview["deliverable_groups"]:
                next_action = "复核可交付业务组"
            elif counts["source_artifacts"] == 0:
                next_action = "接收原始资料"
            else:
                next_action = "查看期间工作台"
            items.append({
                "scope": overview["scope"],
                "display_context": overview["display_context"],
                "period": {
                    "object_id": overview["period"]["object_id"],
                    "status": overview["period"]["status"],
                    "period": overview["period"]["data"].get("period"),
                },
                "baseline": {
                    "object_id": overview["baseline"]["object_id"],
                    "status": overview["baseline"]["status"],
                    "validation": overview["baseline_validation"],
                },
                "counts": counts,
                "blockers": overview["blockers"],
                "pending_confirmation_cards": len(overview["pending_confirmation_cards"]),
                "deliverable_groups": len(overview["deliverable_groups"]),
                "current_run": overview["current_run"],
                "next_action": next_action,
            })
        return {"scope_count": len(items), "scopes": items}

    def history(self, scope: Scope, authorized: list[Scope]) -> dict[str, Any]:
        """Read prior authorized periods and immutable archived voucher bindings."""
        related_scopes = [candidate for candidate in authorized if (
            candidate.tenant_id == scope.tenant_id
            and candidate.organization_id == scope.organization_id
            and candidate.legal_entity_id == scope.legal_entity_id
            and candidate.ledger_id == scope.ledger_id
        )]
        periods = []
        for candidate in related_scopes:
            try:
                overview = self.workbench(candidate)
            except (DomainError, KeyError):
                continue
            periods.append({
                "scope": overview["scope"],
                "display_context": overview["display_context"],
                "period": overview["period"],
                "baseline_status": overview["baseline"]["status"],
                "counts": overview["counts"],
                "current_run": overview["current_run"],
            })
        packages = [item for item in self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope)
                    if item["status"] == "EXTERNAL_IMPORTED"]
        archived = []
        for package in packages:
            voucher_id = package["data"].get("voucher_version_id")
            export_id = package["data"].get("export_id")
            if not voucher_id or not export_id:
                continue
            voucher = self.store.get_object(voucher_id, scope, package["data"].get("voucher_version"))
            export = self.store.get_object(export_id, scope)
            archived.append({
                "package": {"object_id": package["object_id"], "version": package["version"], "status": package["status"], "data": package["data"]},
                "voucher": voucher,
                "export": export,
            })
        return {"scope": scope.model_dump(), "periods": periods, "archived_vouchers": archived}

    def object_detail(self, object_id: str, scope: Scope, version: int | None = None) -> dict[str, Any]:
        obj = self.store.get_object(object_id, scope, version)
        return {"object": obj, "relations": self.store.list_relations(scope, object_id), "audits": self.store.list_audits(scope, object_id), "versions": self.store.list_objects(obj["object_type"], scope, latest_only=False) if obj["object_type"] else []}

    def query(self, scope: Scope, question: str) -> dict[str, Any]:
        lowered = question.lower()
        groups = self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope)
        if "未匹配付款" in question or "没有匹配付款" in question or "payment" in lowered:
            results = [item for item in groups if "PAYMENT" not in item["data"].get("fact_type_index", []) or "PAYMENT_INVOICE" in {check["check_type"] for check in self.store.list_reconciliation(scope, item["object_id"]) if check["result"] == "BLOCKED"}]
            return self._query_response(question, results, "仅根据当前 Scope 的结构化事实和对账结果查询；结果为空不代表系统外没有付款。" if results else "当前 Scope 内没有找到可支撑‘未匹配付款’的记录；不能据此断言确定没有付款。")
        if "入库" in question or "stock" in lowered:
            results = [item for item in groups if "STOCK_IN" not in item["data"].get("fact_type_index", [])]
            return self._query_response(question, results, "结果表示缺少已接收的入库证据，不等同于现实中没有入库。")
        if "暂挂" in question or "suspense" in lowered or "阻断" in question:
            results = [item for item in groups if item["status"] in {"SUSPENDED", "BLOCKED"}]
            return self._query_response(question, results, "以下业务组因证据或确定性校验问题暂挂，安全业务组仍可独立处理。")
        if "规则" in question or "历史" in question or "conflict" in lowered:
            results = self.store.list_objects(ObjectType.RULE_CONFLICT.value, scope) + self.store.list_objects(ObjectType.CONFIRMATION_CARD.value, scope, statuses=["PENDING"])
            return self._query_response(question, results, "返回规则冲突和待确认卡；未确认候选规则不会被回答为正式规则。")
        if "交付" in question or "deliver" in lowered:
            results = [item for item in groups if item["status"] == "READY" and item["data"].get("reconciliation_status") == "PASS"]
            return self._query_response(question, results, "只有对账通过、凭证本地复核完成的业务组才会进入可交付集合。")
        if "重新分析" in question or "变化" in question or "run" in lowered:
            runs = self.store.list_runs(scope)
            return self._query_response(question, runs, "Run 按固定输入和版本保存；重新分析只产生新的 Run，不覆盖旧结果。")
        return self._query_response(question, [], "无法用当前结构化对象和证据确认该问题；请补充明确的对象或资料范围。")

    def _query_response(self, question: str, results: list[dict[str, Any]], explanation: str) -> dict[str, Any]:
        return {"question": question, "scope_query": True, "structured_results": results, "result_count": len(results), "explanation": explanation, "agent_used_after_structured_query": False}

    def create_procurement_demo(self, scope: Scope, *, actor_id: str = "demo", variant: str = "normal") -> dict[str, Any]:
        if self.store.database.settings.require_auth:
            raise PermissionDenied("合成演示只能用于显式关闭认证的隔离测试环境")
        self.create_scope(scope, actor_id=actor_id)
        baseline = self.store.get_object(self._baseline_object_id(scope), scope)
        if baseline["status"] != "CONFIRMED" or baseline["data"].get("validation_version") != VALIDATION_VERSION:
            self.confirm_baseline(scope, actor_id=actor_id, expected_version=baseline["version"], payload=self._demo_baseline_payload(scope, actor_id))
        if variant not in {"normal", "missing_stock", "amount_mismatch"}:
            raise DomainError("未知采购演示变体", "INVALID_DEMO_VARIANT", 422)
        artifact_specs = [("合同.pdf", "CONTRACT", b"contract:purchase-001", {"contract_no": "C-001"}), ("进项发票.pdf", "INVOICE", b"invoice:purchase-001", {"invoice_no": "INV-001"}), ("付款流水.csv", "PAYMENT", b"payment:purchase-001", {"transaction_id": "PAY-001"})]
        if variant == "normal":
            artifact_specs.append(("入库单.pdf", "STOCK_IN", b"stock:purchase-001", {"warehouse": "A-01"}))
        fact_ids = []
        for filename, record_type, content, original in artifact_specs:
            artifact = self.create_artifact(ArtifactInput(scope=scope, filename=filename, content_base64=base64.b64encode(content).decode(), source_channel="DEMO", observed_period=scope.accounting_period_id, mime_type="text/plain"), actor_id=actor_id)
            if record_type == "INVOICE":
                normalized = {"external_id": "INV-001", "invoice_total": 1130, "net_amount": 1000, "tax": 130, "tax_rate": 0.13, "supplier_ref": "SUP-001"}
            elif record_type == "PAYMENT":
                normalized = {"external_id": "PAY-001", "payment_total": 1130, "supplier_ref": "SUP-001"}
            else:
                normalized = {"external_id": f"{record_type}-001", **original}
            fact = next((item for item in self.store.list_objects(ObjectType.FACT_RECORD.value, scope) if item["data"].get("source_artifact_id") == artifact["object_id"] and item["data"].get("record_type") == record_type), None)
            if fact is None:
                fact = self.create_fact_record(FactInput(scope=scope, source_artifact_id=artifact["object_id"], source_anchor=SourceAnchor(page=1, row=1, field=record_type.lower()), record_type=record_type, original_value=original, normalized_value=normalized, parser_version="demo-parser-v1", extraction_confidence=0.99), actor_id=actor_id)
            fact_ids.append(fact["object_id"])
        group = self.create_procurement_business(scope, fact_ids=fact_ids, business_identity="purchase-001", actor_id=actor_id)
        if variant == "amount_mismatch":
            for fact in self.store.list_objects(ObjectType.FACT_RECORD.value, scope):
                if fact["data"].get("record_type") == "PAYMENT":
                    revised_data = deepcopy(fact["data"])
                    revised_data["normalized_value"]["payment_total"] = 900
                    fact = self.store.revise_object(fact["object_id"], fact["version"], scope, revised_data, status="PARSED", created_by=actor_id)
        group = self._refresh_group(scope, self.store.get_object(group["object_id"], scope), actor_id=actor_id)
        checks = self.reconcile_group(scope, group_id=group["object_id"], actor_id=actor_id)
        run = self.create_run(scope, actor_id=actor_id, input_ids=fact_ids, model_version="fixture-procurement-parser")
        run = self.complete_run(scope, run_id=run["run_id"], actor_id=actor_id, result={"status": "SUCCEEDED", "group_id": group["object_id"], "variant": variant, "mock": True})
        return {"scope": scope.model_dump(), "group": self.store.get_object(group["object_id"], scope), "facts": [self.store.get_object(item, scope) for item in fact_ids], "checks": checks, "run": run, "variant": variant}

    # ---------- helpers ----------

    def _fact_source_identity(self, scope: Scope, fact: dict[str, Any]) -> str:
        data = fact["data"]
        artifact = self.store.get_object(data["source_artifact_id"], scope)
        return digest({"sha256": artifact["data"]["sha256"], "anchor": data["source_anchor"], "record_type": data["record_type"]})

    def _fact_identity_keys(self, scope: Scope, fact: dict[str, Any]) -> set[tuple[str, ...]]:
        keys = {("source", self._fact_source_identity(scope, fact))}
        values = fact["data"].get("normalized_value", {})
        kind = fact["data"].get("record_type")
        fields = {"INVOICE": ("invoice_no", "external_id"), "PAYMENT": ("transaction_id", "external_id")}
        if kind in fields:
            # Preserve every alias: adding invoice_no must never erase external_id.
            identifiers = {str(values[k]).strip().upper() for k in fields[kind]
                           if type(values.get(k)) in {str, int} and str(values[k]).strip()}
            account = ""
            if kind == "PAYMENT":
                accounts = [values[k] for k in ("bank_account_ref", "account_ref") if values.get(k) not in (None, "")]
                if accounts and all(isinstance(a, str) and a.strip() and len(a) <= 128 and not any(unicodedata.category(ch).startswith("C") for ch in a) for a in accounts):
                    normalized_accounts = {a.strip().upper() for a in accounts}
                    # Conflicting aliases do not establish a known bank account.
                    if len(normalized_accounts) == 1:
                        account = normalized_accounts.pop()
            keys.update(("business", kind, identifier, account) for identifier in identifiers)
        return keys

    def _duplicate_facts(self, scope: Scope, group: dict[str, Any]) -> list[dict[str, Any]]:
        owners, conflicts = {}, []
        group_id = group["object_id"]

        def matches(key):
            # An unknown bank account cannot disprove a duplicate. Two explicitly
            # different accounts may legitimately use the same bank-local number.
            identity, account = (key[:3], key[3]) if key[0] == "business" else (key, "")
            return identity, [(fid, bank) for fid, bank in owners.get(identity, [])
                              if not account or not bank or account == bank], account

        for fact_id in group["data"].get("member_fact_ids", []):
            for key in self._fact_identity_keys(scope, self.store.get_object(fact_id, scope)):
                identity, previous, account = matches(key)
                for owner_id, _ in previous:
                    conflicts.append({"fact_id": fact_id, "other_fact_id": owner_id, "identity": identity, "group_id": group_id})
                owners.setdefault(identity, []).append((fact_id, account))
        for other in self.store.list_objects(ObjectType.PROCESSING_GROUP.value, scope):
            if other["object_id"] == group_id or other["status"] in {"VOID", "MERGED"}:
                continue
            if not other["data"].get("confirmed_by") and other["status"] not in {"CONFIRMED", "READY", "DELIVERED", "ARCHIVED"}:
                continue
            for fact_id in other["data"].get("member_fact_ids", []):
                for key in self._fact_identity_keys(scope, self.store.get_object(fact_id, scope)):
                    identity, previous, _ = matches(key)
                    for owner_id, _ in previous:
                        conflicts.append({"fact_id": owner_id, "other_fact_id": fact_id, "identity": identity, "group_id": other["object_id"]})
        return conflicts

    def _require_voucher_sources(self, group: dict[str, Any], voucher: dict[str, Any]) -> None:
        if not voucher["data"].get("reconciliation_basis") or voucher["data"]["reconciliation_basis"] != group["data"].get("reconciliation_basis"):
            raise PreconditionFailed("凭证固定的来源事实已变化，不能用新的校验结果放行旧凭证；请重新生成修订版本")

    def _group_basis(self, scope: Scope, group: dict[str, Any]) -> dict[str, Any]:
        facts, evidence = [], []
        for fact_id in sorted(group["data"].get("member_fact_ids", [])):
            fact = self.store.get_object(fact_id, scope)
            artifact = self.store.get_object(fact["data"]["source_artifact_id"], scope)
            facts.append({"fact_id": fact_id, "fact_version": fact["version"], "fact_status": fact["status"],
                          "artifact_id": artifact["object_id"], "artifact_version": artifact["version"], "artifact_status": artifact["status"],
                          'source_current':self.materials.source_valid(artifact) and artifact['data'].get('parse_status')!='FAILED' and ('parsed_fact_ids' not in artifact['data'] or fact_id in artifact['data']['parsed_fact_ids'])})
        for evidence_id in sorted(group["data"].get("evidence_ids", [])):
            item = self.store.get_object(evidence_id, scope)
            evidence.append({"id": evidence_id, "version": item["version"], "status": item["status"],
                             "expired": bool(item["data"].get("expired")), "conflict": bool(item["data"].get("conflict"))})
        baseline = self.store.get_object(self._baseline_object_id(scope), scope)
        return {"facts": facts, "evidence": evidence, "engine_version": ENGINE_VERSION,
                "baseline": {"id": baseline["object_id"], "version": baseline["version"], "status": baseline["status"]}}

    def _require_current_reconciliation(self, scope: Scope, group: dict[str, Any]) -> None:
        if group["data"].get("reconciliation_basis") != digest(self._group_basis(scope, group)):
            raise PreconditionFailed("来源事实、资料或证据版本已变化，须重新校验，不能复用旧放行结果")
        if group["data"].get("reconciliation_status") != "PASS":
            raise PreconditionFailed("确定性校验未通过")
        if self._duplicate_facts(scope, group):
            raise PreconditionFailed("重复来源或外部事实已被其他业务组确认，不能继续记账")

    def _scope_id(self, scope: Scope) -> str:
        return "scope:" + ":".join([scope.tenant_id, scope.organization_id, scope.legal_entity_id, scope.ledger_id, scope.accounting_period_id])

    def _scoped_system_object_id(self, scope: Scope, prefix: str, legacy_id: str) -> str:
        scoped_id = f"{prefix}:{self._scope_id(scope)}"
        try:
            self.store.get_object(scoped_id, scope)
            return scoped_id
        except (KeyError, ScopeViolation):
            pass
        try:
            self.store.get_object(legacy_id, scope)
            return legacy_id
        except (KeyError, ScopeViolation):
            return scoped_id

    def _book_object_id(self, scope: Scope) -> str:
        return self._scoped_system_object_id(scope, "ledger", scope.ledger_id)

    def _period_object_id(self, scope: Scope) -> str:
        return self._scoped_system_object_id(scope, "period", scope.accounting_period_id)

    def _baseline_object_id(self, scope: Scope) -> str:
        return self._scoped_system_object_id(scope, "baseline", scope.baseline_id)

    def _find_by_data(self, object_type: str, scope: Scope, field: str, value: Any) -> dict[str, Any] | None:
        for item in self.store.list_objects(object_type, scope):
            if item["data"].get(field) == value:
                return item
        return None

    def _ensure_period_open(self, scope: Scope) -> None:
        try:
            period = self.store.get_object(self._period_object_id(scope), scope)
        except KeyError:
            return
        if period["status"] in {"CLOSED", "ARCHIVED", "LOCKED"}:
            raise PreconditionFailed("当前期间已关闭或锁账，普通写操作被拒绝")

    def _require_baseline_confirmed(self, scope: Scope) -> None:
        baseline = self.store.get_object(self._baseline_object_id(scope), scope)
        if baseline["status"] != "CONFIRMED" or baseline["data"].get("validation_version") != VALIDATION_VERSION:
            raise PreconditionFailed("账套基线缺少可核验的上期关闭来源及余额校验，请重新确认")
        if baseline["data"].get("historical_confirmation"):
            prepared = self.historical.confirmation_inputs(scope, baseline["data"]["historical_confirmation"])
            if prepared != baseline["data"].get("confirmed_inputs"):
                raise PreconditionFailed("历史期末结转候选与基线输入不一致")
        inputs, totals = self._checked_baseline_inputs(scope, baseline["data"].get("confirmed_inputs", {}), allow_historical=bool(baseline["data"].get("historical_confirmation")))
        snapshot = baseline["data"].get("prior_close_snapshot") or {}
        if not snapshot or snapshot.get("snapshot_digest") != digest({key: snapshot.get(key) for key in ("period", "source", "lines", "totals")}) or snapshot.get("period") != inputs["prior_period"] or snapshot.get("source") != inputs["close_source"] or snapshot.get("totals") != {"debit": totals["debit"], "credit": totals["credit"]}:
            raise PreconditionFailed("基线内部上期关闭快照缺失或与确认输入不一致，请重新确认")

    def _checked_baseline_inputs(self, scope: Scope, payload: dict[str, Any], *, allow_historical=False):
        try:
            inputs, totals = validate_confirmation(payload, scope.accounting_period_id)
        except (ValidationError, ValueError) as exc:
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            raise PreconditionFailed("基线来源或余额校验失败：" + reason) from exc
        for ref in (inputs["balance_source"], inputs["close_source"]):
            try:
                source = self.store.get_object(ref["artifact_id"], scope)
            except KeyError as exc:
                raise PreconditionFailed("基线来源资料不存在") from exc
            if source["object_type"] != ObjectType.SOURCE_ARTIFACT.value or source["version"] != ref["version"] or source["status"] not in {"ACTIVE", "PERIOD_EXCEPTION"}:
                raise PreconditionFailed("基线来源类型或版本无效，须使用当前有效原件重新核实")
            if source["data"].get("source_purpose") == "historical_reference" and not allow_historical:
                raise PreconditionFailed("历史账表必须通过当前历史核对候选确认，不能绕过科目和辅助明细校验")
            if source["data"].get("observed_period") != inputs["prior_period"]:
                raise PreconditionFailed("基线来源所属期间与上期不一致")
            try:
                root = self.store.database.settings.storage_path.resolve()
                path = (root / source["data"]["storage_path"]).resolve()
                if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source["data"].get("sha256"):
                    raise ValueError("来源内容不可核验")
            except (KeyError, OSError, ValueError) as exc:
                raise PreconditionFailed("基线原件不存在、越界或内容哈希已变化") from exc
        return inputs, totals

    def _demo_baseline_payload(self, scope: Scope, actor_id: str) -> dict[str, Any]:
        # Synthetic fixture only. The production /demo API is denied by authorization.
        if self.store.database.settings.require_auth:
            raise PermissionDenied("合成基线只能用于显式关闭认证的隔离测试环境")
        prior = previous_period(scope.accounting_period_id)
        content = (f"SYNTHETIC ONLY: {scope.legal_entity_id} {scope.ledger_id} {prior} closed; cash debit 1000; capital credit 1000.").encode()
        source = self.create_artifact(ArtifactInput(scope=scope, filename="演示上期关闭及余额.txt",
            content_base64=base64.b64encode(content).decode(), source_channel="DEMO", observed_period=prior, mime_type="text/plain"), actor_id=actor_id)
        ref = {"artifact_id": source["object_id"], "version": source["version"], "anchor": {"row": 1}}
        balances = [{"account_code": code, "account_name": name, "closing_debit": debit, "opening_debit": debit,
                     "closing_credit": credit, "opening_credit": credit, "requires_auxiliary": False, "auxiliary": [], "source_anchor": {"row": 1}}
                    for code, name, debit, credit in (("1001", "库存现金", "1000.00", "0.00"), ("4001", "实收资本", "0.00", "1000.00"))]
        return {"prior_period": prior, "close_reference": "SYNTHETIC-CLOSE", "currency": "CNY", "completeness_confirmed": True,
                "balance_source": ref, "close_source": ref, "balances": balances}

    def _set_current_run(self, scope: Scope, run_id: str, actor_id: str) -> None:
        scope_obj = self.store.get_object(self._scope_id(scope), scope)
        data = deepcopy(scope_obj["data"])
        data["current_run_id"] = run_id
        self.store.revise_object(scope_obj["object_id"], scope_obj["version"], scope, data, status=scope_obj["status"], created_by=actor_id)
        period = self.store.get_object(self._period_object_id(scope), scope)
        p_data = deepcopy(period["data"])
        p_data["current_run_id"] = run_id
        self.store.revise_object(period["object_id"], period["version"], scope, p_data, status=period["status"], created_by=actor_id)

    def _voucher_for_group(self, scope: Scope, group_id: str) -> dict[str, Any] | None:
        vouchers = [item for item in self.store.list_objects(ObjectType.VOUCHER_VERSION.value, scope) if item["data"].get("group_id") == group_id]
        return vouchers[-1] if vouchers else None

    def _group_imported(self, scope: Scope, group_id: str) -> bool:
        group = self.store.get_object(group_id, scope)
        try:
            self._require_current_reconciliation(scope, group)
        except DomainError:
            return False
        packages = [item for item in self.store.list_objects(ObjectType.DELIVERY_PACKAGE.value, scope) if item["data"].get("group_id") == group_id]
        for package in packages:
            if package["status"] != "EXTERNAL_IMPORTED":
                continue
            try:
                export = self.store.get_object(package["data"]["export_id"], scope)
                self._validate_export_binding(package, export)
                voucher = self.store.get_object(package["data"]["voucher_version_id"], scope, package["data"]["voucher_version"])
                self._require_voucher_sources(group, voucher)
                receipt = self.store.get_object(package["data"]["external_receipt_id"], scope)
                expected = {"export_id": export["object_id"], "voucher_version_id": package["data"]["voucher_version_id"], "voucher_version": package["data"]["voucher_version"]}
                if receipt["status"] == "IMPORTED" and all(receipt["data"]["payload"].get(k) == v for k, v in expected.items()):
                    return True
            except (KeyError, DomainError):
                continue
        return False

    def _validate_export_binding(self, package: dict[str, Any], export: dict[str, Any]) -> None:
        if not package["data"].get("voucher_version") or export["object_type"] != ObjectType.EXPORT.value or export["data"].get("package_id") != package["object_id"] or any(export["data"].get(key) != package["data"].get(key) for key in ("voucher_version_id", "voucher_version")) or not export["data"].get("lines"):
            raise PreconditionFailed("交付包和导出记录的固定版本不完整或不一致，不能继续交付")
