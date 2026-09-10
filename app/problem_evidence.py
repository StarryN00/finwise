"""Bounded, read-only evidence review of fully reversed blue invoices."""
from collections import Counter
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import re

from app.invoice_checks import AMOUNT_ISSUE, BLUE_LABEL, red_invoice_evidence


RULE_VERSION = 'blue-invoice-cancellation-v2'
STATUS_ISSUE = 'invoice_status：发票状态须人工核对'
MONEY_FIELDS = ('net_amount', 'tax', 'invoice_total')
PARTY_FIELDS = ('seller_tax_id', 'seller_name', 'buyer_tax_id', 'buyer_name')
INVOICE_TYPES = {'INVOICE', 'SALES_INVOICE'}
# Explicit values supported by this bounded rule; no currency alias inference.
CURRENCIES = {'CNY', 'USD', 'EUR', 'HKD', 'JPY', 'GBP', 'CHF', 'CAD', 'AUD', 'SGD', '人民币'}
BOUNDARY = '仅复核全额红冲证据，不代表税务查验、人工核实、账务可用或问题已解除。'


def _money(value):
    # Reject floats, non-finite values, excessive precision and fractional cents.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Invalid amount')
    if not re.fullmatch(r'-?\d{1,24}(?:\.\d{1,2})?', str(value)):
        raise ValueError('Invalid amount')
    return Decimal(value)


def _raw_money(value):
    # Excel numeric cells may be floats; compare their decimal text, never round.
    if isinstance(value, float):
        value = str(value)
    if isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r'-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?', value):
            value = value.replace(',', '')
    return _money(value)


def _amount_source_codes(data, amounts):
    codes = set()
    original = data.get('original_value') or {}
    for field, amount in zip(MONEY_FIELDS, amounts):
        source = (data.get('field_sources') or {}).get(field) or {}
        if source.get('original_value') is None or not source.get('region'):
            codes.add('AMOUNT_SOURCE_MISSING')
            continue
        try:
            if _raw_money(source['original_value']) != amount:
                codes.add('AMOUNT_SOURCE_MISMATCH')
        except (ValueError, InvalidOperation):
            codes.add('AMOUNT_SOURCE_INVALID')
        # Cross-check the preserved row array when its sheet/row are available.
        if original.get('sheet') is None or original.get('row') is None:
            continue
        cell = re.fullmatch(r'(.+)!([A-Z]+)([1-9]\d*)', source['region'])
        if (not cell or cell[1] != original['sheet'] or int(cell[3]) != original['row']
                or source.get('row', original['row']) != original['row']):
            codes.add('AMOUNT_SOURCE_ANCHOR_MISMATCH')
            continue
        column = 0
        for letter in cell[2]:
            column = column * 26 + ord(letter) - ord('A') + 1
        row = original.get('values')
        if not isinstance(row, list) or column > len(row):
            codes.add('AMOUNT_SOURCE_MISSING')
            continue
        try:
            if _raw_money(row[column-1]) != amount:
                codes.add('AMOUNT_SOURCE_MISMATCH')
        except (ValueError, InvalidOperation):
            codes.add('AMOUNT_SOURCE_INVALID')
    return codes


def _mentions_blue(data, number):
    """Include malformed explicit links as blockers, never as passing evidence."""
    original = data.get('original_value') or {}
    values = original.get('values') or []
    for i, header in enumerate(original.get('headers') or []):
        label = str(header or '').strip()
        value = values[i] if i < len(values) else None
        if label == BLUE_LABEL and number in str(value):
            return True
        if label in {'备注', '发票备注'} and isinstance(value, str) and BLUE_LABEL in value and number in value:
            return True
    return False


def _source_text(data, field):
    value = (data.get('normalized_value') or {}).get(field)
    source = (data.get('field_sources') or {}).get(field) or {}
    raw = source.get('original_value')
    if (not isinstance(value, str) or not value.strip() or not isinstance(raw, str)
            or raw.strip() != value or not source.get('region')
            or source.get('derivation') or (data.get('normalized_value') or {}).get(field + '_derivation')
            or source.get('status') in {'INVALID', 'AMBIGUOUS', 'INFERRED', 'DEFAULT'}):
        return None
    return value


def check_problem_evidence(scope, artifacts, facts, source_validity):
    """Return {blue_fact_id: check}; no I/O, replay, commands or mutation.

    Inputs are current ObjectStore objects, including all candidate invoices (not
    only the current UI page). Scope is a Scope model or its exact six-key dict.
    source_validity is {artifact_id: bool}: the caller must freshly verify the
    supplied artifact version/hash against the retained original. Missing is not
    valid. The caller must also supply trusted current facts/replayed extraction,
    not user-submitted values; this pure function does not authenticate extraction.
    PASS is a review result only. Integration owns all workflow decisions.
    """
    from app.ontology.contracts import Scope

    scope = Scope.model_validate(scope).model_dump()
    artifacts = list(artifacts)
    # Re-parsing retains replaced facts; they are history, not duplicate invoices.
    # Live cross-period/foreign rows remain candidates and must fail isolation.
    facts = [fact for fact in facts if fact.get('status') != 'SUPERSEDED']
    aa = {a['object_id']: a for a in artifacts}
    artifact_counts = Counter(a['object_id'] for a in artifacts)
    fact_counts = Counter(f['object_id'] for f in facts)
    numbers = Counter((f.get('data') or {}).get('normalized_value', {}).get('invoice_no')
                      for f in facts if (f.get('data') or {}).get('record_type') in INVOICE_TYPES)
    result = {}
    for blue in facts:
        bd = blue.get('data') or {}
        bn = bd.get('normalized_value') or {}
        if bd.get('record_type') not in INVOICE_TYPES or bn.get('invoice_status') != '已红冲-全额':
            continue
        codes, links, refs = set(), [], []
        number = bn.get('invoice_no')
        if not isinstance(number, str) or not re.fullmatch(r'\d{20}', number):
            codes.add('BLUE_INVOICE_NUMBER_INVALID')
            linked = []
        else:
            linked = [f for f in facts if f is not blue and _mentions_blue(f.get('data') or {}, number)]
        if not linked:
            codes.add('RED_EVIDENCE_MISSING')
        members = [blue, *sorted(linked, key=lambda f: (f['object_id'], f['version']))]
        amounts, currencies, parties, source_rows = [], [], [], []
        for index, fact in enumerate(members):
            fid, d = fact['object_id'], fact.get('data') or {}
            n = d.get('normalized_value') or {}
            artifact = aa.get(d.get('source_artifact_id'))
            ad = artifact.get('data', {}) if artifact else {}
            aid = d.get('source_artifact_id')
            anchor = d.get('source_anchor') or {}
            if fact_counts[fid] != 1 or numbers[n.get('invoice_no')] != 1:
                codes.add('DUPLICATE_INVOICE')
            if fact.get('scope') != scope or artifact and artifact.get('scope') != scope:
                codes.add('SCOPE_MISMATCH')
            if d.get('record_type') != bd.get('record_type'):
                codes.add('DIRECTION_MISMATCH')
            if fact.get('status') not in {'PARSED', 'NEEDS_REVIEW'}:
                codes.add('FACT_NOT_CURRENT')
            try:
                invoice_period = date.fromisoformat(n.get('invoice_date', '')).isoformat()[:7]
            except (ValueError, TypeError):
                invoice_period = None
            if (n.get('period') != scope['accounting_period_id'] or invoice_period != scope['accounting_period_id']
                    or d.get('period_check') != 'PASS' or ad.get('observed_period') != scope['accounting_period_id']):
                codes.add('PERIOD_MISMATCH')
            if not artifact:
                codes.add('SOURCE_MISSING')
            elif (artifact_counts[aid] != 1 or artifact.get('status') != 'ACTIVE'
                  or ad.get('parse_status') not in {'PARSED', 'PARSED_WITH_ISSUES'}
                  or fid not in ad.get('parsed_fact_ids', [])
                  or d.get('source_artifact_version') != artifact['version']):
                codes.add('SOURCE_NOT_CURRENT')
            if source_validity.get(aid) is not True or not re.fullmatch(r'[0-9a-fA-F]{64}', str(ad.get('sha256', ''))):
                codes.add('SOURCE_INVALID')
            if not anchor.get('region') or not (d.get('field_sources') or {}):
                codes.add('SOURCE_ANCHOR_MISSING')
            if (d.get('original_value') or {}).get('formulas'):
                codes.add('FORMULA_UNVERIFIED')
            if any(s.get('status') in {'INVALID', 'AMBIGUOUS'} for s in (d.get('field_sources') or {}).values()):
                codes.add('OTHER_SOURCE_ISSUES')
            allowed = {STATUS_ISSUE} if index == 0 else {AMOUNT_ISSUE}
            if not isinstance(d.get('extraction_issues'), list) or set(d['extraction_issues']) - allowed:
                codes.add('OTHER_EXTRACTION_ISSUES')
            valid_amount = False
            try:
                with localcontext() as context:
                    context.prec = 64
                    net, tax, total = [_money(n.get(key)) for key in MONEY_FIELDS]
                    if total != net + tax or (index == 0 and (net <= 0 or tax < 0 or total <= 0)):
                        codes.add('AMOUNT_INVALID')
                    amounts.append((net, tax, total))
                    valid_amount = True
            except (ValueError, InvalidOperation):
                codes.add('AMOUNT_INVALID')
            if any(not ((d.get('field_sources') or {}).get(key) or {}).get('region') for key in MONEY_FIELDS):
                codes.add('AMOUNT_SOURCE_MISSING')
            if valid_amount:
                codes.update(_amount_source_codes(d, amounts[-1]))
            party = tuple(_source_text(d, field) for field in PARTY_FIELDS)
            if None in party:
                codes.add('PARTY_SOURCE_MISSING')
            parties.append(party)
            currency = _source_text(d, 'currency')
            if currency is None:
                codes.add('CURRENCY_SOURCE_MISSING')
            elif currency not in CURRENCIES:
                codes.add('CURRENCY_UNSUPPORTED')
            currencies.append(currency)
            if _source_text(d, 'invoice_no') is None or _source_text(d, 'invoice_status') is None:
                codes.add('INVOICE_SOURCE_MISSING')
            if index:
                with localcontext() as context:
                    context.prec = 64
                    evidence = red_invoice_evidence(d) if valid_amount else None
                if not evidence or evidence['blue_invoice_no'] != number:
                    codes.add('RED_EVIDENCE_INVALID')
                else:
                    links.append({'fact_id': fid, **evidence})
                    original = d.get('original_value') or {}
                    if not original.get('sheet') or not original.get('row') or original['row'] != anchor.get('row'):
                        codes.add('LINK_SOURCE_ANCHOR_MISSING')
            regions = sorted({s['region'] for s in (d.get('field_sources') or {}).values() if s.get('region')})
            refs.append(dict(fact_id=fid, fact_version=fact['version'], artifact_id=aid,
                             artifact_version=artifact['version'] if artifact else None,
                             sha256=ad.get('sha256'), source_anchor=deepcopy(anchor), source_regions=regions))
            source_rows.append((ad.get('sha256'), anchor.get('region')))
        if len(set(source_rows)) != len(source_rows):
            codes.add('DUPLICATE_SOURCE_ROW')
        if len(set(parties)) > 1:
            codes.add('PARTY_MISMATCH')
        if len(set(currencies)) > 1:
            codes.add('CURRENCY_MISMATCH')
        if len(amounts) == len(members):
            with localcontext() as context:
                context.prec = 64
                if any(sum((row[i] for row in amounts), Decimal(0)) != 0 for i in range(3)):
                    codes.add('AMOUNT_CANCELLATION_MISMATCH')
        result[blue['object_id']] = dict(rule_version=RULE_VERSION, status='BLOCKED' if codes else 'PASS',
                                        codes=sorted(codes), refs=refs, links=links, boundary=BOUNDARY)
    return result


def _relationship_diagnostics(fid, check, visible_facts, messages, hidden):
    """Local display only; balances are arithmetic, never workflow permission."""
    def money_text(value):
        try:
            amount = _money(value)
            return format(amount if amount else Decimal(0), '.2f')
        except (ValueError, InvalidOperation):
            return None

    relationships = []
    for ref in check['refs']:
        fact = next((f for f in visible_facts.get(ref['fact_id'], []) if f['version'] == ref['fact_version']), None)
        if fact is None:
            continue
        values = fact['data'].get('normalized_value') or {}
        relationships.append(dict(fact_id=ref['fact_id'], invoice_no=values.get('invoice_no'),
            role='BLUE' if ref['fact_id'] == fid else 'RED',
            amount=money_text(values.get('net_amount')), tax_amount=money_text(values.get('tax')),
            invoice_total=money_text(values.get('invoice_total')), region=(ref.get('source_anchor') or {}).get('region'),
            artifact_id=ref['artifact_id'], fact_version=ref['fact_version'], artifact_version=ref['artifact_version']))
    blue = next((r for r in relationships if r['role'] == 'BLUE'), {})
    reds = [r for r in relationships if r['role'] == 'RED']
    codes = set(check['codes'])
    ambiguous = bool(codes & {'DUPLICATE_INVOICE', 'DUPLICATE_SOURCE_ROW'})
    balances = []
    for field, name, label in [('net_amount', 'amount', '不含税金额'), ('tax', 'tax_amount', '税额'),
                               ('invoice_total', 'invoice_total', '价税合计')]:
        blue_value, red_value, net = blue.get(name), None, None
        if reds and not hidden and not ambiguous and all(r[name] is not None for r in reds):
            with localcontext() as context:
                context.prec = 64
                red_value = format(sum((Decimal(r[name]) for r in reds), Decimal(0)), '.2f')
                if blue_value is not None:
                    net = format(Decimal(blue_value) + Decimal(red_value), '.2f')
        balances.append(dict(field=field, label=label, blue=blue_value, red=red_value, net=net,
                             status='UNKNOWN' if net is None else 'PASS' if Decimal(net) == 0 else 'MISMATCH'))

    conflicts = {'DUPLICATE_INVOICE', 'DUPLICATE_SOURCE_ROW', 'SCOPE_MISMATCH', 'DIRECTION_MISMATCH',
                 'PERIOD_MISMATCH', 'AMOUNT_SOURCE_MISMATCH', 'AMOUNT_SOURCE_ANCHOR_MISMATCH',
                 'AMOUNT_CANCELLATION_MISMATCH', 'PARTY_MISMATCH', 'CURRENCY_MISMATCH'}
    # Missing parties/currency or missing red invoices can also yield mismatch
    # codes in the existing validator. Do not present those as proven conflicts.
    if 'PARTY_SOURCE_MISSING' in codes:
        conflicts.discard('PARTY_MISMATCH')
    if codes & {'CURRENCY_SOURCE_MISSING', 'CURRENCY_UNSUPPORTED'}:
        conflicts.discard('CURRENCY_MISMATCH')
    if any(b['status'] == 'UNKNOWN' for b in balances):
        conflicts.discard('AMOUNT_CANCELLATION_MISMATCH')
    steps = []
    for code in check['codes']:
        conflict = code in conflicts
        steps.append(dict(code=code, label=messages[code], status='BLOCKED' if conflict else 'UNKNOWN',
                          message=messages[code], nature='EVIDENCE_CONFLICT' if conflict else 'SYSTEM_EVIDENCE_INCOMPLETE',
                          nature_label='证据存在矛盾，仍需核对原因' if conflict else '系统证据不完整，不能认定客户缺资料'))
    groups = [
        ('EXPLICIT_RED_LINKS', '显式红冲关联', {'BLUE_INVOICE_NUMBER_INVALID', 'RED_EVIDENCE_MISSING', 'RED_EVIDENCE_INVALID', 'LINK_SOURCE_ANCHOR_MISSING'}),
        ('SCOPE_DIRECTION_PERIOD', '范围、方向与期间', {'SCOPE_MISMATCH', 'DIRECTION_MISMATCH', 'PERIOD_MISMATCH'}),
        ('CURRENT_SOURCE', '当前原件及金额来源', {'SOURCE_MISSING', 'SOURCE_NOT_CURRENT', 'SOURCE_INVALID', 'SOURCE_ANCHOR_MISSING',
            'FACT_NOT_CURRENT', 'DUPLICATE_INVOICE', 'DUPLICATE_SOURCE_ROW', 'FORMULA_UNVERIFIED', 'OTHER_SOURCE_ISSUES',
            'OTHER_EXTRACTION_ISSUES', 'INVOICE_SOURCE_MISSING', 'AMOUNT_SOURCE_MISSING', 'AMOUNT_SOURCE_INVALID',
            'AMOUNT_SOURCE_MISMATCH', 'AMOUNT_SOURCE_ANCHOR_MISMATCH'}),
        ('PARTIES', '购销双方身份', {'PARTY_SOURCE_MISSING', 'PARTY_MISMATCH'}),
        ('CURRENCY', '明确币种来源', {'CURRENCY_SOURCE_MISSING', 'CURRENCY_UNSUPPORTED', 'CURRENCY_MISMATCH'}),
        ('AMOUNT_BALANCE', '三项金额抵销', {'AMOUNT_INVALID', 'AMOUNT_CANCELLATION_MISMATCH'}),
    ]
    for code, label, blockers in groups:
        if codes & blockers:
            continue
        known = bool(reds) and not hidden and not ambiguous
        if code == 'AMOUNT_BALANCE':
            known = known and all(b['status'] == 'PASS' for b in balances)
        steps.append(dict(code=code, label=label, status='PASS' if known else 'UNKNOWN',
                          message=(label + '本项检查通过；不代表整体通过或账务可用。') if known else
                          '可核对的同范围关联记录不足，本项尚不能确认。',
                          nature='VERIFIED' if known else 'SYSTEM_EVIDENCE_INCOMPLETE',
                          nature_label='分项通过' if known else '系统证据不完整'))
    return dict(relationships=relationships, balances=balances, check_steps=steps)


def full_red_checks(scope, artifacts, facts, valid_sources_dict):
    """Workflow-facing adapter; source validity has the same contract as above.

    relationships includes same-scope candidate links, not only validated reds.
    Its amount is net_amount; all money display values are exact strings or None.
    balances PASS means arithmetic cancellation only; UNKNOWN never substitutes
    zero. check_steps classifies evidence, not business fault or customer duty.
    These display fields contain local financial data: do not send to a model.
    Only the pre-existing top-level status/codes decide the validator outcome.
    """
    messages = {
        'BLUE_INVOICE_NUMBER_INVALID': '蓝字发票号码缺失或格式无效',
        'RED_EVIDENCE_MISSING': '未找到原件明确关联的红字发票及确认单依据',
        'RED_EVIDENCE_INVALID': '关联红字发票的原件声明、状态或金额不满足核对条件',
        'DUPLICATE_INVOICE': '存在重复发票号码或重复事实记录',
        'DUPLICATE_SOURCE_ROW': '存在重复来源行，不能重复计入抵销',
        'SCOPE_MISMATCH': '关联资料不在同一企业、账套或核定范围',
        'DIRECTION_MISMATCH': '蓝红发票的进项或销项方向不同',
        'FACT_NOT_CURRENT': '关联事实已失效或不属于当前可核对记录',
        'PERIOD_MISMATCH': '关联日期、期间或原件不属于当前办理期间',
        'SOURCE_MISSING': '未提供关联原件',
        'SOURCE_NOT_CURRENT': '原件状态、解析成员或版本不再匹配',
        'SOURCE_INVALID': '原件哈希未验证通过',
        'SOURCE_ANCHOR_MISSING': '缺少可核对的来源定位',
        'LINK_SOURCE_ANCHOR_MISSING': '红冲关联声明缺少有效来源定位',
        'FORMULA_UNVERIFIED': '原件含尚未核实的公式',
        'OTHER_SOURCE_ISSUES': '来源字段还有无效或含义不明的问题',
        'OTHER_EXTRACTION_ISSUES': '仍有其他提取问题或检查结果缺失',
        'AMOUNT_INVALID': '金额无效、正负号或价税关系不一致',
        'AMOUNT_SOURCE_MISSING': '金额缺少原件字段定位',
        'AMOUNT_SOURCE_MISMATCH': '提取金额与保留的原始单元格金额不一致，不能据此撤回提醒',
        'AMOUNT_SOURCE_INVALID': '保留的原始金额无法精确核对，需检查系统提取结果',
        'AMOUNT_SOURCE_ANCHOR_MISMATCH': '金额来源与保留原始行的工作表或行号不一致',
        'AMOUNT_CANCELLATION_MISMATCH': '净额、税额和价税合计未分别精确抵销',
        'PARTY_SOURCE_MISSING': '购销双方名称或税号缺少明确原件来源',
        'PARTY_MISMATCH': '蓝红发票的购销双方名称或税号不一致',
        'CURRENCY_SOURCE_MISSING': '当前提取结果缺少可核验的币种来源，尚不能认定客户缺资料；不能默认人民币',
        'CURRENCY_UNSUPPORTED': '原件币种不在当前规则支持范围，保留人工核对',
        'CURRENCY_MISMATCH': '蓝红发票的明确币种不一致',
        'INVOICE_SOURCE_MISSING': '发票号码或状态缺少一致的原件来源',
    }
    from app.ontology.contracts import Scope

    scope_value = Scope.model_validate(scope).model_dump()
    artifacts, facts = list(artifacts), list(facts)
    checks = check_problem_evidence(scope, artifacts, facts, valid_sources_dict)
    visible_facts = {}
    for fact in facts:
        visible_facts.setdefault(fact['object_id'], []).append(fact)
    owned_ids = {fid for fid, rows in visible_facts.items() if all(f.get('scope') == scope_value for f in rows)}
    visible_facts = {fid: rows for fid, rows in visible_facts.items()
                     if all(f.get('scope') == scope_value and all(a.get('scope') == scope_value for a in artifacts
                            if a['object_id'] == f['data'].get('source_artifact_id')) for f in rows)}
    # Keep isolation failures, but never return another scope's identifiers, raw
    # values, source regions, or aggregates (including through legacy refs/links).
    checks = {fid: check for fid, check in checks.items() if fid in owned_ids}
    for fid, check in checks.items():
        codes = check['codes']
        hidden = any(ref['fact_id'] not in visible_facts for ref in check['refs'])
        check['refs'] = [ref for ref in check['refs'] if ref['fact_id'] in visible_facts]
        check['links'] = [link for link in check['links'] if link['fact_id'] in visible_facts]
        refs = deepcopy(check['refs'])
        for ref in refs:
            linked_regions = [region for link in check['links'] if link['fact_id'] == ref['fact_id']
                              for region in link['source_regions']]
            ref['source_regions'] = sorted(set(ref['source_regions'] + linked_regions))
        check.update(fact_id=fid, code=codes[0] if codes else 'FULL_RED_OFFSET',
                     message='；'.join(messages[code] for code in codes) if codes else
                     '同范围、本期有效来源的蓝红发票已逐项精确抵销，双方身份及明确币种一致。',
                     evidence_refs=refs)
        check.update(_relationship_diagnostics(fid, check, visible_facts, messages, hidden))
    return checks
