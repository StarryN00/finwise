"""版式驱动解析：别名表覆盖不到的表头，靠已确认的版式确定性解析。"""
from __future__ import annotations

import pytest

from app.profile_proposals import propose_mapping
from app.source_profiles import ProfileMapping, fingerprint
from app.tabular import ParseOptions, bank_statistics_row, extract_workbook, read_workbook
from test_tabular_ingestion import xlsx_fixture

# "借"/"贷" 两个单字列名不在别名表里，正好代表一类别名表接不住的真实导出。
TERSE = ['交易时间', '借', '贷', '账户余额', '对方姓名', '摘要']
TERSE_ROWS = [
    ['2026-01-02', '', '1000.00', '1000.00', '甲公司', '货款'],
    ['2026-01-03', '400.00', '', '600.00', '乙公司', '手续费'],
    ['2026-01-04', '', '250.00', '850.00', '丙公司', '退款'],
]


def workbook(rows, name='数据'):
    return xlsx_fixture([(name, rows)])


def parse(content, resolver=None, kind='bank_statement', period='2026-01'):
    options = ParseOptions(document_kind=kind, bank_account_ref='ACCT-1')
    return extract_workbook(content, options, period, resolver=resolver)


def resolver_for(mapping: ProfileMapping, kind='bank_statement'):
    def resolve(labels, document_kind):
        return mapping if document_kind == kind else None
    return resolve


# ---------- 未命中时的行为 ----------

def test_unknown_header_without_profile_is_unrecognised_not_an_exception():
    """别名表接不住时只标记工作表，不中断整份文件 —— 永不硬失败。"""
    result = parse(workbook([TERSE] + TERSE_ROWS))
    assert result['records'] == []
    assert result['sheets'][0]['status'] == 'UNRECOGNIZED'


def test_resolver_returning_none_keeps_the_same_unrecognised_outcome():
    result = parse(workbook([TERSE] + TERSE_ROWS), resolver=lambda labels, kind: None)
    assert result['sheets'][0]['status'] == 'UNRECOGNIZED'


# ---------- 版式生效 ----------

def test_profile_makes_an_unknown_header_parse_without_touching_alias_tables():
    mapping = ProfileMapping(header_row=1, fields={'transaction_date': [0], 'expense': [1],
                                                   'income': [2], 'balance': [3],
                                                   'counterparty': [4], 'summary': [5]})
    result = parse(workbook([TERSE] + TERSE_ROWS), resolver=resolver_for(mapping))
    assert len(result['records']) == 3
    assert result['sheets'][0]['mapping_origin'] == 'PROFILE'
    first = result['records'][0]['normalized_value']
    assert first['income'] == '1000.00' and first['expense'] == '0.00'
    assert first['counterparty'] == '甲公司' and first['summary'] == '货款'
    assert result['records'][1]['normalized_value']['expense'] == '400.00'


def test_profile_takes_precedence_over_alias_table():
    """别名表会把"交易时间"这一列当作日期，但这份导出里它只有时分秒。

    版式必须赢，否则就是"匹配成功却映射错列"的静默错误。
    """
    header = ['交易日', '交易时间', '支出金额', '收入金额', '账户余额']
    rows = [['2026-01-02', '09:15:00', '', '500.00', '500.00']]
    alias_only = parse(workbook([header] + rows))
    assert alias_only['records'][0]['extraction_issues']  # 别名表把时分秒当成了日期

    mapping = ProfileMapping(header_row=1, fields={'transaction_date': [0], 'expense': [2],
                                                   'income': [3], 'balance': [4]})
    with_profile = parse(workbook([header] + rows), resolver=resolver_for(mapping))
    record = with_profile['records'][0]
    assert record['extraction_issues'] == []
    assert record['normalized_value']['transaction_date'] == '2026-01-02'


def test_profile_declared_null_token_is_a_structural_zero():
    header = ['交易时间', '支出', '收入', '余额']
    rows = [['2026-01-02', '-', '100.00', '100.00']]
    mapping = ProfileMapping(header_row=1, null_tokens=['-'],
                             fields={'transaction_date': [0], 'expense': [1], 'income': [2], 'balance': [3]})
    record = parse(workbook([header] + rows), resolver=resolver_for(mapping))['records'][0]
    assert record['extraction_issues'] == []
    assert record['normalized_value']['expense'] == '0.00'


def test_undeclared_malformed_amount_stays_unknown_and_never_becomes_zero():
    header = ['交易时间', '支出', '收入', '余额']
    rows = [['2026-01-02', '待定', '100.00', '100.00']]
    mapping = ProfileMapping(header_row=1, null_tokens=['-'],
                             fields={'transaction_date': [0], 'expense': [1], 'income': [2], 'balance': [3]})
    record = parse(workbook([header] + rows), resolver=resolver_for(mapping))['records'][0]
    assert record['normalized_value']['expense'] is None
    assert any(issue.startswith('expense') for issue in record['extraction_issues'])


def test_direction_column_profile_splits_a_single_amount_column():
    header = ['交易时间', '交易金额', '交易类型', '交易后余额']
    rows = [['2026-01-02', '1000.00', '来账', '1000.00'],
            ['2026-01-03', '400.00', '往账', '600.00']]
    mapping = ProfileMapping(header_row=1, amount_model='DIRECTION_SINGLE',
                             direction_expense=['往账'], direction_income=['来账'],
                             fields={'transaction_date': [0], 'amount': [1], 'direction': [2], 'balance': [3]})
    records = parse(workbook([header] + rows), resolver=resolver_for(mapping))['records']
    assert [r['normalized_value']['income'] for r in records] == ['1000.00', '0.00']
    assert [r['normalized_value']['expense'] for r in records] == ['0.00', '400.00']
    assert all(not r['extraction_issues'] for r in records)


def test_direction_value_outside_the_declared_vocabulary_raises_an_issue():
    header = ['交易时间', '交易金额', '交易类型', '交易后余额']
    rows = [['2026-01-02', '1000.00', '冲正', '1000.00']]
    mapping = ProfileMapping(header_row=1, amount_model='DIRECTION_SINGLE',
                             direction_expense=['往账'], direction_income=['来账'],
                             fields={'transaction_date': [0], 'amount': [1], 'direction': [2], 'balance': [3]})
    record = parse(workbook([header] + rows), resolver=resolver_for(mapping))['records'][0]
    assert any(issue.startswith('direction') for issue in record['extraction_issues'])
    assert record['normalized_value']['expense'] is None


def test_signed_single_column_uses_the_sign_for_direction():
    header = ['交易时间', '交易金额', '交易后余额']
    rows = [['2026-01-02', '1000.00', '1000.00'], ['2026-01-03', '-400.00', '600.00']]
    mapping = ProfileMapping(header_row=1, amount_model='SIGNED_SINGLE',
                             fields={'transaction_date': [0], 'amount': [1], 'balance': [2]})
    records = parse(workbook([header] + rows), resolver=resolver_for(mapping))['records']
    assert records[0]['normalized_value']['income'] == '1000.00'
    assert records[1]['normalized_value']['expense'] == '400.00'


# ---------- 页脚统计行 ----------

def test_single_row_statistics_footer_is_a_reference_not_a_transaction():
    header = ['交易时间', '收入金额', '支出金额', '账户余额']
    rows = [['2026-01-02', 100, 0, 100],
            ['借方交易笔数', 9, '借方交易金额', 124280.67]]
    result = parse(workbook([header] + rows))
    assert [r['source_anchor']['row'] for r in result['records']] == [2]
    assert [r['reason'] for r in result['sheets'][0]['reference_rows']] == ['BANK_STATISTICS']


def test_statistics_detector_defers_to_the_paired_total_footer():
    """两行式页脚由既有配对逻辑处理，单行统计检测必须避让。"""
    assert bank_statistics_row(['总收入笔数', '总收入金额', '总支出笔数', '总支出金额', '', '', '', '']) is False
    assert bank_statistics_row(['借方交易笔数', 9, '借方交易金额', 1.0]) is True


# ---------- 提案器 ----------

def test_proposer_infers_columns_and_verifies_direction_by_balance():
    sheet = read_workbook(workbook([TERSE] + TERSE_ROWS))[0]
    proposal = propose_mapping(sheet, 'bank_statement')
    assert proposal.outcome == 'PROPOSAL'
    assert proposal.mapping.fields['expense'] == [1] and proposal.mapping.fields['income'] == [2]
    assert any('余额连续性' in line for line in proposal.evidence)


def test_proposer_corrects_direction_on_reverse_ordered_exports():
    """倒序导出若不先纠正时序，收付会被整体标反 —— 这是不会报错的错误。"""
    reversed_rows = list(reversed(TERSE_ROWS))
    sheet = read_workbook(workbook([TERSE] + reversed_rows))[0]
    proposal = propose_mapping(sheet, 'bank_statement')
    assert proposal.outcome == 'PROPOSAL'
    assert proposal.mapping.fields['expense'] == [1] and proposal.mapping.fields['income'] == [2]
    assert any('倒序' in line for line in proposal.evidence)


def continuous_rows(count: int, opening: float = 1000.0) -> list[list[str]]:
    """生成一段余额真正连续的流水；接缝断裂会让连续性校验失真。"""
    rows, balance = [], opening
    for index in range(count):
        incoming = index % 2 == 0
        amount = 100.0 + index
        balance = balance + amount if incoming else balance - amount
        rows.append([f'2026-01-{index + 2:02d}',
                     '' if incoming else f'{amount:.2f}',
                     f'{amount:.2f}' if incoming else '',
                     f'{balance:.2f}', '某公司', '往来'])
    return rows


def test_proposer_confidence_shrinks_when_evidence_is_thin():
    thin = read_workbook(workbook([TERSE] + continuous_rows(2)))[0]
    thick = read_workbook(workbook([TERSE] + continuous_rows(12)))[0]
    assert propose_mapping(thin, 'bank_statement').confidence < 70
    assert propose_mapping(thick, 'bank_statement').confidence >= 90


def test_proposer_abstains_when_balance_cannot_settle_the_direction():
    header = ['交易时间', '金额甲', '金额乙', '余额']
    rows = [['2026-01-02', '10.00', '20.00', '999.00'],
            ['2026-01-03', '30.00', '40.00', '111.00'],
            ['2026-01-04', '50.00', '60.00', '222.00']]
    proposal = propose_mapping(read_workbook(workbook([header] + rows))[0], 'bank_statement')
    assert proposal.outcome == 'ABSTAIN' and proposal.mapping is None


def test_proposer_abstains_for_document_kinds_it_does_not_cover():
    sheet = read_workbook(workbook([TERSE] + TERSE_ROWS))[0]
    assert propose_mapping(sheet, 'purchase_invoices').outcome == 'ABSTAIN'


def test_proposal_fingerprint_matches_the_header_it_was_derived_from():
    """提案的指纹必须能反过来命中同一张表头，否则版式永远复用不上。"""
    sheet = read_workbook(workbook([TERSE] + TERSE_ROWS))[0]
    proposal = propose_mapping(sheet, 'bank_statement')
    header = next(r for r in sheet['rows'] if r['row'] == proposal.header_row)
    assert fingerprint(header['values'], 'bank_statement') == fingerprint(TERSE, 'bank_statement')
