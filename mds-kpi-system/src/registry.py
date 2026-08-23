"""The KPI registry, loaded from config/kpis.yaml.

config/kpis.yaml is the single source of truth. Nothing in this repo may invent
a metric_id that is not in it, and run_weekly refuses to write a snapshot for an
unknown id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "config" / "kpis.yaml"


@dataclass(frozen=True)
class KpiSpec:
    id: str
    name: str
    department: str
    owner: str
    type: str                       # predictive | responsive
    sources: tuple[str, ...]
    definition: str
    sub_metric_specs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Registry:
    kpis: dict[str, KpiSpec]

    def __getitem__(self, metric_id: str) -> KpiSpec:
        try:
            return self.kpis[metric_id]
        except KeyError:
            raise KeyError(
                f"unknown metric_id {metric_id!r}. Add it to config/kpis.yaml first."
            ) from None

    def __contains__(self, metric_id: str) -> bool:
        return metric_id in self.kpis

    def __len__(self) -> int:
        return len(self.kpis)

    @property
    def departments(self) -> list[str]:
        seen: list[str] = []
        for spec in self.kpis.values():
            if spec.department not in seen:
                seen.append(spec.department)
        return seen

    def for_department(self, department: str) -> list[KpiSpec]:
        return [s for s in self.kpis.values() if s.department == department]

    def owner_of(self, department: str) -> str:
        specs = self.for_department(department)
        return specs[0].owner if specs else "unassigned"


def load(path: str | Path | None = None) -> Registry:
    raw = yaml.safe_load(Path(path or DEFAULT_PATH).read_text())
    kpis: dict[str, KpiSpec] = {}
    for department, block in (raw.get("departments") or {}).items():
        owner = (block or {}).get("owner", "unassigned")
        for entry in (block or {}).get("kpis") or []:
            spec = KpiSpec(
                id=entry["id"],
                name=entry["name"],
                department=department,
                owner=owner,
                type=entry.get("type", "responsive"),
                sources=tuple(entry.get("source") or []),
                definition=" ".join((entry.get("definition") or "").split()),
                sub_metric_specs=tuple(entry.get("sub_metrics") or []),
            )
            if spec.id in kpis:
                raise ValueError(f"duplicate metric id in kpis.yaml: {spec.id}")
            kpis[spec.id] = spec
    return Registry(kpis=kpis)


@lru_cache(maxsize=1)
def default() -> Registry:
    return load()
