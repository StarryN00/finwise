"""Source-declared red invoice checks; not tax authentication or ledger approval."""
import re
from decimal import Decimal, InvalidOperation

RULE_VERSION = 'red-invoice-source-v1'
AMOUNT_ISSUE = 'invoice_total：红字或零金额发票须人工核对'
BLUE_LABEL = '被红冲蓝字数电发票号码'
CONFIRM_LABEL = '红字发票信息确认单编号'


def red_invoice_evidence(data):
    if data.get('record_type') not in {'INVOICE', 'SALES_INVOICE'}:
        return None
    n = data.get('normalized_value', {})
    try:
        total, net, tax = (Decimal(n[k]) for k in ('invoice_total', 'net_amount', 'tax'))
        if (not all(x.is_finite() for x in (total, net, tax)) or total >= 0
                or net >= 0 or tax > 0 or total != net + tax):
            return None
    except (KeyError, TypeError, InvalidOperation):
        return None
    if n.get('invoice_status') not in {'正常', '有效'}:
        return None
    if not re.fullmatch(r'\d{20}', str(n.get('invoice_no', ''))):
        return None
    original = data.get('original_value', {})
    # Any formula requires its own verification, even if a cache looks valid.
    if original.get('formulas'):
        return None
    values, headers = original.get('values', []), original.get('headers', [])
    identifiers = {BLUE_LABEL: set(), CONFIRM_LABEL: set()}
    regions = []
    for i, header in enumerate(headers):
        value = values[i] if i < len(values) else None
        label = str(header or '').strip()
        if label == '是否正数发票' and str(value or '').strip() != '否':
            return None
        if label == '发票风险等级' and str(value or '').strip() != '正常':
            return None
        if label in identifiers and value not in (None, '') and not isinstance(value, str):
            return None
        if label not in {'备注', '发票备注', BLUE_LABEL, CONFIRM_LABEL} or not isinstance(value, str):
            continue
        text = f'{label}：{value}' if label in identifiers else value
        found = False
        for key in identifiers:
            if key not in text:
                continue
            matches = re.findall(re.escape(key) + r'\s*[:：]\s*(\d{20})(?![\dA-Za-z])', text)
            if not matches or len(matches) != text.count(key):
                return None
            identifiers[key].update(matches)
            found = True
        if found:
            from app.tabular import column_name
            regions.append(f"{original.get('sheet', '')}!{column_name(i+1)}{original.get('row', '')}")
    if any(len(v) != 1 for v in identifiers.values()):
        return None
    blue = next(iter(identifiers[BLUE_LABEL]))
    if blue == n['invoice_no']:
        return None
    return {'rule_version': RULE_VERSION, 'status': 'PASS', 'blue_invoice_no': blue,
            'confirmation_no': next(iter(identifiers[CONFIRM_LABEL])), 'source_regions': regions,
            'message': '原件注明红冲蓝字发票及红字确认单，负数金额关系一致；无需重复说明负数原因。',
            'boundary': '仅取消负数人工提醒，不代表税务查验、人工核实或账务可用。'}
