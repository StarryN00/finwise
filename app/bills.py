"""Human bill context is a version-bound supplement, never a rewritten fact."""
from calendar import monthrange
from datetime import date
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from app.db import utcnow
from app.ontology.errors import PreconditionFailed, VersionConflict
from app.ontology.store import digest

TYPE = 'BillBusinessConfirmation'
ROLE_ISSUE = 'period：票据清单未列本期收付日期及业务角色，请关联收票或出票业务依据'
PERIOD_ISSUE = '业务期间：不属于已核定的本期业务范围，需核对原件与业务日期'
DISPLAY_ROLE_ISSUE = ROLE_ISSUE.replace('period：', '业务期间：')


class BillInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    business_kind: Literal['RECEIVED', 'HELD', 'ENDORSED', 'OTHER']
    input_token: StrictStr = Field(min_length=1, max_length=100)
    business_period: StrictStr = Field(pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    business_date: StrictStr = Field(default='', max_length=10)
    original_receipt_period: StrictStr = Field(default='', max_length=7)
    account_candidate_id: StrictStr = Field(default='', max_length=100)
    account_name: StrictStr = Field(default='', max_length=200)
    account_code: StrictStr = Field(default='', max_length=40)
    reason: StrictStr = Field(min_length=1, max_length=2000)
    evidence_ids: list[StrictStr] = Field(default_factory=list, max_length=10)


class BillReview:
    def __init__(self, service):
        self.service, self.store = service, service.store

    @staticmethod
    def supports(fact):
        d = fact['data']
        return d.get('record_type') == 'ELECTRONIC_ACCEPTANCE' and d.get('normalized_value', {}).get('register_kind') == 'bill_register'

    def binding(self, fact, artifact):
        values = fact['data'].get('normalized_value', {})
        return {**self.service.materials.binding(fact, artifact),
                'acceptance_no': values.get('acceptance_no'), 'sub_range': values.get('sub_range')}

    def input_token(self, scope, fact, artifact):
        prior = next((c for c in self.store.list_objects(TYPE, scope) if c['data']['binding']['fact_id']==fact['object_id']), None)
        return digest({'binding':self.binding(fact,artifact), 'prior':{'id':prior['object_id'],'version':prior['version'],'status':prior['status']} if prior else None})

    def source_ok(self, scope, fact, artifact):
        return (self.supports(fact) and artifact['status'] == 'ACTIVE'
                and artifact['data'].get('observed_period') == scope.accounting_period_id
                and artifact['data'].get('parse_status') in {'PARSED', 'PARSED_WITH_ISSUES'}
                and fact['status'] not in {'VOID', 'ARCHIVED', 'SUPERSEDED'}
                and fact['object_id'] in artifact['data'].get('parsed_fact_ids', [])
                and bool(fact['data'].get('source_anchor'))
                and self.service.materials.source_valid(artifact))

    def candidates(self, scope):
        """Only same-Scope evidence; no global chart or invented account codes."""
        result = []
        baseline = self.store.get_object(self.service._baseline_object_id(scope), scope)
        if baseline['status'] == 'CONFIRMED':
            try:
                self.service._require_baseline_confirmed(scope)
                lines = baseline['data'].get('confirmed_inputs', {}).get('balances', [])
                self._add_candidates(result, baseline, lines, 'BASELINE', '已确认期初科目')
            except PreconditionFailed:
                pass
        historical = self.service.historical.view(scope)
        if historical and historical['status'] in {'NEEDS_REVIEW', 'READY_FOR_CONFIRMATION'}:
            refs = historical['data'].get('sources', [])
            if refs and all(self._evidence_valid(scope, r) for r in refs):
                self._add_candidates(result, historical, (historical['data'].get('result') or {}).get('balances', []),
                                     'HISTORICAL', '历史账表识别，当前科目待核对')
        return result

    @staticmethod
    def _add_candidates(result, source, lines, status, label):
        for line in lines:
            code, name = line.get('account_code'), line.get('account_name')
            if not code or not name:
                continue
            binding = {'object_id': source['object_id'], 'version': source['version'], 'account_code': code, 'account_name': name}
            result.append({'id': digest(binding), 'code': code, 'name': name, 'status': status,
                           'source_label': label, 'binding': binding})

    def _evidence_valid(self, scope, ref):
        try:
            a = self.store.get_object(ref['artifact_id'], scope)
            return (a['status'] in {'ACTIVE', 'PERIOD_EXCEPTION'} and a['version'] == ref['version']
                    and a['data'].get('sha256') == ref['sha256'] and self.service.materials.source_valid(a))
        except KeyError:
            return False

    def view(self, scope, artifacts, facts):
        candidates = self.candidates(scope)
        candidate_ids = {c['id'] for c in candidates}
        files, records = {a['object_id']: a for a in artifacts}, {f['object_id']: f for f in facts}
        confirmations = []
        for obj in self.store.list_objects(TYPE, scope):
            d, b = obj['data'], obj['data']['binding']
            f, a = records.get(b['fact_id']), files.get(b['artifact_id'])
            valid = bool(obj['status'] in {'CONFIRMED', 'OPINION'} and f and a and self.source_ok(scope, f, a)
                         and b == self.binding(f, a)
                         and (not d['account_candidate_id'] or d['account_candidate_id'] in candidate_ids)
                         and all(self._evidence_valid(scope, r) for r in d['evidence_refs']))
            confirmations.append({**obj, 'valid': valid, 'stale': obj['status'] != 'REVOKED' and not valid})
        return {'candidates': candidates, 'confirmations': confirmations,
                'confirmed_count': sum(c['valid'] and c['status'] == 'CONFIRMED' for c in confirmations)}

    def execute(self, scope, action, target, version, actor, payload):
        self.service._ensure_period_open(scope)
        obj = self.store.get_object(target, scope)
        if obj['version'] != version:
            raise VersionConflict()
        if action == 'revoke_bill_business':
            if obj['status'] not in {'CONFIRMED', 'OPINION'} or set(payload) - {'reason'} or not isinstance(payload.get('reason', ''), str) or len(payload.get('reason', '')) > 2000:
                raise PreconditionFailed('确认记录已撤销或撤销原因无效')
            saved = self.store.revise_object(target, version, scope,
                {**obj['data'], 'revoked_by': actor, 'revoked_at': utcnow(), 'revocation_reason': payload.get('reason', '').strip()},
                status='REVOKED', created_by=actor)
            self.store.add_audit('BILL_CONFIRMATION_REVOKED', actor, scope, object_id=target, object_version=saved['version'], before=obj, after=saved)
            return {'object': saved}
        try:
            value = BillInput.model_validate(payload)
        except ValidationError as exc:
            raise PreconditionFailed('请填写有效的业务归属、科目与判断依据；不允许修改原始金额或责任人') from exc
        artifact = self.store.get_object(obj['data'].get('source_artifact_id', ''), scope)
        if not self.source_ok(scope, obj, artifact):
            raise PreconditionFailed('票据或来源已失效，请重新核对当前版本')
        if value.input_token != self.input_token(scope, obj, artifact):
            raise VersionConflict('票据原件或人工处理版本已变化，请刷新后重新核对')
        values = obj['data']['normalized_value']
        if value.business_period != scope.accounting_period_id:
            raise PreconditionFailed('本期业务必须属于当前期间；历史持有请单独填写原收票期间')
        if value.business_kind == 'HELD':
            if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', value.original_receipt_period) or value.original_receipt_period >= value.business_period:
                raise PreconditionFailed('历史持有必须填写早于本期的原收票期间')
            occurrence = value.original_receipt_period
        else:
            if value.original_receipt_period:
                raise PreconditionFailed('仅历史持有填写原收票期间')
            occurrence = value.business_period
        try:
            first = date.fromisoformat(occurrence + '-01')
            last = first.replace(day=monthrange(first.year, first.month)[1])
            if value.business_date:
                day = date.fromisoformat(value.business_date)
                if day.isoformat() != value.business_date or value.business_date[:7] != occurrence:
                    raise ValueError()
                first = last = day
            issue, maturity = values.get('issue_date'), values.get('maturity_date')
            if issue and last < date.fromisoformat(issue) or maturity and first > date.fromisoformat(maturity):
                raise ValueError()
        except ValueError as exc:
            raise PreconditionFailed('业务日期或期间与原收票期间、出票日或到期日矛盾，请核对') from exc
        selected = next((c for c in self.candidates(scope) if c['id'] == value.account_candidate_id), None)
        if value.account_candidate_id and not selected:
            raise PreconditionFailed('科目来源或版本已变化，请重新选择')
        if selected and (value.account_name or value.account_code):
            raise PreconditionFailed('选择已有科目时不能替换其名称或编码')
        if not selected and not value.account_name:
            raise PreconditionFailed('请选择企业科目或填写拟用科目名称')
        evidence = []
        for aid in dict.fromkeys(value.evidence_ids):
            a = self.store.get_object(aid, scope)
            if a['object_type'] != 'SourceArtifact' or a['status'] not in {'ACTIVE', 'PERIOD_EXCEPTION'} or not self.service.materials.source_valid(a):
                raise PreconditionFailed('关联依据不是当前范围内的有效原件')
            evidence.append({'artifact_id': aid, 'version': a['version'], 'sha256': a['data']['sha256']})
        binding = self.binding(obj, artifact)
        key = 'bill-confirm-' + digest({'scope': scope.model_dump(), 'fact_id': target})
        old = next((x for x in self.store.list_objects(TYPE, scope) if x['object_id'] == key), None)
        current = self.view(scope, self.store.list_objects('SourceArtifact', scope), self.store.list_objects('FactRecord', scope))
        if any(c['object_id'] == key and c['valid'] for c in current['confirmations']):
            raise PreconditionFailed('本条已有有效处理记录；如需更正，请先撤销后重新确认')
        data = {**value.model_dump(), 'binding': binding, 'evidence_refs': evidence,
                'account_name': selected['name'] if selected else value.account_name,
                'account_code': selected['code'] if selected else value.account_code,
                'account_status': selected['status'] if selected else 'PROPOSED',
                'account_source': selected['source_label'] if selected else '人工拟用科目，尚未建立科目',
                'confirmed_by': actor, 'confirmed_at': utcnow(),
                'date_precision': 'DAY' if value.business_date else 'MONTH',
                'current_receipt': value.business_kind == 'RECEIVED',
                'effect': '人工补充业务归属及拟用科目，不代表原件核实或账务可用'}
        status = 'OPINION' if value.business_kind == 'OTHER' else 'CONFIRMED'
        saved = self.store.revise_object(key, old['version'], scope, data, status=status, created_by=actor) if old else self.store.create_initial_object(TYPE, scope, data, status=status, created_by=actor, object_id=key)
        self.store.add_audit('BILL_BUSINESS_CONFIRMED', actor, scope, object_id=key, object_version=saved['version'], before=old, after=saved, reason=value.reason)
        return {'object': saved, 'business_confirmed': status == 'CONFIRMED'}
