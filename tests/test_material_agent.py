import base64
from copy import deepcopy
import time

import pytest

from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from test_tabular_ingestion import xlsx_fixture

HEADERS = {'X-Actor-Id': 'alice', 'X-Role': 'operator'}


def prepare(client, scope):
    client.post('/api/v1/scopes', json=scope, headers=HEADERS)
    content = xlsx_fixture([('发票', [
        ['数电发票号码', '开票日期', '金额', '税额', '价税合计', '销售方纳税人名称'],
        ['260000000001', '2026-03-08', '100.00', '13.00', '113.00', '保密供应商'],
    ])])
    source = client.post('/api/v1/artifacts', headers=HEADERS, json={
        'scope': scope, 'filename': '采购.xlsx', 'content_base64': base64.b64encode(content).decode(),
        'source_purpose': 'business'}).json()
    svc = client.app.state.service
    typed = Scope(**scope)
    with svc.store.database.transaction():
        result = svc.parse_artifact(typed, artifact_id=source['object_id'], actor_id='alice', expected_version=source['version'], payload={'document_kind': 'purchase_invoices'})
    object.__setattr__(svc.store.database.settings, 'agent_loop_enabled', True)
    return svc, typed, result['artifact']


def reader(*tools):
    sequence = iter(tools)
    return lambda packet: ({'tool': next(sequence), 'reason': '测试工具选择'}, {'mock': True})


def wb(client, scope):
    response = client.post('/api/v1/workbench', headers=HEADERS, json={'scope': scope})
    assert response.status_code == 200, response.text
    return response.json()


def test_user_tasks_withheld_until_tools_finish_then_source_is_optional(client, scope):
    svc, typed, source = prepare(client, scope)
    before = wb(client, scope)['material_review']
    assert before['agent_processing']['not_started'] == 1
    assert not before['tasks']
    response = client.post('/api/v1/materials/process', headers=HEADERS, json={'scope': scope})
    assert response.status_code == 200, response.text
    svc.material_agent.reader = reader('inspect_source', 'verify_extraction', 'search_related', 'inspect_issues', 'finish')
    for _ in range(5):
        assert svc.material_agent.step()
    after = wb(client, scope)['material_review']
    assert after['agent_processing']['verified'] == 1, after['agent_processing']
    assert all(t.get('optional') for t in after['tasks'] if t['kind'] == 'VERIFY')
    assert after['problem_buckets'][-1]['count'] == 1
    assert svc.store.list_objects('VoucherVersion', typed) == []


def test_premature_finish_does_not_mark_completed(client, scope):
    svc, typed, _ = prepare(client, scope)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('finish')
    svc.material_agent.step()
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['status'] == 'QUEUED'
    assert job['data']['steps'][-1]['result']['error'] == 'FINISH_REJECTED'


def test_resume_preserves_evidence_and_retry_has_no_duplicate_job(client, scope):
    svc, typed, _ = prepare(client, scope)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('inspect_source', 'verify_extraction')
    svc.material_agent.step(); svc.material_agent.step()
    from app.material_agent import MaterialAgent
    svc.material_agent = MaterialAgent(svc)
    svc.material_agent.reader = reader('search_related', 'inspect_issues', 'finish')
    for _ in range(3): svc.material_agent.step()
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['status'] in {'COMPLETED', 'NEEDS_USER'}
    assert len(job['data']['steps']) == 5
    svc.material_agent.enqueue(typed, 'alice')
    assert len(svc.store.list_objects('MaterialAgentRun', typed)) == 1


def test_failing_model_stops_and_explicit_resume_keeps_progress(client, scope):
    svc, typed, _ = prepare(client, scope)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = lambda packet: ({'tool': 'invented', 'reason': 'bad'}, {'mock': True})
    svc.material_agent.step()
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['status'] == 'FAILED'
    response = client.post(f"/api/v1/materials/process/{job['object_id']}/resume", headers=HEADERS, json={'scope': scope})
    assert response.status_code == 200, response.text
    resumed = svc.store.get_object(job['object_id'], typed)
    assert resumed['status'] == 'QUEUED' and len(resumed['data']['steps']) == 1


def test_changed_source_invalidates_old_result_and_read_does_not_enqueue(client, scope):
    svc, typed, source = prepare(client, scope)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('verify_extraction', 'search_related', 'inspect_issues', 'finish')
    for _ in range(4): svc.material_agent.step()
    svc.store.revise_object(source['object_id'], source['version'], typed, {**source['data'], 'new_note': 'changed'}, status='ACTIVE', created_by='alice')
    before = len(svc.store.list_objects('MaterialAgentRun', typed))
    assert wb(client, scope)['material_review']['agent_processing']['not_started'] == 1
    assert len(svc.store.list_objects('MaterialAgentRun', typed)) == before


def test_read_only_actor_cannot_start_or_resume(client, scope):
    prepare(client, scope)
    headers = {'X-Actor-Id': 'viewer', 'X-Role': 'viewer'}
    assert client.post('/api/v1/materials/process', headers=headers, json={'scope': scope}).status_code == 403
    assert client.post('/api/v1/materials/process/unknown/resume', headers=headers, json={'scope': scope}).status_code == 403


def test_lease_recovery_and_no_progress_limit(client, scope):
    svc, typed, _ = prepare(client, scope)
    job = svc.material_agent.enqueue(typed, 'alice')[0]
    svc.store.revise_object(job['object_id'], job['version'], typed, {**job['data'], 'lease_until': time.time()-1}, status='RUNNING', created_by='system')
    svc.material_agent.reader = reader('inspect_source', 'inspect_source', 'inspect_source')
    for _ in range(3): svc.material_agent.step()
    assert svc.store.get_object(job['object_id'], typed)['status'] == 'BLOCKED'


def test_two_wrong_rows_cannot_pass_even_when_aggregates_agree(client, scope):
    svc, typed, source = prepare(client, scope)
    facts = svc.material_agent.facts(typed, source)
    f = facts[0]; data = deepcopy(f['data']); data['normalized_value']['net_amount'] = '101.00'
    svc.store.revise_object(f['object_id'], f['version'], typed, data, status=f['status'], created_by='test')
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('verify_extraction', 'reread_source', 'verify_extraction', 'apply_extraction', 'verify_extraction', 'search_related', 'inspect_issues', 'finish')
    for _ in range(8): assert svc.material_agent.step()
    jobs = svc.store.list_objects('MaterialAgentRun', typed)
    assert len(jobs) == 1, jobs
    assert jobs[0]['status'] in {'COMPLETED', 'NEEDS_USER'}, jobs[0]['data']['steps']
    assert jobs[0]['data']['steps'][0]['result']['status'] == 'BLOCKED'
    assert svc.material_agent.facts(typed, svc.store.get_object(source['object_id'], typed))[0]['data']['normalized_value']['net_amount'] == '100.00'


@pytest.mark.parametrize('mutation', ['missing_anchor', 'wrong_alias', 'missing_value', 'old_warning'])
def test_candidate_cannot_shrink_reference_contract(client, scope, mutation):
    from app.source_checks import verify_source
    svc, typed, source = prepare(client, scope)
    content = svc.material_agent._content(source)
    reference = svc.material_agent._extract(typed, source, content)
    candidate = deepcopy(reference)
    row = candidate['records'][0]
    if mutation == 'missing_anchor':
        row['normalized_value']['seller_name'] = '错误供应商'
        row['field_sources'].pop('seller_name')
    elif mutation == 'wrong_alias':
        row['normalized_value']['counterparty'] = '错误供应商'
    elif mutation == 'missing_value':
        row['normalized_value'].pop('net_amount')
    else:
        row['extraction_issues'] = ['发票日期：原件日期识别异常，请重新读取']
    assert verify_source(content, candidate, reference)['status'] == 'BLOCKED'


def test_source_rows_skipped_by_parser_are_not_silently_verified():
    from app.source_checks import verify_source
    from app.tabular import extract_workbook, ParseOptions
    content = xlsx_fixture([('入库', [
        ['入库单号', '入库日期', '供应商', '金额'],
        ['RK001', '2026-03-08', '供应商甲', '100'],
        ['', '2026-03-09', '供应商乙', '200'],
    ])])
    reference = extract_workbook(content, ParseOptions(document_kind='stock_in'), '2026-03')
    assert len(reference['records']) == 1
    proof = verify_source(content, reference, reference)
    assert proof['status'] == 'BLOCKED'
    assert any(f['code'] == 'UNACCOUNTED_SOURCE_ROW' and f['row'] == 3 for f in proof['failures'])


def test_bank_repair_preserves_confirmed_account_binding(client, scope):
    from test_bank_accounts import bank_file
    from test_tabular_ingestion import uploaded, parse
    from conftest import command
    source = uploaded(client, scope, bank_file(), filename='农业银行.xlsx')
    source = parse(client, scope, source, 'bank_statement').json()['effect']['artifact']
    svc, typed = client.app.state.service, Scope(**scope)
    candidate = svc.bank_accounts.view(typed)['statements'][0]
    response = command(client, scope, 'confirm_statement_account', source['object_id'], source['version'], 'agent-bank-confirm', {
        'token': candidate['token'], 'ownership_confirmed': True,
        'new_account': {k: candidate['identity'][k] for k in ('account_number', 'holder', 'bank_name', 'currency')}})
    assert response.status_code == 200, response.text
    source = response.json()['effect']['artifact']
    binding = deepcopy(source['data']['bank_account_binding'])
    fact = svc.material_agent.facts(typed, source)[0]
    data = deepcopy(fact['data']); data['normalized_value']['income'] = '999.00'
    svc.store.revise_object(fact['object_id'], fact['version'], typed, data, status=fact['status'], created_by='test')
    object.__setattr__(svc.store.database.settings, 'agent_loop_enabled', True)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('verify_extraction', 'reread_source', 'verify_extraction', 'apply_extraction', 'verify_extraction')
    for _ in range(5): assert svc.material_agent.step()
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['data']['proof']['status'] == 'PASS', job['data']['steps']
    current = svc.store.get_object(source['object_id'], typed)
    assert {k: v for k, v in current['data']['bank_account_binding'].items() if k != 'artifact_version'} == {k: v for k, v in binding.items() if k != 'artifact_version'}
    assert all(f['data']['normalized_value']['bank_account_ref'] == binding['account_reference'] for f in svc.material_agent.facts(typed, current))
    assert not svc.store.list_objects('VoucherVersion', typed)


@pytest.mark.parametrize('kind', ['Decision', 'MaterialGuidanceOpinion', 'FactRecord', 'SourceArtifact'])
def test_other_inputs_invalidate_result_and_enqueue_fresh_job(client, scope, kind):
    svc, typed, source = prepare(client, scope)
    first = svc.material_agent.enqueue(typed, 'alice')[0]
    svc.store.create_initial_object(kind, typed, {'decision_type': 'TASK_ACTION', 'source_artifact_id': 'related'}, status='CONFIRMED', created_by='test')
    jobs = svc.material_agent.enqueue(typed, 'alice')
    assert jobs[0]['object_id'] != first['object_id']


def test_prior_task_dispositions_are_respected_by_loop(client, scope):
    from test_task_actions import unknown_task, execute
    artifact, fact, task, _ = unknown_task(client, scope)
    response = execute(client, scope, artifact, task, 'suspend', {'reason': '等待下期业务核对'}, 'agent-suspend')
    assert response.status_code == 200, response.text
    svc, typed = client.app.state.service, Scope(**scope)
    object.__setattr__(svc.store.database.settings, 'agent_loop_enabled', True)
    tasks = svc.material_agent.issue_view(typed)['tasks']
    projected = next(t for t in tasks if t['id'] == task['id'])
    assert projected['task_action']['valid']
    assert projected['handling']['owner'] == 'NONE'
    job = svc.material_agent.enqueue(typed, 'alice')[0]
    data, result, _ = svc.material_agent._tools(typed, job, {'tool': 'inspect_issues'})
    assert task['id'] not in data['issues']


def test_old_extraction_warning_is_repaired_instead_of_sent_to_user(client, scope):
    svc, typed, source = prepare(client, scope)
    fact = svc.material_agent.facts(typed, source)[0]
    svc.store.revise_object(fact['object_id'], fact['version'], typed,
        {**fact['data'], 'extraction_issues': ['发票日期：原件日期识别异常，请重新读取']}, status='NEEDS_REVIEW', created_by='test')
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('verify_extraction', 'reread_source', 'verify_extraction', 'apply_extraction', 'verify_extraction', 'search_related', 'inspect_issues', 'finish')
    for _ in range(8): assert svc.material_agent.step()
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['data']['steps'][0]['result']['status'] == 'BLOCKED'
    assert job['status'] == 'COMPLETED', job['data']['steps']
    assert not svc.material_agent.facts(typed, source)[0]['data']['extraction_issues']


def test_formula_only_unparsed_row_blocks_completeness():
    from io import BytesIO
    from zipfile import ZipFile
    from app.source_checks import verify_source
    from app.tabular import extract_workbook, ParseOptions
    content = xlsx_fixture([('入库', [['入库单号', '入库日期', '供应商', '金额'], ['RK001', '2026-03-08', '甲', 100]])])
    buffer = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(buffer, 'w') as changed:
        for name in original.namelist():
            data = original.read(name)
            if name == 'xl/worksheets/sheet1.xml':
                data = data.replace(b'</sheetData>', b'<row r="3"><c r="A3"><f>"RK002"</f></c><c r="D3"><f>200</f></c></row></sheetData>')
            changed.writestr(name, data)
    content = buffer.getvalue()
    result = extract_workbook(content, ParseOptions(document_kind='stock_in'), '2026-03')
    proof = verify_source(content, result, result)
    assert proof['status'] == 'BLOCKED'
    assert any(f['code'] == 'UNACCOUNTED_SOURCE_ROW' and f['row'] == 3 for f in proof['failures'])


def test_personal_opinion_completion_wakes_loop_with_actionable_result(client, scope, monkeypatch):
    from test_material_guidance_v2 import request_for, configure, install
    from app.material_guidance import GuidanceRequest
    body = request_for(client, scope)
    svc, typed = client.app.state.service, Scope(**scope)
    configure(svc, monkeypatch, agent_mode='gateway')
    calls = install(client, monkeypatch)
    helper = svc.material_guidance
    result = helper.save_opinion(GuidanceRequest(**body, user_text='把这两笔放到2月'), 'alice', 'accountant')
    # Finish the legacy task, then let the new loop observe its persisted result.
    # Direct projection remains available while processing is withholding tasks.
    source = svc.store.get_object(result['job']['data']['binding']['artifact']['id'], typed) if 'binding' in result['job']['data'] else svc.store.get_object(body['artifact_id'], typed)
    object.__setattr__(svc.store.database.settings, 'agent_loop_enabled', True)
    first = svc.material_agent.enqueue(typed, 'alice')[0]
    before = svc.material_agent.fingerprint(typed, source)
    assert helper.process_one() and len(calls) == 1
    assert svc.material_agent.fingerprint(typed, source) != before
    assert svc.material_agent.enqueue(typed, 'alice')[0]['object_id'] != first['object_id']
    task = next(t for t in svc.material_agent.issue_view(typed, actor_id='alice')['tasks'] if t['id'] == body['task_id'])
    assert task['handling']['owner'] == 'USER'
    assert task['handling']['state'] == 'NEEDS_INPUT'


def test_identical_reread_does_not_revise_facts_or_invalidate_confirmations(client, scope):
    svc, typed, source = prepare(client, scope)
    before = svc.material_agent.facts(typed, source)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('reread_source', 'verify_extraction', 'apply_extraction', 'verify_extraction')
    for _ in range(4): assert svc.material_agent.step()
    assert svc.store.get_object(source['object_id'], typed) == source
    assert svc.material_agent.facts(typed, source) == before
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['data']['steps'][2]['result']['unchanged'] is True
    assert job['data']['proof']['status'] == 'PASS'


@pytest.mark.parametrize('change', ['amount', 'identity', 'extra_row'])
def test_duplicate_invoice_detail_sheet_must_reconcile(change):
    from app.tabular import extract_workbook, ParseOptions
    from app.source_checks import verify_source
    header = ['数电发票号码', '开票日期', '金额', '税额', '价税合计', '销售方纳税人名称']
    row = ['260000000001', '2026-03-08', '100.00', '13.00', '113.00', '供应商甲']
    details = deepcopy(row)
    good = xlsx_fixture([('发票基础信息', [header, row]), ('信息汇总表', [header, details])])
    reference = extract_workbook(good, ParseOptions(document_kind='purchase_invoices'), '2026-03')
    assert verify_source(good, reference, reference)['status'] == 'PASS'
    if change == 'amount': details[2] = '200.00'
    if change == 'identity': details[5] = '错误供应商'
    rows = [header, details] + ([row] if change == 'extra_row' else [])
    content = xlsx_fixture([('发票基础信息', [header, row]), ('信息汇总表', rows)])
    reference = extract_workbook(content, ParseOptions(document_kind='purchase_invoices'), '2026-03')
    assert verify_source(content, reference, reference)['status'] == 'BLOCKED'


def test_revoked_worker_authority_stops_before_model_call(client, scope):
    svc, typed, _ = prepare(client, scope)
    svc.material_agent.enqueue(typed, 'alice')
    object.__setattr__(svc.store.database.settings, 'require_auth', True)
    calls = []
    svc.material_agent.reader = lambda packet: calls.append(packet)
    assert not svc.material_agent.step()
    assert not calls
    assert svc.store.list_objects('MaterialAgentRun', typed)[-1]['status'] == 'BLOCKED'


def test_source_changes_during_model_call_discard_result(client, scope):
    svc, typed, source = prepare(client, scope)
    before = svc.material_agent.facts(typed, source)
    job = svc.material_agent.enqueue(typed, 'alice')[0]
    def changed(packet):
        (svc.store.database.settings.storage_path / source['data']['storage_path']).write_bytes(b'changed')
        return {'tool': 'verify_extraction', 'reason': '测试变更'}, {'mock': True}
    svc.material_agent.reader = changed
    assert svc.material_agent.step()
    assert svc.store.get_object(job['object_id'], typed)['status'] == 'STALE'
    assert svc.material_agent.facts(typed, source) == before


def test_transient_provider_failure_retries_with_bounded_backoff(client, scope):
    from app.ontology.gateway import GatewayFailure
    svc, typed, _ = prepare(client, scope)
    job = svc.material_agent.enqueue(typed, 'alice')[0]
    def unavailable(packet):
        raise GatewayFailure('Transport unavailable', 'PROVIDER_UNREACHABLE')
    svc.material_agent.reader = unavailable
    for attempt in range(3):
        assert svc.material_agent.step()
        current = svc.store.get_object(job['object_id'], typed)
        if attempt < 2:
            assert current['status'] == 'QUEUED'
            assert not svc.material_agent.step()  # Do not spin or call during backoff.
            svc.store.revise_object(current['object_id'], current['version'], typed,
                {**current['data'], 'retry_after': 0}, status='QUEUED', created_by='test')
    assert current['status'] == 'FAILED'
    svc.material_agent.enqueue(typed, 'alice', retry_id=job['object_id'])
    svc.material_agent.reader = reader('inspect_source')
    assert svc.material_agent.step()
    current = svc.store.get_object(job['object_id'], typed)
    assert len(current['data']['steps']) == 4
    assert current['data']['model_failures'] == 0


def test_verified_tax_period_context_releases_only_business_period_question(client, scope):
    from test_tabular_ingestion import uploaded, parse
    content = xlsx_fixture([('发票', [
        ['税款所属期：2026年03月'],
        ['数电发票号码', '开票日期', '金额', '税额', '价税合计', '销售方纳税人名称'],
        ['260000000001', '2026-02-20', '100.00', '13.00', '113.00', '供应商甲'],
    ])])
    source = uploaded(client, scope, content)
    source = parse(client, scope, source).json()['effect']['artifact']
    svc, typed = client.app.state.service, Scope(**scope)
    object.__setattr__(svc.store.database.settings, 'agent_loop_enabled', True)
    before = next(t for t in svc.material_agent.issue_view(typed)['tasks'] if t['kind'] == 'ISSUE')
    assert before['triage']['route'] == 'SYSTEM'
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('verify_extraction', 'search_related', 'inspect_issues', 'finish')
    for _ in range(4): assert svc.material_agent.step()
    job = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    assert job['status'] == 'NEEDS_USER', job['data']['steps']
    after = next(t for t in wb(client, scope)['material_review']['tasks'] if t['kind'] == 'ISSUE')
    assert after['triage']['matched_rule'] == 'BUSINESS_PERIOD'
    assert after['handling']['owner'] == 'USER'
    assert len(after['record_ids']) == 1
    assert svc.material_agent.facts(typed, source)[0]['data']['normalized_value']['invoice_date'] == '2026-02-20'
    svc.store.create_initial_object('MaterialGuidanceOpinion', typed,
        {'task_id': after['id'], 'text': '请继续核对归属期间'}, status='SAVED_NOT_EXECUTED', created_by='alice')
    feedback = next(t for t in svc.material_agent.issue_view(typed)['tasks'] if t['kind'] == 'ISSUE')
    assert feedback['source_reading_verified']
    assert feedback['triage']['matched_rule'] == 'BUSINESS_PERIOD'
    svc.store.revise_object(source['object_id'], source['version'], typed, {**source['data'], 'changed': True}, status='ACTIVE', created_by='test')
    stale = next(t for t in svc.material_agent.issue_view(typed)['tasks'] if t['kind'] == 'ISSUE')
    assert not stale['source_reading_verified'] and stale['triage']['route'] == 'SYSTEM'


def test_business_feedback_reuses_reading_proof_but_rechecks_issues(client, scope):
    svc, typed, source = prepare(client, scope)
    svc.material_agent.enqueue(typed, 'alice')
    svc.material_agent.reader = reader('verify_extraction', 'search_related', 'inspect_issues', 'finish')
    for _ in range(4): assert svc.material_agent.step()
    original = svc.store.list_objects('MaterialAgentRun', typed)[-1]
    svc.store.create_initial_object('MaterialGuidanceOpinion', typed,
        {'task_id': 'business-question', 'text': '费用归属需要核对'}, status='SAVED_NOT_EXECUTED', created_by='alice')
    fresh = svc.material_agent.enqueue(typed, 'alice')[0]
    assert fresh['object_id'] != original['object_id']
    assert fresh['data']['proof_from'] == original['object_id']
    assert fresh['data']['proof']['status'] == 'PASS'
    assert fresh['data']['issues'] is None and fresh['data']['searched'] is False
    assert svc.material_agent.reading_proof(typed, source, svc.store.list_objects('MaterialAgentRun', typed))
    fact = svc.material_agent.facts(typed, source)[0]
    data = deepcopy(fact['data']); data['normalized_value']['invoice_date'] = '2026-02-01'
    svc.store.revise_object(fact['object_id'], fact['version'], typed, data, status=fact['status'], created_by='test')
    assert svc.material_agent.reading_proof(typed, source, svc.store.list_objects('MaterialAgentRun', typed)) is None


def test_pdf_evidence_runs_outside_write_transaction_without_replacing_facts(client, scope, monkeypatch):
    from test_local_pdf_ocr import pages, parse_pages
    svc, typed, source=prepare(client, scope)
    baseline=deepcopy(svc.material_agent.facts(typed,source))
    svc.material_agent.enqueue(typed,'alice')
    def evidence(_):
        with svc.store.database.connect() as connection:
            assert not connection.in_transaction
        return {'reading':parse_pages(pages())}
    monkeypatch.setattr(svc.material_agent,'_pdf_evidence',evidence)
    svc.material_agent.reader=reader('verify_extraction','reread_source','suspend')
    for _ in range(3):assert svc.material_agent.step()
    job=svc.store.list_objects('MaterialAgentRun',typed)[-1]
    assert job['status']=='BLOCKED'
    assert job['data']['pdf_reading']['statement']['totals']['total_count']==2
    assert job['data']['candidate'] is None
    assert job['data']['proof']['arithmetic_status']=='PASS'
    assert svc.material_agent.facts(typed,source)==baseline
    assert '本地 OCR' in job['data']['message']


def test_ocr_missing_dependency_is_a_saved_tool_error(client, scope, monkeypatch):
    svc,typed,source=prepare(client,scope);svc.material_agent.enqueue(typed,'alice')
    monkeypatch.setattr(svc.material_agent,'_pdf_evidence',lambda source:{'error':'本地 OCR 未安装'})
    svc.material_agent.reader=reader('verify_extraction','reread_source','suspend')
    for _ in range(3):assert svc.material_agent.step()
    job=svc.store.list_objects('MaterialAgentRun',typed)[-1]
    assert job['status']=='BLOCKED' and job['data']['message']=='本地 OCR 未安装'



def test_ocr_engine_exception_consumes_step_and_reaches_bounded_stop(client, scope, monkeypatch):
    svc,typed,source=prepare(client,scope);svc.material_agent.enqueue(typed,'alice')
    def broken(_): raise OSError('private engine path must not leave server')
    monkeypatch.setattr(svc.material_agent,'_pdf_evidence',broken)
    svc.material_agent.reader=reader('verify_extraction','reread_source','suspend')
    for _ in range(3):assert svc.material_agent.step()
    job=svc.store.list_objects('MaterialAgentRun',typed)[-1]
    assert job['status']=='BLOCKED' and len(job['data']['steps'])==3
    assert job['data']['steps_this_run']==3
    assert 'private engine' not in str(job['data'])



def test_ocr_only_finish_rejection_points_to_pause_not_endless_verify(client, scope, monkeypatch):
    from test_local_pdf_ocr import pages, parse_pages
    svc,typed,source=prepare(client,scope);svc.material_agent.enqueue(typed,'alice')
    monkeypatch.setattr(svc.material_agent,'_pdf_evidence',lambda source:{'reading':parse_pages(pages())})
    svc.material_agent.reader=reader('verify_extraction','reread_source','finish','suspend')
    for _ in range(4):assert svc.material_agent.step()
    job=svc.store.list_objects('MaterialAgentRun',typed)[-1]
    assert job['data']['steps'][-2]['result']['missing_tools']==['suspend']
    assert job['status']=='BLOCKED' and '本地 OCR' in job['data']['message']
