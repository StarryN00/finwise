from copy import deepcopy

import pytest

from app.local_pdf_ocr import LocalOCRError, HEADERS, parse_pages, compare_saved, money


def token(text, x, y, score=.99):
    return {'text':text,'box':[[x-20,y-8],[x+20,y-8],[x+20,y+8],[x-20,y+8]],'score':score}


def pages():
    head=[token('江苏银行对公账户对账单',100,10),token('起始日期：2026-08-01',100,30),
          token('终止日期：2026-08-31',100,50),token('期末余额：87.00',100,70),
          token('借方笔数：2借方发生总额：13.00贷方笔数：0贷方发生总额：0.00合计笔数：2',100,90)]
    cols=[token(h,100+i*100,150) for i,h in enumerate(HEADERS)]
    rows=[]
    for n,date,amount,balance in [(1,'2026-08-02','10.00','90.00'),(2,'2026-08-03','3.00','87.00')]:
        y=150+n*60
        for i,value in {0:str(n),1:date,3:'服务费',5:amount,7:balance,8:'123456',9:'对方单位'}.items():
            rows.append(token(value,100+i*100,y))
    return [head+cols+rows]


def saved(reading):
    return [{'source_anchor':{'row':r['sequence']},'normalized_value':{
        'transaction_date':r['transaction_date'],'summary':r['summary'], 'expense':r['debit'],
        'income':r['credit'],'balance':r['balance'],'counterparty':r['counterparty_name'],
        'counterparty_account':r['counterparty_account']}} for r in reading['statement']['rows']]


def test_complete_arithmetic_is_not_full_ocr_approval():
    r=parse_pages(pages());p=compare_saved(r,saved(r))
    assert p['records']==2 and p['matched_fields']==14
    assert p['arithmetic_status']=='PASS'
    assert p['status']=='BLOCKED'  # OCR agreement does not grant execution.


def test_original_date_is_not_changed_to_fit_header():
    p=pages();next(t for t in p[0] if t['text']=='2026-08-03')['text']='2026-09-03'
    r=parse_pages(p);f=saved(r);f[1]['normalized_value']['transaction_date']='2026-08-03'
    check=compare_saved(r,f)
    assert check['out_of_period_rows']==[2] and check['arithmetic_status']=='PASS'
    assert any(x.get('field')=='transaction_date' for x in check['failures'])
    assert r['statement']['rows'][1]['transaction_date']=='2026-09-03'


def test_missing_row_fails_counts_and_totals():
    p=pages();p[0]=[t for t in p[0] if t['box'][0][1]<250]
    r=parse_pages(p)
    assert not next(c for c in r['checks'] if c['name']=='笔数与表头一致')['passed']
    assert compare_saved(r,saved(r))['arithmetic_status']=='REVIEW'


def test_missing_date_cannot_silently_drop_amounts():
    p=pages();p[0]=[t for t in p[0] if t['text']!='2026-08-03']
    with pytest.raises(LocalOCRError):parse_pages(p)


def test_duplicate_sequence_and_unknown_layout_are_rejected():
    p=pages();next(t for t in p[0] if t['text']=='2')['text']='1'
    with pytest.raises(LocalOCRError,match='序号'):parse_pages(p)
    p=pages();p[0][0]['text']='其他银行'
    with pytest.raises(LocalOCRError,match='版式'):parse_pages(p)


def test_money_only_normalizes_group_separators_never_guesses_digits():
    assert money('560.393.12')=='560393.12'
    for bad in ['1,512.Q1','123.4','1,23.45','nan','40,62466']:
        with pytest.raises(LocalOCRError):money(bad)


def test_numeric_changes_and_account_names_are_compared_independently():
    r=parse_pages(pages());f=saved(r);f[0]['normalized_value'].update(expense='11.00',counterparty='错误单位')
    result=compare_saved(r,f)
    assert {x.get('field') for x in result['failures']}=={'expense','counterparty'}
    assert result['status']=='BLOCKED'


def test_uncertain_score_and_missing_sequence_remain_evidence():
    p=pages();p[0]=[t for t in p[0] if t['text']!='1'];next(t for t in p[0] if t['text']=='90.00')['score']=.6
    r=parse_pages(p)
    assert {w['code'] for w in r['warnings']}=={'SEQUENCE_NOT_READ','LOW_OCR_SCORE'}
    assert r['evidence'][0]['cells']['balance'][0]['box']
