"""Deterministic source-reading evidence; never grants accounting approval."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re

from app.ontology.store import digest
from app.tabular import date_value, read_workbook, header_mapping, extract_row


def invoice_reference_matches(sheet, reference):
    """Account for every line-item row on a duplicate tax export summary sheet."""
    rows = [r for r in sheet.get('rows', []) if any(v not in (None, '') for v in r['values']) or r.get('formulas')]
    invoices = reference.get('records', [])
    if not rows or not invoices or any(r['record_type'] not in {'INVOICE', 'SALES_INVOICE'} for r in invoices):
        return False
    kind = 'sales_invoices' if invoices[0]['record_type'] == 'SALES_INVOICE' else 'purchase_invoices'
    mapping = header_mapping(rows[0]['values'], kind)
    if not mapping:
        return False
    known = {r['normalized_value']['invoice_no']: r['normalized_value'] for r in invoices}
    if len(known) != len(invoices):
        return False
    totals = defaultdict(lambda: {k: Decimal(0) for k in ('net_amount', 'tax', 'invoice_total')})
    try:
        for row in rows[1:]:
            if row.get('formulas'):
                return False
            parsed = extract_row(sheet['name'], row, rows[0]['values'], mapping, kind, '0000-00', None)
            value = parsed['normalized_value']
            target = known.get(value.get('invoice_no'))
            if target is None:
                return False
            for key in ('invoice_date', 'seller_name', 'seller_tax_id', 'buyer_name', 'buyer_tax_id', 'invoice_status'):
                if value.get(key) != target.get(key):
                    return False
            for key in ('net_amount', 'tax', 'invoice_total'):
                totals[value['invoice_no']][key] += Decimal(str(value[key]))
        return set(totals) == set(known) and all(
            totals[number][key] == Decimal(str(known[number][key]))
            for number in totals for key in ('net_amount', 'tax', 'invoice_total'))
    except (ValueError, ArithmeticError, KeyError, TypeError):
        return False


def verify_source(content, candidate, reference):
    failures, evidence = [], []
    try:
        sheets = {s['name']: s for s in read_workbook(content)}
    except Exception:
        return {'status': 'BLOCKED', 'code': 'SOURCE_READER_UNAVAILABLE',
                'message': '当前原件无法用表格读取工具逐字段核验，需要系统接入适合此格式的读取工具。',
                'failures': [], 'records': 0, 'field_checks': 0}
    expected = [(r['original_value'].get('sheet'), r['source_anchor'].get('row')) for r in reference.get('records', [])]
    actual = [(r['original_value'].get('sheet'), r['source_anchor'].get('row')) for r in candidate.get('records', [])]
    if not expected or sorted(expected) != sorted(actual) or len(set(actual)) != len(actual):
        failures.append({'code': 'ROW_COVERAGE_MISMATCH'})
    reference_rows = {key: row for key, row in zip(expected, reference.get('records', []))}
    summaries = {s.get('sheet'): s for s in reference.get('sheets', [])}
    for name, sheet in sheets.items():
        summary = summaries.get(name, {})
        nonempty = [r for r in sheet.get('rows', []) if any(v not in (None, '') for v in r['values']) or r.get('formulas')]
        if summary.get('status') == 'EXTRACTED' and isinstance(summary.get('header_row'), int):
            header = summary['header_row']
            headers = next((r['values'] for r in nonempty if r['row'] == header), [])
            references = {r['row']: r for r in summary.get('reference_rows', [])}
            for raw_row in nonempty:
                number = raw_row['row']
                if number <= header or (name, number) in reference_rows or raw_row['values'] == headers:
                    continue
                ref = references.get(number)
                # These rows carry an explicit parser classification, raw cells,
                # and are included in the source arithmetic checks below.
                if ref and ref.get('reason') in {'BANK_STATISTICS', 'BANK_TOTAL_HEADER', 'BANK_TOTAL_VALUES', 'INVOICE_TOTAL', 'SUMMARY_REFERENCE'} and ref.get('values') == raw_row['values']:
                    continue
                failures.append({'code': 'UNACCOUNTED_SOURCE_ROW', 'sheet': name, 'row': number})
            continue
        if summary.get('status') == 'REFERENCE_ONLY' and invoice_reference_matches(sheet, reference):
            continue
        if summary.get('status') == 'EMPTY' and not nonempty:
            continue
        sheet = sheets.get(summary.get('sheet'), {})
        # Known tax-export empty templates contain metadata and a numbered header,
        # not invoice records. Unknown/nonempty layouts must remain blocked.
        rows = sheet.get('rows', [])
        known = summary.get('sheet') in {'海关缴款书', '代扣代缴', '农产品加计扣除发票信息', '农产品加计扣除海关文书', '异常发票'}
        if not (known and len(rows) == 3 and rows[2]['values'][0] == '序号'):
            failures.append({'code': 'UNCLASSIFIED_SHEET'})
    for record in candidate.get('records', []):
        reference_row = reference_rows.get((record['original_value'].get('sheet'), record['source_anchor'].get('row')))
        if reference_row is None:
            continue
        # The independent local re-read owns the full contract. A candidate may
        # not drop anchors or alter derived aliases to reduce the check scope.
        for key in ('record_type', 'normalized_value', 'field_sources', 'extraction_issues', 'period_check'):
            if record.get(key) != reference_row.get(key):
                failures.append({'code': 'REFERENCE_CONTRACT_MISMATCH', 'row': record['source_anchor'].get('row'), 'field': key})
        values = record.get('normalized_value', {})
        sources = reference_row.get('field_sources', {})
        row = record['source_anchor'].get('row')
        sheet_name = record['original_value'].get('sheet')
        core = ('invoice_no', 'invoice_date', 'net_amount', 'tax') if record['record_type'] in {'INVOICE', 'SALES_INVOICE'} else ()
        if not sources:
            failures.append({'code': 'NO_SOURCE_ANCHORS', 'row': row})
        for field in set(core) | {k for k, v in sources.items() if v.get('region') and k in values}:
            source = sources.get(field, {})
            if source.get('account_id') and source.get('derivation'):
                # Already replayed under the fixed, authorized bank binding.
                # It is registry evidence, not a same-row source cell.
                evidence.append({'row': row, 'field': field, 'region': source.get('region'), 'passed': record.get('field_sources', {}).get(field) == source and values.get(field) == reference_row['normalized_value'].get(field)})
                continue
            if field == 'invoice_total' and values.get('invoice_total_derivation'):
                continue
            if values.get(field + '_derivation'):
                failures.append({'code': 'UNSUPPORTED_DERIVATION', 'row': row, 'field': field})
                continue
            region = sources.get(field, {}).get('region', '')
            matched = re.fullmatch(r'(.*)!([A-Z]+)(\d+)', region)
            passed = False
            try:
                if not matched or matched[1] != sheet_name or (int(matched[3]) != row and field != 'bank_account_ref'):
                    raise ValueError('anchor')
                source_row = next(r for r in sheets[sheet_name]['rows'] if r['row'] == int(matched[3]))
                col = 0
                for char in matched[2]:
                    col = col * 26 + ord(char) - 64
                if matched[2] + matched[3] in source_row.get('formulas', {}):
                    raise ValueError('formula')
                raw, value = source_row['values'][col - 1], values.get(field)
                if field == 'bank_account_ref' and int(matched[3]) != row:
                    passed = source.get('original_value') == record.get('field_sources', {}).get(field, {}).get('original_value') and values.get(field) == reference_row['normalized_value'].get(field)
                elif raw in (None, '') or value is None:
                    raise ValueError('missing')
                elif 'date' in field:
                    passed = date_value(raw) == value
                elif any(part in field for part in ('name', 'account', '_no', '_id', 'status', 'summary', 'currency', 'direction')):
                    passed = str(raw).strip() == str(value).strip()
                else:
                    try:
                        a = Decimal(str(raw).replace(',', '').rstrip('%'))
                        if str(raw).endswith('%'):
                            a /= 100
                        passed = a.is_finite() and a.quantize(Decimal('.000001')) == Decimal(str(value)).quantize(Decimal('.000001'))
                    except InvalidOperation:
                        passed = str(raw).strip() == str(value).strip()
            except (ValueError, KeyError, StopIteration, IndexError, ArithmeticError, TypeError):
                pass
            evidence.append({'row': row, 'field': field, 'region': region, 'passed': passed})
            if not passed:
                failures.append({'code': 'SOURCE_FIELD_MISMATCH', 'row': row, 'field': field})
        if values.get('invoice_total_derivation'):
            try:
                passed = Decimal(str(values['invoice_total'])) == Decimal(str(values['net_amount'])) + Decimal(str(values['tax']))
            except (KeyError, ArithmeticError, ValueError):
                passed = False
            if not passed:
                failures.append({'code': 'DERIVED_AMOUNT_MISMATCH', 'row': row})
    # Source arithmetic is additional evidence; absent totals are not invented.
    checks = reference.get('checks', {})
    if checks.get('overall') in {'REVIEW', 'MISMATCH', 'FAIL', 'FAILED'}:
        failures.append({'code': 'SOURCE_ARITHMETIC_FAILED'})
    if reference.get('errors'):
        failures.append({'code': 'EXTRACTION_INCOMPLETE'})
    return {'status': 'PASS' if not failures else 'BLOCKED', 'records': len(actual),
            'field_checks': len(evidence), 'evidence': evidence, 'failures': failures,
            'candidate_hash': digest(candidate), 'arithmetic_status': checks.get('overall', 'NOT_AVAILABLE'),
            'message': '原件字段与提取值已逐项核验。' if not failures else '原件读取仍有具体疑点，系统需要继续处理。'}
