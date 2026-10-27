from copy import deepcopy

from app.stage23_pilot import check_delivery
from test_monthly_agent import validation_fixture


def fixture(monkeypatch):
    delivery, tables = validation_fixture()
    monkeypatch.setattr('app.stage23_pilot.read_tables', lambda *_: tables)
    delivery['voucher_assessments'] = [{
        'voucher': '记-001', 'status': 'READY_FOR_REVIEW', 'reason': '业务依据已核对',
        'evidence': [{'source_id': 'journal', 'sheet': 'Sheet', 'row': 1}], 'finding_ids': []}]
    return delivery, {'period': '2026-08', 'sources': [{'id': s, 'path': s, 'sha256': 'hash'} for s in tables]}


def test_business_gap_cannot_be_promoted_to_review_ready(monkeypatch, tmp_path):
    d, manifest = fixture(monkeypatch)
    monkeypatch.setattr('app.stage23_pilot.sha256', lambda _: 'hash')
    assert check_delivery(tmp_path, manifest, d, {})['passed']
    d['findings'] = [{'id': 'missing', 'title': '缺业务依据', 'detail': '已有资料中没有依据',
                      'evidence': [{'source_id': 'journal', 'sheet': 'Sheet', 'row': 1}],
                      'affected_vouchers': ['记-001'], 'needs_user': True}]
    assert not check_delivery(tmp_path, manifest, d, {})['passed']
    d['voucher_assessments'][0].update(status='NEEDS_EVIDENCE', finding_ids=['missing'])
    assert check_delivery(tmp_path, manifest, d, {})['passed']


def test_duplicate_or_missing_business_reviews_fail(monkeypatch, tmp_path):
    d, manifest = fixture(monkeypatch)
    monkeypatch.setattr('app.stage23_pilot.sha256', lambda _: 'hash')
    d['voucher_assessments'].append(deepcopy(d['voucher_assessments'][0]))
    assert not check_delivery(tmp_path, manifest, d, {})['passed']
    d['voucher_assessments'] = []
    assert not check_delivery(tmp_path, manifest, d, {})['passed']


def test_changed_source_hash_blocks_delivery(monkeypatch, tmp_path):
    d, manifest = fixture(monkeypatch)
    monkeypatch.setattr('app.stage23_pilot.sha256', lambda _: 'changed')
    result = check_delivery(tmp_path, manifest, d, {})
    assert not result['passed'] and not result['source_integrity']
