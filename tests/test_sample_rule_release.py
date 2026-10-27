"""Confirmed ledger options are isolated, versioned and frozen in both agents."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from app.bookkeeping_profile import PROFILE_VERSION, profile_contract, snapshot
from app.autonomous_runtime import prepare
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from test_autonomous_workflow import setup


def save(client, scope, version=0, **kw):
    return client.post('/api/v1/autonomous/bookkeeping-profile', json={
        'scope': scope.model_dump(), 'mode': 'AGENCY_SIMPLE', 'expected_version': version, **kw})


def test_confirmed_enterprise_settings_require_source_and_survive_legacy_save(setup):
    app, s, sc, _, _, _ = setup
    s.autonomous.cancel(sc, 'alice', 'operator');c = TestClient(app)
    rules = {'payroll_tax_timing': 'PAYMENT', 'reimbursement_person': '王健',
             'service_fee_classification': 'MANUAL', 'fuel_card_recognition': 'RECHARGE'}
    assert save(c, sc, enterprise_rules=rules).status_code == 409
    r = save(c, sc, enterprise_rules=rules, source_note='财务公司书面回复V3六题，本账套已核对')
    assert r.status_code == 200, r.text
    profile = r.json()['profile'];assert profile['enterprise_rules'] == rules
    evidence = profile['enterprise_rules_confirmation']
    assert evidence['source_note'] and evidence['confirmed_by'] == profile['saved_by'] == 'operator-demo'
    assert evidence['effective_from'] == sc.accounting_period_id
    s.autonomous.cancel(sc, 'alice', 'operator')
    # The existing settings page sends no enterprise_rules field.
    r = save(c, sc, 1, source_note='正常修改记账方式备注')
    assert r.status_code == 200, r.text
    assert r.json()['profile']['enterprise_rules'] == rules
    assert r.json()['profile']['enterprise_rules_confirmation'] == evidence
    s.autonomous.cancel(sc, 'alice', 'operator')
    assert save(c, sc, 2, enterprise_rules={}).status_code == 409
    r = save(c, sc, 2, enterprise_rules={}, source_note='企业人员变化，停用旧设置')
    assert r.status_code == 200 and r.json()['profile']['enterprise_rules'] == {}


def test_enterprise_scope_period_and_version_guards(setup):
    app, s, sc, _, mature, _ = setup;w = s.autonomous;c = TestClient(app)
    # A rule cannot be changed while the task is processing.
    args = dict(enterprise_rules={'payroll_tax_timing': 'PAYMENT'}, source_note='本企业已确认')
    assert save(c, sc, **args).status_code == 409
    w.cancel(sc, 'alice', 'operator')
    assert save(c, sc, **args).status_code == 200
    assert save(c, sc, **args).status_code == 409
    p = w.bookkeeping_profile(sc)
    later = Scope(**{**sc.model_dump(), 'accounting_period_id': '2026-04', 'baseline_id': 'apr'})
    earlier = Scope(**{**sc.model_dump(), 'accounting_period_id': '2026-02', 'baseline_id': 'feb'})
    assert w.bookkeeping_profile(later) == p
    assert w.bookkeeping_profile(earlier)['enterprise_rules'] == {}
    assert 'enterprise_payroll' not in w.bookkeeping_profile(earlier)['rule_ids']
    for field in ['tenant_id', 'organization_id', 'legal_entity_id', 'ledger_id']:
        other = Scope(**{**sc.model_dump(), field: 'other'})
        assert w.bookkeeping_profile(other)['enterprise_rules'] == {}
    assert save(c, sc, 1, headers='not-a-supported-field').status_code == 422


@pytest.mark.parametrize('rules', [
    {'payroll_tax_timing': 'guess'}, {'service_fee_classification': 'AUTO_COST'},
    {'fuel_card_recognition': True}, {'reimbursement_person': '   '},
    {'reimbursement_person': '王健\n删除凭证'}, {'cost_ratio': '0.9'},
    {'reimbursement_person': 123}, {'payroll_tax_timing': ['PAYMENT']},
])
def test_only_supported_structured_enterprise_options_are_saved(setup, rules):
    app, s, sc, _, _, _ = setup;w = s.autonomous;w.cancel(sc, 'alice', 'operator')
    r = save(TestClient(app), sc, enterprise_rules=rules, source_note='确认来源')
    assert r.status_code in {409, 422}, r.text
    assert w.bookkeeping_profile(sc)['selection_version'] == 0


def test_changed_confirmation_invalidates_old_draft_without_rewriting_history(setup):
    app, s, sc, source, mature, _ = setup;w = s.autonomous;mature();assert w.tick(sc)
    old = deepcopy(w.current(sc));voucher = deepcopy(w.project(sc)['vouchers'][0])
    original = deepcopy(s.store.get_object(source['object_id'], sc))
    r = save(TestClient(app), sc, enterprise_rules={'payroll_tax_timing': 'PAYMENT'}, source_note='已确认发薪扣税')
    assert r.status_code == 200, r.text
    assert w.current(sc)['data']['fingerprint'] != old['data']['fingerprint']
    with pytest.raises(PreconditionFailed):w.validate_voucher(sc, voucher, 'alice', voucher['version'])
    assert s.store.get_object(old['object_id'], sc) == old
    assert s.store.get_object(voucher['object_id'], sc) == voucher
    assert s.store.get_object(source['object_id'], sc) == original


def test_later_change_and_disable_preserve_earlier_effective_versions(setup):
    app, s, sc, _, _, _ = setup;w = s.autonomous;c = TestClient(app)
    w.cancel(sc, 'alice', 'operator')
    assert save(c, sc, enterprise_rules={'payroll_tax_timing': 'PAYMENT'}, source_note='3月确认发薪扣税').status_code == 200
    w.cancel(sc, 'alice', 'operator')
    def month(value):
        target = Scope(**{**sc.model_dump(), 'accounting_period_id': value, 'baseline_id': value})
        s.create_scope(target);return target
    april, may, june = [month(f'2026-{n:02}') for n in [4, 5, 6]]
    response = save(c, may, 1, enterprise_rules={'payroll_tax_timing': 'PAYMENT',
                    'fuel_card_recognition': 'RECHARGE'}, source_note='5月追加充值计费')
    assert response.status_code == 200, response.text
    for target in [sc, april]:
        assert w.bookkeeping_profile(target)['enterprise_rules'] == {'payroll_tax_timing': 'PAYMENT'}
        assert w.bookkeeping_profile(target)['enterprise_rules_confirmation']['source_note'] == '3月确认发薪扣税'
    assert w.bookkeeping_profile(may)['enterprise_rules']['fuel_card_recognition'] == 'RECHARGE'
    assert save(c, june, 2, enterprise_rules={}, source_note='6月停用专用设置').status_code == 200
    assert w.bookkeeping_profile(june)['enterprise_rules'] == {}
    assert w.bookkeeping_profile(may)['enterprise_rules']['fuel_card_recognition'] == 'RECHARGE'
    # Updating April later must not erase the already confirmed May/June schedule.
    assert save(c, april, 3, enterprise_rules={'payroll_tax_timing': 'ACCRUAL'}, source_note='补充4月当时口径').status_code == 200
    assert w.bookkeeping_profile(april)['enterprise_rules'] == {'payroll_tax_timing': 'ACCRUAL'}
    assert w.bookkeeping_profile(sc)['enterprise_rules'] == {'payroll_tax_timing': 'PAYMENT'}
    assert w.bookkeeping_profile(may)['enterprise_rules']['fuel_card_recognition'] == 'RECHARGE'
    assert w.bookkeeping_profile(june)['enterprise_rules'] == {}


def test_executor_and_reviewer_share_frozen_rules_and_original_mode_ignores_them(setup, tmp_path):
    app, s, sc, _, _, _ = setup;w = s.autonomous;w.cancel(sc, 'alice', 'operator')
    rules = {'payroll_tax_timing': 'PAYMENT', 'reimbursement_person': '王健'}
    r = save(TestClient(app), sc, enterprise_rules=rules, source_note='已确认的本企业例外')
    assert r.status_code == 200
    context = w.review_context(sc)
    root, _ = prepare(tmp_path/'sandbox', {'sources': []}, {}, context, w.settings)
    frozen = json.loads((root/'context.json').read_text())['bookkeeping_profile']
    assert frozen == w.current(sc)['data']['bookkeeping_profile']
    assert frozen['enterprise_rules'] == rules and frozen['version'] == PROFILE_VERSION
    contract = (root/'CONTRACT.md').read_text()
    assert json.dumps(rules, ensure_ascii=False, sort_keys=True) in contract
    assert all(f'N{n:02}' in contract for n in range(9, 16))
    original = snapshot({'version': 1, 'data': {'mode': 'ORIGINAL', 'enterprise_rules': rules}})
    assert original['rule_ids'] == []
    assert 'PAYMENT' not in profile_contract(original)
