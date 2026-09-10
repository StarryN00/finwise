from __future__ import annotations

from typing import Any, Optional
import hashlib
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from app.ontology.contracts import ArtifactInput, CommandRequest, DemoRequest, FactInput, QueryRequest, Scope, ScopeQuery
from app.ontology.baseline import BaselineConfirmation, VALIDATION_VERSION
from app.ontology.errors import DomainError
from app.ontology.service import OntologyService
from app.auth import authorize_api, authorized_scopes, identity

router = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize_api)])


def service(request: Request) -> OntologyService:
    return request.app.state.service


def actor(
    request: Request,
    x_actor_id: Optional[str] = Header(default=None),
    x_role: Optional[str] = Header(default=None),
) -> tuple[str, str]:
    principal = identity(request)
    return principal["user_id"], principal["role"]


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": "finwise-ontology",
        "agent": {
            "mode": settings.agent_mode,
            "provider": settings.agent_provider if settings.agent_mode == "gateway" else None,
            "model": settings.agent_model if settings.agent_mode == "gateway" else None,
            "configured": bool(settings.agent_mode == "gateway" and settings.deepseek_api_key),
        },
        "historical_worker": {"alive": bool(request.app.state.service.historical.thread and request.app.state.service.historical.thread.is_alive()), "mode": "local-deterministic"},
    }


@router.get("/ontology/contract")
def ontology_contract() -> dict[str, Any]:
    return {
        "contract_version": "ontology-v1.2",
        "voucher_amount_encoding": "decimal-string-2dp; readers accept legacy numeric amounts",
        "baseline_validation_version": VALIDATION_VERSION,
        "baseline_confirmation_schema": BaselineConfirmation.model_json_schema(),
        "compatibility_policy": "新增字段向后兼容；对象、关系和命令语义变更必须升级版本",
        "object_scope_required": True,
        "objects": ["Scope", "AccountingBook", "AccountingPeriod", "BaselineSnapshot", "SourceArtifact", "FactRecord", "BusinessFact", "BusinessEvent", "ProcessingGroup", "Evidence", "Decision", "RuleInstance", "VoucherVersion", "DeliveryPackage", "ProcessingRun"],
        "relations": ["DERIVED_FROM", "SUPPORTS", "MATCHES", "BELONGS_TO", "APPLIES_TO", "CONFLICTS_WITH", "GENERATES", "VALIDATES"],
        "commands": ["parse_artifact", "confirm_baseline", "create_procurement_group", "approve_rule", "approve_rule_batch", "resolve_rule_conflict", "revoke_rule", "confirm_grouping", "suspend_group", "rerun_group", "generate_draft", "validate_draft", "revise_voucher", "release_delivery", "export_package", "ack_external_import", "close_period", "archive_period", "lock_period", "archive_artifact", "reparse_fact", "reconcile_group", "retry_run", "replay_run", "cancel_run", "complete_run"],
        "read_only_workflows": ["POST /api/v1/baseline/candidate"],
        "agent_can_write": ["AgentSuggestion", "RuleCandidate", "ConfirmationCard", "ModelRun"],
        "agent_cannot_write": ["BusinessFact", "RuleInstance", "VoucherVersion", "DeliveryPackage", "AccountingPeriod"],
        "agent_gateway": {"version": "gateway-v2", "schema_version": "agent-output-v1", "provider_modes": ["disabled", "gateway"], "configured_provider": "deepseek"},
        "parse_plans": {
            "object_type": "ParsePlan", "schema_version": "structure-plan-v1", "executor_version": "plan-executor-v1",
            "supported_kinds": ["bank_statement", "purchase_invoices", "sales_invoices"],
            "agent_stage": "STRUCTURE_PLAN", "agent_route": "POST /api/v1/agent/suggestion",
            "commands": ["inspect_parse_plan", "preview_parse_plan", "apply_parse_plan"],
            "inspect_payload": {"document_kind": "required", "row_start": "optional 1..20000", "page_size": "optional 1..100"},
            "preview_target": "SourceArtifact with proposal/document_kind, or ParsePlan with proposal",
            "apply_payload": ["proposal", "preview_token", "plan_confirmed"],
            "source_binding": "SourceArtifact.data.plan_ref", "requires_human_confirmation": True,
            "boundary": "模型只返回结构锚点；原值、本地检查及应用结果由本地执行器产生",
        },
        "historical_preparation": {
            "version": "historical-ledger-v1", "object_type": "HistoricalPreparation",
            "automatic_trigger": "SourceArtifact.source_purpose=historical_reference",
            "retry_command": {"action": "prepare_historical", "target": "BaselineSnapshot", "payload": "optional artifact_ids: exactly two current scoped historical originals"},
            "confirmation": {"action": "confirm_baseline", "payload": {"historical_preparation": {"object_id": "current candidate id", "version": "current candidate version"}, "final_close_confirmed": True, "completeness_confirmed": True, "carry_forward_confirmed": True}},
            "can_write": ["HistoricalPreparation"], "cannot_auto_write": ["BaselineSnapshot", "FactRecord", "VoucherVersion", "DeliveryPackage"],
        },
        "historical_issue_plans": {
            "version": "historical-issue-plan-v1", "object_type": "HistoricalIssuePlan",
            "save_command": "save_historical_issue_plan", "save_target": "HistoricalPreparation",
            "review_command": "review_historical_issue_plan", "review_target": "HistoricalIssuePlan",
            "routes": ["existing_evidence", "unavailable"],
            "review_requires_another_actor": True,
            "effect": "只记录方案、无法补充原因及复核；不修改原件、金额、科目或解除余额校验门禁",
        },
    }


@router.post("/scopes")
def create_scope(body: Scope, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    return service(request).create_scope(body, actor_id=actor_id)


@router.post("/artifacts")
def receive_artifact(body: ArtifactInput, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    return service(request).create_artifact(body, actor_id=actor_id)


@router.post("/facts")
def create_fact(body: FactInput, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    return service(request).create_fact_from_api(body, actor_id=actor_id)


@router.post("/business/procurement")
def create_procurement(body: dict[str, Any], request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, role = context
    scope = Scope.model_validate(body["scope"])
    business_identity = body.get("business_identity", "")
    return service(request).execute_command(
        scope,
        action="create_procurement_group",
        target_id=business_identity,
        target_version=1,
        idempotency_key=body.get("idempotency_key", f"procurement:{business_identity}"),
        actor_id=actor_id,
        role=role,
        payload={"fact_ids": body.get("fact_ids", []), "business_identity": business_identity},
    )


@router.post("/agent/rule-suggestion")
def agent_rule_suggestion(body: dict[str, Any], request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    scope = Scope.model_validate(body["scope"])
    return service(request).agent_suggest_rule(scope, group_id=body["group_id"], actor_id=actor_id, model_output=body.get("model_output"), model_version=body.get("model_version", "client-supplied-test-model"))


@router.post("/agent/suggestion")
def agent_suggestion(body: dict[str, Any], request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    if body.get('stage') == 'STRUCTURE_PLAN':
        from app.parse_plans import PlanRequest
        from pydantic import ValidationError
        try:
            plan_request = PlanRequest.model_validate(body)
        except ValidationError:
            raise HTTPException(422, '结构识别请求不符合契约；不接受模型输出或原件取值')
        try:
            return service(request).parse_plans.request(plan_request,*context)
        except ValueError:
            raise HTTPException(422, '原件不符合结构识别的本地安全检查，未发送模型')
    if body.get('stage') == 'MATERIAL_GUIDANCE':
        from app.material_guidance import GuidanceRequest, guidance
        from pydantic import ValidationError
        try:
            guidance_request = GuidanceRequest.model_validate(body)
        except ValidationError:
            raise HTTPException(422, '资料建议请求不符合契约；不接受模型输出、提取值或任意字段')
        return guidance(service(request), guidance_request, *context)
    actor_id, _ = context
    scope = Scope.model_validate(body["scope"])
    return service(request).agent_suggest(scope, stage=body.get("stage", "DOCUMENT_UNDERSTANDING"), group_id=body.get("group_id"), actor_id=actor_id, model_output=body.get("model_output"), model_version=body.get("model_version", "client-supplied-test-model"))


@router.post("/commands")
def command(body: CommandRequest, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, role = context
    return service(request).execute_command(body.scope, action=body.action, target_id=body.target_id, target_version=body.target_version, idempotency_key=body.idempotency_key, actor_id=actor_id, role=role, payload=body.payload)


@router.post("/workbench")
def workbench(body: ScopeQuery, request: Request) -> dict[str, Any]:
    return service(request).workbench(body.scope,actor_id=actor(request)[0])


@router.get("/portfolio")
def portfolio(request: Request) -> dict[str, Any]:
    return service(request).portfolio(authorized_scopes(request))


@router.post("/history")
def history(body: ScopeQuery, request: Request) -> dict[str, Any]:
    return service(request).history(body.scope, authorized_scopes(request))


@router.post("/baseline/candidate")
def baseline_candidate(body: dict[str, Any], request: Request) -> dict[str, Any]:
    scope = Scope.model_validate(body["scope"])
    return service(request).baseline_candidate(
        scope,
        balance_artifact_id=body["balance_artifact_id"],
        close_artifact_id=body["close_artifact_id"],
    )


@router.post("/query")
def query(body: QueryRequest, request: Request) -> dict[str, Any]:
    return service(request).query(body.scope, body.question)


@router.post("/demo/procurement")
def procurement_demo(body: DemoRequest, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    return service(request).create_procurement_demo(body.scope, actor_id=actor_id, variant=body.variant)


@router.post("/runs")
def create_run(body: dict[str, Any], request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    return service(request).create_run(Scope.model_validate(body["scope"]), actor_id=actor_id, input_ids=body.get("input_ids", []), model_version=body.get("model_version", "not-used"))


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str, body: ScopeQuery, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, role = context
    return service(request).execute_command(body.scope, action="retry_run", target_id=run_id, target_version=1, idempotency_key=f"retry:{run_id}", actor_id=actor_id, role=role)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, body: ScopeQuery, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, role = context
    return service(request).execute_command(body.scope, action="cancel_run", target_id=run_id, target_version=1, idempotency_key=f"cancel:{run_id}", actor_id=actor_id, role=role)


@router.post("/runs/{run_id}/complete")
def complete_run(run_id: str, body: dict[str, Any], request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, role = context
    scope = Scope.model_validate(body["scope"])
    return service(request).execute_command(scope, action="complete_run", target_id=run_id, target_version=1, idempotency_key=body.get("idempotency_key", f"complete:{run_id}"), actor_id=actor_id, role=role, payload={"result": body.get("result", {})})


@router.post("/runs/{run_id}/replay")
def replay_run(run_id: str, body: ScopeQuery, request: Request, context: tuple[str, str] = Depends(actor)) -> dict[str, Any]:
    actor_id, _ = context
    return service(request).replay_run(body.scope, run_id=run_id, actor_id=actor_id)


@router.post("/objects/detail")
def object_detail(body: dict[str, Any], request: Request) -> dict[str, Any]:
    return service(request).object_detail(body["object_id"], Scope.model_validate(body["scope"]), body.get("version"))


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: str,
    request: Request,
    tenant_id: str = Query(...),
    organization_id: str = Query(...),
    legal_entity_id: str = Query(...),
    ledger_id: str = Query(...),
    accounting_period_id: str = Query(...),
    baseline_id: str = Query(...),
) -> Response:
    scope = Scope(tenant_id=tenant_id, organization_id=organization_id, legal_entity_id=legal_entity_id, ledger_id=ledger_id, accounting_period_id=accounting_period_id, baseline_id=baseline_id)
    artifact = service(request).store.get_object(artifact_id, scope)
    if artifact["object_type"] != "SourceArtifact":
        raise DomainError("该对象不是原始资料", "NOT_AN_ARTIFACT", 404)
    root = request.app.state.settings.storage_path.resolve()
    relative = artifact["data"]["storage_path"]
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise DomainError("资料存储路径无效", "INVALID_ARTIFACT_PATH", 409)
    if not path.is_file():
        raise DomainError("原始文件存储缺失，不能伪造下载内容", "ARTIFACT_STORAGE_MISSING", 500)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != artifact["data"].get("sha256"):
        raise DomainError("资料哈希校验失败", "ARTIFACT_INTEGRITY_ERROR", 409)
    return Response(content=content, media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(artifact["data"]["filename"], safe=""), "X-Content-Type-Options": "nosniff"})
