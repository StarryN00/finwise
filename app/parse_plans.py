"""Source-bound structure proposals; external inference never owns a transaction."""
from copy import deepcopy
import hashlib
from pathlib import Path
import time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.db import utcnow
from app.parse_plan import VERSION, EXECUTOR_VERSION, KINDS, Proposal, builtin, execute, packet, signature, fields_for, column_index
from app.tabular import read_workbook
from app.ontology.contracts import Scope
from app.ontology.errors import DomainError, PermissionDenied, PreconditionFailed, VersionConflict
from app.ontology.gateway import GatewayFailure
from app.ontology.store import digest, scope_key

TYPE = 'ParsePlan'

# Closed local messages only: never serialize ValidationError input values or
# provider/exception text. Codes distinguish failures without leaking raw output.
EXECUTION_ERRORS = {
    '方案必须逐一覆盖全部工作表':'SHEET_COVERAGE',
    '参考或未知工作表不能同时声明取值字段':'REFERENCE_FIELDS',
    '表头定位不存在':'HEADER_NOT_FOUND',
    '同一列不能重复绑定字段':'DUPLICATE_COLUMN',
    '方案包含未知目标字段':'UNKNOWN_FIELD',
    '映射列没有原始表头依据':'COLUMN_WITHOUT_HEADER',
    '需要指出日期、标识和金额列；不能降低必需字段':'REQUIRED_FIELDS',
    '参考行定位不存在或重复':'INVALID_REFERENCE_ROWS',
    '字段列定位无效':'INVALID_COLUMN',
}


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: Scope
    artifact_id: StrictStr = Field(min_length=1, max_length=256)
    artifact_version: StrictInt = Field(ge=1)
    document_kind: Literal['bank_statement', 'purchase_invoices', 'sales_invoices']
    row_start: Optional[StrictInt] = Field(default=None,ge=1,le=20000)
    page_size: StrictInt = Field(default=40,ge=1,le=100)


class PlanRequest(InspectRequest):
    stage: Literal['STRUCTURE_PLAN']
    idempotency_key: StrictStr = Field(min_length=1, max_length=128)


class ParsePlanService:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def authorized(self, scope, actor, role=None):
        if role is not None and role not in {'operator','accountant','admin'}:
            raise PermissionDenied('当前角色不能识别或确认结构方案')
        if not self.store.database.settings.require_auth:
            return
        with self.store.database.connect() as connection:
            user = connection.execute('SELECT role,enabled FROM auth_users WHERE user_id=?', (actor,)).fetchone()
            grant = connection.execute('SELECT 1 FROM auth_scope_grants WHERE user_id=? AND scope_json=?', (actor,scope_key(scope))).fetchone()
        if not user or not user['enabled'] or user['role'] not in {'operator','accountant','admin'} or not grant:
            raise PermissionDenied('操作人的权限或处理范围已变化')

    def source(self, scope, artifact_id, version, kind):
        a = self.store.get_object(artifact_id,scope)
        if a['version'] != version:
            raise VersionConflict('原件版本已变化，请刷新结构方案')
        if (a['object_type'] != 'SourceArtifact' or a['status'] != 'ACTIVE'
                or a['data'].get('period_check') != 'PASS'
                or a['data'].get('observed_period') != scope.accounting_period_id):
            raise PreconditionFailed('请选择当前期间有效原件')
        if kind not in KINDS or a['data'].get('payroll_mapping_id'):
            raise PreconditionFailed('此资料类型不能使用当前结构方案')
        if (Path(a['data']['filename']).suffix.lower() not in {'.xls','.xlsx'}
                or any(s.get('layout') in {'single_amount_bank','boc-text-v1'} for s in a['data'].get('parse_sheets',[]))):
            raise PreconditionFailed('此原件使用专用解析通道，当前结构方案只支持三类Excel表格')
        previous = a['data'].get('parse_options',{}).get('document_kind')
        if previous and previous != kind:
            raise PreconditionFailed('结构方案不能更改原件资料类型')
        root = self.store.database.settings.storage_path.resolve()
        path = (root/a['data']['storage_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PreconditionFailed('原件存储路径无效')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != a['data'].get('sha256'):
            raise PreconditionFailed('原件哈希校验失败')
        if kind=='bank_statement':
            for sheet in read_workbook(content):
                rows=[r for r in sheet['rows'] if any(v not in (None,'') for v in r['values'])]
                if any({'交易类型','交易金额','交易时间','余额'} <= {str(v or '').strip() for v in r['values']} for r in rows[:20]):
                    raise PreconditionFailed('单金额银行流水请沿用专用解析通道，不能改成收支双列方案')
        return a,content

    def inspect(self, request):
        a,content = self.source(request.scope,request.artifact_id,request.artifact_version,request.document_kind)
        sheets = read_workbook(content)
        samples = []
        for index,sheet in enumerate(sheets):
            rows = ([r for r in sheet['rows'] if request.row_start<=r['row']<request.row_start+request.page_size]
                    if request.row_start is not None else sheet['rows'][:40]+sheet['rows'][-20:])
            chosen = {r['row']:r for r in rows}
            samples.append({'sheet_index':index,'name':sheet['name'],
                'rows':[chosen[n] for n in sorted(chosen)],'total_rows':len(sheet['rows']),
                'merged_cells':sheet.get('merged_cells',[])})
        return {'artifact':{'object_id':a['object_id'],'version':a['version'],
                            'filename':a['data']['filename'],'sha256':a['data']['sha256']},
                'document_kind':request.document_kind,'sheets':samples,
                'proposal':builtin(sheets,request.document_kind).model_dump(),
                'parse_plans':[p for p in self.view(request.scope) if p['data']['artifact_id']==a['object_id']]}

    def request(self, request, actor, role):
        scope = request.scope
        self.authorized(scope,actor,role)
        identity = 'parseplan_'+digest([scope.model_dump(),actor,request.idempotency_key])
        request_hash = digest(request.model_dump())
        with self.store.database.transaction():
            self.service._ensure_period_open(scope)
            prior = next((p for p in self.store.list_objects(TYPE,scope) if p['object_id']==identity),None)
            if prior:
                if prior['data'].get('request_hash') != request_hash:
                    raise VersionConflict('相同请求编号不能用于不同原件或版本')
                if prior['status']=='RUNNING' and time.time()>prior['data']['expires_at']:
                    prior = self.store.revise_object(identity,prior['version'],scope,
                        {**prior['data'],'error':'识别已中断，请明确重新发起'},status='FAILED',created_by=actor)
                return {'object':prior,'idempotent':True}
            a,content = self.source(scope,request.artifact_id,request.artifact_version,request.document_kind)
            safe = packet(read_workbook(content),request.document_kind)
            settings = self.store.database.settings
            data = {'artifact_id':a['object_id'],'artifact_version':a['version'],
                    'sha256':a['data']['sha256'],'document_kind':request.document_kind,
                    'schema_version':VERSION,'executor_version':EXECUTOR_VERSION,
                    'input_hash':digest(safe),'request_hash':request_hash,'origin':'AI',
                    'requested_by':actor,'requested_at':utcnow(),
                    'expires_at':time.time()+settings.gateway_timeout_seconds*(settings.gateway_max_retries+1)+30}
            reused = self.reusable(scope,a,content,request.document_kind)
            if reused:
                template,proposal,preview = reused
                data.update(origin='REUSED_FORMAT',reused_from=template['object_id'],
                            proposal=proposal,preview=preview)
                job = self.store.create_initial_object(TYPE,scope,data,status='REVIEW',created_by=actor,object_id=identity)
                self.store.add_audit('STRUCTURE_PLAN_REUSED',actor,scope,object_id=identity,after={'reused_from':template['object_id']})
                return {'object':job,'idempotent':False}
            job = self.store.create_initial_object(TYPE,scope,data,status='RUNNING',created_by=actor,object_id=identity)
            self.store.add_audit('STRUCTURE_PLAN_REQUESTED',actor,scope,object_id=identity,after={'input_hash':data['input_hash']})
        metadata = {}
        retained_proposal = None
        phase = 'TRANSPORT'
        try:
            result = self.service.gateway.complete(scope,stage='STRUCTURE_PLAN',sanitized_input=safe)
            metadata = result.metadata()
            phase = 'SCHEMA'
            proposal = Proposal.model_validate(result.output).model_dump()
            phase = 'ANCHORS'
            for sheet in proposal['sheets']:
                if set(sheet['fields'])-set(fields_for(request.document_kind)):
                    raise ValueError('unsafe field vocabulary')
                for column in sheet['fields'].values():
                    column_index(column)
            # This object now contains only closed enums, bounded indices, known
            # system field names and Excel column anchors. It is safe to retain
            # even if the anchors do not form an executable plan.
            retained_proposal = proposal
            phase = 'OBSERVATION'
            # A model may only point at rows actually included in its packet.
            observed = {s['sheet_index']:{r['row'] for r in s['rows']} for s in safe['sheets']}
            for sheet in proposal['sheets']:
                if sheet['sheet_index'] not in observed or (sheet['role']=='DATA' and sheet['header_row'] not in observed[sheet['sheet_index']]):
                    raise ValueError('unobserved header')
                if any(r['row'] not in observed[sheet['sheet_index']] for r in sheet['reference_rows']):
                    raise ValueError('unobserved reference')
            phase = 'EXECUTION'
            preview = execute(content,proposal,request.document_kind,scope.accounting_period_id) if proposal['outcome']=='PLAN' else None
            values = {'proposal':proposal,'preview':preview}
            status = 'REVIEW' if preview is not None else 'NEEDS_INPUT'
        except Exception as exc:
            code = 'STRUCTURE_PLAN_'+phase+'_REJECTED'
            reason = {'TRANSPORT':'结构识别服务未返回有效结果','SCHEMA':'模型方案不符合结构契约',
                      'ANCHORS':'模型方案包含未知字段或非法列锚点',
                      'OBSERVATION':'模型指向了未提供样本的工作表、表头或参考行',
                      'EXECUTION':'结构方案未通过本地执行检查'}[phase]
            if isinstance(exc,GatewayFailure):
                code = exc.code
            elif phase=='EXECUTION' and type(exc) is ValueError and str(exc) in EXECUTION_ERRORS:
                code = 'STRUCTURE_PLAN_'+EXECUTION_ERRORS[str(exc)]
                reason = str(exc)  # Exact match to the closed local messages above.
            metadata = {**metadata,'error_code':code,'validation_stage':phase}
            values = {'error':reason+'；请核对结构方案后重新预览',
                      'validation_stage':phase,'validation_error_code':code}
            if retained_proposal is not None:
                values.update(proposal=retained_proposal,proposal_hash=digest(retained_proposal))
            status = 'FAILED'
        with self.store.database.transaction():
            latest = self.store.get_object(identity,scope)
            if latest['version']!=job['version'] or latest['status']!='RUNNING':
                return {'object':latest,'idempotent':True}
            try:
                self.authorized(scope,actor,role)
                self.service._ensure_period_open(scope)
                self.source(scope,a['object_id'],a['version'],request.document_kind)
                if time.time()>data['expires_at']:
                    raise PreconditionFailed('识别超时')
            except (DomainError,KeyError,OSError):
                values = {'error':'原件、期间或权限已变化，本次方案未采用'}
                status = 'FAILED'
            updated = self.store.revise_object(identity,job['version'],scope,
                {**data,**values,'gateway':metadata,'finished_at':utcnow()},status=status,created_by=actor)
            self.store.add_audit('STRUCTURE_PLAN_FINISHED',actor,scope,object_id=identity,
                after={'status':status,'gateway':metadata})
        return {'object':updated,'idempotent':False}

    def reusable(self, scope, artifact, content, kind):
        sheets = read_workbook(content)
        for entry in self.store.list_scope_objects():
            other = Scope(**entry['data']['scope'])
            if any(getattr(other,k)!=getattr(scope,k) for k in ('tenant_id','organization_id','legal_entity_id','ledger_id')):
                continue
            for job in reversed(self.store.list_objects(TYPE,other)):
                data = job['data']
                if (job['status']!='APPLIED' or data.get('document_kind')!=kind
                        or data.get('schema_version')!=VERSION or data.get('executor_version')!=EXECUTOR_VERSION):
                    continue
                proposal = data.get('proposal')
                try:
                    if any(s.get('reference_rows') for s in proposal['sheets']):
                        continue
                    source = self.store.get_object(data['artifact_id'],other)
                    ref = source['data'].get('plan_ref',{})
                    if (source['status']!='ACTIVE' or source['version']!=data.get('applied_artifact_version')
                            or ref.get('plan_id')!=job['object_id'] or ref.get('plan_version')!=job['version']):
                        continue
                    if signature(sheets,proposal)!=data.get('layout_signature'):
                        continue
                    result = execute(content,proposal,kind,scope.accounting_period_id,
                                     artifact['data'].get('parse_options',{}).get('bank_account_ref'))
                    if not result.get('apply_ready'):
                        continue
                except (ValueError,KeyError,IndexError,TypeError):
                    continue
                return job,proposal,result
        return None

    def impact(self, scope, artifact, extracted):
        objects = self.store.list_objects(None,scope)
        facts = [f for f in objects if f['object_type']=='FactRecord'
                 if f['data'].get('source_artifact_id')==artifact['object_id'] and f['status']!='SUPERSEDED']
        def references(value):
            if isinstance(value,str):return {value}
            if isinstance(value,dict):return set().union(*(references(v) for v in value.values()))
            if isinstance(value,list):return set().union(*(references(v) for v in value))
            return set()
        affected = {artifact['object_id'],*(f['object_id'] for f in facts)}
        checks = []
        candidates = [o for o in objects if o['object_type'] not in
                      {'SourceArtifact','FactRecord','ParsePlan','PayrollMapping','Scope','MaterialIssueResponse'}
                      and o['status'] not in {'REVOKED','SUPERSEDED','VOID','EXPIRED','MERGED'}]
        # Follow exact persisted object references through confirmations, evidence,
        # groups, historical results, vouchers and delivery approvals.
        while True:
            linked = [o for o in candidates if o['object_id'] not in affected and references(o['data']) & affected]
            if not linked:break
            checks.extend(linked);affected.update(o['object_id'] for o in linked)
        checks.sort(key=lambda o:o['object_id'])
        counts = {}
        for obj in checks:counts[obj['object_type']]=counts.get(obj['object_type'],0)+1
        confirmations = sum(o['status'] in {'VERIFIED','CONFIRMED','APPROVED','REVIEWED','OPINION'} for o in checks)
        return {'previous_fact_count':len(facts),'new_fact_count':len(extracted['records']),
                'invalidated_confirmation_count':confirmations,'dependent_check_count':len(checks),
                'dependency_counts':counts,
                'dependencies':[{'object_id':o['object_id'],'object_type':o['object_type'],
                                 'version':o['version'],'status':o['status'],'effect':'来源版本变化后需重新评估'} for o in checks],
                'message':'关联确认和下游校验需重新评估；此处列出影响范围，不代表已删除或全部失效。',
                'basis_hash':digest([[o['object_id'],o['version'],o['status']] for o in facts+checks])}

    def extracted(self, scope, artifact, content, proposal, kind):
        try:
            result = execute(content,proposal,kind,scope.accounting_period_id,
                             artifact['data'].get('parse_options',{}).get('bank_account_ref'))
        except (ValueError,KeyError,IndexError) as exc:
            raise PreconditionFailed('结构方案不能执行，请核对工作表、表头和字段定位') from exc
        if kind=='bank_statement':
            result = self.service.bank_accounts.prepare(scope,artifact,result)
        return result

    def token(self, job_id, version, artifact, proposal, extracted, impact):
        extracted = deepcopy(extracted)
        # Account attachment timestamps change on every read, not its evidence.
        extracted.get('bank_account_binding',{}).pop('confirmed_at',None)
        return digest([job_id,version,artifact['scope'],artifact['object_id'],artifact['version'],
                       artifact['data']['sha256'],VERSION,EXECUTOR_VERSION,proposal,extracted,impact])

    def preview(self, scope, target_id, version, actor, payload):
        self.authorized(scope,actor)
        target = self.store.get_object(target_id,scope)
        if target['version']!=version:
            raise VersionConflict()
        if target['object_type']=='SourceArtifact':
            if set(payload)!={'proposal','document_kind'}:
                raise PreconditionFailed('首次预览只接受结构方案和资料类型')
            kind = payload['document_kind']
            a,content = self.source(scope,target_id,version,kind)
            data = {'artifact_id':a['object_id'],'artifact_version':version,'sha256':a['data']['sha256'],
                    'document_kind':kind,'schema_version':VERSION,'executor_version':EXECUTOR_VERSION,
                    'origin':'HUMAN','requested_by':actor,'requested_at':utcnow()}
            target = None
        else:
            if target['object_type']!=TYPE or target['status'] not in {'REVIEW','NEEDS_INPUT','FAILED'} or set(payload)!={'proposal'}:
                raise PreconditionFailed('方案状态或预览请求已变化')
            data = deepcopy(target['data']);kind = data['document_kind']
            a,content = self.source(scope,data['artifact_id'],data['artifact_version'],kind)
            self.validate_binding(data,a)
        try:proposal = Proposal.model_validate(payload['proposal']).model_dump()
        except ValueError as exc:raise PreconditionFailed('结构方案只接受约定的锚点字段') from exc
        result = self.extracted(scope,a,content,proposal,kind)
        impact = self.impact(scope,a,result)
        if target is None:
            target = self.store.create_initial_object(TYPE,scope,data,status='REVIEW',created_by=actor)
        if data.get('proposal')!=proposal:
            data['origin']='HUMAN'
        data.update(proposal=proposal,preview=result,impact=impact,
                    layout_signature=signature(read_workbook(content),proposal),
                    proposal_hash=digest(proposal),previewed_by=actor,previewed_at=utcnow())
        data.pop('error',None)
        data.pop('validation_stage',None)
        data.pop('validation_error_code',None)
        data['preview_token']=self.token(target['object_id'],target['version']+1,a,proposal,result,impact)
        updated = self.store.revise_object(target['object_id'],target['version'],scope,data,status='REVIEW',created_by=actor)
        return {'object':updated}

    def validate_binding(self, data, artifact):
        if (data.get('sha256')!=artifact['data']['sha256'] or data.get('schema_version')!=VERSION
                or data.get('executor_version')!=EXECUTOR_VERSION):
            raise PreconditionFailed('原件或结构执行器已变化，请重新预览方案')

    def apply(self, scope, target_id, version, actor, payload):
        self.authorized(scope,actor)
        if set(payload)!={'proposal','preview_token','plan_confirmed'} or payload['plan_confirmed'] is not True:
            raise PreconditionFailed('请明确确认结构方案及本次影响')
        job = self.store.get_object(target_id,scope);data = job['data']
        if job['object_type']!=TYPE or job['version']!=version or job['status']!='REVIEW':
            raise PreconditionFailed('结构方案版本或状态已变化')
        a,content = self.source(scope,data['artifact_id'],data['artifact_version'],data['document_kind'])
        self.validate_binding(data,a)
        if payload['proposal']!=data.get('proposal') or not data.get('preview_token') or payload['preview_token']!=data['preview_token']:
            raise PreconditionFailed('字段方案已改变或尚未预览，请先更新预览')
        result = self.extracted(scope,a,content,data['proposal'],data['document_kind'])
        impact = self.impact(scope,a,result)
        if self.token(target_id,version,a,data['proposal'],result,impact)!=data['preview_token']:
            raise PreconditionFailed('提取结果或影响范围已变化，请重新预览')
        if not result.get('apply_ready') or result.get('errors') or result['checks']['overall']=='REVIEW':
            raise PreconditionFailed('仍有未确定行或对账问题，不能应用结构方案')
        ref = {'plan_id':target_id,'plan_version':version+1,'plan_origin':data['origin'],
               'sha256':data['sha256'],'proposal_hash':digest(data['proposal']),'executor_version':EXECUTOR_VERSION}
        options = a['data'].get('parse_options') or {'document_kind':data['document_kind']}
        effect = self.service.parse_artifact(scope,artifact_id=a['object_id'],actor_id=actor,
            expected_version=a['version'],payload=options,_mapped=result,_plan_ref=ref)
        updated = self.store.revise_object(target_id,version,scope,
            {**data,'confirmed_by':actor,'confirmed_at':utcnow(),'applied_artifact_version':effect['artifact']['version']},
            status='APPLIED',created_by=actor)
        return {**effect,'object':updated}

    def replay(self, scope, artifact):
        if artifact.get('scope')!=scope.model_dump():
            raise PreconditionFailed('原件 Scope 不匹配')
        ref = artifact['data'].get('plan_ref')
        if not isinstance(ref,dict):
            raise PreconditionFailed('原件缺少结构方案绑定')
        try:job = self.store.get_object(ref['plan_id'],scope)
        except KeyError as exc:raise PreconditionFailed('绑定的结构方案不存在') from exc
        data = job['data']
        a,content = self.source(scope,artifact['object_id'],artifact['version'],data['document_kind'])
        self.validate_binding(data,a)
        if (job['object_type']!=TYPE or job['status']!='APPLIED' or job['version']!=ref.get('plan_version')
                or data['artifact_id']!=a['object_id'] or data.get('applied_artifact_version')!=a['version']
                or a['data'].get('plan_ref')!=ref or ref.get('sha256')!=data['sha256']
                or ref.get('executor_version')!=EXECUTOR_VERSION or ref.get('proposal_hash')!=digest(data.get('proposal'))):
            raise PreconditionFailed('结构方案绑定已失效，请重新核对')
        # Account confirmation is replayed separately by MaterialReview.
        try:
            result = execute(content,data['proposal'],data['document_kind'],scope.accounting_period_id,
                             a['data'].get('parse_options',{}).get('bank_account_ref'))
        except (ValueError,KeyError,IndexError) as exc:raise PreconditionFailed('结构方案不能回放') from exc
        if not result.get('apply_ready') or result.get('errors'):
            raise PreconditionFailed('当前回放仍有结构或对账问题，请重新核对')
        return result

    def view(self, scope):
        result = []
        for job in self.store.list_objects(TYPE,scope):
            item = deepcopy(job)
            try:
                data = job['data']
                expected = data.get('applied_artifact_version') if job['status']=='APPLIED' else data['artifact_version']
                artifact = self.store.get_object(data['artifact_id'],scope)
                if artifact['status']!='ACTIVE' or artifact['version']!=expected:
                    item['status']='STALE'
                item['data']['filename']=artifact['data']['filename']
            except (KeyError,DomainError):item['status']='STALE'
            result.append(item)
        return result
