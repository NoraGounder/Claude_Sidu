"""Shared test helpers."""

from pathlib import Path

import pytest
import yaml


# Opt-in safeguards The Marble Jar turned on for its launch (decisions.md D15-D17). Tests that use its
# config as the engine's default behaviour take them out again; test_quailworks.py checks they are set.
LAUNCH_SAFEGUARDS = {"gate.yaml": ["verify_statuses"],
                     "sending.yaml": ["min_warmup_days", "min_warmup_reputation", "send_order", "require_backup"]}


def engine_defaults(client_dir: Path) -> None:
    """Remove the client's opt-in launch safeguards from a temp copy, back to engine defaults."""
    for name, keys in LAUNCH_SAFEGUARDS.items():
        path = client_dir / name
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in keys:
            data.pop(key, None)
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def legacy_nl(client_dir: Path) -> None:
    """Switch a temp copy of the client config to the earlier Dutch market, which the synthetic
    fixtures in these tests are written for. The engine logic under test is market-independent."""
    icp_path = client_dir / "icp.yaml"
    icp = yaml.safe_load(icp_path.read_text(encoding="utf-8"))
    icp["allowed_countries"] = ["NL", "BE"]
    icp["company"]["employees_min"], icp["company"]["employees_max"] = 50, 500   # the fixtures' size band (TMJ D30 widened it)
    for seg in icp["segments"]:
        seg["enabled"] = seg["name"].endswith("_nl")
    icp_path.write_text(yaml.safe_dump(icp, allow_unicode=True, sort_keys=False), encoding="utf-8")

    gate_path = client_dir / "gate.yaml"
    gate = yaml.safe_load(gate_path.read_text(encoding="utf-8"))
    gate["contact_countries"] = ["NL", "BE"]
    gate_path.write_text(yaml.safe_dump(gate, allow_unicode=True, sort_keys=False), encoding="utf-8")

    scoring_path = client_dir / "scoring.yaml"
    scoring = yaml.safe_load(scoring_path.read_text(encoding="utf-8"))
    scoring["fit"]["dutch_language_site"] = 5
    scoring_path.write_text(yaml.safe_dump(scoring, allow_unicode=True, sort_keys=False), encoding="utf-8")
    engine_defaults(client_dir)


@pytest.fixture(autouse=True)
def _no_real_backups(monkeypatch):
    """Tests never touch the real backup vault: a session with GTM_BACKUP_KEY/REMOTE set would
    otherwise restore real data into a test folder or push a test database to the vault."""
    monkeypatch.delenv("GTM_BACKUP_KEY", raising=False)
    monkeypatch.delenv("GTM_BACKUP_REMOTE", raising=False)
