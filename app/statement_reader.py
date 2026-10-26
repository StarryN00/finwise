"""把扫描件对账单交给视觉模型读出来。读数本身不被信任，交给校验器判定。"""
from __future__ import annotations

from typing import Any, Iterable

from app.scanned_statements import data_url

INSTRUCTION = (
    "这是一份银行对账单的扫描件。逐行抄录表格，不要归纳、不要省略、不要推算任何数字。"
    "只抄你确实看清的内容；看不清的字段留空字符串，绝不猜测。"
    "借方发生额是账户支出，贷方发生额是账户收入，按对账单原样抄录，不要换算方向。"
    "金额保留两位小数，去掉千分位逗号；日期写成 YYYY-MM-DD。"
    "如果同一页被切成多张图片，图片之间有重叠，同一笔交易只抄录一次（以序号为准）。"
)

SCHEMA_HINT = (
    "只返回一个 JSON 对象，不要任何解释文字。结构为："
    '{"account_name":"","account_number":"","currency":"","period_start":"YYYY-MM-DD",'
    '"period_end":"YYYY-MM-DD",'
    '"totals":{"closing_balance":"0.00","debit_count":0,"debit_total":"0.00",'
    '"credit_count":0,"credit_total":"0.00","total_count":0},'
    '"rows":[{"sequence":1,"transaction_date":"YYYY-MM-DD","summary":"","debit":"0.00",'
    '"credit":"0.00","balance":"0.00","counterparty_account":"","counterparty_name":""}]}。'
    "totals 必须抄自对账单表头自己印出来的笔数与合计，不得由你汇总得出——"
    "那几个数字是用来校验你抄录是否正确的，自己算就失去意义了。"
    "不得添加约定之外的字段。"
)


class GatewayStatementReader:
    """通过 Agent Gateway 的图像通道读取。"""

    def __init__(self, gateway_provider):
        self.provider = gateway_provider
        self.calls: list[dict[str, Any]] = []

    def read(self, images: Iterable[bytes], *, hint: str = "") -> dict[str, Any]:
        urls = [data_url(image) for image in images]
        output, metadata = self.provider.read_images(
            images=urls, instruction=INSTRUCTION, schema_hint=SCHEMA_HINT, hint=hint)
        self.calls.append(metadata)
        return output
