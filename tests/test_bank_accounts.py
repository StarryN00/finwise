from copy import deepcopy
import pytest

from app.ontology.contracts import Scope
from app.bank_accounts import identify_account
from test_tabular_ingestion import uploaded, xlsx_fixture, parse
from conftest import command


def bank_file(account='001-234567890', holder='合成企业', bank='中国农业银行'):
    return xlsx_fixture([('账户明细', [
        [f'账号:{account}', f'户名:{holder}', '币种:人民币', f'开户银行:{bank}'],
        ['交易时间', '收入金额', '支出金额', '账户余额', '对方账号', '对方户名'],
        ['2026-03-08', '100', '0', '100', '999999999', '对手公司'],
        ['2026-04-02', '0', '10', '90', '888888888', '对手公司'],
    ])])


def test_header_identity_and_counterparty_exclusion():
    d=identify_account(bank_file(), '农业银行.xlsx')
    assert d['account_number']=='001-234567890'
    assert d['holder']=='合成企业' and d['currency']=='CNY'
    assert d['sources']['account_number']['region']=='账户明细!A1'
    assert identify_account(xlsx_fixture([('表', [['对方账号:999999999','对方开户行:中国银行']])]), '农业银行.xlsx')['account_number']==''
    assert identify_account(bank_file() + b'', '农业银行.xlsx')['bank_name']=='中国农业银行'
    assert identify_account(bank_file(),'南京银行流水.xls')['bank_hint']=='南京银行'
    assert identify_account(bank_file(),'泰隆银行流水.xls')['bank_hint']=='泰隆银行'


def test_register_associate_and_cross_period_reuse(client, scope):
    source=uploaded(client,scope,bank_file(),filename='农业银行.xlsx')
    result=parse(client,scope,source,'bank_statement').json()['effect']
    assert result['facts'][0]['data']['normalized_value']['bank_account_ref']=='001-234567890'
    assert result['facts'][0]['status']=='NEEDS_REVIEW'
    svc=client.app.state.service;s=Scope(**scope)
    candidate=svc.bank_accounts.view(s)['statements'][0]
    assert candidate['status']=='NEW'
    payload={'token':candidate['token'],'ownership_confirmed':True,'new_account':{k:candidate['identity'][k] for k in ('account_number','holder','bank_name','currency')}}
    a=result['artifact']
    r=command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'bank-confirm-one',payload)
    assert r.status_code==200,r.text
    effect=r.json()['effect'];assert effect['counts']['period_exception']==1
    assert effect['facts'][0]['status']=='PARSED'
    assert command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'bank-confirm-one',payload).json()['idempotent']
    assert not svc.store.list_objects('SourceVerification',s)
    assert svc.workbench(s)['baseline']['status']=='DRAFT'
    f=effect['facts'][0]
    assert command(client,scope,'reparse_fact',f['object_id'],f['version'],'reject-account-rewrite',{'parser_version':'forged-v2','normalized_value':{**f['data']['normalized_value'],'bank_account_ref':'77777777777'}}).status_code==409
    other={**scope,'accounting_period_id':'2026-04','baseline_id':'apr'}
    a2=uploaded(client,other,bank_file(),filename='农业银行.xlsx')
    r2=parse(client,other,a2,'bank_statement',key='parse-apr').json()['effect']
    assert r2['artifact']['data']['bank_account_binding']['automatic'] is True
    assert len(svc.bank_accounts.view(Scope(**other))['accounts'])==1
    foreign={**scope,'legal_entity_id':'other'}
    assert svc.bank_accounts.view(Scope(**foreign))['accounts']==[]
    task=next(t for t in svc.workbench(s)['material_review']['tasks'] if t['kind']=='VERIFY')
    f=effect['facts'][0]
    verified=command(client,scope,'verify_source_values',a['object_id'],effect['artifact']['version'],'verify-linked-fact',{'task_id':task['id'],'records':[{'object_id':f['object_id'],'version':f['version']}],'note':'已核对原始值'})
    assert verified.status_code==200,verified.text
    assert verified.json()['effect']['verified_count']==1
    assert svc.workbench(s)['baseline']['status']=='DRAFT'


def test_candidate_conflict_and_missing_metadata(client,scope):
    content=xlsx_fixture([('表',[['账号:00123456789','账号:00987654321']])])
    assert 'account_number' in identify_account(content,'农业银行.xlsx')['conflicts']
    s=Scope(**scope);svc=client.app.state.service;svc.create_scope(s)
    p=svc.workbench(s)['period']
    payload={'account_number':'00123456789','holder':'合成企业','bank_name':'中国农业银行','currency':'CNY','ownership_confirmed':True}
    assert command(client,scope,'register_bank_account',p['object_id'],p['version'],'register-reader',payload,role='reviewer').status_code==403
    r=command(client,scope,'register_bank_account',p['object_id'],p['version'],'register-good',payload)
    assert r.status_code==200,r.text
    assert command(client,scope,'register_bank_account',p['object_id'],p['version'],'register-again',payload).status_code==200
    assert len(svc.bank_accounts.view(s)['accounts'])==1
    a=uploaded(client,scope,bank_file('00123456789','另一个企业'),filename='农业银行.xlsx')
    parsed=parse(client,scope,a,'bank_statement').json()['effect']['artifact']
    d=svc.bank_accounts.view(s)['statements'][0]
    assert d['status']=='CONFLICT'
    bad={'token':d['token'],'account_id':r.json()['effect']['object']['object_id'],'ownership_confirmed':True}
    assert command(client,scope,'confirm_statement_account',parsed['object_id'],parsed['version'],'bad-holder',bad).status_code==409


def test_stale_tampered_and_foreign_account_rejected(client,scope):
    svc=client.app.state.service;s=Scope(**scope)
    a=uploaded(client,scope,bank_file(),filename='农业银行.xlsx')
    a=parse(client,scope,a,'bank_statement').json()['effect']['artifact']
    c=svc.bank_accounts.view(s)['statements'][0]
    base={'token':c['token'],'ownership_confirmed':True,'new_account':{k:c['identity'][k] for k in ('account_number','holder','bank_name','currency')}}
    malicious={**base,'new_account':{**base['new_account'],'account_number':'99888888888'}}
    assert command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'wrong-number',malicious).status_code==409
    assert not svc.bank_accounts.accounts(s)
    assert command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'extra-values',{**base,'income':'99999'}).status_code==409
    p=svc.workbench(s)['period']
    command(client,scope,'register_bank_account',p['object_id'],p['version'],'change-registry',{'account_number':'007777777','holder':'另一账户','bank_name':'中国银行','currency':'CNY','ownership_confirmed':True})
    assert command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'stale-token',base).status_code==409
    c=svc.bank_accounts.view(s)['statements'][0]
    foreign={**base,'token':c['token']};foreign.pop('new_account');foreign['account_id']='foreign-account'
    assert command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'foreign-account',foreign).status_code==409
    path=client.app.state.settings.storage_path/a['data']['storage_path'];path.write_bytes(b'tampered')
    c=svc.bank_accounts.view(s)['statements'][0];assert c['status']=='INVALID'
    assert command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'bad-original',{**base,'token':c['token']}).status_code==409
    assert not svc.store.list_objects('SourceVerification',s)


def test_missing_account_requires_reason_and_failed_parse_rolls_back_registry(client,scope):
    svc=client.app.state.service;s=Scope(**scope)
    source=uploaded(client,scope,xlsx_fixture([('表',[['未知列'],['无交易记录']])]))
    source=parse(client,scope,source,'bank_statement').json()['effect']['artifact']
    c=svc.bank_accounts.view(s)['statements'][0]
    payload={'token':c['token'],'ownership_confirmed':True,'new_account':{'account_number':'0012345678','holder':'合成企业','bank_name':'中国银行','currency':'CNY'}}
    r=command(client,scope,'confirm_statement_account',source['object_id'],source['version'],'missing-reason',payload)
    assert r.status_code==409
    assert command(client,scope,'confirm_statement_account',source['object_id'],source['version'],'empty-transactions',{**payload,'note':'已向企业核实账户'}).status_code==409
    assert not svc.bank_accounts.accounts(s)


def test_manual_parse_option_is_not_account_approval(client,scope):
    a=uploaded(client,scope,bank_file())
    r=parse(client,scope,a,'bank_statement',bank_account_ref='forged').json()['effect']
    assert r['facts'][0]['data']['normalized_value']['bank_account_ref']=='001-234567890'
    assert r['facts'][0]['status']=='NEEDS_REVIEW'
    assert 'bank_account_binding' not in r['artifact']['data']
    f=r['facts'][0]
    assert command(client,scope,'reparse_fact',f['object_id'],f['version'],'no-approval-bypass',{'parser_version':'v2','normalized_value':f['data']['normalized_value']}).status_code==409


def test_known_number_can_resolve_bank_without_another_confirmation(client,scope):
    svc=client.app.state.service;s=Scope(**scope);svc.create_scope(s)
    p=svc.workbench(s)['period']
    r=command(client,scope,'register_bank_account',p['object_id'],p['version'],'register-partial',{'account_number':'001-234567890','holder':'合成企业','bank_name':'中国农业银行','currency':'CNY','ownership_confirmed':True})
    a=uploaded(client,scope,bank_file(bank=''))
    a=parse(client,scope,a,'bank_statement').json()['effect']['artifact']
    c=svc.bank_accounts.view(s)['statements'][0];assert c['status']=='LINKED'
    assert c['binding']['automatic']


def test_bank_only_registration_assigns_all_current_files_without_account_or_note(client,scope):
    svc=client.app.state.service;s=Scope(**scope)
    for n in range(2):
        content=xlsx_fixture([('流水',[['交易日期','收入','支出','余额'],['2026-03-08',100+n,0,100+n],['2026-04-02',0,1,99+n]])])
        a=uploaded(client,scope,content,filename=f'农业银行{n}.xlsx')
        parse(client,scope,a,'bank_statement',key=f'bank-only-parse-{n}')
    c=svc.bank_accounts.view(s)['statements'][0]
    r=command(client,scope,'confirm_statement_account',c['artifact_id'],c['artifact_version'],'bank-only-confirm',{'token':c['token'],'new_account':{'bank_name':'农业银行'},'ownership_confirmed':True})
    assert r.status_code==200,r.text
    assert len(r.json()['effect']['associated_statements'])==1
    accounts=svc.bank_accounts.accounts(s);assert len(accounts)==1
    assert accounts[0]['data']['account_number']=='' and accounts[0]['data']['holder']==''
    assert all(c['status']=='LINKED' for c in svc.bank_accounts.view(s)['statements'])
    facts=r.json()['effect']['facts'];assert facts[0]['data']['normalized_value']['bank_account_ref']=='中国农业银行'
    assert facts[1]['status']=='PERIOD_EXCEPTION'
    t=next(t for t in svc.workbench(s)['material_review']['tasks'] if t['artifact_id']==c['artifact_id'] and t['kind']=='VERIFY')
    f=facts[0]
    r=command(client,scope,'verify_source_values',c['artifact_id'],r.json()['effect']['artifact']['version'],'bank-only-verify',{'task_id':t['id'],'records':[{'object_id':f['object_id'],'version':f['version']}]})
    assert r.status_code==200,r.text
    assert svc.workbench(s)['baseline']['status']=='DRAFT'
    next_scope={**scope,'accounting_period_id':'2026-04','baseline_id':'bank-only-april'}
    next_content=xlsx_fixture([('流水',[['交易日期','收入','支出'],['2026-04-03',123,0]])])
    a=uploaded(client,next_scope,next_content,filename='农业银行4月.xlsx')
    following=parse(client,next_scope,a,'bank_statement',key='bank-only-future').json()['effect']
    assert following['artifact']['data']['bank_account_binding']['automatic']
    assert following['facts'][0]['data']['normalized_value']['bank_account_ref']=='中国农业银行'
    assert following['facts'][0]['data']['normalized_value']['income']=='123.00'
    assert not svc.store.list_objects('SourceVerification',Scope(**next_scope))


def test_multiple_accounts_same_bank_requires_choice_and_ambiguous_file_bank_rejected(client,scope):
    svc=client.app.state.service;s=Scope(**scope);svc.create_scope(s);p=svc.workbench(s)['period']
    for n in (1,2):
        r=command(client,scope,'register_bank_account',p['object_id'],p['version'],f'two-bank-accounts-{n}',{'bank_name':'农业银行','account_number':f'00000000{n}','ownership_confirmed':True})
        assert r.status_code==200,r.text
    content=xlsx_fixture([('流水',[['交易日期','收入','支出'],['2026-03-08',100,0]])])
    a=uploaded(client,scope,content,filename='农业银行流水.xlsx');a=parse(client,scope,a,'bank_statement').json()['effect']['artifact']
    c=svc.bank_accounts.view(s)['statements'][0];assert c['status']=='REVIEW' and not c['match_id']
    assert 'bank_account_binding' not in a['data']
    account=svc.bank_accounts.accounts(s)[0]
    r=command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'choose-one-bank-account',{'token':c['token'],'account_id':account['object_id'],'ownership_confirmed':True})
    assert r.status_code==200,r.text
    assert 'bank_name' in identify_account(content,'农业银行_南京银行流水.xlsx')['conflicts']


def test_multiple_statement_sections_and_counterparty_blocks_are_not_own_account():
    rows=[['账号:00123456789','户名:甲'],['交易日期','支出','收入'],['2026-03-08',1,0],
          ['账号:00987654321','户名:乙'],['交易日期','支出','收入'],['2026-03-09',2,0]]
    c=identify_account(xlsx_fixture([('表',rows)]))
    assert 'account_number' in c['conflicts'] and 'holder' in c['conflicts']
    c=identify_account(xlsx_fixture([('表',[['对方账户信息'],['账号:00987654321','户名:对方公司','开户银行:中国银行'],['交易日期','支出','收入'],['2026-03-08',1,0]])]))
    assert not c['account_number'] and not c['holder'] and not c['bank_name']
    for suffix in (':','：'):
        c=identify_account(xlsx_fixture([('表',[['对方账户信息'+suffix],['账号:00987654321','户名:对方公司','开户银行:中国银行'],['交易日期','支出','收入'],['2026-03-08',1,0]])]))
        assert not c['account_number'] and not c['holder'] and not c['bank_name']
    c=identify_account(xlsx_fixture([('表',[['账号:00123456789'],['交易日期','支出','收入','摘要'],['2026-03-08',1,0,'账号:00987654321']])]))
    assert c['account_number']=='00123456789' and not c['conflicts']


def test_empty_account_and_branch_are_valid_bank_only_identity():
    i=identify_account(bank_file(account='',bank='中国农业银行南京分行'),'农业银行.xlsx')
    assert i['account_number']=='' and i['conflicts']==[]
    assert i['bank_name']=='中国农业银行南京分行'


def test_observed_multiple_numbers_prevent_default_bank_batch(client,scope):
    svc=client.app.state.service;s=Scope(**scope)
    for n,number in enumerate(('00123456789','00987654321','')):
        a=uploaded(client,scope,bank_file(account=number),filename=f'农业银行{n}.xlsx')
        parse(client,scope,a,'bank_statement',key=f'multi-observed-{n}')
    p=svc.workbench(s)['period']
    r=command(client,scope,'register_bank_account',p['object_id'],p['version'],'default-multi-observed',{'bank_name':'农业银行','ownership_confirmed':True})
    assert r.status_code==200,r.text
    assert r.json()['effect']['associated_statements']==[]
    candidates=svc.bank_accounts.view(s)['statements']
    assert all(c['requires_specific_account'] and c['status']=='REVIEW' for c in candidates)
    c=next(c for c in candidates if c['identity']['account_number'])
    payload={'token':c['token'],'new_account':{'bank_name':'农业银行'},'ownership_confirmed':True}
    assert command(client,scope,'confirm_statement_account',c['artifact_id'],c['artifact_version'],'no-default-multi',payload).status_code==409
    payload['new_account']['account_number']=c['identity']['account_number']
    r=command(client,scope,'confirm_statement_account',c['artifact_id'],c['artifact_version'],'choose-specific-multi',payload)
    assert r.status_code==200,r.text
    assert r.json()['effect']['associated_statements']==[]


def test_custom_bank_filename_reuse_and_manual_source_attribution(client,scope):
    svc=client.app.state.service;s=Scope(**scope);svc.create_scope(s);p=svc.workbench(s)['period']
    r=command(client,scope,'register_bank_account',p['object_id'],p['version'],'register-cmb',{'bank_name':'招商银行','ownership_confirmed':True})
    assert r.status_code==200,r.text
    content=xlsx_fixture([('流水',[['交易日期','收入','支出'],['2026-03-08',100,0]])])
    a=uploaded(client,scope,content,filename='招商银行3月.xlsx')
    effect=parse(client,scope,a,'bank_statement').json()['effect']
    assert effect['artifact']['data']['bank_account_binding']['automatic']
    a=uploaded(client,scope,bank_file(account='',bank=''),filename='流水.xlsx')
    a=parse(client,scope,a,'bank_statement',key='unknown-bank').json()['effect']['artifact']
    c=svc.bank_accounts.candidate(s,a)
    r=command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'manual-bank',{'token':c['token'],'new_account':{'bank_name':'中国银行'},'ownership_confirmed':True})
    assert r.status_code==200,r.text
    source=r.json()['effect']['facts'][0]['data']['field_sources']['bank_name']
    assert source['region']=='银行归属确认记录' and source['derivation']=='人工确认银行，非原件提取'


@pytest.mark.parametrize('missing_source_number',[False,True])
def test_legacy_v1_binding_remains_verifiable_without_mutation(client,scope,missing_source_number):
    from app.tabular import extract_workbook,ParseOptions
    svc=client.app.state.service;s=Scope(**scope)
    content=bank_file(account='' if missing_source_number else '001-234567890')
    a=uploaded(client,scope,content,filename='农业银行.xlsx')
    options=ParseOptions(document_kind='bank_statement')
    identity=svc.bank_accounts.identity(a);identity['version']='bank-identity-v1'
    account=svc.bank_accounts.register(s,'operator',{**{k:identity[k] for k in ('bank_name','account_number','holder','currency')},'account_number':'001-234567890','ownership_confirmed':True})
    extracted=svc.bank_accounts.attach(a,extract_workbook(content,options,s.accounting_period_id),account,identity,'operator')
    extracted['bank_account_binding'].pop('account_reference')
    if missing_source_number:extracted['bank_account_binding'].pop('account_number')
    for row in extracted['records']:
        row['normalized_value'].pop('bank_name');row['field_sources'].pop('bank_name')
        row['field_sources']['bank_account_ref']={**identity['sources'].get('account_number',{'original_value':None}),'derivation':'企业账户档案关联','account_id':account['object_id']}
    result=svc.parse_artifact(s,artifact_id=a['object_id'],expected_version=a['version'],actor_id='operator',payload={'document_kind':'bank_statement'},_mapped=extracted)
    a=result['artifact'];f=result['facts'][0]
    task=next(t for t in svc.workbench(s)['material_review']['tasks'] if t['kind']=='VERIFY')
    r=command(client,scope,'verify_source_values',a['object_id'],a['version'],'legacy-verification',{'task_id':task['id'],'records':[{'object_id':f['object_id'],'version':f['version']}]})
    assert r.status_code==200,r.text
    assert svc.store.get_object(a['object_id'],s)['version']==a['version']
    assert svc.store.get_object(f['object_id'],s)['data']==f['data']


def test_first_custom_bank_confirmation_can_be_verified(client,scope):
    svc=client.app.state.service;s=Scope(**scope)
    content=xlsx_fixture([('流水',[['交易日期','收入','支出'],['2026-03-08',100,0]])])
    a=uploaded(client,scope,content,filename='招商银行3月.xlsx')
    a=parse(client,scope,a,'bank_statement').json()['effect']['artifact']
    c=svc.bank_accounts.candidate(s,a)
    r=command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'first-cmb',{'token':c['token'],'new_account':{'bank_name':'招商银行'},'ownership_confirmed':True})
    assert r.status_code==200,r.text
    effect=r.json()['effect'];f=effect['facts'][0];task=next(t for t in svc.workbench(s)['material_review']['tasks'] if t['kind']=='VERIFY')
    r=command(client,scope,'verify_source_values',a['object_id'],effect['artifact']['version'],'verify-first-cmb',{'task_id':task['id'],'records':[{'object_id':f['object_id'],'version':f['version']}]})
    assert r.status_code==200,r.text


def test_custom_bank_multiple_numbers_block_before_any_batch_write(client,scope):
    svc=client.app.state.service;s=Scope(**scope)
    for n,number in enumerate(('00123456789','00987654321')):
        a=uploaded(client,scope,bank_file(account=number,bank=''),filename=f'招商银行{n}.xlsx')
        parse(client,scope,a,'bank_statement',key=f'cmb-multi-{n}')
    c=svc.bank_accounts.view(s)['statements'][0]
    r=command(client,scope,'confirm_statement_account',c['artifact_id'],c['artifact_version'],'no-cmb-first-default',{'token':c['token'],'new_account':{'bank_name':'招商银行'},'ownership_confirmed':True})
    assert r.status_code==409,r.text
    assert not svc.bank_accounts.accounts(s)
    p=svc.workbench(s)['period']
    r=command(client,scope,'register_bank_account',p['object_id'],p['version'],'cmb-default',{'bank_name':'招商银行','ownership_confirmed':True})
    assert r.status_code==200,r.text
    assert r.json()['effect']['associated_statements']==[]
    assert all(c['status']=='REVIEW' for c in svc.bank_accounts.view(s)['statements'])


@pytest.mark.parametrize('filename',['流水.xlsx','招商银行3月.xlsx'])
def test_prior_manually_assigned_bank_number_protects_next_period(client,scope,filename):
    svc=client.app.state.service;s=Scope(**scope)
    a=uploaded(client,scope,bank_file(account='00123456789',bank=''),filename=filename)
    a=parse(client,scope,a,'bank_statement').json()['effect']['artifact'];c=svc.bank_accounts.candidate(s,a)
    r=command(client,scope,'confirm_statement_account',a['object_id'],a['version'],'prior-manual-bank',{'token':c['token'],'new_account':{'bank_name':'招商银行'},'ownership_confirmed':True})
    assert r.status_code==200,r.text
    other={**scope,'accounting_period_id':'2026-04','baseline_id':'april-manual-bank'}
    for n,number in enumerate(('00987654321','')):
        a=uploaded(client,other,bank_file(account=number,bank=''),filename=f'招商银行4月{n}.xlsx')
        effect=parse(client,other,a,'bank_statement',key=f'next-bank-{n}').json()['effect']
        assert not effect['artifact']['data'].get('bank_account_binding')
    assert all(c['status']=='REVIEW' and c['requires_specific_account'] for c in svc.bank_accounts.view(Scope(**other))['statements'])
