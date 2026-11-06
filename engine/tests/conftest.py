"""Shared test helpers."""

from pathlib import Path

import yaml


def legacy_nl(client_dir: Path) -> None:
    """Switch a temp copy of the client config to the earlier Dutch market, which the synthetic
    fixtures in these tests are written for. The engine logic under test is market-independent."""
    icp_path = client_dir / "icp.yaml"
    icp = yaml.safe_load(icp_path.read_text(encoding="utf-8"))
    icp["allowed_countries"] = ["NL", "BE"]
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
