"""AI proposes payroll column semantics; local code alone reads source values."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import logging
import re
import threading
import time
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from app.db import utcnow
from app.ontology.contracts import Scope
from app.ontology.errors import PreconditionFailed
from app.ontology.gateway import GatewayFailure
from app.ontology.store import digest, scope_key
from app.tabular import (GENERIC_FIELDS, ExtractionError, column_name, read_workbook,
                         extract_generic_row, payroll_period_source)

VERSION = 'payroll-mapping-v1'
TYPE = 'PayrollMapping'
FIELDS = tuple(GENERIC_FIELDS['payroll'])
# A vocabulary, not a column mapping. Only these semantic tokens leave the host.
WORDS = sorted(set(('姓名 员工 职工 人员 工号 名称 基本 工资 薪资 薪酬 底薪 实发 实付 应发 应付 '
                    '收入 奖金 绩效 岗位 津贴 补贴 加班 扣款 应扣 个人 公司 单位 企业 承担 缴 纳 '
                    '社保 社会保险 养老 医疗 失业 公积金 住房 个税 所得税 税额 合计 总计 小计 '
                    '备注 说明 注 入职 上班 调薪 涨薪 调 月 年 期间 月份 所属 发放 银行 账号 '
                    '出勤 应出 实出 天数 餐费 带薪假 代扣 减免 salary payroll employee name basic net gross tax pension').split()),key=len,reverse=True)
WORD_RE = re.compile('|'.join(map(re.escape,WORDS)),re.I)


class SheetMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sheet_index: StrictInt = Field(ge=0,le=9)
    header_rows: list[StrictInt] = Field(min_length=1,max_length=4)
    fields: dict[StrictStr,Optional[StrictStr]]
    period_cell: Optional[StrictStr] = None
    row_mode: Literal['table','slips'] = 'table'


class MappingProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sheets: list[SheetMapping] = Field(min_length=1,max_length=10)
    confidence: float = Field(ge=0,le=1)


def col_index(label):
    if not isinstance(label,str) or not re.fullmatch('[A-Z]{1,2}',label):
        raise ExtractionError('字段列定位无效')
    n=0
    for c in label:n=n*26+ord(c)-64
    return n-1


def safe_value(value):
    if value in (None,''):return ''
    if isinstance(value,(int,float)):return '<NUMBER>'
    text=str(value)
    # Never transmit original strings, amounts, names, IDs, paths or formula text.
    words=WORD_RE.findall(text)
    return ' '.join(w.lower() for w in words)[:160] if words else '<TEXT>'


def bounded_sheets(content):
    sheets=read_workbook(content)
    if len(sheets)>10 or any(len(s['rows'])>1000 or max((len(r['values']) for r in s['rows']),default=0)>80 for s in sheets):
        raise ExtractionError('AI 工资表适配暂支持最多10个工作表、每表1000行80列，请拆分后处理')
    return sheets


def structure_packet(sheets):
    result=[]
    for i,s in enumerate(sheets):
        # Structure only: no employee rows or monetary samples are needed for mapping.
        rows=[{'row':r['row'],'cells':{column_name(c+1):safe_value(v) for c,v in enumerate(r['values']) if v not in (None,'')}} for r in s['rows'][:40]]
        result.append({'sheet_index':i,'rows':rows,'total_rows':len(s['rows']), 'merged_cells':[m for m in s.get('merged_cells',[]) if m[1]<=40]})
    packet={'schema_version':VERSION,'allowed_fields':list(FIELDS),'sheets':result}
    if len(str(packet))>45000:raise ExtractionError('表头结构过大，请拆分工资表')
    return packet


def header_values(sheet,rows):
    width=max((len(r['values']) for r in sheet['rows']),default=0)
    values=[]
    for col in range(1,width+1):
        parts=[]
        for row in rows:
            r,c=row,col
            for c1,r1,c2,r2 in sheet.get('merged_cells',[]):
                if c1<=c<=c2 and r1<=r<=r2:r,c=r1,c1;break
            raw=sheet['rows'][r-1]['values']
            v=raw[c-1] if c<=len(raw) else None
            if v not in (None,'') and str(v) not in parts:parts.append(str(v))
        values.append(' / '.join(parts))
    return values


def primary_blocks(sheet, item):
    """Locate repeated headers using two independent source anchors, not amounts."""
    rows=item['header_rows']
    anchors=[col_index(item['fields'][f]) for f in ('person_name','actual_salary')]
    clean=lambda v:re.sub(r'\s+','',str(v or ''))
    # Some two-row headers put anchors in a merged cell; use merged values.
    first_headers=header_values(sheet,[rows[0]])
    if any(not first_headers[c] for c in anchors):return [rows]
    blocks=[]
    for r in sheet['rows']:
        if r['row']+max(rows)-min(rows)>len(sheet['rows']):continue
        if blocks and r['row']<=max(blocks[-1]):continue
        if any(r1<r['row']<=r2 and any(c1<=c+1<=c2 for c in anchors) for c1,r1,c2,r2 in sheet.get('merged_cells',[])):continue
        values=header_values(sheet,[r['row']])
        if all(clean(values[c])==clean(first_headers[c]) for c in anchors):
            blocks.append([r['row']+n-rows[0] for n in rows])
    return blocks


def validated_proposal(raw,sheets):
    try:p=MappingProposal.model_validate(raw).model_dump()
    except ValidationError as exc:raise ExtractionError('模型字段方案不符合约定，请重新识别或核对格式') from exc
    populated={i for i,s in enumerate(sheets) if any(r['formulas'] or any(v not in (None,'') for v in r['values']) for r in s['rows'])}
    if {s['sheet_index'] for s in p['sheets']}!=populated or len(p['sheets'])!=len(populated):
        raise ExtractionError('方案必须覆盖全部非空工作表，不能遗漏或重复')
    for item in p['sheets']:
        s=sheets[item['sheet_index']];rs=item['header_rows']
        if rs!=list(range(min(rs),max(rs)+1)) or min(rs)<1 or max(rs)>min(40,len(s['rows'])):
            raise ExtractionError('表头定位越界或重复')
        if set(item['fields'])-set(FIELDS):raise ExtractionError('模型返回了不支持的系统字段')
        headers=header_values(s,rs)
        cols=[v for v in item['fields'].values() if v]
        if len(set(cols))!=len(cols):raise ExtractionError('同一原列不能同时映射多个系统字段')
        if not item['fields'].get('person_name') or not item['fields'].get('actual_salary'):
            raise ExtractionError('必须明确姓名和实发工资列；不能用应发工资替代实发工资')
        for col in cols:
            idx=col_index(col)
            if idx>=len(headers) or not headers[idx]:raise ExtractionError('字段指向空白或不存在的表头')
        # Unit evidence can be a title or a separate column, not only the salary header.
        if any(re.search(r'万元|千元|万人民币|千人民币',str(v or '')) for r in s['rows'] for v in r['values']):
            raise ExtractionError('原表存在非元金额单位，当前适配不自动换算，请核对金额单位')
        for r in s['rows']:
            for v in r['values']:
                text=str(v or '')
                for label,unit in re.findall(r'(金额单位|币种|单位)\s*[:：]\s*([^\s，,；;）)]+)',text):
                    if label=='单位' and unit.endswith(('公司','单位','企业','事务所','中心','合作社')):continue
                    if unit not in {'元','人民币','人民币元','CNY','RMB','￥','¥'}:
                        raise ExtractionError('原表明确的金额单位或币种不是人民币元，请核对后处理')
            for index,v in enumerate(r['values'][:-1]):
                if re.fullmatch(r'(?:金额单位|币种|单位)\s*[:：]?',str(v or '').strip()):
                    unit=str(r['values'][index+1] or '').strip()
                    if str(v).strip().rstrip('：:')=='单位' and unit.endswith(('公司','单位','企业','事务所','中心','合作社')):continue
                    if unit and unit not in {'元','人民币','人民币元','CNY','RMB','￥','¥'}:raise ExtractionError('独立单位单元格不是人民币元，请核对后处理')
        blocks=primary_blocks(s,item)
        compact=lambda value:re.sub(r'\s+','',str(value or '')).lower()
        names={compact(headers[col_index(item['fields']['person_name'])]),'姓名','员工','职工','人员','employee','name'}
        for row in s['rows']:
            cells=[compact(v) for v in row['values'] if v not in (None,'')]
            if any(v in names for v in cells) and any(re.search(r'实发|实付|应发|net.?salary|gross.?salary',v) for v in cells):
                if row['row'] not in {b[0] for b in blocks}:raise ExtractionError('后续疑似工资表头的锚点列发生变化，不能沿用原字段对应')
        if blocks and blocks[0][0]<rs[0]:raise ExtractionError('表头方案跳过了更早的工资表头，不能遗漏前面的员工')
        if item['row_mode']=='table' and len(blocks)>1 and any('险种' in str(v or '') for r in s['rows'] for v in r['values']):
            raise ExtractionError('检测到重复工资条及险种子表，不能按连续人员表提取，请重新识别行结构')
        if item['row_mode']=='table':
            if any(any(header_values(s,b)[col_index(c)]!=headers[col_index(c)] for c in cols) for b in blocks):
                raise ExtractionError('连续表的分段字段含义发生变化，请拆分或重新核对格式')
            periods=payroll_period_source(s,s['rows'])
            if periods.get('status')=='AMBIGUOUS':raise ExtractionError('连续表包含冲突或无法确认的期间标题，请核对分段期间')
        money_cols=[col_index(c) for f,c in item['fields'].items() if c and f!='person_name']
        for row in s['rows'][rs[0]-1:rs[-1]]:
            for c in money_cols:
                v=row['values'][c] if c<len(row['values']) else None
                if (v not in (None,'') and re.fullmatch(r'-?\d+(?:\.\d+)?',str(v))) or column_name(c+1)+str(row['row']) in row['formulas']:
                    raise ExtractionError('拟选表头包含明细金额或公式行，不能遗漏员工')
        pc,ac=(col_index(item['fields'][f]) for f in ('person_name','actual_salary'))
        for row in s['rows'][:rs[0]-1]:
            values=row['values']
            if ac<len(values) and re.fullmatch(r'-?\d+(?:\.\d+)?',str(values[ac] if values[ac] is not None else '')):
                raise ExtractionError('表头之前存在疑似员工金额行，不能作为标题排除')
        salary_header=headers[col_index(item['fields']['actual_salary'])]
        if re.search(r'应发|gross',salary_header,re.I) and not re.search(r'实发|实付|net',salary_header,re.I):
            raise ExtractionError('不能把应发工资映射为实发工资')
        if re.search('万元|千元',salary_header):raise ExtractionError('工资金额单位不是元，当前适配不自动换算')
        if sum(bool(WORD_RE.search(headers[col_index(c)])) for c in cols)<2:
            raise ExtractionError('所选行缺少可核验的工资表头语义')
        for field,col in item['fields'].items():
            if col and 'housing_fund' in field and re.search('减免|贷款|赡养',headers[col_index(col)]) and '公积金' not in headers[col_index(col)]:
                raise ExtractionError('住房扣除或个税减免不是公积金缴费，不能作为公积金字段')
        if item['period_cell']:
            match=re.fullmatch(r'([A-Z]{1,2})([1-9]\d*)',item['period_cell'])
            if not match or int(match[2])>len(s['rows']) or col_index(match[1])>=len(s['rows'][int(match[2])-1]['values']):
                raise ExtractionError('期间单元格越界')
    return p


def layout_signature(sheets,proposal):
    return digest([{'sheet_index':p['sheet_index'],'header_rows':p['header_rows'],
                    'headers':header_values(sheets[p['sheet_index']],p['header_rows']),
                    'merges':[m for m in sheets[p['sheet_index']].get('merged_cells',[]) if m[1]<=max(p['header_rows'])],
                    'width':max((len(r['values']) for r in sheets[p['sheet_index']]['rows']),default=0),
                    'repeated_headers':len(primary_blocks(sheets[p['sheet_index']],p))>1,
                    'header_variants':sorted({tuple(header_values(sheets[p['sheet_index']],b)) for b in primary_blocks(sheets[p['sheet_index']],p)}),
                    'insurance_subtable':any('险种' in str(v or '') for r in sheets[p['sheet_index']]['rows'] for v in r['values'])} for p in proposal['sheets']])


def extract_mapped(sheets,raw,period):
    proposal=validated_proposal(raw,sheets);records=[];summaries=[];excluded=[]
    for p in proposal['sheets']:
        s=sheets[p['sheet_index']];headers=header_values(s,p['header_rows'])
        mapping={k:[col_index(v)] if v else [] for k,v in p['fields'].items()}
        person_col=mapping['person_name'][0]
        salary_col=mapping['actual_salary'][0]
        # Resolve period from the current source cell, never a saved value or filename.
        period_rows=[]
        if p['period_cell']:
            m=re.fullmatch(r'([A-Z]+)(\d+)',p['period_cell']);r=s['rows'][int(m[2])-1]
            values=[None]*len(r['values']);values[col_index(m[1])]=r['values'][col_index(m[1])]
            period_rows=[{**r,'values':values}]
        ps=payroll_period_source(s,period_rows)
        context={'period_source':ps,'header_rows':[s['rows'][n-1] for n in p['header_rows']],
                 'header_paths':{i:[{'raw_value':h}] for i,h in enumerate(headers)},'unresolved':{}}
        # Unmapped contribution semantics must remain visible, not silently become zero.
        mapped={ix for v in mapping.values() for ix in v}
        for i,h in enumerate(headers):
            if i not in mapped and re.search('社保|公积金|社会保险|养老|医疗',h):context['unresolved'][i]='缴费字段尚未归类，请核对单位与个人承担部分'
        count=0
        header_patterns=[s['rows'][n-1]['values'] for n in p['header_rows']]
        clean=lambda vs:[re.sub(r'\s+','',str(v or '')) for v in vs]
        patterns=[clean(vs) for vs in header_patterns]
        slip_data=set();slip_headers=set();auxiliary=set();blocks=primary_blocks(s,p)
        if p['row_mode']=='slips':
            if p['header_rows']!=list(range(min(p['header_rows']),max(p['header_rows'])+1)):
                raise ExtractionError('工资条表头必须连续')
            for block in blocks:
                slip_headers.update(block);slip_data.add(max(block)+1)
            if not slip_data:raise ExtractionError('未找到重复工资条表头')
            # Only a bounded, explicitly labelled insurance subtable is excluded.
            # A blank employee cell alone is never enough to discard an amount row.
            for n in slip_data:
                if n+2>len(s['rows']):continue
                h=s['rows'][n]['values'];d=s['rows'][n+1]['values']
                labels=' '.join(re.sub(r'\s+','',str(v or '')) for v in h)
                insurance=re.compile('(?:企业|基本)?(?:养老|医疗|失业|工伤|生育|社会保险|社保)(?:保险)?')
                person=d[person_col] if person_col<len(d) else None
                if len(re.findall('单位缴|个人缴|单位承担|个人承担',labels))>=2 and any(insurance.search(str(v or '')) for v in d) and (not person or insurance.fullmatch(str(person))):
                    auxiliary.update((n+1,n+2))
        for r in s['rows']:
            vs=r['values'];num=r['row']
            if not r['formulas'] and not any(v not in (None,'') for v in vs):continue
            if num<=max(p['header_rows']):excluded.append({'sheet':s['name'],'row':num,'reason':'表头或标题'});continue
            if num in slip_headers or clean(vs) in patterns:excluded.append({'sheet':s['name'],'row':num,'reason':'重复表头'});continue
            person=str(vs[person_col] or '').strip() if person_col<len(vs) else ''
            salary=vs[salary_col] if salary_col<len(vs) else None
            if person in {'合计','总计','小计','本页合计'}:
                excluded.append({'sheet':s['name'],'row':num,'reason':'汇总行（不重复累计）'});continue
            is_note=person.startswith(('说明','备注','注：','注:','薪资')) or bool(re.match(r'^(?:20\d{2}|\d{2})[./-]\d{1,2}(?:[./-]\d{1,2})?月?\s*(?:入职|上班|调薪|涨薪|调\s*\d)',person))
            if p['row_mode']=='slips' and num not in slip_data:
                text=' '.join(str(v) for v in vs if v not in (None,''))
                identity_note=not person and salary in (None,'') and bool(re.search(r'身份证(?:号码)?|银行[：:]|账号[：:]',text))
                calculation_note=not person and salary in (None,'') and bool(re.match(r'^(?:白班|夜班|夜餐).*餐费.*=\d',text))
                period_title=any(min(b)-1==num for b in blocks) and payroll_period_source(s,[r]).get('status')=='EXPLICIT'
                if num not in auxiliary and not is_note and not identity_note and not calculation_note and not period_title:
                    raise ExtractionError(f'第 {num} 行可能为遗漏员工或变更表头，请重新核对工资条结构')
                excluded.append({'sheet':s['name'],'row':num,'reason':'已定位社保子表（不重复累计）' if num in auxiliary else '工资条标题或明确附注'});continue
            if is_note and salary in (None,'') and not r['formulas']:
                excluded.append({'sheet':s['name'],'row':num,'reason':'明确附注'});continue
            # Other rows are retained, even when identity/amount is missing or invalid.
            row_context=deepcopy(context);current_headers=headers
            if p['row_mode']=='slips':
                block=next(b for b in blocks if max(b)+1==num)
                current_headers=header_values(s,block)
                row_context['period_source']=payroll_period_source(s,s['rows'][max(0,min(block)-2):min(block)-1])
                row_context['header_paths']={i:[{'raw_value':h}] for i,h in enumerate(current_headers)}
                row_context['header_rows']=[s['rows'][n-1] for n in block]
            rec=extract_generic_row(s['name'],r,current_headers,mapping,'payroll',period,None,None,row_context)
            if p['row_mode']=='slips':
                changed=[column_name(i+1) for i in mapped if clean([current_headers[i]])!=clean([headers[i]])]
                if changed:rec['extraction_issues'].append('工资条表头与首块不同，请核对列含义：'+','.join(changed))
                if row_context['period_source'].get('value')!=ps.get('value'):
                    rec['extraction_issues'].append('工资条期间与首块不同或缺失，请核对本条期间')
                    rec['period_check']='PERIOD_EXCEPTION'
            if person==str(headers[person_col]).split(' / ')[-1]:
                rec['extraction_issues'].append('表头结构发生变化，请重新核对字段对应')
            records.append(rec);count+=1
        summaries.append({'sheet':s['name'],'rows':count,'status':'EXTRACTED'})
    if not records:raise ExtractionError('未定位到工资明细行，请核对表头范围及字段')
    duplicates={}
    for r in records:
        key=digest(r['normalized_value']);duplicates.setdefault(key,[]).append(r)
    for group in duplicates.values():
        if len(group)>1:
            for r in group:r['extraction_issues'].append('存在相同工资明细，已保留全部来源，请核对是否重复')
    for r in records:
        if r['extraction_issues']:r['extraction_confidence']=0.0
    return {'records':records,'sheets':summaries,'errors':[], 'checks':{'excluded_rows':excluded,'mapping_version':VERSION}}


class PayrollMappingService:
    def __init__(self,service):
        self.service=service;self.store=service.store;self.stop_event=threading.Event();self.thread=None

    def all_jobs(self):
        return [j for scope in self.store.list_scope_objects() for j in self.store.list_objects(TYPE,Scope(**scope['data']['scope']))]

    def authorized(self,scope,actor):
        if not self.store.database.settings.require_auth:return
        with self.store.database.connect() as connection:
            row=connection.execute('SELECT role,enabled FROM auth_users WHERE user_id=?',(actor,)).fetchone()
            grant=connection.execute('SELECT 1 FROM auth_scope_grants WHERE user_id=? AND scope_json=?',(actor,scope_key(scope))).fetchone()
        if not row or not row['enabled'] or row['role'] not in {'operator','accountant','admin'} or not grant:
            raise PreconditionFailed('发起人的范围权限已变化，请由有权用户重新识别')

    def source(self,scope,artifact_id,version=None):
        a=self.store.get_object(artifact_id,scope)
        if a['object_type']!='SourceArtifact' or a['status']!='ACTIVE' or a['data']['observed_period']!=scope.accounting_period_id:
            raise PreconditionFailed('请选择当前期间有效工资表原件')
        if version is not None and a['version']!=version:raise PreconditionFailed('原件版本已变化，请重新识别格式')
        kind=a['data'].get('parse_options',{}).get('document_kind')
        if kind and kind!='payroll':raise PreconditionFailed('本轮 AI 格式适配仅支持工资表')
        root=self.store.database.settings.storage_path.resolve();path=(root/a['data']['storage_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise PreconditionFailed('原件存储路径无效')
        content=path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=a['data']['sha256']:raise PreconditionFailed('原件哈希不一致')
        return a,bounded_sheets(content)

    def replay(self,scope,artifact):
        """Re-read source values using only the applied, scope-bound proposal."""
        if artifact.get('scope')!=scope.model_dump():
            raise PreconditionFailed('工资原件 Scope 不匹配')
        a,sheets=self.source(scope,artifact['object_id'],artifact['version'])
        mapping_id=a['data'].get('payroll_mapping_id')
        if not mapping_id or mapping_id!=artifact['data'].get('payroll_mapping_id'):
            raise PreconditionFailed('工资原件缺少有效字段对应绑定，请重新核对格式')
        try:job=self.store.get_object(mapping_id,scope)
        except KeyError as exc:raise PreconditionFailed('工资字段对应绑定不存在，请重新核对格式') from exc
        data=job['data']
        if (job['object_type']!=TYPE or job['status']!='APPLIED'
                or data.get('artifact_id')!=a['object_id']
                or data.get('applied_artifact_version')!=a['version']
                or data.get('sha256')!=a['data']['sha256']
                or data.get('schema_version')!=VERSION):
            raise PreconditionFailed('工资字段对应绑定已失效，请重新核对格式')
        try:
            return extract_mapped(sheets,data.get('proposal'),scope.accounting_period_id)
        except (ValueError,KeyError,IndexError) as exc:
            raise PreconditionFailed('工资字段对应方案不能回放，请重新核对格式：'+str(exc)) from exc

    def request(self,scope,artifact_id,version,actor,payload):
        if payload:raise PreconditionFailed('识别格式不接受客户端提供模型输出')
        a,sheets=self.source(scope,artifact_id,version)
        jobs=self.store.list_objects(TYPE,scope)
        existing=next((j for j in reversed(jobs) if j['data']['artifact_id']==artifact_id and (j['data'].get('applied_artifact_version') if j['status']=='APPLIED' else j['data']['artifact_version'])==version and j['status'] in {'QUEUED','RUNNING','REVIEW','APPLIED'}),None)
        if existing:return {'object':existing}
        packet=structure_packet(sheets)
        data={'artifact_id':artifact_id,'artifact_version':version,'sha256':a['data']['sha256'],
              'input_hash':digest(packet),'schema_version':VERSION,'requested_by':actor,'queued_at':utcnow(), 'attempt':1+sum(j['data']['artifact_id']==artifact_id for j in jobs)}
        # Only format metadata crosses periods; no historical employee values are reused.
        for template in reversed(self.all_jobs()):
            ts=template['scope'];ss=scope.model_dump()
            if template['status']!='APPLIED' or template['data'].get('schema_version')!=VERSION or any(ts[k]!=ss[k] for k in ('tenant_id','organization_id','legal_entity_id','ledger_id')):continue
            p=template['data']['proposal']
            try:
                p=validated_proposal(p,sheets)
                if layout_signature(sheets,p)!=template['data']['layout_signature']:continue
                preview=extract_mapped(sheets,p,scope.accounting_period_id)
            except (ValueError,KeyError,IndexError):continue
            data.update(proposal=p,layout_signature=layout_signature(sheets,p),preview=preview,reused_from=template['object_id'],origin='CONFIRMED_FORMAT')
            break
        job=self.store.create_initial_object(TYPE,scope,data,status='REVIEW' if 'proposal' in data else 'QUEUED',created_by=actor)
        return {'object':job}

    def run_once(self):
        with self.store.database.transaction():
            jobs=self.all_jobs()
            # A lost lease is paused rather than silently sending another paid request.
            for j in jobs:
                if j['status']=='RUNNING' and time.time()-j['data'].get('started_epoch',0)>360:
                    self.store.revise_object(j['object_id'],j['version'],Scope(**j['scope']),{**j['data'],'error':'处理已中断，请重新识别'},status='FAILED',created_by='mapping-worker')
            job=next((j for j in jobs if j['status']=='QUEUED'),None)
            if not job:return False
            scope=Scope(**job['scope'])
            job=self.store.revise_object(job['object_id'],job['version'],scope,{**job['data'],'started_epoch':time.time()},status='RUNNING',created_by='mapping-worker')
        metadata={};proposal=None
        try:
            self.service._ensure_period_open(scope)
            self.authorized(scope,job['data']['requested_by'])
            a,sheets=self.source(scope,job['data']['artifact_id'],job['data']['artifact_version'])
            packet=structure_packet(sheets)
            if digest(packet)!=job['data']['input_hash']:raise ExtractionError('原件结构已变化')
            result=self.service.gateway.complete(scope,stage='PAYROLL_MAPPING',sanitized_input=packet)
            metadata=result.metadata();proposal=validated_proposal(result.output,sheets)
            preview=extract_mapped(sheets,proposal,scope.accounting_period_id)
            values={'proposal':proposal,'preview':preview,'layout_signature':layout_signature(sheets,proposal),'gateway':metadata,'origin':'AI'}
            status='REVIEW'
        except (GatewayFailure,ValueError,KeyError,PreconditionFailed) as exc:
            values={'error':str(exc),'gateway':metadata,'candidate_proposal':proposal};status='FAILED'
        except Exception:
            logging.exception('payroll_mapping_failed')
            values={'error':'格式识别发生错误，请重试或联系管理员','gateway':metadata};status='FAILED'
        with self.store.database.transaction():
            current=self.store.get_object(job['object_id'],scope)
            if current['version']!=job['version'] or current['status']!='RUNNING':return True
            if status=='REVIEW':
                try:
                    self.service._ensure_period_open(scope);self.authorized(scope,job['data']['requested_by']);self.source(scope,job['data']['artifact_id'],job['data']['artifact_version'])
                except (ValueError,KeyError,PreconditionFailed):status='FAILED';values={'error':'原件或期间已变化，请重新识别','gateway':metadata}
            updated=self.store.revise_object(job['object_id'],job['version'],scope,{**job['data'],**values,'finished_at':utcnow()},status=status,created_by='mapping-worker')
            self.store.add_audit('PAYROLL_MAPPING_FINISHED',job['data']['requested_by'],scope,object_id=updated['object_id'],after={'status':status,'gateway':metadata,'input_hash':job['data']['input_hash']})
        return True

    def correction(self,scope,job_id,version,proposal):
        job=self.store.get_object(job_id,scope)
        if job['object_type']!=TYPE or job['status']!='REVIEW' or job['version']!=version:raise PreconditionFailed('格式方案已变化，请重新查看')
        a,sheets=self.source(scope,job['data']['artifact_id'],job['data']['artifact_version'])
        try:
            proposal=validated_proposal(proposal,sheets)
            # Corrections may change column semantics, but not silently hide source sheets/rows.
            if [(p['sheet_index'],p['header_rows'],p['period_cell'],p['row_mode']) for p in proposal['sheets']]!=[(p['sheet_index'],p['header_rows'],p['period_cell'],p.get('row_mode','table')) for p in job['data']['proposal']['sheets']]:
                raise ExtractionError('表头或期间定位改变需要重新识别')
            extracted=extract_mapped(sheets,proposal,scope.accounting_period_id)
        except (ValueError,IndexError) as exc:raise PreconditionFailed(str(exc)) from exc
        return job,a,sheets,proposal,extracted

    def preview(self,scope,job_id,version,actor,payload):
        if set(payload)!={'proposal'}:raise PreconditionFailed('预览只接受字段对应方案')
        job,a,sheets,proposal,extracted=self.correction(scope,job_id,version,payload['proposal'])
        updated=self.store.revise_object(job_id,version,scope,{**job['data'],'proposal':proposal,'preview':extracted,'layout_signature':layout_signature(sheets,proposal)},status='REVIEW',created_by=actor)
        return {'object':updated}

    def apply(self,scope,job_id,version,actor,payload):
        if set(payload)!={'proposal','mapping_confirmed'} or payload['mapping_confirmed'] is not True:raise PreconditionFailed('请明确确认字段对应关系')
        job,a,sheets,proposal,extracted=self.correction(scope,job_id,version,payload['proposal'])
        if proposal!=job['data']['proposal']:raise PreconditionFailed('字段对应已改变，请先更新提取预览再确认')
        effect=self.service.parse_artifact(scope,artifact_id=a['object_id'],actor_id=actor,expected_version=a['version'],payload={'document_kind':'payroll'},_mapped=extracted,_mapping_id=job_id)
        updated=self.store.revise_object(job_id,version,scope,{**job['data'],'proposal':proposal,'preview':extracted,'layout_signature':layout_signature(sheets,proposal),'confirmed_by':actor,'confirmed_at':utcnow(),'applied_artifact_version':effect['artifact']['version']},status='APPLIED',created_by=actor)
        return {**effect,'object':updated}

    def view(self,scope):
        result=[]
        for j in self.store.list_objects(TYPE,scope):
            item=deepcopy(j)
            try:a,sheets=self.source(scope,j['data']['artifact_id'])
            except (ValueError,KeyError,PreconditionFailed):item['status']='STALE';result.append(item);continue
            expected=j['data'].get('applied_artifact_version') if j['status']=='APPLIED' else j['data']['artifact_version']
            if a['version']!=expected:item['status']='STALE'
            item['data']['filename']=a['data']['filename']
            if j['data'].get('proposal'):
                item['data']['columns']=[{'sheet_index':p['sheet_index'],'sheet':sheets[p['sheet_index']]['name'],'headers':header_values(sheets[p['sheet_index']],p['header_rows'])} for p in j['data']['proposal']['sheets']]
            result.append(item)
        return result

    def start(self):
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:
                    if self.run_once():continue
                except Exception:logging.exception('mapping_worker_poll_failed')
                self.stop_event.wait(1)
        self.thread=threading.Thread(target=loop,name='payroll-mapping',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)
