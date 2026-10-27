"""Evidence-backed invoice matching tasks and read-only workbench projection."""
import hashlib
import json
from decimal import Decimal, InvalidOperation


def source_key(ref):
    return tuple(ref.get(k) for k in ('source_id', 'sheet', 'page', 'row', 'location'))


def invoice_id(ref):
    return hashlib.sha256(json.dumps(source_key(ref), ensure_ascii=False).encode()).hexdigest()[:24]


def invoice_matching_errors(delivery, context):
    errors = []
    banks = {source_key(b['source']): b for b in delivery.get('bank', [])}
    invoices = {source_key(i['source']): i for i in delivery.get('invoices', [])}
    statements = {a['answer_id']: a for a in context.get('statements', []) if a.get('answer_id')}
    matching = {}
    for finding in delivery.get('findings', []):
        item = finding.get('invoice_matching')
        if item is None:
            continue
        try:
            if not isinstance(item, dict) or not finding.get('needs_user'):
                raise ValueError('票款待匹配必须关联当前人工事项')
            if finding.get('decision') is not None:
                raise ValueError('票款待匹配使用选票入口，不保留组合猜测的处理选项')
            state = item.get('state')
            if state not in {'MISSING', 'CANDIDATE', 'AMOUNT_DIFFERENCE'}:
                raise ValueError('票款待匹配类型无效')
            if not isinstance(item.get('reason'), str) or not item['reason'].strip():
                raise ValueError('必须说明待匹配的依据与缺口')
            groups = {}
            for field, allowed in (('payment_sources', banks), ('candidate_invoice_sources', invoices), ('confirmed_invoice_sources', invoices)):
                refs = item.get(field)
                if not isinstance(refs, list) or not all(isinstance(r, dict) for r in refs):
                    raise ValueError('票款待匹配须提供付款及票据定位列表')
                keys = [source_key(r) for r in refs]
                if len(set(keys)) != len(keys) or not set(keys) <= set(allowed):
                    raise ValueError('票款定位重复或不在本轮银行/发票清单内')
                groups[field] = keys
            payments, candidates, confirmed = (groups[k] for k in ('payment_sources', 'candidate_invoice_sources', 'confirmed_invoice_sources'))
            if not payments or set(candidates) & set(confirmed):
                raise ValueError('款项必须存在，候选票据与已确认票据不能重叠')
            directions = set()
            payment_total = Decimal(0)
            for key in payments:
                income, expense = Decimal(banks[key]['income']), Decimal(banks[key]['expense'])
                if not income.is_finite() or not expense.is_finite() or min(income, expense) < 0 or (income > 0) == (expense > 0):
                    raise ValueError('必须引用单向非零的真实资金记录')
                directions.add('IN' if income else 'OUT')
                payment_total += income or expense
            if len(directions) != 1:
                raise ValueError('不能混合收款与付款来抵消差额')
            if state == 'MISSING' and (candidates or confirmed):
                raise ValueError('缺票类型不能包含已找到的票据')
            if state == 'CANDIDATE' and not candidates:
                raise ValueError('归属待确认须保留候选票据')
            if state == 'AMOUNT_DIFFERENCE':
                if candidates or not confirmed:
                    raise ValueError('只有票据归属已确认后才能列为确定差额')
                gross = sum((Decimal(invoices[k]['gross']) for k in confirmed), Decimal(0))
                if not gross.is_finite() or payment_total == gross:
                    raise ValueError('金额相同不能列为金额差异')
            if confirmed:
                evidence, answer_ids = item.get('confirmation_evidence', []), item.get('answer_ids', [])
                if not isinstance(evidence, list) or not isinstance(answer_ids, list) or not set(answer_ids) <= set(statements):
                    raise ValueError('已确认归属须引用有效原件或真实回应')
                evidence_keys = {source_key(r) for r in finding.get('evidence', [])}
                if not all(isinstance(r, dict) and source_key(r) in evidence_keys for r in evidence):
                    raise ValueError('确认依据必须纳入该事项的原件审查')
                valid_answers = [statements[a] for a in answer_ids if statements[a].get('kind') != 'MATERIALS_COMPLETE'
                                 and statements[a].get('option', {}).get('kind') != 'DEFER'
                                 and set(statements[a].get('affected_vouchers', [])) & set(finding.get('affected_vouchers', []))]
                if len(valid_answers) != len(answer_ids) or not (evidence or valid_answers):
                    raise ValueError('已确认归属不能只以金额相等或资料齐全声明为依据')
                if not evidence and all(a.get('kind') == 'INVOICE_MATCH_SELECTION' and not a.get('note', '').strip() for a in valid_answers):
                    selected = {source_key(i['source']) for a in valid_answers
                                for i in a.get('invoice_selection', {}).get('invoices', [])}
                    if not set(confirmed) <= selected:
                        raise ValueError('仅选票的回应只能确认实际选择的票据，不能确认其他票据')
            matching[finding['id']] = (set(payments), set(candidates + confirmed))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            errors.append('票款待匹配无效：' + str(exc))
    if context.get('review_loop_version', 0) >= 8:
        for match in delivery.get('settlement_matches', []):
            if match.get('status') != 'CANDIDATE':
                continue
            covered = [matching[fid] for fid in match.get('finding_ids', []) if fid in matching]
            if not any(source_key(match['payment_source']) in payments
                       and {source_key(r) for r in match['invoice_sources']} <= invoices
                       for payments, invoices in covered):
                errors.append('候选票款关联必须归入票款待匹配并覆盖候选票据，不能继续包装为用途问题')
    return errors


def matching_projection(delivery):
    """Amounts and selectable IDs come from reviewed records, never UI arithmetic."""
    banks = {source_key(b['source']): b for b in delivery.get('bank', [])}
    invoices = {source_key(i['source']): i for i in delivery.get('invoices', [])}
    used = {}
    for match in delivery.get('settlement_matches', []):
        if match.get('status') == 'MATCHED':
            for ref in match['invoice_sources']:
                used.setdefault(source_key(ref), []).extend(match['affected_vouchers'])
    for finding in delivery.get('findings', []):
        for ref in (finding.get('invoice_matching') or {}).get('confirmed_invoice_sources', []):
            used.setdefault(source_key(ref), []).extend(finding.get('affected_vouchers', []))
    catalog = []
    for key, row in invoices.items():
        catalog.append({**row, 'id': invoice_id(row['source']), 'used_by': sorted(set(used.get(key, [])))})
    rows = []
    for finding in delivery.get('findings', []):
        item = finding.get('invoice_matching')
        if not item or not finding.get('needs_user'):
            continue
        payments = [banks[source_key(r)] for r in item['payment_sources']]
        payment_total = sum((Decimal(b['expense']) or Decimal(b['income']) for b in payments), Decimal(0))
        candidate_total = sum((Decimal(invoices[source_key(r)]['gross']) for r in item['candidate_invoice_sources']), Decimal(0))
        confirmed_total = sum((Decimal(invoices[source_key(r)]['gross']) for r in item['confirmed_invoice_sources']), Decimal(0))
        rows.append({'finding_id': finding['id'], 'state': item['state'], 'reason': item['reason'],
                     'party': '、'.join(sorted({b.get('counterparty') or '对方名称未识别' for b in payments})),
                     'payments': payments, 'payment_total': f'{payment_total:.2f}',
                     'candidate_total': f'{candidate_total:.2f}', 'confirmed_total': f'{confirmed_total:.2f}',
                     'candidate_invoice_ids': [invoice_id(r) for r in item['candidate_invoice_sources']],
                     'confirmed_invoice_ids': [invoice_id(r) for r in item['confirmed_invoice_sources']],
                     'difference': f'{payment_total - confirmed_total:.2f}' if item['state'] == 'AMOUNT_DIFFERENCE' else None,
                     'affected_vouchers': finding.get('affected_vouchers', []), 'evidence': finding.get('evidence', []),
                     'blocks_confirmation': finding.get('blocks_confirmation', True),
                     'can_continue': finding.get('request', {}).get('can_continue', '')})
    return {'items': rows, 'invoices': catalog}
