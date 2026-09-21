"""扫描件银行对账单：模型必须读出数值，因此安全性改由对账单自带的真值保证。

其余解析路径守的是"模型只给指针，不给数值"——Excel 有单元格网格，模型可以说
"金额在第 5 列"。扫描件没有网格，模型只能直接读数。这条线在这里必然断掉。

换来的保证是：银行对账单是自证的。表头写明借贷笔数与合计、期末余额，行与行之间
还有余额连续性。模型读出的每一位数字都要同时通过这几道校验才能落库——读错一位，
至少有一道会崩。任何一道不过，整份退回为待人工核对，绝不部分采信。
"""
from __future__ import annotations

import base64
import re
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Iterable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

READER_VERSION = "scanned-statement-v1"
# 单张图在模型侧最多折算 1024 token，整页会被缩到约 1300×1300 等效像素。
# 校验没过时把页面横向切条重读，每条各自享有完整的 token 预算。
STRIP_OVERLAP_RATIO = 0.06
MAX_STRIPS_PER_PAGE = 6
CENT = Decimal("0.01")


class ScannedStatementError(ValueError):
    pass


def _money(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(CENT)
    text = str(value if value is not None else "").strip().replace(",", "").replace("￥", "")
    if text in {"", "-", "--"}:
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"金额无法识别：{value!r}") from exc


class StatementTotals(BaseModel):
    """对账单表头自报的合计。这些数字是校验模型读数的标尺。"""

    model_config = ConfigDict(extra="forbid")

    closing_balance: Decimal
    debit_count: StrictInt = Field(ge=0)
    debit_total: Decimal
    credit_count: StrictInt = Field(ge=0)
    credit_total: Decimal
    total_count: StrictInt = Field(ge=0)

    @field_validator("closing_balance", "debit_total", "credit_total", mode="before")
    @classmethod
    def parse_money(cls, value):
        return _money(value)


class StatementRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: StrictInt = Field(ge=1)
    transaction_date: StrictStr
    summary: StrictStr = ""
    # 银行视角：借方是账户支出，贷方是账户收入。与账簿视角正好相反，
    # 这里保留银行原始口径，方向换算留给下游，避免在读数阶段就把方向搞反。
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    balance: Decimal
    counterparty_account: StrictStr = ""
    counterparty_name: StrictStr = ""

    @field_validator("debit", "credit", "balance", mode="before")
    @classmethod
    def parse_money(cls, value):
        return _money(value)

    @field_validator("transaction_date")
    @classmethod
    def iso_date(cls, value: str) -> str:
        text = value.strip().replace("/", "-").replace(".", "-")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError(f"交易日期必须是 YYYY-MM-DD：{value!r}")
        return text


class ScannedStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_name: StrictStr = ""
    account_number: StrictStr = ""
    currency: StrictStr = ""
    period_start: StrictStr = ""
    period_end: StrictStr = ""
    totals: StatementTotals
    rows: list[StatementRow] = Field(min_length=1)


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    passed: bool
    detail: StrictStr = ""


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["ACCEPTED", "REVIEW"]
    checks: list[CheckResult]
    opening_balance: Optional[Decimal] = None

    @property
    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]


def verify(statement: ScannedStatement) -> VerificationReport:
    """五道独立校验，全过才算读对。任何一道不过都退回人工，不部分采信。"""
    rows, totals = statement.rows, statement.totals
    checks: list[CheckResult] = []

    checks.append(CheckResult(
        name="笔数与表头一致", passed=len(rows) == totals.total_count,
        detail=f"表头 {totals.total_count} 笔，读出 {len(rows)} 笔"))

    debits = [r for r in rows if r.debit > 0]
    credits = [r for r in rows if r.credit > 0]
    debit_sum = sum((r.debit for r in debits), Decimal("0.00"))
    credit_sum = sum((r.credit for r in credits), Decimal("0.00"))
    checks.append(CheckResult(
        name="借方笔数与合计一致",
        passed=len(debits) == totals.debit_count and debit_sum == totals.debit_total,
        detail=f"表头 {totals.debit_count} 笔 / {totals.debit_total}，读出 {len(debits)} 笔 / {debit_sum}"))
    checks.append(CheckResult(
        name="贷方笔数与合计一致",
        passed=len(credits) == totals.credit_count and credit_sum == totals.credit_total,
        detail=f"表头 {totals.credit_count} 笔 / {totals.credit_total}，读出 {len(credits)} 笔 / {credit_sum}"))

    checks.append(CheckResult(
        name="末行余额等于表头期末余额",
        passed=rows[-1].balance == totals.closing_balance,
        detail=f"表头 {totals.closing_balance}，末行 {rows[-1].balance}"))

    # 余额连续性：余额ₜ = 余额ₜ₋₁ − 借方ₜ + 贷方ₜ（银行视角，借方减少余额）
    breaks = []
    for previous, current in zip(rows, rows[1:]):
        expected = previous.balance - current.debit + current.credit
        if expected != current.balance:
            breaks.append(f"第{current.sequence}行 期望 {expected} 实际 {current.balance}")
    checks.append(CheckResult(
        name="行间余额连续", passed=not breaks,
        detail="；".join(breaks[:3]) if breaks else f"{len(rows) - 1} 处衔接全部成立"))

    opening = rows[0].balance + rows[0].debit - rows[0].credit
    derived_closing = opening - totals.debit_total + totals.credit_total
    checks.append(CheckResult(
        name="期初倒算与期末吻合",
        passed=derived_closing == totals.closing_balance,
        detail=f"期初 {opening} − {totals.debit_total} + {totals.credit_total} = {derived_closing}"))

    passed = all(check.passed for check in checks)
    return VerificationReport(outcome="ACCEPTED" if passed else "REVIEW",
                              checks=checks, opening_balance=opening)


# ---------- 图像取出 ----------

def page_images(content: bytes) -> list[bytes]:
    """取出 PDF 每页的内嵌图。扫描件通常每页正好一张。"""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise ScannedStatementError("加密 PDF 无法读取，请提供未加密的对账单")
    images: list[bytes] = []
    for page in reader.pages:
        for image in page.images:
            images.append(image.data)
    if not images:
        raise ScannedStatementError("该 PDF 里没有可取出的图像")
    return images


def is_image_only_pdf(content: bytes, threshold: int = 200) -> bool:
    """是不是"能打开、有内嵌图、但几乎没有文字"的扫描件。

    只有同时满足这三点才算扫描件。损坏的 PDF 不在此列 —— 那是真的读不了，
    应当沿原路明确失败，而不是伪装成"等待图像识别"。
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or not reader.pages:
            return False
        text = sum(len(page.extract_text() or "") for page in reader.pages)
        if text >= threshold:
            return False
        return any(True for page in reader.pages for _ in page.images)
    except Exception:
        return False


def horizontal_strips(image: bytes, count: int) -> list[bytes]:
    """把一页横向切成若干带重叠的条。

    整页会被模型缩到约 1300×1300 等效像素，小字号的金额容易糊。切条之后
    每一条各自享有完整的分辨率预算，重叠是为了不让跨切口的那一行丢失。
    """
    from PIL import Image

    count = max(1, min(count, MAX_STRIPS_PER_PAGE))
    with Image.open(BytesIO(image)) as source:
        width, height = source.size
        band = height / count
        overlap = int(band * STRIP_OVERLAP_RATIO)
        strips: list[bytes] = []
        for index in range(count):
            top = max(0, int(index * band) - overlap)
            bottom = min(height, int((index + 1) * band) + overlap)
            buffer = BytesIO()
            source.crop((0, top, width, bottom)).save(buffer, format="PNG")
            strips.append(buffer.getvalue())
    return strips


def data_url(image: bytes) -> str:
    kind = "png"
    if image[:3] == b"\xff\xd8\xff":
        kind = "jpeg"
    elif image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        kind = "webp"
    elif image[:6] in (b"GIF87a", b"GIF89a"):
        kind = "gif"
    return f"data:image/{kind};base64," + base64.b64encode(image).decode("ascii")


# ---------- 读取 ----------

class StatementReader(Protocol):
    def read(self, images: Iterable[bytes], *, hint: str = "") -> dict[str, Any]:
        ...


def parse_statement(payload: dict[str, Any]) -> ScannedStatement:
    try:
        return ScannedStatement.model_validate(payload)
    except Exception as exc:
        raise ScannedStatementError(f"扫描件读数不符合约定结构：{exc}") from exc


def read_and_verify(content: bytes, reader: StatementReader) -> tuple[ScannedStatement, VerificationReport]:
    """先整页读，校验不过再切条重读一次。两次都不过就如实交回待人工核对。"""
    images = page_images(content)
    statement = parse_statement(reader.read(images))
    report = verify(statement)
    if report.outcome == "ACCEPTED":
        return statement, report

    retried: list[bytes] = []
    for image in images:
        retried.extend(horizontal_strips(image, MAX_STRIPS_PER_PAGE // 2))
    failures = "；".join(check.name for check in report.failures)
    second = parse_statement(reader.read(retried, hint=f"上一次读取未通过：{failures}"))
    second_report = verify(second)
    if second_report.outcome == "ACCEPTED":
        return second, second_report
    # 两次都没过时交回失败更少的那一份，供人工在卡片上核对。
    if len(second_report.failures) < len(report.failures):
        return second, second_report
    return statement, report
