"""Human-reviewed opening balances with exact prior-close reconciliation."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_serializer, field_validator, model_validator

from app.ontology.contracts import SourceAnchor
from app.ontology.procurement import decimal_field

VALIDATION_VERSION = "baseline-v1"
AMOUNT_FIELDS = ("closing_debit", "closing_credit", "opening_debit", "opening_credit")


def previous_period(period: str) -> str:
    first = datetime.strptime(period + "-01", "%Y-%m-%d")
    if first.strftime("%Y-%m") != period:
        raise ValueError("会计期间必须为 YYYY-MM")
    return (first - timedelta(days=1)).strftime("%Y-%m")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BaselineAnchor(SourceAnchor):
    model_config = ConfigDict(extra="forbid", strict=True)


class BaselineSource(StrictModel):
    artifact_id: StrictStr = Field(min_length=1)
    version: StrictInt = Field(ge=1)
    anchor: BaselineAnchor

    @field_validator("anchor")
    @classmethod
    def located(cls, value):
        if not value.model_dump(exclude_none=True):
            raise ValueError("来源必须有页码、行号或区域定位")
        return value


class BalanceAmounts(StrictModel):
    closing_debit: Decimal
    closing_credit: Decimal
    opening_debit: Decimal
    opening_credit: Decimal
    source_anchor: BaselineAnchor

    @field_validator(*AMOUNT_FIELDS, mode="before")
    @classmethod
    def exact_money(cls, value):
        return decimal_field(value)

    @field_serializer(*AMOUNT_FIELDS)
    def serialize_money(self, value):
        return format(value, ".2f")

    @model_validator(mode="after")
    def reconcile(self):
        if not self.source_anchor.model_dump(exclude_none=True):
            raise ValueError("每项余额必须有原始资料定位")
        if self.closing_debit != self.opening_debit or self.closing_credit != self.opening_credit:
            raise ValueError("本期期初与上期期末余额不一致")
        return self


class AuxiliaryBalance(BalanceAmounts):
    key: StrictStr = Field(min_length=1)


class AccountBalance(BalanceAmounts):
    account_code: StrictStr = Field(min_length=1)
    account_name: StrictStr = Field(min_length=1)
    requires_auxiliary: StrictBool
    auxiliary: list[AuxiliaryBalance] = Field(default_factory=list)

    @model_validator(mode="after")
    def auxiliary_matches(self):
        if self.requires_auxiliary and not self.auxiliary:
            raise ValueError("需要辅助核算的科目缺少明细")
        if len({a.key for a in self.auxiliary}) != len(self.auxiliary):
            raise ValueError("同一科目的辅助核算明细重复")
        if self.auxiliary and any(sum((getattr(a, f) for a in self.auxiliary), Decimal(0)) != getattr(self, f) for f in AMOUNT_FIELDS):
            raise ValueError("辅助明细与科目控制余额不一致")
        return self


class BaselineConfirmation(StrictModel):
    prior_period: StrictStr
    close_reference: StrictStr = Field(min_length=1)
    balance_source: BaselineSource
    close_source: BaselineSource
    currency: Literal["CNY"]
    completeness_confirmed: StrictBool
    balances: list[AccountBalance] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_and_balanced(self):
        if not self.completeness_confirmed:
            raise ValueError("须核实科目、辅助明细和上期结账资料完整")
        if len({a.account_code for a in self.balances}) != len(self.balances):
            raise ValueError("基线科目重复，不能重复汇总")
        if sum((a.opening_debit - a.opening_credit for a in self.balances), Decimal(0)) != 0:
            raise ValueError("期初试算借贷不平衡")
        return self


def validate_confirmation(payload, period):
    confirmation = BaselineConfirmation.model_validate(payload)
    if confirmation.prior_period != previous_period(period):
        raise ValueError("期初必须衔接紧邻上期关闭资料，不能借用其他月份余额")
    totals = {side: format(sum((getattr(a, "opening_" + side) for a in confirmation.balances), Decimal(0)), ".2f") for side in ("debit", "credit")}
    return confirmation.model_dump(mode="json", exclude_none=True), totals
