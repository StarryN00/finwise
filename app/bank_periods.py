"""Explicit bank-date attribution and reference-only receiving-period intake."""
from copy import deepcopy
from datetime import date
import json
import re

from app.db import utcnow
from app.materials import compare_fields
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed, VersionConflict
from app.ontology.store import digest

ASSIGNMENT = 'BankPeriodAssignment'
INTAKE = 'BankPeriodIntake'
PERIOD_ISSUE = '业务期间：不属于已核定的本期业务范围，需核对原件与业务日期'
BOOK_KEYS = ('tenant_id', 'organization_id', 'legal_entity_id', 'ledger_id')


class BankPeriods:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def book_objects(self, scope, kind):
        # This explicit transfer boundary is narrower than arbitrary cross-scope reads.
        where = ' AND '.join("json_extract(o.scope_json, '$."+k+"')=?" for k in BOOK_KEYS)
        with self.store.database.connect() as c:
            rows = c.execute("SELECT o.* FROM ontology_objects o WHERE o.object_type=? AND "+where+
                " AND o.version=(SELECT MAX(v.version) FROM ontology_objects v WHERE v.object_id=o.object_id)",
                [kind]+[getattr(scope,k) for k in BOOK_KEYS]).fetchall()
        return [self.store._object_from_row(r) for r in rows]

    def target_month(self, scope, fact, artifact):
        d = fact['data']; v = d.get('normalized_value', {})
        if (artifact['status'] != 'ACTIVE' or not self.service.materials.source_valid(artifact)
            or artifact['data'].get('parse_options', {}).get('document_kind') != 'bank_statement'
            or fact['status'] not in {'PARSED','NEEDS_REVIEW','PERIOD_EXCEPTION'}
            or d.get('record_type') not in {'PAYMENT','BANK_TRANSACTION','RECEIPT'}):
            return None
        field = next((r for r in compare_fields(d) if r['field']=='transaction_date'), None)
        if not field or field['state'] not in {'DIRECT_MATCH','NORMALIZED_MATCH'} or not field['region']:
            return None
        raw = str(v.get('transaction_date') or '')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):return None
        try: date.fromisoformat(raw)
        except ValueError:return None
        month = raw[:7]
        if v.get('period') != month or month == scope.accounting_period_id:return None
        # For tabular sources, replay the date cell from the retained bytes rather
        # than treating a stored normalized value as its own proof.
        match=re.fullmatch(r'(.*)!([A-Z]+)(\d+)',field['region'])
        if match:
            anchor=(d.get('source_anchor') or {}).get('region','')
            record_row=re.fullmatch(r'(.*)!([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?',anchor)
            if (not record_row or record_row[1]!=match[1] or record_row[3]!=match[3]
                or (record_row[5] and record_row[5]!=match[3])):return None
            from app.tabular import read_workbook, date_value
            try:
                root=self.store.database.settings.storage_path.resolve()
                path=(root/artifact['data']['storage_path']).resolve()
                if not path.is_relative_to(root):return None
                sheet=next(s for s in read_workbook(path.read_bytes()) if s['name']==match[1])
                row=next(r for r in sheet['rows'] if r['row']==int(match[3]))
                index=0
                for char in match[2]:index=index*26+ord(char)-64
                if row.get('formulas') or date_value(row['values'][index-1])!=v.get('transaction_date'):return None
            except (ValueError,KeyError,StopIteration,IndexError,OSError):return None
        else:
            return None
        return month

    def binding(self, fact, artifact):
        return {'fact_id':fact['object_id'],'fact_version':fact['version'],
                'artifact_id':artifact['object_id'],'artifact_version':artifact['version'],
                'sha256':artifact['data'].get('sha256'), 'source_anchor':fact['data'].get('source_anchor')}

    def valid(self, assignment):
        if assignment['status']!='CONFIRMED':return False
        try:
            scope=Scope(**assignment['scope']); b=assignment['data']['binding']
            f=self.store.get_object(b['fact_id'],scope); a=self.store.get_object(b['artifact_id'],scope)
            return b==self.binding(f,a) and assignment['data']['target_period']==self.target_month(scope,f,a)
        except (KeyError,ValueError):return False

    def assignments(self, scope):
        return [{**x,'valid':self.valid(x)} for x in self.store.list_objects(ASSIGNMENT,scope)]

    def input_token(self, scope, task, facts, artifact):
        return digest([scope.model_dump(),task['id'],[self.binding(f,artifact) for f in facts]])

    def decorate(self, scope, task, records, artifact, facts):
        months=[self.target_month(scope,f,artifact) for f in facts]
        if not months or not all(months) or len(set(months))!=1 or not task['reason'].startswith('业务期间：'):
            return
        task['bank_period']={'target_period':months[0], 'record_ids':[r['object_id'] for r in records],
                            'input_token':self.input_token(scope,task,facts,artifact)}
        task['input_token']=task['bank_period']['input_token']

    def guard_dependencies(self, obj):
        scope=Scope(**obj['scope'])
        refs={obj['object_id']}
        if obj['object_type']==ASSIGNMENT:
            for intake in self.book_objects(scope,INTAKE):
                if intake['status']=='ACCEPTED' and intake['data']['assignment_id']==obj['object_id']:
                    raise PreconditionFailed('目标期间已接续，请先在目标期间撤销接续')
            refs.add(obj['data']['binding']['fact_id'])
        for kind in ('ProcessingGroup','BusinessEvent','VoucherVersion','DeliveryPackage'):
            for item in self.book_objects(scope,kind):
                if item['status'] in {'VOID','SUPERSEDED','REVOKED','CANCELLED'}:continue
                def contains(value):
                    if isinstance(value,str):return value in refs
                    if isinstance(value,list):return any(contains(v) for v in value)
                    if isinstance(value,dict):return any(contains(v) for v in value.values())
                    return False
                if contains(item['data']):raise PreconditionFailed('已有下游依赖 '+item['object_id']+'，不能直接撤销')
        for relation in self.store.list_relations(scope,obj['object_id']):
            if relation.get('status') not in {'VOID','REVOKED','SUPERSEDED'}:
                raise PreconditionFailed('已有业务关联，须先处理依赖再撤销')

    def duplicate_status(self, scope, assignment):
        source=Scope(**assignment['scope']); b=assignment['data']['binding']
        f=self.store.get_object(b['fact_id'],source); v=f['data']['normalized_value']
        for other in self.store.list_objects('FactRecord',scope):
            if other['status'] in {'VOID','SUPERSEDED'}:continue
            d=other['data']; w=d.get('normalized_value',{})
            if d.get('record_type') not in {'PAYMENT','BANK_TRANSACTION','RECEIPT'}:continue
            a=self.store.get_object(d['source_artifact_id'],scope)
            if a['status']!='ACTIVE' or not self.service.materials.source_valid(a):continue
            same_source=a['data'].get('sha256')==b['sha256'] and d.get('source_anchor')==b['source_anchor']
            txn=v.get('bank_transaction_id') or v.get('transaction_id')
            same_txn=bool(txn and txn==(w.get('bank_transaction_id') or w.get('transaction_id'))
                          and v.get('bank_account_ref') and v.get('bank_account_ref')==w.get('bank_account_ref'))
            if same_source or same_txn:return 'DUPLICATE'
            if (v.get('transaction_date')==w.get('transaction_date')
                and all(v.get(k)==w.get(k) for k in ('income','expense'))
                and any(v.get(k) is not None for k in ('income','expense'))):return 'AMBIGUOUS'
        for other in self.book_objects(scope,INTAKE):
            if other['status']=='ACCEPTED' and other['data']['assignment_id']==assignment['object_id']:
                return 'ACCEPTED' if other['scope']==scope.model_dump() else 'ACCEPTED_ELSEWHERE'
            if other['status']!='ACCEPTED' or other['scope']['accounting_period_id']!=scope.accounting_period_id:
                continue
            origin=Scope(**other['data']['source_scope'])
            prior=self.store.get_object(other['data']['assignment_id'],origin)
            if prior['version']!=other['data']['assignment_version'] or not self.valid(prior):continue
            pb=prior['data']['binding']
            pf=self.store.get_object(pb['fact_id'],origin,version=pb['fact_version'])
            pv=pf['data']['normalized_value']
            same_source=pb['sha256']==b['sha256'] and pb['source_anchor']==b['source_anchor']
            txn=v.get('bank_transaction_id') or v.get('transaction_id')
            same_txn=bool(txn and txn==(pv.get('bank_transaction_id') or pv.get('transaction_id'))
                          and v.get('bank_account_ref') and v.get('bank_account_ref')==pv.get('bank_account_ref'))
            if same_source or same_txn:return 'DUPLICATE'
            if (v.get('transaction_date')==pv.get('transaction_date')
                and all(v.get(k)==pv.get(k) for k in ('income','expense'))
                and any(v.get(k) is not None for k in ('income','expense'))):return 'AMBIGUOUS'
        return 'READY'

    def incoming(self, scope):
        incoming=[]
        for x in self.book_objects(scope,ASSIGNMENT):
            if x['data']['target_period']!=scope.accounting_period_id:continue
            valid=self.valid(x); b=x['data']['binding']; source=Scope(**x['scope'])
            intake=next((i for i in self.store.list_objects(INTAKE,scope)
                         if i['data']['assignment_id']==x['object_id'] and i['status']=='ACCEPTED'),None)
            status=self.duplicate_status(scope,x) if valid else 'STALE'
            if intake and intake['data']['assignment_version']!=x['version']:status='STALE'
            f=self.store.get_object(b['fact_id'],source,version=b['fact_version'])
            a=self.store.get_object(b['artifact_id'],source,version=b['artifact_version'])
            incoming.append({'assignment_id':x['object_id'],'assignment_version':x['version'],
                'source_scope':x['scope'],'source_period':source.accounting_period_id,
                'target_period':scope.accounting_period_id,'valid':valid,'status':status,'intake':intake,
                'binding':b,'filename':a['data']['filename'], 'values':deepcopy(f['data']['normalized_value']),
                'comparison':compare_fields(f['data']), 'original_issues':f['data'].get('extraction_issues',[]),
                'input_token':digest([scope.model_dump(),x['object_id'],x['version'],b,status])})
        return incoming

    def view(self, scope):
        outgoing=self.assignments(scope); incoming=self.incoming(scope)
        for x in outgoing:
            target_exists=any(all(o['data']['scope'].get(k)==getattr(scope,k) for k in BOOK_KEYS)
                and o['data']['scope']['accounting_period_id']==x['data']['target_period']
                for o in self.store.list_scope_objects())
            x['handoff_status']='WAITING_INTAKE' if target_exists else 'WAITING_PERIOD'
            if any(i['status']=='ACCEPTED' and i['data']['assignment_id']==x['object_id']
                   and i['data']['assignment_version']==x['version'] for i in self.book_objects(scope,INTAKE)):
                x['handoff_status']='ACCEPTED' if x['valid'] else 'STALE'
        return {'outgoing':outgoing,'incoming':incoming,
                'counts':{'confirmed_other_period':sum(x['valid'] for x in outgoing),
                          'awaiting_intake':sum(x['status']=='READY' for x in incoming),
                          'accepted':sum(x['status']=='ACCEPTED' for x in incoming)},
                'boundary':'期间归属与接续不是原件核实、账务可用或完整分录。'}

    def execute(self, scope, action, obj, actor, payload):
        self.service._ensure_period_open(scope)
        if action in {'revoke_bank_period','revoke_bank_period_intake'}:
            if set(payload)-{'reason'} or not isinstance(payload.get('reason',''),str):
                raise PreconditionFailed('撤销只接受原因')
            expected='CONFIRMED' if action=='revoke_bank_period' else 'ACCEPTED'
            if obj['status']!=expected:raise PreconditionFailed('记录已撤销')
            self.guard_dependencies(obj)
            revised=self.store.revise_object(obj['object_id'],obj['version'],scope,
                {**obj['data'],'revoked_by':actor,'revoked_at':utcnow(),'reason':payload.get('reason','')[:2000]},
                status='REVOKED',created_by=actor)
            self.store.add_audit(action,actor,scope,object_id=obj['object_id'],after=revised)
            return {'object':revised,'message':'已撤销，重新按有效来源评估；未修改原始流水。'}
        if action=='accept_bank_period':
            if set(payload)!={'assignment_id','assignment_version','input_token'}:raise PreconditionFailed('接续请求字段无效')
            item=next((x for x in self.incoming(scope) if x['assignment_id']==payload['assignment_id']),None)
            if not item or item['assignment_version']!=payload['assignment_version'] or item['input_token']!=payload['input_token']:
                raise VersionConflict('接续依据变化，请刷新')
            if item['status']!='READY':raise PreconditionFailed('记录失效、已接续或存在重复疑点，不能重复接续')
            saved=self.store.create_initial_object(INTAKE,scope,
                {'assignment_id':item['assignment_id'],'assignment_version':item['assignment_version'],
                 'source_scope':item['source_scope'],'binding':item['binding'],'accepted_by':actor,'accepted_at':utcnow()},
                status='ACCEPTED',created_by=actor)
            self.store.add_audit(action,actor,scope,object_id=saved['object_id'],after=saved)
            return {'object':saved,'message':'已按来源引用接续；未复制流水事实，不代表账务可用。'}
        if set(payload)-{'task_id','input_token','record_ids','target_period','reason'}:
            raise PreconditionFailed('不允许修改流水值或责任人')
        ids=payload.get('record_ids'); reason=payload.get('reason','')
        if not isinstance(ids,list) or not 1<=len(ids)<=5 or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)) or not isinstance(reason,str) or len(reason)>2000:
            raise PreconditionFailed('仅选择当前页一至五条记录，原因最多2000字')
        wb=self.service.workbench(scope)
        task=next((t for t in wb['material_review']['tasks'] if t['id']==payload.get('task_id') and t['artifact_id']==obj['object_id']),None)
        info=(task or {}).get('bank_period')
        if not info or info['input_token']!=payload.get('input_token'):raise VersionConflict('事项或流水依据已变化')
        if payload.get('target_period')!=info['target_period'] or not set(ids)<=set(info['record_ids']):
            raise PreconditionFailed('目标期间必须与原交易日期一致，记录必须属于当前事项')
        if len({info['record_ids'].index(i)//5 for i in ids})!=1:
            raise PreconditionFailed('只允许选择同一展示页的流水')
        objects=[]
        for fid in ids:
            fact=self.store.get_object(fid,scope)
            if any(x['valid'] and x['data']['binding']['fact_id']==fid for x in self.assignments(scope)):
                raise PreconditionFailed('此条已确认归属')
            if self.target_month(scope,fact,obj)!=info['target_period']:raise VersionConflict('日期或来源已变化')
            data={'binding':self.binding(fact,obj),'target_period':info['target_period'],
                  'task_id':task['id'],'confirmed_by':actor,'confirmed_at':utcnow(),'reason':reason.strip()}
            saved=self.store.create_initial_object(ASSIGNMENT,scope,data,status='CONFIRMED',created_by=actor)
            self.store.add_audit(action,actor,scope,object_id=saved['object_id'],after=saved)
            objects.append(saved)
        return {'objects':objects,'message':'已确认其他期间归属，不计入本期流水发生额；等待目标期间接续，尚未入账。'}
