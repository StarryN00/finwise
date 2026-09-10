"""Read-only, declaration-driven routing for material tasks.

The ordered rule catalog preserves the legacy routes while keeping safety gates
ahead of every business or fallback action. Routing never writes business data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.action_types import ACTION_TYPES, FALLBACK_IDS, Predicate, evaluate_predicate


VERSION = 'issue-triage-v1'
RULESET_VERSION = 'issue-triage-rules-v2'
STATUS_ISSUE = '发票状态：发票状态须人工核对'
BUSINESS_CODES = {
    'AMOUNT_CANCELLATION_MISMATCH': '请核对关联红票是否齐全，是否存在部分红冲或尚未提供的其他红票。',
    'PARTY_MISMATCH': '请核对这些明确关联的蓝红票为何购销双方不一致，是否关联了错误的发票。',
    'CURRENCY_MISMATCH': '请核对关联蓝红票的币种为何不同，不能跨币种抵消。',
    'PERIOD_MISMATCH': '请核对红冲发生期间及原业务期间，确认是否属于跨期红冲。',
    'RED_EVIDENCE_MISSING': '请确认对应红票是否已提供，或本次是否只提供了已红冲蓝票的清单。',
}


@dataclass(frozen=True)
class TriageRule:
    id: str
    predicate: Predicate
    outcome: str


def truthy(field: str) -> Predicate:
    return Predicate(op='TRUTHY', field=field)


TRIAGE_RULES = (
    TriageRule('SOURCE_INVALID', Predicate(op='NOT', children=[truthy('source_valid')]), 'source_invalid'),
    TriageRule('PARSE_PENDING', truthy('parse_task'), 'parse'),
    TriageRule('BINDING_INCOMPLETE', Predicate(op='NOT', children=[truthy('binding_complete')]), 'binding'),
    TriageRule('UNSAFE_COMPARISON', Predicate(op='NOT', children=[truthy('comparison_safe')]), 'comparison'),
    TriageRule('RED_UNKNOWN_EVIDENCE', truthy('red_unknown_codes'), 'red_unknown'),
    TriageRule('RED_BUSINESS_REVIEW', truthy('red_business_codes'), 'red_business'),
    TriageRule('RED_SYSTEM_REVIEW', truthy('red_status_task'), 'red_system'),
    TriageRule('BILL_ACCOUNT', truthy('bill_account'), 'bill_account'),
    TriageRule('BILL_OPINION', truthy('bill_opinion'), 'bill_opinion'),
    TriageRule('BILL_BUSINESS', truthy('bill_action'), 'bill_action'),
    TriageRule('STATEMENT_ACCOUNT', truthy('statement_action'), 'statement_action'),
    TriageRule('BUSINESS_PERIOD', truthy('business_period'), 'business_period'),
    TriageRule('INVOICE_AMOUNT', truthy('invoice_amount_action'), 'invoice_amount'),
    TriageRule('MISSING_INVOICE_DATE', truthy('missing_invoice_date'), 'missing_date'),
    TriageRule('VERIFY_SOURCE', truthy('verify_task'), 'verify'),
    TriageRule('SAFE_UNKNOWN', truthy('safe_unknown'), 'safe_unknown'),
)


def _base(title: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'version': VERSION, 'ruleset_version': RULESET_VERSION, 'route': 'SYSTEM',
        'title': title, 'human_ready': False,
        'explanation': '系统尚未形成可交给用户判断的具体问题；当前提醒保留，不代表业务错误。',
        'next_action': '由系统维护人员检查原件、字段映射和校验规则；此处可以查看来源，继续处理其他业务事项。',
        'questions': [], 'checks': checks, 'blocking_retained': True,
        'matched_rule': None, 'fallback_eligible': False,
    }


def _human(result: dict[str, Any], descriptor: dict[str, Any], explanation: str,
           questions: list[str], *, required_options: set[str] | None = None) -> dict[str, Any]:
    available = {item.get('id') for item in descriptor.get('options', []) if item.get('available')}
    if not available or required_options and not required_options <= available:
        result.update(explanation=explanation + ' 当前没有可执行的办理选项，需先检查处理能力。')
        return result
    result.update(route='HUMAN', human_ready=True, explanation=explanation,
                  questions=questions, next_action=questions[0])
    return result


def _context(task, rows, checks, source_valid):
    descriptor = task.get('descriptor') or {}
    presentation = descriptor.get('presentation') or {}
    focused = {row['id']: set(row.get('focus_fields', [])) for row in presentation.get('records', [])}
    options = {item['id'] for item in descriptor.get('options', []) if item.get('available')}
    comparisons = [cell for row in rows for cell in row.get('comparison', [])
                   if cell.get('field') in focused.get(row['object_id'], set())]
    codes = {code for check in checks for code in check.get('codes', [])}
    ownership_fields = {'bank_account_ref', 'bank_name', 'account_number', 'holder'} \
        if 'confirm_statement_account' in options else set()
    binding_complete = bool(rows) and len(rows) == len(set(task.get('record_ids', []))) \
        and all(row.get('source_anchor', {}).get('region') for row in rows)
    comparison_safe = not any(
        cell.get('state') in {'DIFFERENT', 'AMBIGUOUS'} or
        cell.get('state') == 'UNLOCATED' and cell.get('field') not in ownership_fields
        for cell in comparisons
    )
    reason = task.get('reason', '')
    values = {
        'source_valid': bool(source_valid),
        'parse_task': task.get('kind') == 'PARSE',
        'binding_complete': binding_complete,
        'comparison_safe': comparison_safe,
        'red_status_task': reason == STATUS_ISSUE,
        'red_unknown_codes': reason == STATUS_ISSUE and bool(codes - BUSINESS_CODES.keys()),
        'red_business_codes': reason == STATUS_ISSUE and bool(codes) and not bool(codes - BUSINESS_CODES.keys()),
        'bill_account': task.get('kind') == 'BILL_ACCOUNT',
        'bill_opinion': task.get('kind') == 'BILL' and any(
            (row.get('bill_confirmation') or {}).get('status') == 'OPINION' for row in rows
        ),
        'bill_action': 'confirm_bill_business' in options,
        'statement_action': 'confirm_statement_account' in options,
        'business_period': reason.startswith('业务期间：') and any(
            cell.get('field') in {'transaction_date', 'invoice_date', 'period'}
            and cell.get('state') in {'DIRECT_MATCH', 'NORMALIZED_MATCH', 'DERIVED'}
            and cell.get('value') for cell in comparisons
        ),
        'invoice_amount_action': 'confirm_invoice_amount' in options,
        'missing_invoice_date': reason.startswith('开票日期：')
            and all((row.get('values') or {}).get('invoice_no') for row in rows)
            and bool(comparisons) and all(
                cell.get('field') == 'invoice_date' and cell.get('state') == 'MISSING'
                and cell.get('region') and cell.get('source_value') in (None, '')
                for cell in comparisons
            ),
        'verify_task': task.get('kind') == 'VERIFY',
    }
    recognized = any(values[key] for key in (
        'parse_task', 'red_status_task', 'bill_account', 'bill_opinion', 'bill_action',
        'statement_action', 'business_period', 'invoice_amount_action',
        'missing_invoice_date', 'verify_task',
    ))
    values['fallback_eligible'] = bool(
        source_valid and binding_complete and comparison_safe and not recognized
    )
    action_context = {**values, 'available_action_ids': sorted(options)}
    applicable = {
        definition.id for definition in ACTION_TYPES
        if evaluate_predicate(definition.applicability, action_context)
    }
    values['safe_unknown'] = set(FALLBACK_IDS) <= applicable
    return {
        'descriptor': descriptor, 'presentation': presentation, 'options': options,
        'comparisons': comparisons, 'codes': codes, 'values': values,
        'applicable_action_ids': applicable,
    }


def _render(outcome, result, task, rows, checks, context):
    descriptor, presentation, codes = context['descriptor'], context['presentation'], context['codes']
    if outcome == 'source_invalid':
        result['explanation'] = '原件已失效、不可读取或哈希不一致，系统不能用当前提取结果判断业务。'
    elif outcome == 'parse':
        result.update(title='资料识别待检查', explanation='本份资料尚未形成可用的提取结果，需先检查格式支持、识别状态或失败原因；这不是客户缺资料的结论。')
    elif outcome == 'binding':
        result['explanation'] = '问题记录或来源定位不完整，需先定位原件中的具体数据，不能要求用户确认一个未定位的问题。'
    elif outcome == 'comparison':
        result['explanation'] = '问题字段的原值、提取值或来源定位尚未核对一致；先检查系统识别，不要求用户替系统确认提取错误。'
    elif outcome == 'red_unknown':
        result['title'] = '红蓝发票关联检查'
        result['explanation'] = '；'.join(dict.fromkeys(
            check.get('message', '证据检查未完成') for check in checks if check.get('status') != 'PASS'
        ))
        uncertain = {'RED_EVIDENCE_MISSING', 'RED_EVIDENCE_INVALID', 'LINK_SOURCE_ANCHOR_MISSING',
                     'SCOPE_MISMATCH', 'DIRECTION_MISMATCH', 'SOURCE_INVALID', 'FACT_NOT_CURRENT'}
        complete_arithmetic = not codes & uncertain and checks and all(
            check.get('links') and check.get('balances')
            and all(balance.get('status') == 'PASS' for balance in check['balances']) for check in checks
        )
        if complete_arithmetic:
            result['explanation'] = '已找到明确关联的红票，不含税金额、税额和价税合计算术抵消均为零。' + result['explanation']
        result['explanation'] += '。红冲状态本身不要求人工确认；先补齐系统证据链，不代表客户必须补充文件。'
    elif outcome == 'red_business':
        result['title'] = '红蓝发票关联检查'
        return _human(result, descriptor, '；'.join(dict.fromkeys(
            check.get('message', '') for check in checks if check.get('status') != 'PASS'
        )), [BUSINESS_CODES[code] for code in sorted(codes)])
    elif outcome == 'red_system':
        result.update(title='红蓝发票关联检查', explanation='“已红冲”是检查线索，不是业务错误。系统尚需完成关联红票、金额、税额及来源校验，不要求你再次确认红冲状态。')
    elif outcome == 'bill_account':
        return _human(result, descriptor, '票据业务归属已有确认，但拟用或历史科目尚未满足当前账套的科目依据；这不是解析错误。',
                      ['请查看已有确认及科目来源，核对当前账套适用科目；如需变更，沿用原有撤销后重新确认流程，不直接创建科目或制证。'])
    elif outcome == 'bill_opinion':
        return _human(result, descriptor, '已有处理意见，但实际业务归属尚未明确；需要补充的是业务判断，不是检查字段映射。',
                      ['请查看已有意见，取得明确业务依据后，通过原有撤销入口撤销意见再重新确认；当前不能重复提交确认。'])
    elif outcome == 'bill_action':
        return _human(result, descriptor, '票据号码和出票信息不能说明企业实际何时收到、持有或背书；需要补充的是业务事实，不一定是新文件。',
                      ['请确认实际业务性质、所属期间及拟用科目；日期不详可只确认月份。'])
    elif outcome == 'statement_action':
        return _human(result, descriptor, '本份流水尚未明确关联到企业银行账户，已有交易金额不因此认定错误。',
                      ['请确认这份流水属于企业的哪个银行账户；账号可选，不凭文件名生成账号。'])
    elif outcome == 'business_period':
        return _human(result, descriptor, presentation.get('explanation') or '原件日期与当前办理期间不同，需明确实际业务归属。',
                      ['请核对清单所列日期是否为实际业务日期，以及这些记录应归属哪个期间；不能直接改成本期。'])
    elif outcome == 'invoice_amount':
        return _human(result, descriptor, '负数或零金额本身不代表错误，但现有证据尚未说明这条记录的实际业务原因。',
                      ['请确认本条记录属于退货、折让、红冲还是其他业务；有原件明确依据时优先检查该依据。'])
    elif outcome == 'missing_date':
        return _human(result, descriptor, '已定位到具体发票；原件对应的开票日期单元格为空，不是日期格式转换失败。',
                      ['请核对该发票原件的开票日期，提供已有日期依据或正确版本；不按文件名猜测日期。'])
    elif outcome == 'verify':
        return _human(result, descriptor, '系统检查已通过，尚未有人核实原件与提取值。',
                      ['只核实当前已查看的原件与提取值，不代表账务可用。'])
    elif outcome == 'safe_unknown':
        result['fallback_eligible'] = True
        explanation = ('当前问题已绑定到可核验的原件和记录，但没有匹配到专用业务动作；'
                       '请选择一种受控处置，原问题和财务门禁继续保留。')
        return _human(result, descriptor, explanation,
                      ['请根据已掌握的事实记录判断、暂停、请求具体材料、排除本期处理或转交复核。'],
                      required_options=set(FALLBACK_IDS))
    return result


def classify_task(task, rows, checks, source_valid):
    """Normalize once, then evaluate the ordered declaration catalog."""
    context = _context(task, rows, checks, source_valid)
    presentation = context['presentation']
    title = presentation.get('type_label') or task.get('title') or '问题待判定'
    result = _base(title, checks)
    result['applicable_action_ids'] = sorted(context['applicable_action_ids'] & context['options'])
    for rule in TRIAGE_RULES:
        if evaluate_predicate(rule.predicate, context['values']):
            result['matched_rule'] = rule.id
            return _render(rule.outcome, result, task, rows, checks, context)
    return result
