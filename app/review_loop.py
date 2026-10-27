"""Stage-four decision contracts; user choices are inputs, never posting approval."""
from collections import defaultdict

REVIEW_POLICY_VERSION = 12


def effective_entries(delivery):
    groups = defaultdict(list)
    for entry in delivery.get('entries', []):
        groups[entry['voucher']].append(entry)
    for revision in delivery.get('revisions', []):
        groups[revision['voucher']] = revision['entries']
    return groups


def review_loop_errors(delivery, context):
    errors = []
    strict = context.get('review_loop_version', 0) >= 3
    if context.get('review_loop_version', 0) >= 4 and not isinstance(delivery.get('settlement_matches'), list):
        errors.append('必须交付付款发票关联清单；没有候选关联时明确为空列表')
    numbers = {a['voucher'] for a in delivery.get('voucher_assessments', [])}
    statements = {a['answer_id']: a for a in context.get('statements', []) if a.get('answer_id')}
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    for finding in delivery.get('findings', []):
        decision = finding.get('decision')
        if decision is None and (finding.get('invoice_matching') or not (strict and finding.get('needs_user'))):
            continue
        if not isinstance(decision, dict) or not text(decision.get('question')) or not isinstance(decision.get('options'), list):
            errors.append('待决事项必须交付具体问题与处理选项')
            continue
        options = decision['options']
        if not options and not text(decision.get('unavailable_reason')):
            errors.append('无法提出方案时须解释目前可完成的边界')
        ids = set()
        recommended = 0
        for option in options:
            if not isinstance(option, dict):
                errors.append('处理选项结构无效'); continue
            if not all(text(option.get(k)) for k in ('id','label','basis','effect','next_step')):
                errors.append('选项缺少名称、依据、影响或后续工作')
            if not isinstance(option.get('assumptions'), list) or not option['assumptions'] or not all(text(x) for x in option['assumptions']):
                errors.append('每个选项必须明确适用前提')
            if option.get('kind') not in {'BUSINESS_FACT','ACCOUNTING_CHOICE','DEFER'}:
                errors.append('选项必须区分业务陈述、处理选择与暂无法判断')
            if type(option.get('recommended')) is not bool:
                errors.append('推荐标识必须为布尔值')
            recommended += option.get('recommended') is True
            if option.get('id') in ids:
                errors.append('同一事项的选项编号不能重复')
            ids.add(option.get('id'))
        if recommended > 1:
            errors.append('同一事项最多推荐一个方案')
    revisions = delivery.get('revisions', [])
    if not isinstance(revisions, list):
        return errors + ['修订分录必须为列表']
    seen = set()
    applications = delivery.get('travel_policy_applications', [])
    policy_applications = {p.get('id'): p for p in applications if isinstance(p, dict) and isinstance(p.get('id'), str)} if isinstance(applications, list) else {}
    for revision in revisions:
        number = revision.get('voucher')
        if number not in numbers or number in seen:
            errors.append('修订必须唯一关联已有凭证')
        seen.add(number)
        ids = revision.get('answer_ids', [])
        pids = revision.get('policy_application_ids', [])
        policy_authorized = (bool(context.get('travel_policy')) and isinstance(pids, list) and bool(pids)
                             and all(isinstance(p, str) and p in policy_applications for p in pids))
        if pids and not policy_authorized:
            errors.append('修订引用的企业规则应用无效或规则未启用')
        rule_ids = revision.get('profile_rule_ids', [])
        profile = context.get('bookkeeping_profile') or {}
        profile_authorized = (profile.get('id') == 'AGENCY_SIMPLE' and isinstance(rule_ids, list) and bool(rule_ids)
                              and all(isinstance(r, str) and r in profile.get('rule_ids', []) for r in rule_ids)
                              and delivery.get('bookkeeping_profile') == {k: profile.get(k) for k in ('id', 'version', 'selection_version')})
        if rule_ids and not profile_authorized:
            errors.append('修订引用的简易代账规则未启用或不适用')
        policy_authorized = policy_authorized or profile_authorized
        if not text(revision.get('reason')) or not isinstance(ids, list) or not set(ids) <= set(statements) or (not ids and not policy_authorized):
            errors.append('修订必须说明原因并引用本次上下文中的用户回应')
        elif not policy_authorized and not any(statements[i].get('kind') != 'MATERIALS_COMPLETE' and statements[i].get('option', {}).get('kind') != 'DEFER' for i in ids):
            errors.append('仅资料范围或暂无法判断不能授权修改分录')
    responses = delivery.get('decision_responses', [])
    if not isinstance(responses, list):
        return errors + ['回应处理结果必须为列表']
    response_ids = [r.get('answer_id') for r in responses]
    if len(set(response_ids)) != len(response_ids) or not set(response_ids) <= set(statements):
        errors.append('回应结果必须唯一引用真实用户回应')
    if strict and set(response_ids) != set(statements):
        errors.append('必须逐项说明用户回应被如何采用及仍未解决什么')
    for response in responses:
        if response.get('outcome') not in {'APPLIED','PARTIAL','UNRESOLVED'} or not text(response.get('explanation')):
            errors.append('回应结果必须说明已应用、部分应用或无法解决的具体原因')
        if not set(response.get('affected_vouchers', [])) <= numbers:
            errors.append('回应结果必须关联真实凭证')
    return errors


def review_loop_approved(delivery, review):
    """Require explicit independent coverage before accepting options or revisions."""
    expected = {
        'reviewed_decisions': {f['id'] for f in delivery.get('findings', []) if f.get('decision') is not None},
        'reviewed_revisions': {r['voucher'] for r in delivery.get('revisions', [])},
        'reviewed_responses': {r['answer_id'] for r in delivery.get('decision_responses', [])},
        'reviewed_settlement_matches': {m['id'] for m in delivery.get('settlement_matches', [])},
        'reviewed_invoice_matching': {f['id'] for f in delivery.get('findings', []) if f.get('invoice_matching') is not None},
    }
    return all(isinstance(review.get(key, []), list)
               and all(isinstance(value, str) for value in review.get(key, []))
               and set(review.get(key, [])) == values
               for key, values in expected.items())
