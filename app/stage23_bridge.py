"""Review-only bridge for the isolated Codex pilot; never approves accounting."""
from collections import defaultdict
from decimal import Decimal
import base64
import json
from pathlib import Path

from app.db import utcnow
from app.ontology.contracts import ArtifactInput
from app.ontology.errors import PreconditionFailed, VersionConflict
from app.ontology.store import digest
from app.stage23_pilot import sha256
from app.ontology.service import OntologyService

ORIGIN = 'codex-stage23-pilot-v1'


class Stage23PilotService(OntologyService):
    """Installed explicitly by the pilot server, never by the normal app."""
    stage23_pilot_enabled = True

    def validate_draft(self, scope, *, voucher_id, actor_id, expected_version):
        self._ensure_period_open(scope)
        voucher = self.store.get_object(voucher_id, scope)
        if voucher['data'].get('origin') == ORIGIN:
            return validate_draft(self, scope, voucher, actor_id, expected_version)
        return super().validate_draft(scope, voucher_id=voucher_id, actor_id=actor_id,
                                     expected_version=expected_version)

    def workbench(self, scope, **kwargs):
        view = super().workbench(scope, **kwargs)
        packets = self.store.list_objects('Stage23ReviewPacket', scope)
        if not packets:
            return view
        packet = packets[-1]
        current = []
        stale = []
        for voucher in view['vouchers']:
            if voucher['data'].get('packet_id') != packet['object_id']:
                continue
            try:
                check_current(self, scope, voucher)
                current.append(voucher)
            except (PreconditionFailed, KeyError, OSError) as exc:
                stale.append(str(exc))
        view['stage23_review'] = {'packet_id': packet['object_id'], 'ready_count': len(current),
            'pending_count': len(packet['data']['pending_vouchers']), 'stale': stale,
            'formal_balance_impact': False}
        if current and not stale:
            # The upstream legacy queues stay visible; only the next available
            # action points to the real, independently checked voucher drafts.
            view['material_review']['next_step'] = {
                'version': 'workbench-next-step-v1', 'origin': ORIGIN,
                'state': 'READY_TO_CONFIRM', 'owner': 'USER',
                'title': '复核 Agent 已查证的候选凭证',
                'explanation': f"可复核 {len(current)} 张；另有 {len(packet['data']['pending_vouchers'])} 张保留待补证，尚未定稿。",
                'task_id': None, 'action': {'kind': 'VOUCHERS', 'label': '进入凭证复核'}}
        return view


def require_pilot(service):
    settings = service.store.database.settings
    # This adapter is installed only by the isolated server script.
    if not getattr(service, 'stage23_pilot_enabled', False) or settings.environment != 'development':
        raise PreconditionFailed('该实验接入仅在隔离环境启用')


def attach_delivery(service, scope, folder):
    require_pilot(service)
    folder = Path(folder)
    status = json.loads((folder/'status.json').read_text())
    if status['status'] != 'ANALYSIS_ACCEPTED':
        raise PreconditionFailed('自主处理与独立审查尚未通过，不能接入凭证复核')
    workspace = folder/'executor'
    if sha256(workspace/'work/delivery.json') != status['delivery_sha256']:
        raise PreconditionFailed('审查后成果已变化')
    review_dir = (folder/status['review_dir']).resolve()
    if review_dir.parent != folder.resolve():
        raise PreconditionFailed('审查路径越界')
    review = json.loads((review_dir/'review.json').read_text())
    if review.get('verdict') != 'pass' or review.get('defects') or not review.get('coverage'):
        raise PreconditionFailed('独立审查未通过')
    mechanical = json.loads((review_dir/'candidate/mechanical.json').read_text())
    if not mechanical.get('passed'):
        raise PreconditionFailed('确定性检查未通过')
    if sha256(review_dir/'candidate/delivery.json') != status['delivery_sha256']:
        raise PreconditionFailed('独立审查针对的不是当前成果')
    manifest = json.loads((workspace/'manifest.json').read_text())
    if manifest['period'] != scope.accounting_period_id:
        raise PreconditionFailed('成果期间不匹配')
    frozen = json.loads((folder/'frozen.json').read_text())
    if not all(sha256(workspace/p)==h for p,h in frozen.items()):
        raise PreconditionFailed('冻结输入或工具变化')
    delivery = json.loads((workspace/'work/delivery.json').read_text())
    packet_id = 'stage23-' + digest({'scope': scope.model_dump(), 'hash': status['delivery_sha256']})[:24]
    store = service.store
    try:
        return store.get_object(packet_id, scope)
    except KeyError:
        pass
    approved = set(review.get('ready_vouchers', []))
    assessments = {a['voucher']: a for a in delivery['voucher_assessments']}
    ready = {k for k,a in assessments.items() if a['status']=='READY_FOR_REVIEW'}
    if approved != ready:
        raise PreconditionFailed('独立审查与执行结果的可复核凭证范围不一致')
    source_versions = []
    ids = {}
    with store.database.transaction():
        for source in manifest['sources']:
            path = workspace/source['path']
            if sha256(path) != source['sha256']:
                raise PreconditionFailed('原件哈希变化')
            artifact = service.create_artifact(ArtifactInput(scope=scope, filename=source['filename'],
                content_base64=base64.b64encode(path.read_bytes()).decode()), actor_id='stage23-bridge')
            ids[source['id']] = artifact['object_id']
            source_versions.append({'id': artifact['object_id'], 'version': artifact['version'], 'sha256': source['sha256']})
        groups = defaultdict(list)
        for entry in delivery['entries']:
            groups[entry['voucher']].append(entry)
        packet = store.create_initial_object('Stage23ReviewPacket', scope, {
            'origin': ORIGIN, 'delivery_sha256': status['delivery_sha256'], 'delivery': delivery,
            'source_map': ids, 'source_versions': source_versions,
            'mechanical': mechanical, 'independent_review': review,
            'formal_balance_impact': False, 'ready_vouchers': sorted(ready),
            'pending_vouchers': sorted(set(groups)-ready), 'vouchers': [],
        }, status='PROPOSED', created_by='stage23-bridge', object_id=packet_id)
        vouchers = []
        for number in sorted(ready):
            assessment = assessments[number]
            reference = packet_id + ':' + number
            lines = []
            for i, entry in enumerate(groups[number], 1):
                debit = Decimal(entry['debit'])
                lines.append({'line_no': i, 'direction': 'DEBIT' if debit else 'CREDIT',
                    'account': entry['name'], 'account_code': entry['code'],
                    'amount': entry['debit'] if debit else entry['credit'],
                    'source_group_id': reference, 'source': {**entry['source'],
                       'artifact_id': ids[entry['source']['source_id']]}, 'memo': entry.get('memo','')})
            debit, credit = service._voucher_totals(lines, reference)
            if debit != credit:
                raise PreconditionFailed('候选凭证借贷不平')
            data = {'origin': ORIGIN, 'packet_id': packet_id, 'group_id': reference,
                    'voucher_number': number, 'lines': lines,
                    'date': groups[number][0]['date'], 'assessment': assessment,
                    'debit_total': str(debit), 'credit_total': str(credit),
                    'formal_balance_impact': False, 'source_versions': source_versions}
            draft = store.create_initial_object('VoucherDraft', scope, data, status='DRAFT', created_by='stage23-bridge')
            voucher = store.create_initial_object('VoucherVersion', scope, {**data, 'draft_id': draft['object_id']},
                status='DRAFT', created_by='stage23-bridge')
            vouchers.append(voucher['object_id'])
            store.add_audit('STAGE23_DRAFT_CREATED', 'stage23-bridge', scope,
                object_type='VoucherVersion', object_id=voucher['object_id'], object_version=1,
                after=voucher, reason='独立审查后的候选进入人工复核；未确认业务、未过账')
        packet = store.revise_object(packet_id, packet['version'], scope,
            {**packet['data'], 'vouchers': vouchers}, status='PROPOSED', created_by='stage23-bridge')
    return packet


def check_current(service, scope, voucher):
    require_pilot(service)
    packet = service.store.get_object(voucher['data']['packet_id'], scope)
    if packet['data']['origin'] != ORIGIN or voucher['object_id'] not in packet['data']['vouchers']:
        raise PreconditionFailed('凭证不属于已核验的实验成果')
    number = voucher['data']['voucher_number']
    if number not in packet['data']['ready_vouchers']:
        raise PreconditionFailed('该凭证尚缺业务依据')
    for ref in packet['data']['source_versions']:
        artifact = service.store.get_object(ref['id'], scope)
        if artifact['version'] != ref['version'] or artifact['status'] != 'ACTIVE':
            raise PreconditionFailed('原件版本或状态变化，须重新核验')
        path = service.store.database.settings.storage_path/artifact['data']['storage_path']
        if sha256(path) != ref['sha256']:
            raise PreconditionFailed('原件内容变化，须重新核验')
    initial = service.store.get_object(voucher['object_id'], scope, 1)
    if voucher['data']['lines'] != initial['data']['lines']:
        raise PreconditionFailed('分录已修改，须重新进行独立审查')
    return packet


def validate_draft(service, scope, voucher, actor_id, expected_version):
    if voucher['version'] != expected_version:
        raise VersionConflict()
    if voucher['status'] != 'DRAFT':
        raise PreconditionFailed('实验凭证当前不可复核')
    check_current(service, scope, voucher)
    debit, credit = service._voucher_totals(voucher['data']['lines'], voucher['data']['group_id'])
    if debit != credit:
        raise PreconditionFailed('借贷不平')
    data = {**voucher['data'], 'validated_by': actor_id, 'validated_at': utcnow(),
            'debit_total': str(debit), 'credit_total': str(credit), 'formal_balance_impact': False}
    result = service.store.revise_object(voucher['object_id'], expected_version, scope, data,
                                        status='LOCALLY_CONFIRMED', created_by=actor_id)
    service.store.add_audit('STAGE23_LOCALLY_REVIEWED', actor_id, scope,
        object_type='VoucherVersion', object_id=result['object_id'], object_version=result['version'],
        before=voucher, after=result, reason='隔离实验中的人工本地复核，不产生正式入账或交付包')
    return result
