from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import HistoricalBalanceRow, MonthlyWorkPackage, Voucher, VoucherEntry
from app.schemas.ledger import (
    AccountOptionRead,
    DetailLedgerRowRead,
    GeneralLedgerRowRead,
    JournalLedgerRowRead,
    LedgerSummaryRead,
    TrialBalanceRead,
)


CONFIRMED_STATUS = "CONFIRMED"
MONEY_QUANT = Decimal("0.01")
CURRENT_ACCOUNT_PREFIXES = ("1122", "1123", "1221", "2202", "2203", "2241")


class LedgerService:
    def __init__(self, db: Session):
        self.db = db

    def get_summary(self, package_id: UUID) -> LedgerSummaryRead:
        confirmed_count = self._voucher_count(package_id, CONFIRMED_STATUS)
        pending_count = self._pending_voucher_count(package_id)
        entry_count = self.db.scalar(
            select(func.count(VoucherEntry.id))
            .join(Voucher, Voucher.id == VoucherEntry.voucher_id)
            .where(Voucher.monthly_work_package_id == package_id, Voucher.status == CONFIRMED_STATUS)
        )
        return LedgerSummaryRead(
            confirmed_voucher_count=confirmed_count,
            pending_voucher_count=pending_count,
            entry_count=entry_count or 0,
            is_final=pending_count == 0,
        )

    def get_account_options(self, package_id: UUID) -> list[AccountOptionRead]:
        rows = self.get_general(package_id)
        return [
            AccountOptionRead(
                account_code=row.account_code,
                account_name=row.account_name,
                account_category=row.account_category,
            )
            for row in rows
        ]

    def get_journal(self, package_id: UUID) -> list[JournalLedgerRowRead]:
        rows: list[JournalLedgerRowRead] = []
        for voucher in self._confirmed_vouchers(package_id):
            for entry in voucher.entries:
                debit_amount = _money(entry.amount) if entry.direction == "DEBIT" else Decimal("0.00")
                credit_amount = _money(entry.amount) if entry.direction == "CREDIT" else Decimal("0.00")
                rows.append(
                    JournalLedgerRowRead(
                        voucher_id=str(voucher.id),
                        voucher_entry_id=str(entry.id),
                        voucher_date=voucher.voucher_date,
                        voucher_number=voucher.voucher_number or "未编号",
                        summary=voucher.summary,
                        account_code=entry.account_code,
                        account_name=entry.account_name,
                        direction=entry.direction,
                        direction_label=_direction_label(entry.direction),
                        debit_amount=debit_amount,
                        credit_amount=credit_amount,
                        source_type=entry.source_type,
                    )
                )
        return rows

    def get_general(self, package_id: UUID) -> list[GeneralLedgerRowRead]:
        grouped: dict[str, dict[str, Decimal | str]] = self._opening_balance_buckets(package_id)
        for voucher in self._confirmed_vouchers(package_id):
            for entry in voucher.entries:
                bucket = grouped.setdefault(
                    entry.account_code,
                    {
                        "account_name": entry.account_name,
                        "opening_debit": Decimal("0.00"),
                        "opening_credit": Decimal("0.00"),
                        "period_debit": Decimal("0.00"),
                        "period_credit": Decimal("0.00"),
                    },
                )
                if not bucket.get("account_name"):
                    bucket["account_name"] = entry.account_name
                if entry.direction == "DEBIT":
                    bucket["period_debit"] = _money(bucket["period_debit"]) + _money(entry.amount)
                else:
                    bucket["period_credit"] = _money(bucket["period_credit"]) + _money(entry.amount)

        return [
            self._build_general_row(
                account_code=account_code,
                account_name=str(values["account_name"]),
                opening_debit=_money(values["opening_debit"]),
                opening_credit=_money(values["opening_credit"]),
                period_debit=_money(values["period_debit"]),
                period_credit=_money(values["period_credit"]),
            )
            for account_code, values in sorted(grouped.items())
        ]

    def get_detail(self, package_id: UUID, account_code: str) -> list[DetailLedgerRowRead]:
        rows: list[DetailLedgerRowRead] = []
        balance_direction = _normal_balance(account_code)
        opening_bucket = self._opening_balance_buckets(package_id).get(account_code)
        running_balance = self._opening_running_balance(opening_bucket, balance_direction)
        if opening_bucket and running_balance != Decimal("0.00"):
            package = self.db.get(MonthlyWorkPackage, package_id)
            rows.append(
                DetailLedgerRowRead(
                    voucher_id=f"opening:{package_id}:{account_code}",
                    voucher_entry_id=f"opening:{package_id}:{account_code}",
                    voucher_date=date(package.period_year, package.period_month, 1) if package else date.today(),
                    voucher_number="-",
                    summary="期初余额",
                    counter_accounts="-",
                    counter_account_display="-",
                    debit_amount=Decimal("0.00"),
                    credit_amount=Decimal("0.00"),
                    balance_direction=balance_direction,
                    balance_direction_label=_balance_direction_label(balance_direction),
                    balance=_money(running_balance),
                )
            )
        for voucher in self._confirmed_vouchers(package_id):
            matching_entries = [entry for entry in voucher.entries if entry.account_code == account_code]
            if not matching_entries:
                continue
            counter_detail = _counter_account_detail(voucher, account_code)
            for entry in matching_entries:
                debit_amount = _money(entry.amount) if entry.direction == "DEBIT" else Decimal("0.00")
                credit_amount = _money(entry.amount) if entry.direction == "CREDIT" else Decimal("0.00")
                if balance_direction == "DEBIT":
                    running_balance = running_balance + debit_amount - credit_amount
                else:
                    running_balance = running_balance + credit_amount - debit_amount
                rows.append(
                    DetailLedgerRowRead(
                        voucher_id=str(voucher.id),
                        voucher_entry_id=str(entry.id),
                        voucher_date=voucher.voucher_date,
                        voucher_number=voucher.voucher_number or "未编号",
                        summary=voucher.summary,
                        counter_accounts=counter_detail["counter_accounts"],
                        counter_account_display=counter_detail["counter_account_display"],
                        counter_account_name=counter_detail["counter_account_name"],
                        counter_auxiliary_type=counter_detail["counter_auxiliary_type"],
                        counter_auxiliary_name=counter_detail["counter_auxiliary_name"],
                        debit_amount=debit_amount,
                        credit_amount=credit_amount,
                        balance_direction=balance_direction,
                        balance_direction_label=_balance_direction_label(balance_direction),
                        balance=_money(running_balance),
                    )
                )
        return rows

    def _opening_running_balance(self, opening_bucket: dict[str, Decimal | str] | None, balance_direction: str) -> Decimal:
        if not opening_bucket:
            return Decimal("0.00")
        opening_debit = _money(opening_bucket["opening_debit"])
        opening_credit = _money(opening_bucket["opening_credit"])
        if balance_direction == "DEBIT":
            return _money(opening_debit - opening_credit)
        return _money(opening_credit - opening_debit)

    def get_trial_balance(self, package_id: UUID) -> TrialBalanceRead:
        parent_rows = self.get_general(package_id)
        auxiliary_rows = self._build_auxiliary_rows(package_id)
        rows = self._interleave_trial_rows(parent_rows, auxiliary_rows)
        opening_debit_total = _sum(row.opening_debit for row in parent_rows)
        opening_credit_total = _sum(row.opening_credit for row in parent_rows)
        period_debit_total = _sum(row.period_debit for row in parent_rows)
        period_credit_total = _sum(row.period_credit for row in parent_rows)
        closing_debit_total = _sum(row.closing_debit for row in parent_rows)
        closing_credit_total = _sum(row.closing_credit for row in parent_rows)
        period_diff = abs(period_debit_total - period_credit_total)
        closing_diff = abs(closing_debit_total - closing_credit_total)
        difference = _money(max(period_diff, closing_diff))
        return TrialBalanceRead(
            rows=rows,
            opening_debit_total=opening_debit_total,
            opening_credit_total=opening_credit_total,
            period_debit_total=period_debit_total,
            period_credit_total=period_credit_total,
            closing_debit_total=closing_debit_total,
            closing_credit_total=closing_credit_total,
            is_balanced=difference == Decimal("0.00"),
            difference=difference,
        )

    def _confirmed_vouchers(self, package_id: UUID) -> list[Voucher]:
        return list(
            self.db.scalars(
                select(Voucher)
                .options(joinedload(Voucher.entries))
                .where(Voucher.monthly_work_package_id == package_id, Voucher.status == CONFIRMED_STATUS)
                .order_by(Voucher.voucher_date.asc(), Voucher.voucher_number.asc(), Voucher.created_at.asc())
            )
            .unique()
            .all()
        )

    def _voucher_count(self, package_id: UUID, status: str) -> int:
        return (
            self.db.scalar(
                select(func.count(Voucher.id)).where(
                    Voucher.monthly_work_package_id == package_id,
                    Voucher.status == status,
                )
            )
            or 0
        )

    def _pending_voucher_count(self, package_id: UUID) -> int:
        return (
            self.db.scalar(
                select(func.count(Voucher.id)).where(
                    Voucher.monthly_work_package_id == package_id,
                    Voucher.status != CONFIRMED_STATUS,
                )
            )
            or 0
        )

    def _build_general_row(
        self,
        *,
        account_code: str,
        account_name: str,
        opening_debit: Decimal = Decimal("0.00"),
        opening_credit: Decimal = Decimal("0.00"),
        period_debit: Decimal,
        period_credit: Decimal,
        row_type: str = "ACCOUNT",
        parent_account_code: str | None = None,
        auxiliary_type: str | None = None,
        auxiliary_code: str | None = None,
        auxiliary_name: str | None = None,
        display_code: str | None = None,
        display_name: str | None = None,
        level: int = 0,
        is_expandable: bool = False,
    ) -> GeneralLedgerRowRead:
        balance_direction = _normal_balance(account_code)
        opening_debit = _money(opening_debit)
        opening_credit = _money(opening_credit)
        if balance_direction == "DEBIT":
            net_balance = opening_debit - opening_credit + period_debit - period_credit
        else:
            net_balance = opening_credit - opening_debit + period_credit - period_debit
        closing_debit = _money(net_balance) if balance_direction == "DEBIT" and net_balance > 0 else Decimal("0.00")
        closing_credit = _money(net_balance) if balance_direction == "CREDIT" and net_balance > 0 else Decimal("0.00")
        if net_balance < 0 and balance_direction == "DEBIT":
            closing_credit = _money(abs(net_balance))
        if net_balance < 0 and balance_direction == "CREDIT":
            closing_debit = _money(abs(net_balance))
        return GeneralLedgerRowRead(
            account_code=account_code,
            account_name=account_name,
            account_category=_account_category(account_code),
            balance_direction=balance_direction,
            balance_direction_label=_balance_direction_label(balance_direction),
            opening_debit=opening_debit,
            opening_credit=opening_credit,
            period_debit=_money(period_debit),
            period_credit=_money(period_credit),
            closing_debit=closing_debit,
            closing_credit=closing_credit,
            row_type=row_type,
            parent_account_code=parent_account_code,
            auxiliary_type=auxiliary_type,
            auxiliary_code=auxiliary_code,
            auxiliary_name=auxiliary_name,
            display_code=display_code or account_code,
            display_name=display_name or account_name,
            level=level,
            is_expandable=is_expandable,
        )

    def _opening_balance_buckets(self, package_id: UUID) -> dict[str, dict[str, Decimal | str]]:
        package = self.db.get(MonthlyWorkPackage, package_id)
        if not package:
            return {}
        rows = list(
            self.db.scalars(
                select(HistoricalBalanceRow)
                .where(
                    HistoricalBalanceRow.enterprise_id == package.enterprise_id,
                    HistoricalBalanceRow.fiscal_year <= package.period_year,
                )
                .order_by(HistoricalBalanceRow.fiscal_year.desc(), HistoricalBalanceRow.created_at.desc())
            )
        )
        grouped: dict[str, dict[str, Decimal | str]] = {}
        seen: set[str] = set()
        for row in rows:
            if row.account_code in seen:
                continue
            seen.add(row.account_code)
            grouped[row.account_code] = {
                "account_name": row.account_name,
                "opening_debit": _money(row.opening_debit),
                "opening_credit": _money(row.opening_credit),
                "period_debit": Decimal("0.00"),
                "period_credit": Decimal("0.00"),
            }
        return grouped

    def _build_auxiliary_rows(self, package_id: UUID) -> list[GeneralLedgerRowRead]:
        grouped: dict[tuple[str, str, str], dict[str, Decimal | str]] = {}
        for voucher in self._confirmed_vouchers(package_id):
            for entry in voucher.entries:
                auxiliary = _entry_auxiliary(voucher, entry)
                if not auxiliary:
                    continue
                auxiliary_type, auxiliary_name, auxiliary_code = auxiliary
                key = (entry.account_code, auxiliary_type, auxiliary_name)
                bucket = grouped.setdefault(
                    key,
                    {
                        "account_name": entry.account_name,
                        "auxiliary_code": auxiliary_code,
                        "period_debit": Decimal("0.00"),
                        "period_credit": Decimal("0.00"),
                    },
                )
                if entry.direction == "DEBIT":
                    bucket["period_debit"] = _money(bucket["period_debit"]) + _money(entry.amount)
                else:
                    bucket["period_credit"] = _money(bucket["period_credit"]) + _money(entry.amount)

        rows: list[GeneralLedgerRowRead] = []
        for (account_code, auxiliary_type, auxiliary_name), values in sorted(grouped.items()):
            rows.append(
                self._build_general_row(
                    account_code=account_code,
                    account_name=auxiliary_name,
                    opening_debit=Decimal("0.00"),
                    opening_credit=Decimal("0.00"),
                    period_debit=_money(values["period_debit"]),
                    period_credit=_money(values["period_credit"]),
                    row_type="AUXILIARY",
                    parent_account_code=account_code,
                    auxiliary_type=auxiliary_type,
                    auxiliary_code=str(values["auxiliary_code"] or auxiliary_name),
                    auxiliary_name=auxiliary_name,
                    display_code=str(values["auxiliary_code"] or ""),
                    display_name=auxiliary_name,
                    level=1,
                )
            )
        return rows

    def _interleave_trial_rows(
        self,
        parent_rows: list[GeneralLedgerRowRead],
        auxiliary_rows: list[GeneralLedgerRowRead],
    ) -> list[GeneralLedgerRowRead]:
        children_by_parent: dict[str, list[GeneralLedgerRowRead]] = defaultdict(list)
        for row in auxiliary_rows:
            if row.parent_account_code:
                children_by_parent[row.parent_account_code].append(row)

        rows: list[GeneralLedgerRowRead] = []
        for parent in parent_rows:
            children = children_by_parent.get(parent.account_code, [])
            rows.append(parent.model_copy(update={"is_expandable": bool(children)}))
            rows.extend(children)
        return rows


def _money(value: Decimal | str) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _sum(values) -> Decimal:
    total = Decimal("0.00")
    for value in values:
        total += _money(value)
    return _money(total)


def _direction_label(direction: str) -> str:
    return {"DEBIT": "借方", "CREDIT": "贷方"}.get(direction, direction)


def _normal_balance(account_code: str) -> str:
    if account_code.startswith(("2", "3", "6")):
        return "CREDIT"
    return "DEBIT"


def _balance_direction_label(direction: str) -> str:
    return {"DEBIT": "借方", "CREDIT": "贷方"}.get(direction, direction)


def _account_category(account_code: str) -> str:
    first_digit = account_code[:1]
    return {
        "1": "资产",
        "2": "负债",
        "3": "权益",
        "4": "成本",
        "5": "损益",
        "6": "损益",
    }.get(first_digit, "其他")


def _counter_accounts(entries: list[VoucherEntry], account_code: str) -> str:
    names = []
    for entry in entries:
        if entry.account_code == account_code:
            continue
        label = entry.account_name or entry.account_code
        if label not in names:
            names.append(label)
    return "、".join(names)


def _counter_account_detail(voucher: Voucher, account_code: str) -> dict[str, str | None]:
    account_names: list[str] = []
    displays: list[str] = []
    auxiliary_types: list[str] = []
    auxiliary_names: list[str] = []

    for entry in voucher.entries:
        if entry.account_code == account_code:
            continue
        account_name = entry.account_name or entry.account_code
        if account_name not in account_names:
            account_names.append(account_name)

        auxiliary = _entry_auxiliary(voucher, entry)
        auxiliary_type = auxiliary[0] if auxiliary else None
        auxiliary_name = auxiliary[1] if auxiliary else None
        if auxiliary_type and auxiliary_type not in auxiliary_types:
            auxiliary_types.append(auxiliary_type)
        if auxiliary_name and auxiliary_name not in auxiliary_names:
            auxiliary_names.append(auxiliary_name)

        display = f"{account_name} / {auxiliary_name}" if auxiliary_name else account_name
        if display not in displays:
            displays.append(display)

    counter_accounts = "、".join(account_names)
    return {
        "counter_accounts": counter_accounts,
        "counter_account_display": "、".join(displays) or counter_accounts,
        "counter_account_name": counter_accounts or None,
        "counter_auxiliary_type": "、".join(auxiliary_types) or None,
        "counter_auxiliary_name": "、".join(auxiliary_names) or None,
    }


def _entry_auxiliary(voucher: Voucher, entry: VoucherEntry) -> tuple[str, str, str] | None:
    if entry.account_code.startswith("1002"):
        bank_account = _first_text(
            voucher.source_data,
            (
                ("bank_account_name",),
                ("bank_name",),
                ("account_name",),
                ("bank", "account_name"),
                ("bank", "bank_name"),
                ("bank", "account_no"),
                ("transaction", "account_name"),
                ("transaction", "bank_name"),
                ("transaction", "account_no"),
                ("bank_transaction", "account_name"),
                ("bank_transaction", "bank_name"),
                ("bank_transaction", "account_no"),
            ),
        )
        return ("BANK_ACCOUNT", bank_account or "默认银行账户", "")

    if not entry.account_code.startswith(CURRENT_ACCOUNT_PREFIXES):
        return None

    counterparty = _first_text(
        voucher.source_data,
        (
            ("counterparty_name",),
            ("counterparty",),
            ("invoice", "counterparty_name"),
            ("invoice", "seller_name"),
            ("invoice", "buyer_name"),
            ("bank", "counterparty_name"),
            ("transaction", "counterparty_name"),
            ("bank_transaction", "counterparty_name"),
        ),
    )
    if not counterparty or counterparty == "-":
        return None
    return ("COUNTERPARTY", counterparty, "")


def _first_text(source: dict | None, paths: tuple[tuple[str, ...], ...]) -> str | None:
    if not isinstance(source, dict):
        return None
    for path in paths:
        value = source
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
