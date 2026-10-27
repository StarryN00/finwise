"""Confirmed ledger policy and source-backed application gates, never posting authority."""
from app.ontology.contracts import Scope
from app.ontology.store import digest
from app.reimbursements import reimbursement_covers_voucher

POLICY_TYPE = 'EnterpriseTravelPolicy'
POLICY_SUMMARY = ('有发票且银行备注差旅、金额关联及重复检查通过，默认管理费用—差旅费；'
                  '餐费、礼品按本企业默认分类并允许按实际用途调整；补贴、借款核销等单独人工确认。')
POLICY_RULES = {
    'recognition': 'INVOICE_AND_BANK_TRAVEL_MEMO',
    'default_account_name': '管理费用—差旅费',
    'meal_default_account_name': '管理费用—业务招待费',
    'gift_default_account_name': '管理费用—福利费',
    'explicit_purpose_overrides_default': True,
    'payee_mismatch_alone_blocks': False,
    'allowance_requires_confirmation': True,
    'loan_offset_requires_confirmation': True,
    'allowance_monthly_limit': None,
    'cross_period': 'CHECK_HISTORY_AND_OPEN_BALANCE',
    'formal_posting': False,
}


def policy_scope(scope):
    # One fixed namespace per ledger; this is not an accounting period or a new book.
    return Scope(**{**scope.model_dump(), 'accounting_period_id': '__policies__', 'baseline_id': 'travel'})


def policy_id(scope):
    return 'travel-policy-' + digest(policy_scope(scope).model_dump())


def travel_policy_errors(delivery, context):
    """Validate explicit policy references and human gates; semantic evidence is independently reviewed."""
    errors = []
    policy = context.get('travel_policy')
    applications = delivery.get('travel_policy_applications', [])
    if not isinstance(applications, list):
        return ['差旅规则应用清单必须为列表']
    if policy and 'travel_policy_applications' not in delivery:
        errors.append('须交付差旅规则应用清单；没有适用业务时明确为空列表')
    if applications and not policy:
        return ['没有生效的企业差旅规则，不能引用默认处理政策']
    assessments = {a['voucher']: a for a in delivery.get('voucher_assessments', [])}
    findings = {f['id']: f for f in delivery.get('findings', [])}
    matches = {m['id']: m for m in delivery.get('settlement_matches', [])}
    answers = {a['answer_id']: a for a in context.get('statements', [])}
    manual_codes = {'ALLOWANCE', 'DUPLICATE', 'LOAN_OFFSET', 'EMPLOYEE_SETTLEMENT',
                    'PERIOD', 'AMOUNT_GAP', 'CLASSIFICATION', 'INVOICE_MISSING'}
    ids = set()
    for item in applications:
        try:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip() or item['id'] in ids:
                raise ValueError('规则应用编号必须唯一且非空')
            ids.add(item['id'])
            if item.get('policy_id') != policy['id'] or type(item.get('policy_version')) is not int or item['policy_version'] != policy['version']:
                raise ValueError('引用的差旅规则版本不是本轮冻结版本')
            number = item.get('voucher')
            if number not in assessments or item.get('kind') not in {'TRAVEL', 'MEAL', 'GIFT', 'ALLOWANCE', 'LOAN_OFFSET', 'SETTLEMENT'}:
                raise ValueError('规则应用须关联真实凭证和明确业务类别')
            if not isinstance(item.get('reason'), str) or not item['reason'].strip() or not isinstance(item.get('evidence'), list) or not item['evidence']:
                raise ValueError('规则应用须解释处理依据并定位原件')
            pending = item.get('manual_reasons')
            confirmed = item.get('confirmed_reasons')
            fids = item.get('finding_ids')
            mids = item.get('settlement_match_ids')
            if not all(isinstance(x, list) for x in (pending, confirmed, fids, mids)):
                raise ValueError('规则应用须提供人工事项、确认、问题和关联编号清单')
            if any(not isinstance(code, str) or code not in manual_codes for code in pending):
                raise ValueError('人工事项类型无效')
            if any(not isinstance(fid, str) or fid not in findings or number not in findings[fid].get('affected_vouchers', []) for fid in fids):
                raise ValueError('规则应用的问题须关联同一凭证')
            if any(not isinstance(mid, str) or mid not in matches or number not in matches[mid].get('affected_vouchers', []) for mid in mids):
                raise ValueError('规则应用的票款关联须属于同一凭证')
            confirmed_codes = set()
            for confirmation in confirmed:
                if not isinstance(confirmation, dict) or confirmation.get('code') not in manual_codes:
                    raise ValueError('人工确认类型无效')
                aids = confirmation.get('answer_ids')
                if not isinstance(aids, list) or not aids:
                    raise ValueError('人工确认必须引用实际用户回应')
                for aid in aids:
                    answer = answers.get(aid) if isinstance(aid, str) else None
                    invoice_statement = (answer and answer.get('kind') == 'INVOICE_MATCH_SELECTION'
                                         and (bool(answer.get('note', '').strip())
                                              or confirmation['code'] in {'INVOICE_MISSING', 'AMOUNT_GAP'}))
                    if not answer or (answer.get('kind') not in {'FREE_TEXT', 'REVIEW_SELECTION'} and not invoice_statement) or answer.get('option', {}).get('kind') == 'DEFER':
                        raise ValueError('企业政策、资料齐全或暂无法判断不能代替逐笔人工确认')
                    if number not in answer.get('affected_vouchers', []):
                        raise ValueError('人工确认必须属于当前凭证')
                confirmed_codes.add(confirmation['code'])
            if set(pending) & confirmed_codes:
                raise ValueError('同一人工事项不能同时待确认和已确认')
            required = {item['kind']} if item['kind'] in {'ALLOWANCE', 'LOAN_OFFSET'} else set()
            if not required <= set(pending) | confirmed_codes:
                raise ValueError('补贴或借款核销必须保留人工确认门禁')
            if pending:
                blockers = [findings[fid] for fid in fids if findings[fid].get('needs_user') and findings[fid].get('blocks_confirmation', True)]
                if not blockers or assessments[number]['status'] == 'READY_FOR_REVIEW':
                    raise ValueError('未确认的人工事项必须保留具体阻断问题，不能直接放行')
            if item['kind'] == 'TRAVEL' and assessments[number]['status'] == 'READY_FOR_REVIEW':
                if not reimbursement_covers_voucher(delivery, context, number) and (not mids or any(matches[mid].get('status') != 'MATCHED' or not matches[mid].get('invoice_sources') for mid in mids)):
                    raise ValueError('普通差旅进入复核须有已核实的发票和付款关联')
        except (ValueError, TypeError, KeyError) as exc:
            errors.append('差旅规则应用无效：' + str(exc))
    return errors


def travel_policy_reviewed(delivery, review, context):
    policy = context.get('travel_policy')
    expected = {'id': policy['id'], 'version': policy['version']} if policy else None
    if review.get('reviewed_travel_policy') != expected:
        return False
    applications = delivery.get('travel_policy_applications', [])
    if not isinstance(applications, list) or any(not isinstance(a, dict) or not isinstance(a.get('id'), str) for a in applications):
        return False
    ids = [a['id'] for a in applications]
    actual = review.get('reviewed_travel_policy_applications', [])
    return (isinstance(actual, list) and all(isinstance(x, str) for x in actual)
            and len(actual) == len(set(actual)) and set(actual) == set(ids))
