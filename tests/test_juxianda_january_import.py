import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app.auth import create_user, grant_scope
from app.config import Settings
from app.main import create_app
from scripts.import_juxianda_january import HISTORY, JANUARY, SCOPE, USER, run
from test_tabular_ingestion import INVOICE_HEADERS, xlsx_fixture


def test_fresh_january_import_keeps_history_separate_and_never_copies_march(tmp_path):
    source = tmp_path / 'sources'
    (source / '聚贤达1月材料').mkdir(parents=True)
    for name in HISTORY:
        (source / name).write_bytes(name.encode())
    for name in JANUARY:
        (source / '聚贤达1月材料' / name).write_bytes(name.encode())
    invoice = xlsx_fixture([('发票', [INVOICE_HEADERS,
        ['I-1', '2026-01-10', '100', '13', '13%', '供应商'],
        ['I-2', '2026-02-02', '100', '13', '13%', '供应商']])])
    (source / '聚贤达1月材料' / '聚贤达1月进项.xlsx').write_bytes(invoice)
    bank = xlsx_fixture([('银行', [['交易日期', '摘要', '支出', '收入', '余额'],
        ['2026-01-10', '采购付款', '113.00', None, '1000.00']])])
    (source / '聚贤达1月材料' / '2026.1月聚贤达南京银行流水.xls').write_bytes(bank)
    (source / '三月不允许导入.xlsx').write_bytes(b'leave untouched')
    original_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
    previous, target = tmp_path / 'previous', tmp_path / 'january'
    app = create_app(Settings(root=Path(__file__).resolve().parents[1],
        database_path=previous / 'finwise.db', storage_path=previous / 'artifacts'))
    old_scope = SCOPE.model_copy(update={'accounting_period_id': '2026-03', 'baseline_id': 'baseline-2026-03'})
    app.state.service.create_scope(old_scope)
    create_user(app.state.database, USER, 'OnlyFixture!2026', 'accountant')
    grant_scope(app.state.database, USER, old_scope)
    before = hashlib.sha256((previous / 'finwise.db').read_bytes()).hexdigest()

    report = run(source, previous, target)
    assert len(report['files']) == 17 and report['historical_files'] == 2
    assert [f['filename'] for f in report['files'][:2]] == HISTORY
    assert report['scope']['accounting_period_id'] == '2026-01'
    assert report['counts']['records'] == 3 and report['counts']['period_exceptions'] == 1
    assert report['baseline_status'] == 'DRAFT' and report['model_calls'] == 0
    assert report['march_imported'] is False and report['source_hashes_verified'] is True
    assert report['files'][-1]['observed_period'] == '2026-01~2026-02'
    assert report['files'][-1]['parse_status'] == 'RECEIVED'
    with sqlite3.connect(target / 'finwise.db') as connection:
        assert connection.execute('SELECT count(*) FROM auth_sessions').fetchone()[0] == 0
        grants = [json.loads(row[0]) for row in connection.execute('SELECT scope_json FROM auth_scope_grants')]
        assert grants == [SCOPE.model_dump()]
        actions = {row[0] for row in connection.execute('SELECT action FROM commands')}
        assert actions == {'parse_artifact'}
        bank_facts = [json.loads(row[0]) for row in connection.execute(
            "SELECT data_json FROM ontology_objects WHERE object_type='FactRecord' AND status='NEEDS_REVIEW'")
            if json.loads(row[0]).get('record_type') == 'PAYMENT']
        assert len(bank_facts) == 1
        assert bank_facts[0]['normalized_value']['bank_account_ref'] is None
        assert 'bank_account_ref：请确认流水所属的企业账户' in bank_facts[0]['extraction_issues']
        assert connection.execute("SELECT count(*) FROM ontology_objects WHERE object_type IN ('ModelRun','ProcessingGroup','VoucherVersion','DeliveryPackage')").fetchone()[0] == 0
    assert hashlib.sha256((previous / 'finwise.db').read_bytes()).hexdigest() == before
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in original_hashes.items())
    with pytest.raises(ValueError, match='新数据目录必须不存在'):
        run(source, previous, target)


def test_missing_original_stops_before_creating_new_dataset(tmp_path):
    source = tmp_path / 'sources'
    source.mkdir()
    with pytest.raises(FileNotFoundError):
        run(source, tmp_path / 'previous', tmp_path / 'must-not-exist')
    assert not (tmp_path / 'must-not-exist').exists()


@pytest.mark.parametrize('redirect_directory', [False, True])
def test_whitelisted_path_cannot_redirect_to_march(tmp_path, redirect_directory):
    source = tmp_path / 'sources'
    source.mkdir()
    for name in HISTORY:
        (source / name).write_bytes(name.encode())
    march = source / '三月'
    march.mkdir()
    january = source / '聚贤达1月材料'
    if redirect_directory:
        january.symlink_to(march, target_is_directory=True)
        (march / '聚贤达1月进项.xlsx').write_bytes(b'march original')
    else:
        january.mkdir()
        target = march / '三月原件.xlsx'
        target.write_bytes(b'march original')
        (january / '聚贤达1月进项.xlsx').symlink_to(target)
    with pytest.raises(ValueError, match='符号链接'):
        run(source, tmp_path / 'previous', tmp_path / 'must-not-exist')
    assert not (tmp_path / 'must-not-exist').exists()
