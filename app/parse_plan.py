"""Versioned, source-bound structure plans. Models propose pointers, never values."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.tabular import (BANK_FIELDS, INVOICE_FIELDS, read_workbook,
    extract_row, header_mapping, bank_footer_header, bank_footer_values, column_name, date_value)

VERSION = 'structure-plan-v1'
EXECUTOR_VERSION = 'plan-executor-v1'
KINDS = {'bank_statement', 'purchase_invoices', 'sales_invoices'}


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReferenceRow(Closed):
    row: StrictInt = Field(ge=1, le=20000)
    role: Literal['TOTAL', 'HEADER', 'NOTE']


class SheetPlan(Closed):
    sheet_index: StrictInt = Field(ge=0, le=49)
    role: Literal['DATA', 'REFERENCE', 'UNKNOWN']
    header_row: StrictInt = Field(ge=0, le=20000)
    fields: dict[StrictStr, StrictStr]
    reference_rows: list[ReferenceRow] = Field(default_factory=list, max_length=100)


class DataSheetPlan(SheetPlan):
    role: Literal['DATA']
    header_row: StrictInt = Field(ge=1, le=20000)


class ReferenceSheetPlan(SheetPlan):
    role: Literal['REFERENCE', 'UNKNOWN']
    header_row: Literal[0]
    fields: dict[StrictStr, StrictStr] = Field(max_length=0)
    reference_rows: list[ReferenceRow] = Field(default_factory=list, max_length=0)


class Proposal(Closed):
    schema_version: Literal['structure-plan-v1']
    outcome: Literal['PLAN', 'ABSTAIN']
    sheets: list[Union[DataSheetPlan, ReferenceSheetPlan]] = Field(max_length=10)


def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).rstrip(':：')


def fields_for(kind):
    return BANK_FIELDS if kind == 'bank_statement' else INVOICE_FIELDS


def source_guards(sheets):
    """Reject unsupported scales/layouts locally, before any model transmission."""
    issues = []
    for sheet in sheets:
        if (sheet.get('hidden') or sheet.get('sheet_state','visible')!='visible'
                or sheet.get('hidden_rows') or sheet.get('hidden_columns')):
            issues.append({'sheet': sheet['name'], 'row': 0,
                           'reason': '原件含隐藏工作表、行或列，当前结构解析不支持；未忽略隐藏内容'})
        for row in sheet['rows']:
            for i, value in enumerate(row['values']):
                if not isinstance(value, str):
                    continue
                text = normalized(value)
                if text in {'单位','金额单位','币种','货币','币别'}:
                    adjacent=next((normalized(v) for v in row['values'][i+1:i+5] if v not in (None,'')), '')
                    bad_unit=bool(re.fullmatch(r'(?:人民币)?(?:百万元|万元|千元|亿元)',adjacent))
                    bad_currency=text in {'币种','货币','币别'} and adjacent not in {'人民币','CNY','RMB','人民币元'}
                    if bad_unit or bad_currency:
                        issues.append({'sheet':sheet['name'],'row':row['row'],
                                       'region':f"{sheet['name']}!{column_name(i+1)}{row['row']}",
                                       'reason':'相邻单元格声明非人民币元或未支持币种，不能按元直接读取'})
                # A unit in a header is a scale declaration, not a conversion.
                scale = re.search(r'(?:单位[:：]?|(?:金额|收入|支出|余额|借方|贷方|税额|单价|合计)[（(]?)(?:人民币)?(?:百万元|万元|千元|亿元)', text)
                currency = re.search(r'(?:币种|货币)[:：]?([^\s,，;；]+)', text)
                if scale or (currency and currency.group(1) not in {'人民币', 'CNY', 'RMB', '人民币元'}):
                    issues.append({'sheet': sheet['name'], 'row': row['row'],
                                   'region': f"{sheet['name']}!{column_name(i+1)}{row['row']}",
                                   'reason': '原件声明非人民币元或未支持币种，不能按元直接读取', 'value': value})
    return issues


def meaningful(row):
    return any(v not in (None,'') for v in row['values']) or bool(row.get('formulas'))


def column_index(value):
    if not re.fullmatch('[A-Z]{1,2}', value):
        raise ValueError('字段列定位无效')
    result = 0
    for char in value:
        result = result * 26 + ord(char) - 64
    return result - 1


def header_values(sheet, row):
    values = list(row['values'])
    # Parent labels are local source strings, never model-supplied values.
    for c1, r1, c2, r2 in sheet.get('merged_cells', []):
        if r1 <= row['row'] <= r2:
            anchor = next((r for r in sheet['rows'] if r['row'] == r1), None)
            if anchor and c1 <= len(anchor['values']):
                while len(values) < c2: values.append(None)
                for c in range(c1 - 1, c2):
                    if values[c] in (None, ''): values[c] = anchor['values'][c1 - 1]
    return values


def builtin(sheets, kind):
    plans = []
    base_invoice = kind != 'bank_statement' and any(s['name'] == '发票基础信息' for s in sheets)
    for index, sheet in enumerate(sheets):
        candidates = [(r, header_mapping(header_values(sheet, r), kind)) for r in sheet['rows']]
        found = next(((r, m) for r, m in candidates if m), None)
        if base_invoice and sheet['name'] == '信息汇总表':
            plans.append(dict(sheet_index=index, role='REFERENCE', header_row=0, fields={}))
        elif found:
            r, mapping = found
            plans.append(dict(sheet_index=index, role='DATA', header_row=r['row'],
                              fields={k:column_name(v[0]+1) for k,v in mapping.items() if v}))
        else:
            plans.append(dict(sheet_index=index, role='UNKNOWN' if any(meaningful(r) for r in sheet['rows']) else 'REFERENCE', header_row=0, fields={}))
    return Proposal.model_validate(dict(schema_version=VERSION, outcome='PLAN', sheets=plans))


def packet(sheets, kind):
    """No filenames, sheet names, identities, raw amounts, dates or account numbers."""
    if source_guards(sheets):
        raise ValueError('原件包含当前未支持的单位、币种或隐藏结构，未发送模型；请查看本地结构预览')
    aliases = {normalized(a) for table in (BANK_FIELDS, INVOICE_FIELDS) for values in table.values() for a in values}
    aliases |= {'合计','合计行','总计','总收入笔数','总收入金额','总支出笔数','总支出金额','序号','人民币','单位元',
                '数量','单价','规格型号','税收分类编码','货物或应税劳务名称','发票代码','单位'}
    def safe(value):
        text = normalized(value)
        if not text: return {'type':'BLANK'}
        if text in aliases: return {'type':'HEADER','text':text}
        if re.fullmatch(r'-?\d+(\.\d+)?', text): return {'type':'NUMBER','zero':float(text)==0,'negative':text.startswith('-')}
        if re.match(r'^\d{4}[-/年.]\d',text): return {'type':'DATE'}
        # Nonstandard labels may combine financial vocabulary, not identity text.
        if re.fullmatch(r'(?:交易|记账|发生|入账|凭证|开票|收款|付款|流入|流出|收入|支出|税前|税后|含税|不含税|本期|期末|期初|借方|贷方|结余|余额|日期|时点|时间|金额|税额|数额|数|合计|净额|人民币|元|英文|Date|Amount|Debit|Credit|Balance|Income|Expense|_)+',text):
            return {'type':'HEADER','text':text}
        return {'type':'TEXT'}
    output=[]
    for index,s in enumerate(sheets):
        rows=[r for r in s['rows'] if meaningful(r)]
        chosen={r['row']:r for r in rows[:20]+rows[-15:]}
        shapes={}
        for r in rows:
            shape=tuple(safe(v)['type'] for v in r['values'])
            shapes.setdefault(shape,r)
        for r in list(shapes.values())[:30]: chosen[r['row']]=r
        width=max((len(r['values']) for r in rows),default=0)
        profiles={}
        for col in range(width):
            values=[r['values'][col] for r in rows if col<len(r['values']) and r['values'][col] not in (None,'')]
            profiles[column_name(col+1)]={'nonempty_count':len(values),
                                         'distinct_count':len({str(v) for v in values})}
        # Canonical export roles, never arbitrary workbook/sheet names.
        role_hint = ({'发票基础信息':'INVOICE_HEADERS','信息汇总表':'INVOICE_LINE_ITEMS'}.get(s['name'])
                     if kind!='bank_statement' else None)
        output.append({'sheet_index':index,'total_rows':len(rows),'column_profiles':profiles,'role_hint':role_hint,
                       'rows':[{'row':r['row'],'cells':{column_name(i+1):
                           ({'type':'FORMULA','cached':v is not None} if f"{column_name(i+1)}{r['row']}" in r.get('formulas',{}) else safe(v))
                           for i,v in enumerate(r['values'])}} for r in sorted(chosen.values(),key=lambda x:x['row'])]})
    result={'document_kind':kind,'allowed_fields':list(fields_for(kind)), 'sheets':output,
            'schema':Proposal.model_json_schema()}
    if len(sheets)>10 or len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode())>60000:
        raise ValueError('结构样本超过安全预算，请分表处理；未发送模型')
    return result


def execute(content, raw_plan, kind, period, bank_account_ref=None):
    if kind not in KINDS: raise ValueError('此资料类型尚未接入结构方案')
    plan=Proposal.model_validate(raw_plan)
    sheets=read_workbook(content)
    if plan.outcome!='PLAN': raise ValueError('尚未形成可执行方案，请人工指认结构')
    if sorted(s.sheet_index for s in plan.sheets)!=list(range(len(sheets))):
        raise ValueError('方案必须逐一覆盖全部工作表')
    result={'records':[],'sheets':[],'errors':[],'unresolved_rows':source_guards(sheets)}
    all_identities={}
    for spec in plan.sheets:
        sheet=sheets[spec.sheet_index]
        rows=[r for r in sheet['rows'] if meaningful(r)]
        refs=[]; count=0
        if spec.role!='DATA':
            if spec.fields or spec.header_row: raise ValueError('参考或未知工作表不能同时声明取值字段')
            if spec.role=='UNKNOWN':
                result['unresolved_rows'].append({'sheet':sheet['name'],'row':0,'reason':'工作表用途未确定'})
            result['sheets'].append({'sheet':sheet['name'],'status':spec.role,'rows':0,'reference_rows':[{'row':r['row'],'reason':'SHEET_REFERENCE','values':r['values']} for r in rows]})
            continue
        header=next((r for r in rows if r['row']==spec.header_row),None)
        if not header: raise ValueError('表头定位不存在')
        headers=header_values(sheet,header)
        mapping={k:[] for k in fields_for(kind)}
        if len(set(spec.fields.values()))!=len(spec.fields): raise ValueError('同一列不能重复绑定字段')
        for field,col in spec.fields.items():
            if field not in mapping: raise ValueError('方案包含未知目标字段')
            i=column_index(col)
            if i>=len(headers) or headers[i] in (None,''): raise ValueError('映射列没有原始表头依据')
            mapping[field]=[i]
        required=['transaction_date'] if kind=='bank_statement' else ['invoice_no','invoice_date','net_amount','tax']
        if not all(mapping[k] for k in required) or (kind=='bank_statement' and not (mapping['income'] or mapping['expense'])):
            raise ValueError('需要指出日期、标识和金额列；不能降低必需字段')
        overrides={r.row:r.role for r in spec.reference_rows}
        if len(overrides)!=len(spec.reference_rows) or not set(overrides).issubset({r['row'] for r in rows}):
            raise ValueError('参考行定位不存在或重复')
        footer=None
        for row in rows:
            n=row['row']; values=row['values']
            role=None
            if n<=spec.header_row:
                role='HEADER'
                if n<spec.header_row:
                    date_field='transaction_date' if kind=='bank_statement' else 'invoice_date'
                    for i in mapping[date_field]:
                        try:
                            date_value(values[i] if i<len(values) else None)
                        except ValueError:
                            continue
                        role='PRE_HEADER_UNRESOLVED'
                        result['unresolved_rows'].append({'sheet':sheet['name'],'row':n,
                            'reason':'所选表头之前存在可解析日期的数据行，请核对是否遗漏前段明细','values':values})
            elif [normalized(v) for v in values]==[normalized(v) for v in header['values']]: role='REPEATED_HEADER'
            elif kind=='bank_statement' and bank_footer_header(values): role='BANK_TOTAL_HEADER';footer=n
            elif footer is not None and n==footer+1 and bank_footer_values(values): role='BANK_TOTAL_VALUES'
            elif normalized(next((v for v in values if v not in (None,'')),'')) in {'合计','合计行','总计','小计','本页合计'}:
                identity=['transaction_date'] if kind=='bank_statement' else ['invoice_no','invoice_date']
                if all(i>=len(values) or values[i] in (None,'') or normalized(values[i]) in {'合计','合计行','总计','小计','本页合计'} for k in identity for i in mapping[k]): role='SUMMARY_REFERENCE'
            if role is None and n in overrides: role='PLAN_'+overrides[n]
            if role:
                refs.append({'row':n,'reason':role,'values':values});continue
            record=extract_row(sheet['name'],row,headers,mapping,kind,period,bank_account_ref)
            record['plan_provenance']={'sheet_index':spec.sheet_index,'header_row':spec.header_row,'fields':spec.fields,'executor_version':EXECUTOR_VERSION}
            # Keep questionable source rows visible. Never synthesize missing values.
            fatal=any(any(word in issue for word in ('日期缺失','金额格式','来源缺失','金额缺失','方向不明确')) for issue in record['extraction_issues'])
            fatal = fatal or any('公式' in issue for issue in record['extraction_issues'])
            if fatal: result['unresolved_rows'].append({'sheet':sheet['name'],'row':n,'reason':'原始行的身份或取值需要核对','values':values})
            if kind!='bank_statement':
                identity=record['normalized_value'].get('invoice_no')
                if identity:
                    if identity in all_identities:
                        result['unresolved_rows'].append({'sheet':sheet['name'],'row':n,'reason':'同一发票重复出现，需确认主表与明细关系'})
                    all_identities[identity]=n
            result['records'].append(record);count+=1
        result['sheets'].append({'sheet':sheet['name'],'status':'EXTRACTED','rows':count,'header_row':spec.header_row,'reference_rows':refs})
    if not result['records']: result['errors'].append('尚未提取可定位业务记录')
    from app.reconcile import reconcile
    result['checks']=reconcile(result,kind)
    result['apply_ready']=bool(result['records']) and not result['unresolved_rows'] and result['checks']['overall']!='REVIEW'
    return result


def signature(sheets, plan):
    """No row counts or fixed tail; every reuse executes on the full new source."""
    rows=[]
    for spec in Proposal.model_validate(plan).sheets:
        s=sheets[spec.sheet_index]
        h=next((r for r in s['rows'] if r['row']==spec.header_row),None)
        rows.append([spec.sheet_index,spec.role,[normalized(x) for x in header_values(s,h)] if h else None,spec.fields])
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
