import base64

from app.ontology.contracts import ArtifactInput, Scope
from conftest import command
from test_baseline_candidate import source
from test_tabular_ingestion import INVOICE_HEADERS, parse, uploaded, xlsx_fixture


def overview(client, scope):
    response = client.post('/api/v1/workbench', json={'scope': scope})
    assert response.status_code == 200
    return response.json()['data_readiness']


def test_readiness_classifies_files_without_turning_prior_bills_into_baseline(client, scope):
    content = xlsx_fixture([('发票', [INVOICE_HEADERS,
        ['I-1', '2026-03-01', '100', '13', None, '供应商'],
        ['I-2', '2026-03-02', '100', '13', None, '供应商'],
        ['I-3', '2026-02-28', '100', '13', '13%', '供应商']])])
    current = uploaded(client, scope, content)
    parse(client, scope, current)
    prior = uploaded(client, scope, b'prior bill', '2月承兑.xls', '2026-02')
    result = overview(client, scope)
    assert result['counts']['files'] == 2
    assert result['counts']['records'] == 3
    assert result['counts']['needs_review'] == 0
    assert result['counts']['extracted_pending'] == 2
    assert result['counts']['period_exceptions'] == 1
    assert result['counts']['verified_records'] == 0
    nodes = {n['id']: n for n in result['categories']}
    assert nodes['baseline']['artifact_ids'] == []
    assert nodes['unassigned']['artifact_ids'] == [prior['object_id']]
    assert nodes['purchase']['artifact_ids'] == [current['object_id']]
    tax_issues = [i for i in nodes['purchase']['issues'] if '税率' in i['title']]
    assert tax_issues == []
    assert result['usable_results'] == []
    assert result['baseline_sources']['balance'] == []


def test_readiness_tracks_baseline_purpose_without_granting_verification(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed)
    artifact = service.create_artifact(ArtifactInput(scope=typed, filename='余额.xlsx',
        content_base64=base64.b64encode(b'not a workbook').decode(),
        observed_period='2026-02', source_purpose='opening_balance'), actor_id='fixture')
    r = overview(client, scope)
    assert r['baseline_sources']['balance'] == [artifact['object_id']]
    assert r['usable_results'] == []
    assert r['counts']['verified_records'] == 0
    assert client.post('/api/v1/baseline/candidate', json={'scope': scope,
        'balance_artifact_id': artifact['object_id'], 'close_artifact_id': artifact['object_id']}).status_code != 200


def test_explicit_history_is_visible_but_not_a_verified_or_automatic_baseline(client, scope):
    service, typed = client.app.state.service, Scope(**{**scope, 'accounting_period_id': '2026-01'})
    service.create_scope(typed)
    artifact = service.create_artifact(ArtifactInput(scope=typed, filename='2025全年序时账.xls',
        content_base64=base64.b64encode(b'historical original').decode(),
        observed_period='2025-12', source_purpose='historical_reference'), actor_id='fixture')
    result = overview(client, typed.model_dump())
    assert result['categories'][0]['artifact_ids'] == [artifact['object_id']]
    assert result['baseline_sources'] == {'balance': [], 'close': []}
    assert result['usable_results'] == []
    assert result['counts']['records'] == 0


def test_historical_prerequisite_does_not_replace_current_period_progress(client, scope):
    service = client.app.state.service
    typed = Scope(**{**scope, 'accounting_period_id': '2026-01'})
    service.create_scope(typed)
    service.create_artifact(ArtifactInput(
        scope=typed, filename='2025全年序时账.xls',
        content_base64=base64.b64encode(b'historical original').decode(),
        observed_period='2025-12', source_purpose='historical_reference'), actor_id='fixture')
    service.historical.run_once()
    overview = service.workbench(typed)
    prerequisite = overview['progress']['prerequisite']
    assert prerequisite['status'] == 'ACTION_REQUIRED'
    assert prerequisite['does_not_block'] == ['资料整理', '资料核对']
    assert overview['progress']['current_stage'] == 'source'
    assert overview['progress']['stages'][1]['name'] == '资料分析'
    assert not overview['progress']['stages'][1]['summary'].startswith('历史')


def test_readiness_shows_human_baseline_proof_then_removes_stale_proof(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    service.create_scope(typed)
    rows = [['1001', '库存现金', '1000', '0', '1000', '0', '否', None],
            ['4001', '实收资本', '0', '1000', '0', '1000', '否', None]]
    a = source(service, typed, '期初.xlsx', rows)
    b = source(service, typed, '期末.xlsx', rows)
    candidate = service.baseline_candidate(typed, balance_artifact_id=a['object_id'], close_artifact_id=b['object_id'])
    baseline = service.workbench(typed)['baseline']
    payload = {**candidate['confirmation_payload'], 'completeness_confirmed': True}
    response = command(client, scope, 'confirm_baseline', baseline['object_id'], baseline['version'], 'confirmed-baseline-proof', payload)
    assert response.status_code == 200, response.text
    proof = overview(client, scope)['usable_results'][0]
    assert proof['kind'] == 'baseline' and proof['confirmed_by'] == 'alice'
    assert proof['confirmed_at'] and set(proof['source_ids']) == {a['object_id'], b['object_id']}
    service.archive_artifact(typed, artifact_id=a['object_id'], actor_id='fixture', expected_version=a['version'])
    assert not overview(client, scope)['usable_results']


def test_model_coverage_is_historical_not_verification_or_mock_success(client, scope):
    source_artifact = uploaded(client, scope, xlsx_fixture([('发票', [INVOICE_HEADERS,
        ['I-1', '2026-03-01', '100', '13', '13%', '供应商']])]))
    fact = parse(client, scope, source_artifact).json()['effect']['facts'][0]
    store, typed = client.app.state.service.store, Scope(**scope)
    data = {'stage': 'RULE_SUGGESTION', 'model_version': 'deepseek-chat',
            'gateway': {'mock': False}, 'input_summary': {'facts': [{'fact_id': fact['object_id']}]}}
    for status, mock in [('SUCCEEDED', True), ('PAUSED', False), ('SUCCEEDED', False)]:
        store.create_initial_object('ModelRun', typed, {**data, 'gateway': {'mock': mock}}, status=status)
    r = overview(client, scope)
    assert r['model_coverage']['real_successful_calls'] == 1
    assert r['model_coverage']['historical_fact_count'] == 1
    assert r['model_coverage']['current_verified_count'] == 0
    assert r['counts']['verified_records'] == 0
    assert r['counts']['extracted_pending'] == 1
    other = {**scope, 'legal_entity_id': 'other', 'baseline_id': 'other-base'}
    client.app.state.service.create_scope(Scope(**other))
    assert overview(client, other)['counts']['files'] == 0
    assert overview(client, other)['model_coverage']['real_successful_calls'] == 0


def test_archived_source_and_stale_reconciliation_are_not_usable(client, scope):
    service, typed = client.app.state.service, Scope(**scope)
    demo = service.create_procurement_demo(typed, variant='normal', actor_id='fixture')
    # Existing fixture safety gates, not a synthetic green UI status.
    group = service.store.get_object(demo['group']['object_id'], typed)
    assert group['data']['reconciliation_status'] == 'PASS'
    assert overview(client, scope)['counts']['verified_records'] == 4
    fact = demo['facts'][0]
    artifact = service.store.get_object(fact['data']['source_artifact_id'], typed)
    service.archive_artifact(typed, artifact_id=artifact['object_id'], expected_version=artifact['version'], actor_id='fixture')
    r = overview(client, scope)
    assert r['counts']['verified_records'] == 0
    assert fact['object_id'] not in [i['object_id'] for i in r['records']]


def test_verified_voucher_and_stage_are_withdrawn_on_fact_version_change(client, scope):
    from test_delivery_safety import ready_voucher
    service, typed, group, voucher = ready_voucher(client, scope)
    service.validate_draft(typed, voucher_id=voucher['object_id'], actor_id='reviewer', expected_version=voucher['version'])
    before = service.workbench(typed)
    assert before['data_readiness']['counts']['verified_records'] == 4
    proof = next(p for p in before['data_readiness']['usable_results'] if p['kind'] == 'voucher')
    assert proof['confirmed_by'] == 'reviewer' and proof['confirmed_at']
    assert next(s for s in before['progress']['stages'] if s['id'] == 'voucher')['status'] == 'COMPLETED'
    fact = service.store.list_objects('FactRecord', typed)[0]
    service.reparse_fact(typed, fact_id=fact['object_id'], expected_version=fact['version'], actor_id='alice',
                         parser_version='rechecked-v2', normalized_value={**fact['data']['normalized_value'], 'supplier_ref':'corrected'})
    after = service.workbench(typed)
    assert after['data_readiness']['counts']['verified_records'] == 0
    assert not any(p['kind'] == 'voucher' for p in after['data_readiness']['usable_results'])
    assert next(s for s in after['progress']['stages'] if s['id'] == 'voucher')['completed_count'] == 0
    service.reconcile_group(typed, group_id=group['object_id'], actor_id='alice')
    # Fresh group checks must not authorize the old voucher binding.
    assert not any(p['kind'] == 'voucher' for p in service.workbench(typed)['data_readiness']['usable_results'])
