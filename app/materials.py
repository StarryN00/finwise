"""Material-level review is separate from financial eligibility."""
from collections import Counter
import hashlib
import re
from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError
from app.db import utcnow
from app.ontology.errors import PermissionDenied, PreconditionFailed, VersionConflict
from app.ontology.store import digest
from app.action_types import ACTION_TYPE_BY_ID, FALLBACK_IDS


def compare_fields(data):
    """Align values using their recorded source, never a label/value guess."""
    original=data.get('original_value') or {}
    values=data.get('normalized_value') or {}
    sources=data.get('field_sources') or {}
    rows=[]
    for field,value in values.items():
        source=sources.get(field) or {}
        issue=any(str(i).startswith(field+'：') for i in data.get('extraction_issues',[]))
        if field.endswith(('_derivation','_origin')) or (value is None and field!='tax_rate' and not source and not issue):
            continue
        if field=='counterparty' and any(value==values.get(k) for k in ('seller_name','buyer_name')):
            continue
        if field=='period' and not source:
            origin=next((key for key in ('invoice_date','transaction_date','entry_date')
                         if values.get(key) and str(values[key])[:7]==value and sources.get(key)),None)
            if origin:
                source={**sources[origin],'derivation':'从原件业务日期取所属月份'}
        raw=source.get('original_value')
        label=source.get('source_label') or source.get('header') or ''
        region=source.get('region','')
        match=re.fullmatch(r'(.*)!([A-Z]+)(\d+)',region)
        original_sheet=original.get('sheet') or data.get('source_anchor',{}).get('region','').rsplit('!',1)[0]
        if raw is None and match and match[1]==original_sheet and int(match[3])==data.get('source_anchor',{}).get('row'):
            index=0
            for letter in match[2]:index=index*26+ord(letter)-64
            index-=1
            raw_values=original.get('values',[])
            raw=raw_values[index] if index<len(raw_values) else None
            headers=original.get('headers',[])
            label=label or (str(headers[index] or '') if index<len(headers) else '')
        status='UNLOCATED'
        if source.get('status')=='INVALID' or value is None and raw not in (None,''):
            status='DIFFERENT'
        elif source.get('status')=='AMBIGUOUS':
            status='AMBIGUOUS'
        elif values.get(field+'_derivation') or source.get('derivation'):
            status='DERIVED'
        elif value is None:
            status='MISSING'
        elif raw is not None:
            status='DIRECT_MATCH' if str(raw).strip()==str(value).strip() else 'DIFFERENT'
            if status=='DIFFERENT':
                # Do not normalize identifiers, names, or ambiguous date strings as numbers.
                if not any(token in field for token in ('name','_id','_no','account','date','period','range')):
                    try:
                        a=Decimal(str(raw).strip().replace(',',''))
                        b=Decimal(str(value))
                        if a.is_finite() and b.is_finite() and a==b:status='NORMALIZED_MATCH'
                    except (InvalidOperation,ValueError):pass
                if field=='tax_rate' and str(raw).strip().endswith('%'):
                    try:
                        if Decimal(str(raw).strip()[:-1])/100==Decimal(str(value)):status='NORMALIZED_MATCH'
                    except (InvalidOperation,ValueError):pass
                if 'date' in field:
                    from app.tabular import date_value
                    try:
                        if date_value(raw)==value:status='NORMALIZED_MATCH'
                    except ValueError:pass
        rows.append({'field':field,'source_label':label,'source_value':raw,'value':value,
                     'state':status,'region':region,'derivation':values.get(field+'_derivation') or source.get('derivation')})
    for field,source in sources.items():
        if field.startswith('unmapped_'):
            rows.append({'field':field,'source_label':source.get('source_label',''),
                         'source_value':source.get('original_value'),'value':None,
                         'state':'AMBIGUOUS','region':source.get('region','')})
    return rows


class RecordRef(BaseModel):
    model_config=ConfigDict(extra='forbid')
    object_id: StrictStr
    version: StrictInt


class VerifyInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    task_id: StrictStr
    records: list[RecordRef] = Field(min_length=1,max_length=5)
    note: StrictStr = Field(default='',max_length=2000)


class ReasonInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    task_id: StrictStr
    reason: StrictStr = Field(min_length=1,max_length=2000)


class TaskActionInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    task_id: StrictStr = Field(min_length=1)
    descriptor_hash: StrictStr = Field(min_length=16)
    action_type_id: StrictStr = Field(min_length=1)
    values: dict[str, StrictStr]


class RevokeTaskActionInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    reason: StrictStr = Field(min_length=1,max_length=2000)


class MaterialReview:
    def __init__(self, service):
        self.service=service
        self.store=service.store

    def source_valid(self, artifact):
        root=self.store.database.settings.storage_path.resolve()
        path=(root/artifact['data'].get('storage_path','')).resolve()
        try:
            return path.is_relative_to(root) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==artifact['data'].get('sha256')
        except OSError:
            return False

    def eligible(self, fact, artifact, scope):
        d=fact['data']
        if artifact['data'].get('parse_options',{}).get('document_kind')=='bank_statement':
            b=artifact['data'].get('bank_account_binding',{})
            reference=b.get('account_reference',b.get('account_number',b.get('identity',{}).get('account_number')))
            if not reference and b.get('identity',{}).get('version')=='bank-identity-v1':
                account=next((a for a in self.service.bank_accounts.accounts(scope) if a['object_id']==b.get('account_id') and a['version']==b.get('account_version')),None)
                reference=account['data']['account_number'] if account else None
            if b.get('artifact_version')!=artifact['version'] or b.get('sha256')!=artifact['data'].get('sha256') or reference!=d['normalized_value'].get('bank_account_ref'):return False
        return (artifact['status']=='ACTIVE' and artifact['data'].get('observed_period')==scope.accounting_period_id
            and artifact['data'].get('parse_status') in {'PARSED','PARSED_WITH_ISSUES'}
            and fact['object_id'] in artifact['data'].get('parsed_fact_ids',[])
            and fact['status']=='PARSED' and d.get('period_check')=='PASS' and not d.get('extraction_issues')
            and bool(d.get('source_anchor')) and bool(d.get('field_sources')))

    @staticmethod
    def binding(fact, artifact):
        return {'fact_id':fact['object_id'],'fact_version':fact['version'],
            'artifact_id':artifact['object_id'],'artifact_version':artifact['version'],
            'sha256':artifact['data'].get('sha256'),'source_anchor':fact['data'].get('source_anchor'),
            'value_hash':digest(fact['data'].get('normalized_value'))}

    def view(self, scope, readiness, artifacts, facts, bill_review=None, invoice_review=None):
        from app.bills import DISPLAY_ROLE_ISSUE, PERIOD_ISSUE
        from app.invoice_review import DISPLAY_ISSUE
        invoice_confirmations = {c['data']['binding']['fact_id']:c for c in (invoice_review or {}).get('confirmations',[]) if c['valid']}
        bill_confirmations = {c['data']['binding']['fact_id']: c for c in (bill_review or {}).get('confirmations', []) if c['valid']}
        categories=[c for c in readiness['categories'] if c['id'] not in {'baseline','unassigned'}]
        ids={i for c in categories for i in c['artifact_ids']}
        ids.update(a['object_id'] for a in artifacts if a['data'].get('source_purpose') not in {'opening_balance','prior_close','historical_reference'} and a['data'].get('observed_period')==scope.accounting_period_id)
        files={a['object_id']:a for a in artifacts if a['object_id'] in ids and a['status']!='ARCHIVED'}
        facts_by_id={f['object_id']:f for f in facts}
        checks=self.store.list_objects('SourceVerification',scope)
        responses=self.store.list_objects('MaterialIssueResponse',scope)
        valid_source={aid:self.source_valid(a) for aid,a in files.items()}
        automatic = self.service.invoice_amounts.automatic_checks(scope, list(files.values()), facts)
        unusable=set()
        for result in readiness.get('usable_results',[]):
            if result.get('kind')=='group':
                members=result.get('source_ids',[])
                if any(fid not in facts_by_id or not valid_source.get(facts_by_id[fid]['data']['source_artifact_id'],False) for fid in members):
                    unusable.update(members)
        verified={}
        for check in checks:
            b=check['data']['binding']; f=facts_by_id.get(b['fact_id']);a=files.get(b['artifact_id'])
            if check['status']=='VERIFIED' and f and a and valid_source[a['object_id']] and self.eligible(f,a,scope) and b==self.binding(f,a):
                verified[f['object_id']]=check
        records=[]
        assigned={x['data']['binding']['fact_id']:x for x in self.service.bank_periods.assignments(scope) if x['valid']}
        for row in readiness['records']:
            if row['source_artifact_id'] not in files:
                continue
            f=facts_by_id[row['object_id']];a=files[row['source_artifact_id']]
            issues=list(dict.fromkeys('bank_account_ref：请确认流水所属的企业账户' if i.startswith(('本方账户：','bank_account_ref：')) else i for i in row['issues']))
            bill = self.service.bills.supports(f)
            confirmation = bill_confirmations.get(f['object_id'])
            role_confirmed = bool(confirmation and confirmation['status']=='CONFIRMED')
            invoice_confirmation=invoice_confirmations.get(f['object_id'])
            auto_check = automatic.get(f['object_id'])
            if invoice_confirmation or auto_check:issues=[i for i in issues if i!=DISPLAY_ISSUE]
            if role_confirmed:
                issues = [i for i in issues if i not in {DISPLAY_ROLE_ISSUE, PERIOD_ISSUE}]
                if confirmation['data']['account_status'] != 'BASELINE':
                    issues.append('会计科目：拟用或历史科目仍待核对，不自动建立科目或制证')
            if not valid_source[a['object_id']]:
                issues.append('原件哈希或存储状态异常，禁止核实')
            eligible=self.eligible(f,a,scope) and valid_source[a['object_id']]
            if auto_check:
                from app.invoice_review import ISSUE
                effective = {**f, 'status': 'PARSED' if f['status']=='NEEDS_REVIEW' else f['status'],
                             'data': {**f['data'], 'extraction_issues': [i for i in f['data'].get('extraction_issues',[]) if i != ISSUE]}}
                eligible = self.eligible(effective, a, scope) and valid_source[a['object_id']]
            if not eligible and not issues and not role_confirmed and not invoice_confirmation:
                issues.append('bank_account_ref：请确认流水所属的企业账户' if a['data'].get('parse_options',{}).get('document_kind')=='bank_statement' else '来源或解析版本未满足核实条件，请核对原件当前提取结果')
            state='PERIOD_EXCEPTION' if row['state']=='PERIOD_EXCEPTION' else 'NEEDS_REVIEW' if issues or not eligible else 'SOURCE_VERIFIED' if f['object_id'] in verified else 'AWAITING_VERIFICATION'
            if role_confirmed:
                state = 'NEEDS_REVIEW' if issues else 'BUSINESS_CONFIRMED'
            if invoice_confirmation and not issues:
                state = 'ISSUE_CONFIRMED'
            period_assignment=assigned.get(f['object_id'])
            if period_assignment:
                issues=[i for i in issues if not i.startswith('业务期间：不属于已核定的本期业务范围')]
                state='NEEDS_REVIEW' if issues else 'OTHER_PERIOD'
                eligible=False
            records.append({**row,'state':state,'issues':issues,'eligible':eligible,
                'period_assignment':period_assignment,
                'automatic_invoice_check':auto_check,
                'invoice_amount_confirmation':invoice_confirmation,
                'bill_supported':bill, 'bill_confirmation':confirmation,
                'original_value':f['data'].get('original_value',{}),
                'comparison':compare_fields(f['data']),
                'verification':verified.get(f['object_id'])})
        tasks=[]
        def task(kind,artifact,title,rows,reason,action):
            if reason.startswith('bank_account_ref：'):title='确认流水所属银行'
            binding={'artifact_id':artifact['object_id'],'version':artifact['version'],'sha256':artifact['data'].get('sha256'),
                     'records':[(r['object_id'],r['version']) for r in rows],'kind':kind,'reason':reason}
            key='material-'+digest(binding)
            response=next((r for r in responses if r['data'].get('task_id')==key and r['status']=='DEFERRED'),None)
            tasks.append({'id':key,'kind':kind,'artifact_id':artifact['object_id'],'artifact_version':artifact['version'],
                'filename':artifact['data']['filename'],'title':title,'reason':reason,'record_ids':[r['object_id'] for r in rows],
                'action':action,'deferred':bool(response),'response':response})
        for a in files.values():
            status=a['data'].get('parse_status','RECEIVED')
            if status=='RECONCILIATION_FAILED':
                task('PARSE',a,'核对解析对账差异',[],
                     '；'.join(a['data'].get('parse_errors',[])) or '原件明细与对账依据不一致，请核对结构方案','parse')
                continue
            if status in {'RECEIVED','FAILED'}:
                from app.tabular import PARSER_VERSION
                retryable=status=='RECEIVED' or a['data'].get('parse_version')!=PARSER_VERSION
                task('PARSE',a,'识别资料' if status=='RECEIVED' else '处理识别失败',[],
                     '；'.join(a['data'].get('parse_errors',[])) or '原件已保存，尚未提取', 'parse' if retryable else 'supplement')
            eligible=[r for r in records if r['source_artifact_id']==a['object_id'] and r['state']=='AWAITING_VERIFICATION' and not r.get('automatic_invoice_check')]
            for start in range(0,len(eligible),5):
                task('VERIFY',a,'核对原件与提取值',eligible[start:start+5],'请逐条比较原始数据与提取值；仅选择已核对的本页记录。','verify')
            problem_records=[r for r in records if r['source_artifact_id']==a['object_id'] and r['state'] in {'PERIOD_EXCEPTION','NEEDS_REVIEW'}]
            reasons=dict.fromkeys(reason for r in problem_records for reason in r['issues'])
            for reason in reasons:
                rows = [r for r in problem_records if reason in r['issues']]
                if reason in {DISPLAY_ROLE_ISSUE, PERIOD_ISSUE}:
                    rows = [r for r in rows if not r['bill_supported']]
                if rows:
                    if reason==DISPLAY_ISSUE:
                        for row in rows:
                            if self.service.invoice_amounts.supports(facts_by_id[row['object_id']]):
                                task('INVOICE_AMOUNT',a,'核对红字或零金额发票',[row],reason,'confirm_invoice_amount')
                                tasks[-1]['input_token']=self.service.invoice_amounts.input_token(scope,facts_by_id[row['object_id']],a)
                            else:task('ISSUE',a,reason,[row],reason,'supplement')
                    elif reason.startswith('会计科目：'):
                        for row in rows:
                            task('BILL_ACCOUNT',a,'核对票据拟用科目',[row],reason,'review_bill_account')
                    else:
                        task('ISSUE',a,reason,rows,reason,'supplement')
            for r in problem_records:
                if r['bill_supported'] and (not r['bill_confirmation'] or r['bill_confirmation']['status']=='OPINION'):
                    task('BILL',a,'确认票据业务与科目',[r],'确认票据业务与科目','confirm_bill')
                    tasks[-1]['input_token'] = self.service.bills.input_token(scope,facts_by_id[r['object_id']],a)
            if a['data'].get('parse_options',{}).get('document_kind')=='bank_statement' and not any(r.startswith('bank_account_ref：') for r in reasons):
                candidate=self.service.bank_accounts.candidate(scope,a)
                if candidate['status']!='LINKED':
                    reason='bank_account_ref：请确认流水所属的企业账户'
                    task('ISSUE',a,reason,[r for r in records if r['source_artifact_id']==a['object_id']],reason,'supplement')
        from app.task_descriptors import describe_task
        record_index = {r['object_id']: r for r in records}
        for item in tasks:
            artifact = files[item['artifact_id']]
            self.service.bank_periods.decorate(scope,item,[record_index[rid] for rid in item['record_ids']],
                artifact,[facts_by_id[rid] for rid in item['record_ids']])
            bank = self.service.bank_accounts.candidate(scope, artifact) if item['reason'].startswith('bank_account_ref：') else None
            item['descriptor'] = describe_task(item, scope, artifact,
                [record_index[rid] for rid in item['record_ids']], bank)
        counts=Counter(r['state'] for r in records)
        parse_counts=Counter('failed' if a['data'].get('parse_status') in {'FAILED','RECONCILIATION_FAILED'} else 'pending' if a['data'].get('parse_status','RECEIVED')=='RECEIVED' else 'extracted' for a in files.values())
        return {'version':'material-review-v2','records':records,'tasks':tasks,
            'categories':[{**c,'source_verified_count':sum(r['state']=='SOURCE_VERIFIED' for r in records if r['category_id']==c['id'])} for c in categories],
            'counts':{'files':len(files),'unassigned_files':sum(aid not in files for c in readiness['categories'] if c['id']=='unassigned' for aid in c['artifact_ids']),'file_states':dict(parse_counts),'records':len(records),'source_verified':counts['SOURCE_VERIFIED'],
                'awaiting_verification':counts['AWAITING_VERIFICATION'],'needs_review':counts['NEEDS_REVIEW'],
                'other_period':counts['OTHER_PERIOD'],
                'business_confirmed':counts['BUSINESS_CONFIRMED'], 'bill_confirmed':sum(c['status']=='CONFIRMED' for c in bill_confirmations.values()),
                'issue_confirmed':counts['ISSUE_CONFIRMED'], 'invoice_amount_confirmed':len(invoice_confirmations),
                'system_checked':counts['AWAITING_VERIFICATION']+counts['SOURCE_VERIFIED'],
                'issue_tasks':sum(t['kind']!='VERIFY' and not t['deferred'] for t in tasks),
                'period_exceptions':counts['PERIOD_EXCEPTION'],'accounting_usable':sum(r['state']=='CHECKED' and r['object_id'] not in unusable and valid_source.get(r['source_artifact_id'],False) for r in readiness['records']),
                'supplement_issues':len({(b['group_id'],e) for c in categories for b in c.get('business_issues',[]) for e in b.get('missing_evidence',[])}),
                'deferred':sum(t['deferred'] for t in tasks),'active_tasks':sum(not t['deferred'] for t in tasks)}}

    def execute(self, scope, action, target, version, actor, payload):
        self.service._ensure_period_open(scope)
        obj=self.store.get_object(target,scope)
        if obj['version']!=version:
            raise VersionConflict()
        if action=='revoke_source_verification':
            if set(payload)-{'reason'} or not isinstance(payload.get('reason',''),str) or len(payload.get('reason',''))>2000 or obj['status']!='VERIFIED':
                raise PreconditionFailed('核实记录已撤销或请求字段无效')
            revised=self.store.revise_object(target,version,scope,{**obj['data'],'revoked_by':actor,'revoked_at':utcnow(),'revocation_reason':payload.get('reason','').strip()},status='REVOKED',created_by=actor)
            self.store.add_audit('SOURCE_VERIFICATION_REVOKED',actor,scope,object_id=target,object_version=revised['version'],before=obj,after=revised,reason='仅撤销资料核实，不改变财务事实')
            return {'object':revised}
        try:
            value=(ReasonInput if action=='defer_material_issue' else VerifyInput).model_validate(payload)
        except ValidationError as exc:
            raise PreconditionFailed('请填写有效原因或选择当前页记录；不允许提交修改值或责任人') from exc
        if action=='defer_material_issue':
            overview=self.service.workbench(scope)['material_review']
            task=next((t for t in overview['tasks'] if t['id']==value.task_id and t['artifact_id']==target),None)
            if not task or task['kind']=='VERIFY':
                raise PreconditionFailed('问题已变化，请刷新后核对；资料核实事项可暂时跳过')
            key='material-response-'+digest({'scope':scope.model_dump(),'task':task['id']})
            existing=[r for r in self.store.list_objects('MaterialIssueResponse',scope) if r['object_id']==key]
            if existing:
                return {'object':existing[0]}
            data={'task_id':task['id'],'artifact_id':target,'artifact_version':version,'reason':value.reason,'actor':actor,'recorded_at':utcnow(),'effect':'仍待补充，不改变财务门禁'}
            saved=self.store.create_initial_object('MaterialIssueResponse',scope,data,status='DEFERRED',created_by=actor,object_id=key)
            self.store.add_audit('MATERIAL_ISSUE_DEFERRED',actor,scope,object_id=key,object_version=1,after=saved,reason=value.reason)
            return {'object':saved}
        if not self.source_valid(obj):
            raise PreconditionFailed('原件哈希或存储状态已变化，禁止核实')
        refs=value.records
        task=next((t for t in self.service.workbench(scope)['material_review']['tasks'] if t['id']==value.task_id and t['kind']=='VERIFY' and t['artifact_id']==target),None)
        if not task or not {r.object_id for r in refs}.issubset(task['record_ids']):
            raise PreconditionFailed('核实页面已变化或包含未展示的记录，请刷新后选择当前事项')
        if len({r.object_id for r in refs})!=len(refs):
            raise PreconditionFailed('不可重复选择同一条记录')
        from app.tabular import extract_workbook, ParseOptions, ExtractionError
        root=self.store.database.settings.storage_path
        try:
            if obj['data'].get('plan_ref'):
                extracted=self.service.parse_plans.replay(scope,obj)
            elif obj['data'].get('payroll_mapping_id'):
                extracted=self.service.payroll_mapping.replay(scope,obj)
            else:
                extracted=extract_workbook((root/obj['data']['storage_path']).read_bytes(),ParseOptions(**obj['data']['parse_options']),scope.accounting_period_id)
            if obj['data']['parse_options']['document_kind']=='bank_statement':
                extracted=self.service.bank_accounts.replay(scope,obj,extracted)
        except (ExtractionError,ValidationError) as exc:
            raise PreconditionFailed('当前原件不能重新验证，请先处理解析问题') from exc
        results=[]
        for ref in refs:
            f=self.store.get_object(ref.object_id,scope)
            if f['version']!=ref.version:
                raise VersionConflict()
            if f['data'].get('source_artifact_id')!=target or not self.eligible(f,obj,scope):
                raise PreconditionFailed('记录有字段缺口、期间异常或来源已失效，不能确认资料核实')
            source=next((r for r in extracted['records'] if r['source_anchor']==f['data']['source_anchor'] and r['record_type']==f['data']['record_type']),None)
            if not source or source['extraction_issues'] or source['period_check']!='PASS' or source['normalized_value']!=f['data']['normalized_value'] or source['field_sources']!=f['data']['field_sources']:
                raise PreconditionFailed('提取值与当前原件重新校验不一致，请重新提取后核对')
            binding=self.binding(f,obj)
            key='source-check-'+digest({'scope':scope.model_dump(),'binding':binding})
            prior=next((v for v in self.store.list_objects('SourceVerification',scope) if v['object_id']==key),None)
            if prior and prior['status']=='VERIFIED':
                results.append(prior);continue
            data={'binding':binding,'note':value.note,'verified_by':actor,'verified_at':utcnow(),'effect':'仅资料核实，不授予账务许可'}
            saved=self.store.revise_object(key,prior['version'],scope,data,status='VERIFIED',created_by=actor) if prior else self.store.create_initial_object('SourceVerification',scope,data,status='VERIFIED',created_by=actor,object_id=key)
            self.store.add_audit('SOURCE_VALUES_VERIFIED',actor,scope,object_id=key,object_version=saved['version'],before=prior,after=saved,reason='原件与提取值人工核对，保留财务门禁')
            results.append(saved)
        return {'objects':results,'verified_count':len(results)}

    def execute_task_action(self, scope, target, version, actor, role, payload):
        """Persist one fallback decision without mutating evidence or finance objects."""
        self.service._ensure_period_open(scope)
        artifact = self.store.get_object(target, scope)
        if artifact['version'] != version or artifact['object_type'] != 'SourceArtifact':
            raise VersionConflict()
        if not self.source_valid(artifact):
            raise PreconditionFailed('原件已失效或哈希不一致，不能执行人工兜底动作')
        try:
            value = TaskActionInput.model_validate(payload)
        except ValidationError as exc:
            raise PreconditionFailed('任务动作字段无效，请刷新后按当前表单填写') from exc
        definition = ACTION_TYPE_BY_ID.get(value.action_type_id)
        if not definition or value.action_type_id not in FALLBACK_IDS or not definition.fallback:
            raise PreconditionFailed('只能执行当前目录声明的兜底动作')
        if role not in definition.permissions:
            raise PermissionDenied('当前角色不能执行该任务动作')
        overview = self.service.workbench(scope, actor_id=actor)['material_review']
        task = next((item for item in overview['tasks']
                     if item['id'] == value.task_id and item['artifact_id'] == target), None)
        if not task or (task.get('triage') or {}).get('route') != 'HUMAN':
            raise PreconditionFailed('事项已变化或安全门禁未通过，请刷新后重新核对')
        descriptor = task.get('descriptor') or {}
        option = next((item for item in descriptor.get('options', [])
                       if item.get('id') == value.action_type_id and item.get('available')
                       and item.get('fallback') is True), None)
        if not option or descriptor.get('fingerprint') != value.descriptor_hash:
            raise VersionConflict('事项动作目录或依据版本已变化，请刷新后重试')
        expected = {field.name for field in definition.fields}
        if set(value.values) != expected:
            raise PreconditionFailed('请只填写当前动作声明的决策字段')
        inputs = {}
        for field in definition.fields:
            entered = value.values.get(field.name, '').strip()
            if field.required and not entered:
                raise PreconditionFailed(f'请填写{field.label}')
            if len(entered) > field.max_length:
                raise PreconditionFailed(f'{field.label}内容过长')
            inputs[field.name] = entered
        if value.action_type_id == 'request_supplement':
            vague = {'资料', '材料', '补充资料', '相关资料', '待确认', '待核验', '不清楚'}
            if inputs['material'] in vague or inputs['fact_to_verify'] in vague \
                    or len(inputs['material']) < 4 or len(inputs['fact_to_verify']) < 6:
                raise PreconditionFailed('请分别写明具体材料名称和需要核验的具体事实')
        if value.action_type_id == 'mark_out_of_scope':
            self._assert_not_in_formal_downstream(scope, task['record_ids'])
        active = [item for item in self.store.list_objects('Decision', scope)
                  if item['status'] == 'CONFIRMED'
                  and item['data'].get('decision_type') == 'TASK_ACTION'
                  and item['data'].get('task_id') == task['id']]
        if active:
            raise PreconditionFailed('本事项已有有效处置记录，请先撤销后再选择')
        escalation = {'operator': 'accountant', 'accountant': 'admin'}.get(role)
        if value.action_type_id == 'escalate' and escalation is None:
            raise PreconditionFailed('管理员已是当前最高权限，请改用其他处置或线下治理入口')
        key = 'task-action-' + digest({'scope': scope.model_dump(), 'task_id': task['id']})
        previous = next((item for item in self.store.list_objects('Decision', scope)
                         if item['object_id'] == key), None)
        data = {
            'decision_type': 'TASK_ACTION', 'action_catalog_version': 'action-catalog-v1',
            'action_type_id': value.action_type_id, 'task_id': task['id'],
            'descriptor_hash': value.descriptor_hash, 'binding': descriptor['scope'],
            'inputs': inputs, 'effects': [item.model_dump() for item in definition.effects],
            'grants_accounting_usable': False, 'decided_by': actor, 'decided_at': utcnow(),
            'escalated_to_role': escalation if value.action_type_id == 'escalate' else None,
            'candidate_request': {'event': 'ACTION_TYPE_CANDIDATE_REQUESTED', 'status': 'AUDIT_ONLY'},
        }
        saved = (self.store.revise_object(key, previous['version'], scope, data, status='CONFIRMED', created_by=actor)
                 if previous else self.store.create_initial_object(
                     'Decision', scope, data, status='CONFIRMED', created_by=actor, object_id=key
                 ))
        self.store.add_audit('TASK_ACTION_EXECUTED', actor, scope, object_type='Decision',
                             object_id=key, object_version=saved['version'], before=previous, after=saved,
                             evidence=task['record_ids'], reason=value.action_type_id)
        self.store.add_audit('ACTION_TYPE_CANDIDATE_REQUESTED', actor, scope, object_type='Decision',
                             object_id=key, object_version=saved['version'], after={
                                 'action_type_id': value.action_type_id, 'task_id': task['id'],
                                 'status': 'AUDIT_ONLY',
                             }, reason='阶段 2 仅预留审计接口；未创建动作、未自动审批')
        return {'object': saved, 'action_type': definition.model_dump()}

    def revoke_task_action(self, scope, target, version, actor, payload):
        self.service._ensure_period_open(scope)
        decision = self.store.get_object(target, scope)
        if decision['version'] != version:
            raise VersionConflict()
        if decision['object_type'] != 'Decision' or decision['status'] != 'CONFIRMED' \
                or decision['data'].get('decision_type') != 'TASK_ACTION':
            raise PreconditionFailed('任务动作已撤销、失效或目标类型不匹配')
        try:
            value = RevokeTaskActionInput.model_validate(payload)
        except ValidationError as exc:
            raise PreconditionFailed('请填写有效撤销原因') from exc
        data = {**decision['data'], 'revoked_by': actor, 'revoked_at': utcnow(),
                'revocation_reason': value.reason}
        saved = self.store.revise_object(target, version, scope, data, status='REVOKED', created_by=actor)
        self.store.add_audit('TASK_ACTION_REVOKED', actor, scope, object_type='Decision',
                             object_id=target, object_version=saved['version'], before=decision, after=saved,
                             evidence=[item['id'] for item in decision['data']['binding'].get('records', [])],
                             reason=value.reason)
        return {'object': saved}

    def _assert_not_in_formal_downstream(self, scope, record_ids):
        selected = set(record_ids)
        groups = [item for item in self.store.list_objects('ProcessingGroup', scope)
                  if item['status'] not in {'VOID', 'MERGED'}
                  and selected.intersection(item['data'].get('member_fact_ids', []))]
        if groups:
            raise PreconditionFailed('绑定记录已进入正式下游流程，不能标记本期不处理')

    def task_action_projection(self, scope, material):
        """Apply only current, version-bound decisions to the read model."""
        decisions = [item for item in self.store.list_objects('Decision', scope)
                     if item['data'].get('decision_type') == 'TASK_ACTION']
        tasks = {item['id']: item for item in material.get('tasks', [])}
        records = {item['object_id']: item for item in material.get('records', [])}
        projected = []
        for decision in decisions:
            task = tasks.get(decision['data'].get('task_id'))
            valid = bool(
                decision['status'] == 'CONFIRMED' and task
                and decision['data'].get('descriptor_hash') == task.get('descriptor', {}).get('fingerprint')
                and decision['data'].get('binding') == task.get('descriptor', {}).get('scope')
            )
            item = {**decision, 'valid': valid}
            projected.append(item)
            if not valid:
                continue
            task['task_action'] = item
            if decision['data']['action_type_id'] == 'mark_out_of_scope':
                for ref in decision['data']['binding'].get('records', []):
                    row = records.get(ref['id'])
                    if row:
                        row['eligible'] = False
                        row['period_disposition'] = 'OUT_OF_SCOPE'
        material['task_action_records'] = projected
        return material
