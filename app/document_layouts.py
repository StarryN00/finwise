"""Explicit local layouts; never infer business dates from a file name."""
from decimal import Decimal
from io import BytesIO
import re


def special_sheet(sheet, kind, period, bank_account=None):
    from app.tabular import money_value, date_value, period_value, column_name
    nonempty = [r for r in sheet['rows'] if any(v not in ('', None) for v in r['values'])]
    header = None
    layout = None
    for row in nonempty[:20]:
        labels = [str(v or '').strip() for v in row['values']]
        s = set(labels)
        if kind == 'bank_statement' and {'交易类型','交易金额','交易时间','余额'} <= s:
            layout = 'single_amount_bank'
        elif kind == 'social_security' and {'险种类型','单位应缴金额','个人应缴金额','应费款所属期'} <= s:
            layout = 'unit_medical'
        elif kind == 'electronic_acceptance' and {'票据（包）号','子票区间','票据（包）金额','出票日','到期日','票据状态'} <= s:
            layout = 'endorsement' if '背书日期' in s else 'bill_register'
        if layout:
            header = row
            break
    if header is None:
        return None
    headers = header['values']
    labels = [str(v or '').strip() for v in headers]
    records = []
    for row in nonempty:
        if row['row'] <= header['row']:
            continue
        values, number, issues, sources = row['values'], row['row'], [], {}
        if str(next((v for v in values if v not in ('', None)), '')).strip() in {'合计','总计','小计'}:
            continue

        def value(field, label, converter=str, required=True):
            idx = labels.index(label) if label in labels else -1
            indices=[i for i,l in enumerate(labels) if l==label]
            if len(indices)>1:
                issues.append(f'{field}：存在重复列标题，须核对全部同名列')
            raw = values[idx] if 0 <= idx < len(values) else None
            if raw in ('', None):
                if required:
                    issues.append(f'{field}：来源缺失')
                return None
            sources[field] = {'row':number,'region':f"{sheet['name']}!{column_name(idx+1)}{number}"}
            if column_name(idx+1)+str(number) in row['formulas']:
                issues.append(f'{field}：公式值须与原件计算结果核实')
            try:
                if converter is str and not isinstance(raw,str) and field in {'acceptance_no','sub_range'}:
                    issues.append(f'{field}：编号精度须核对')
                return converter(raw)
            except (ValueError, TypeError):
                issues.append(f'{field}：原件格式无效，须核对')
                return None

        def positive_money(raw):
            result=money_value(raw)
            if Decimal(result)<0:
                raise ValueError('negative')
            return result

        if layout == 'single_amount_bank':
            day=value('transaction_date','交易时间',date_value)
            direction=value('direction','交易类型')
            amount=value('amount','交易金额',positive_money)
            currency=value('currency','币种')
            if direction not in {'收入','支出'} or amount is None or Decimal(amount)<=0:
                issues.append('direction：收支方向或金额须核对')
            if currency not in {'人民币','CNY','RMB'}:
                issues.append('currency：币种不支持或不明确')
            n={'transaction_date':day,'period':day[:7] if day else None,'currency':currency,
               'direction':direction,'expense':amount if direction=='支出' else '0.00' if direction=='收入' else None,
               'income':amount if direction=='收入' else '0.00' if direction=='支出' else None,
               'balance':value('balance','余额',money_value),'bank_account_ref':bank_account}
            if bank_account:
                n['bank_account_origin']='MANUAL_PARSE_OPTION'
                issues.append('bank_account_ref：账户为人工指定，须补充与本原件关联的账户依据')
            else:
                issues.append('bank_account_ref：本方账户待人工核对，原件未列示账户')
            record_type='PAYMENT' if direction=='支出' else 'RECEIPT' if direction=='收入' else 'BANK_TRANSACTION'
            for field in ('expense','income'):
                if 'amount' in sources:
                    sources[field]={**sources['amount'],'field':'交易类型与交易金额'}
            n['payment_total' if direction=='支出' else 'receipt_total']=amount
        elif layout == 'unit_medical':
            def single_period(raw):
                if not re.fullmatch(r'20\d{2}(?:0[1-9]|1[0-2])|20\d{2}[-/](?:0[1-9]|1[0-2])',str(raw).strip()):
                    raise ValueError('ambiguous period')
                return period_value(raw)
            employer=value('employer_amount','单位应缴金额',positive_money)
            employee=value('employee_amount','个人应缴金额',positive_money)
            n={'aggregation_level':'UNIT','insurance_type':value('insurance_type','险种类型'),
               'employer_amount':employer,'employee_amount':employee,
               'period':value('period','应费款所属期',single_period),
               'start_period':value('start_period','起始费款所属期',single_period,False),
               'end_period':value('end_period','截止费款所属期',single_period,False),
               'employer_base':value('employer_base','单位缴费基数总额',positive_money,False),
               'employee_base':value('employee_base','个人缴费基数总额',positive_money,False),
               'people_count':value('people_count','缴费人数',str,False),
               'payment_status':value('payment_status','缴费标志',str,False),
               'total':format(Decimal(employer)+Decimal(employee),'.2f') if employer is not None and employee is not None else None,
               'total_derivation':'employer_amount + employee_amount'}
            record_type='SOCIAL_SECURITY'
            if any(n[f] and n[f]!=n['period'] for f in ('start_period','end_period')):
                issues.append('period：所属期与起止期间不一致或跨月，不能全部计入本期')
                n['period']=None
        else:
            day=value('transaction_date','背书日期',date_value) if layout=='endorsement' else None
            n={'register_kind':layout,'acceptance_no':value('acceptance_no','票据（包）号'),
               'sub_range':value('sub_range','子票区间'),'amount':value('amount','票据（包）金额',positive_money),
               'issue_date':value('issue_date','出票日',date_value),'maturity_date':value('maturity_date','到期日',date_value),
               'status':value('status','票据状态'),'transaction_date':day,'period':day[:7] if day else None}
            for field,label in [('issuer','出票人名称'),('payee','收款人名称'),('endorser','背书人名称'),('endorsee','被背书人名称')]:
                n[field]=value(field,label,str,False)
            if layout=='bill_register':
                issues.append('period：票据清单未列本期收付日期及业务角色，请关联收票或出票业务依据')
            if n['issue_date'] and n['maturity_date'] and n['issue_date']>n['maturity_date']:
                issues.append('maturity_date：到期日早于出票日')
            if day and ((n['issue_date'] and day<n['issue_date']) or (n['maturity_date'] and day>n['maturity_date'])):
                issues.append('transaction_date：背书日期不在出票日至到期日期间')
            match=re.fullmatch(r'(\d+),(\d+)',n['sub_range'] or '')
            if not match or int(match[1])>int(match[2]):
                issues.append('sub_range：子票区间格式或起止顺序无效')
            if n['amount'] is not None and Decimal(n['amount'])<=0:
                issues.append('amount：票据金额必须大于零')
            record_type='ELECTRONIC_ACCEPTANCE'
        records.append({'record_type':record_type,'source_anchor':{'row':number,'region':f"{sheet['name']}!A{number}:{column_name(len(headers))}{number}"},
            'original_value':{'sheet':sheet['name'],'row':number,'headers':headers,'values':values,'cell_types':row['types'],'formulas':row['formulas']},
            'normalized_value':n,'field_sources':sources,'extraction_issues':issues,'extraction_confidence':0.0 if issues else 1.0,
            'period_check':'PASS' if n['period']==period else 'PERIOD_EXCEPTION'})
    checks={}
    if layout in {'endorsement','bill_register'}:
        for index,left in enumerate(records):
            a=left['normalized_value'];ma=re.fullmatch(r'(\d+),(\d+)',a['sub_range'] or '')
            for right in records[index+1:]:
                b=right['normalized_value'];mb=re.fullmatch(r'(\d+),(\d+)',b['sub_range'] or '')
                if ma and mb and a['acceptance_no']==b['acceptance_no'] and all(a.get(k)==b.get(k) for k in ('transaction_date','endorser','endorsee')) and max(int(ma[1]),int(mb[1]))<=min(int(ma[2]),int(mb[2])):
                    for record in (left,right):
                        record['extraction_issues'].append('sub_range：同票据同一业务的子区间重复或重叠，不能重复累计')
    if layout=='single_amount_bank':
        checks['balance_continuity']=True
        for previous,current in zip(records,records[1:]):
            a,b=previous['normalized_value'],current['normalized_value']
            if any(v is None for v in [a['balance'],b['balance'],b['income'],b['expense']]) or Decimal(a['balance'])+Decimal(b['income'])-Decimal(b['expense'])!=Decimal(b['balance']):
                current['extraction_issues'].append('balance：与上一笔余额及收支变动不一致')
                checks['balance_continuity']=False
        text=' '.join(str(v) for r in nonempty if r['row']<header['row'] for v in r['values'])
        m=re.search(r'总收入\(¥\)：([\d,.]+).*总支出\(¥\)：([\d,.]+).*总收入笔数:(\d+).*总支出笔数:(\d+)',text)
        if m:
            try:
                totals=[sum(Decimal(r['normalized_value'][f]) for r in records) for f in ('income','expense')]
                counts=[sum(r['normalized_value']['direction']==d for r in records) for d in ('收入','支出')]
                checks['statement_totals']=totals==[Decimal(money_value(m[1])),Decimal(money_value(m[2]))] and counts==[int(m[3]),int(m[4])]
            except (TypeError,ValueError):
                checks['statement_totals']=False
            if not checks['statement_totals']:
                for r in records:
                    r['extraction_issues'].append('amount：收支金额或笔数与原表汇总不一致')
    for record in records:
        record['extraction_issues']=list(dict.fromkeys(record['extraction_issues']))
        record['extraction_confidence']=0.0 if record['extraction_issues'] else 1.0
    return {'records':records,'checks':checks,'sheets':[{'sheet':sheet['name'],'status':'PARSED','rows':len(records),'layout':layout}],
            'errors':[] if records else ['已识别表头，但未找到明细记录，须核对原件']}


def extract_boc_pdf(content, kind, period):
    from app.tabular import ExtractionError, MAX_BYTES, money_value
    if kind!='bank_statement' or len(content)>MAX_BYTES:
        raise ExtractionError('该 PDF 类型或大小不受支持；请提供文字型银行对账单')
    try:
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(content))
        if reader.is_encrypted or len(reader.pages)!=1:
            raise ValueError('Only validated single-page layout')
        text=reader.pages[0].extract_text()
        if len(text)>200000:
            raise ValueError('Text limit')
    except Exception as exc:
        raise ExtractionError('PDF 损坏、加密或版式不支持；本轮不支持扫描件 OCR') from exc
    if not all(t in text for t in ['中国银行','Account No.','Previous Page Balance','Debit Total','Credit Total']):
        raise ExtractionError('未识别为已适配的中行文字对账单；请提供对应银行原始导出表')
    try:
        account=re.search(r'账号\s+(\d+)',text)[1]
        start,end=re.search(r'起始日期\s*(\d{8})',text)[1],re.search(r'截止日期\s*(\d{8})',text)[1]
        from datetime import datetime
        start_day=datetime.strptime(start,'%Y%m%d').date();end_day=datetime.strptime(end,'%Y%m%d').date()
        if start_day>end_day or start_day.strftime('%Y-%m')!=end_day.strftime('%Y-%m'):
            raise ValueError('Period span')
        opening=Decimal(money_value(re.search(r'承前页余额\s+([\d,.\-]+)',text)[1]))
        summary=re.search(r'借方合计\s+([\d,.\-]+)\s+贷方合计\s+([\d,.\-]+)\s+本页余额\s+([\d,.\-]+)\s+本对账期末余额\s+([\d,.\-]+)',text)
        if not summary or '人民币(CNY)' not in text:
            raise ValueError('Missing totals or currency')
        expected=['序号','记账日','起息日','交易类型','凭证','凭证号码/业务编号/用途/摘要','借方发生额','贷方发生额','余额','机构/柜员/流水','备注']
        header_lines=[[re.sub(r'\s+','',s) for s in line.split('|')[1:-1]] for line in text.splitlines() if line.strip().startswith('|')]
        if expected not in header_lines:
            raise ValueError('Unrecognized column order')
        records=[];prev=opening
        for line_no,line in enumerate(text.splitlines(),1):
            if not line.strip().startswith('|'):
                continue
            cells=[s.strip() for s in line.split('|')[1:-1]]
            if len(cells)==11 and not cells[0] and records and any(cells):
                if any(cells[i] for i in (1,2,3,4,6,7,8,9,10)):
                    raise ValueError('Unsupported continuation')
                r=records[-1];r['normalized_value']['summary']+=cells[5]
                r['original_value']['values'][5]+=cells[5]
                r['original_value']['raw_text']+='\n'+line
                r['field_sources']['summary']['region']+=f' 至文本第{line_no}行'
                r['source_anchor']['region']+=f' 至文本第{line_no}行'
                continue
            if len(cells)!=11 or not cells[0].isdigit():
                continue
            if int(cells[0])!=len(records)+1:
                raise ValueError('Sequence mismatch')
            day=datetime.strptime(start[:2]+cells[1],'%Y%m%d').date()
            if not start_day<=day<=end_day:
                raise ValueError('Date outside statement')
            debit,credit=[Decimal(money_value(v or '0')) for v in cells[6:8]]
            balance=Decimal(money_value(cells[8]))
            if debit<0 or credit<0 or (debit>0)==(credit>0):
                raise ValueError('Ambiguous direction')
            if prev-debit+credit!=balance:
                raise ValueError('Balance mismatch')
            prev=balance
            n={'transaction_date':day.isoformat(),'period':day.strftime('%Y-%m'),'bank_account_ref':account,
               'expense':format(debit,'.2f'),'income':format(credit,'.2f'),'balance':format(balance,'.2f'),
               'summary':cells[5],'transaction_id':cells[9],'currency':'CNY',
               'payment_total' if debit>0 else 'receipt_total':format(debit or credit,'.2f')}
            anchor={'page':1,'row':line_no,'region':f'第1页 文本第{line_no}行 序号{cells[0]}'}
            fields={key:{**anchor,'field':label} for key,label in [('transaction_date','记账日'),('expense','借方发生额'),('income','贷方发生额'),('balance','余额'),('summary','凭证号码/业务编号/用途/摘要'),('transaction_id','机构/柜员/流水')]}
            fields['bank_account_ref']={'page':1,'region':'第1页 页首账号','field':'账号'}
            records.append({'record_type':'PAYMENT' if debit else 'RECEIPT','source_anchor':anchor,
                'original_value':{'page':1,'row':line_no,'headers':['序号','记账日','起息日','交易类型','凭证','摘要','借方发生额','贷方发生额','余额','流水','备注'],'values':cells,'raw_text':line},
                'normalized_value':n,'field_sources':fields,'extraction_issues':[], 'extraction_confidence':1.0,
                'period_check':'PASS' if n['period']==period else 'PERIOD_EXCEPTION'})
        if not records or sum(Decimal(r['normalized_value']['expense']) for r in records)!=Decimal(money_value(summary[1])) or sum(Decimal(r['normalized_value']['income']) for r in records)!=Decimal(money_value(summary[2])) or prev!=Decimal(money_value(summary[3])) or prev!=Decimal(money_value(summary[4])):
            raise ValueError('Statement totals mismatch')
    except (ValueError,TypeError,IndexError,AttributeError) as exc:
        raise ExtractionError('中行 PDF 日期、列结构、收支或余额校验未通过，需核对原件') from exc
    return {'records':records,'sheets':[{'sheet':'第1页','status':'PARSED','rows':len(records),'layout':'boc-text-v1'}],
            'errors':[],'checks':{'statement_totals':True,'balance_continuity':True}}
