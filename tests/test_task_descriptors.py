from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ontology.contracts import Scope
from app.task_descriptors import VERIFY_RECORD_TYPE_LABELS, TaskDescriptor, describe_task
from conftest import command
from test_material_review import setup, view
from test_invoice_amount_review import setup_invoices, confirm_amount
from test_tabular_ingestion import uploaded, parse
from test_bank_accounts import bank_file


@pytest.mark.parametrize('kind,action,reason,expected,slot', [
    ('VERIFY', 'verify', '核对读取', 'verify_source_values', 'record_selection'),
    ('INVOICE_AMOUNT', 'confirm_invoice_amount', '红字金额', 'confirm_invoice_amount', ''),
    ('BILL', 'confirm_bill', '确认票据业务与科目', 'confirm_bill_business', 'bill_business'),
    ('BILL_ACCOUNT', 'review_bill_account', '科目待核对', 'confirm_bill_business', 'bill_business'),
    ('ISSUE', 'supplement', '期间：待确认', 'supplement', ''),
    ('PARSE', 'parse', 'PDF未识别', 'parse', ''),
    ('PARSE', 'supplement', '未知格式', 'supplement', ''),
    ('ISSUE', 'supplement', 'bank_account_ref：待确认', 'confirm_statement_account', 'bank_ownership'),
])
def test_descriptor_profiles_are_serializable_and_bind_exact_inputs(scope, kind, action, reason, expected, slot):
    artifact = dict(object_id='a', version=2, data={'sha256': 'file-hash'})
    records = [dict(object_id='f', version=3, values={'invoice_no': 'INV-1'}, source_anchor={'region': '表!A3'})]
    task = dict(id='unchanged-task', kind=kind, action=action, reason=reason, title='问题', filename='测试.xlsx')
    before = deepcopy((artifact, records, task))
    result = describe_task(task, Scope(**scope), artifact, records, {'status': 'NEW'} if slot == 'bank_ownership' else None)
    assert TaskDescriptor.model_validate(result).model_dump() == result
    primary = result['options'][0]
    assert primary['id'] == expected
    assert primary['completion'] and primary['requires'] and primary['not_effects']
    assert primary['execution_type'] in {'COMMAND', 'NAVIGATION'}
    assert primary['confirmation_label'] and primary['success_label']
    assert primary['post_submit_owner'] in {'SYSTEM', 'EXTERNAL', 'NONE'}
    assert result['scope']['legal_entity_id'] == scope['legal_entity_id']
    assert result['scope']['artifact'] == {'id': 'a', 'version': 2, 'sha256': 'file-hash'}
    assert result['scope']['records'][0]['version'] == 3
    assert result['why']['evidence'][0]['source_anchor'] == {'region': '表!A3'}
    assert result['steps'] == []
    assert [f['slot'] for f in primary['fields'] if f['component'] == 'slot'] == ([slot] if slot else [])
    assert (artifact, records, task) == before
    assert primary['available'] == (kind != 'BILL_ACCOUNT')
    valid_fields = {f['name'] for f in primary['fields']}
    valid_fields.update(p['name'] for f in primary['fields'] for p in f['properties'])
    assert all(step['prompt'] and set(step['fields']) <= valid_fields for step in primary['steps'])
    assert len(result['fingerprint']) == 64
    assert len({o['id'] for o in result['options']}) == len(result['options'])
    if kind != 'VERIFY':
        defer = next(o for o in result['options'] if o['id'] == 'defer_material_issue')
        assert len(defer['fields']) == 1 and defer['fields'][0]['required']
        assert '问题及原始异常继续保留' in defer['not_effects']


def test_projection_is_additive_and_does_not_change_existing_tasks_counts_or_gates(client, scope, monkeypatch):
    setup(client, scope)
    current = view(client, scope)
    assert current['material_review']['tasks']
    for task in current['material_review']['tasks']:
        descriptor = task.pop('descriptor')
        assert descriptor['scope']['artifact']['id'] == task['artifact_id']
        assert [r['id'] for r in descriptor['scope']['records']] == task['record_ids']
    monkeypatch.setattr('app.task_descriptors.describe_task', lambda *args: {})
    previous = view(client, scope)
    for task in previous['material_review']['tasks']:
        task.pop('descriptor')
    # Routing is now a documented derivative of descriptor fields/options.
    # Compare every pre-existing field unchanged, excluding only this additive
    # projection; its own routing and conservation tests live in issue_triage.
    for overview in (current, previous):
        for task in overview['material_review']['tasks']:
            task.pop('triage')
            task.pop('handling', None)
        overview['material_review']['counts'].pop('human_issue_tasks')
        overview['material_review']['counts'].pop('system_issue_tasks')
        overview['material_review']['counts'].pop('selected_processing_tasks', None)
        overview['material_review'].pop('flow', None)
        overview['material_review'].pop('next_step', None)
        overview['problem_review'].pop('triage_tasks')
    assert current == previous


def test_every_current_task_answers_stage_reason_action_and_effect_questions(client, scope):
    setup(client, scope)
    tasks = view(client, scope)['material_review']['tasks']
    assert tasks
    for task in tasks:
        descriptor = TaskDescriptor.model_validate(task['descriptor'])
        assert descriptor.stage in {'SOURCE_REVIEW', 'BUSINESS_REVIEW', 'SYSTEM_REVIEW'}
        assert descriptor.why_now.strip()
        assert descriptor.why.facts.strip()
        assert descriptor.why.rule.strip()
        available = [option for option in descriptor.options if option.available]
        assert available, task['id']
        assert all(option.effects for option in available)
        assert all(effect.grants_accounting_usable is False
                   for option in available for effect in option.effects)


def test_invoice_and_defer_descriptions_match_existing_behavior_without_unlocking_finance(client, scope):
    a, facts = setup_invoices(client, scope)
    before = view(client, scope)
    task = next(t for t in before['material_review']['tasks'] if t['kind'] == 'INVOICE_AMOUNT')
    d = task['descriptor']
    assert d['options'][0]['fields'][0]['required']
    assert '仅解除本张发票' in d['options'][0]['effects'][0]['description']
    assert d['options'][0]['effects'][0]['grants_accounting_usable'] is False
    r = command(client, scope, 'defer_material_issue', a['object_id'], a['version'], 'contract-defer',
                {'task_id': task['id'], 'reason': '等待客户说明'})
    assert r.status_code == 200
    deferred = view(client, scope)
    assert deferred['material_review']['counts']['deferred'] == 1
    assert deferred['material_review']['counts']['needs_review'] == before['material_review']['counts']['needs_review']
    assert confirm_amount(client, scope, facts[0]).status_code == 200
    after = view(client, scope)
    assert not any(t['id'] == task['id'] for t in after['material_review']['tasks'])
    assert after['material_review']['counts']['source_verified'] == 0
    for key in ('baseline', 'baseline_validation', 'groups', 'vouchers', 'data_readiness'):
        assert after[key] == before[key]


def test_bank_slot_has_optional_number_and_no_unknown_action(client, scope):
    a = uploaded(client, scope, bank_file(), filename='农业银行.xlsx')
    assert parse(client, scope, a, 'bank_statement').status_code == 200
    task = next(t for t in view(client, scope)['material_review']['tasks'] if t['reason'].startswith('bank_account_ref：'))
    option = task['descriptor']['options'][0]
    assert option['id'] == 'confirm_statement_account'
    fields = {p['name']: p for p in option['fields'][0]['properties']}
    assert not fields['account_number']['required']
    assert fields['bank_name']['required'] and fields['confirmed']['required']
    assert '不确认交易与发票匹配' in option['not_effects']


def test_unknown_contract_properties_rejected():
    with pytest.raises(ValidationError):
        TaskDescriptor.model_validate({'version': 'decision-v999', 'title': 'x', 'why': {}, 'scope': {}, 'options': [], 'execute': 'arbitrary'})


@pytest.mark.parametrize('kind,reason,values,raw,fields,quoted', [
    ('ISSUE', '发票状态：发票状态须人工核对', {'invoice_status': '已红冲-全额'},
     {'invoice_status': '已红冲-全额'}, ['invoice_status'], '已红冲-全额'),
    ('ISSUE', 'invoice_status：发票状态须人工核对', {'invoice_status': '作废'},
     {'invoice_status': '作废'}, ['invoice_status'], '作废'),
    ('ISSUE', '价税合计：金额格式无效', {'invoice_total': None},
     {'invoice_total': '1O0.00'}, ['invoice_total'], '1O0.00'),
    ('ISSUE', '开票日期：日期缺失或不能确定', {'invoice_date': None},
     {'invoice_date': '2026/02/30'}, ['invoice_date'], '2026/02/30'),
    ('ISSUE', '业务期间：不属于已核定的本期业务范围', {'period': '2026-01', 'invoice_date': '2026-01-12'},
     {'invoice_date': '2026/01/12'}, ['period', 'invoice_date'], '2026/01/12'),
    ('ISSUE', 'bank_account_ref：请确认流水所属的企业账户', {'bank_account_ref': None, 'bank_name': '农业银行'},
     {'bank_name': '中国农业银行'}, ['bank_account_ref', 'bank_name'], '中国农业银行'),
    ('BILL', '确认票据业务与科目', {'acceptance_no': 'B-123', 'amount': '123.00', 'issue_date': '2026-01-12'},
     {'amount': '123.00'}, ['acceptance_no', 'amount', 'issue_date'], '123.00'),
    ('INVOICE_AMOUNT', '价税合计：红字或零金额发票须人工核对', {'invoice_total': '-10.00'},
     {'invoice_total': '-10.00'}, ['invoice_total'], '-10.00'),
])
def test_presentation_quotes_evidence_and_references_only_current_fields(scope, kind, reason, values, raw, fields, quoted):
    task = dict(id='task', kind=kind, reason=reason, title='问题', action='supplement', filename='测试.xlsx')
    artifact = dict(object_id='artifact', version=1, data={})
    records = [dict(object_id='row-2', version=2, values={**values, 'unrelated': '不得引入'}, issues=[reason],
                    source_anchor={'region': '表!A2:Z2'},
                    comparison=[dict(field=k, source_value=v, value=values[k], region='表!B2') for k, v in raw.items()])]
    bank = {'status': 'NEW', 'identity': {'bank_name': '农业银行'}} if 'bank_account_ref' in reason else None
    before = deepcopy((task, artifact, records, bank, scope))
    result = describe_task(task, Scope(**scope), artifact, records, bank)
    p = result['presentation']
    assert set(p) == {'type_label', 'explanation', 'records'}
    assert p['records'] == [{'id': 'row-2', 'focus_fields': fields}]
    if kind == 'BILL':
        assert '业务性质、实际业务期间及拟用科目' in p['explanation']
        assert quoted not in p['explanation'] and 'B-123' not in p['explanation']
    else:
        assert f'「{quoted}」' in p['explanation']
        assert '表!B2' in p['explanation']
    assert '不得引入' not in p['explanation']
    assert (task, artifact, records, bank, scope) == before
    assert result == describe_task(task, Scope(**scope), artifact, records, bank)
    if '状态' in reason:
        assert '不能仅据此判为提取错误' in p['explanation']
        assert [o['id'] for o in result['options']] == ['supplement', 'defer_material_issue']
    if '开票日期' in reason or '业务期间' in reason:
        assert '开票日期' in result['why']['recommendation']
        assert '收票' not in result['why']['recommendation']


def test_presentation_parse_failure_and_unknown_are_not_customer_missing(scope):
    artifact = dict(object_id='a', version=1, data={'parse_status': 'RECONCILIATION_FAILED',
                                                'parse_errors': ['明细合计100，声明合计200']})
    task = dict(id='t', kind='PARSE', reason='STRUCTURE_PLAN_INVALID_REFERENCE_ROWS', title='解析', action='parse', filename='测试.xlsx')
    result = describe_task(task, Scope(**scope), artifact, [])
    assert result['presentation']['records'] == []
    assert '「明细合计100，声明合计200」' in result['presentation']['explanation']
    assert '「STRUCTURE_PLAN_INVALID_REFERENCE_ROWS」' in result['presentation']['explanation']
    assert '不代表客户缺资料' in result['presentation']['explanation']
    task.update(kind='ISSUE', reason='未知检查条件', action='supplement')
    result = describe_task(task, Scope(**scope), artifact, [])
    assert '信息不足' in result['presentation']['explanation']
    assert '不能据此认定客户缺少资料' in result['presentation']['explanation']
    assert result['options'][0]['label'] == '补充资料（可选）'


def test_old_descriptor_valid_and_projection_cannot_add_raw_payload(scope):
    task = dict(id='t', kind='ISSUE', reason='未知', title='问题', action='supplement', filename='测试.xlsx')
    result = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), [])
    old = deepcopy(result)
    old.pop('presentation')
    validated = TaskDescriptor.model_validate(old).model_dump()
    assert validated.pop('presentation') is None
    assert validated == old
    result['presentation']['records'] = [{'id': 'r', 'focus_fields': [], 'values': {'amount': 1}}]
    with pytest.raises(ValidationError):
        TaskDescriptor.model_validate(result)


def test_projection_multiple_records_preserves_order_and_uses_raw_source(scope):
    reason = '价税合计：金额格式无效'
    task = dict(id='t', kind='ISSUE', reason=reason, title='问题', action='supplement', filename='测试.xlsx')
    records = [dict(object_id=f'r{i}', version=i, values={'invoice_total': None, 'invoice_status': '作废'},
                    issues=[reason, '发票状态：发票状态须人工核对'],
                    field_sources={'invoice_total': {'original_value': raw, 'region': f'表!C{i}'}},
                    comparison=[{'field': 'invoice_status', 'source_value': '作废', 'state': 'DIRECT_MATCH'}])
               for i, raw in [(3, '=A3+B3'), (2, '金额待定')]]
    result = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), records)
    assert result['presentation']['records'] == [dict(id='r3', focus_fields=['invoice_total']), dict(id='r2', focus_fields=['invoice_total'])]
    assert '「=A3+B3」' in result['presentation']['explanation']
    assert '「金额待定」' in result['presentation']['explanation']
    assert '作废' not in result['presentation']['explanation']


def test_presentation_does_not_change_action_contract_or_bindings(scope, monkeypatch):
    task = dict(id='t', kind='BILL', reason='确认票据业务与科目', title='票据', action='confirm_bill', filename='测试.xlsx')
    artifact = dict(object_id='a', version=1, data={'sha256': 'hash'})
    records = [dict(object_id='r', version=2, values={'amount': '10.00'}, source_anchor={'row': 3})]
    projected = describe_task(task, Scope(**scope), artifact, records)
    monkeypatch.setattr('app.task_descriptors.issue_presentation', lambda *args: None)
    legacy = describe_task(task, Scope(**scope), artifact, records)
    for key in ('scope', 'options', 'steps', 'why', 'title', 'version'):
        assert projected[key] == legacy[key]


@pytest.mark.parametrize('record_type,field,expected,excluded', [
    ('SALES_INVOICE', 'invoice_date', '开票日期', '收票'),
    ('BANK_TRANSACTION', 'transaction_date', '原件业务日期', '收票'),
    ('ELECTRONIC_ACCEPTANCE', 'transaction_date', '收票', '开票日期'),
])
def test_period_advice_uses_record_business_type(scope, record_type, field, expected, excluded):
    task = dict(id='t', kind='ISSUE', reason='业务期间：不属于本期', title='期间', action='supplement', filename='测试.xlsx')
    record = dict(object_id='r', version=1, record_type=record_type,
                  values={'period': '2026-01', field: '2026-01-02', 'maturity_date': '2026-12-31'})
    result = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), [record])
    assert expected in result['why']['recommendation']
    assert excluded not in result['why']['recommendation']
    assert result['presentation']['records'] == [{'id': 'r', 'focus_fields': ['period', field]}]


def test_many_records_have_two_distinct_original_quotes_and_all_references(scope):
    task = dict(id='t', kind='ISSUE', reason='发票状态：须人工核对', title='状态', action='supplement', filename='测试.xlsx')
    records = [dict(object_id=f'r{i}', version=1, values={'invoice_status': 'normalized'},
                    comparison=[dict(field='invoice_status', source_value=['已红冲-全额', '已红冲-全额', '作废', '其他状态'][min(i, 3)], region=f'表!C{i}')])
               for i in range(100)]
    before = deepcopy(records)
    p = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), records)['presentation']
    assert len(p['explanation']) <= 400
    assert p['explanation'].count('「') == 2
    assert p['explanation'].count('已红冲-全额') == 1
    assert '「作废」' in p['explanation'] and '其他状态' not in p['explanation']
    assert '涉及 100 条记录，详见下方清单' in p['explanation']
    assert p['records'] == [dict(id=f'r{i}', focus_fields=['invoice_status']) for i in range(100)]
    assert records == before


@pytest.mark.parametrize('kind', ['ISSUE', 'PARSE'])
def test_long_evidence_is_omitted_whole_never_sliced(scope, kind):
    identifier = 'IDENTIFIER-' + '0123456789' * 60
    task = dict(id='t', kind=kind, reason=identifier if kind == 'PARSE' else 'invoice_status：须核对', title='问题', action='supplement', filename='测试.xlsx')
    records = [] if kind == 'PARSE' else [dict(object_id='r', version=1, values={'invoice_status': identifier},
                                             comparison=[dict(field='invoice_status', source_value=identifier)])]
    p = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={'parse_errors': [identifier]}), records)['presentation']
    assert len(p['explanation']) <= 400
    assert 'IDENTIFIER-' not in p['explanation']
    assert '详见' in p['explanation']


def test_verify_preview_is_compact_identity_date_amount_without_losing_records(scope):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='测试.xlsx')
    values = dict(invoice_no='INV-1', invoice_date='2026-03-01', invoice_total='113.00', tax='13.00',
                  net_amount='100.00', invoice_status='正常', buyer_name='企业', seller_name='供应商')
    records = [dict(object_id=f'r{i}', version=1, values=values) for i in range(5)]
    p = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), records)['presentation']
    assert p['records'] == [dict(id=f'r{i}', focus_fields=['invoice_no', 'invoice_date', 'invoice_total', 'tax']) for i in range(5)]
    assert len(p['explanation']) <= 400
    assert 'INV-1' not in p['explanation']
    assert p['explanation'] == '请核对下方 5 条发票记录的发票号码、开票日期、价税合计和税额是否与原件一致。'


def test_verify_payroll_includes_actual_salary(scope):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='工资.xlsx')
    record = dict(object_id='r', version=1, values={'person_name': '员工', 'period': '2026-03',
                                                 'actual_salary': '5000', 'basic_salary': '6000'})
    p = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), [record])['presentation']
    assert p['records'] == [dict(id='r', focus_fields=['person_name', 'period', 'actual_salary'])]


@pytest.mark.parametrize('record_type,values,subject,expected_fields', [
    ('INVOICE',
     {'invoice_no': 'INV-1', 'invoice_date': '2026-01-10', 'invoice_total': '113.00', 'tax': '13.00'},
     '采购发票', '发票号码、开票日期、价税合计和税额'),
    ('ELECTRONIC_ACCEPTANCE',
     {'acceptance_no': 'B-1', 'transaction_date': '2026-01-13', 'amount': '9352.00', 'period': '2026-01'},
     '电子承兑', '票据包号、交易日期、金额和业务期间'),
    ('SALES_INVOICE',
     {'invoice_no': 'INV-1', 'invoice_date': '2026-01-10', 'invoice_total': '113.00', 'tax': '13.00'},
     '销售发票', '发票号码、开票日期、价税合计和税额'),
    ('PAYMENT',
     {'transaction_id': 'TX-1', 'transaction_date': '2026-01-08', 'expense': '88.00'},
     '银行支出流水', '交易流水号、交易日期和支出金额'),
    ('RECEIPT',
     {'transaction_id': 'TX-2', 'transaction_date': '2026-01-09', 'income': '188.00', 'balance': '500.00'},
     '银行收入流水', '交易流水号、交易日期、收入金额和账户余额'),
    ('BANK_TRANSACTION',
     {'transaction_id': 'TX-3', 'transaction_date': '2026-01-10', 'expense': '88.00', 'income': '0.00'},
     '银行流水', '交易流水号、交易日期、支出金额和收入金额'),
    ('PAYROLL',
     {'person_name': '员工', 'period': '2026-01', 'actual_salary': '5000.00'},
     '工资', '姓名、业务期间和实发工资'),
    ('SOCIAL_SECURITY',
     {'person_name': '员工', 'period_ref': '2026-01', 'employer_amount': '800.00', 'employee_amount': '400.00'},
     '社保', '姓名、费款所属期、单位缴费金额和个人缴费金额'),
    ('SOCIAL_SECURITY',
     {'insurance_type': '养老', 'period': '2026-01', 'start_period': '2026-01', 'end_period': '2026-01',
      'employer_amount': '800.00', 'employee_amount': '400.00'},
     '社保', '险种、业务期间、单位缴费金额和个人缴费金额'),
    ('HOUSING_FUND',
     {'account': 'HF-1', 'person_name': '员工', 'entry_date': '2026-01-10', 'period': '2026-01', 'amount': '600.00'},
     '住房公积金', '个人公积金账号、姓名、入账日期和金额'),
    ('INDIVIDUAL_INCOME_TAX',
     {'person_name': '员工', 'person_id': 'P-1', 'period': '2026-01', 'income': '5000.00'},
     '个人所得税', '姓名、个人编号、业务期间和收入金额'),
    ('OPENING_BALANCE',
     {'account_code': '1001', 'account_name': '库存现金', 'opening_debit': '100.00', 'opening_credit': '0.00'},
     '期初余额', '科目编码、科目名称、期初借方余额和期初贷方余额'),
    ('CONTRACT',
     {'contract_no': 'C-1', 'contract_date': '2026-01-02', 'supplier': '供应商', 'amount': '1000.00'},
     '合同', '合同编号、合同日期、供应商和金额'),
    ('STOCK_IN',
     {'stock_in_no': 'S-1', 'stock_in_date': '2026-01-03', 'supplier': '供应商', 'amount': '1000.00'},
     '入库', '入库单号、入库日期、供应商和金额'),
])
def test_verify_presentation_tells_user_exactly_what_to_compare(
        scope, record_type, values, subject, expected_fields):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='测试.xlsx')
    records = [dict(object_id=f'r{i}', version=1, record_type=record_type, values=values)
               for i in range(4)]
    presentation = describe_task(
        task, Scope(**scope), dict(object_id='a', version=1, data={}), records
    )['presentation']
    assert presentation['type_label'] == f'核对{subject}明细读取结果'
    assert presentation['explanation'] == (
        f'请核对下方 4 条{subject}记录的{expected_fields}是否与原件一致。'
    )


def test_verify_presentation_does_not_mislabel_cross_family_records(scope):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='混合资料.xlsx')
    records = [
        dict(object_id='bill', version=1, record_type='ELECTRONIC_ACCEPTANCE',
             values={'acceptance_no': 'B-1', 'amount': '100.00'}),
        dict(object_id='bank', version=1, record_type='PAYMENT',
             values={'transaction_id': 'TX-1', 'expense': '100.00'}),
    ]
    presentation = describe_task(
        task, Scope(**scope), dict(object_id='a', version=1, data={}), records
    )['presentation']
    assert presentation['type_label'] == '核对混合资料明细读取结果'
    assert presentation['explanation'].startswith('请核对下方 2 条混合资料记录的')
    assert '2 条电子承兑记录' not in presentation['explanation']
    assert '2 条银行流水记录' not in presentation['explanation']


def test_verify_presentation_infers_each_legacy_record_before_naming_the_group(scope):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='旧版混合资料.xlsx')
    records = [
        dict(object_id='invoice', version=1,
             values={'invoice_no': 'INV-1', 'invoice_total': '113.00'}),
        dict(object_id='payroll', version=1,
             values={'person_name': '员工', 'net_pay': '5000.00'}),
    ]
    presentation = describe_task(
        task, Scope(**scope), dict(object_id='a', version=1, data={}), records
    )['presentation']
    assert presentation['type_label'] == '核对混合资料明细读取结果'
    assert presentation['explanation'].startswith('请核对下方 2 条混合资料记录的')


@pytest.mark.parametrize('missing_type', [None, ''])
def test_verify_presentation_fails_closed_when_one_record_type_is_missing(scope, missing_type):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='旧版混合资料.xlsx')
    records = [
        dict(object_id='bank', version=1, record_type='PAYMENT',
             values={'transaction_id': 'TX-1', 'expense': '100.00'}),
        dict(object_id='legacy', version=1, record_type=missing_type,
             values={'acceptance_no': 'B-1', 'amount': '100.00'}),
    ]
    presentation = describe_task(
        task, Scope(**scope), dict(object_id='a', version=1, data={}), records
    )['presentation']
    assert presentation['type_label'] == '核对混合资料明细读取结果'
    assert presentation['explanation'].startswith('请核对下方 2 条混合资料记录的')
    assert '2 条银行支出流水记录' not in presentation['explanation']


@pytest.mark.parametrize('record_type,values,comparison,expected_fields', [
    ('SOCIAL_SECURITY',
     {'person_name': None, 'person_id': 'P-1', 'period_ref': '2026-01',
      'employer_amount': '800.00', 'employee_amount': '400.00'},
     ['person_id', 'period_ref', 'employer_amount', 'employee_amount'],
     '个人编号、费款所属期、单位缴费金额和个人缴费金额'),
    ('HOUSING_FUND',
     {'account': 'HF-1', 'person_name': None, 'entry_date': '2026-01-10',
      'period': '2026-01', 'amount': '600.00'},
     ['account', 'entry_date', 'period', 'amount'],
     '个人公积金账号、入账日期、业务期间和金额'),
    ('INDIVIDUAL_INCOME_TAX',
     {'person_name': '员工', 'person_id': None, 'period': '2026-01', 'income': '5000.00'},
     ['person_name', 'period', 'income'],
     '姓名、业务期间和收入金额'),
    ('RECEIPT',
     {'transaction_id': None, 'transaction_date': '2026-01-09',
      'income': '188.00', 'balance': None},
     ['transaction_date', 'income'],
     '交易日期和收入金额'),
])
def test_verify_presentation_only_names_fields_rendered_in_real_comparison(
        scope, record_type, values, comparison, expected_fields):
    task = dict(id='t', kind='VERIFY', reason='核对读取结果', title='核对', action='verify', filename='真实解析结构.xlsx')
    records = [dict(
        object_id='r', version=1, record_type=record_type, values=values,
        comparison=[dict(field=name, source_value=values.get(name), value=values.get(name),
                         state='DIRECT_MATCH', region=f'表!{name}') for name in comparison],
    )]
    presentation = describe_task(
        task, Scope(**scope), dict(object_id='a', version=1, data={}), records
    )['presentation']
    assert presentation['records'] == [dict(id='r', focus_fields=comparison)]
    subject = VERIFY_RECORD_TYPE_LABELS[record_type]
    assert presentation['explanation'] == (
        f'请核对下方 1 条{subject}记录的{expected_fields}是否与原件一致。'
    )


@pytest.mark.parametrize('kind,status,title,explanation', [
    ('BILL', 'OPINION', '处理意见已记录，业务归属仍待确认', '已有处理意见'),
    ('BILL_ACCOUNT', 'CONFIRMED', '核对票据拟用科目', '科目仍待核对'),
    ('BILL_ACCOUNT', None, '核对票据拟用科目', '拟用或历史科目记录'),
])
def test_bill_presentation_preserves_existing_pending_state(scope, kind, status, title, explanation):
    task = dict(id='t', kind=kind, reason='确认票据业务与科目', title='票据', action='confirm_bill', filename='票据.xlsx')
    record = dict(object_id='r', version=2, values={'acceptance_no': 'B-1', 'amount': '100'},
                  bill_confirmation={'status': status} if status else None)
    before = deepcopy(record)
    result = describe_task(task, Scope(**scope), dict(object_id='a', version=1, data={}), [record])
    assert result['presentation']['type_label'] == result['title'] == title
    assert explanation in result['presentation']['explanation']
    assert len(result['presentation']['explanation']) <= 400
    assert result['options'][0]['id'] == 'confirm_bill_business'
    assert result['options'][0]['available'] is False
    assert result['presentation']['records'] == [dict(id='r', focus_fields=['acceptance_no', 'amount'])]
    assert record == before
