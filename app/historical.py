"""Local historical-ledger preparation, with a durable, leased, scope-bound queue.

Only the two explicitly recognized workbook layouts are accepted. This module
creates candidates, never current-period facts or human financial approvals.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import re
import threading
import time

from app.db import utcnow
from app.ontology.baseline import previous_period
from app.ontology.contracts import Scope
from app.ontology.errors import DomainError, PreconditionFailed
from app.ontology.store import digest
from app.tabular import ExtractionError, read_workbook

VERSION = "historical-ledger-v1"
TYPE = "HistoricalPreparation"
SYSTEM = "historical-worker"
LEASE_SECONDS = 300
log = logging.getLogger(__name__)


def issue_key(issue):
    # A stable key for one issue within a fixed preparation version; UI order is not identity.
    return digest({k: v for k, v in issue.items() if k not in {"issue_key", "evidence"}})


def money(value, *, signed=False):
    # Blank numeric cells mean no amount only in the recognized debit/credit layout.
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        raise ExtractionError("金额单元格不是有效数字")
    try:
        number = Decimal(str(value).replace(",", ""))
        if not number.is_finite() or abs(number) > Decimal("999999999999999") or number != number.quantize(Decimal(".01")) or (number < 0 and not signed):
            raise ValueError()
        return number
    except (InvalidOperation, ValueError) as exc:
        raise ExtractionError("金额无效或超过两位小数，请核对原件") from exc


def located(sheet, row, field=None):
    return {"row": row, "region": f"{sheet}!第{row}行", **({"field": field} if field else {})}


def code_text(value):
    # Excel numeric cells do not preserve leading zeros. Never pad or truncate.
    if isinstance(value, bool):
        raise ExtractionError("科目或辅助编码不能为布尔值")
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 999999999999999 or number != number.to_integral_value():
            raise ExtractionError("数值型科目或辅助编码不是可精确表示的整数")
        return str(int(number))
    return str(value or "").strip()


def check_currency(sheet):
    # Denominations may be in a single cell or a label/value pair. Explicit
    # foreign or ambiguous currencies are never implicitly converted to CNY.
    for row in sheet["rows"]:
        values = row["values"]
        for i, value in enumerate(values):
            for match in re.finditer(r"(?:币种|币别|CURRENCY)[^\S\r\n]*[:：]?[^\S\r\n]*([^\r\n]*)", str(value).upper()):
                currency = match.group(1).strip() or (str(values[i+1]).strip().upper() if i+1<len(values) else "")
                if currency not in {"人民币", "人民币元", "CNY", "RMB"}:
                    raise ExtractionError("账表币种不是明确的人民币口径或存在冲突；本轮不支持外币结转或自动换算")


def identify(content):
    sheets = read_workbook(content)
    populated = [s for s in sheets if any(any(v not in (None, "") for v in r["values"]) for r in s["rows"])]
    if len(populated) != 1:
        raise ExtractionError("历史账表须为一个有效工作表；多表或未知结构需要人工选择用途")
    sheet = populated[0]
    check_currency(sheet)
    sheet["company_labels"] = sorted({str(v).replace("编制单位：", "").replace("编制单位:", "").strip()
                                      for r in sheet["rows"] for v in r["values"]
                                      if str(v).startswith(("编制单位：", "编制单位:"))})
    title = str(sheet["rows"][0]["values"][0]).strip()
    if title not in {"科目余额表", "序时账"}:
        raise ExtractionError("尚不支持此历史账表结构，请提供科目余额表或序时账原件")
    texts = [str(v) for r in sheet["rows"][:4] for v in r["values"]]
    ranges = {tuple(map(int, m)) for text in texts for m in re.findall(r"(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月", text)}
    if len(ranges) != 1:
        raise ExtractionError("无法从表内唯一确认历史期间，不能按文件名猜测")
    y1, m1, y2, m2 = ranges.pop()
    try:
        start, end = date(y1, m1, 1), date(y2, m2, 1)
    except ValueError as exc:
        raise ExtractionError("表内期间无效") from exc
    if start > end:
        raise ExtractionError("表内期间起止顺序不正确")
    if any(r["formulas"] for r in sheet["rows"]):
        raise ExtractionError("历史账表含公式，需要提供已固化数值的导出账表")
    return title, sheet, start.strftime("%Y-%m"), end.strftime("%Y-%m")


def prepare_workbooks(balance_bytes, journal_bytes, period):
    bt, balance, start, end = identify(balance_bytes)
    jt, journal, jstart, jend = identify(journal_bytes)
    if bt != "科目余额表" or jt != "序时账":
        raise ExtractionError("来源用途不匹配，须分别提供余额表和序时账")
    if (start, end) != (jstart, jend) or end != previous_period(period):
        raise ExtractionError("历史账表期间不一致或未衔接本期紧邻上期，不能跨月生成期初候选")
    if len(balance["company_labels"]) > 1 or len(journal["company_labels"]) > 1 or (balance["company_labels"] and journal["company_labels"] and balance["company_labels"] != journal["company_labels"]):
        raise ExtractionError("两份账表的编制单位不一致，请核对企业归属")
    br = balance["rows"]
    header = next((i for i, r in enumerate(br[:10]) if r["values"][:2] == ["科目编码", "科目名称"]), None)
    # XLSX readers omit trailing empty header cells; pad only the known layout.
    if header is None or [(v or None) for v in (br[header]["values"]+[None]*8)[2:8]] != ["期初余额", None, "本期发生额", None, "期末余额", None]:
        raise ExtractionError("科目余额表不是已支持的期初、发生额、期末六金额列结构")
    if br[header+1]["values"][2:8] != ["借方", "贷方"] * 3:
        raise ExtractionError("余额表借贷列不明确")
    if not any("单位：元" in str(v) or "单位:元" in str(v) for r in br[:header] for v in r["values"]):
        raise ExtractionError("余额表金额单位尚未明确为元")
    accounts, auxiliary_rows, total, issues, checks = {}, {}, None, [], []

    def check(code, title, ok, message, anchors=None):
        item = {"code": code, "title": title, "passed": bool(ok), "message": message, "anchors": anchors or []}
        checks.append(item)
        if not ok:
            issues.append(item)

    for row in br[header+2:]:
        values = row["values"] + [None]*8
        code, name = code_text(values[0]), str(values[1] or "").strip()
        if not code:
            if name == "合计":
                if total is not None:
                    raise ExtractionError("余额表有重复总计行")
                total = [money(v) for v in values[2:8]]
            elif name and not name.endswith("小计"):
                raise ExtractionError(f"余额表第 {row['row']} 行用途不明，不能忽略")
            elif not name and any(v not in (None, "") for v in values[2:8]):
                raise ExtractionError(f"余额表第 {row['row']} 行有金额但缺少科目")
            continue
        if not re.fullmatch(r"\d+(?:\.\d+)?", code) or not name or code in accounts or code in auxiliary_rows:
            raise ExtractionError(f"余额表第 {row['row']} 行科目无效或重复")
        amounts = [money(v) for v in values[2:8]]
        if "." in code:
            parent, key = code.split(".")
            if parent not in accounts:
                raise ExtractionError("辅助明细缺少所属科目，不能猜测归属")
            auxiliary_rows[code] = {"parent": parent, "key": key, "amounts": amounts, "anchor": located(balance["name"], row["row"], "期末辅助余额")}
            continue
        accounts[code] = {"code": code, "name": name, "amounts": amounts, "anchor": located(balance["name"], row["row"], "期末余额")}
        if len(accounts) > 2000:
            raise ExtractionError("本地历史核对最多支持 2000 个科目，请拆分核对范围")
        check("ACCOUNT_EQUATION", f"科目 {code} 余额衔接", amounts[0]-amounts[1]+amounts[2]-amounts[3] == amounts[4]-amounts[5],
              f"科目 {code} 的期初净额＋本期发生净额应等于期末净额", [accounts[code]["anchor"]])
    if not accounts or total is None:
        raise ExtractionError("余额表缺少科目或总计，不能生成空候选")
    leaves = [code for code in accounts if not any(other != code and other.startswith(code) for other in accounts)]
    for code, account in accounts.items():
        children = [other for other in leaves if other.startswith(code)]
        if code not in leaves:
            sums = [sum((accounts[c]["amounts"][i] for c in children), Decimal(0)) for i in range(6)]
            expected = account["amounts"]
            matches = sums[2:4] == expected[2:4] and all(sums[i]-sums[i+1] == expected[i]-expected[i+1] for i in (0,4))
            check("HIERARCHY", f"科目 {code} 明细汇总", matches, f"科目 {code} 发生额及期初、期末净额应与末级明细一致（借贷明细不互相抵销）", [account["anchor"]])
    sums = [sum((accounts[c]["amounts"][i] for c in leaves), Decimal(0)) for i in range(6)]
    roots = [c for c in accounts if not any(p!=c and c.startswith(p) for p in accounts)]
    root_sums = [sum((accounts[c]["amounts"][i] for c in roots), Decimal(0)) for i in range(6)]
    check("BALANCE_TOTAL", "余额表合计与一级科目", root_sums == total, "一级科目汇总应等于表内总计；末级明细采用借贷不抵销口径，单独汇总")
    check("TRIAL_BALANCE", "期初、发生额和期末借贷平衡", all(sums[i] == sums[i+1] for i in (0, 2, 4)), "三个口径均须借贷平衡")
    jr = journal["rows"]
    h = next((i for i,r in enumerate(jr[:10]) if r["values"][:2] == ["日期", "凭证字号"]), None)
    expected = ["日期", "凭证字号", "摘要", "科目全称", "科目编码", "科目名称", "数量", "外币", "借方金额", "贷方金额"]
    if h is None or jr[h]["values"][:10] != expected:
        raise ExtractionError("序时账表头尚不支持，不能猜测科目或金额列")
    movements, vouchers, voucher_dates, auxiliary = defaultdict(lambda: [Decimal(0), Decimal(0)]), defaultdict(lambda: [Decimal(0), Decimal(0)]), {}, {}
    entry_count, months, journal_total, unmapped = 0, set(), None, {}
    for row in jr[h+1:]:
        v = row["values"] + [None]*10
        if money(v[7], signed=True) != 0:
            raise ExtractionError(f"序时账第 {row['row']} 行包含外币金额，请另行核对币种及本位币金额口径")
        if not v[0] and not v[1] and v[2] == "合计":
            if journal_total is not None:
                raise ExtractionError("序时账有重复总计")
            journal_total = [money(v[8], signed=True), money(v[9], signed=True)]
            continue
        if str(v[0] or "").startswith("编制单位："):
            continue
        if not any(x not in (None, "") for x in row["values"]):
            continue
        try:
            d = date.fromisoformat(str(v[0])[:10])
        except ValueError as exc:
            raise ExtractionError(f"序时账第 {row['row']} 行日期不明确") from exc
        month, code = d.strftime("%Y-%m"), code_text(v[4])
        if not start <= month <= end or not v[1] or not re.fullmatch(r"\d+", code):
            raise ExtractionError(f"序时账第 {row['row']} 行期间、凭证号或科目无效")
        if code not in accounts:
            unmapped.setdefault(code, []).append(located(journal["name"], row["row"]))
        values = [money(v[8], signed=True), money(v[9], signed=True)]
        key = (month, str(v[1]))
        if key in voucher_dates and voucher_dates[key] != str(d):
            raise ExtractionError("同月同凭证号对应多个日期，需要核实凭证唯一性")
        voucher_dates[key] = str(d)
        for i in range(2):
            movements[code][i] += values[i]
            vouchers[key][i] += values[i]
        if any(x not in (None, "") for x in row["values"][10:]):
            pairs = [(jr[h]["values"][i], code_text(v[i]), v[i+1] if i+1<len(v) else None)
                     for i in range(10, len(row["values"]), 2) if any(x not in (None, "") for x in v[i:i+2])]
            record = auxiliary.setdefault(code, {"anchors": [], "keys": set(), "movements": defaultdict(lambda: [Decimal(0),Decimal(0)]), "supported": True})
            record["anchors"].append(located(journal["name"], row["row"]))
            if len(pairs)!=1 or pairs[0][0] not in {"客户编码","供应商编码","存货编码","项目编码","部门编码","人员编码"} or not re.fullmatch(r"\d+", pairs[0][1]) or not pairs[0][2]:
                record["supported"] = False
            else:
                kind, key, _ = pairs[0]
                record["keys"].add((kind, key))
                for i in range(2):
                    record["movements"][key][i] += values[i]
        months.add(month)
        entry_count += 1
    if not entry_count or journal_total is None:
        raise ExtractionError("序时账没有有效分录或合计，不能推断完整性")
    actual_total = [sum((v[i] for v in vouchers.values()), Decimal(0)) for i in range(2)]
    check("JOURNAL_TOTAL", "全年发生额交叉核对", actual_total == journal_total == sums[2:4], "序时账逐行汇总、序时账合计与余额表发生额应相等")
    for code, anchors in unmapped.items():
        check("UNMAPPED_ACCOUNT", f"科目 {code} 未在余额表列出", False,
              f"序时账使用了科目 {code}，余额表没有该科目。请核对是否为停用、重分类或导出遗漏，并提供科目及余额依据；全年发生净额抵销不能替代期末余额依据。", anchors)
    for (month, number), values in vouchers.items():
        check("VOUCHER_BALANCE", f"{month} {number} 借贷平衡", values[0] == values[1], f"{month} {number} 的借贷金额应一致")
    for code, account in accounts.items():
        actual = [sum((v[i] for c,v in movements.items() if c.startswith(code)), Decimal(0)) for i in range(2)]
        check("ACCOUNT_MOVEMENT", f"科目 {code} 发生额核对", actual == account["amounts"][2:4], f"科目 {code} 序时账发生额应与余额表一致", [account["anchor"]])
    auxiliary_balances = {}
    for code in set(auxiliary) | {a["parent"] for a in auxiliary_rows.values()}:
        evidence = auxiliary.get(code, {"anchors": [], "keys": set(), "movements": {}, "supported": False})
        rows = [a for a in auxiliary_rows.values() if a["parent"] == code]
        same_dimension = len({k[0] for k in evidence["keys"]}) == 1
        keys = {k[1] for k in evidence["keys"]}
        matched = bool(rows) and evidence["supported"] and same_dimension and keys.issubset({a["key"] for a in rows})
        if matched and code in accounts:
            matched = all(sum((a["amounts"][i] for a in rows), Decimal(0)) == accounts[code]["amounts"][i] for i in range(6))
            matched = matched and all(a["amounts"][2:4] == evidence["movements"].get(a["key"], [Decimal(0),Decimal(0)]) and a["amounts"][0]-a["amounts"][1]+a["amounts"][2]-a["amounts"][3] == a["amounts"][4]-a["amounts"][5] for a in rows)
        else:
            matched = False
        check("AUXILIARY_REQUIRED", f"科目 {code} 辅助余额与发生额", matched,
              f"科目 {code} 的辅助编码、发生额、期末明细须与序时账及科目控制额一致；总额为零不代表每项辅助余额为零。若不一致，请补充或核对辅助明细。", evidence["anchors"] + [a["anchor"] for a in rows])
        auxiliary_balances[code] = [{"key": a["key"], "source_anchor": a["anchor"],
                                     **{side: format(a["amounts"][4+i], ".2f") for i, sides in enumerate((("opening_debit","closing_debit"),("opening_credit","closing_credit"))) for side in sides}} for a in rows]
    balances = []
    for code in leaves:
        a = accounts[code]
        debit, credit = (format(v, ".2f") for v in a["amounts"][4:6])
        balances.append({"account_code": code, "account_name": a["name"], "source_anchor": a["anchor"],
                         "closing_debit": debit, "opening_debit": debit, "closing_credit": credit, "opening_credit": credit,
                         "requires_auxiliary": code in auxiliary_balances, "auxiliary": auxiliary_balances.get(code, [])})
    return {"start_period": start, "end_period": end, "opening_period": period,
            "account_count": len(accounts), "leaf_count": len(leaves), "entry_count": entry_count,
            "voucher_count": len(vouchers), "active_months": sorted(months), "balances": balances,
            "movement_totals": dict(zip(("debit", "credit"), (format(v, ".2f") for v in actual_total))),
            "totals": {"debit": format(sums[4], ".2f"), "credit": format(sums[5], ".2f")},
            "source_totals": {"debit": format(total[4], ".2f"), "credit": format(total[5], ".2f")},
            "auxiliary_count": len(auxiliary_rows),
            "currency_basis": "表内金额单位为元；最终确认须人工核实为人民币口径。明确外币或外币金额不进入本候选。",
            "checks": checks, "issues": issues, "passed_checks": sum(c["passed"] for c in checks),
            "basis": "采用上年期末余额作为本期期初候选，不将上年年初余额或历史分录导入本期；最终结账版本和辅助明细须由人工核实。"}


def issue_evidence(result, sources):
    """Read-only projection of the exact source rows behind stored findings.

    It also supports existing job versions: no re-run, migration or approval is
    needed merely to inspect evidence. Advice is deterministic, not a model
    conclusion or a proposed account mapping.
    """
    index, vouchers = defaultdict(list), defaultdict(list)
    for ref, content in sources:
        title, sheet, _, _ = identify(content)
        journal = title == "序时账"
        header = next(r for r in sheet["rows"] if r["values"][:2] == (["日期", "凭证字号"] if journal else ["科目编码", "科目名称"]))
        labels = header["values"] if journal else ["科目编码", "科目名称", "期初借方", "期初贷方", "发生额借方", "发生额贷方", "期末借方", "期末贷方"]
        for row in sheet["rows"]:
            if row["row"] <= header["row"] + (0 if journal else 1):
                continue
            values = row["values"] + [None]*10
            anchor = located(sheet["name"], row["row"])
            item = {"source": ref, "anchor": anchor, "kind": "journal" if journal else "balance",
                    "cells": [{"label": str(label or f"第 {n+1} 列"), "value": row["values"][n]}
                              for n, label in enumerate(labels) if n < len(row["values"]) and (label or row["values"][n] not in (None, ""))]}
            if journal and values[0] and values[1] and re.fullmatch(r"\d+", code_text(values[4])):
                item.update({"date": str(values[0])[:10], "voucher_number": str(values[1]), "summary": str(values[2] or ""),
                             "account_code": code_text(values[4]), "account_name": str(values[3] or values[5] or ""),
                             "debit": format(money(values[8], signed=True), ".2f"), "credit": format(money(values[9], signed=True), ".2f")})
                vouchers[(ref["artifact_id"], item["date"], item["voucher_number"])].append(item)
            index[(anchor["region"], anchor["row"])].append(item)
    enriched, contexts = [], {}
    remaining_rows, remaining_bytes = 1000, 2 * 1024 * 1024

    def bounded_rows(rows):
        nonlocal remaining_rows, remaining_bytes
        kept = []
        for row in rows:
            size = len(json.dumps(row, ensure_ascii=False).encode())
            if remaining_rows <= 0 or size > remaining_bytes:
                break
            kept.append(row)
            remaining_rows -= 1
            remaining_bytes -= size
        return kept

    for issue in result["issues"]:
        rows, missing = [], 0
        for anchor in issue["anchors"]:
            matches = index.get((anchor.get("region"), anchor.get("row")), [])
            if len(matches) != 1:
                missing += 1  # Ambiguous locations must not select an arbitrary file.
            elif not any(r["source"] == matches[0]["source"] and r["anchor"] == matches[0]["anchor"] for r in rows):
                rows.append(matches[0])
        rows.sort(key=lambda r: (r.get("date", ""), r["anchor"]["row"]), reverse=True)
        evidence = {"rows": rows, "missing_locations": missing, "summary": None, "related_vouchers": [],
                    "advice": ["核对所列原件值与校验要求；若资料缺失或导出不完整，补充正确版本后重新核对。"],
                    "completion_condition": "原件依据完整、问题校验通过后，再由人工核实并确认期初。"}
        if issue["code"] == "UNMAPPED_ACCOUNT" and rows and not missing and all("debit" in r for r in rows):
            totals = {side: sum((Decimal(r[side]) for r in rows), Decimal(0)) for side in ("debit", "credit")}
            negative = [r for r in rows if Decimal(r["debit"]) < 0 or Decimal(r["credit"]) < 0]
            evidence["summary"] = {"record_count": len(rows), "account_names": sorted({r["account_name"] for r in rows}),
                "debit": format(totals["debit"], ".2f"), "credit": format(totals["credit"], ".2f"),
                "net_movement": format(totals["debit"]-totals["credit"], ".2f"), "negative_count": len(negative),
                **{f"{side}_{sign}": format(sum((Decimal(r[side]) for r in rows if (Decimal(r[side]) >= 0 if sign == "positive" else Decimal(r[side]) < 0)), Decimal(0)), ".2f")
                   for side in ("debit", "credit") for sign in ("positive", "negative")}}
            keys = list(dict.fromkeys((r["source"]["artifact_id"], r["date"], r["voucher_number"]) for r in negative))
            evidence["contexts_omitted"] = 0
            for key in keys:
                if len(evidence["related_vouchers"]) >= 20 or (key not in contexts and len(contexts) >= 100):
                    evidence["contexts_omitted"] += 1
                    continue
                if key not in contexts:
                    kept = bounded_rows(vouchers[key])
                    contexts[key] = {"id": digest(key), "date": key[1], "voucher_number": key[2], "rows": kept,
                                     "source_id": key[0], "omitted_rows": len(vouchers[key])-len(kept)}
                evidence["related_vouchers"].append({"context_id": contexts[key]["id"], "date": key[1], "voucher_number": key[2], "source_id": key[0]})
            evidence["advice"] = ([f"优先核对 {negative[0]['date']} {negative[0]['voucher_number']} 的负数记录及同凭证其他科目，确认是否为科目调整，并核对摘要与科目名称所指业务是否一致。"] if negative else ["先核对这些分录使用的科目编码、名称及业务归属，不能直接套用相近科目。"])
            evidence["advice"] += ["若原账已调整科目，取得调整说明、对应关系及最终期末余额依据；若是导出遗漏，重新导出包含停用、零余额科目的完整余额表。",
                                   "补充依据后重新核对。发生净额相抵不能证明期末余额为零，不自动补零或修改科目映射。"]
        evidence["rows"] = bounded_rows(rows)
        evidence["omitted_rows"] = len(rows)-len(evidence["rows"])
        enriched.append({**issue, "evidence": evidence})
    return {"issues": enriched, "evidence_vouchers": list(contexts.values())}


class HistoricalPreparation:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.stop_event = threading.Event()
        self.thread = None

    def get(self, scope):
        try:
            return self.store.get_object("historical_" + digest(scope.model_dump())[:24], scope)
        except KeyError:
            return None

    def sources(self, scope):
        return sorted((s for s in self.store.list_objects("SourceArtifact", scope)
                       if s["status"] in {"ACTIVE", "PERIOD_EXCEPTION"} and s["data"].get("source_purpose") == "historical_reference"), key=lambda s: s["object_id"])

    def binding(self, source):
        return {"artifact_id": source["object_id"], "version": source["version"], "sha256": source["data"]["sha256"], "filename": source["data"]["filename"]}

    def enqueue(self, scope, actor, *, retry=False, artifact_ids=None):
        with self.store.database.transaction():
            self.service._ensure_period_open(scope)
            sources = self.sources(scope)
            cohort_hash = digest([self.binding(s) for s in sources])
            old = self.get(scope)
            if artifact_ids is None and old and old["data"].get("cohort_hash") == cohort_hash:
                sources = [s for s in sources if s["object_id"] in {r["artifact_id"] for r in old["data"]["sources"]}]
            if artifact_ids is not None:
                if not isinstance(artifact_ids, list) or len(artifact_ids) != 2 or not all(isinstance(i,str) for i in artifact_ids) or len(set(artifact_ids)) != 2 or not set(artifact_ids).issubset({s["object_id"] for s in sources}):
                    raise PreconditionFailed("请选择当前范围内两份不同的历史原件")
                sources = [s for s in sources if s["object_id"] in artifact_ids]
            if not sources:
                raise PreconditionFailed("尚无历史账表原件，请先上传")
            refs = [self.binding(s) for s in sources]
            fingerprint = digest({"sources": refs, "parser": VERSION})
            if old and old["data"]["input_hash"] == fingerprint and old["data"].get("cohort_hash") == cohort_hash:
                if not retry or old["status"] in {"QUEUED", "RUNNING"}:
                    return old
            data = {"sources": refs, "input_hash": fingerprint, "cohort_hash": cohort_hash, "parser_version": VERSION,
                    "attempt": 0, "queued_at": utcnow(), "step": "等待后台读取历史账表", "result": None}
            job = self.store.create_object(TYPE, scope, data, status="QUEUED", created_by=actor,
                                           object_id="historical_" + digest(scope.model_dump())[:24])
            self.store.add_audit("HISTORICAL_QUEUED", actor, scope, object_id=job["object_id"], after={"input_hash": fingerprint, "sources": refs})
            return job

    def view(self, scope):
        job = self.get(scope)
        if job and job["data"].get("result"):
            job = deepcopy(job)
            for issue in job["data"]["result"]["issues"]:
                issue["issue_key"] = issue_key(issue)
        if job and job["status"] in {"NEEDS_REVIEW", "READY_FOR_CONFIRMATION"}:
            try:
                sources = self.checked_sources(job)
            except (DomainError, OSError, KeyError) as exc:
                return {**job, "status": "STALE", "data": {**job["data"], "result": None, "error": str(exc)}}
            if job["data"]["result"]["issues"]:
                try:
                    evidence = issue_evidence(job["data"]["result"], sources)
                    return {**job, "data": {**job["data"], "result": {**job["data"]["result"], **evidence}}}
                except (ExtractionError, KeyError, ValueError, StopIteration):
                    return {**job, "data": {**job["data"], "evidence_error": "暂时无法读取问题明细，请查看原件并重新核对；原核对结论未改变。"}}
        return job

    def checked_sources(self, job):
        scope = Scope(**job["scope"])
        result = []
        for ref in job["data"]["sources"]:
            source = self.store.get_object(ref["artifact_id"], scope)
            if source["status"] not in {"ACTIVE", "PERIOD_EXCEPTION"} or self.binding(source) != ref:
                raise PreconditionFailed("历史原件版本或用途已变化，请重新处理")
            if source["data"].get("observed_period") != previous_period(scope.accounting_period_id):
                raise PreconditionFailed("历史原件所属期末必须为本期紧邻上期，请核对资料期间")
            root = self.store.database.settings.storage_path.resolve()
            path = (root / source["data"]["storage_path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise PreconditionFailed("历史原件不存在、越界或过大")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != ref["sha256"]:
                raise PreconditionFailed("历史原件哈希发生变化，停止处理")
            result.append((ref, content))
        return result

    def claim(self):
        with self.store.database.transaction():
            for item in self.store.list_scope_objects():
                scope = Scope(**item["data"]["scope"])
                job = self.get(scope)
                if not job or job["status"] not in {"QUEUED", "RUNNING"}:
                    continue
                if job["status"] == "RUNNING" and job["data"].get("lease_until", 0) > time.time():
                    continue
                try:
                    self.service._ensure_period_open(scope)
                except DomainError:
                    self.finish(job, "FAILED", {"error": "期间已关闭，停止后台处理"})
                    continue
                if job["data"].get("attempt", 0) >= 3:
                    self.finish(job, "FAILED", {"error": "后台任务多次中断，请检查服务后重试"})
                    continue
                data = {**job["data"], "attempt": job["data"].get("attempt", 0)+1,
                        "started_at": utcnow(), "lease_until": time.time()+LEASE_SECONDS, "step": "正在解析账表并核对科目、发生额和期末余额"}
                claimed = self.store.revise_object(job["object_id"], job["version"], scope, data, status="RUNNING", created_by=SYSTEM)
                self.store.add_audit("HISTORICAL_STARTED", SYSTEM, scope, object_id=job["object_id"], after={"attempt": data["attempt"], "input_hash": data["input_hash"]})
                return claimed
        return None

    def finish(self, job, status, values):
        scope = Scope(**job["scope"])
        with self.store.database.transaction():
            current = self.get(scope)
            if current["version"] != job["version"]:
                return False  # A newer input or lease owns the result now.
            if status in {"NEEDS_REVIEW", "READY_FOR_CONFIRMATION"}:
                try:
                    self.service._ensure_period_open(scope)
                    self.checked_sources(job)
                except (DomainError, KeyError, OSError) as exc:
                    status, values = "FAILED", {"error": str(exc), "result": None, "step": "来源或期间变化，停止处理"}
            data = {**job["data"], **values, "finished_at": utcnow(), "lease_until": None}
            result = self.store.revise_object(job["object_id"], job["version"], scope, data, status=status, created_by=SYSTEM)
            self.store.add_audit("HISTORICAL_" + status, SYSTEM, scope, object_id=job["object_id"], object_version=result["version"],
                                 after={"input_hash": data["input_hash"], "output_hash": digest(values), "parser_version": VERSION, "error": data.get("error")})
            return True

    def run_once(self):
        job = self.claim()
        if not job:
            return False
        try:
            sources = self.checked_sources(job)
            if len(sources) != 2:
                status = "WAITING_INPUT" if len(sources) < 2 else "NEEDS_SELECTION"
                self.finish(job, status, {"step": "还需要余额表和序时账各一份" if len(sources)<2 else "有多个历史原件，请明确选择本次核对的两份账表"})
                return True
            classified = {}
            for ref, content in sources:
                title, _, _, _ = identify(content)
                if title in classified:
                    raise ExtractionError("两份原件用途重复，需要余额表和序时账各一份")
                classified[title] = (ref, content)
            result = prepare_workbooks(classified["科目余额表"][1], classified["序时账"][1], job["scope"]["accounting_period_id"])
            result["balance_source"] = classified["科目余额表"][0]
            result["journal_source"] = classified["序时账"][0]
            # Source versions/hashes and open period are checked again before publishing.
            self.checked_sources(job)
            self.service._ensure_period_open(Scope(**job["scope"]))
            self.finish(job, "NEEDS_REVIEW" if result["issues"] else "READY_FOR_CONFIRMATION", {"result": result, "step": "系统核对完成，等待人工核实"})
        except (ExtractionError, PreconditionFailed, KeyError, OSError, ValueError) as exc:
            self.finish(job, "FAILED", {"error": str(exc), "step": "处理失败，原件已保留"})
        except Exception:
            log.exception("historical_preparation_failed", extra={"job_id": job["object_id"]})
            self.finish(job, "FAILED", {"error": "后台处理发生错误，请联系管理员检查日志后重试", "step": "处理失败，原件已保留"})
        return True

    def confirmation_inputs(self, scope, payload):
        if set(payload) != {"historical_preparation", "completeness_confirmed", "final_close_confirmed", "carry_forward_confirmed"} or any(payload.get(k) is not True for k in ("completeness_confirmed", "final_close_confirmed", "carry_forward_confirmed")):
            raise PreconditionFailed("须人工核实最终结账版本、辅助明细完整性，并明确采用上期末余额结转本期期初")
        ref = payload["historical_preparation"]
        job = self.get(scope)
        if not job or ref != {"object_id": job["object_id"], "version": job["version"]} or job["status"] != "READY_FOR_CONFIRMATION":
            raise PreconditionFailed("历史核对候选尚未就绪或版本已变化")
        sources = dict((r["artifact_id"], b) for r,b in self.checked_sources(job))
        result = job["data"]["result"]
        fresh = prepare_workbooks(sources[result["balance_source"]["artifact_id"]], sources[result["journal_source"]["artifact_id"]], scope.accounting_period_id)
        if fresh["issues"] or fresh["balances"] != result["balances"] or job["data"]["parser_version"] != VERSION:
            raise PreconditionFailed("来源核对不通过，请重新处理历史账表")
        # Closing and carried-forward opening come from the same balance sheet,
        # not from pretending the journal is a second balance sheet.
        source = result["balance_source"]
        source = {"artifact_id": source["artifact_id"], "version": source["version"], "anchor": result["balances"][0]["source_anchor"]}
        return {"prior_period": result["end_period"], "close_reference": "历史期末结转候选 " + job["object_id"],
                "currency": "CNY", "completeness_confirmed": True, "balance_source": source, "close_source": source,
                "balances": deepcopy(result["balances"])}

    def start(self):
        # Reconcile only explicit historical uploads. Also repairs upload/queue crash gaps.
        for item in self.store.list_scope_objects():
            scope = Scope(**item["data"]["scope"])
            sources, job = self.sources(scope), self.get(scope)
            if sources and (not job or job["data"].get("cohort_hash") != digest([self.binding(s) for s in sources])):
                try:
                    self.enqueue(scope, SYSTEM)
                except DomainError:
                    pass
        self.stop_event.clear()

        def loop():
            while not self.stop_event.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    log.exception("historical_worker_poll_failed")
                self.stop_event.wait(1)
        self.thread = threading.Thread(target=loop, name="historical-preparation", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
