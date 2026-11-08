"""Load a client's Layer 0 configuration from clients/<client>/."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]


def clients_dir() -> Path:
    return Path(os.environ.get("GTM_CLIENTS_DIR", REPO_ROOT / "clients"))


def data_dir() -> Path:
    path = Path(os.environ.get("GTM_DATA_DIR", REPO_ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


class Segment(BaseModel):
    name: str
    enabled: bool = True
    industry_group: str
    locations: list[str]
    max_items: int = 1000
    search_query: str | None = None


class IndustryGroup(BaseModel):
    label: str
    ids: list[int]


class CompanyRules(BaseModel):
    employees_min: int
    employees_max: int
    linkedin_company_sizes: list[str] = Field(default_factory=list)


class Exclusions(BaseModel):
    name_keywords: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class ICP(BaseModel):
    version: int = 1
    buyer_profile: str = ""
    offer_summary: str = ""
    company: CompanyRules
    industry_groups: dict[str, IndustryGroup]
    segments: list[Segment]
    allowed_countries: list[str]
    exclusions: Exclusions = Field(default_factory=Exclusions)
    personas: dict[str, list[str]] = Field(default_factory=dict)


class Limits(BaseModel):
    month_budget_usd: dict[str, float]
    unit_price_usd: dict[str, float] = Field(default_factory=dict)
    sending: dict[str, int] = Field(default_factory=dict)


class ClientConfig(BaseModel):
    slug: str
    root: Path
    client: dict[str, Any]
    icp: ICP
    limits: Limits
    scoring: dict[str, Any]
    ai: dict[str, Any] = Field(default_factory=dict)
    brain: dict[str, Any] = Field(default_factory=dict)

    @property
    def private_dir(self) -> Path:
        return self.root / "private"

    def segment(self, name: str) -> Segment:
        for seg in self.icp.segments:
            if seg.name == name:
                return seg
        known = ", ".join(s.name for s in self.icp.segments)
        raise KeyError(f"Unknown segment '{name}'. Known segments: {known}")

    def exclusion_rows(self) -> list[dict[str, str]]:
        """Rows from private/exclusions.csv (gitignored). Empty if the file does not exist yet."""
        path = self.private_dir / "exclusions.csv"
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as fh:
            return [row for row in csv.DictReader(fh) if row.get("value")]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_client(slug: str) -> ClientConfig:
    root = clients_dir() / slug
    if not root.is_dir():
        raise FileNotFoundError(f"No client folder at {root}")
    return ClientConfig(
        slug=slug,
        root=root,
        client=_load_yaml(root / "client.yaml"),
        icp=ICP.model_validate(_load_yaml(root / "icp.yaml")),
        limits=Limits.model_validate(_load_yaml(root / "limits.yaml")),
        scoring=_load_yaml(root / "scoring.yaml") if (root / "scoring.yaml").exists() else {},
        ai=_load_yaml(root / "ai.yaml") if (root / "ai.yaml").exists() else {},
        brain=_load_yaml(root / "brain.yaml") if (root / "brain.yaml").exists() else {},
    )
