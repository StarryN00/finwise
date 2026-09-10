"""Read-only routing: a rule signal is not automatically a human decision.

No exception is removed here. Routing never grants verification/accounting
eligibility or changes the existing command contract.
"""
VERSION = 'issue-triage-v1'
STATUS_ISSUE = '发票状态：发票状态须人工核对'
BUSINESS_CODES = {
    'AMOUNT_CANCELLATION_MISMATCH': '请核对关联红票是否齐全，是否存在部分红冲或尚未提供的其他红票。',
    'PARTY_MISMATCH': '请核对这些明确关联的蓝红票为何购销双方不一致，是否关联了错误的发票。',
    'CURRENCY_MISMATCH': '请核对关联蓝红票的币种为何不同，不能跨币种抵消。',
    'PERIOD_MISMATCH': '请核对红冲发生期间及原业务期间，确认是否属于跨期红冲。',
    'RED_EVIDENCE_MISSING': '请确认对应红票是否已提供，或本次是否只提供了已红冲蓝票的清单。',
}


def classify_task(task, rows, checks, source_valid):
    """Require identifiable evidence, a concrete question and a declared action."""
    descriptor=task.get('descriptor') or {}
    presentation=descriptor.get('presentation') or {}
    title=presentation.get('type_label') or task.get('title') or '问题待判定'
    focused={r['id']:set(r.get('focus_fields',[])) for r in presentation.get('records',[])}
    options={o['id'] for o in descriptor.get('options',[]) if o.get('available')}
    comparisons=[c for r in rows for c in r.get('comparison',[])
                 if c.get('field') in focused.get(r['object_id'],set())]
    codes={code for check in checks for code in check.get('codes',[])}
    result={'version':VERSION,'route':'SYSTEM','title':title,'human_ready':False,
            'explanation':'系统尚未形成可交给用户判断的具体问题；当前提醒保留，不代表业务错误。',
            'next_action':'由系统维护人员检查原件、字段映射和校验规则；此处可以查看来源，继续处理其他业务事项。',
            'questions':[],'checks':checks,'blocking_retained':True}
    def human(explanation, questions):
        # A read-only classification cannot invent a business command.
        if not any(o.get('available') for o in descriptor.get('options',[])):
            result.update(explanation=explanation+' 当前没有可执行的办理选项，需先检查处理能力。')
            return result
        result.update(route='HUMAN',human_ready=True,explanation=explanation,
                      questions=questions,next_action=questions[0])
        return result
    if not source_valid:
        result.update(explanation='原件已失效、不可读取或哈希不一致，系统不能用当前提取结果判断业务。')
        return result
    if task.get('kind')=='PARSE':
        result.update(title='资料识别待检查',explanation='本份资料尚未形成可用的提取结果，需先检查格式支持、识别状态或失败原因；这不是客户缺资料的结论。')
        return result
    if not rows or len(rows)!=len(set(task.get('record_ids',[]))) or any(not r.get('source_anchor',{}).get('region') for r in rows):
        result.update(explanation='问题记录或来源定位不完整，需先定位原件中的具体数据，不能要求用户确认一个未定位的问题。')
        return result
    ownership_fields={'bank_account_ref','bank_name','account_number','holder'} if 'confirm_statement_account' in options else set()
    if any(c.get('state') in {'DIFFERENT','AMBIGUOUS'} or
           c.get('state')=='UNLOCATED' and c.get('field') not in ownership_fields for c in comparisons):
        result.update(explanation='问题字段的原值、提取值或来源定位尚未核对一致；先检查系统识别，不要求用户替系统确认提取错误。')
        return result
    if task.get('reason')==STATUS_ISSUE:
        result['title']='红蓝发票关联检查'
        if codes- BUSINESS_CODES.keys():
            result['explanation']='；'.join(dict.fromkeys(c.get('message','证据检查未完成') for c in checks if c.get('status')!='PASS'))
            uncertain_links={'RED_EVIDENCE_MISSING','RED_EVIDENCE_INVALID','LINK_SOURCE_ANCHOR_MISSING',
                             'SCOPE_MISMATCH','DIRECTION_MISMATCH','SOURCE_INVALID','FACT_NOT_CURRENT'}
            if not codes & uncertain_links and checks and all(c.get('links') and c.get('balances') and all(b.get('status')=='PASS' for b in c['balances']) for c in checks):
                result['explanation']='已找到明确关联的红票，不含税金额、税额和价税合计算术抵消均为零。'+result['explanation']
            result['explanation']+='。红冲状态本身不要求人工确认；先补齐系统证据链，不代表客户必须补充文件。'
            return result
        if codes:
            return human('；'.join(dict.fromkeys(c.get('message','') for c in checks if c.get('status')!='PASS')),
                         [BUSINESS_CODES[c] for c in sorted(codes)])
        result.update(explanation='“已红冲”是检查线索，不是业务错误。系统尚需完成关联红票、金额、税额及来源校验，不要求你再次确认红冲状态。')
        return result
    if task.get('kind')=='BILL_ACCOUNT':
        return human('票据业务归属已有确认，但拟用或历史科目尚未满足当前账套的科目依据；这不是解析错误。',
                     ['请查看已有确认及科目来源，核对当前账套适用科目；如需变更，沿用原有撤销后重新确认流程，不直接创建科目或制证。'])
    if task.get('kind')=='BILL' and any((r.get('bill_confirmation') or {}).get('status')=='OPINION' for r in rows):
        return human('已有处理意见，但实际业务归属尚未明确；需要补充的是业务判断，不是检查字段映射。',
                     ['请查看已有意见，取得明确业务依据后，通过原有撤销入口撤销意见再重新确认；当前不能重复提交确认。'])
    if 'confirm_bill_business' in options:
        return human('票据号码和出票信息不能说明企业实际何时收到、持有或背书；需要补充的是业务事实，不一定是新文件。',
                     ['请确认实际业务性质、所属期间及拟用科目；日期不详可只确认月份。'])
    if 'confirm_statement_account' in options:
        return human('本份流水尚未明确关联到企业银行账户，已有交易金额不因此认定错误。',
                     ['请确认这份流水属于企业的哪个银行账户；账号可选，不凭文件名生成账号。'])
    reason=task.get('reason','')
    if reason.startswith('业务期间：') and any(c.get('field') in {'transaction_date','invoice_date','period'} and c.get('state') in {'DIRECT_MATCH','NORMALIZED_MATCH','DERIVED'} and c.get('value') for c in comparisons):
        return human(presentation.get('explanation') or '原件日期与当前办理期间不同，需明确实际业务归属。',
                     ['请核对清单所列日期是否为实际业务日期，以及这些记录应归属哪个期间；不能直接改成本期。'])
    if 'confirm_invoice_amount' in options:
        return human('负数或零金额本身不代表错误，但现有证据尚未说明这条记录的实际业务原因。',
                     ['请确认本条记录属于退货、折让、红冲还是其他业务；有原件明确依据时优先检查该依据。'])
    if (reason.startswith('开票日期：') and all((r.get('values') or {}).get('invoice_no') for r in rows)
            and comparisons and all(c.get('field')=='invoice_date' and c.get('state')=='MISSING'
                                    and c.get('region') and c.get('source_value') in (None,'') for c in comparisons)):
        return human('已定位到具体发票；原件对应的开票日期单元格为空，不是日期格式转换失败。',
                     ['请核对该发票原件的开票日期，提供已有日期依据或正确版本；不按文件名猜测日期。'])
    if task.get('kind')=='VERIFY':
        return human('系统检查已通过，尚未有人核实原件与提取值。', ['只核实当前已查看的原件与提取值，不代表账务可用。'])
    # Missing/invalid fields and unknown rules are system checks until the system
    # can demonstrate both a real evidence gap and a specific supported remedy.
    if comparisons:
        result['explanation']='当前提醒涉及的字段尚不能满足检查条件；需先区分原件为空、提取遗漏或格式解释错误。不能直接认定客户缺资料。'
    return result
