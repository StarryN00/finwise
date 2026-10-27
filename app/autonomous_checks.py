"""Server-owned admission checks; model claims never replace original evidence."""
from collections import Counter, defaultdict
from app.travel_policy import travel_policy_errors
from app.bookkeeping_profile import bookkeeping_profile_errors
from app.reimbursements import reimbursement_errors
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from app.stage23_pilot import read_tables, check_delivery, sha256
from app.review_loop import review_loop_errors
from app.invoice_matching import invoice_matching_errors


def settlement_match_errors(delivery, tables=None, pdf=None, anchor=None):
    """Recompute invoice/payment links; matching tax never establishes settlement."""
    errors, checks = [], []
    matches = delivery.get('settlement_matches', [])
    if not isinstance(matches, list):
        return ['付款发票关联必须为列表'], checks
    def key(ref):
        return tuple(ref.get(k) for k in ('source_id', 'sheet', 'page', 'row', 'location'))
    def money(value):
        if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d{2}', value):
            raise ValueError('金额必须是非负两位小数字符串')
        return Decimal(value)
    def original_value(ref, value):
        if tables is None or ref.get('source_id') not in tables:
            return True  # PDF amounts are independently checked against OCR below.
        rows = tables[ref['source_id']].get(ref.get('sheet'), [])
        values = next(r['values'] for r in rows if r['row'] == ref.get('row'))
        return any(str(v).strip() and Decimal(str(v)) == value for v in values
                   if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
                   or isinstance(v, str) and re.fullmatch(r'\d+(?:\.\d+)?', v.strip()))
    seen_ids, used_payments, used_invoices, used_components = set(), set(), set(), set()
    vouchers = {a['voucher'] for a in delivery.get('voucher_assessments', [])}
    findings = {f['id'] for f in delivery.get('findings', [])}
    for match in matches:
        try:
            if not isinstance(match, dict) or not isinstance(match.get('id'), str) or not match['id'].strip() or match['id'] in seen_ids:
                raise ValueError('关联编号必须唯一')
            seen_ids.add(match['id'])
            if match.get('basis') != 'GROSS' or match.get('status') not in {'MATCHED', 'CANDIDATE'}:
                raise ValueError('付款关联仅允许价税合计口径，税额不能用作匹配依据')
            if not isinstance(match.get('reason'), str) or not match['reason'].strip():
                raise ValueError('关联必须说明业务依据及未解决边界')
            for field, allowed in (('affected_vouchers', vouchers), ('finding_ids', findings)):
                refs = match.get(field)
                if not isinstance(refs, list) or not set(refs) <= allowed:
                    raise ValueError('关联必须指向已有凭证及具体事项')
            payment_ref = match['payment_source']
            invoice_refs = match['invoice_sources']
            if not isinstance(payment_ref, dict) or not isinstance(invoice_refs, list) or not invoice_refs or not all(isinstance(r, dict) for r in invoice_refs):
                raise ValueError('关联须定位银行付款和候选发票')
            if anchor and not all(anchor(r) for r in [payment_ref, *invoice_refs]):
                raise ValueError('关联原件定位无效')
            banks = [b for b in delivery.get('bank', []) if key(b['source']) == key(payment_ref)]
            if len(banks) != 1 or money(banks[0]['expense']) <= 0 or money(banks[0]['income']) != 0:
                raise ValueError('关联须唯一定位一笔实际银行付款')
            payment = money(banks[0]['expense'])
            if not original_value(payment_ref, payment):
                raise ValueError('付款金额与原件不一致')
            if pdf is not None and payment_ref.get('source_id') not in (tables or {}):
                raw = (pdf.get(payment_ref['source_id'], {}).get('ocr') or {}).get('statement', {}).get('rows', [])
                observed = [r for r in raw if int(r['sequence']) == int(banks[0]['sequence'])]
                if len(observed) != 1 or Decimal(str(observed[0]['debit'])) != payment:
                    raise ValueError('付款关联金额未通过银行原件OCR复算')
            gross = Decimal(0)
            invoice_keys = set()
            for ref in invoice_refs:
                invoices = [i for i in delivery.get('invoices', []) if key(i['source']) == key(ref)]
                if len(invoices) != 1 or key(ref) in invoice_keys:
                    raise ValueError('关联发票必须唯一且不得重复累计')
                invoice = invoices[0]
                value = money(invoice['gross'])
                if (invoice['kind'] != '进项' or money(invoice['net']) + money(invoice['tax']) != value
                        or not original_value(ref, money(invoice['net'])) or not original_value(ref, money(invoice['tax']))):
                    raise ValueError('关联发票价税合计须与原件一致')
                invoice_keys.add(key(ref)); gross += value
            components = match.get('other_components', [])
            if not isinstance(components, list):
                raise ValueError('非发票报销组成必须为列表')
            other = Decimal(0)
            component_keys = set()
            for component in components:
                ref = component['source']; value = money(component['amount'])
                if (not isinstance(ref, dict) or not isinstance(component.get('reason'), str) or not component['reason'].strip()
                        or value <= 0 or key(ref) in component_keys | invoice_keys | {key(payment_ref)}
                        or anchor and not anchor(ref) or not original_value(ref, value)):
                    raise ValueError('非发票组成须有独立原件金额和原因，不能用付款差额造数')
                component_keys.add(key(ref)); other += value
            difference = payment - gross - other
            checks.append({'id':match['id'], 'payment':str(payment), 'invoice_gross':str(gross),
                           'other_amount':str(other), 'difference':str(difference), 'status':match['status']})
            if match['status'] == 'MATCHED':
                if difference != 0:
                    raise ValueError('价税合计及有据报销组成未覆盖付款，不能声明完整匹配')
                if key(payment_ref) in used_payments or invoice_keys & used_invoices or component_keys & used_components:
                    raise ValueError('同一付款或发票不能重复完整匹配')
                used_payments.add(key(payment_ref)); used_invoices.update(invoice_keys); used_components.update(component_keys)
            elif not match['finding_ids']:
                raise ValueError('候选关联须保留差额或业务归属的具体待决事项')
        except (KeyError, ValueError, InvalidOperation, TypeError, StopIteration) as exc:
            errors.append('付款发票关联无效：' + str(exc))
    return errors, checks


def confirmation_blockers(delivery, number):
    """Older findings fail closed; either side of the association can block."""
    linked = {fid for a in delivery.get('voucher_assessments', [])
              if a.get('voucher') == number for fid in a.get('finding_ids', [])}
    return [f for f in delivery.get('findings', []) if f.get('needs_user')
            and f.get('blocks_confirmation', True) is not False
            and (number in f.get('affected_vouchers', []) or f.get('id') in linked)]


def validate(workspace, manifest, delivery, pdf, context=None):
    errors, checks = [], []
    if not isinstance(delivery,dict) or any(not isinstance(delivery.get(key,[]),list) for key in ('entries','findings','voucher_assessments','opening','bank','invoices')):
        return {'passed':False,'errors':['成果结构必须符合交付契约'],'checks':[]}
    if not isinstance(delivery.get('source_roles'),dict) or not isinstance(delivery.get('bindings',{}),dict):
        return {'passed':False,'errors':['原件用途或账表绑定结构不正确'],'checks':[]}
    tables = read_tables(workspace, manifest)
    sources = {s['id']: s for s in manifest['sources']}
    def require(ok, message):
        checks.append(message)
        if not ok:
            errors.append(message)
    def amount(value):
        if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d{2}', value):
            raise ValueError('金额必须是非负两位小数字符串')
        return Decimal(value)
    def anchor(ref):
        if not isinstance(ref, dict) or ref.get('source_id') not in sources:
            return False
        sid = ref['source_id']
        if sid in tables:
            return any(r['row'] == ref.get('row') for r in tables[sid].get(ref.get('sheet'), []))
        if sources[sid]['path'].lower().endswith('.pdf'):
            from pypdf import PdfReader
            page = ref.get('page')
            return isinstance(page, int) and 1 <= page <= len(PdfReader(workspace/sources[sid]['path']).pages)
        return bool(ref.get('location'))
    require(delivery.get('period') == manifest['period'], '目标期间一致')
    require(set(delivery.get('source_roles', {})) == set(sources), '所有原件均有用途与限制')
    require(all(sha256(workspace/s['path']) == s['sha256'] for s in sources.values()), '原件哈希一致')
    entries = delivery.get('entries', [])
    grouped = defaultdict(list)
    voucher_dates = defaultdict(set)
    for entry in entries:
        try:
            debit, credit = amount(entry['debit']), amount(entry['credit'])
            require(bool(debit) != bool(credit), '分录恰有一侧正金额')
            require(date.fromisoformat(entry['date']).strftime('%Y-%m') == manifest['period'], '分录日期在本期')
            require(bool(entry['code']) and bool(entry['name']) and bool(entry['voucher']), '分录有科目与凭证号')
            require(anchor(entry.get('source')), '分录可定位原件')
            grouped[entry['voucher']].append((debit, credit))
            voucher_dates[entry['voucher']].add(entry['date'])
        except (KeyError, ValueError, InvalidOperation, TypeError):
            errors.append('分录结构、金额或日期无效')
    for number, rows in grouped.items():
        require(sum(x[0] for x in rows) == sum(x[1] for x in rows) > 0, f'{number}借贷平衡')
        require(len(voucher_dates[number]) == 1, f'{number}凭证日期一致')
    assessments = delivery.get('voucher_assessments', [])
    require(Counter(a.get('voucher') for a in assessments) == Counter(grouped.keys()), '每张凭证恰有一项业务评估')
    findings = delivery.get('findings', [])
    require(len({f.get('id') for f in findings}) == len(findings), '事项编号唯一')
    for finding in findings:
        require(isinstance(finding.get('affected_vouchers',[]),list), '事项影响范围必须为列表')
        require(bool(finding.get('title')) and bool(finding.get('detail')) and type(finding.get('needs_user')) is bool, '事项说明与归属明确')
        require(bool(finding.get('evidence')) and all(anchor(e) for e in finding.get('evidence', [])), '事项有原件定位')
        require(set(finding.get('affected_vouchers', [])) <= set(grouped), '事项关联现有候选')
        require(type(finding.get('blocks_confirmation', True)) is bool, '确认阻断标志必须为布尔值')
        if finding.get('needs_user') and finding.get('blocks_confirmation') is False:
            require(bool(str(finding.get('confirmation_reason', '')).strip()), '非阻断事项必须解释为何不影响当前分录确认')
        request = finding.get('request')
        if request is not None:
            require(isinstance(request, dict) and all(isinstance(request.get(k), str) and request[k].strip()
                    for k in ('question', 'why_needed', 'can_continue', 'evidence_request'))
                    and request.get('scope') in {'PERIOD', 'ONBOARDING'}, '补证须明确最小问题、影响、可继续工作和所需依据')
    for assessment in assessments:
        number = assessment.get('voucher')
        require(assessment.get('status') in {'READY_FOR_REVIEW','NEEDS_EVIDENCE','SYSTEM_BLOCKED'}, '候选状态有效')
        require(bool(assessment.get('reason')) and bool(assessment.get('evidence')) and all(anchor(e) for e in assessment.get('evidence', [])), '候选有业务依据')
        require(set(assessment.get('finding_ids', [])) <= {f.get('id') for f in findings}, '候选关联事项有效')
        blockers = confirmation_blockers(delivery, number)
        require(assessment.get('status') != 'READY_FOR_REVIEW' or not blockers, '缺关键业务依据不能确认通过')
        require(assessment.get('status') != 'NEEDS_EVIDENCE' or bool(blockers), '缺证候选必须交付具体补证事项')
    require(bool(entries) or bool(findings), '没有候选时必须说明具体资料缺口')
    errors.extend(review_loop_errors(delivery, context or {}))
    errors.extend(travel_policy_errors(delivery, context or {}))
    errors.extend(bookkeeping_profile_errors(delivery, context or {}))
    errors.extend(reimbursement_errors(delivery, context or {}, anchor, tables, pdf))
    applications = delivery.get('travel_policy_applications', [])
    for application in applications if isinstance(applications, list) else []:
        if isinstance(application, dict):
            require(isinstance(application.get('evidence'), list) and bool(application['evidence'])
                    and all(anchor(ref) for ref in application['evidence']), '差旅规则应用须定位本轮原件')
    settlement_errors, settlement_checks = settlement_match_errors(delivery, tables, pdf, anchor)
    errors.extend(settlement_errors)
    errors.extend(invoice_matching_errors(delivery, context or {}))
    for revision in delivery.get('revisions', []):
        rows = revision.get('entries', [])
        require(bool(rows), '修订必须保留有依据的非空分录')
        debit_total, credit_total = Decimal(0), Decimal(0)
        dates = set()
        for entry in rows:
            try:
                debit, credit = amount(entry['debit']), amount(entry['credit'])
                require(bool(debit) != bool(credit), '修订分录恰有一侧正金额')
                require(entry['voucher'] == revision['voucher'] and bool(entry['code']) and bool(entry['name']), '修订分录凭证与科目有效')
                require(date.fromisoformat(entry['date']).strftime('%Y-%m') == manifest['period'], '修订日期在本期')
                require(anchor(entry.get('source')), '修订仍须定位原件，用户选择不是原件')
                debit_total += debit; credit_total += credit; dates.add(entry['date'])
            except (KeyError, ValueError, InvalidOperation, TypeError):
                errors.append('修订分录结构无效')
        require(debit_total == credit_total > 0 and len(dates) == 1, '修订借贷平衡且凭证日期一致')
    require(len(delivery.get('report', '')) >= 100, '有处理结论与范围限制')
    bindings = delivery.get('bindings', {})
    if all(bindings.get(k) for k in ('journal', 'opening', 'reported_balance')):
        prior = check_delivery(workspace, manifest, delivery, pdf,
            bank_source_ids={r['source']['source_id'] for r in delivery.get('bank',[])},source_anchor=anchor)
        errors.extend(prior['errors'])
        checks.extend(prior.get('checks', []))
    elif bindings.get('journal'):
        b = bindings['journal']
        try:
            raw = [r for r in tables[b['source_id']][b['sheet']]
                   if str(r['values'][b['date']]).startswith(manifest['period']) and r['values'][b['voucher']]]
            expected = Counter((r['row'], str(r['values'][b['code']]), str(r['values'][b['voucher']]),
                                Decimal(str(r['values'][b['debit']] or 0)), Decimal(str(r['values'][b['credit']] or 0))) for r in raw)
            actual = Counter((e['source']['row'], e['code'], e['voucher'], amount(e['debit']), amount(e['credit'])) for e in entries)
            require(expected == actual, '本期原账分录完整重建')
        except (KeyError, IndexError, TypeError, InvalidOperation):
            errors.append('原账绑定无法重算')
    # Source-bookkeeping cannot use a fabricated period ledger as a validation oracle.
    require(delivery.get('mode') in {'JOURNAL_REVIEW','SOURCE_BOOKKEEPING'}, '明确已有账审查或原件制证模式')
    require(delivery.get('mode') != 'JOURNAL_REVIEW' or bool(bindings.get('journal')), '已有账审查需要原账绑定')
    return {'passed': not errors, 'errors': errors, 'checks': checks, 'settlement_checks': settlement_checks,
            'mode': delivery.get('mode'), 'source_integrity': '原件哈希一致' not in errors,
            'limitations': ['程序验证定位、结构和算术；业务覆盖及候选依据须经独立原件审查']}
