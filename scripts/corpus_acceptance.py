"""语料验收：对真实银行流水跑完整链路，量化别名表 / 版式库各自的贡献。

用法： .venv/bin/python scripts/corpus_acceptance.py [语料目录]
语料是真实客户数据，不入库；默认读 .data/。
"""
from __future__ import annotations

import re
import sys
import tempfile
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.db import Database
from app.profile_proposals import propose_mapping
from app.source_profiles import ProfileStore, fingerprint
from app.tabular import ExtractionError, ParseOptions, extract_workbook, read_workbook

PATTERN = re.compile(r"(流水|银行明细|对账单|交易明细)")
KIND = "bank_statement"


def corpus(root: Path) -> list[Path]:
    seen, files = set(), []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("~$") or not PATTERN.search(path.name):
            continue
        if path.suffix.lower() not in {".xls", ".xlsx", ".csv", ".pdf"} or path.name in seen:
            continue
        seen.add(path.name)
        files.append(path)
    return files


def parse(content: bytes, store: ProfileStore | None):
    def resolver(labels, kind):
        if store is None:
            return None
        found = store.resolve(fingerprint_value=fingerprint(labels, kind), document_kind=kind)
        return found.mapping if found else None

    # 本方账户由操作人在上传时指定；语料验收固定给一个，避免把"待指定账户"混进解析问题里。
    options = ParseOptions(document_kind=KIND, bank_account_ref="ACCT-CORPUS")
    return extract_workbook(content, options, "2026-03", resolver=resolver)


def learn(content: bytes, store: ProfileStore) -> list[str]:
    """对未识别的工作表提案版式，验证后登记。返回登记说明。"""
    learned = []
    try:
        sheets = read_workbook(content)
    except Exception as exc:
        return [f"ABSTAIN 读取失败：{type(exc).__name__}"]
    for sheet in sheets:
        proposal = propose_mapping(sheet, KIND)
        if proposal.outcome != "PROPOSAL" or proposal.mapping is None:
            learned.append(f"ABSTAIN {sheet['name'][:12]}：{proposal.reason}")
            continue
        header = next((r for r in sheet["rows"] if r["row"] == proposal.header_row), None)
        if header is None:
            continue
        key = fingerprint(header["values"], KIND)
        if store.resolve(fingerprint_value=key, document_kind=KIND, count_hit=False):
            continue
        store.record(fingerprint_value=key, document_kind=KIND,
                     label=proposal.label_hint or sheet["name"], mapping=proposal.mapping,
                     origin="AGENT", confidence=proposal.confidence)
        learned.append(f"{proposal.confidence}% {proposal.mapping.amount_model} :: " + "；".join(proposal.evidence))
    return learned


def verdict(result) -> tuple[str, int, int]:
    records = result["records"]
    clean = sum(1 for r in records if not r.get("extraction_issues"))
    if not records:
        return "零记录", 0, 0
    return ("OK" if clean == len(records) else "带问题"), len(records), len(records) - clean


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / ".data"
    files = corpus(root)
    if not files:
        print(f"语料目录为空：{root}")
        return 1

    temporary = Path(tempfile.mkdtemp())
    settings = Settings(root=Path(__file__).resolve().parents[1],
                        database_path=temporary / "corpus.db", storage_path=temporary / "artifacts",
                        require_auth=False)
    database = Database(settings)
    database.initialize()
    store = ProfileStore(database)

    before, after, notes = {}, {}, {}
    # 一、基线：只有别名表。
    for path in files:
        try:
            before[path.name] = verdict(parse(path.read_bytes(), None))
        except Exception as exc:
            before[path.name] = (f"失败({type(exc).__name__})", 0, 0)
    # 二、学习：版式一旦登记就对同模板的所有文件生效，因此先全量学完再评估。
    for path in files:
        if before[path.name][0] != "OK":
            notes[path.name] = learn(path.read_bytes(), store)
    # 三、评估：别名表 + 版式库。
    for path in files:
        try:
            after[path.name] = verdict(parse(path.read_bytes(), store))
        except Exception as exc:
            after[path.name] = (f"失败({type(exc).__name__})", 0, 0)

    print(f"{'文件':<50}{'别名表':<20}{'＋版式库':<20}{'新学到的版式'}")
    print("-" * 165)
    for path in files:
        name = path.name
        b, a = before[name], after[name]
        note = (notes.get(name) or [""])[0][:62]
        print(f"{name[:48]:<50}{b[0] + ' ' + str(b[1]):<20}{a[0] + ' ' + str(a[1]):<20}{note}")
    print("-" * 165)
    ok_before = sum(1 for v in before.values() if v[0] == "OK")
    ok_after = sum(1 for v in after.values() if v[0] == "OK")
    rows_before = sum(v[1] for v in before.values())
    rows_after = sum(v[1] for v in after.values())
    print(f"整文件通过： {ok_before}/{len(files)}  ->  {ok_after}/{len(files)}")
    tally: Counter = Counter()
    for path in files:
        try:
            for record in parse(path.read_bytes(), store)["records"]:
                for issue in record.get("extraction_issues", []):
                    tally[issue.split("：")[0]] += 1
        except Exception:
            pass
    print("剩余问题分布：", dict(tally.most_common(8)))
    print(f"提取记录数： {rows_before}  ->  {rows_after}")
    print(f"登记版式数： {len(store.list_profiles())}")
    print("分布：", dict(Counter(v[0] for v in after.values())))
    profiles = store.list_profiles()
    reused = len(files) - len(profiles)
    print(f"版式复用：{len(profiles)} 份版式覆盖 {len(files)} 个文件"
          f"（{reused} 个文件命中既有版式，无需再次提案）")
    low = [p for p in profiles if p.confidence < 70]
    print(f"需人工确认的低置信版式：{len(low)}", [f"{p.confidence}% {p.label[:26]}" for p in low])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
