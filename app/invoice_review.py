"""Version-bound acknowledgement of non-positive invoice amounts, not ledger approval."""
from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from app.db import utcnow
from app.ontology.errors import PreconditionFailed, VersionConflict
from app.ontology.store import digest

TYPE = 'InvoiceAmountConfirmation'
ISSUE = 'invoice_total：红字或零金额发票须人工核对'
DISPLAY_ISSUE = '价税合计：红字或零金额发票须人工核对'


class AmountInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    input_token: StrictStr = Field(min_length=1, max_length=100)
    reason: StrictStr = Field(min_length=1, max_length=2000)


class InvoiceAmountReview:
    def __init__(self, service):
        self.service, self.store = service, service.store

    @staticmethod
    def supports(f):
        d=f['data']
        return d.get('record_type') in {'INVOICE','SALES_INVOICE'} and ISSUE in d.get('extraction_issues',[])

    def source_ok(self, scope, f, a):
        return (self.supports(f) and a['status']=='ACTIVE'
                and a['data'].get('observed_period')==scope.accounting_period_id
                and a['data'].get('parse_status') in {'PARSED','PARSED_WITH_ISSUES'}
                and f['status'] not in {'VOID','ARCHIVED','SUPERSEDED'}
                and f['object_id'] in a['data'].get('parsed_fact_ids',[])
                and bool(f['data'].get('source_anchor')) and self.service.materials.source_valid(a))

    def input_token(self, scope, f, a):
        prior=next((c for c in self.store.list_objects(TYPE,scope) if c['data']['binding']['fact_id']==f['object_id']),None)
        return digest({'binding':self.service.materials.binding(f,a), 'prior':(prior['object_id'],prior['version'],prior['status']) if prior else None})

    def automatic_checks(self, scope, artifacts, facts):
        """Recheck retained sources without rewriting facts or human opinions."""
        from app.invoice_checks import red_invoice_evidence
        from app.tabular import extract_workbook, ParseOptions, ExtractionError
        aa = {a['object_id']: a for a in artifacts}
        replayed, out = {}, {}
        for f in facts:
            d = f['data']; a = aa.get(d.get('source_artifact_id'))
            if not a or not self.supports(f) or not red_invoice_evidence(d):
                continue
            if (not self.source_ok(scope, f, a)
                    or d.get('source_artifact_version') != a['version']):
                continue
            aid = a['object_id']
            if aid not in replayed:
                try:
                    result = (self.service.parse_plans.replay(scope, a) if a['data'].get('plan_ref') else
                        extract_workbook((self.store.database.settings.storage_path/a['data']['storage_path']).read_bytes(),
                            ParseOptions(**a['data']['parse_options']), scope.accounting_period_id))
                    replayed[aid] = [] if result.get('checks', {}).get('overall') == 'REVIEW' else result['records']
                except (ExtractionError, ValidationError, PreconditionFailed, VersionConflict, OSError, KeyError, ValueError):
                    replayed[aid] = []
            matching = [r for r in replayed[aid] if r['source_anchor'] == d.get('source_anchor')
                        and r['record_type'] == d.get('record_type')]
            if len(matching) != 1:
                continue
            source = matching[0]
            if any(source.get(k) != d.get(k) for k in ('normalized_value', 'field_sources', 'original_value', 'period_check')):
                continue
            check = red_invoice_evidence(source)
            if check:
                out[f['object_id']] = {**check, 'binding': self.service.materials.binding(f, a)}
        return out

    def view(self, scope, artifacts, facts):
        aa={a['object_id']:a for a in artifacts};ff={f['object_id']:f for f in facts};out=[]
        for c in self.store.list_objects(TYPE,scope):
            b=c['data']['binding'];f=ff.get(b['fact_id']);a=aa.get(b['artifact_id'])
            valid=bool(c['status']=='CONFIRMED' and f and a and self.source_ok(scope,f,a) and b==self.service.materials.binding(f,a))
            out.append({**c,'valid':valid,'stale':c['status']=='CONFIRMED' and not valid})
        return {'confirmations':out,'confirmed_count':sum(c['valid'] for c in out)}

    def execute(self, scope, action, target, version, actor, payload):
        self.service._ensure_period_open(scope)
        obj=self.store.get_object(target,scope)
        if obj['version']!=version:raise VersionConflict()
        if action=='revoke_invoice_amount':
            if set(payload)-{'reason'} or not isinstance(payload.get('reason',''),str) or len(payload.get('reason',''))>2000 or obj['status']!='CONFIRMED':
                raise PreconditionFailed('核对记录已撤销或请求字段无效')
            saved=self.store.revise_object(target,version,scope,{**obj['data'],'revoked_by':actor,'revoked_at':utcnow(),'revocation_reason':payload.get('reason','').strip()},status='REVOKED',created_by=actor)
            self.store.add_audit('INVOICE_AMOUNT_REVOKED',actor,scope,object_id=target,object_version=saved['version'],before=obj,after=saved,reason='撤销金额问题人工核对')
            return {'object':saved}
        try:value=AmountInput.model_validate(payload)
        except ValidationError as exc:raise PreconditionFailed('请填写核对说明；不允许修改金额或责任人') from exc
        if not self.supports(obj):raise PreconditionFailed('仅支持红字或零金额发票的人工核对')
        a=self.store.get_object(obj['data']['source_artifact_id'],scope)
        if not self.source_ok(scope,obj,a):raise PreconditionFailed('原件或解析版本已失效，请刷新核对')
        if self.automatic_checks(scope, [a], [obj]):
            raise PreconditionFailed('原件红冲依据与金额检查已通过，无需重复人工说明；请刷新查看')
        if value.input_token!=self.input_token(scope,obj,a):raise VersionConflict('核对依据或处理记录已变化，请刷新')
        # Re-read the retained file; acknowledgement must not disguise extraction errors.
        from app.tabular import extract_workbook, ParseOptions, ExtractionError
        try:
            result=extract_workbook((self.store.database.settings.storage_path/a['data']['storage_path']).read_bytes(),ParseOptions(**a['data']['parse_options']),scope.accounting_period_id)
            source=next((r for r in result['records'] if r['source_anchor']==obj['data']['source_anchor'] and r['record_type']==obj['data']['record_type']),None)
            if not source or source['normalized_value']!=obj['data']['normalized_value'] or source['field_sources']!=obj['data']['field_sources'] or ISSUE not in source['extraction_issues']:
                raise PreconditionFailed('提取结果与原件重新校验不一致，请先重新提取')
            n=source['normalized_value'];total,net,tax=(Decimal(n[k]) for k in ('invoice_total','net_amount','tax'))
            if not all(v.is_finite() for v in (total,net,tax)) or total>0 or total!=net+tax:
                raise PreconditionFailed('金额存在其他不一致，不能通过此项核对放行')
        except (ExtractionError,ValidationError,InvalidOperation,TypeError,KeyError) as exc:
            raise PreconditionFailed('原件金额不能重新验证，请先处理解析问题') from exc
        key='invoice-amount-'+digest({'scope':scope.model_dump(),'fact_id':target})
        prior=next((c for c in self.store.list_objects(TYPE,scope) if c['object_id']==key),None)
        binding=self.service.materials.binding(obj,a)
        if prior and prior['status']=='CONFIRMED' and prior['data']['binding']==binding:
            raise PreconditionFailed('本条已核对，请勿重复确认')
        data={'binding':binding,'issue':ISSUE,'invoice_no':obj['data']['normalized_value'].get('invoice_no'),
              'invoice_total':str(total),'reason':value.reason,'confirmed_by':actor,'confirmed_at':utcnow(),
              'effect':'仅解除红字或零金额人工核对提醒；其他资料问题与财务门禁保留'}
        saved=self.store.revise_object(key,prior['version'],scope,data,status='CONFIRMED',created_by=actor) if prior else self.store.create_initial_object(TYPE,scope,data,status='CONFIRMED',created_by=actor,object_id=key)
        self.store.add_audit('INVOICE_AMOUNT_CONFIRMED',actor,scope,object_id=key,object_version=saved['version'],before=prior,after=saved,reason=value.reason)
        return {'object':saved}
