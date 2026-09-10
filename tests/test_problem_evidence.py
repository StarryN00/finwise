from copy import deepcopy
from decimal import localcontext

import pytest

from app.invoice_checks import AMOUNT_ISSUE, BLUE_LABEL, CONFIRM_LABEL
from app.problem_evidence import RULE_VERSION, STATUS_ISSUE, check_problem_evidence, full_red_checks


BLUE = '26322000000633306346'


def inputs(scope, splits=('-100.00',)):
    facts = []
    for i, net in enumerate(('100.00', *splits)):
        from decimal import Decimal
        tax = Decimal(net) * Decimal('0.13')
        values = dict(invoice_no=BLUE if i == 0 else str(26322000000625714620 + i),
                      invoice_status='已红冲-全额' if i == 0 else '正常', invoice_date='2026-03-01', period='2026-03',
                      net_amount=net, tax=str(tax.quantize(Decimal('0.01'))),
                      invoice_total=str((Decimal(net) + tax).quantize(Decimal('0.01'))),
                      seller_tax_id='seller-tax', seller_name='销方', buyer_tax_id='buyer-tax', buyer_name='购方', currency='CNY')
        original = dict(sheet='发票', row=i+2, headers=[BLUE_LABEL, CONFIRM_LABEL],
                        values=[BLUE, str(32058326011138350730+i)] if i else ['', ''], formulas={})
        data = dict(record_type='SALES_INVOICE', source_artifact_id='a', source_artifact_version=2,
                    source_anchor={'row': i+2, 'region': f'发票!A{i+2}:N{i+2}'}, normalized_value=values,
                    original_value=original, period_check='PASS', extraction_issues=[STATUS_ISSUE if i == 0 else AMOUNT_ISSUE],
                    field_sources={k: {'region': f'发票!C{i+2}', 'original_value': v} for k, v in values.items()})
        for column, field in zip(('C', 'D', 'E'), ('net_amount', 'tax', 'invoice_total')):
            original['headers'].append(field)
            original['values'].append(values[field])
            data['field_sources'][field]['region'] = f'发票!{column}{i+2}'
        facts.append(dict(object_id=f'f{i}', version=1, scope=deepcopy(scope), status='NEEDS_REVIEW', data=data))
    artifact = dict(object_id='a', version=2, scope=deepcopy(scope), status='ACTIVE',
                    data={'sha256': 'a'*64, 'observed_period': '2026-03', 'parse_status': 'PARSED_WITH_ISSUES',
                          'parsed_fact_ids': [f['object_id'] for f in facts]})
    return [artifact], facts, {'a': True}


def check(scope, args):
    return check_problem_evidence(scope, *args)['f0']


@pytest.mark.parametrize('splits', [('-100.00',), ('-40.00', '-60.00'), ('-20.00', '-30.00', '-50.00')])
def test_exact_single_and_multiple_explicit_reds_pass_without_mutation(scope, splits):
    args = inputs(scope, splits)
    before = deepcopy(args)
    result = check(scope, args)
    assert result['status'] == 'PASS' and result['codes'] == []
    assert len(result['refs']) == len(splits) + 1
    assert len(result['links']) == len(splits)
    assert result['links'][0]['source_regions'] == ['发票!A3', '发票!B3']
    assert result['refs'][0]['fact_version'] == 1
    assert result['refs'][0]['artifact_version'] == 2
    assert result['refs'][0]['sha256'] == 'a'*64
    assert args == before
    result['refs'][0]['source_anchor']['row'] = 900
    assert args == before
    with localcontext() as context:
        context.prec = 3
        assert check(scope, args)['status'] == 'PASS'


@pytest.mark.parametrize('change,code', [
    ('direction', 'DIRECTION_MISMATCH'), ('fact_scope', 'SCOPE_MISMATCH'), ('artifact_scope', 'SCOPE_MISMATCH'),
    ('period', 'PERIOD_MISMATCH'), ('date', 'PERIOD_MISMATCH'), ('period_check', 'PERIOD_MISMATCH'),
    ('artifact_period', 'PERIOD_MISMATCH'), ('hash', 'SOURCE_INVALID'), ('validity_missing', 'SOURCE_INVALID'),
    ('invalid_hash_text', 'SOURCE_INVALID'), ('archived', 'SOURCE_NOT_CURRENT'), ('stale_source', 'SOURCE_NOT_CURRENT'),
    ('unregistered_fact', 'SOURCE_NOT_CURRENT'), ('duplicate_fact', 'DUPLICATE_INVOICE'),
    ('duplicate_number', 'DUPLICATE_INVOICE'), ('duplicate_artifact', 'SOURCE_NOT_CURRENT'),
    ('duplicate_row', 'DUPLICATE_SOURCE_ROW'), ('party', 'PARTY_MISMATCH'),
    ('currency', 'CURRENCY_MISMATCH'), ('currency_missing', 'CURRENCY_SOURCE_MISSING'),
    ('currency_inferred', 'CURRENCY_SOURCE_MISSING'), ('party_missing', 'PARTY_SOURCE_MISSING'),
    ('other_issue', 'OTHER_EXTRACTION_ISSUES'), ('issues_missing', 'OTHER_EXTRACTION_ISSUES'),
    ('formula', 'FORMULA_UNVERIFIED'), ('fact_void', 'FACT_NOT_CURRENT'),
    ('link_missing', 'RED_EVIDENCE_INVALID'), ('malformed_link', 'RED_EVIDENCE_INVALID'),
    ('link_anchor', 'LINK_SOURCE_ANCHOR_MISSING'), ('amount_source', 'AMOUNT_SOURCE_MISSING'),
])
def test_conservative_blockers(scope, change, code):
    artifacts, facts, validity = inputs(scope)
    red, a = facts[1]['data'], artifacts[0]
    if change == 'direction': red['record_type'] = 'INVOICE'
    elif change == 'fact_scope': facts[1]['scope']['ledger_id'] = 'foreign'
    elif change == 'artifact_scope': a['scope']['tenant_id'] = 'foreign'
    elif change == 'period': red['normalized_value']['period'] = '2026-02'
    elif change == 'date': red['normalized_value']['invoice_date'] = '2026-02-01'
    elif change == 'period_check': red['period_check'] = 'FAIL'
    elif change == 'artifact_period': a['data']['observed_period'] = '2026-02'
    elif change == 'hash': validity['a'] = False
    elif change == 'validity_missing': validity.clear()
    elif change == 'invalid_hash_text': a['data']['sha256'] = ''
    elif change == 'archived': a['status'] = 'ARCHIVED'
    elif change == 'stale_source': red['source_artifact_version'] = 1
    elif change == 'unregistered_fact': a['data']['parsed_fact_ids'].remove('f1')
    elif change == 'duplicate_fact': facts.append(deepcopy(facts[1]))
    elif change == 'duplicate_number':
        duplicate = deepcopy(facts[1]); duplicate['object_id'] = 'duplicate'; facts.append(duplicate)
    elif change == 'duplicate_artifact': artifacts.append(deepcopy(a))
    elif change == 'duplicate_row': red['source_anchor'] = deepcopy(facts[0]['data']['source_anchor'])
    elif change in {'party', 'currency'}:
        field = 'seller_tax_id' if change == 'party' else 'currency'
        red['normalized_value'][field] = red['field_sources'][field]['original_value'] = 'DIFFERENT'
    elif change in {'currency_missing', 'party_missing'}:
        red['field_sources'].pop('currency' if change == 'currency_missing' else 'buyer_name')
    elif change == 'currency_inferred': red['field_sources']['currency']['derivation'] = '默认人民币'
    elif change == 'other_issue': red['extraction_issues'].append('tax：其他错误')
    elif change == 'issues_missing': red.pop('extraction_issues')
    elif change == 'formula': red['original_value']['formulas'] = {'C3': '=1'}
    elif change == 'fact_void': facts[1]['status'] = 'VOID'
    elif change == 'link_missing': red['original_value']['values'][1] = ''
    elif change == 'malformed_link': red['original_value']['values'][0] += 'X'
    elif change == 'link_anchor': red['original_value']['sheet'] = ''
    elif change == 'amount_source': red['field_sources'].pop('net_amount')
    result = check(scope, (artifacts, facts, validity))
    assert result['status'] == 'BLOCKED' and code in result['codes']


@pytest.mark.parametrize('amount', ['-99.00', '-100.01', 'NaN', 'Infinity', '-1e999999999', '-100.001', -100.0, None, True])
def test_mismatched_and_invalid_amounts_never_pass(scope, amount):
    args = inputs(scope)
    args[1][1]['data']['normalized_value']['net_amount'] = amount
    assert check(scope, args)['status'] == 'BLOCKED'


def test_total_cancellation_does_not_hide_net_and_tax_mismatch(scope):
    args = inputs(scope)
    args[1][1]['data']['normalized_value'].update(net_amount='-101.00', tax='-12.00')
    assert 'AMOUNT_CANCELLATION_MISMATCH' in check(scope, args)['codes']


def test_no_link_or_missing_source_cannot_be_replaced_with_amount_matching(scope):
    args = inputs(scope)
    args[1][1]['data']['original_value']['values'] = ['', '']
    assert 'RED_EVIDENCE_MISSING' in check(scope, args)['codes']
    args = inputs(scope)
    args[0].clear()
    assert 'SOURCE_MISSING' in check(scope, args)['codes']


def test_invalid_extra_linked_red_blocks_even_when_valid_red_cancels_total(scope):
    args = inputs(scope, ('-100.00', '-10.00'))
    args[1][2]['data']['normalized_value']['invoice_status'] = '作废'
    assert 'RED_EVIDENCE_INVALID' in check(scope, args)['codes']


def test_non_target_status_has_no_check_and_explicit_currency_is_required(scope):
    args = inputs(scope)
    for fact in args[1]:
        fact['data']['normalized_value'].pop('currency')
        fact['data']['field_sources'].pop('currency')
    assert check(scope, args)['codes'] == ['CURRENCY_SOURCE_MISSING']
    args[1][0]['data']['normalized_value']['invoice_status'] = '正常'
    assert check_problem_evidence(scope, *args) == {}


@pytest.mark.parametrize('field', ['tenant_id', 'organization_id', 'legal_entity_id', 'ledger_id', 'baseline_id', 'accounting_period_id'])
def test_every_scope_dimension_is_exact(scope, field):
    args = inputs(scope)
    args[1][1]['scope'][field] = 'foreign'
    assert 'SCOPE_MISMATCH' in check(scope, args)['codes']


@pytest.mark.parametrize('change,code', [('unknown', 'CURRENCY_UNSUPPORTED'), ('derived', 'CURRENCY_SOURCE_MISSING'),
                                        ('amount_source_invalid', 'OTHER_SOURCE_ISSUES'), ('blue_other_issue', 'OTHER_EXTRACTION_ISSUES')])
def test_unknown_currency_and_unreported_source_errors_block(scope, change, code):
    args = inputs(scope)
    for fact in args[1]:
        d = fact['data']
        if change == 'unknown':
            d['normalized_value']['currency'] = d['field_sources']['currency']['original_value'] = '未知'
        elif change == 'derived': d['normalized_value']['currency_derivation'] = '默认币种'
        elif change == 'amount_source_invalid': d['field_sources']['tax']['status'] = 'INVALID'
    if change == 'blue_other_issue': args[1][0]['data']['extraction_issues'].append('tax：无法核对')
    assert code in check(scope, args)['codes']


def test_partial_reversal_and_positive_red_never_pass(scope):
    args = inputs(scope, ('-40.00',))
    assert 'AMOUNT_CANCELLATION_MISMATCH' in check(scope, args)['codes']
    args = inputs(scope, ('100.00',))
    assert 'RED_EVIDENCE_INVALID' in check(scope, args)['codes']


def test_workflow_interface_and_missing_currency_message(scope):
    args = inputs(scope, ('-40.00', '-60.00'))
    before = deepcopy(args)
    result = full_red_checks(scope, *args)['f0']
    assert result['fact_id'] == 'f0' and result['status'] == 'PASS'
    assert result['rule_version'] == RULE_VERSION and result['code'] == 'FULL_RED_OFFSET'
    assert result['message'] and len(result['evidence_refs']) == 3
    assert '发票!B3' in result['evidence_refs'][1]['source_regions']
    assert args == before
    for fact in args[1]:
        fact['data']['normalized_value'].pop('currency')
        fact['data']['field_sources'].pop('currency')
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED' and result['code'] == 'CURRENCY_SOURCE_MISSING'
    assert '不能默认人民币' in result['message']
    assert '当前提取结果' in result['message'] and '尚不能认定客户缺资料' in result['message']


def test_superseded_facts_are_history_but_live_cross_period_links_still_block(scope):
    args = inputs(scope)
    history = deepcopy(args[1])
    for fact in history:
        fact['status'] = 'SUPERSEDED'
        fact['object_id'] += '-old'
    args[1].extend(history)
    result = full_red_checks(scope, *args)
    assert list(result) == ['f0'] and result['f0']['status'] == 'PASS'
    assert len(result['f0']['refs']) == 2
    before = deepcopy(args)
    assert full_red_checks(scope, *args) == result and args == before
    live = deepcopy(history[1])
    live['status'] = 'NEEDS_REVIEW'
    live['data']['normalized_value']['period'] = '2026-02'
    args[1].append(live)
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED'
    assert 'PERIOD_MISMATCH' in result['codes'] and 'DUPLICATE_INVOICE' in result['codes']


def test_workflow_codes_never_contain_source_text(scope):
    args = inputs(scope)
    args[1][1]['data']['extraction_issues'].append('私有原值：不可作为枚举')
    result = full_red_checks(scope, *args)['f0']
    assert result['code'] == 'OTHER_EXTRACTION_ISSUES'
    assert '私有原值' not in result['code'] and '私有原值' not in result['message']


@pytest.mark.parametrize('alter_field_source', [False, True])
def test_balanced_normalized_amount_forgery_is_blocked_by_both_raw_layers(scope, alter_field_source):
    from decimal import Decimal
    args = inputs(scope)
    for fact in args[1]:
        d = fact['data']
        for field in ('net_amount', 'tax', 'invoice_total'):
            d['normalized_value'][field] = str(Decimal(d['normalized_value'][field]) * 2)
            if alter_field_source:
                d['field_sources'][field]['original_value'] = d['normalized_value'][field]
    before = deepcopy(args)
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED' and 'AMOUNT_SOURCE_MISMATCH' in result['codes']
    assert args == before


@pytest.mark.parametrize('change,code', [('sheet', 'AMOUNT_SOURCE_ANCHOR_MISMATCH'),
    ('row', 'AMOUNT_SOURCE_ANCHOR_MISMATCH'), ('column', 'AMOUNT_SOURCE_MISSING'),
    ('raw_missing', 'AMOUNT_SOURCE_MISSING'), ('raw_formula', 'AMOUNT_SOURCE_INVALID'),
    ('raw_row_mismatch', 'AMOUNT_SOURCE_MISMATCH'), ('raw_fractional_cent', 'AMOUNT_SOURCE_INVALID')])
def test_amount_source_is_located_and_exact(scope, change, code):
    args = inputs(scope)
    d = args[1][1]['data']; source = d['field_sources']['tax']
    if change == 'sheet': source['region'] = '其他表!D3'
    elif change == 'row': source['region'] = '发票!D99'
    elif change == 'column': source['region'] = '发票!ZZ3'
    elif change == 'raw_missing': source.pop('original_value')
    elif change == 'raw_formula': source['original_value'] = '=-13'
    elif change == 'raw_row_mismatch': d['original_value']['values'][3] = '-26.00'
    elif change == 'raw_fractional_cent': source['original_value'] = '-13.001'
    assert code in full_red_checks(scope, *args)['f0']['codes']


def test_decimal_equivalent_excel_cells_do_not_cause_false_mismatch(scope):
    args = inputs(scope)
    for fact in args[1]:
        d = fact['data']
        for index, field in enumerate(('net_amount', 'tax', 'invoice_total'), 2):
            d['field_sources'][field]['original_value'] = float(d['normalized_value'][field])
            d['original_value']['values'][index] = float(d['normalized_value'][field])
    assert full_red_checks(scope, *args)['f0']['status'] == 'PASS'


def test_relationships_balances_and_steps_are_additive_exact_and_readonly(scope):
    args = inputs(scope, ('-40.00', '-60.00'))
    before = deepcopy(args)
    core = check_problem_evidence(scope, *args)['f0']
    with localcontext() as context:
        context.prec = 2
        result = full_red_checks(scope, *args)['f0']
    for key, value in core.items():
        assert result[key] == value
    assert RULE_VERSION == 'blue-invoice-cancellation-v2'
    assert result['relationships'] == [
        dict(fact_id='f0', invoice_no=BLUE, role='BLUE', amount='100.00', tax_amount='13.00', invoice_total='113.00',
             region='发票!A2:N2', artifact_id='a', fact_version=1, artifact_version=2),
        dict(fact_id='f1', invoice_no='26322000000625714621', role='RED', amount='-40.00', tax_amount='-5.20', invoice_total='-45.20',
             region='发票!A3:N3', artifact_id='a', fact_version=1, artifact_version=2),
        dict(fact_id='f2', invoice_no='26322000000625714622', role='RED', amount='-60.00', tax_amount='-7.80', invoice_total='-67.80',
             region='发票!A4:N4', artifact_id='a', fact_version=1, artifact_version=2),
    ]
    assert result['balances'] == [dict(field=f, label=l, blue=b, red=r, net='0.00', status='PASS')
        for f, l, b, r in [('net_amount', '不含税金额', '100.00', '-100.00'), ('tax', '税额', '13.00', '-13.00'),
                            ('invoice_total', '价税合计', '113.00', '-113.00')]]
    assert all(step['status'] == 'PASS' for step in result['check_steps'])
    assert args == before
    result['relationships'][0]['amount'] = '999'
    result['balances'][0]['blue'] = '999'
    assert args == before


def test_balanced_subchecks_never_override_missing_currency_gate(scope):
    args = inputs(scope)
    for f in args[1]:
        f['data']['normalized_value'].pop('currency')
        f['data']['field_sources'].pop('currency')
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED' and result['codes'] == ['CURRENCY_SOURCE_MISSING']
    assert all(b['status'] == 'PASS' for b in result['balances'])
    step = next(s for s in result['check_steps'] if s['code'] == 'CURRENCY_SOURCE_MISSING')
    assert step['status'] == 'UNKNOWN' and step['nature'] == 'SYSTEM_EVIDENCE_INCOMPLETE'
    assert '尚不能认定客户缺资料' in step['message']


@pytest.mark.parametrize('missing', [None, 'NaN', True, '1.001'])
def test_each_balance_is_independent_and_missing_is_not_zero(scope, missing):
    args = inputs(scope, ('-40.00', '-60.00'))
    args[1][2]['data']['normalized_value']['tax'] = missing
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED'
    assert result['relationships'][2]['tax_amount'] is None
    net, tax, total = result['balances']
    assert net['status'] == total['status'] == 'PASS'
    assert tax == dict(field='tax', label='税额', blue='13.00', red=None, net=None, status='UNKNOWN')


def test_partial_cancellation_is_a_conflict_but_absent_red_is_unknown(scope):
    args = inputs(scope, ('-40.00',))
    result = full_red_checks(scope, *args)['f0']
    assert [b['net'] for b in result['balances']] == ['60.00', '7.80', '67.80']
    assert all(b['status'] == 'MISMATCH' for b in result['balances'])
    step = next(s for s in result['check_steps'] if s['code'] == 'AMOUNT_CANCELLATION_MISMATCH')
    assert step['nature'] == 'EVIDENCE_CONFLICT' and step['status'] == 'BLOCKED'
    args[1].pop()
    result = full_red_checks(scope, *args)['f0']
    assert all(b['red'] is None and b['net'] is None and b['status'] == 'UNKNOWN' for b in result['balances'])
    step = next(s for s in result['check_steps'] if s['code'] == 'AMOUNT_CANCELLATION_MISMATCH')
    assert step['nature'] == 'SYSTEM_EVIDENCE_INCOMPLETE'


def test_duplicate_rows_are_not_aggregated_as_distinct_reds(scope):
    args = inputs(scope)
    args[1].append(deepcopy(args[1][1]))
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED'
    assert all(b['red'] is None and b['status'] == 'UNKNOWN' for b in result['balances'])


@pytest.mark.parametrize('foreign_part', ['fact', 'artifact'])
def test_foreign_scope_never_leaks_in_relationships_legacy_refs_or_totals(scope, foreign_part):
    import json
    args = inputs(scope)
    red = args[1][1]
    red['object_id'] = 'foreign-secret-fact'
    red['data']['source_anchor']['region'] = 'foreign-secret-region'
    if foreign_part == 'fact':
        red['scope']['legal_entity_id'] = 'foreign'
    else:
        artifact = deepcopy(args[0][0]); artifact['object_id'] = 'foreign-secret-artifact'
        artifact['scope']['legal_entity_id'] = 'foreign'; args[0].append(artifact)
        red['data']['source_artifact_id'] = artifact['object_id']
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED' and 'SCOPE_MISMATCH' in result['codes']
    text = json.dumps(result, ensure_ascii=False)
    assert 'foreign-secret' not in text and red['data']['normalized_value']['invoice_no'] not in text
    assert len(result['relationships']) == 1 and result['relationships'][0]['role'] == 'BLUE'
    assert all(b['red'] is None and b['net'] is None for b in result['balances'])
    args[1][0]['scope']['legal_entity_id'] = 'foreign'
    assert full_red_checks(scope, *args) == {}


def test_owned_blue_with_foreign_artifact_keeps_blocker_without_exposing_source(scope):
    import json
    args = inputs(scope)
    args[0][0]['scope']['legal_entity_id'] = 'foreign'
    result = full_red_checks(scope, *args)['f0']
    assert result['status'] == 'BLOCKED' and 'SCOPE_MISMATCH' in result['codes']
    assert result['relationships'] == result['refs'] == result['links'] == result['evidence_refs'] == []
    assert BLUE not in json.dumps(result)
