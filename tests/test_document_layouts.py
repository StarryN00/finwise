from decimal import Decimal
import pytest
from app.tabular import ParseOptions, extract_workbook, ExtractionError
from test_tabular_ingestion import xlsx_fixture


def extract(rows, kind):
    return extract_workbook(xlsx_fixture([('资料', rows)]), ParseOptions(document_kind=kind), '2026-01')


def test_single_amount_bank_is_located_and_account_remains_missing():
    result = extract([['总收入(¥)：20.00 总支出(¥)：10.00 总收入笔数:1 总支出笔数:1'],
        ['序号','交易时间','币种','交易类型','交易金额','余额'],
        ['1','2026-01-01','人民币','收入','20.00','30.00'],
        ['2','2026-01-02','人民币','支出','10.00','20.00']], 'bank_statement')
    assert len(result['records']) == 2
    a,b = result['records']
    assert b['normalized_value']['payment_total'] == '10.00'
    assert b['field_sources']['expense']['region'] == '资料!E4'
    assert any('账户' in i for i in a['extraction_issues'])
    assert result['checks']['balance_continuity'] is True


def test_single_amount_totals_and_continuity_are_not_ignored():
    rows=[['总收入(¥)：20.00 总支出(¥)：10.00 总收入笔数:1 总支出笔数:1'],
        ['序号','交易时间','币种','交易类型','交易金额','余额'],
        ['1','2026-01-01','人民币','收入','20','30'],['2','2026-01-02','人民币','支出','10','99']]
    assert any('余额' in e for e in extract(rows,'bank_statement')['records'][1]['extraction_issues'])


def test_unit_medical_is_a_unit_total_not_a_person():
    r=extract([['险种类型','单位缴费基数总额','个人缴费基数总额','单位应缴金额','个人应缴金额','应费款所属期','缴费人数'],
        ['医疗','1000','1000','70','20','202601','1']], 'social_security')['records'][0]
    assert r['normalized_value']['aggregation_level'] == 'UNIT'
    assert r['normalized_value']['period'] == '2026-01'
    assert r['normalized_value']['total'] == '90.00'
    assert 'person_id' not in r['normalized_value']
    assert r['extraction_issues'] == []


def test_acceptance_snapshot_never_uses_issue_date_as_business_date():
    rows=[['票据（包）号','子票区间','出票日','到期日','票据（包）金额','票据状态'],
          ['123','001,010','20260101','20260701','10','已收票'],
          ['123','011,020','20260101','20260701','10','已收票']]
    r=extract(rows,'electronic_acceptance')['records']
    assert len(r)==2 and r[0]['source_anchor']!=r[1]['source_anchor']
    assert r[0]['normalized_value']['issue_date']=='2026-01-01'
    assert r[0]['normalized_value']['transaction_date'] is None
    assert r[0]['period_check']=='PERIOD_EXCEPTION'


def test_endorsement_retains_both_dates_and_source():
    r=extract([['票据（包）号','子票区间','出票日','到期日','票据（包）金额','票据状态','背书日期','背书人名称','被背书人名称'],
        ['123','001,010','20251101','20260501','10','已收票','20260113','甲','乙']], 'electronic_acceptance')['records'][0]
    assert r['normalized_value']['transaction_date']=='2026-01-13'
    assert r['normalized_value']['issue_date']=='2025-11-01'
    assert r['field_sources']['transaction_date']['region']=='资料!G2'
    assert r['period_check']=='PASS'


def test_unknown_pdf_fails_explicitly():
    with pytest.raises(ExtractionError):
        extract_workbook(b'%PDF-unknown',ParseOptions(document_kind='bank_statement'),'2026-01')


@pytest.mark.parametrize('period',['202601-202603','202601/202602','20260199'])
def test_medical_rejects_ambiguous_period(period):
    r=extract([['险种类型','单位应缴金额','个人应缴金额','应费款所属期'],['医疗','70','20',period]],'social_security')['records'][0]
    assert r['period_check']=='PERIOD_EXCEPTION'


def test_medical_period_range_is_not_collapsed():
    r=extract([['险种类型','单位应缴金额','个人应缴金额','应费款所属期','起始费款所属期','截止费款所属期'],['医疗','70','20','202601','202512','202601']], 'social_security')['records'][0]
    assert r['period_check']=='PERIOD_EXCEPTION'


@pytest.mark.parametrize('sub,amount,date',[('010,001','10','20260113'),('001,010','0','20260113'),('001,010','10','20251013')])
def test_invalid_bill_range_amount_or_event_date(sub,amount,date):
    r=extract([['票据（包）号','子票区间','出票日','到期日','票据（包）金额','票据状态','背书日期'],
        ['123',sub,'20251101','20260501',amount,'已收票',date]],'electronic_acceptance')['records'][0]
    assert r['extraction_issues'] and r['extraction_confidence']==0


def test_overlapping_bill_ranges_are_both_flagged():
    rows=[['票据（包）号','子票区间','出票日','到期日','票据（包）金额','票据状态','背书日期'],
        ['123','001,010','20251101','20260501','10','已收票','20260113'],
        ['123','006,015','20251101','20260501','10','已收票','20260113']]
    assert all(any('重叠' in e for e in r['extraction_issues']) for r in extract(rows,'electronic_acceptance')['records'])


def test_pdf_layout_balance_and_wrapped_summary(monkeypatch):
    import pypdf
    from types import SimpleNamespace
    text='''中国银行 Account No. Previous Page Balance Debit Total Credit Total 人民币(CNY)
账号 123456 起始日期20260101 截止日期20260131 承前页余额 0.18
|序号|记账日|起息日|交易类型|凭证|凭证号码/业务编号/用途/摘要|借方发生额|贷方发生额|余额|机构/柜员/流水|备注|
|1|260128|260128|代收费||网银服务年|0.18||0.00|流水1||
||||||费||||||
借方合计 0.18 贷方合计 0.00 本页余额 0.00 本对账期末余额 0.00'''
    def run(value):
        monkeypatch.setattr(pypdf,'PdfReader',lambda _:SimpleNamespace(is_encrypted=False,pages=[SimpleNamespace(extract_text=lambda:value)]))
        return extract_workbook(b'%PDF-fixture',ParseOptions(document_kind='bank_statement'),'2026-01')
    r=run(text)['records'][0]
    assert r['normalized_value']['payment_total']=='0.18'
    assert r['normalized_value']['summary']=='网银服务年费'
    assert '至文本' in r['field_sources']['summary']['region']
    with pytest.raises(ExtractionError):run(text.replace('|0.18||0.00|','|0.18|||'))
    with pytest.raises(ExtractionError):run(text.replace('|记账日|起息日|','|起息日|记账日|'))
