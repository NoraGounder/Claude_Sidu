"""Quailworks Engineering (clients/quailworks-engineering): the engineering-design offer on the same engine.
Config checks only, with synthetic text; nothing is fetched, written to a vendor or sent."""

import re

import yaml

from gtm.config import REPO_ROOT, load_client
from gtm.layers import l1_hiring, l5_copy, l6_send
from gtm.signals import rules_for
from gtm.sources.jev import check_policy

QWE = "quailworks-engineering"


def _labels(cfg, signal: str, text: str) -> list[str]:
    return [label for label, pattern in rules_for(cfg.scoring).rules[signal] if re.search(pattern, text, re.I)]


def test_config_loads_with_every_launch_safeguard():
    cfg = load_client(QWE)
    check_policy(cfg.ai)                                           # Jev 1.14 only, no fallback
    sending = l6_send.load_sending(cfg)
    gate = yaml.safe_load((cfg.root / "gate.yaml").read_text(encoding="utf-8"))
    assert cfg.client["sender"]["consent_to_send_in_name"] == "pending"     # its own yes (decisions.md E2)
    assert sending["campaign_prefix"] == "QWE" and sending["send_order"] == "best_first"
    assert sending["min_warmup_days"] >= 14 and sending["min_warmup_reputation"] >= 95 and sending["require_backup"]
    assert set(gate["verify_statuses"]) >= {"DELIVERABLE", "HIGH_PROBABILITY"}
    assert gate["contact_countries"] == ["GB", "US"] and set(cfg.icp.allowed_countries) == {"GB", "US"}
    assert "Quailworks sp. z o.o." in gate["gdpr_notice"]["en"] and "'stop'" in gate["gdpr_notice"]["en"]
    assert cfg.client["crm"]["hubspot_token_env"] == "HUBSPOT_TOKEN_QUAILWORKS"   # one CRM for one company (E1)
    assert cfg.limits.month_budget_usd["fullenrich"] <= 20 and cfg.limits.month_budget_usd["blitzapi"] == 0


def test_never_shares_a_sending_domain_and_holds_companies_the_gtm_offer_emailed():
    cfg = load_client(QWE)
    sending = l6_send.load_sending(cfg)
    assert l6_send.shared_domains(cfg) == []                         # one domain, one client
    assert sending["avoid_overlap_with"] == ["quailworks"] and sending["overlap_days"] >= 90   # E12


def test_hiring_searches_cover_the_uk_and_us_design_market():
    cfg = load_client(QWE)
    plans = l1_hiring.plan(cfg)
    assert len(plans) == 7 and all(p.est_cost == 0 for p in plans)  # flat plan: no charge per record
    assert {c for p in plans for c in p.company["hq"]["country_code"]["include"]} == {"GB", "US"}
    assert "Mechanical Design Engineer" in plans[0].job["title"]["include"]
    assert all(p.company["employee_count"] == {"min": 11, "max": 500} for p in plans)


def test_design_roles_count_once_and_electronics_roles_do_not_count():
    cfg = load_client(QWE)
    assert _labels(cfg, "design_job_ad", "Senior Mechanical Design Engineer") == ["mechanical design engineer"]
    assert _labels(cfg, "design_job_ad", "Chassis Design Engineer") == ["chassis engineer"]
    assert _labels(cfg, "design_job_ad", "Composites Design Engineer") == ["composites design engineer"]
    assert _labels(cfg, "design_job_ad", "Design Engineer - Structures") == ["design engineer"]
    assert _labels(cfg, "design_job_ad", "Electronics Design Engineer") == []
    assert _labels(cfg, "design_job_ad", "PCB Design Engineer") == []
    assert _labels(cfg, "cad_platform", "Experience with CATIA V5 or 3DEXPERIENCE required") == ["CATIA"]
    assert _labels(cfg, "cad_platform", "Siemens NX and Teamcenter") == ["Siemens NX"]


def test_email_one_is_short_names_no_employer_and_passes_the_banned_phrase_check():
    cfg = load_client(QWE)
    seq = l5_copy.load_sequence(cfg)
    gate = yaml.safe_load((cfg.root / "gate.yaml").read_text(encoding="utf-8"))
    facts = {"job_title": {"value": "mechanical design engineer"}}
    subject, steps = l5_copy.render(seq, "en", "design_job_ad", "design", facts, {"id": 7, "first_name": "Alex"},
                                    {"name": "Northfield Motorsport Ltd"}, {"first_name": "Sam"}, gate["gdpr_notice"]["en"])
    body = steps[0]["body"]
    assert subject == "your mechanical design engineer opening"
    assert body.startswith(("Hi Alex,", "Hello Alex,")) and "opening at Northfield Motorsport." in body
    assert "one-page profile" in body and body.endswith(gate["gdpr_notice"]["en"])
    words = body.replace(gate["gdpr_notice"]["en"], "").split()
    assert len(words) <= 110
    text = " ".join(s["body"] for s in steps).lower() + " " + subject.lower()
    banned = l5_copy.BANNED + tuple(p.lower() for p in seq["banned_phrases"])
    assert not any(b in text for b in banned) and "{" not in text
    for hook in seq["hook_priority"]:                            # every hook renders with its own fact
        need = l5_copy.hook_meta(seq, hook)["needs"]
        f = {need: {"value": {"cad": "CATIA", "trade_show": "Autosport International", "open_roles": 9}.get(need, "design engineer")}} if need else {}
        _, s = l5_copy.render(seq, "en", hook, "design", f, {"id": 1, "first_name": "Alex"}, {"name": "Acme Ltd"},
                              {"first_name": "Sam"}, "Notice.")
        assert "{" not in s[0]["body"] and "Acme" in s[0]["body"]
