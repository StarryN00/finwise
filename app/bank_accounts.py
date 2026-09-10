"""Company/ledger account registry and source-bound statement association."""
from copy import deepcopy
import hashlib
import re
import unicodedata

from app.db import utcnow
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed, VersionConflict
from app.ontology.store import digest
from app.tabular import read_workbook, header_mapping, column_name, date_value, ExtractionError, extract_workbook, ParseOptions

VERSION = 'bank-identity-v2'
FIELDS = ('account_number', 'holder', 'bank_name', 'currency')
LABELS = {'account_number': ('账号','帐号','账户号码','本方账号'), 'holder': ('户名','账户名称','客户名称'),
          'bank_name': ('开户银行','开户行','银行名称'), 'currency': ('币种','货币')}
BANKS = ('中国农业银行','中国银行','中国工商银行','中国建设银行','南京银行','泰隆银行')


def bank_key(value):
    text=clean(value)
    aliases={'农业银行':'中国农业银行','工商银行':'中国工商银行','建设银行':'中国建设银行','浙江泰隆商业银行':'泰隆银行'}
    for name in sorted((*BANKS,*aliases),key=len,reverse=True):
        if text.startswith(name):return aliases.get(name,name)
    return text


def compatible(identity,data):
    bank=identity.get('bank_name') or identity.get('bank_hint')
    return (not bank or bank_key(bank)==bank_key(data.get('bank_name'))) and all(
        not identity.get(k) or not data.get(k) or clean(identity[k])==clean(data[k]) for k in ('account_number','holder','currency'))


def clean(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def account_key(value):
    # Separators remain part of identity: never assume a bank prefix is cosmetic.
    return clean(value)


def identify_account(content, filename=''):
    result={k:'' for k in FIELDS};sources={};found={k:[] for k in FIELDS}
    if content.startswith(b'%PDF'):
        from app.document_layouts import extract_boc_pdf
        parsed=extract_boc_pdf(content,'bank_statement','2000-01')
        if parsed['records']:
            r=parsed['records'][0]
            found['account_number'].append((r['normalized_value']['bank_account_ref'],{'region':'第1页 页首账号','page':1}))
            found['bank_name'].append(('中国银行',{'region':'已验证的中国银行对账单版式','page':1}))
        # Do not infer holder/currency or use unrestricted PDF text as an identity.
    else:
        for sheet in read_workbook(content):
            foreign=False;date_column=None
            for row in sheet['rows']:
                values=row['values']
                mapping=header_mapping(values,'bank_statement')
                if mapping or any(clean(v)=='交易类型' for v in values):
                    date_column=next((i for i,v in enumerate(values) if clean(v) in {'交易时间','交易日期'}),None)
                    continue
                if date_column is not None and date_column<len(values):
                    try:
                        if date_value(values[date_column]):continue
                    except (ValueError,TypeError):pass
                labels_in_row={clean(v).rstrip(':：') for v in values if isinstance(v,str)}
                if labels_in_row & {'对方账户信息','对方信息','交易对手信息','对手账户信息','收款方信息','付款方信息'}:foreign=True
                if labels_in_row & {'本方账户信息','本方信息','本方账户','账户明细'}:foreign=False
                if foreign:continue
                for i,v in enumerate(values):
                    if not isinstance(v,str):continue
                    text=unicodedata.normalize('NFKC',v).strip()
                    for field,labels in LABELS.items():
                        m=re.fullmatch(r'(?:'+ '|'.join(labels)+r')\s*[:：]?\s*(.*)',text)
                        if not m:continue
                        value=m[1].strip();region=f"{sheet['name']}!{column_name(i+1)}{row['row']}"
                        if not value and i+1<len(values) and isinstance(values[i+1],str):
                            value=values[i+1].strip();region=f"{sheet['name']}!{column_name(i+2)}{row['row']}"
                            if any(re.match(r'^(?:'+ '|'.join(labels)+r')(?:\s*[:：]|$)',value) for labels in LABELS.values()):value=''
                        if value and not any(region.endswith(c) for c in row.get('formulas',{})):
                            found[field].append((value,{'region':region,'original_value':value,'source_label':labels[0]}))
    conflicts=[]
    for field,items in found.items():
        unique={clean(v): (v,s) for v,s in items}
        if len(unique)>1:conflicts.append(field)
        elif unique:result[field],sources[field]=next(iter(unique.values()))
    if result['currency'] in {'人民币','人民币元','RMB','CNY'}:result['currency']='CNY'
    if result['account_number'] and not re.fullmatch(r'[0-9][0-9 \-]{5,63}',result['account_number']):
        conflicts.append('account_number')
    hints=[b for b in BANKS if b in filename or (b!='中国银行' and b.removeprefix('中国') in filename)]
    hint=hints[0] if len(hints)==1 else ''
    if len(hints)>1 or result['bank_name'] and hint and bank_key(result['bank_name'])!=bank_key(hint):conflicts.append('bank_name')
    return {**result,'sources':sources,'conflicts':conflicts,'bank_hint':hint,'version':VERSION}


class BankAccounts:
    def __init__(self, service):self.service=service;self.store=service.store;self.cache={}

    def registry_scope(self,scope):
        return Scope(**{**scope.model_dump(),'accounting_period_id':'__bank_registry__','baseline_id':'__bank_registry__'})

    def accounts(self,scope):return self.store.list_objects('BankAccount',self.registry_scope(scope))

    def content(self,artifact):
        root=self.store.database.settings.storage_path.resolve();path=(root/artifact['data']['storage_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise PreconditionFailed('原件不存在，无法确认账户')
        content=path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=artifact['data']['sha256']:raise PreconditionFailed('原件哈希校验失败')
        return content

    def identity(self,artifact):
        content=self.content(artifact);key=(artifact['data']['sha256'],artifact['data']['filename'])
        if key not in self.cache:
            if len(self.cache)>128:self.cache.clear()
            self.cache[key]=identify_account(content,artifact['data']['filename'])
        return deepcopy(self.cache[key])

    def matching_identity(self,artifact,accounts):
        identity=self.identity(artifact)
        hints={bank_key(a['data']['bank_name']) for a in accounts if bank_key(a['data']['bank_name']) in clean(artifact['data']['filename'])}
        if identity['bank_hint']:hints.add(bank_key(identity['bank_hint']))
        if len(hints)>1 or hints and identity['bank_name'] and bank_key(identity['bank_name']) not in hints:identity['conflicts'].append('bank_name')
        elif hints:identity['bank_hint']=next(iter(hints))
        return identity

    def candidate(self,scope,artifact,accounts=None):
        accounts=self.accounts(scope) if accounts is None else accounts
        try:identity=self.matching_identity(artifact,accounts);error=''
        except (ExtractionError,PreconditionFailed,ValueError) as exc:
            identity={**{k:'' for k in FIELDS},'sources':{},'conflicts':[],'bank_hint':''};error=str(exc)
        bank=identity['bank_name'] or identity['bank_hint']
        matches=[a for a in accounts if bank and bank_key(a['data']['bank_name'])==bank_key(bank)]
        if not bank and identity['account_number']:
            matches=[a for a in accounts if account_key(a['data']['account_number'])==account_key(identity['account_number'])]
        number_matches=[a for a in matches if identity['account_number'] and account_key(a['data']['account_number'])==account_key(identity['account_number'])]
        selectable=number_matches if number_matches else matches
        exact=[a for a in selectable if compatible(identity,a['data'])] if len(selectable)==1 else []
        numbers=self.observed_numbers(scope,bank) if bank else set()
        # First parse has not stored parse_options yet; include this source now.
        if identity['account_number'] and not identity['conflicts']:numbers.add(account_key(identity['account_number']))
        ambiguous=len(numbers)>1
        if ambiguous:exact=[a for a in exact if a['data']['account_number'] and identity['account_number']]
        bound=artifact['data'].get('bank_account_binding')
        valid=bound and bound.get('sha256')==artifact['data']['sha256'] and bound.get('artifact_version')==artifact['version'] and any(a['object_id']==bound.get('account_id') and a['version']==bound.get('account_version') for a in accounts)
        conflict=number_matches and any(not compatible(identity,a['data']) for a in number_matches)
        status='INVALID' if error else 'CONFLICT' if identity['conflicts'] or conflict else 'MATCHED' if exact else 'REVIEW' if matches or ambiguous else 'NEW' if bank else 'MISSING'
        if valid and not error and status!='CONFLICT':status='LINKED'
        token=digest({'scope':scope.model_dump(),'artifact':artifact['object_id'],'version':artifact['version'],'sha':artifact['data']['sha256'],'identity':identity,'accounts':[(a['object_id'],a['version']) for a in accounts],'observed_numbers':sorted(numbers)})
        return {'artifact_id':artifact['object_id'],'artifact_version':artifact['version'],'filename':artifact['data']['filename'],
                'identity':identity,'status':status,'error':error,'token':token,'match_id':bound['account_id'] if status=='LINKED' else exact[0]['object_id'] if exact else None,
                'suggested_id':exact[0]['object_id'] if exact else None,
                'binding':bound if status=='LINKED' else None,'requires_specific_account':ambiguous,'record_count':artifact['data'].get('parse_counts',{}).get('rows',0)}

    def observed_numbers(self,scope,bank):
        """Observed identities prevent a bank-only default from hiding multiple accounts."""
        accounts=self.accounts(scope)
        # Include the proposed bank during a first confirmation, before it is saved.
        accounts=[*accounts,{'data':{'bank_name':bank,'account_number':''}}]
        numbers={account_key(a['data']['account_number']) for a in accounts if bank_key(a['data']['bank_name'])==bank_key(bank) and a['data']['account_number']}
        for a in self.store.list_objects('SourceArtifact',scope):
            if a['status']!='ACTIVE' or a['data'].get('parse_options',{}).get('document_kind')!='bank_statement':continue
            try:i=self.matching_identity(a,accounts)
            except (ExtractionError,PreconditionFailed,ValueError):continue
            if not i['conflicts'] and bank_key(i['bank_name'] or i['bank_hint'])==bank_key(bank) and i['account_number']:numbers.add(account_key(i['account_number']))
        # Prior-period confirmed identity only; never expose other-period transactions.
        import json
        keys=('tenant_id','organization_id','legal_entity_id','ledger_id')
        where=' AND '.join("json_extract(o.scope_json, '$."+k+"') = ?" for k in keys)
        with self.store.database.connect() as conn:
            rows=conn.execute("SELECT o.version,o.data_json FROM ontology_objects o WHERE o.object_type='SourceArtifact' AND o.status='ACTIVE' AND "+where+" AND o.version=(SELECT MAX(v.version) FROM ontology_objects v WHERE v.object_id=o.object_id)",[getattr(scope,k) for k in keys]).fetchall()
        for row in rows:
            data=json.loads(row['data_json']);b=data.get('bank_account_binding',{});i=b.get('identity',{})
            account=next((a for a in accounts if a.get('object_id')==b.get('account_id') and a.get('version')==b.get('account_version') and a.get('object_id')),None)
            if not account or b.get('artifact_version')!=row['version'] or b.get('sha256')!=data.get('sha256'):continue
            number=b.get('account_number') or i.get('account_number') or account['data']['account_number']
            if bank_key(account['data']['bank_name'])==bank_key(bank) and number:numbers.add(account_key(number))
        return numbers

    def view(self,scope,artifacts=None):
        accounts=self.accounts(scope)
        artifacts=artifacts if artifacts is not None else self.store.list_objects('SourceArtifact',scope)
        statements=[self.candidate(scope,a,accounts) for a in artifacts if a['status']=='ACTIVE' and a['data'].get('parse_options',{}).get('document_kind')=='bank_statement']
        # Registry exposes only bank master data, never another period's financial objects.
        return {'accounts':[{'object_id':a['object_id'],'version':a['version'],'status':a['status'],'data':a['data']} for a in accounts], 'statements':statements}

    def register(self,scope,actor,payload):
        if set(payload)-set(FIELDS)-{'ownership_confirmed'} or payload.get('ownership_confirmed') is not True:
            raise PreconditionFailed('请确认账户属于当前企业，不能提交额外字段')
        data={k:payload.get(k,'CNY' if k=='currency' else '') for k in FIELDS}
        if any(not isinstance(v,str) or len(v)>128 for v in data.values()):raise PreconditionFailed('银行及可选账户信息格式无效')
        data={k:v.strip() for k,v in data.items()}
        data['bank_name']=bank_key(data['bank_name'])
        if not data['bank_name']:raise PreconditionFailed('请选择或填写银行；账号可不填写')
        if data['account_number'] and not re.fullmatch(r'[0-9][0-9 \-]{5,63}',data['account_number']):raise PreconditionFailed('填写账号时须为完整文本；也可以留空，仅按银行记账')
        if not re.fullmatch('[A-Z]{3}',data['currency']):raise PreconditionFailed('币种请使用 CNY 等三位代码')
        same_bank=[a for a in self.accounts(scope) if bank_key(a['data']['bank_name'])==data['bank_name']]
        existing=[a for a in same_bank if account_key(a['data']['account_number'])==account_key(data['account_number'])]
        if not data['account_number'] and len(same_bank)==1:existing=same_bank
        if not data['account_number'] and len(same_bank)>1:raise PreconditionFailed('该银行已登记多个账户，请选择具体账户，不能再创建无账号的默认项')
        if existing:
            if any(data[k] and existing[0]['data'][k] and clean(existing[0]['data'][k])!=clean(data[k]) for k in ('account_number','holder','currency')):raise PreconditionFailed('该银行既有账户信息冲突，请核对已登记信息')
            return existing[0]
        a=self.store.create_initial_object('BankAccount',self.registry_scope(scope),{**data,'confirmed_by':actor,'confirmed_at':utcnow()},status='CONFIRMED',created_by=actor)
        self.store.add_audit('BANK_ACCOUNT_REGISTERED',actor,scope,object_id=a['object_id'],object_version=a['version'],after=a,reason='人工确认企业对公账户档案')
        return a

    def attach(self,artifact,extracted,account,identity,actor,automatic=False,note=''):
        extracted=deepcopy(extracted)
        number=identity['account_number'] or account['data']['account_number']
        reference=number or account['data']['bank_name']
        binding={'account_id':account['object_id'],'account_version':account['version'],'account_number':number,'account_reference':reference,'sha256':artifact['data']['sha256'],
                 'artifact_version':artifact['version']+1,'identity':identity,'confirmed_by':actor,'confirmed_at':utcnow(),'automatic':automatic,'note':note}
        extracted['bank_account_binding']=binding
        if identity['bank_name'] and bank_key(identity['bank_name'])==bank_key(account['data']['bank_name']):
            bank_source={**identity['sources'].get('bank_name',{}),'derivation':'原件银行信息归类'}
        elif identity['bank_hint'] and bank_key(identity['bank_hint'])==bank_key(account['data']['bank_name']):
            bank_source={'region':'文件名','original_value':artifact['data']['filename'],'derivation':'根据文件名识别银行，经企业银行档案关联'}
        else:
            bank_source={'region':'银行归属确认记录','original_value':account['data']['bank_name'],'derivation':'人工确认银行，非原件提取','confirmed_by':actor}
        bank_source['account_id']=account['object_id']
        for row in extracted['records']:
            row['normalized_value']['bank_account_ref']=reference
            row['normalized_value']['bank_name']=account['data']['bank_name']
            source=identity['sources'].get('account_number',{'region':'企业账户档案','original_value':number}) if number else bank_source
            row['field_sources']['bank_account_ref']={**source,'derivation':'企业银行归属关联（账号选填）','account_id':account['object_id']}
            row['field_sources']['bank_name']=bank_source
            row['extraction_issues']=[i for i in row['extraction_issues'] if not i.startswith('bank_account_ref：')]
        return extracted

    def prepare(self,scope,artifact,extracted):
        c=self.candidate(scope,artifact)
        if c['match_id'] and c['status'] in {'MATCHED','LINKED'}:
            a=next(a for a in self.accounts(scope) if a['object_id']==c['match_id'])
            return self.attach(artifact,extracted,a,c['identity'],'system',True)
        identity=c['identity'];extracted=deepcopy(extracted)
        for r in extracted['records']:
            if identity['account_number'] and not identity['conflicts']:
                r['normalized_value']['bank_account_ref']=identity['account_number']
                r['field_sources']['bank_account_ref']=identity['sources']['account_number']
            r['extraction_issues']=[i for i in r['extraction_issues'] if not i.startswith('bank_account_ref：')]+['bank_account_ref：请确认流水所属的企业账户']
        return extracted

    def replay(self,scope,artifact,extracted):
        """Read-only verification replays the fixed, previously confirmed binding."""
        c=self.candidate(scope,artifact)
        if c['status']!='LINKED':raise PreconditionFailed('请先确认本份流水所属账户，再核实提取值')
        binding=c['binding']
        # Filename hints are registry-derived, not immutable source fields.
        if {k:v for k,v in binding['identity'].items() if k not in {'version','bank_hint'}}!={k:v for k,v in c['identity'].items() if k not in {'version','bank_hint'}}:raise PreconditionFailed('账户识别依据已变化，请重新核对账户归属')
        account=next(a for a in self.accounts(scope) if a['object_id']==binding['account_id'])
        if binding['identity'].get('version')=='bank-identity-v1':
            extracted=deepcopy(extracted)
            for row in extracted['records']:
                row['normalized_value']['bank_account_ref']=binding.get('account_number') or account['data']['account_number']
                row['field_sources']['bank_account_ref']={**binding['identity']['sources'].get('account_number',{'original_value':None}),'derivation':'企业账户档案关联','account_id':account['object_id']}
                row['extraction_issues']=[i for i in row['extraction_issues'] if not i.startswith('bank_account_ref：')]
            return extracted
        return self.attach(artifact,extracted,account,binding['identity'],binding['confirmed_by'],binding['automatic'],binding.get('note',''))

    def confirm(self,scope,artifact_id,actor,payload):
        if set(payload)-{'token','ownership_confirmed','account_id','new_account','note'} or payload.get('ownership_confirmed') is not True:raise PreconditionFailed('请明确确认本份流水属于当前企业账户')
        a=self.store.get_object(artifact_id,scope);c=self.candidate(scope,a)
        if payload.get('token')!=c['token']:raise VersionConflict('原件或账户档案已变化，请刷新核对')
        if a['status']!='ACTIVE' or c['status'] in {'INVALID','CONFLICT'}:raise PreconditionFailed('原件账户信息冲突或失效，请先核对来源')
        if bool(payload.get('account_id'))==bool(payload.get('new_account')):raise PreconditionFailed('请选择已有账户或登记新账户，不能同时提交')
        if payload.get('account_id'):
            account=next((x for x in self.accounts(scope) if x['object_id']==payload['account_id']),None)
            if not account:raise PreconditionFailed('账户不属于当前企业和账套')
        else:
            proposed=payload['new_account']
            if not isinstance(proposed,dict):raise PreconditionFailed('账户资料格式无效')
            account={'data':proposed}
        identity=c['identity']
        confirmation_identity={**identity,'bank_hint':''}
        numbers=self.observed_numbers(scope,account['data'].get('bank_name'))
        if identity['account_number']:numbers.add(account_key(identity['account_number']))
        if len(numbers)>1 and not account['data'].get('account_number'):raise PreconditionFailed('该银行已识别多个明确账号，请选择具体账户或填入本份流水的账号')
        if not compatible(confirmation_identity,account['data']):raise PreconditionFailed('银行或已填写的账户信息与原件不一致，不能覆盖原件识别值')
        note=payload.get('note','')
        if not isinstance(note,str) or len(note)>1000:raise PreconditionFailed('账户关联依据格式无效')
        if payload.get('new_account'):account=self.register(scope,actor,{**payload['new_account'],'ownership_confirmed':True})
        if not compatible(confirmation_identity,account['data']):raise PreconditionFailed('既有银行账户与原件冲突，请核对或选填新账号')
        options=ParseOptions.model_validate(a['data'].get('parse_options',{}))
        if options.document_kind!='bank_statement':raise PreconditionFailed('仅银行流水可以关联本方账户')
        extracted=extract_workbook(self.content(a),options,scope.accounting_period_id)
        if not extracted['records']:raise PreconditionFailed('尚无可关联交易，请先解决资料识别问题')
        extracted=self.attach(a,extracted,account,identity,actor,note=note)
        result=self.service.parse_artifact(scope,artifact_id=artifact_id,actor_id=actor,expected_version=a['version'],payload=a['data']['parse_options'],_mapped=extracted)
        result['associated_statements']=self.associate_matching(scope,actor,account['object_id'])
        return result

    def associate_matching(self,scope,actor,account_id):
        """After explicit bank registration, associate uniquely matching current files."""
        associated=[]
        for a in self.store.list_objects('SourceArtifact',scope):
            if a['status']!='ACTIVE' or a['data'].get('period_check')!='PASS' or a['data'].get('parse_options',{}).get('document_kind')!='bank_statement':continue
            c=self.candidate(scope,a)
            if c['status']!='MATCHED' or c['match_id']!=account_id:continue
            try:extracted=extract_workbook(self.content(a),ParseOptions(**a['data']['parse_options']),scope.accounting_period_id)
            except ExtractionError:continue
            if not extracted['records']:continue
            account=next(x for x in self.accounts(scope) if x['object_id']==c['match_id'])
            extracted=self.attach(a,extracted,account,c['identity'],actor,True)
            result=self.service.parse_artifact(scope,artifact_id=a['object_id'],actor_id=actor,expected_version=a['version'],payload=a['data']['parse_options'],_mapped=extracted)
            associated.append({'artifact_id':a['object_id'],'version':result['artifact']['version'],'counts':result['counts']})
        return associated
