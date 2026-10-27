"""Local CPU OCR evidence for the known Jiangsu bank statement layout.

OCR is an independent reading, not permission to overwrite financial facts.
Only comparisons and arithmetic checks are returned to the processing loop.
"""
from collections import Counter
from functools import lru_cache
from io import BytesIO
import re
import threading

from app.scanned_statements import ScannedStatement, StatementRow, StatementTotals, verify

VERSION = 'rapidocr-jiangsu-v1'
LOCK = threading.Lock()
HEADERS = ('序号', '交易日期', '交易时间', '摘要', '凭证种类', '借方发生额', '贷方发生额', '余额', '对方账户', '对方户名')
FIELDS = ('sequence', 'transaction_date', 'time', 'summary', 'voucher', 'debit', 'credit', 'balance', 'counterparty_account', 'counterparty_name')


class LocalOCRError(ValueError):
    pass


def center(box):
    return [sum(p[i] for p in box) / len(box) for i in (0, 1)]


def money(text):
    # Some scans turn thousands commas into dots. Accept only complete groups
    # of three plus exactly two decimals; never repair a digit or balance.
    text = re.sub(r'\s+', '', text)
    if not text:
        return '0.00'
    if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:[,.]\d{3})+)[,.]\d{2}', text):
        raise LocalOCRError('金额格式无法可靠识别')
    return re.sub(r'[,.]', '', text[:-3]) + '.' + text[-2:]


@lru_cache(maxsize=2)
def engine(numeric=False):
    try:
        from rapidocr import RapidOCR, ModelType, OCRVersion, LangRec
    except ImportError as exc:
        raise LocalOCRError('本地 OCR 未安装，请安装项目 pdf-ocr 可选依赖') from exc
    return RapidOCR(params={
        'Det.ocr_version': OCRVersion.PPOCRV4, 'Det.model_type': ModelType.MOBILE,
        'Rec.ocr_version': OCRVersion.PPOCRV4, 'Rec.model_type': ModelType.MOBILE,
        'Rec.lang_type': LangRec.EN if numeric else LangRec.CH,
        'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 2,
        'Global.log_level': 'warning',
    })


@lru_cache(maxsize=2)
def read_pages(content):
    from pypdf import PdfReader
    from PIL import Image
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 10:
        raise LocalOCRError('本地 OCR 仅支持未加密且不超过 10 页的扫描件')
    pages = []
    with LOCK:
        for page in reader.pages:
            images = list(page.images)
            # Multiple image tiles/overlays need a renderer; do not silently
            # process just the first tile as though it were the whole page.
            if len(images) != 1 or (page.extract_text() or '').strip():
                raise LocalOCRError('当前扫描版式需整页渲染，不能仅取部分图像')
            with Image.open(BytesIO(images[0].data)) as image:
                if image.width * image.height > 20_000_000:
                    raise LocalOCRError('扫描页像素过大，请使用不超过 2000 万像素的页面')
                image = image.convert('RGB')
                result = engine()(image, use_det=True, use_cls=True)
                if result.boxes is None or result.txts is None:
                    raise LocalOCRError('本地 OCR 未识别出文本')
                tokens = [{'box': b.tolist(), 'text': t, 'score': float(s)}
                          for b, t, s in zip(result.boxes, result.txts, result.scores)]
                for token in tokens:
                    if not re.fullmatch(r'[\d,.OQIl]+', token['text']) or not re.search(r'[OQIl]', token['text']) or '.' not in token['text']:
                        continue
                    xs, ys = zip(*token['box'])
                    crop = image.crop((max(0,min(xs)-3),max(0,min(ys)-3),min(image.width,max(xs)+3),min(image.height,max(ys)+3)))
                    attempts = []
                    for threshold in (None, 100, 130, 160):
                        sample = crop if threshold is None else crop.convert('L').point(lambda v: 255 if v > threshold else 0).convert('RGB')
                        second = engine(True)(sample, use_det=False, use_cls=False)
                        if not second.txts or len(second.txts) != 1:
                            continue
                        text, score = second.txts[0], float(second.scores[0])
                        try: normalized = money(text)
                        except LocalOCRError: continue
                        attempts.append({'text':text,'score':score,'normalized':normalized,'threshold':threshold})
                        if threshold is None and score >= .95:
                            break
                    if attempts:
                        best, hits = Counter(a['normalized'] for a in attempts).most_common(1)[0]
                        if len(attempts) > 1 and hits * 2 <= len(attempts):
                            continue
                        selected = next(a for a in attempts if a['normalized'] == best)
                        token['first_read'] = {'text':token['text'],'score':token['score']}
                        token.update(text=selected['text'], score=selected['score'], reader='numeric_crop', retries=attempts)
                pages.append(tokens)
    return pages


def parse_pages(pages):
    if not pages or not any('江苏银行对公账户对账单' in t['text'] for t in pages[0]):
        raise LocalOCRError('本地 OCR 已识字，当前表格适配器尚不支持该对账单版式')
    metadata = ''.join(t['text'] for t in pages[0][:20]).replace(' ', '')
    def value(label, pattern):
        found = re.search(label + r'[:：](' + pattern + ')', metadata)
        if not found:
            raise LocalOCRError('未能完整识别对账单表头统计信息')
        return found[1]
    count = int(value('合计笔数', r'\d+'))
    if not 1 <= count <= 500:
        raise LocalOCRError('对账单笔数超出本地适配范围')
    totals = StatementTotals(
        closing_balance=money(value('期末余额', r'[\d,.]+')),
        debit_count=int(value('借方笔数', r'\d+')),
        debit_total=money(value('借方发生总额', r'[\d,.]+')),
        credit_count=int(value('贷方笔数', r'\d+')),
        credit_total=money(value('贷方发生总额', r'[\d,.]+')), total_count=count)
    start, end = [value(label, r'\d{4}-\d{2}-\d{2}') for label in ('起始日期', '终止日期')]
    rows, evidence, warnings = [], [], []
    for page_no, tokens in enumerate(pages, 1):
        seq = next((t for t in tokens if t['text'] == '序号'), None)
        if not seq:
            raise LocalOCRError('扫描页缺少表头，无法保证明细完整性')
        hy = center(seq['box'])[1]
        hh = max(p[1] for p in seq['box']) - min(p[1] for p in seq['box'])
        xs = []
        for label in HEADERS:
            matches = [t for t in tokens if label in t['text'] and abs(center(t['box'])[1] - hy) < hh]
            if len(matches) != 1:
                raise LocalOCRError('表头列无法唯一定位')
            t = matches[0]; left = min(p[0] for p in t['box']); width = max(p[0] for p in t['box']) - left
            xs.append(left + width * (t['text'].index(label) + len(label)/2) / len(t['text']))
        if xs != sorted(xs):
            raise LocalOCRError('表头顺序不属于已验证版式')
        bounds = [(a+b)/2 for a,b in zip(xs, xs[1:])]
        def col(t):
            x = center(t['box'])[0]
            return sum(x > b for b in bounds)
        dates = sorted([t for t in tokens if col(t) == 1 and center(t['box'])[1] > hy + hh
                        and re.fullmatch(r'\d{4}-\d{2}-\d{2}', t['text'])], key=lambda t:center(t['box'])[1])
        if not dates:
            raise LocalOCRError('扫描页未找到完整交易日期列')
        # Dates at the top of each printed row identify row starts; multiline
        # counterparty text belongs below that start, not to the nearest center.
        starts = [center(t['box'])[1] - hh * .8 for t in dates]
        assigned = set()
        for i, date in enumerate(dates):
            cells = [[] for _ in FIELDS]
            bottom = starts[i+1] if i+1 < len(starts) else center(date['box'])[1] + hh*3
            for token_index, t in enumerate(tokens):
                if starts[i] <= center(t['box'])[1] < bottom:
                    cells[col(t)].append(t); assigned.add(token_index)
            texts = [''.join(t['text'] for t in sorted(c, key=lambda t: (center(t['box'])[1],center(t['box'])[0]))) for c in cells]
            number = len(rows)+1
            if texts[0] and texts[0] != str(number):
                raise LocalOCRError('扫描序号不连续，不能证明没有漏行')
            if not texts[0]:
                warnings.append({'row':number,'field':'sequence','code':'SEQUENCE_NOT_READ'})
            if not texts[7] or bool(texts[5]) == bool(texts[6]):
                raise LocalOCRError('借贷方向或余额不完整，不能补零猜测')
            row = StatementRow(sequence=number, transaction_date=date['text'], summary=texts[3],
                debit=money(texts[5]), credit=money(texts[6]), balance=money(texts[7]),
                counterparty_account=texts[8], counterparty_name=texts[9])
            rows.append(row)
            evidence.append({'row':number,'page':page_no,'cells':{
                f:c for f,c in zip(FIELDS,cells)}})
            for field, cell in zip(FIELDS,cells):
                if field not in {'time','voucher'} and any(t['score'] < .90 for t in cell):
                    warnings.append({'row':number,'field':field,'code':'LOW_OCR_SCORE'})
        # Any date/amount-shaped token in a core column below the header must
        # have been assigned. A missing date cannot silently drop a transaction.
        for index,t in enumerate(tokens):
            if center(t['box'])[1] > hy + hh and col(t) in {1,5,6,7} and index not in assigned:
                if re.search(r'\d{2}[-.,]\d{2}', t['text']):
                    raise LocalOCRError('存在未归属交易行的日期或金额，无法保证完整性')
    statement = ScannedStatement(period_start=start, period_end=end, totals=totals, rows=rows)
    report = verify(statement)
    return {'version':VERSION,'statement':statement.model_dump(mode='json'),
            'checks':[c.model_dump() for c in report.checks], 'evidence':evidence,'warnings':warnings}


def read_statement(content):
    return parse_pages(read_pages(content))


def compare_saved(reading, facts):
    """Never treat agreement with the same OCR output as independent proof."""
    mapping = {'transaction_date':'transaction_date','summary':'summary','debit':'expense',
               'credit':'income','balance':'balance','counterparty_name':'counterparty',
               'counterparty_account':'counterparty_account'}
    saved = {f['source_anchor'].get('row'):f for f in facts}
    failures = list(reading['warnings']);matches=0
    rows = reading['statement']['rows']
    if len(saved) != len(facts) or set(saved) != {r['sequence'] for r in rows}:
        failures.append({'code':'ROW_COVERAGE_MISMATCH'})
    for r in rows:
        s = saved.get(r['sequence'],{}).get('normalized_value',{})
        for field, target in mapping.items():
            if str(s.get(target) or '') != str(r[field]):
                failures.append({'code':'INDEPENDENT_READING_MISMATCH','row':r['sequence'],'field':target})
            else:matches+=1
    numeric_names={'笔数与表头一致','借方笔数与合计一致','贷方笔数与合计一致','末行余额等于表头期末余额','行间余额连续','期初倒算与期末吻合'}
    numeric=[c for c in reading['checks'] if c['name'] in numeric_names]
    arithmetic = len(numeric)==6 and all(c['passed'] for c in numeric)
    dates=[r['sequence'] for r in rows if not reading['statement']['period_start'] <= r['transaction_date'] <= reading['statement']['period_end']]
    # This adapter supplements existing evidence, never auto-promotes OCR-only
    # dates/identities into approved facts. A later executor may resolve cells.
    message=f"本地 OCR 已读取 {len(rows)} 条流水；金额与余额校验{'通过' if arithmetic else '未通过'}；与已有提取有 {sum(f['code']=='INDEPENDENT_READING_MISMATCH' for f in failures)} 处字段分歧。"
    if dates:message+='第 '+ '、'.join(map(str,dates))+' 行日期超出表头期间，保留原值继续查证。'
    return {'status':'BLOCKED','code':'OCR_EVIDENCE_ONLY','records':len(rows),'field_checks':len(rows)*len(mapping),
            'matched_fields':matches,'arithmetic_status':'PASS' if arithmetic else 'REVIEW',
            'failures':failures,'out_of_period_rows':dates,
            'message':message+'未覆盖原记录，也未请求整表人工确认。'}
