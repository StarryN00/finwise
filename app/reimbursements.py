"""Per-person reimbursement controls for proposed entries, never a posted subledger."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re

from app.invoice_matching import source_key
from app.review_loop import effective_entries


def reimbursement_contract():
    return '''

### 个人报销往来（合同 v12，仅简易代账）
employee_reimbursements：用户与代账公司确认“以票据为准、个人报销付款抵扣、差额记其他应付款，后续月份逐步匹配”；人员必须分别挂账，归属不明票据暂留待分配，禁止公司报销总池跨人冲抵。
本规则替代普通个人报销“票款必须逐笔等额匹配”和“有差额必阻断”的前提，不取消原件、人员归属、查重、进项依据、费用期间、补贴或借款核销要求。
1. 对已经确认为公司报销且归属明确的票据，按实际费用分类及可抵扣税额记借方，按价税合计贷记本企业其他应付款—该个人；给该人的实际报销付款借记同一往来、贷记银行。未见票据时先记有据的个人报销付款往来，不虚构费用或税额。退款按实际反方向逐笔处理。不能将一般借款/工资/供应商付款冒充个人报销，不能自动核销历史个人借款。
2. 不要求发票与某一笔付款一一对应或金额相同；同一个人的票据和付款分别汇总，余额跨月保留。期末贷方余额=期初贷方余额+本期有据报销票据价税合计-本期报销付款（退款/红票按真实方向）。借方余额必须明确“已付、待后续票据抵扣”，不能显示成公司欠个人或把差额当作补贴/无票费用。金额大小和1000元均不改变此规则。
3. 按原件/真实人工陈述确认报销人；收款人与报销人不同须保留双方，并用代收付依据确定所属个人。不能仅按金额、地点、日期、同一批上传推断人员。确实看不出报销人的票据，放 unassigned_reimbursement_invoices，只问“这张票是谁报销的”，不猜人、不与任何人的付款强行抵扣。已知个人的付款仍可单独进入复核；票据待分配不自动阻断该付款。
4. 先查该个人前期凭证与未结余额。同一发票已在前期入费用时不得本期重复记费，本期付款仅结往来。期初以本企业有据余额/已确认账为准；本系统草稿、ACCEPTED运行或未正式记账的候选不是正式期初。缺期初时问具体历史缺口，不能默认为零。科目依据必须确实包含该个人及该明细编码，不能引用差旅费行或其他应付款总科目冒充现存个人明细；确无个人明细时保留具体科目缺口，不能自行编造编码或零期初。未来月份仍按原件和该人历史余额续算；不改前期账。既有原账entries完整保留，需变更时用revisions及profile_rule_ids:["employee_reimbursements"]，不得仅删除问题或改状态放行。
5. delivery必须交付employee_reimbursements和unassigned_reimbursement_invoices列表，无适用业务为[]。每个人一项，必须覆盖全部适用报销（含仅有付款、只有票据和已结清），且其他应付款明细不能被不同人共用。结构：
{id:"ER-张三",person:"张三",account_code:"本企业明细科目编码",account_name:"实际科目名",account_evidence:[科目及人员归属原件source],opening_balance:"0.00",opening_evidence:[前期余额或新户无余额依据source],invoices:[{source:本轮invoices中的完整source,voucher:"费用及挂账凭证号",ownership_evidence:[确认报销人的原件source]}],payments:[{source:本轮bank中的完整source,voucher:"付款冲往来凭证号",ownership_evidence:[报销款人员归属原件source]}],closing_balance:"-26.00"}。
余额统一贷方正、借方负，两位小数字符串；程序用delivery.opening同科目credit-debit复算期初、逐笔发票gross及银行expense/income复算发生额，与effective_entries(修订后的分录)该科目全部发生额核对。当月已记个人费用票据逐票列invoices；前期已记票据不再列当月发生额。普通挂账允许同一凭证内同时确认费用和付款，须保留其他应付款借贷两侧，不净额吞明细。红票/退款保留原符号和来源；一张票只能归属一个人一次。
待分配结构：{id:"UI-票号",source:本轮invoices中的完整source,finding_id:"人员归属待确认事项"}。该finding保留票据原件，request精确问报销人，可用decision.options=[]及unavailable_reason解释等待归属；无凭证可关联时affected_vouchers=[]。不得把待分配票据写入任何猜测个人的生效分录。原账已经存在与之冲突的费用时先保留原账和具体阻断，不能以“待分配”掩盖已记费用。
收到真实人工归属说明后，invoices/payments项可增加ownership_answer_ids:[实际回应id]；须关联该票据原件或当前凭证，ownership_evidence可为空但票据/付款source仍须真实。资料齐全、暂无法判断或混合多人组的单纯选票不能确认报销人；独立审查须查回应是否明确了“这张票/款属于这个人”，不能仅因引用了回答就放行。
6. 差旅政策应用仍逐笔覆盖；有本规则校验通过的个人报销挂账/付款，可不提供MATCHED逐笔票款关联。不把正常个人报销往来余额列为AMOUNT_GAP、INVOICE_MISSING、EMPLOYEE_SETTLEMENT或人为新造CANDIDATE关联。实际重复、人员冲突、无据费用、补贴和借款核销仍保留具体人工门禁；其他业务沿用原票款匹配规则。原账改成有据个人往来后，同步改写旧票款问题：已有invoice_matching候选票全部明确分配或进入待分配清单；不得继续用CANDIDATE/MISSING/AMOUNT_GAP问题阻断已纳入本规则的付款。真正未解决的科目、人员、借款或费用冲突另列有据问题，不能把旧版逐笔配票问题原样保留。
7. report用简单中文按个人列“期初、本期票据、本期已付、期末公司还欠/已付待抵扣”，另列待分配票据，保留本轮原账修订对照和期间。独立审查返回reviewed_employee_reimbursements:[以上两个清单全部id]，逐项从原件核对人员、科目、期初、重复票、费用/税额/银行及往来方向、余额和后续结转影响；检查是否漏列或仍多问逐笔配平。只凭字段/算术通过不代表业务通过，不得将候选余额作为正式余额。
'''


def reimbursements_enabled(context):
    profile = context.get('bookkeeping_profile') or {}
    return profile.get('id') == 'AGENCY_SIMPLE' and 'employee_reimbursements' in profile.get('rule_ids', [])


def reimbursement_errors(delivery, context, anchor=None, tables=None, pdf=None):
    accounts = delivery.get('employee_reimbursements', [])
    pending = delivery.get('unassigned_reimbursement_invoices', [])
    if not reimbursements_enabled(context):
        return ['当前记账方式未启用个人报销往来规则'] if accounts or pending else []
    if not all(isinstance(delivery.get(k), list) for k in ('employee_reimbursements', 'unassigned_reimbursement_invoices')):
        return ['简易代账须交付个人报销往来及待分配票据清单；无业务时为[]']
    errors = []
    banks = {source_key(b['source']): b for b in delivery.get('bank', [])}
    invoices = {source_key(i['source']): i for i in delivery.get('invoices', [])}
    findings = {f['id']: f for f in delivery.get('findings', [])}
    answers = {a['answer_id']: a for a in context.get('statements', []) if a.get('answer_id')}
    groups = effective_entries(delivery)
    ids, persons, codes, used_invoices, used_payments, invoice_numbers = set(), set(), set(), set(), set(), set()

    def money(value):
        if not isinstance(value, str) or not re.fullmatch(r'-?\d+\.\d{2}', value):
            raise ValueError('往来金额须为有方向的两位小数字符串')
        return Decimal(value)

    def evidence(refs):
        if not isinstance(refs, list) or not refs or any(not isinstance(r, dict) or not r.get('source_id') or (anchor and not anchor(r)) for r in refs):
            raise ValueError('人员归属、科目和期初须有本轮原件定位')

    def original_values(ref):
        rows = (tables or {}).get(ref.get("source_id"), {}).get(ref.get("sheet"), [])
        return next((r["values"] for r in rows if r["row"] == ref.get("row")), [])

    def original_amount(ref, value):
        if tables is None or ref.get('source_id') not in tables:
            return True  # PDF amounts also receive independent visual review.
        rows = tables[ref['source_id']].get(ref.get('sheet'), [])
        values = next((r['values'] for r in rows if r['row'] == ref.get('row')), [])
        return any(Decimal(str(v).strip()) == value for v in values
                   if not isinstance(v, bool) and re.fullmatch(r'-?\d+(?:\.\d+)?', str(v).strip()))

    def unique(item):
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip() or item['id'] in ids:
            raise ValueError('报销往来及待分配编号必须唯一')
        ids.add(item['id'])

    def ownership(item, key, voucher):
        refs, aids = item.get('ownership_evidence', []), item.get('ownership_answer_ids', [])
        if not isinstance(refs, list) or not isinstance(aids, list) or len(aids) != len(set(aids)):
            raise ValueError('人员归属须提供原件或实际回应编号')
        if refs:
            evidence(refs)
        for aid in aids:
            answer = answers.get(aid, {})
            related = [*answer.get('evidence', []), *[i['source'] for i in answer.get('invoice_selection', {}).get('invoices', [])]]
            if (answer.get('kind') not in {'FREE_TEXT', 'REVIEW_SELECTION', 'INVOICE_MATCH_SELECTION'}
                    or answer.get('option', {}).get('kind') == 'DEFER'
                    or (answer.get('kind') == 'INVOICE_MATCH_SELECTION' and not answer.get('note', '').strip())
                    or not (answer.get('text', '').strip() or answer.get('note', '').strip() or answer.get('option', {}).get('label'))
                    or (key not in {source_key(r) for r in related} and voucher not in answer.get('affected_vouchers', []))):
                raise ValueError('归属确认必须来自同笔真实回应，不能以资料齐全或多人组选票代替')
        if not refs and not aids:
            raise ValueError('缺少人员归属依据')
        return refs, aids

    for account in accounts:
        try:
            unique(account)
            person, code = account['person'], account['account_code']
            if not all(isinstance(v, str) and v.strip() for v in (person, code, account.get('account_name'))):
                raise ValueError('须明确个人和本企业其他应付款明细科目')
            if person in persons or code in codes:
                raise ValueError('一人一个报销往来明细，不同人不能共用或相互抵扣')
            persons.add(person); codes.add(code)
            evidence(account.get('account_evidence'))
            if tables is not None:
                cited_rows = [original_values(r) for r in account['account_evidence']
                              if r.get('source_id') in tables]
                if cited_rows and not any(
                    any(str(v).strip() == code for v in row)
                    and any(person in str(v) for v in row) for row in cited_rows
                ):
                    raise ValueError('个人科目编码及姓名须出现在所引原件中，不能用费用或总科目冒充个人明细')
            opening_rows = [r for r in delivery.get('opening', []) if r.get('code') == code]
            if any(not original_amount(r['source'], money(r[side])) for r in opening_rows for side in ('debit','credit') if money(r[side])):
                raise ValueError('个人期初金额与原件不一致')
            opening = sum((money(r['credit']) - money(r['debit']) for r in opening_rows), Decimal(0))
            if money(account['opening_balance']) != opening:
                raise ValueError('个人期初须等于本轮历史余额，不得把前月草稿或付款差额作为期初')
            # Even a zero opening requires evidence that the account is new/settled.
            evidence(account.get('opening_evidence'))
            expected = defaultdict(lambda: [Decimal(0), Decimal(0)])
            for field, records, used in (('invoices', invoices, used_invoices), ('payments', banks, used_payments)):
                if not isinstance(account.get(field), list):
                    raise ValueError('须分别交付个人票据及付款明细')
                for item in account[field]:
                    key = source_key(item['source']); number = item['voucher']
                    if key not in records or key in used or number not in groups:
                        raise ValueError('报销票款须引用本轮真实资料及凭证，不能跨人重复使用')
                    if anchor and not anchor(item['source']):
                        raise ValueError('票款来源不属于本轮原件')
                    used.add(key); owner_refs, owner_answers = ownership(item, key, number)
                    record = records[key]
                    if field == 'invoices':
                        number_key = str(record.get('number', '')).strip()
                        if not number_key or number_key in invoice_numbers:
                            raise ValueError('报销发票号码必须存在且不得重复确认费用')
                        invoice_numbers.add(number_key)
                        gross = money(record['gross'])
                        if record.get('kind') != '进项' or gross != money(record['net']) + money(record['tax']):
                            raise ValueError('报销使用发票价税合计，不能用净额或税额凑差额')
                        if any(not original_amount(item['source'], money(record[field])) for field in ('net','tax') if money(record[field])):
                            raise ValueError('报销票据金额与原件不一致')
                        expected[number][1 if gross >= 0 else 0] += abs(gross)
                    else:
                        debit, credit = money(record['expense']), money(record['income'])
                        if min(debit, credit) < 0 or (debit > 0) == (credit > 0):
                            raise ValueError('每笔付款或退款须保留真实方向，不得净额抵消')
                        if not original_amount(item['source'], debit or credit):
                            raise ValueError('报销付款金额与原件不一致')
                        if pdf is not None and item['source']['source_id'] not in (tables or {}):
                            observed = (pdf.get(item['source']['source_id'], {}).get('ocr') or {}).get('statement', {}).get('rows', [])
                            if observed:
                                raw = [r for r in observed if str(r['sequence']) == str(record.get('sequence'))]
                                if len(raw) != 1 or Decimal(str(raw[0]['debit'])) != debit or Decimal(str(raw[0]['credit'])) != credit:
                                    raise ValueError('报销付款未通过银行原件OCR金额核对')
                        if record.get('counterparty') != person and not owner_answers and not any(source_key(r) != key for r in owner_refs):
                            raise ValueError('收款人不同须有明确代收付归属依据，不能把银行收款人换成其他员工')
                        expected[number][0] += debit; expected[number][1] += credit
            if not expected:
                raise ValueError('个人往来清单须关联本期实际票据或付款')
            actual = {}
            for number, rows in groups.items():
                lines = [e for e in rows if e['code'] == code]
                if lines:
                    actual[number] = [sum((money(e['debit']) for e in lines), Decimal(0)),
                                      sum((money(e['credit']) for e in lines), Decimal(0))]
            if actual != dict(expected):
                raise ValueError('个人往来分录与票据/付款不一致；须分别挂账和冲减，不能直接费用化付款或跨人核销')
            closing = opening + sum((cr - dr for dr, cr in expected.values()), Decimal(0))
            if money(account['closing_balance']) != closing:
                raise ValueError('期末须为期初＋票据确认－付款；贷方正数表示欠个人，借方负数表示待抵扣')
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            errors.append('个人报销往来无效：' + str(exc))
    for item in pending:
        try:
            unique(item)
            key = source_key(item['source'])
            if key not in invoices or key in used_invoices or (anchor and not anchor(item['source'])):
                raise ValueError('待分配票据不能已经分配给个人或重复列示')
            number = str(invoices[key].get('number', '')).strip()
            if not number or number in invoice_numbers:
                raise ValueError('同一张票不能既按个人记账又待分配，或重复列示')
            invoice_numbers.add(number)
            used_invoices.add(key)
            finding = findings.get(item.get('finding_id'), {})
            if not finding.get('needs_user') or key not in {source_key(r) for r in finding.get('evidence', [])}:
                raise ValueError('待分配票据须保留有原件依据的人员归属问题')
            if any(source_key(e['source']) == key for rows in groups.values() for e in rows):
                raise ValueError('归属不明票据不能在待分配同时按猜测人员入账')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append('待分配报销票据无效：' + str(exc))
    # Existing matching findings cannot retain the obsolete per-payment gate.
    for finding in findings.values():
        matching = finding.get('invoice_matching') or {}
        payment_keys = {source_key(r) for r in matching.get('payment_sources', [])}
        if not payment_keys.intersection(used_payments):
            continue
        for ref in matching.get('candidate_invoice_sources', []):
            if source_key(ref) not in used_invoices:
                errors.append('个人报销候选票据须明确分配或列入待分配清单，不能遗漏归属问题')
        if matching.get('state') in {'CANDIDATE', 'MISSING', 'AMOUNT_DIFFERENCE'} and finding.get('blocks_confirmation', True):
            errors.append('已按个人往来处理的付款不能继续被逐笔配票或缺票差额问题阻断；实际冲突另列具体问题')
    return errors


def reimbursement_reviewed(delivery, review, context):
    if not reimbursements_enabled(context):
        return not delivery.get('employee_reimbursements') and not delivery.get('unassigned_reimbursement_invoices')
    expected = [r['id'] for field in ('employee_reimbursements', 'unassigned_reimbursement_invoices') for r in delivery.get(field, [])]
    actual = review.get('reviewed_employee_reimbursements')
    return isinstance(actual, list) and all(isinstance(i, str) for i in actual) and len(actual) == len(set(actual)) and set(actual) == set(expected)


def reimbursement_covers_voucher(delivery, context, voucher):
    if not reimbursements_enabled(context) or reimbursement_errors(delivery, context):
        return False
    return any(item['voucher'] == voucher for account in delivery['employee_reimbursements']
               for field in ('invoices', 'payments') for item in account[field])
