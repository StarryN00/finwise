"""Scope-owned durable stage 2/3 workflow and human-review admission."""
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal
import json
import logging
from pathlib import Path
import threading
import time
import uuid

from app import main_flow
from app.ontology.service import _history_stage,_scope_stage,historical_prerequisite
from app.db import utcnow
from app.ontology.contracts import Scope
from app.ontology.errors import PermissionDenied, PreconditionFailed, VersionConflict
from app.ontology.store import digest
from app.stage23_pilot import sha256
from app import autonomous_runtime
from app.autonomous_executors import BACKENDS, availability, choices, for_run, runtime_identity, RetryableExecutionError
from app.autonomous_checks import confirmation_blockers, settlement_match_errors
from app.invoice_matching import invoice_matching_errors, matching_projection
from app.reimbursements import reimbursement_errors, reimbursement_reviewed
from app.review_loop import REVIEW_POLICY_VERSION, effective_entries, review_loop_approved, review_loop_errors
from app.travel_policy import (POLICY_TYPE, POLICY_SUMMARY, POLICY_RULES, policy_scope, policy_id,
                               travel_policy_errors, travel_policy_reviewed)
from app.bookkeeping_profile import (PROFILES, PROFILE_TYPE, profile_scope, profile_id, snapshot,
                                     bookkeeping_profile_errors, bookkeeping_profile_reviewed, EnterpriseRules)

TYPE = 'AutonomousMonthlyRun'
WATCH = 'AutonomousMonthlyWatch'
ORIGIN = 'autonomous-monthly-v1'
ACTIVE = {'QUEUED','ANALYZING','REVIEWING'}
LABELS = {'WAITING_INPUT':'等待提供资料','QUEUED':'等待自动处理','ANALYZING':'正在分析和查证','REVIEWING':'正在独立审查',
          'ACCEPTED':'已完成自动处理','BLOCKED':'系统处理受阻','CANCELLED':'已暂停自动处理','STALE':'资料变化，结果已过期'}
log = logging.getLogger(__name__)


class AutonomousWorkflow:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.settings = self.store.database.settings
        self.stop_event = threading.Event()
        self.thread = None
        self.runner = autonomous_runtime.run

    def watch(self, scope):
        items = self.store.list_objects(WATCH, scope)
        return items[0] if items else None

    def owns(self, scope):
        return self.settings.autonomous_enabled and self.watch(scope) is not None

    def authorize(self, scope, actor, role):
        self.service.material_agent._authorize(scope, actor, role)

    def period_is_closed(self, scope):
        period = self.store.get_object(self.service._period_object_id(scope), scope)
        return period['status'] in {'CLOSED', 'ARCHIVED', 'LOCKED'}

    def bookkeeping_profile(self, scope):
        try:
            record = self.store.get_object(profile_id(scope), profile_scope(scope))
        except KeyError:
            record = None
        history = ([self.store.get_object(record['object_id'], profile_scope(scope), version)
                    for version in range(1, record['version'])] if record else [])
        return snapshot(record, scope.accounting_period_id, history)

    def save_bookkeeping_profile(self, scope, actor, role, *, mode, expected_version, cost_ratio=None, source_note='',
                                 enterprise_rules=None):
        self.authorize(scope, actor, role)
        self.service._ensure_period_open(scope)
        if not self.settings.autonomous_enabled or mode not in PROFILES:
            raise PreconditionFailed('记账方式不可用')
        if enterprise_rules is not None:
            enterprise_rules = EnterpriseRules.model_validate(enterprise_rules).model_dump(exclude_none=True)
            person = enterprise_rules.get('reimbursement_person')
            if person is not None:
                if not person.strip():
                    raise PreconditionFailed('默认报销结算人不能为空')
                enterprise_rules['reimbursement_person'] = person.strip()
        if cost_ratio is not None:
            try:
                ratio = Decimal(cost_ratio)
                if not ratio.is_finite() or not 0 < ratio <= 1 or ratio.as_tuple().exponent < -4:
                    raise ValueError()
                cost_ratio = format(ratio.normalize(), 'f')
            except (ValueError, ArithmeticError):
                raise PreconditionFailed('成本比例须大于0且不超过100%，最多两位百分数小数')
        with self.store.database.transaction():
            target = profile_scope(scope)
            try:
                old = self.store.get_object(profile_id(scope), target)
            except KeyError:
                old = None
            if expected_version != (old['version'] if old else 0):
                raise VersionConflict()
            previous = snapshot(old)
            effective_previous = self.bookkeeping_profile(scope)
            note = source_note.strip()
            rules_changed = enterprise_rules is not None and enterprise_rules != effective_previous['enterprise_rules']
            rules = enterprise_rules if rules_changed else previous['enterprise_rules']
            confirmation = previous['enterprise_rules_confirmation']
            if rules_changed:
                if not note:
                    raise PreconditionFailed('请记录企业规则新增、变更或停用的确认来源')
                confirmation = {'source_note': note, 'confirmed_by': actor, 'confirmed_at': utcnow(),
                                'effective_from': scope.accounting_period_id}
            if cost_ratio is not None and not note:
                raise PreconditionFailed('请记录本企业成本比例的确认来源')
            job = self.current(scope)
            if old and not rules_changed and (mode, cost_ratio, note) == (previous['id'], previous['cost_ratio'], previous['source_note']):
                return self.bookkeeping_profile(scope), job, False
            if job and job['status'] in ACTIVE:
                raise PreconditionFailed('任务正在运行，请先暂停，再切换记账方式')
            data = {'mode': mode, 'cost_ratio': cost_ratio, 'source_note': note,
                    'enterprise_rules': rules, 'enterprise_rules_confirmation': confirmation,
                    'saved_by': actor, 'saved_at': utcnow()}
            if old:
                obj = self.store.revise_object(old['object_id'], expected_version, target, data, status='ACTIVE', created_by=actor)
            else:
                obj = self.store.create_initial_object(PROFILE_TYPE, target, data, status='ACTIVE', created_by=actor, object_id=profile_id(scope))
            self.store.add_audit('BOOKKEEPING_PROFILE_SELECTED', actor, scope, object_id=obj['object_id'],
                                 before=old, after=obj, reason=PROFILES[mode]['label'])
            job = self.enqueue(scope, actor, role) if self.inputs(scope)[1] else None
            return self.bookkeeping_profile(scope), job, True

    def travel_policy(self, scope):
        try:
            obj = self.store.get_object(policy_id(scope), policy_scope(scope))
        except KeyError:
            return None
        if scope.accounting_period_id < obj['data']['effective_from']:
            return None
        return {'id': obj['object_id'], 'version': obj['version'], 'enabled': obj['status'] == 'ACTIVE', **obj['data']}

    def save_travel_policy(self, scope, actor, role, *, enabled, expected_version, source_note):
        self.authorize(scope, actor, role)
        self.service._ensure_period_open(scope)
        if not self.settings.autonomous_enabled:
            raise PreconditionFailed('月度自主处理尚未启用')
        if not source_note.strip():
            raise PreconditionFailed('请记录规则的确认来源')
        with self.store.database.transaction():
            target = policy_scope(scope)
            try:
                old = self.store.get_object(policy_id(scope), target)
            except KeyError:
                old = None
            if expected_version != (old['version'] if old else 0):
                raise VersionConflict()
            status = 'ACTIVE' if enabled else 'INACTIVE'
            if old and old['status'] == status and old['data']['source_note'] == source_note.strip():
                return self.travel_policy(scope), None
            data = {'summary': POLICY_SUMMARY, 'rules': POLICY_RULES,
                    'source_note': source_note.strip(), 'confirmed_by': actor, 'confirmed_at': utcnow(),
                    'effective_from': old['data']['effective_from'] if old else scope.accounting_period_id}
            if old:
                obj = self.store.revise_object(old['object_id'], expected_version, target, data, status=status, created_by=actor)
            else:
                obj = self.store.create_initial_object(POLICY_TYPE, target, data, status=status, created_by=actor, object_id=policy_id(scope))
            self.store.add_audit('TRAVEL_POLICY_CONFIRMED' if enabled else 'TRAVEL_POLICY_DISABLED', actor, scope,
                                 object_id=obj['object_id'], before=old, after=obj, reason=source_note.strip())
            # Only the requested open period is started here; other periods detect stale inputs normally.
            job = self.enqueue(scope, actor, role) if self.inputs(scope)[1] else None
            return self.travel_policy(scope), job

    def inputs(self, scope):
        sources = [o for o in self.store.list_objects('SourceArtifact',scope) if o['status'] in {'ACTIVE','PERIOD_EXCEPTION'}]
        answers = self.store.list_objects('AutonomousAnswer',scope)
        baseline = self.store.get_object(self.service._baseline_object_id(scope),scope)
        refs = sorted([(o['object_id'],o['version'],o['status'],o['data'].get('sha256')) for o in sources])
        basis = [ORIGIN, REVIEW_POLICY_VERSION, refs, sorted((a['object_id'],a['version']) for a in answers),baseline['version']]
        policy = self.travel_policy(scope)
        if policy:
            basis.append([policy['id'], policy['version'], policy['enabled']])
        basis.append(self.bookkeeping_profile(scope))
        fp = digest(basis)
        return fp, sorted(sources,key=lambda o:o['object_id']), answers

    def current(self, scope):
        watch = self.watch(scope)
        return self.store.get_object(watch['data']['run_id'],scope) if watch and watch['data'].get('run_id') else None

    def selected_backend(self, scope):
        watch = self.watch(scope)
        data = (watch or {}).get('data', {})
        return data.get('backend', 'codex' if data.get('run_id') else self.settings.autonomous_backend)

    def select_backend(self, scope, actor, role, backend):
        if not self.settings.autonomous_enabled:
            raise PreconditionFailed('月度自主处理尚未启用')
        self.authorize(scope, actor, role)
        if backend not in BACKENDS:
            raise PreconditionFailed('不支持的自主执行器')
        available, message = availability(self.settings, backend)
        if not available:
            raise PreconditionFailed(message)
        with self.store.database.transaction():
            job = self.current(scope)
            if job and job['status'] in ACTIVE:
                raise PreconditionFailed('任务正在运行，请先暂停，再切换执行器')
            watch = self.watch(scope)
            if watch and self.selected_backend(scope) == backend:
                return job
            data = {**(watch or {}).get('data', {}), 'backend': backend, 'requested_by': actor, 'role': role}
            if watch:
                self.store.revise_object(watch['object_id'], watch['version'], scope, data, status='ACTIVE', created_by=actor)
            else:
                self.store.create_initial_object(WATCH, scope, {**data, 'revision': 0}, status='ACTIVE', created_by=actor,
                    object_id='autonomous-watch-'+digest(scope.model_dump()))
            self.store.add_audit('AUTONOMOUS_EXECUTOR_SELECTED', actor, scope, reason=BACKENDS[backend])
            return self.enqueue(scope, actor, role) if self.inputs(scope)[1] else None

    def source_key(self, scope):
        _, sources, _ = self.inputs(scope)
        baseline = self.store.get_object(self.service._baseline_object_id(scope), scope)
        return digest([[(s['object_id'],s['version'],s['status'],s['data'].get('sha256')) for s in sources],baseline['version']])

    def review_context(self, scope):
        _, _, answers = self.inputs(scope)
        statements = [{'answer_id':a['object_id'],**a['data']} for a in answers]
        for answer in statements:
            if answer.get('kind') == 'FREE_TEXT' and 'affected_vouchers' not in answer:
                prior = self.store.get_object(answer['run_id'], scope)
                finding = next((f for f in prior['data']['result']['delivery']['findings'] if f['id'] == answer['finding_id']), {})
                answer['affected_vouchers'] = finding.get('affected_vouchers', [])
        complete = any(a.get('kind')=='MATERIALS_COMPLETE' and a.get('source_key')==self.source_key(scope) for a in statements)
        policy = self.travel_policy(scope)
        return {'statements':statements,'materials_complete':complete,'review_loop_version':REVIEW_POLICY_VERSION,
                'travel_policy': policy if policy and policy['enabled'] else None,
                'bookkeeping_profile': self.bookkeeping_profile(scope),
                'goal':'按代理记账日常处理口径自主核对原件和历史，先形成有依据的待复核凭证；仅将实际影响处理且系统无法查清的具体缺口交人工，不把常规月结或理论疑点变成人工确认'}

    def _accepted_input(self, scope, run_id):
        job=self.current(scope)
        if not job or job['object_id']!=run_id or job['status']!='ACCEPTED' or job['data']['fingerprint']!=self.inputs(scope)[0]:
            raise PreconditionFailed('事项版本已变化，请刷新后提交')
        return job

    def enqueue(self, scope, actor, role='operator', *, retry=False, recheck=False):
        if not self.settings.autonomous_enabled:
            raise PreconditionFailed('月度自主处理尚未启用')
        self.authorize(scope,actor,role)
        with self.store.database.transaction():
            fp,sources,answers=self.inputs(scope)
            if not sources:
                raise PreconditionFailed('请先上传原始资料')
            old=self.current(scope)
            watch=self.watch(scope)
            runtime=runtime_identity(self.settings, self.selected_backend(scope))
            backend_changed=bool(old and old['data'].get('runtime', {}).get('backend', 'codex') != runtime['backend'])
            if recheck and not retry:
                raise PreconditionFailed('重新查证须明确请求新一轮处理')
            if old and old['data']['fingerprint']==fp and not retry and not backend_changed:
                return old
            if old and old['status'] in ACTIVE and old['data']['fingerprint']==fp:
                return old
            if old and old['status'] in ACTIVE:
                self._revise(scope,old,'STALE',{'message':'资料已变化，新任务接续处理'})
            partial=bool(old and old['status']=='ACCEPTED' and any(a['status']=='SYSTEM_BLOCKED' for a in old['data']['result']['delivery']['voucher_assessments']))
            policy_update=bool(old and old['status']=='ACCEPTED' and old['data']['result'].get('review_policy_version',1)<REVIEW_POLICY_VERSION)
            history_recheck=bool(recheck and retry and old and old['status']=='ACCEPTED' and
                                 any(f.get('needs_user') for f in old['data']['result']['delivery'].get('findings',[])))
            if recheck and not history_recheck:
                raise PreconditionFailed('只能对当前已完成且仍有待决事项的任务重新查证')
            if retry and old and old['status'] not in {'BLOCKED','CANCELLED','STALE'} and not partial and not policy_update and not history_recheck and not backend_changed:
                raise PreconditionFailed('只可重试受阻、暂停或过期的任务')
            revision=(watch or {}).get('data',{}).get('revision',0)+1
            job=self.store.create_initial_object(TYPE,scope,{'fingerprint':fp,'requested_by':actor,'role':role,'runtime':runtime,
                'revision':revision,'source_ids':[s['object_id'] for s in sources], 'queued_at':time.time(),
                'travel_policy':self.travel_policy(scope),
                'bookkeeping_profile':self.bookkeeping_profile(scope),
                'recheck_reason':'EXISTING_EVIDENCE' if history_recheck else None,
                'message':'已接收资料，等待自主处理','phase':'QUEUED','round':0,'attempt':0,
                'events':[{'at':utcnow(),'phase':'QUEUED','message':'资料已入队'}],
                'parent_id':old['object_id'] if old else None},status='QUEUED',created_by=actor)
            data={'run_id':job['object_id'],'revision':revision,'requested_by':actor,'role':role,'backend':runtime['backend']}
            if watch:
                self.store.revise_object(watch['object_id'],watch['version'],scope,data,status='ACTIVE',created_by=actor)
            else:
                self.store.create_initial_object(WATCH,scope,data,status='ACTIVE',created_by=actor,
                    object_id='autonomous-watch-'+digest(scope.model_dump()))
            self.store.add_audit('AUTONOMOUS_QUEUED',actor,scope,object_id=job['object_id'],reason='授权自主分析查证；候选仍需人工复核')
            return job

    def signal(self, scope, actor):
        if self.settings.autonomous_enabled:
            self.enqueue(scope,actor)

    def cancel(self, scope, actor, role):
        self.authorize(scope,actor,role)
        with self.store.database.transaction():
            job=self.current(scope)
            if not job or job['status'] not in ACTIVE:
                raise PreconditionFailed('当前没有可暂停的自动任务')
            result=self._revise(scope,job,'CANCELLED',{'message':'已暂停；原件及处理过程保留'})
            watch=self.watch(scope)
            self.store.revise_object(watch['object_id'],watch['version'],scope,watch['data'],status='PAUSED',created_by=actor)
            self.store.add_audit('AUTONOMOUS_CANCELLED',actor,scope,object_id=job['object_id'],reason='暂停后拒收迟到结果')
            return result

    def answer(self, scope, actor, role, run_id, finding_id, text):
        self.authorize(scope,actor,role)
        with self.store.database.transaction():
            job=self._accepted_input(scope,run_id)
            result=job['data']['result']
            finding = next((f for f in result['delivery']['findings'] if f['id']==finding_id and f['needs_user']), None)
            if not finding:
                raise PreconditionFailed('不是当前待补充的业务事项')
            self.store.create_initial_object('AutonomousAnswer',scope,{'run_id':run_id,'finding_id':finding_id,
                'affected_vouchers':finding.get('affected_vouchers', []),
                'question':finding.get('request', {}).get('question', finding.get('title', '')),
                'evidence':finding.get('evidence', []),
                'text':text,'author':actor,'at':utcnow(),'kind':'FREE_TEXT','evidence_kind':'USER_STATEMENT'},status='RECORDED',created_by=actor)
            return self.enqueue(scope,actor,role)

    def materials_complete(self, scope, actor, role, run_id, note=''):
        self.authorize(scope,actor,role)
        with self.store.database.transaction():
            self._accepted_input(scope,run_id)
            if self.review_context(scope)['materials_complete']:
                raise PreconditionFailed('已记录资料范围，请选择处理方案或补充新的业务说明')
            self.store.create_initial_object('AutonomousAnswer',scope,{
                'run_id':run_id,'kind':'MATERIALS_COMPLETE','text':note or '现有资料已全部提供，请分析不增加附件时可完成的部分及可行方案。',
                'source_key':self.source_key(scope),'author':actor,'at':utcnow(),'evidence_kind':'USER_STATEMENT'},
                status='RECORDED',created_by=actor)
            return self.enqueue(scope,actor,role)

    def match_invoices(self, scope, actor, role, run_id, items, acknowledged):
        self.authorize(scope, actor, role)
        with self.store.database.transaction():
            job = self._accepted_input(scope, run_id)
            result = job['data']['result']; delivery = result['delivery']
            if acknowledged is not True or not review_loop_approved(delivery, result['review']):
                raise PreconditionFailed('请确认票据归属；当前事项须通过独立审查')
            projection = matching_projection(delivery)
            tasks = {i['finding_id']: i for i in projection['items']}
            invoices = {i['id']: i for i in projection['invoices']}
            seen = set()
            for item in items:
                fid, ids, note = item['finding_id'], item['invoice_ids'], item['note'].strip()
                if fid not in tasks or fid in seen:
                    raise PreconditionFailed('不是当前票款待匹配事项，或重复提交了同一事项')
                if len(set(ids)) != len(ids) or not set(ids) <= set(invoices):
                    raise PreconditionFailed('所选票据不在本轮已核查资料中，或重复选择同一票据')
                if not ids and not note:
                    raise PreconditionFailed('请选择对应票据或填写具体说明；暂不处理的项目可保留')
                seen.add(fid)
                selected = [invoices[i] for i in ids]
                selection = {'action': 'CONFIRM_INVOICES' if ids else 'EXPLAIN',
                             'payments': tasks[fid]['payments'], 'invoices': selected,
                             'previous_state': tasks[fid]['state']}
                text = ('确认所选票据属于这笔款项，未声明这些票据已覆盖全部金额；差额、重复与记账依据仍须核查。' if ids else '')
                self.store.create_initial_object('AutonomousAnswer', scope, {
                    'run_id': run_id, 'finding_id': fid, 'kind': 'INVOICE_MATCH_SELECTION',
                    'invoice_selection': selection, 'note': note, 'text': text + ('\n' + note if note else ''),
                    'affected_vouchers': tasks[fid]['affected_vouchers'], 'acknowledged': True,
                    'author': actor, 'at': utcnow(), 'evidence_kind': 'USER_STATEMENT'},
                    status='RECORDED', created_by=actor)
            return self.enqueue(scope, actor, role)

    def choose(self, scope, actor, role, run_id, finding_id, option_id, acknowledged, note=''):
        self.authorize(scope,actor,role)
        with self.store.database.transaction():
            job=self._accepted_input(scope,run_id)
            if acknowledged is not True:
                raise PreconditionFailed('请确认已阅读方案前提与影响，所选情况适用于本笔业务')
            delivery=job['data']['result']['delivery']
            if not review_loop_approved(delivery,job['data']['result']['review']):
                raise PreconditionFailed('处理方案尚未通过独立审查')
            finding=next((f for f in delivery['findings'] if f['id']==finding_id and f['needs_user']),None)
            option=next((o for o in (finding or {}).get('decision',{}).get('options',[]) if o['id']==option_id),None)
            if not option: raise PreconditionFailed('不是当前已审查的处理选项')
            self.store.create_initial_object('AutonomousAnswer',scope,{
                'run_id':run_id,'finding_id':finding_id,'kind':'REVIEW_SELECTION','question':finding['decision']['question'],
                'option':option,'affected_vouchers':finding.get('affected_vouchers',[]),'text':note,
                'acknowledged':True,'author':actor,'at':utcnow(),
                'evidence_kind':'USER_DECISION' if option['kind']=='ACCOUNTING_CHOICE' else 'USER_STATEMENT'},
                status='RECORDED',created_by=actor)
            return self.enqueue(scope,actor,role)

    def _revise(self, scope, job, status, updates):
        return self.store.revise_object(job['object_id'],job['version'],scope,{**job['data'],**updates},status=status,created_by='autonomous-worker')

    def continuation_from(self, scope, job):
        previous = job
        if not previous['data'].get('folder') and previous['data'].get('parent_id'):
            previous = self.store.get_object(previous['data']['parent_id'], scope)
        if previous['status'] == 'ACCEPTED' or previous['data']['fingerprint'] != job['data']['fingerprint']:
            return None
        old_runtime, new_runtime = previous['data'].get('runtime') or {}, job['data'].get('runtime') or {}
        if any(old_runtime.get(key) != new_runtime.get(key) for key in ('backend', 'model', 'base_url')):
            return None
        folder = previous['data'].get('folder')
        if not folder:
            return None
        path = Path(folder).resolve()
        path.relative_to((self.settings.database_path.parent/'autonomous-runs').resolve())
        return path

    def _claim(self, scope):
        with self.store.database.transaction():
            job=self.current(scope)
            if not job:
                return None
            if job['status'] in {'ANALYZING','REVIEWING'}:
                if job['data'].get('lease_until',0)>time.time(): return None
                if job['data'].get('attempt',0)>=3:
                    self._revise(scope,job,'BLOCKED',{'message':'连续恢复次数达到上限，请查看处理过程后重试'})
                    return None
            elif job['status']!='QUEUED': return None
            if time.time()-job['data']['queued_at']<5: return None
            self.authorize(scope,job['data']['requested_by'],job['data']['role'])
            if self.inputs(scope)[0]!=job['data']['fingerprint']:
                self._revise(scope,job,'STALE',{'message':'资料已变化，原任务停止'})
                return None
            token=uuid.uuid4().hex
            return self._revise(scope,job,'ANALYZING',{'lease_token':token,'lease_until':time.time()+90,
                'attempt':job['data'].get('attempt',0)+1,'message':'正在准备冻结输入'})

    def tick(self, scope):
        # Later ledger preferences must never invalidate an already closed month.
        if self.period_is_closed(scope): return False
        watch=self.watch(scope)
        if not watch or watch['status']!='ACTIVE': return False
        current=self.current(scope)
        try:
            if current and self.inputs(scope)[0]!=current['data']['fingerprint']:
                self.enqueue(scope,watch['data']['requested_by'],watch['data']['role'])
            job=self._claim(scope)
        except (PermissionDenied, PreconditionFailed) as exc:
            with self.store.database.transaction():
                j=self.current(scope)
                if j and (j['status'] in ACTIVE or j['data']['fingerprint']!=self.inputs(scope)[0]):
                    self._revise(scope,j,'BLOCKED',{'message':str(exc)})
            return False
        if not job: return False
        token=job['data']['lease_token']
        last_beat=[0.0]
        def heartbeat(force=False):
            if self.stop_event.is_set(): raise RuntimeError('服务停止，任务将在重启后恢复')
            if not force and time.monotonic()-last_beat[0]<3: return
            with self.store.database.transaction():
                j=self.store.get_object(job['object_id'],scope)
                if j['status'] not in ACTIVE or j['data'].get('lease_token')!=token or self.watch(scope)['status']!='ACTIVE':
                    raise PreconditionFailed('任务已暂停或被新的任务取代')
                self.authorize(scope,j['data']['requested_by'],j['data']['role'])
                if self.current(scope)['object_id']!=j['object_id'] or self.inputs(scope)[0]!=j['data']['fingerprint']:
                    raise PreconditionFailed('资料已变化，迟到结果拒收')
                self._revise(scope,j,j['status'],{'lease_until':time.time()+90})
            last_beat[0]=time.monotonic()
        def progress(phase,round_no,message):
            heartbeat(True)
            with self.store.database.transaction():
                j=self.store.get_object(job['object_id'],scope)
                if j['status'] not in ACTIVE or j['data'].get('lease_token')!=token or self.watch(scope)['status']!='ACTIVE' or self.current(scope)['object_id']!=j['object_id'] or self.inputs(scope)[0]!=j['data']['fingerprint']:
                    raise PreconditionFailed('任务或资料已变化，进度更新拒收')
                events=[*j['data']['events'],{'at':utcnow(),'phase':phase,'round':round_no,'message':message}]
                self._revise(scope,j,phase,{'phase':phase,'round':round_no,'message':message,'events':events})
        folder=self.settings.database_path.parent/'autonomous-runs'/job['object_id']/token
        try:
            if not self.settings.agent_send_full_records:
                raise PreconditionFailed('部署尚未允许模型处理原件内容；任务保留为系统受阻')
            run_settings=for_run(self.settings, job['data'].get('runtime'))
            run_settings=replace(run_settings,autonomous_resume_from=self.continuation_from(scope,job))
            available, message=availability(run_settings, run_settings.autonomous_backend)
            if not available:
                raise PreconditionFailed(message)
            fp,sources,answers=self.inputs(scope)
            paths={s['object_id']:self.settings.storage_path/s['data']['storage_path'] for s in sources}
            manifest={'period':scope.accounting_period_id,'baseline_id':scope.baseline_id,'sources':[
                {'id':s['object_id'],'filename':s['data']['filename'],'sha256':s['data']['sha256'],
                 'path':'sources/'+s['object_id']+Path(s['data']['filename']).suffix.lower()} for s in sources]}
            context=self.review_context(scope)
            if job['data'].get('parent_id'):
                parent=self.store.get_object(job['data']['parent_id'],scope)
                while not parent['data'].get('result') and parent['data'].get('parent_id'):
                    parent=self.store.get_object(parent['data']['parent_id'],scope)
                context['prior_findings']=(parent['data'].get('result') or {}).get('delivery',{}).get('findings',[])
            with self.store.database.transaction():
                j=self.store.get_object(job['object_id'],scope)
                self._revise(scope,j,j['status'],{'folder':str(folder)})
            result=self.runner(folder,manifest,paths,context,run_settings,heartbeat,progress)
            result['runtime']=runtime_identity(run_settings)
            heartbeat(True)
            with self.store.database.transaction():
                j=self.store.get_object(job['object_id'],scope)
                # Repeat every gate under the same transaction as voucher creation.
                self.authorize(scope,j['data']['requested_by'],j['data']['role'])
                if j['status'] not in ACTIVE or j['data'].get('lease_token')!=token or self.watch(scope)['status']!='ACTIVE' or self.current(scope)['object_id']!=j['object_id'] or self.inputs(scope)[0]!=j['data']['fingerprint']:
                    raise PreconditionFailed('输入或任务变化，成果未入库')
                for source in self.inputs(scope)[1]:
                    if sha256(self.settings.storage_path/source['data']['storage_path'])!=source['data']['sha256']:
                        raise PreconditionFailed('原件内容变化，成果未入库')
                vouchers=self.admit(scope,j,result)
                self._revise(scope,j,'ACCEPTED',{'result':result,'vouchers':vouchers,'lease_until':0,
                    'message':'自动处理与独立审查已完成；候选等待人工复核'})
            return True
        except Exception as exc:
            with self.store.database.transaction():
                latest=self.store.get_object(job['object_id'],scope)
                if latest['status'] in ACTIVE and latest['data'].get('lease_token')==token:
                    recovering=isinstance(exc,(TimeoutError,RetryableExecutionError)) and latest['data'].get('attempt',0)<3
                    state='QUEUED' if self.stop_event.is_set() or recovering else 'BLOCKED'
                    updates={'message':'执行暂时中断，已保留进度，系统将自动接续' if recovering else str(exc),'lease_until':0}
                    if recovering:
                        updates['queued_at']=time.time()+20
                        updates['events']=[*latest['data']['events'],{'at':utcnow(),'phase':'QUEUED','message':updates['message']}]
                    self._revise(scope,latest,state,updates)
            log.warning('Autonomous run %s stopped: %s',job['object_id'],type(exc).__name__)
            return False

    def admit(self, scope, job, result):
        if not result.get('mechanical',{}).get('passed') or result.get('review',{}).get('verdict')!='pass' or result['review'].get('defects') or not result['review'].get('coverage'):
            raise PreconditionFailed('校验或独立证据审查未通过')
        delivery=result['delivery']
        if delivery['period']!=scope.accounting_period_id: raise PreconditionFailed('成果期间不一致')
        context=self.review_context(scope)
        context['review_loop_version']=result.get('review_policy_version',1)
        if context['review_loop_version'] < REVIEW_POLICY_VERSION:
            raise PreconditionFailed('处理口径已升级，成果须按当前契约重新分析审查')
        if (job['data'].get('bookkeeping_profile') != context['bookkeeping_profile']
                or bookkeeping_profile_errors(delivery, context)
                or not bookkeeping_profile_reviewed(delivery, result['review'], context)):
            raise PreconditionFailed('记账方式或规则版本与本轮不一致，须重新分析审查')
        if context.get('travel_policy') and context['review_loop_version'] < 5:
            raise PreconditionFailed('启用差旅政策的成果必须使用新版审查契约')
        source_ids = {s['object_id'] for s in self.inputs(scope)[1]}
        if reimbursement_errors(delivery, context, lambda r: r.get('source_id') in source_ids) or not reimbursement_reviewed(delivery, result['review'], context):
            raise PreconditionFailed('个人报销往来、人员分配或独立审查不完整')
        if travel_policy_errors(delivery, context) or not travel_policy_reviewed(delivery, result['review'], context):
            raise PreconditionFailed('差旅规则引用、人工确认或独立审查不完整')
        if (review_loop_errors(delivery,context) or settlement_match_errors(delivery)[0]
                or invoice_matching_errors(delivery, context) or not review_loop_approved(delivery,result['review'])):
            raise PreconditionFailed('处理方案、修订或用户回应尚未通过完整审查')
        groups=effective_entries(delivery)
        for rows in groups.values():
            if not rows or len({entry.get('date') for entry in rows}) != 1:
                raise PreconditionFailed('同一凭证的分录日期必须一致')
        ready={a['voucher'] for a in delivery['voucher_assessments'] if a['status']=='READY_FOR_REVIEW'}
        if ready!=set(result['review'].get('ready_vouchers',[])): raise PreconditionFailed('独立审查范围不一致')
        nonblocking={f['id'] for f in delivery.get('findings',[]) if f.get('needs_user') and f.get('blocks_confirmation') is False}
        if nonblocking!=set(result['review'].get('nonblocking_findings',[])):
            raise PreconditionFailed('非阻断事项未经独立审查逐项确认')
        if any(confirmation_blockers(delivery, number) for number in ready):
            raise PreconditionFailed('候选仍有影响确认的业务缺口')
        refs={s['object_id'] for s in self.inputs(scope)[1]}
        prior_confirmed={v['data'].get('review_basis'):v for v in self.store.list_objects('VoucherVersion',scope)
                         if v['status']=='LOCALLY_CONFIRMED' and v['data'].get('review_basis')}
        vouchers=[]
        for a in delivery['voucher_assessments']:
            if a['voucher'] not in ready: continue
            reference=job['object_id']+':'+a['voucher']
            lines=[]
            for i,e in enumerate(groups[a['voucher']],1):
                if e['source']['source_id'] not in refs: raise PreconditionFailed('凭证来源不属于当前范围')
                debit=Decimal(e['debit'])
                lines.append({'line_no':i,'direction':'DEBIT' if debit else 'CREDIT','amount':e['debit'] if debit else e['credit'],
                    'account':e['name'],'account_code':e['code'],'memo':e.get('memo',''),'source_group_id':reference,
                    'source':{**e['source'],'artifact_id':e['source']['source_id']}})
            debit,credit=self.service._voucher_totals(lines,reference)
            if debit!=credit: raise PreconditionFailed('候选借贷不平')
            data={'origin':ORIGIN,'run_id':job['object_id'],'group_id':reference,'voucher_number':a['voucher'],
                  'date':groups[a['voucher']][0]['date'],'lines':lines,'assessment':a,'fingerprint':job['data']['fingerprint'],
                  'debit_total':str(debit),'credit_total':str(credit),'formal_balance_impact':False}
            applications=[p for p in delivery.get('travel_policy_applications', []) if p['voucher']==a['voucher']]
            data['travel_policy_applications']=applications
            data['bookkeeping_profile']=context['bookkeeping_profile']
            reimbursements=[r for r in delivery.get('employee_reimbursements',[]) if any(item['voucher']==a['voucher'] for field in ('invoices','payments') for item in r[field])]
            data['employee_reimbursements']=reimbursements
            related=[f for f in delivery['findings'] if a['voucher'] in f.get('affected_vouchers',[]) or f['id'] in a.get('finding_ids',[])]
            matches=[m for m in delivery.get('settlement_matches',[]) if a['voucher'] in m['affected_vouchers']]
            basis=[REVIEW_POLICY_VERSION,groups[a['voucher']],a,related,self.source_key(scope)]
            basis.append(context['bookkeeping_profile'])
            basis.append(reimbursements)
            if matches: basis.append(matches)
            policy=self.travel_policy(scope)
            if policy: basis.append([policy['id'],policy['version'],policy['enabled'],applications])
            data['review_basis']=digest(basis)
            prior=prior_confirmed.get(data['review_basis'])
            status='LOCALLY_CONFIRMED' if prior else 'DRAFT'
            if prior:
                data.update(carried_from=prior['object_id'],validated_by=prior['data']['validated_by'],validated_at=prior['data']['validated_at'])
            draft=self.store.create_initial_object('VoucherDraft',scope,data,status='DRAFT',created_by='autonomous-worker')
            v=self.store.create_initial_object('VoucherVersion',scope,{**data,'draft_id':draft['object_id']},status=status,created_by='autonomous-worker')
            vouchers.append(v['object_id'])
            self.store.add_audit('AUTONOMOUS_CANDIDATE', 'autonomous-worker',scope,object_id=v['object_id'],after=v,reason='有依据候选进入人工复核；无正式余额影响')
            if prior:
                self.store.add_audit('AUTONOMOUS_REVIEW_CARRIED','autonomous-worker',scope,object_id=v['object_id'],reason='独立重查通过且原件、分录和评估完全相同，沿用此前人工复核')
        return vouchers

    def validate_voucher(self, scope, voucher, actor, expected_version):
        if not self.owns(scope): raise PreconditionFailed('自主处理未启用，不能沿用旧结果')
        if voucher['version']!=expected_version: raise VersionConflict()
        if voucher['status']!='DRAFT': raise PreconditionFailed('该候选已复核或修改，不能重复使用原审查许可')
        job=self.current(scope)
        if not job or job['object_id']!=voucher['data']['run_id'] or job['status']!='ACCEPTED' or job['data']['fingerprint']!=self.inputs(scope)[0]:
            raise PreconditionFailed('原件或任务已变化，候选需要重新处理')
        if voucher['object_id'] not in job['data']['vouchers']: raise PreconditionFailed('候选不属于已审查成果')
        delivery=job['data']['result']['delivery']
        number=voucher['data']['voucher_number']
        ready={a['voucher'] for a in delivery['voucher_assessments'] if a['status']=='READY_FOR_REVIEW'}
        if number not in ready or number not in job['data']['result']['review'].get('ready_vouchers',[]) or confirmation_blockers(delivery,number):
            raise PreconditionFailed('该分录仍需补充关键依据，不能确认通过')
        for s in self.inputs(scope)[1]:
            if sha256(self.settings.storage_path/s['data']['storage_path'])!=s['data']['sha256']:
                raise PreconditionFailed('原件内容变化，复核被阻止')
        initial=self.store.get_object(voucher['object_id'],scope,1)
        if initial['data']['lines']!=voucher['data']['lines']: raise PreconditionFailed('分录修改后须重新审查')
        result=self.store.revise_object(voucher['object_id'],expected_version,scope,{**voucher['data'],
            'validated_by':actor,'validated_at':utcnow(),'formal_balance_impact':False},status='LOCALLY_CONFIRMED',created_by=actor)
        self.store.add_audit('AUTONOMOUS_HUMAN_REVIEW',actor,scope,object_id=voucher['object_id'],before=voucher,after=result,reason='人工本地复核；未正式过账')
        return result

    def start(self):
        if not self.settings.autonomous_enabled or self.thread: return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                for o in self.store.list_scope_objects():
                    if self.stop_event.is_set(): break
                    sc=Scope.model_validate(o['data']['scope'])
                    try: self.tick(sc)
                    except Exception as exc: log.warning('Monthly scope worker: %s',type(exc).__name__)
                self.stop_event.wait(2)
        self.thread=threading.Thread(target=loop,daemon=True,name='autonomous-monthly');self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=8)
        self.thread=None

    def project(self, scope):
        job=self.current(scope)
        fp,sources,answers=self.inputs(scope)
        closed=self.period_is_closed(scope)
        stale=bool(job and not closed and job['data']['fingerprint']!=fp)
        accepted=bool(job and job['status']=='ACCEPTED' and not stale)
        result=job['data'].get('result',{}) if accepted else {}
        can_reassess=bool(accepted and not closed and result.get('review_policy_version',1)<REVIEW_POLICY_VERSION)
        delivery=result.get('delivery',{})
        findings=delivery.get('findings',[])
        pending=[f for f in findings if f.get('needs_user')]
        blocking_findings=[f for f in pending if f.get('blocks_confirmation',True) is not False]
        assessments=delivery.get('voucher_assessments',[])
        vouchers=[self.store.get_object(v,scope) for v in job['data'].get('vouchers',[])] if accepted else []
        confirmed=sum(v['status']=='LOCALLY_CONFIRMED' for v in vouchers)
        status='STALE' if stale else job['status'] if job else 'WAITING_INPUT'
        baseline=self.store.get_object(self.service._baseline_object_id(scope),scope)
        period=self.store.get_object(self.service._period_object_id(scope),scope)
        gaps=sum(a['status']=='NEEDS_EVIDENCE' for a in assessments)
        blocked=sum(a['status']=='SYSTEM_BLOCKED' for a in assessments)
        # Read-only projection of every assessed entry; never manufacture VoucherVersion IDs.
        groups=effective_entries(delivery)
        originals=defaultdict(list)
        for entry in delivery.get('entries',[]): originals[entry['voucher']].append(entry)
        revisions={r['voucher']:r for r in delivery.get('revisions',[])}
        previews=[{'voucher':a['voucher'],'assessment':a,'entries':groups[a['voucher']],
                   'original_entries':originals[a['voucher']],'revision':revisions.get(a['voucher']),
                   'findings':[f for f in findings if a['voucher'] in f.get('affected_vouchers',[]) or f['id'] in a.get('finding_ids',[])]}
                  for a in assessments if groups[a['voucher']]]
        # 主线六步与传统管线共用 `app/main_flow.py` 的定义。这里只负责算状态 ——
        # 名字、顺序和"算不算主线"不在这里写第二份。
        #
        # 第 4 步「AI 处理」吸收内部的自主分析与独立审查两步：两步都由机器完成，
        # 对使用的人是同一件事，细节进 summary。原来它们各占一格，进度条会在
        # 「独立审查」这个人类无事可做的步骤上停着。
        # 第 5 步「人工确认」才是真正要人做的：findings 里 needs_user 的那些。
        historical_preparation=self.service.historical.view(scope)
        prerequisite=historical_prerequisite(
            historical_preparation,
            self.service.historical_plans.view(scope,historical_preparation),
            'VALID' if baseline['status']=='CONFIRMED' else 'DRAFT')
        if accepted:
            analysis_summary=f"{len(delivery.get('entries',[]))} 条分录 · 独立审查" + ('完成' if not blocked else f'后仍有 {blocked} 张系统受阻')
        else:
            analysis_summary='正在独立审查' if status=='REVIEWING' else LABELS[status]
        stages={
            'scope':_scope_stage(scope),
            'history':_history_stage(prerequisite,historical_preparation),
            'source':{'status':'COMPLETED' if sources else 'WAITING','summary':f'{len(sources)} 份原件'},
            'analysis':{'status':'COMPLETED' if accepted and not blocked else 'RUNNING' if status in ACTIVE else 'WAITING',
                        'summary':analysis_summary},
            'confirmation':{'status':'COMPLETED' if accepted and not pending else 'WAITING',
                            'summary':f'{len(pending)} 项需要你补充说明' if pending else ('没有需要你确认的事项' if accepted else '完成后交接具体问题')},
            'voucher':{'status':'COMPLETED' if vouchers and confirmed==len(previews) and not blocked else 'WAITING',
                       'summary':f'{confirmed} / {len(previews)} 张已复核 · {gaps} 张待补证'},
            'delivery':{'status':'WAITING','summary':'尚未正式交付'},
        }
        flow=main_flow.build(stages)
        # 还有凭证没复核完时，当前步骤要停在凭证上，不被后面的步骤抢走。
        if previews and confirmed<len(previews):
            flow={**flow,'current_stage':'voucher'}
        flow['prerequisite']=prerequisite
        history=self.store.list_objects(TYPE,scope)
        previous_result=None
        if not accepted:
            previous=max((h for h in history if h['status']=='ACCEPTED'),key=lambda h:h['data']['revision'],default=None)
            if previous:
                old=previous['data']['result']['delivery']
                previous_result={'run_id':previous['object_id'],'revision':previous['data']['revision'],
                    'candidate_count':len(old.get('voucher_assessments',[])),
                    'ready_count':sum(a['status']=='READY_FOR_REVIEW' for a in old.get('voucher_assessments',[])),
                    'pending_count':sum(a['status']=='NEEDS_EVIDENCE' for a in old.get('voucher_assessments',[]))}
        safe_job={k:job[k] for k in ('object_id','version','status')} if job else None
        if safe_job:
            safe_job['data']={k:job['data'].get(k) for k in ('revision','message','phase','round','attempt','events','parent_id','runtime')}
            safe_job['status']=status
        workflow={'enabled':True,'job':safe_job,'executor':self.selected_backend(scope),'executors':choices(self.settings),
                  'bookkeeping_profile':self.bookkeeping_profile(scope),
                  'bookkeeping_profiles':[{'id':key, **value} for key,value in PROFILES.items()],
                  'applied_bookkeeping_profile':(job['data'].get('bookkeeping_profile') or
                      {'id':'ORIGINAL','label':PROFILES['ORIGINAL']['label']}) if job else None,
                  'travel_policy':self.travel_policy(scope),
                  'applied_travel_policy':job['data'].get('travel_policy') if accepted else None,
                  'travel_policy_applications':delivery.get('travel_policy_applications', []),
                  'previous_result':previous_result,
                  'status':status,'label':'部分系统问题仍待处理' if accepted and blocked else LABELS[status],'stale':stale,
                  'accepted':accepted,'can_retry':status in {'BLOCKED','CANCELLED','STALE'} or bool(blocked),'can_reassess':can_reassess,'source_count':len(sources),'candidate_count':len(assessments),
                  'ready_count':len(vouchers),'pending_count':gaps,'blocked_count':blocked,
                  'confirmed_count':confirmed,'findings':findings,'assessments':assessments,
                  'entry_previews':previews,'entry_preview_count':len(previews),
                  'invoice_matching':matching_projection(delivery),
                  'blocking_finding_count':len(blocking_findings),
                  'report':delivery.get('report',''),'mode':delivery.get('mode'),
                  'review':result.get('review',{}),'mechanical':result.get('mechanical',{}),
                  'answers':[{'answer_id':a['object_id'],**a['data']} for a in answers],
                  'materials_complete':self.review_context(scope)['materials_complete'],
                  'decision_responses':delivery.get('decision_responses',[]),
                  'history':[{'id':h['object_id'],'revision':h['data']['revision'],'status':LABELS.get(h['status'],h['status']),
                              'bookkeeping_mode':PROFILES.get(h['data'].get('bookkeeping_profile',{}).get('id','ORIGINAL'),{}).get('label','原有处理'),
                              'executor':BACKENDS.get(h['data'].get('runtime',{}).get('backend','codex'),'执行器待核实')} for h in history]}
        counts={'source_artifacts':len(sources),'facts':len(delivery.get('entries',[])),'groups':len(assessments),
                'pending_confirmation_cards':len(pending),'blockers':len(blocking_findings)+blocked,'reconciliation_checks':len(result.get('mechanical',{}).get('checks',[]))}
        next_step={'version':'workbench-next-step-v1','owner':'USER' if accepted else 'SYSTEM',
                   'state':'READY_TO_CONFIRM' if vouchers else 'NEEDS_EVIDENCE' if previews else status,'title':'查看分录与复核事项' if previews else LABELS[status],
                   'explanation':job['data']['message'] if job else '上传资料后系统自动处理','task_id':None,
                   'action':{'kind':'VOUCHERS','label':'查看分录与复核事项'} if previews else None}
        return {'autonomous_available':True,'scope':scope.model_dump(),'display_context':self.service.display_context(scope),'period':period,'baseline':baseline,
                'baseline_validation':{'status':'VALID' if baseline['status']=='CONFIRMED' else 'DRAFT','reason':'原件审查不改变正式期初确认状态'},
                'autonomous_workflow':workflow,'counts':counts,'artifacts':self.store.list_objects('SourceArtifact',scope),
                'vouchers':vouchers,'deliveries':[],'groups':[],'pending_confirmation_cards':[],
                'blockers':[{'reason':f['title'],'group_id':f['id'],'missing_evidence':[f['detail']]} for f in blocking_findings],
                'deliverable_groups':[], 'current_run':None,'history_runs':[],'fact_summaries':[],
                'progress':flow,
                'material_review':{'next_step':next_step,'tasks':[],'counts':{'files':len(sources),'records':counts['facts']},'buckets':[]},
                'data_readiness':{'baseline_sources':{'balance':[],'close':[]},'categories':[]},
                'bank_accounts':self.service.bank_accounts.view(scope,sources),'parse_plans':[],
                'payroll_mappings':[],'historical_preparation':historical_preparation,'historical_issue_plans':[]}
