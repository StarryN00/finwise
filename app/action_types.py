"""Versioned, system-owned ActionType declarations and closed predicate evaluator."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.task_descriptors import (
    BANK_PROPERTIES, BILL_PROPERTIES, EffectDescriptor, FieldDescriptor, ReversibilityDescriptor,
)


CATALOG_VERSION = 'action-catalog-v1'
FALLBACK_IDS = (
    'record_judgement', 'suspend', 'request_supplement', 'mark_out_of_scope', 'escalate'
)


class Predicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    op: Literal['ALWAYS', 'EQ', 'IN', 'CONTAINS', 'TRUTHY', 'ALL', 'ANY', 'NOT']
    field: str = ''
    value: Any = None
    children: list['Predicate'] = Field(default_factory=list)


class ActionType(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    version: Literal['action-type-v1'] = 'action-type-v1'
    label: str
    description: str
    scope_kind: Literal['RECORD', 'ARTIFACT', 'GROUP', 'PERIOD']
    stage: Literal['SOURCE_REVIEW', 'BUSINESS_REVIEW', 'SYSTEM_REVIEW']
    applicability: Predicate
    required_evidence: list[str]
    fields: list[FieldDescriptor]
    decision_inputs: list[str]
    effects: list[EffectDescriptor]
    not_effects: list[str]
    permissions: list[Literal['operator', 'accountant', 'reviewer', 'admin']]
    reversibility: ReversibilityDescriptor
    fallback: bool = False
    batch_grouping_keys: list[str] = Field(default_factory=list)


def effect(kind: str, target: str, description: str) -> EffectDescriptor:
    return EffectDescriptor(kind=kind, target=target, description=description,
                            grants_accounting_usable=False)


def text(name: str, label: str, *, placeholder: str, required: bool = True) -> FieldDescriptor:
    return FieldDescriptor(name=name, label=label, component='textarea', required=required,
                           placeholder=placeholder, max_length=2000)


ALL_ROLES = ['operator', 'accountant', 'admin']
SAFE_UNKNOWN = Predicate(op='TRUTHY', field='fallback_eligible')
AVAILABLE = lambda action_id: Predicate(op='CONTAINS', field='available_action_ids', value=action_id)


def _action(action_id: str, label: str, description: str, stage: str,
            required_evidence: list[str], effects: list[EffectDescriptor], *,
            fields: list[FieldDescriptor] | None = None, permissions: list[str] | None = None,
            fallback: bool = False, revocable: bool = False,
            applicability: Predicate | None = None, decision_inputs: list[str] | None = None,
            scope_kind: str = 'RECORD') -> ActionType:
    resolved_inputs = decision_inputs if decision_inputs is not None else [field.name for field in fields or []]
    return ActionType(
        id=action_id, label=label, description=description, stage=stage,
        scope_kind=scope_kind,
        applicability=applicability or (SAFE_UNKNOWN if fallback else AVAILABLE(action_id)),
        required_evidence=required_evidence, fields=fields or [],
        decision_inputs=resolved_inputs, effects=effects,
        not_effects=['不修改原始文件、事实金额、正式凭证或期间状态', '不自动授予账务可用'],
        permissions=permissions or ALL_ROLES,
        reversibility=ReversibilityDescriptor(
            revocable=revocable, entry='revoke_task_action' if revocable else None
        ), fallback=fallback, batch_grouping_keys=decision_inputs or [],
    )


ACTION_TYPES = (
    _action('parse', '识别当前资料', '沿用现有原件解析入口。', 'SYSTEM_REVIEW', ['当前原件及版本'],
            [effect('START_EXISTING_FLOW', 'SourceArtifact', '进入现有识别流程')], scope_kind='ARTIFACT'),
    _action('supplement', '补充资料', '沿用现有只追加上传入口。', 'SOURCE_REVIEW', ['当前问题'],
            [effect('NAVIGATE', 'SourceArtifact', '打开补充资料入口')]),
    _action('verify_source_values', '确认原件与提取值一致', '核对当前事项中已查看的来源记录。', 'SOURCE_REVIEW',
            ['原件有效', '来源定位完整', '提取重放一致'],
            [effect('CREATE', 'SourceVerification', '保存资料核实结果')],
            fields=[FieldDescriptor(name='records', label='已核对记录', component='slot', slot='record_selection', required=True),
                    text('note', '核实备注（可选）', placeholder='可填写核实说明', required=False)],
            decision_inputs=['artifact_id']),
    _action('confirm_invoice_amount', '确认发票金额业务原因', '沿用发票金额核对入口。', 'BUSINESS_REVIEW',
            ['发票原件', '金额及正负号'], [effect('CREATE', 'InvoiceAmountConfirmation', '保存金额核对记录')],
            fields=[text('reason', '核对说明', placeholder='说明金额、正负号及对应业务原因')]),
    _action('confirm_bill_business', '确认票据业务与科目', '沿用票据业务确认入口。', 'BUSINESS_REVIEW',
            ['票据原件', '业务归属依据'], [effect('CREATE', 'BillBusinessConfirmation', '保存票据业务确认')],
            fields=[FieldDescriptor(name='business', label='确认票据业务与科目', component='slot',
                                    slot='bill_business', required=True, properties=BILL_PROPERTIES)],
            decision_inputs=['business_kind', 'business_period', 'account_name']),
    _action('confirm_statement_account', '确认流水所属银行', '沿用银行账户归属入口。', 'BUSINESS_REVIEW',
            ['流水原件', '银行身份线索'], [effect('LINK', 'SourceArtifact', '保存银行账户关联')],
            fields=[FieldDescriptor(name='ownership', label='流水银行归属', component='slot',
                                    slot='bank_ownership', required=True, properties=BANK_PROPERTIES)],
            decision_inputs=['account_id'], scope_kind='ARTIFACT'),
    _action('defer_material_issue', '记录暂无法确认原因', '沿用既有暂缓记录入口。', 'BUSINESS_REVIEW',
            ['当前问题'], [effect('CREATE', 'MaterialIssueResponse', '保存暂缓原因')],
            fields=[text('reason', '原因', placeholder='说明当前为什么无法继续处理')]),
    _action('confirm_bank_period', '确认流水期间归属', '沿用银行流水期间确认入口。', 'BUSINESS_REVIEW',
            ['交易日期原值', '当前办理期间'], [effect('CREATE', 'BankPeriodAssignment', '保存流水期间归属')],
            fields=[FieldDescriptor(name='records', label='需确认归属的流水', component='slot',
                                    slot='period_record_selection', required=True),
                    text('reason', '归属说明（可选）', placeholder='可填写期间归属依据', required=False)],
            decision_inputs=['target_period']),
    _action('record_judgement', '记录专业判断', '记录有依据的受控判断，原告警继续保留。', 'BUSINESS_REVIEW',
            ['当前任务绑定', '具体判断依据'], [effect('CREATE', 'Decision', '保存专业判断并保留告警')],
            fields=[text('judgement', '专业判断', placeholder='说明你对该事项的判断'),
                    text('reason', '判断依据', placeholder='说明可核验的业务依据')],
            fallback=True, revocable=True),
    _action('suspend', '暂停办理本事项', '移出当前办理队列，但不解除业务门禁。', 'BUSINESS_REVIEW',
            ['当前任务绑定'], [effect('QUEUE_STATE', 'Decision', '暂停当前事项，保留业务门禁')],
            fields=[text('reason', '暂停原因', placeholder='说明暂停办理的原因')],
            fallback=True, revocable=True),
    _action('request_supplement', '请求补充具体材料', '记录所需材料和待核验事实，等待外部响应。', 'BUSINESS_REVIEW',
            ['当前任务绑定', '明确材料', '待核验事实'], [effect('WAIT_EXTERNAL', 'Decision', '记录补充请求并等待外部')],
            fields=[text('material', '需要的具体材料', placeholder='例如：2026-01 银行回单'),
                    text('fact_to_verify', '待核验的具体事实', placeholder='例如：核验该笔付款对应的实际收款方')],
            fallback=True, revocable=True),
    _action('mark_out_of_scope', '标记本期不处理', '仅排除绑定记录的本期办理和候选分组。', 'BUSINESS_REVIEW',
            ['当前任务绑定', '尚未进入正式下游流程'],
            [effect('EXCLUDE_PERIOD', 'Decision', '排除绑定记录的本期办理和候选分组')],
            fields=[text('reason', '排除原因', placeholder='说明为什么本期不处理这些绑定记录')],
            permissions=['operator', 'accountant', 'admin'], fallback=True, revocable=True),
    _action('escalate', '转交更高权限复核', '按当前操作人角色转交更高权限，并记录理由。', 'BUSINESS_REVIEW',
            ['当前任务绑定', '升级理由'], [effect('ASSIGN', 'Decision', '转交更高权限复核队列')],
            fields=[text('reason', '转交理由', placeholder='说明需要更高权限复核的事项')],
            permissions=['operator', 'accountant'],
            fallback=True, revocable=True),
)
ACTION_TYPE_BY_ID = {item.id: item for item in ACTION_TYPES}


def evaluate_predicate(predicate: Predicate | dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate only the declared AST. Unknown fields/types fail closed."""
    try:
        node = predicate if isinstance(predicate, Predicate) else Predicate.model_validate(predicate)
        if node.op == 'ALWAYS':
            return not node.field and not node.children
        if node.op in {'ALL', 'ANY'}:
            if not node.children:
                return False
            values = [evaluate_predicate(child, context) for child in node.children]
            return all(values) if node.op == 'ALL' else any(values)
        if node.op == 'NOT':
            return len(node.children) == 1 and not evaluate_predicate(node.children[0], context)
        if not node.field or node.field not in context:
            return False
        actual = context[node.field]
        if node.op == 'TRUTHY':
            return bool(actual)
        if node.op == 'EQ':
            return actual == node.value
        if node.op == 'IN':
            return isinstance(node.value, list) and actual in node.value
        if node.op == 'CONTAINS':
            return isinstance(actual, (list, tuple, set, frozenset, str)) and node.value in actual
        return False
    except (TypeError, ValueError, KeyError):
        return False


def decorate_option(action_id: str, descriptions: list[str]) -> dict[str, Any]:
    definition = ACTION_TYPE_BY_ID[action_id]
    effects = [
        effect(item.kind, item.target, descriptions[index] if index < len(descriptions) else item.description)
        for index, item in enumerate(definition.effects)
    ]
    if len(descriptions) > len(effects):
        effects.extend(effect('RECORD', 'Decision', description) for description in descriptions[len(effects):])
    return {
        'action_type_version': definition.version,
        'fallback': definition.fallback,
        'permissions': list(definition.permissions),
        'applicability': definition.applicability.model_dump(),
        'required_evidence': list(definition.required_evidence),
        'reversibility': definition.reversibility.model_dump(),
        'effects': [item.model_dump() for item in effects],
    }


def fallback_option_descriptors() -> list[dict[str, Any]]:
    options = []
    for action_id in FALLBACK_IDS:
        definition = ACTION_TYPE_BY_ID[action_id]
        option = {
            'id': definition.id, 'label': definition.label,
            'confirmation_label': definition.label,
            'success_label': {
                'record_judgement': '专业判断已记录，原告警继续保留',
                'suspend': '本事项已暂停，业务门禁继续保留',
                'request_supplement': '具体补充请求已记录，等待外部响应',
                'mark_out_of_scope': '绑定记录已排除本期办理',
                'escalate': '事项已转交更高权限复核',
            }[action_id],
            'execution_type': 'COMMAND', 'post_submit_owner': {
                'request_supplement': 'EXTERNAL', 'suspend': 'NONE',
                'record_judgement': 'SYSTEM', 'mark_out_of_scope': 'NONE', 'escalate': 'SYSTEM',
            }[action_id],
            'fields': [field.model_dump() for field in definition.fields],
            'requires': list(definition.required_evidence),
            'completion': definition.description,
            'not_effects': ['不修改原始文件、事实金额、正式凭证或期间状态', '不授予账务可用效果'],
            'available': True, 'unavailable_reason': '',
            'steps': [{'id': 'decision', 'prompt': definition.description,
                       'fields': [field.name for field in definition.fields]}],
        }
        option.update(decorate_option(action_id, []))
        options.append(option)
    return options


def validate_batch_grouping(action_id: str, grouping_keys: list[str]) -> bool:
    definition = ACTION_TYPE_BY_ID.get(action_id)
    return bool(definition and not definition.fallback and definition.decision_inputs
                and set(definition.decision_inputs).issubset(set(grouping_keys)))


def catalog_contract() -> dict[str, Any]:
    return {
        'version': CATALOG_VERSION,
        'schema': ActionType.model_json_schema(),
        'items': [item.model_dump() for item in ACTION_TYPES],
    }
