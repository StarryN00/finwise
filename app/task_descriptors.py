"""Read-only decision descriptions. These never authorize or dispatch commands."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from app.ontology.contracts import Scope
from app.ontology.store import digest


class RecordScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    version: int
    source_anchor: Optional[dict[str, Any]] = None


class ArtifactScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    version: int
    sha256: Optional[str] = None


class DecisionScope(Scope):
    artifact: ArtifactScope
    records: list[RecordScope]


class WhyDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    facts: str
    rule: str
    recommendation: str
    origin: Literal['RULE'] = 'RULE'
    evidence: list[RecordScope]


class SlotProperty(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    label: str
    required: bool = False
    help: str = ''
    placeholder: str = ''
    choices: dict[str, str] = Field(default_factory=dict)


class FieldDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    label: str
    component: Literal['textarea', 'slot']
    required: bool = False
    slot: str = ''
    placeholder: str = ''
    max_length: int = 2000
    properties: list[SlotProperty] = Field(default_factory=list)


class DecisionStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    prompt: str
    fields: list[str]


class EffectDescriptor(BaseModel):
    """A bounded, machine-readable effect. No task action grants accounting use."""
    model_config = ConfigDict(extra='forbid')
    kind: str
    target: str
    description: str
    grants_accounting_usable: Literal[False] = False


class ReversibilityDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revocable: bool
    entry: Optional[str] = None


class OptionDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    action_type_version: str = 'action-catalog-v1'
    fallback: bool = False
    permissions: list[str] = Field(default_factory=list)
    applicability: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)
    reversibility: ReversibilityDescriptor = Field(
        default_factory=lambda: ReversibilityDescriptor(revocable=False)
    )
    label: str
    submit_label: str = ''
    execution_type: Literal['COMMAND', 'NAVIGATION'] = 'COMMAND'
    confirmation_label: str = ''
    success_label: str = ''
    post_submit_owner: Literal['SYSTEM', 'EXTERNAL', 'NONE'] = 'NONE'
    fields: list[FieldDescriptor] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    completion: str
    effects: list[EffectDescriptor]
    not_effects: list[str]
    available: bool = True
    unavailable_reason: str = ''
    steps: list[DecisionStep] = Field(default_factory=list)


class TaskDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['decision-v2'] = 'decision-v2'
    stage: Literal['SOURCE_REVIEW', 'BUSINESS_REVIEW', 'SYSTEM_REVIEW']
    why_now: str
    title: str
    why: WhyDescriptor
    scope: DecisionScope
    options: list[OptionDescriptor]
    steps: list[dict[str, Any]] = Field(default_factory=list)
    fingerprint: str = ''
    presentation: Optional['PresentationDescriptor'] = None


class PresentationRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    focus_fields: list[str]


class PresentationDescriptor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type_label: str
    explanation: str
    records: list[PresentationRecord]


VERIFY_RECORD_TYPE_LABELS = {
    'INVOICE': '采购发票',
    'SALES_INVOICE': '销售发票',
    'PAYMENT': '银行支出流水',
    'RECEIPT': '银行收入流水',
    'BANK_TRANSACTION': '银行流水',
    'ELECTRONIC_ACCEPTANCE': '电子承兑',
    'PAYROLL': '工资',
    'SOCIAL_SECURITY': '社保',
    'HOUSING_FUND': '住房公积金',
    'INDIVIDUAL_INCOME_TAX': '个人所得税',
    'OPENING_BALANCE': '期初余额',
    'CONTRACT': '合同',
    'STOCK_IN': '入库',
}
VERIFY_FIELD_LABELS = {
    'invoice_no': '发票号码', 'acceptance_no': '票据包号', 'person_name': '姓名',
    'person_id': '个人编号', 'contract_no': '合同编号', 'stock_in_no': '入库单号',
    'transaction_id': '交易流水号', 'counterparty': '对方名称', 'bank_account_ref': '本方账户',
    'invoice_date': '开票日期', 'transaction_date': '交易日期', 'entry_date': '入账日期',
    'contract_date': '合同日期', 'stock_in_date': '入库日期', 'issue_date': '出票日期',
    'arrival_date': '到账日期', 'start_period': '起始期间', 'end_period': '截止期间',
    'period': '业务期间', 'period_ref': '费款所属期',
    'invoice_total': '价税合计', 'amount': '金额', 'actual_salary': '实发工资',
    'net_pay': '实发工资', 'total': '合计', 'income': '收入金额', 'expense': '支出金额',
    'net_amount': '不含税金额', 'tax': '税额', 'balance': '账户余额',
    'insurance_type': '险种', 'employer_amount': '单位缴费金额', 'employee_amount': '个人缴费金额',
    'account': '个人公积金账号', 'account_code': '科目编码', 'account_name': '科目名称',
    'opening_debit': '期初借方余额', 'opening_credit': '期初贷方余额',
    'supplier': '供应商', 'item': '存货名称',
}
VERIFY_BANK_TYPES = {'PAYMENT', 'RECEIPT', 'BANK_TRANSACTION'}
VERIFY_INVOICE_TYPES = {'INVOICE', 'SALES_INVOICE'}
VERIFY_PEOPLE_TYPES = {'PAYROLL', 'SOCIAL_SECURITY', 'HOUSING_FUND', 'INDIVIDUAL_INCOME_TAX'}
VERIFY_FOCUS_GROUPS = {
    'INVOICE': (('invoice_no',), ('invoice_date',), ('invoice_total',), ('tax',)),
    'SALES_INVOICE': (('invoice_no',), ('invoice_date',), ('invoice_total',), ('tax',)),
    'PAYMENT': (('transaction_id',), ('transaction_date',), ('expense',), ('balance',)),
    'RECEIPT': (('transaction_id',), ('transaction_date',), ('income',), ('balance',)),
    'BANK_TRANSACTION': (('transaction_id',), ('transaction_date',), ('expense',), ('income',)),
    'ELECTRONIC_ACCEPTANCE': (('acceptance_no',), ('transaction_date',), ('amount',), ('period',)),
    'PAYROLL': (('person_name',), ('period',), ('actual_salary',), ('tax',)),
    'SOCIAL_SECURITY': (
        ('person_name', 'person_id', 'insurance_type'),
        ('period_ref', 'period', 'start_period', 'end_period'),
        ('employer_amount', 'total'),
        ('employee_amount',),
    ),
    'HOUSING_FUND': (('account',), ('person_name',), ('entry_date', 'start_period', 'period'), ('amount',)),
    'INDIVIDUAL_INCOME_TAX': (('person_name',), ('person_id',), ('period',), ('income',)),
    'OPENING_BALANCE': (('account_code',), ('account_name',), ('opening_debit',), ('opening_credit',)),
    'CONTRACT': (('contract_no',), ('contract_date',), ('supplier',), ('amount',)),
    'STOCK_IN': (('stock_in_no',), ('stock_in_date',), ('supplier',), ('amount',)),
}


def _chinese_list(items: list[str]) -> str:
    if len(items) < 2:
        return ''.join(items)
    return '、'.join(items[:-1]) + '和' + items[-1]


def _infer_verify_subject(fields: list[str]) -> str:
    field_set = set(fields)
    return (
        '发票' if field_set & {'invoice_no', 'invoice_date', 'invoice_total'}
        else '电子承兑' if 'acceptance_no' in field_set
        else '银行流水' if field_set & {'transaction_id', 'expense', 'income', 'bank_account_ref'}
        else '工资' if field_set & {'actual_salary', 'net_pay'}
        else '合同' if 'contract_no' in field_set
        else '入库' if 'stock_in_no' in field_set
        else '资料'
    )


def _verify_presentation(records: list[dict[str, Any]], refs: list[dict[str, Any]]) -> tuple[str, str]:
    focused = list(dict.fromkeys(field for ref in refs for field in ref['focus_fields']))
    typed_records = [record.get('record_type') for record in records if record.get('record_type')]
    record_types = set(typed_records)
    if typed_records and len(typed_records) != len(records):
        subject = '混合资料'
    elif len(record_types) == 1:
        subject = VERIFY_RECORD_TYPE_LABELS.get(next(iter(record_types)), '资料')
    elif record_types and record_types <= VERIFY_BANK_TYPES:
        subject = '银行流水'
    elif record_types and record_types <= VERIFY_INVOICE_TYPES:
        subject = '发票'
    elif record_types and record_types <= VERIFY_PEOPLE_TYPES:
        subject = '薪酬与税费'
    elif record_types:
        subject = '混合资料'
    else:
        inferred = {_infer_verify_subject(ref['focus_fields']) for ref in refs}
        subject = next(iter(inferred)) if len(inferred) == 1 else '混合资料'
    labels = list(dict.fromkeys(VERIFY_FIELD_LABELS.get(field, '对应字段') for field in focused))
    target = _chinese_list(labels) if labels else '字段含义和提取值'
    count = len(records)
    return (
        f'核对{subject}明细读取结果',
        f'请核对下方 {count} 条{subject}记录的{target}是否与原件一致。',
    )


BILL_PROPERTIES = [
    dict(name='business_kind', label='业务性质', required=True, choices={
        'RECEIVED': '本期收到', 'HELD': '以前期间收到、本期持有',
        'ENDORSED': '本期背书转出', 'OTHER': '其他（仅记录意见）'}),
    dict(name='business_period', label='业务期间', required=True, help='需明确确认当前办理期间，不默认采用出票日期。'),
    dict(name='original_receipt_period', label='原收票期间', required=True, help='仅历史持有时填写早于本期的原收票期间。'),
    dict(name='business_date', label='业务日期（可选）', help='不知道具体日可留空，按月份留痕；历史持有填写原收票日期。'),
    dict(name='search', label='搜索企业科目', placeholder='输入科目名称或编码'),
    dict(name='account_candidate_id', label='选择企业已有科目', help='历史账表候选不等于当前科目已确认。'),
    dict(name='account_name', label='拟用科目名称', required=True, placeholder='例如：应收票据'),
    dict(name='account_code', label='拟用科目编码（可选）'),
    dict(name='reason', label='判断依据', required=True, placeholder='例如：已向客户核实，本期收到用于结算货款；特殊科目请说明原因。'),
    dict(name='evidence_ids', label='关联已上传资料（可选）'),
]
BANK_PROPERTIES = [
    dict(name='account_id', label='所属银行账户'),
    dict(name='bank_name', label='所属银行', required=True),
    dict(name='account_number', label='本方账号（选填）'),
    dict(name='holder', label='账户户名（选填）'),
    dict(name='currency', label='币种', required=True),
    dict(name='confirmed', label='确认本份流水的银行归属', required=True),
]

OPTION_STEPS = {
    'confirm_bank_period': [
        dict(id='records', prompt='请核对原交易日期，只选择当前页需要确认归属的流水。', fields=['records']),
        dict(id='reason', prompt='可补充归属说明；不改变原件日期，也不直接入账。', fields=['reason']),
    ],
    'confirm_bill_business': [
        dict(id='nature', prompt='这张票据对本企业属于哪种业务？', fields=['business_kind']),
        dict(id='period', prompt='请确认实际业务期间；不知道具体日期可以只填月份。', fields=['business_period','original_receipt_period','business_date']),
        dict(id='account', prompt='准备使用哪个会计科目？已有科目或拟用科目均需你明确选择。', fields=['search','account_candidate_id','account_name','account_code']),
        dict(id='basis', prompt='你依据什么作出上述判断？附件不是必填。', fields=['reason','evidence_ids']),
    ],
    'confirm_statement_account': [
        dict(id='bank', prompt='这些流水属于本企业的哪个银行？账号可以不填。', fields=['account_id','bank_name','account_number','holder','currency']),
        dict(id='ownership', prompt='请确认所选银行确实属于本企业、本份流水归属正确。', fields=['confirmed']),
    ],
    'confirm_invoice_amount': [dict(id='basis', prompt='请核对原金额与正负号，并说明红字或零金额的实际业务原因。', fields=['reason'])],
    'verify_source_values': [
        dict(id='records', prompt='请查看原件对照，只勾选当前事项中你已经逐条核对的记录。', fields=['records']),
        dict(id='note', prompt='是否需要补充核实备注？没有可以直接继续。', fields=['note']),
    ],
    'defer_material_issue': [dict(id='reason', prompt='目前为什么无法继续处理？记录后问题仍保留。', fields=['reason'])],
}


OPTION_EXECUTION = {
    'supplement': dict(execution_type='NAVIGATION', confirmation_label='选择补充资料',
                       success_label='补充资料已接收，等待系统检查', post_submit_owner='SYSTEM'),
    'parse': dict(execution_type='NAVIGATION', confirmation_label='选择识别方式',
                  success_label='资料识别已发起', post_submit_owner='SYSTEM'),
    'verify_source_values': dict(execution_type='COMMAND', confirmation_label='确认所选记录已核对',
                                 success_label='所选记录已完成资料核实', post_submit_owner='NONE'),
    'confirm_invoice_amount': dict(execution_type='COMMAND', confirmation_label='确认本张发票金额已核对',
                                   success_label='本张发票金额核对已完成', post_submit_owner='NONE'),
    'confirm_bill_business': dict(execution_type='COMMAND', confirmation_label='确认票据业务与科目',
                                  success_label='票据业务与科目已确认', post_submit_owner='NONE'),
    'confirm_statement_account': dict(execution_type='COMMAND', confirmation_label='确认本份流水所属银行',
                                      success_label='本份流水所属银行已确认', post_submit_owner='NONE'),
    'defer_material_issue': dict(execution_type='COMMAND', confirmation_label='记录暂无法确认原因',
                                 success_label='原因已记录，等待外部资料或条件', post_submit_owner='EXTERNAL'),
    'confirm_bank_period': dict(execution_type='COMMAND', confirmation_label='确认所选流水归属目标期间',
                                success_label='所选流水期间归属已确认', post_submit_owner='NONE'),
}


def issue_presentation(task, scope, artifact, records, bank=None):
    """Reference existing rows; quote evidence without copying the raw-data contract."""
    from app.ontology.readiness import FIELDS

    reason = task['reason']
    prefix = reason.partition('：')[0]
    field = next((key for key, label in FIELDS.items() if prefix in {key, label}), prefix)
    period_issue = field in {'period', '期间', '业务期间'}
    bank_issue = field == 'bank_account_ref'
    bill_issue = task['kind'] in {'BILL', 'BILL_ACCOUNT'}
    date_issue = period_issue or field.endswith(('_date', '_period')) or '日期' in prefix
    amount_issue = task['kind'] == 'INVOICE_AMOUNT' or field in {'invoice_total', 'net_amount', 'tax', 'income', 'expense', 'balance', 'amount'} or '金额' in reason
    label, detail = '问题待核对', '现有信息不足以确定问题原因，请先核对对应来源和检查说明；不能据此认定客户缺少资料。'
    checks = []
    if task['kind'] == 'VERIFY':
        label, detail = '原件读取核对', '请逐条比较来源字段与读取结果，系统检查通过仍需人工核实。'
    elif task['kind'] == 'PARSE':
        label = '资料待识别' if artifact['data'].get('parse_status') == 'RECEIVED' else '解析问题'
        errors = artifact['data'].get('parse_errors') or []
        checks = [reason, *errors]
        detail = '请核对资料结构、映射与对账依据；解析未完成不代表客户缺资料。'
    elif field == 'invoice_status':
        label, detail = '发票状态待核对', '该状态触发发票状态核对，不能仅据此判为提取错误。请核对发票状态及对应业务处理依据。'
    elif bank_issue:
        label, detail = '流水银行归属待确认', '现有银行线索尚不足以确认本份流水的企业账户归属，请核对所属银行；账号可选填。'
    elif bill_issue:
        label, detail = '票据业务与科目待确认', '尚待明确业务性质、实际业务期间及拟用科目；出票日不代替实际业务日期。'
        if task['kind'] == 'BILL_ACCOUNT':
            label, detail = '核对票据拟用科目', '已有业务确认及拟用或历史科目记录，科目仍待核对，不自动建立科目或制证。'
        elif records and (records[0].get('bill_confirmation') or {}).get('status') == 'OPINION':
            label, detail = '处理意见已记录，业务归属仍待确认', '已有处理意见，但尚未明确业务归属，不能视为业务确认完成。取得明确依据后，可查看并撤销原记录，再重新确认。'
    elif date_issue:
        label, detail = '业务期间待核对' if period_issue else '日期待核对', f'当前办理期间为「{scope.accounting_period_id}」。请核对来源日期的格式、含义及业务期间，不能直接将该记录计入本期。'
    elif amount_issue:
        label = '发票金额待核对' if task['kind'] == 'INVOICE_AMOUNT' else '金额待核对'
        detail = ('请核对原金额、正负号及红字或零金额的业务原因。' if task['kind'] == 'INVOICE_AMOUNT'
                  else '请核对金额原值、格式或计算关系；无法读取的金额不能按零处理。')

    refs, originals, current = [], [], []
    for record in records:
        values = record.get('values') or {}
        comparison = {c['field']: c for c in record.get('comparison', [])}
        sources = record.get('field_sources') or {}
        if task['kind'] == 'VERIFY' and 'comparison' in record:
            # The workbench renders the comparison rows. Do not ask users to
            # check optional schema keys that have no value, source or row.
            available = list(comparison)
        elif task['kind'] == 'VERIFY':
            visible_values = [name for name, value in values.items()
                              if value is not None and (not isinstance(value, str) or value.strip())]
            available = list(dict.fromkeys([*visible_values, *comparison, *sources]))
        else:
            available = list(dict.fromkeys([*values, *comparison, *sources]))
        fields = [field] if field in available else []
        if task['kind'] == 'VERIFY':
            # Keep the first screen compact while naming the exact fields users must compare.
            groups = VERIFY_FOCUS_GROUPS.get(record.get('record_type'))
            if groups:
                fields = [next(name for name in group if name in available)
                          for group in groups if any(name in available for name in group)]
                for name in dict.fromkeys(name for group in groups for name in group):
                    if len(fields) >= 4:
                        break
                    if name in available and name not in fields:
                        fields.append(name)
                selected = set(fields)
                fields = [name for name in available if name in selected]
            else:
                groups = (
                    ('invoice_no', 'acceptance_no', 'person_name', 'person_id', 'contract_no', 'stock_in_no', 'transaction_id', 'counterparty', 'bank_account_ref'),
                    ('invoice_date', 'transaction_date', 'entry_date', 'contract_date', 'stock_in_date', 'period', 'period_ref'),
                    ('invoice_total', 'amount', 'actual_salary', 'net_pay', 'total', 'income', 'expense', 'net_amount'),
                )
                fields = [next(f for f in group if f in available) for group in groups if any(f in available for f in group)]
                fields += [f for f in ('tax', 'expense', 'income', 'period') if f in available and f not in fields][:4-len(fields)]
        elif bill_issue:
            fields = [f for f in ('acceptance_no', 'sub_range', 'amount', 'issue_date', 'transaction_date', 'period', 'transaction_type', 'status') if f in available]
        elif bank_issue:
            fields = [f for f in ('bank_account_ref', 'bank_name', 'account_number', 'holder') if f in available]
        elif period_issue:
            fields = [f for f in ('period', 'invoice_date', 'transaction_date', 'entry_date', 'contract_date', 'stock_in_date', 'period_ref', 'start_period', 'end_period') if f in available]
        elif task['kind'] == 'INVOICE_AMOUNT' or field == 'invoice_total' and '不一致' in reason:
            fields = [f for f in ('invoice_total', 'net_amount', 'tax') if f in available]
        elif not fields and reason in record.get('issues', []):
            # Generic translated fields have lost their name; focus only located anomalies.
            fields = [f for f, c in comparison.items() if c.get('state') in {'DIFFERENT', 'MISSING', 'AMBIGUOUS'}]
        refs.append(dict(id=record['object_id'], focus_fields=fields))
        if task['kind'] == 'VERIFY' or bill_issue:
            continue
        for name in fields:
            cell, source = comparison.get(name, {}), sources.get(name, {})
            raw = cell.get('source_value')
            if raw is None:
                raw = source.get('original_value')
            original = raw is not None
            if raw is None:
                raw = values.get(name)
            region = cell.get('region') or source.get('region') or (record.get('source_anchor') or {}).get('region')
            field_label = cell.get('source_label') or source.get('source_label') or FIELDS.get(name, name)
            quoted = f'{region + " " if region else ""}{field_label}' + ('原值' if original else '当前值') + f'「{raw if raw is not None else "未提供"}」'
            if raw is not None:
                (originals if original else current).append((str(raw), quoted))
    if task['kind'] == 'VERIFY':
        label, detail = _verify_presentation(records, refs)
    if bank_issue and bank:
        identity = bank.get('identity') or {}
        for name, title in [('bank_name', '银行'), ('bank_hint', '银行线索'), ('account_number', '账号'), ('holder', '户名')]:
            if identity.get(name):
                current.append((str(identity[name]), f'{title}「{identity[name]}」'))
        if bank.get('error'):
            checks.append(bank['error'])
    if label == '问题待核对':
        checks.append(reason)
    candidates = originals or current
    candidates += [(str(check), f'检查说明「{check}」') for check in checks]
    # Reserve the overflow notice before adding whole evidence tokens. Never cut IDs.
    notice = f'涉及 {len(records)} 条记录，详见下方清单。' if records else '完整原因详见检查说明。'
    quotes, seen = [], set()
    omitted = False
    for value, quote in candidates:
        if value in seen:
            continue
        seen.add(value)
        if len(quotes) < 2 and len('；'.join([*quotes, quote]) + '。' + detail + notice) <= 400:
            quotes.append(quote)
        else:
            omitted = True
    explanation = ('；'.join(quotes) + '。' if quotes else '') + detail
    if task['kind'] != 'VERIFY' and (omitted or len(records) > 2):
        explanation += notice
    return dict(type_label=label, explanation=explanation, records=refs)


def issue_advice(task, records=()):
    reason = task['reason']
    if task['kind'] == 'PARSE':
        return '请先核对具体识别原因、表头、资料类型及对账依据。系统已适配的版式可重新识别；失败仍保留具体原因，不代表客户缺资料。'
    for words, advice in [
        (('账户',), '请确认流水所属银行，账号选填。同银行有多个账户时再选择具体账户。无需因缺少账号重复上传资料。'),
        (('税率',), '核对原表税率单元格及金额、税额是否存在格式或数值差异。税额保留原值，不用反推税率算回税额；只有后续业务确实需要税率时才补充对应依据。'),
        (('表头', '社保', '公积金', '字段含义'), '先查看完整来源的分组表头，确定这列属于社保、公积金还是其他扣款。不能把所有“单位缴／个人缴”都当成社保；表头仍不明确时，请提供有完整列名的工资表，不需要重填每位员工金额。'),
    ]:
        if any(word in reason for word in words):
            return advice
    if any(word in reason for word in ('期间', '日期', 'period', 'date', '收付')):
        if records and all(r.get('record_type') in {'INVOICE', 'SALES_INVOICE'} or 'invoice_date' in r.get('values', {}) for r in records):
            return '核对原件开票日期、日期格式与当前办理期间，明确发票的业务归属；更正或补充依据后重新校验期间。'
        if records and all(r.get('record_type') == 'ELECTRONIC_ACCEPTANCE' for r in records):
            return '核对实际收票、持有或背书的业务期间；出票日不代替收票日，历史持有不作为本期新增收票。'
        return '核对原件业务日期、日期格式与当前办理期间，明确实际业务归属后重新校验。'
    if reason.startswith(('invoice_status：', '发票状态：')):
        return '核对原件所列发票状态及对应业务处理依据；状态待核对不等于提取错误，当前不提供直接确认状态的操作。'
    return '先对照原件、提取值与当前检查原因。现有信息不足以确定处理方式；有更正或补充依据时再提供，重新校验前保留问题。'


def describe_task(task, scope, artifact, records, bank=None):
    """Additive projection only: IDs, bindings, inputs and write paths stay intact."""
    advice = issue_advice(task, records)
    common = ['不修改原始文件或提取金额', '不解除其他资料问题、期初或凭证门禁']
    requires = ['操作人具备权限且期间开放', '任务、原件及记录版本仍有效', '执行时由原有服务端命令重新校验']
    option = dict(id='supplement', label='补充资料（可选）', fields=[], requires=requires,
                  completion='补充依据后通过对应检查；上传成功不代表问题解除。',
                  effects=['追加保存补充资料，等待对应检查'], not_effects=common)
    title = task['title']
    facts_summary = f"{task['filename']} · 涉及 {len(records)} 条记录"
    if task['kind'] == 'VERIFY':
        advice = '系统已完成提取检查，未发现问题。请确认字段是否归类正确、原件数值是否读对、所属期间是否正确。仅勾选当前事项中已检查的记录，不是确认业务真实、工资计算正确或账务可用。'
        title = '确认字段含义与读取结果'
        option.update(id='verify_source_values', label='确认原件与提取值一致',
                      fields=[dict(name='records', label='选择当前事项中已核对的记录', component='slot', slot='record_selection', required=True),
                              dict(name='note', label='核实备注（可选）', component='textarea')],
                      completion='核对当前事项的字段、数值与期间，仅提交已勾选的记录。',
                      effects=['为已选择且通过校验的记录保存资料核实结果'])
    elif task['kind'] == 'INVOICE_AMOUNT':
        title = '核对发票 ' + str(records[0]['values'].get('invoice_no', ''))
        facts_summary = f"{task['filename']} · 价税合计 {records[0]['values'].get('invoice_total', '待核对')} 元"
        advice = '确认原件的正负号、金额及对应业务原因，例如退货、折让、冲红或零金额业务。有充分依据即可确认，无需重复上传相同文件。'
        option.update(id='confirm_invoice_amount', label='确认已核对',
                      fields=[dict(name='reason', label='核对说明', component='textarea', required=True,
                                   placeholder='例如：已核对原始导出表，确认为退货冲红；对应原业务已核实。')],
                      completion='核对当前发票的原始金额、正负号和业务原因，并填写核对说明。',
                      effects=['保存金额核对记录，仅解除本张发票的红字／零金额提醒'],
                      not_effects=common + ['不计作原件与提取值一致的资料核实'])
    elif task['kind'] in {'BILL', 'BILL_ACCOUNT'}:
        values = records[0]['values']
        facts_summary = f"{task['filename']} · 票据 {values.get('acceptance_no', '待核对')} · 子票 {values.get('sub_range', '待核对')} · 金额 {values.get('amount', '待核对')} 元"
        advice = '可以根据已掌握的情况确认，无需重复上传。出票日不代替收票日，历史持有不作为本期新增收票。'
        option.update(id='confirm_bill_business', label='确认业务与科目',
                      fields=[dict(name='business', label='确认票据业务与科目', component='slot', slot='bill_business', required=True, properties=BILL_PROPERTIES)],
                      completion='明确业务性质、期间、拟用科目和判断依据；其他原件问题及账务门禁仍需处理。',
                      effects=['保存人工补充；明确归属时解除对应角色及期间缺口，选择其他时仅记录意见'],
                      not_effects=common + ['不自动新建科目，不计作原件核实或账务可用'])
        if task['kind'] == 'BILL_ACCOUNT' or (records[0].get('bill_confirmation') or {}).get('status') == 'OPINION':
            option.update(available=False, unavailable_reason='已有处理记录。取得明确依据后，可查看并撤销原记录，再重新确认。')
            title = '核对票据拟用科目' if task['kind'] == 'BILL_ACCOUNT' else '处理意见已记录，业务归属仍待确认'
    elif task['reason'].startswith('bank_account_ref：') and bank:
        identity = bank.get('identity') or {}
        bank_name = identity.get('bank_name') or identity.get('bank_hint')
        if bank_name:
            facts_summary += ' · 已识别银行：' + bank_name
        if bank.get('requires_specific_account'):
            advice = '该银行已出现多个明确账号。请选择具体账户，或展开选填信息登记本份流水的账号；不能按银行名称合并为一个默认账户。'
        option.update(id='confirm_statement_account', label='确认所属银行并继续',
                      fields=[dict(name='ownership', label='流水银行归属', component='slot', slot='bank_ownership', required=True, properties=BANK_PROPERTIES)],
                      completion='核对所属银行并确认归属；同银行存在多个账户时选择具体账户。',
                      effects=['保存银行关联，并按原有规则分配本期可明确归属的同银行资料'],
                      not_effects=common + ['不确认交易与发票匹配'])
        if bank['status'] in {'CONFLICT', 'INVALID'}:
            option.update(available=False, unavailable_reason=bank.get('error') or '银行或来源信息存在冲突，请补充更正依据。')
    elif task.get('bank_period'):
        target=task['bank_period']['target_period']
        advice=f'原件交易日期与提取值一致。建议按 {target} 归属，不计入本期流水发生额；不自动入账。'
        option.update(id='confirm_bank_period',label=f'确认归属 {target}',
            fields=[dict(name='records',label='选择当前页需确认归属的流水',component='slot',slot='period_record_selection',required=True),
                    dict(name='reason',label='归属说明（可选）',component='textarea')],
            completion='仅确认已选择流水的交易月份；目标期间接续仍需明确确认。',
            effects=[f'记录 {target} 归属，从本期流水发生额排除','目标期间可按原始来源接续'],
            not_effects=common+['不复制流水、不自动创建期间、不计作原件核实或账务可用'])
    elif task['kind'] == 'PARSE':
        option.update(id='parse' if task['action'] == 'parse' else 'supplement',
                      label='识别当前资料' if task['action'] == 'parse' else '提供可识别的原始导出',
                      completion='原件成功识别后，返回列表核对新的提取结果。',
                      effects=['进入原有识别流程，成功后检查新的提取结果'] if task['action'] == 'parse' else ['追加保存补充资料，等待对应检查'],
                      not_effects=['不覆盖原始文件或历史版本', '不自动人工核实，不直接解除期初或凭证门禁'])
    options = [option]
    if task['kind'] != 'VERIFY':
        options.append(dict(id='defer_material_issue', label='暂无法确认' if task['kind'] in {'BILL', 'BILL_ACCOUNT', 'INVOICE_AMOUNT'} or bank or task.get('bank_period') else '暂无法补充',
                            submit_label='记录原因并继续',
                            fields=[dict(name='reason', label='原因', component='textarea', required=True)], requires=requires,
                            completion='填写当前无法处理的原因，责任人取当前登录用户。',
                            effects=['保存暂缓原因，退出当前可执行待办'],
                            not_effects=['问题及原始异常继续保留', '不增加资料核实或账务可用成果']))
    if option['id'] not in {'supplement', 'parse', 'verify_source_values'}:
        options.append(dict(id='supplement', label='补充资料（可选）', requires=requires,
                            completion='补充资料后仍须通过对应检查。', effects=['追加保存补充资料'], not_effects=common))
    from app.action_types import decorate_option
    for item in options:
        item['steps'] = OPTION_STEPS.get(item['id'], [])
        item.update(OPTION_EXECUTION[item['id']])
        if item['id'] == 'confirm_bank_period':
            target = task.get('bank_period', {}).get('target_period', '目标期间')
            item['confirmation_label'] = f'确认所选流水归属 {target}'
            item['success_label'] = f'所选流水已确认归属 {target}'
        item.update(decorate_option(item['id'], item.get('effects', [])))
    binding = dict(scope.model_dump(), artifact={'id': artifact['object_id'], 'version': artifact['version'], 'sha256': artifact['data'].get('sha256')},
                   records=[dict(id=r['object_id'], version=r['version'], source_anchor=r.get('source_anchor')) for r in records])
    rule = task['reason'].replace('bank_account_ref：', '所属银行：', 1)
    stage = 'SYSTEM_REVIEW' if task['kind'] == 'PARSE' else ('SOURCE_REVIEW' if task['kind'] == 'VERIFY' else 'BUSINESS_REVIEW')
    result = TaskDescriptor(stage=stage, why_now=advice, title=title, why={'facts': facts_summary, 'rule': rule,
                          'recommendation': advice, 'origin': 'RULE', 'evidence': binding['records']}, scope=binding,
                          options=options, presentation=issue_presentation(task, scope, artifact, records, bank)).model_dump()
    result['fingerprint'] = descriptor_fingerprint(task['id'], task.get('deferred', False), result)
    return result


def descriptor_fingerprint(task_id: str, deferred: bool, descriptor: dict[str, Any]) -> str:
    """Hash a descriptor without recursively binding the previous fingerprint."""
    projected = {**descriptor, 'fingerprint': ''}
    return digest({'task_id': task_id, 'deferred': deferred, 'descriptor': projected})


def attach_fallback_actions(task: dict[str, Any]) -> None:
    """Add only catalog projections to a safely bound unknown projected task."""
    from app.action_types import fallback_option_descriptors

    descriptor = task.get('descriptor') or {}
    if descriptor.get('version') != 'decision-v2':
        return
    existing = {item.get('id') for item in descriptor.get('options', [])}
    descriptor['options'].extend(
        item for item in fallback_option_descriptors() if item['id'] not in existing
    )
    descriptor['fingerprint'] = descriptor_fingerprint(
        task['id'], task.get('deferred', False), descriptor
    )
    TaskDescriptor.model_validate(descriptor)
