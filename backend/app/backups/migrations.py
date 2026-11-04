from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any, Callable, Protocol

from app.backups.constants import CURRENT_FORMAT_VERSION, DATA_MEMBERS


class BackupMigrationError(Exception):
    """A sanitized backup-version migration failure."""


class MissingMigrationPath(BackupMigrationError):
    pass


class ArchiveLike(Protocol):
    path: Path

    @property
    def format_version(self) -> int: ...

    def iter_source_rows(self, member: str) -> Iterator[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class MigratedArchive:
    source: ArchiveLike
    format_version: int
    transforms: tuple[Callable[[str, dict[str, Any]], dict[str, Any]], ...] = ()

    @property
    def path(self) -> Path:
        return self.source.path

    def iter_rows(self, member: str) -> Iterator[dict[str, Any]]:
        if member not in DATA_MEMBERS:
            # Format 2 shipped extra ledger/decision members. Current callers
            # never request them; they are verified and then ignored.
            return
        for source_row in self.source.iter_source_rows(member):
            row = source_row
            for transform in self.transforms:
                row = transform(member, row)
            yield row


Migration = Callable[[str, dict[str, Any]], dict[str, Any]]

_DECIMAL_QUANTUM = Decimal("0.000000000001")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _canonical_decimal(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 60
        return format(value.quantize(_DECIMAL_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _recompute_snapshot_reference_cost(row: dict[str, Any]) -> None:
    """Rebuild the CNY reference cost/PnL from the snapshot's own current FX."""
    quantity = _decimal(row.get("quantity"))
    average_cost = _decimal(row.get("average_cost_price"))
    current_fx = _decimal(row.get("current_fx_to_cny"))
    market_value = _decimal(row.get("market_value_cny"))

    if quantity is None or average_cost is None or current_fx is None:
        row["cost_value_cny"] = None
        row["unrealized_pnl_amount_cny"] = None
        row["unrealized_pnl_rate"] = None
        return

    with localcontext() as context:
        context.prec = 60
        cost = quantity * average_cost * current_fx
        row["cost_value_cny"] = _canonical_decimal(cost)
        if market_value is None:
            row["unrealized_pnl_amount_cny"] = None
            row["unrealized_pnl_rate"] = None
            return
        pnl = market_value - cost
        row["unrealized_pnl_amount_cny"] = _canonical_decimal(pnl)
        rate = pnl / cost if cost != 0 else Decimal("0")
        row["unrealized_pnl_rate"] = _canonical_decimal(rate)


def _v2_to_v3(member: str, row: dict[str, Any]) -> dict[str, Any]:
    """Remove manual cost-FX fields and the FX PnL attribution."""
    if member == "data/holdings.json":
        row.pop("cost_fx_to_cny", None)
        row.pop("baseline_fx_to_cny", None)
    elif member == "data/cost_adjustments.json":
        row.pop("before_cost_fx_to_cny", None)
        row.pop("after_cost_fx_to_cny", None)
    elif member == "data/snapshot_items.json":
        _recompute_snapshot_reference_cost(row)
        for column in (
            "baseline_fx_to_cny",
            "cost_fx_to_cny",
            "fx_neutral_value_cny",
            "price_effect_cny",
            "fx_effect_cny",
            "fx_neutral_weight",
        ):
            row.pop(column, None)
    elif member == "data/settings.json":
        row.pop("rebalance_valuation_basis", None)
    elif member == "data/rebalance_plans.json":
        row.pop("strategy_mode", None)
        row.pop("baseline_reset_at", None)
        input_summary = row.get("input_summary")
        if isinstance(input_summary, dict):
            input_summary.pop("valuation_basis", None)
        projected_result = row.get("projected_result")
        if isinstance(projected_result, dict):
            projected_result.pop("valuation_basis", None)
            projected_result.pop("fx_comparison", None)
    return row


# Each entry upgrades exactly one version.  Current-version archives need no
# transform; older versions are streamed through these ordered row transforms.
MIGRATIONS: dict[int, Migration] = {
    1: lambda member, row: row,
    2: _v2_to_v3,
}


def require_migration_path(source_version: int) -> None:
    version = source_version
    while version < CURRENT_FORMAT_VERSION:
        if version not in MIGRATIONS:
            raise MissingMigrationPath("no supported migration path for backup format")
        version += 1
    if version != CURRENT_FORMAT_VERSION:
        raise MissingMigrationPath("no supported migration path for backup format")


def migrate_to_current(archive: ArchiveLike) -> MigratedArchive:
    require_migration_path(archive.format_version)
    transforms = tuple(MIGRATIONS[version] for version in range(archive.format_version, CURRENT_FORMAT_VERSION))
    return MigratedArchive(source=archive, format_version=CURRENT_FORMAT_VERSION, transforms=transforms)
