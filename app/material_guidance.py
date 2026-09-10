"""Optional, candidate-only material guidance. Never dispatches financial commands."""
from __future__ import annotations

import math
import re
import time
from copy import deepcopy
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from app.db import utcnow
from app.ontology.contracts import Scope
from app.ontology.errors import DomainError, PermissionDenied, PreconditionFailed, VersionConflict
from app.ontology.gateway import GatewayFailure
from app.ontology.store import digest
from app.ontology.readiness import FIELDS

STAGE = 'MATERIAL_GUIDANCE'
SCHEMA = 'material-guidance-v2'
PROMPT = 'material-guidance-prompt-v2'
JOB_TYPE = 'MaterialGuidanceJob'
BOUNDARY = '仅保存处理意见和候选建议，尚未执行；不修改财务数据，不解除任何门禁。'


def clock_seconds():
    return time.time()


class GuidanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: Scope
    stage: Literal['MATERIAL_GUIDANCE']
    task_id: StrictStr = Field(min_length=1, max_length=256)
    descriptor_hash: StrictStr = Field(pattern=r'^[a-f0-9]{64}$')
    request_id: StrictStr = Field(min_length=8, max_length=128)
    user_text: StrictStr = Field(default='', max_length=2000)

    @model_validator(mode='before')
    @classmethod
    def text_alias(cls, data):
        if isinstance(data, dict) and 'custom_text' in data:
            if 'user_text' in data:
                raise ValueError('provide only one opinion field')
            data = dict(data)
            data['user_text'] = data.pop('custom_text')
        return data


class GuidanceOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    option_id: Optional[StrictStr]
    reason: StrictStr = Field(min_length=1, max_length=1500)
    uncertainties: list[StrictStr] = Field(max_length=12)
    prefill: dict[str, Any]
    confidence: float = Field(ge=0, le=1)


class GuidanceStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    option_id: StrictStr
    instruction: StrictStr = Field(min_length=1, max_length=240)


class GuidanceCandidate(GuidanceOutput):
    evidence_refs: list[StrictStr] = Field(min_length=1, max_length=12)
    steps: list[GuidanceStep] = Field(default_factory=list, max_length=5)


class GuidanceOutputV2(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidates: list[GuidanceCandidate] = Field(min_length=1, max_length=3)


def redact_user_text(text):
    """Never send arbitrary residual prose. Only exact local intent phrases leave.

    Unknown prose, including names/IDs/instructions disguised as business terms,
    stays local. This is intentionally not a general-purpose PII detector.
    """
    if not text.strip():
        return {'status': 'EMPTY', 'intents': []}
    phrases = {'已核对原件': 'SOURCE_VIEWED', '这是红冲': 'RED_INVOICE_OPINION',
               '这是退货': 'RETURN_OPINION', '这是折让': 'DISCOUNT_OPINION',
               '日期不详': 'DATE_UNKNOWN', '期间待确认': 'PERIOD_UNKNOWN',
               '账户待确认': 'ACCOUNT_UNKNOWN', '业务归属待确认': 'BUSINESS_UNKNOWN',
               '按原日期归属下月': 'FOLLOW_SOURCE_TRANSACTION_PERIOD',
               '按原日期归属': 'FOLLOW_SOURCE_TRANSACTION_PERIOD',
               '按原件日期归属': 'FOLLOW_SOURCE_TRANSACTION_PERIOD',
               '按原交易日期归属': 'FOLLOW_SOURCE_TRANSACTION_PERIOD',
               '暂无法确认': 'UNCONFIRMED', '请先查看原件': 'SOURCE_REVIEW_REQUESTED'}
    parts = [p.strip() for p in re.split(r'[，,。；;\n]+', text.strip()) if p.strip()]
    intents = set()
    for part in parts:
        if part in phrases:
            intents.add(phrases[part])
        elif re.fullmatch(r'(?:请)?把这(?:两|二|三|几|[1-9])?笔(?:记录)?(?:放到|归属到|归到)(?:[1-9]|1[0-2]|一|二|三|四|五|六|七|八|九|十|十一|十二)月', part):
            intents.add('REQUEST_TARGET_PERIOD_REVIEW')
        else:
            return {'status': 'LOCAL_ONLY', 'intents': []}
    return {'status': 'SANITIZED', 'intents': sorted(intents)} if intents else {'status': 'LOCAL_ONLY', 'intents': []}


def model_binding(service):
    settings = service.store.database.settings
    return {'schema': SCHEMA, 'prompt': PROMPT, 'model': service.gateway.configured_model,
            'provider': settings.agent_provider, 'mode': settings.agent_mode,
            'endpoint_hash': digest(settings.deepseek_base_url), 'max_tokens': settings.agent_max_tokens,
            'timeout_seconds': settings.gateway_timeout_seconds, 'max_retries': settings.gateway_max_retries}


def task_fingerprint(service, scope, task):
    review = task.get('problem_review') or {}
    return digest([scope.model_dump(), task['id'], task['descriptor']['fingerprint'],
                   task.get('triage'), {k: review.get(k) for k in ('object_id', 'version', 'status', 'valid')},
                   model_binding(service)])


def validate_candidates(value, task, packet):
    """Adapt v1 without fabricating model citations or executable prefills."""
    available = {o['id'] for o in packet['options']}
    refs = {r['reference'] for r in packet['records']} | {'task'}
    legacy = 'candidates' not in value
    outputs = [GuidanceOutput.model_validate(value)] if legacy else GuidanceOutputV2.model_validate(value).candidates
    candidates = []
    seen = set()
    for output in outputs:
        if output.option_id is not None and output.option_id not in available:
            raise ValueError('undeclared option')
        if output.option_id in seen:
            raise ValueError('duplicate option')
        seen.add(output.option_id)
        if output.prefill or not math.isfinite(output.confidence) or any(len(s) > 500 or not s.strip() for s in output.uncertainties):
            raise ValueError('invalid candidate')
        item = output.model_dump()
        if not legacy:
            if not set(output.evidence_refs) <= refs or len(set(output.evidence_refs)) != len(output.evidence_refs):
                raise ValueError('invalid evidence refs')
            if any(not s.instruction.strip() or s.option_id not in available for s in output.steps):
                raise ValueError('invalid step option')
            if output.option_id is None:
                if output.steps:
                    raise ValueError('null option cannot carry actionable steps')
            elif output.steps and output.steps[0].option_id != output.option_id:
                raise ValueError('first step must match candidate option')
        else:
            item.update(evidence_refs=[], steps=[], legacy=True)
        if output.confidence < .7:
            item['option_id'] = None
            item['steps'] = []
        candidates.append(item)
    return candidates


# Only categorical source information crosses the Gateway. No filenames, names,
# account identifiers, original cells, notes, invoice numbers or exact amounts.
SAFE_FIELDS = {'period', 'business_period', 'invoice_date', 'transaction_date', 'tax_rate',
               'invoice_total', 'amount', 'tax_amount', 'bank_account_ref', 'account_balance',
               'ticket_no', 'ticket_status', 'issue_date', 'due_date', 'actual_salary',
               'person_name', 'buyer_name', 'seller_name', 'account_number'}
SAFE_FIELDS |= set(FIELDS)
ISSUE_FIELDS = {label: field for field, label in FIELDS.items()}
SAFE_TYPES = {'INVOICE', 'SALES_INVOICE', 'PAYMENT', 'BANK_STATEMENT', 'PAYROLL',
              'SOCIAL_INSURANCE', 'SOCIAL_SECURITY', 'BANK_TRANSACTION', 'RECEIPT',
              'ELECTRONIC_ACCEPTANCE', 'BILL', 'HOUSING_FUND'}

# Descriptor labels/effects can contain dynamic dates or names. Only these
# server-owned, fixed meanings leave the process, never descriptor prose.
OPTION_MEANINGS = {
    'supplement': '提供已有补充依据，上传后仍须校验',
    'parse': '请求识别原件，不代表识别成功',
    'verify_source_values': '人工核实已查看的原件字段',
    'confirm_invoice_amount': '人工说明并核对发票金额业务原因',
    'confirm_bill_business': '人工确认票据业务和拟用科目',
    'confirm_statement_account': '人工确认流水账户归属',
    'defer_material_issue': '记录暂缓原因，保留阻断',
    'confirm_bank_period': '依据已核验原件日期，由用户确认流水期间归属；不改原日期',
}


def safe_packet(task, records):
    descriptor = task['descriptor']
    source = []
    for index, record in enumerate(records[:100]):
        values = record.get('values') or {}
        focuses = next((set(r['focus_fields']) for r in (descriptor.get('presentation') or {}).get('records', [])
                        if r['id'] == record['object_id']), set())
        source.append({'reference': f'record-{index+1}',
                       'record_type': record.get('record_type') if record.get('record_type') in SAFE_TYPES else 'OTHER',
                       'missing_fields': sorted(k for k in SAFE_FIELDS if k in values and values[k] in (None, '')),
                       'issue_fields': sorted({ISSUE_FIELDS.get(i.split('：', 1)[0], i.split('：', 1)[0]) for i in record.get('issues', [])} & SAFE_FIELDS),
                       'field_checks': [{'field': c['field'], 'state': c['state']}
                                        for c in record.get('comparison', [])
                                        if c.get('field') in SAFE_FIELDS and (not focuses or c['field'] in focuses) and c.get('state') in {
                                            'DIRECT_MATCH','NORMALIZED_MATCH','DERIVED','MISSING','DIFFERENT','AMBIGUOUS','UNLOCATED'}][:50],
                       'has_period_exception': record.get('state') == 'PERIOD_EXCEPTION'})
    options = [{'id': o['id'], 'label': OPTION_MEANINGS[o['id']], 'not_effects': [BOUNDARY]}
               for o in descriptor['options'] if o['available'] and o['id'] in OPTION_MEANINGS]
    if (task.get('triage') or {}).get('route') == 'SYSTEM':
        options = []
    return {'task_kind': task['kind'] if task['kind'] in {'VERIFY','ISSUE','PARSE','BILL','BILL_ACCOUNT','INVOICE_AMOUNT'} else 'UNKNOWN',
            'records': source, 'options': options, 'evidence_refs': ['task', *[r['reference'] for r in source]],
            'records_truncated': len(records) > 100,
            'context_limit': '只有脱敏字段检查和可能的用户意见枚举，不是已核验业务事实；不能据此确定日期、账户或科目，金额抵消也不等于财务通过。',
            'output_schema': {'candidates': [{'option_id': 'available option id or null', 'reason': 'string',
                              'uncertainties': ['string'], 'prefill': {}, 'confidence': '0..1',
                              'evidence_refs': ['task or record-N from input'],
                              'steps': [{'option_id': 'available option id', 'instruction': 'bounded instruction; separate human confirmation required'}]}],
                              'candidate_count': '1..3'}}


def current_task(service, request):
    overview = service.workbench(request.scope)
    task = next((t for t in overview['material_review']['tasks'] if t['id'] == request.task_id), None)
    if not task or task['descriptor']['fingerprint'] != request.descriptor_hash:
        raise VersionConflict('事项或依据已变化，请刷新后重新分析')
    artifact = next((a for a in overview['artifacts'] if a['object_id'] == task['artifact_id']), None)
    if not artifact or artifact['status'] != 'ACTIVE' or not service.materials.source_valid(artifact):
        raise VersionConflict('原件已失效或文件哈希异常，不能继续分析')
    return task, overview


def guidance(service, request: GuidanceRequest, actor_id: str, role: str):
    if role not in {'operator', 'accountant', 'admin'}:
        raise PermissionDenied('当前角色不能发起资料办理建议')
    service._ensure_period_open(request.scope)
    task, overview = current_task(service, request)
    if task.get('deferred'):
        raise PreconditionFailed('本项已暂缓；先查看已记录原因，不重复调用模型')
    records = {r['object_id']: r for r in overview['material_review']['records']}
    packet = safe_packet(task, [records[r] for r in task['record_ids']])
    redacted = redact_user_text(request.user_text)
    packet['user_opinion'] = {'status': redacted['status'], 'intents': redacted['intents'],
                              'verified': False, 'executed': False}
    config = model_binding(service)
    fingerprint = task_fingerprint(service, request.scope, task)
    run_id = 'modelrun_guidance_' + digest([request.scope.model_dump(), actor_id, request.request_id])
    store = service.store
    # Atomic reservation makes retrying one HTTP request idempotent. No database
    # transaction is held across the external call.
    with store.database.transaction():
        prior = next((r for r in store.list_objects('ModelRun', request.scope) if r['object_id'] == run_id), None)
        if prior:
            if (prior['data'].get('descriptor_hash') != request.descriptor_hash or
                    prior['data'].get('task_id') != request.task_id or
                    prior['data'].get('opinion_hash', digest('')) != digest(request.user_text) or
                    prior['data'].get('fingerprint', fingerprint) != fingerprint or
                    prior['data'].get('model_binding', config) != config):
                raise VersionConflict('请求编号已用于其他事项版本')
            if prior['status'] == 'RUNNING' and clock_seconds() >= prior['data'].get('expires_at', 0):
                expired = dict(prior['data'])
                expired['gateway'] = dict(expired['gateway'], error_code='GUIDANCE_EXPIRED')
                expired['response'] = {'status':'FAILED', 'descriptor_hash':request.descriptor_hash,
                                       'suggestion':None, 'metadata':expired['gateway'],
                                       'message':'上次分析已超时或中断，未采用任何建议；可以重新分析或继续人工处理。'}
                expired['completed_at'] = utcnow()
                prior = store.revise_object(run_id, prior['version'], request.scope, expired,
                                            status='FAILED', created_by=actor_id)
                store.add_audit('MATERIAL_GUIDANCE_EXPIRED', actor_id, request.scope, object_id=run_id,
                                after={'status':'FAILED','error_code':'GUIDANCE_EXPIRED'})
            return prior['data']['response']
        metadata = {'schema_version': SCHEMA, 'prompt_version': PROMPT, 'mock': None,
                    'provider': service.store.database.settings.agent_provider,
                    'model_version': service.gateway.configured_model, 'input_hash': digest(packet)}
        response = {'status': 'RUNNING', 'descriptor_hash': request.descriptor_hash,
                    'suggestion': None, 'metadata': metadata, 'message': '建议生成中；尚未执行任何处理。'}
        data = {'stage': STAGE, 'task_id': task['id'], 'descriptor_hash': request.descriptor_hash,
                'binding': task['descriptor']['scope'], 'input_summary': packet,
                'requested_by': actor_id, 'gateway': metadata, 'response': response,
                'model_binding': config, 'fingerprint': fingerprint, 'opinion_hash': digest(request.user_text),
                'opinion_status': 'SAVED_NOT_EXECUTED' if request.user_text else 'NONE'}
        if request.user_text:
            opinion_id = 'guidance-opinion-' + digest([request.scope.model_dump(), actor_id, request.request_id])
            try:
                opinion = store.get_object(opinion_id, request.scope)
                if opinion['data'].get('request_hash') != digest(request.model_dump()):
                    raise VersionConflict('请求编号已用于另一条处理意见')
            except KeyError:
                store.create_initial_object('MaterialGuidanceOpinion', request.scope,
                    {'actor_id': actor_id, 'task_id': task['id'], 'descriptor_hash': request.descriptor_hash,
                     'text': request.user_text, 'request_hash': digest(request.model_dump()),
                     'binding': deepcopy(task['descriptor']['scope']), 'boundary': BOUNDARY}, status='SAVED_NOT_EXECUTED',
                    created_by=actor_id, object_id=opinion_id)
            data['opinion_id'] = opinion_id
        settings = store.database.settings
        data['expires_at'] = clock_seconds() + settings.gateway_timeout_seconds * (settings.gateway_max_retries + 1) + 30
        local_only = redacted['status'] == 'LOCAL_ONLY' or not packet['options']
        if local_only:
            response = {'status': 'LOCAL_ONLY', 'descriptor_hash': request.descriptor_hash,
                        'suggestion': None, 'candidates': [], 'metadata': metadata,
                        'opinion_status': data['opinion_status'], 'message': '意见已保存在本地，尚未执行。无法可靠脱敏，本次未调用模型；请继续人工核对。' if packet['options'] else
                        '当前需要系统检查，暂无可执行的人工办理选项；未调用模型，不要求客户补资料，所有阻断继续保留。'}
            data.update(response=response, completed_at=utcnow())
        run = store.create_initial_object('ModelRun', request.scope, data, status='LOCAL_ONLY' if local_only else 'RUNNING', created_by=actor_id, object_id=run_id)
        store.add_audit('MATERIAL_GUIDANCE_REQUESTED', actor_id, request.scope, object_id=run_id,
                        after={'descriptor_hash': request.descriptor_hash, 'input_hash': digest(packet)})
    if local_only:
        return response
    try:
        result = service.gateway.complete(request.scope, stage=STAGE, sanitized_input=packet)
        metadata = result.metadata()
        candidates = validate_candidates(result.output, task, packet)
        current, _ = current_task(service, request)
        service._ensure_period_open(request.scope)
        if task_fingerprint(service, request.scope, current) != fingerprint:
            raise VersionConflict('model configuration changed')
        suggestion = {key: candidates[0][key] for key in GuidanceOutput.model_fields}
        status = 'PROPOSED' if any(c['option_id'] is not None for c in candidates) else 'NEEDS_HUMAN'
        response = {'status': status, 'descriptor_hash': request.descriptor_hash,
                    'suggestion': suggestion, 'candidates': candidates, 'metadata': metadata,
                    'opinion_status': data['opinion_status'], 'boundary': BOUNDARY,
                    'evidence': [{'reference': f'record-{i+1}', 'record': deepcopy(r)}
                                 for i, r in enumerate(task['descriptor']['scope']['records'][:100])],
                    'message': '仅为候选建议；请核对后选择处理方式，提交前仍需确认。'}
        run_status = 'SUCCEEDED'
    except Exception as exc:
        # Provider error bodies may contain sensitive strings: keep a bounded code,
        # never echo transport responses or a malformed model completion.
        metadata = dict(metadata, error_code=exc.code if isinstance(exc, GatewayFailure) else 'GUIDANCE_REJECTED')
        response = {'status': 'FAILED', 'descriptor_hash': request.descriptor_hash, 'suggestion': None,
                    'metadata': metadata, 'message': '本次未得到有效建议，资料未改动。可继续按规则办理，或记录原因交由人工判断。'}
        run_status = 'FAILED'
    with store.database.transaction():
        latest = store.get_object(run_id, request.scope)
        if latest['version'] != run['version'] or latest['status'] != 'RUNNING':
            return latest['data']['response']  # A late result cannot overwrite expiry.
        if run_status == 'SUCCEEDED':
            try:
                current, _ = current_task(service, request)
                service._ensure_period_open(request.scope)
                if task_fingerprint(service, request.scope, current) != fingerprint:
                    raise VersionConflict('model configuration changed')
                if clock_seconds() >= data['expires_at']:
                    raise VersionConflict('guidance lease expired')
            except DomainError:
                run_status = 'FAILED'
                metadata = dict(metadata, error_code='GUIDANCE_STALE')
                response = {'status':'FAILED', 'descriptor_hash':request.descriptor_hash,
                            'suggestion':None, 'metadata':metadata,
                            'message':'事项或期间已变化，请重新核对；本次建议未采用。'}
        data.update(gateway=metadata, response=response, completed_at=utcnow())
        store.revise_object(run_id, run['version'], request.scope, data, status=run_status, created_by=actor_id)
        store.add_audit('MATERIAL_GUIDANCE_FINISHED', actor_id, request.scope, object_id=run_id,
                        after={'status': run_status, 'gateway': metadata, 'descriptor_hash': request.descriptor_hash})
    return response


class MaterialGuidance:
    """Durable candidate-only jobs, polled by the owner's existing worker.

    No threads, startup hooks or writes from project(). Integration must signal
    after authorized scope changes; merely opening a workbench never enqueues.
    """
    def __init__(self, service):
        self.service, self.store = service, service.store

    @staticmethod
    def _authorize(role):
        if role not in {'operator', 'accountant', 'admin'}:
            raise PermissionDenied('当前角色不能保存或重试资料办理建议')

    def execute(self, request, actor_id, role):
        """Compatibility entry: generate advice only, never execute its options."""
        return guidance(self.service, request, actor_id, role)

    def save_opinion(self, request, actor_id, role):
        """Save only. Saving an opinion is not consent to enqueue or call a model."""
        self._authorize(role)
        if not request.user_text.strip():
            raise PreconditionFailed('请填写处理意见')
        with self.store.database.transaction():
            task, _ = current_task(self.service, request)
            self.service._ensure_period_open(request.scope)
            receipt_id = 'guidance-opinion-' + digest([request.scope.model_dump(), actor_id, request.request_id])
            request_hash = digest(request.model_dump())
            try:
                receipt = self.store.get_object(receipt_id, request.scope)
            except KeyError:
                receipt = None
            if receipt:
                if receipt['data']['request_hash'] != request_hash:
                    raise VersionConflict('请求编号已用于另一条处理意见')
            else:
                receipt = self.store.create_initial_object('MaterialGuidanceOpinion', request.scope,
                    {'request_hash': request_hash, 'actor_id': actor_id, 'task_id': request.task_id,
                     'descriptor_hash': request.descriptor_hash, 'binding': deepcopy(task['descriptor']['scope']),
                     'text': request.user_text, 'boundary': BOUNDARY},
                    status='SAVED_NOT_EXECUTED', created_by=actor_id, object_id=receipt_id)
                self.store.add_audit('MATERIAL_GUIDANCE_OPINION_SAVED', actor_id, request.scope,
                                    object_id=receipt_id, after={'status': 'SAVED_NOT_EXECUTED'}, reason=BOUNDARY)
            return {'object': receipt, 'status': 'SAVED_NOT_EXECUTED', 'message': BOUNDARY}

    def retry(self, scope, job_id, actor_id, role):
        self._authorize(role)
        with self.store.database.transaction():
            self.service._ensure_period_open(scope)
            job = self.store.get_object(job_id, scope)
            if job['object_type'] != JOB_TYPE or job['status'] != 'FAILED':
                raise PreconditionFailed('只能重试失败的建议任务')
            if job['data'].get('audience') == 'PERSONAL' and job['data']['requested_by'] != actor_id and role != 'admin':
                raise PermissionDenied('不能重试他人的意见建议')
            request = GuidanceRequest(scope=scope, stage=STAGE, task_id=job['data']['task_id'],
                descriptor_hash=job['data']['descriptor_hash'], request_id=job_id)
            task, _ = current_task(self.service, request)
            if task.get('deferred') or task_fingerprint(self.service, scope, task) != job['data']['fingerprint']:
                raise VersionConflict('事项或模型配置已变化，请生成当前版本建议')
            data = {k: v for k, v in job['data'].items() if k not in {'response', 'expires_at', 'completed_at'}}
            data['attempt'] = data.get('attempt', 0) + 1
            updated = self.store.revise_object(job_id, job['version'], scope, data, status='QUEUED', created_by=actor_id)
            self.store.add_audit('MATERIAL_GUIDANCE_RETRIED', actor_id, scope, object_id=job_id,
                                after={'attempt': data['attempt']}, reason=BOUNDARY)
            return {'job': updated, 'message': '建议已重新排队；尚未执行任何业务处理。'}

    def signal(self, scope, actor_id='system'):
        identity = 'guidance-trigger-' + digest(scope.model_dump())
        with self.store.database.transaction():
            self.service._ensure_period_open(scope)
            data = {'requested_by': actor_id}
            try:
                old = self.store.get_object(identity, scope)
            except KeyError:
                return self.store.create_initial_object('MaterialGuidanceTrigger', scope, data,
                    status='QUEUED', created_by=actor_id, object_id=identity)
            if old['status'] == 'QUEUED' and old['data'] == data:
                return old
            return self.store.revise_object(identity, old['version'], scope, data,
                                            status='QUEUED', created_by=actor_id)

    def _watch_fingerprint(self, scope):
        # Watch only scopes explicitly enqueued/signalled. Guidance's own writes
        # and ModelRun receipts must not cause an automatic feedback loop.
        objects = [o for o in self.store.list_objects(None, scope)
                   if not o['object_type'].startswith('MaterialGuidance') and o['object_type'] != 'ModelRun']
        return digest([model_binding(self.service), [(o['object_id'], o['version'], o['status'],
            self.service.materials.source_valid(o) if o['object_type'] == 'SourceArtifact' else None)
            for o in objects]])

    def enqueue(self, scope, actor_id='system', *, task_id=None, user_text=''):
        if not isinstance(user_text, str) or len(user_text) > 2000 or user_text and not task_id:
            raise PreconditionFailed('处理意见必须绑定单个事项，且不超过2000字')
        jobs = []
        with self.store.database.transaction():
            self.service._ensure_period_open(scope)
            wb = self.service.workbench(scope)
            for task in wb['material_review']['tasks']:
                if task_id is not None and task['id'] != task_id:
                    continue
                if task['kind'] == 'VERIFY' or task.get('deferred'):
                    continue
                if not user_text and (task.get('triage') or {}).get('route') == 'SYSTEM':
                    continue
                if not any(o['available'] for o in task['descriptor']['options']):
                    continue
                artifact = next((a for a in wb['artifacts'] if a['object_id'] == task['artifact_id']), None)
                if not artifact or artifact['status'] != 'ACTIVE' or not self.service.materials.source_valid(artifact):
                    continue
                fingerprint = task_fingerprint(self.service, scope, task)
                audience = 'PERSONAL' if user_text else 'AUTO'
                identity = 'guidance-job-' + digest([fingerprint, user_text, actor_id if user_text else 'AUTO'])
                try:
                    job = self.store.get_object(identity, scope)
                except KeyError:
                    data = {'task_id': task['id'], 'descriptor_hash': task['descriptor']['fingerprint'],
                            'fingerprint': fingerprint, 'binding': deepcopy(task['descriptor']['scope']),
                            'requested_by': actor_id, 'audience': audience, 'attempt': 0, 'boundary': BOUNDARY}
                    if user_text:
                        opinion_id = 'guidance-opinion-' + digest([scope.model_dump(), actor_id, identity])
                        self.store.create_initial_object('MaterialGuidanceOpinion', scope,
                            {'actor_id': actor_id, 'task_id': task['id'], 'descriptor_hash': data['descriptor_hash'],
                             'text': user_text, 'boundary': BOUNDARY}, status='SAVED_NOT_EXECUTED',
                            created_by=actor_id, object_id=opinion_id)
                        data['opinion_id'] = opinion_id
                    job = self.store.create_initial_object(JOB_TYPE, scope, data, status='QUEUED',
                                                          created_by=actor_id, object_id=identity)
                    self.store.add_audit('MATERIAL_GUIDANCE_QUEUED', actor_id, scope, object_id=identity,
                                        after={'task_id': task['id'], 'fingerprint': fingerprint}, reason=BOUNDARY)
                jobs.append(job)
            if task_id is not None and not jobs:
                raise PreconditionFailed('事项不可分析、已暂缓或原件失效')
            if not user_text:
                identity = 'guidance-watch-' + digest(scope.model_dump())
                data = {'fingerprint': self._watch_fingerprint(scope), 'requested_by': actor_id}
                try:
                    watch = self.store.get_object(identity, scope)
                except KeyError:
                    self.store.create_initial_object('MaterialGuidanceWatch', scope, data,
                        status='ACTIVE', created_by=actor_id, object_id=identity)
                else:
                    if watch['data'] != data or watch['status'] != 'ACTIVE':
                        self.store.revise_object(identity, watch['version'], scope, data,
                                                 status='ACTIVE', created_by=actor_id)
        return {'jobs': jobs, 'message': '建议已排队；未执行任何业务处理。'}

    def _finish(self, scope, job, status, response):
        updated = self.store.revise_object(job['object_id'], job['version'], scope,
            {**job['data'], 'response': response, 'completed_at': utcnow()}, status=status, created_by='system')
        self.store.add_audit('MATERIAL_GUIDANCE_JOB_FINISHED', 'system', scope,
                            object_id=job['object_id'], after={'status': status}, reason=BOUNDARY)
        return updated

    def process_one(self):
        """Return whether one trigger/job was handled. No network in transaction."""
        if self.store.database.settings.agent_mode != 'gateway':
            return False
        selected = None
        for owner in self.store.list_scope_objects():
            scope = Scope(**owner['data']['scope'])
            with self.store.database.transaction():
                triggers = self.store.list_objects('MaterialGuidanceTrigger', scope, statuses=['QUEUED'])
                if triggers:
                    trigger = triggers[0]
                    try:
                        self.enqueue(scope, trigger['data']['requested_by'])
                        status = 'DONE'
                    except DomainError:
                        status = 'FAILED'
                    self.store.revise_object(trigger['object_id'], trigger['version'], scope,
                                             trigger['data'], status=status, created_by='system')
                    return True
                watches = self.store.list_objects('MaterialGuidanceWatch', scope, statuses=['ACTIVE'])
                if watches and watches[-1]['data']['fingerprint'] != self._watch_fingerprint(scope):
                    try:
                        self.enqueue(scope, watches[-1]['data']['requested_by'])
                    except DomainError:
                        # Do not spin on a locked period; an explicit future
                        # signal can re-enable this scope's watch.
                        watch = watches[-1]
                        self.store.revise_object(watch['object_id'], watch['version'], scope, watch['data'],
                                                 status='PAUSED', created_by='system')
                    return True
                for job in self.store.list_objects(JOB_TYPE, scope):
                    if job['status'] == 'RUNNING' and clock_seconds() >= job['data']['expires_at']:
                        self._finish(scope, job, 'FAILED', {'status': 'FAILED', 'suggestion': None,
                            'candidates': [], 'message': '建议处理中断或超时，未执行任何处理。'})
                        return True
                    if job['status'] != 'QUEUED':
                        continue
                    opinion = self.store.get_object(job['data']['opinion_id'], scope) if job['data'].get('opinion_id') else None
                    request = GuidanceRequest(scope=scope, stage=STAGE, task_id=job['data']['task_id'],
                        descriptor_hash=job['data']['descriptor_hash'], request_id=job['object_id'] + '-' + str(job['data'].get('attempt', 0)),
                        user_text=opinion['data']['text'] if opinion else '')
                    try:
                        self.service._ensure_period_open(scope)
                        task, _ = current_task(self.service, request)
                        if task.get('deferred') or task_fingerprint(self.service, scope, task) != job['data']['fingerprint']:
                            raise VersionConflict('stale guidance job')
                    except DomainError:
                        self._finish(scope, job, 'STALE', {'status': 'STALE', 'suggestion': None,
                            'candidates': [], 'message': '事项、原件、期间或模型配置已变化；旧建议未采用。'})
                        return True
                    settings = self.store.database.settings
                    data = {**job['data'], 'expires_at': clock_seconds() +
                            settings.gateway_timeout_seconds * (settings.gateway_max_retries + 1) + 30}
                    claimed = self.store.revise_object(job['object_id'], job['version'], scope, data,
                                                       status='RUNNING', created_by='system')
                    selected = (scope, claimed, request)
                    break
            if selected:
                break
        if selected is None:
            return False
        scope, job, request = selected
        try:
            # Internal worker capability only; enqueue is not an HTTP authority
            # boundary. The owner must authorize user-triggered enqueue calls.
            response = guidance(self.service, request, job['data']['requested_by'], 'accountant')
        except Exception:
            response = {'status': 'FAILED', 'suggestion': None, 'candidates': [],
                        'message': '本次建议未完成，未执行任何处理；可继续人工核对。'}
        with self.store.database.transaction():
            latest = self.store.get_object(job['object_id'], scope)
            if latest['version'] != job['version'] or latest['status'] != 'RUNNING':
                return True
            status = 'SUCCEEDED' if response['status'] in {'PROPOSED', 'NEEDS_HUMAN'} else response['status']
            try:
                task, _ = current_task(self.service, request)
                self.service._ensure_period_open(scope)
                if clock_seconds() >= job['data']['expires_at'] or task_fingerprint(self.service, scope, task) != job['data']['fingerprint']:
                    raise VersionConflict('stale guidance callback')
            except DomainError:
                status = 'STALE'
                response = {'status': 'STALE', 'suggestion': None, 'candidates': [],
                            'message': '依据或期间已变化，本次建议未采用。'}
            self._finish(scope, latest, status, response)
        return True

    def project(self, scope, material, actor_id=None):
        """Return a deep-copied material object, without writes/enqueue/model calls."""
        projected = deepcopy(material)
        for task in projected['tasks']:
            task.pop('material_guidance', None)
            task.pop('personal_material_guidance', None)
            task.pop('material_opinions', None)
        all_jobs = self.store.list_objects(JOB_TYPE, scope)
        jobs = [j for j in all_jobs if j['data'].get('audience', 'AUTO') == 'AUTO']
        try:
            self.service._ensure_period_open(scope)
            period_open = True
        except DomainError:
            period_open = False
        for task in projected['tasks']:
            matches = [j for j in jobs if j['data']['task_id'] == task['id']]
            if not matches:
                continue
            fingerprint = task_fingerprint(self.service, scope, task)
            current = [j for j in matches if j['data']['fingerprint'] == fingerprint]
            job = (current or matches)[-1]
            valid = bool(current) and period_open and not task.get('deferred')
            try:
                artifact = self.store.get_object(task['artifact_id'], scope)
                bound = task['descriptor']['scope']['artifact']
                valid = (valid and artifact['status'] == 'ACTIVE' and artifact['version'] == bound['version']
                         and artifact['data'].get('sha256') == bound.get('sha256') and self.service.materials.source_valid(artifact))
            except KeyError:
                valid = False
            response = deepcopy(job['data'].get('response') or {'status': job['status'], 'suggestion': None, 'candidates': []})
            if not valid or job['status'] == 'STALE':
                response = {'status': 'STALE', 'suggestion': None, 'candidates': [], 'message': '依据已变化，旧建议不可采用。'}
            elif job['status'] == 'RUNNING' and clock_seconds() >= job['data']['expires_at']:
                response = {'status': 'FAILED', 'suggestion': None, 'candidates': [], 'message': '建议处理已超时，尚未执行。'}
            task['material_guidance'] = {**response, 'job_id': job['object_id'], 'job_version': job['version'], 'valid': valid,
                                         'descriptor_hash': job['data']['descriptor_hash'], 'boundary': BOUNDARY}
        if actor_id is not None:
            # Never replace the auto card. Actor-owned opinion drafts are a
            # separate channel and are absent from actor-less shared workbenches.
            opinions = [o for o in self.store.list_objects('MaterialGuidanceOpinion', scope) if o['data']['actor_id'] == actor_id]
            for task in projected['tasks']:
                task['material_opinions'] = []
                for opinion in opinions:
                    if opinion['data']['task_id'] != task['id']:
                        continue
                    valid = opinion['data']['descriptor_hash'] == task['descriptor']['fingerprint']
                    try:
                        artifact = self.store.get_object(task['artifact_id'], scope)
                        bound = task['descriptor']['scope']['artifact']
                        valid = (valid and artifact['status'] == 'ACTIVE' and artifact['version'] == bound['version']
                                 and self.service.materials.source_valid(artifact))
                    except KeyError:
                        valid = False
                    task['material_opinions'].append({**deepcopy(opinion), 'valid': valid,
                        'actor_id': actor_id, 'text': opinion['data']['text'], 'boundary': BOUNDARY})
                personal = [j for j in all_jobs if j['data'].get('audience') == 'PERSONAL'
                            and j['data']['requested_by'] == actor_id and j['data']['task_id'] == task['id']]
                if personal:
                    job = personal[-1]
                    valid = period_open and not task.get('deferred') and job['data']['fingerprint'] == task_fingerprint(self.service, scope, task)
                    try:
                        artifact = self.store.get_object(task['artifact_id'], scope)
                        bound = task['descriptor']['scope']['artifact']
                        valid = (valid and artifact['status'] == 'ACTIVE' and artifact['version'] == bound['version']
                                 and artifact['data'].get('sha256') == bound.get('sha256') and self.service.materials.source_valid(artifact))
                    except KeyError:
                        valid = False
                    response = deepcopy(job['data'].get('response') or {'status': job['status'], 'candidates': [], 'suggestion': None})
                    if not valid or job['status'] == 'STALE':
                        response = {'status': 'STALE', 'candidates': [], 'suggestion': None}
                    elif job['status'] == 'RUNNING' and clock_seconds() >= job['data']['expires_at']:
                        response = {'status': 'FAILED', 'candidates': [], 'suggestion': None}
                    task['personal_material_guidance'] = {**response, 'job_id': job['object_id'], 'job_version': job['version'], 'valid': valid,
                        'opinion_status': 'SAVED_NOT_EXECUTED', 'descriptor_hash': job['data']['descriptor_hash'], 'boundary': BOUNDARY}
        return projected
