import pytest

from app.tabular import ParseOptions, extract_workbook
from test_tabular_ingestion import xlsx_fixture


BANK = ['交易时间', '收入金额', '支出金额', '账户余额', '对方账号', '对方户名', '对方开户行', '摘要']
FOOTER = ['总收入笔数', '总收入金额', '总支出笔数', '总支出金额', '', '', '', '']


def extract(rows, kind='bank_statement'):
    return extract_workbook(xlsx_fixture([('数据', rows)]), ParseOptions(document_kind=kind), '2026-01')


def test_bank_footer_is_reference_not_two_transactions_and_does_not_end_sheet():
    result = extract([BANK, ['2026-01-01', 100, 0, 100], FOOTER, ['1', 100, '0', 0],
                      ['2026-01-02', 0, 50, 50]])
    assert [r['source_anchor']['row'] for r in result['records']] == [2, 5]
    assert [r['reason'] for r in result['sheets'][0]['reference_rows']] == ['BANK_TOTAL_HEADER', 'BANK_TOTAL_VALUES']
    assert result['sheets'][0]['reference_rows'][1]['values'][1] == 100


@pytest.mark.parametrize('row', [
    ['2026-01-02', 0, 50, 50],  # Real transaction after a footer heading.
    ['1', 'bad amount', '0', 0],  # Invalid totals are not silently ignored.
    ['1', 100, '0', 0, 'counterparty-id'],
])
def test_ambiguous_footer_following_row_keeps_validation(row):
    result = extract([BANK, FOOTER, row])
    assert len(result['records']) == 1


def test_numeric_row_without_footer_context_is_not_discarded():
    result = extract([BANK, ['6', 228732, '9', 214736.2]])
    assert len(result['records']) == 1 and result['records'][0]['extraction_issues']


@pytest.mark.parametrize('kind', ['sales_invoices', 'purchase_invoices'])
def test_invoice_total_does_not_create_missing_date_or_number_issue(kind):
    headers = ['序号', '发票号码', '开票日期', '金额', '税额', '价税合计', '销方名称']
    result = extract([headers, ['1', 'INV', '2026-01-01', -100, -13, -113, '测试'],
                      ['合计行', None, None, -100, -13],
                      ['合计行', 'REAL', '2026-01-02', 100, 13, 113, '测试']], kind)
    assert [r['source_anchor']['row'] for r in result['records']] == [2, 4]
    assert any('红字' in x for x in result['records'][0]['extraction_issues'])
    assert result['sheets'][0]['reference_rows'][0]['row'] == 3


def test_reparse_supersedes_false_facts_preserves_history_and_is_idempotent(client, scope, monkeypatch):
    from app import tabular
    from app.ontology import service as service_module
    from app.ontology.contracts import Scope
    from test_tabular_ingestion import uploaded, parse
    content = xlsx_fixture([('数据', [BANK, ['2026-03-01', 100, 0, 100], FOOTER, ['1', 100, '0', 0]])])
    source = uploaded(client, scope, content)
    classify = tabular.bank_footer_header
    monkeypatch.setattr(tabular, 'bank_footer_header', lambda values: False)
    monkeypatch.setattr(service_module, 'PARSER_VERSION', 'tabular-v4')
    old = parse(client, scope, source, kind='bank_statement').json()['effect']
    assert len(old['facts']) == 3
    monkeypatch.setattr(tabular, 'bank_footer_header', classify)
    monkeypatch.setattr(service_module, 'PARSER_VERSION', 'tabular-v5')
    response = parse(client, scope, old['artifact'], kind='bank_statement', key='upgrade-footer')
    assert response.status_code == 200, response.text
    new = response.json()['effect']
    assert len(new['facts']) == 1 and new['facts'][0]['object_id'] == old['facts'][0]['object_id']
    store = client.app.state.service.store
    for fact in old['facts'][1:]:
        assert store.get_object(fact['object_id'], Scope(**scope))['status'] == 'SUPERSEDED'
    assert new['artifact']['data']['sha256'] == source['data']['sha256']
    repeat = parse(client, scope, new['artifact'], kind='bank_statement', key='repeat-footer').json()['effect']
    assert repeat['artifact']['version'] == new['artifact']['version']
    assert repeat['facts'] == new['facts']
    assert not store.list_objects('VoucherVersion', Scope(**scope))
