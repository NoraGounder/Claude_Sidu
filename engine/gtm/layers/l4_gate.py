"""Layer 4: send gate. Deterministic checks on every contact with an email; nothing here guesses.

Outcomes (contacts.status):
  ready        every rule passes; Layer 5 may write to them
  held         may pass later: sender consent pending, email needs re-checking, catch-all cap reached
  rejected_l4  never send: suppressed, role or free-mail address, wrong domain, invalid, wrong country

MillionVerifier is used only to re-check emails older than `freshness_days` (FullEnrich already
verified the rest), and only where its key is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from gtm import budget, db
from gtm.config import ClientConfig
from gtm.sources.millionverifier import MillionVerifierClient, MillionVerifierError

VENDOR = "millionverifier"
PRICE_KEY = "millionverifier:check"


@dataclass
class GateResult:
    counts: dict = field(default_factory=dict)
    reasons: dict = field(default_factory=dict)


def load_rules(cfg: ClientConfig) -> dict:
    path = Path(cfg.root) / "gate.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def registrable(domain: str) -> str:
    parts = domain.lower().strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain.lower()


def related_domain(email_domain: str, account_domain: str) -> bool:
    """Same registrable domain, or a group domain carrying the same brand: staff at bunzlretail.nl
    use bunzl.com / bunzl.nl. The brand must be at least 4 letters to avoid accidental matches."""
    e, a = registrable(email_domain), registrable(account_domain)
    if e == a:
        return True
    e_label, a_label = e.split(".")[0], a.split(".")[0]
    return len(e_label) >= 4 and (a_label.startswith(e_label) or e_label.startswith(a_label))


def hard_check(rules: dict, contact: dict, suppressed: dict[str, set[str]]) -> str | None:
    """Reasons a contact must never be emailed. None if it passes."""
    email = (contact.get("email") or "").strip().lower()
    if "@" not in email:
        return "no_email"
    local, _, domain = email.partition("@")
    if email in suppressed["email"] or domain in suppressed["domain"] \
            or (contact.get("account_domain") or "") in suppressed["domain"] \
            or (contact.get("company") or "").lower() in suppressed["company"]:
        return "suppressed"
    if local.split(".")[0].split("-")[0] in {p.lower() for p in rules["role_prefixes"]}:
        return "role_address"
    if domain in {d.lower() for d in rules["free_mail_domains"]}:
        return "free_mail_address"
    acc_domain = contact.get("account_domain") or ""
    if acc_domain and not related_domain(domain, acc_domain):
        return f"domain_mismatch:{domain}"
    country = (contact.get("country") or "").upper()
    if country and len(country) == 2 and country not in rules["contact_countries"]:
        return f"contact_country:{country}"
    if not contact.get("data_source"):
        return "no_data_source"
    status = (contact.get("email_status") or "").upper()
    if status and status not in set(rules["accepted_email_status"]) | {"CATCH_ALL", "ACCEPT_ALL", "RISKY"}:
        return f"email_status:{status}"
    return None


def is_stale(contact: dict, freshness_days: int, now: datetime) -> bool:
    ts = contact.get("verified_at") or contact.get("updated_at")
    if not ts:
        return True
    when = datetime.fromisoformat(ts)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when).days > freshness_days


def needs_verification(rules: dict, contact: dict) -> bool:
    """Optional (gate.yaml `verify_statuses`): emails the finder rated below "deliverable" are held until
    MillionVerifier has checked them (`gate --recheck`). Not set = they are sent as they are."""
    return ((contact.get("email_status") or "").upper() in {s.upper() for s in rules.get("verify_statuses") or []}
            and "MillionVerifier" not in (contact.get("email_source") or ""))


def run(cfg: ClientConfig, conn, recheck: bool = False, mv: MillionVerifierClient | None = None,
        now: datetime | None = None) -> GateResult:
    rules = load_rules(cfg)
    now = now or datetime.now(timezone.utc)
    from gtm.layers.l1_discover import sync_exclusions
    sync_exclusions(conn, cfg)          # private/exclusions.csv may have changed since Layer 1
    suppressed = {k: db.suppressed_values(conn, cfg.slug, k) for k in ("email", "domain", "company")}
    consent = str(cfg.client.get("sender", {}).get("consent_to_send_in_name", "pending")).lower() == "granted"
    rows = [dict(r) for r in conn.execute(
        "SELECT c.*, a.domain AS account_domain, a.name AS company, s.tier, s.signal FROM contacts c"
        " JOIN accounts a ON a.id=c.account_id JOIN l2_scores s ON s.account_id=a.id"
        " WHERE c.client=? AND c.status IN ('email_found','ready','held','rejected_l4')"
        " ORDER BY CASE s.tier WHEN 'tier_1' THEN 1 WHEN 'tier_2' THEN 2 ELSE 3 END, s.signal DESC, c.rank",
        (cfg.slug,)).fetchall()]

    if recheck:
        stale = [r for r in rows if r.get("email")
                 and (is_stale(r, rules["freshness_days"], now) or needs_verification(rules, r))]
        if stale:
            budget.check(conn, cfg, VENDOR, budget.estimate(cfg, PRICE_KEY, len(stale)))
            mv = mv or MillionVerifierClient()
            run_id = db.start_run(conn, cfg.slug, "L4-verify", VENDOR, f"re-check x{len(stale)}",
                                  budget.estimate(cfg, PRICE_KEY, len(stale)), {"contacts": len(stale)})
            try:
                for r in stale:
                    res = mv.verify(r["email"])
                    status = {"ok": "DELIVERABLE", "catch_all": "CATCH_ALL"}.get(res["result"], res["result"].upper())
                    r["email_status"], r["verified_at"] = status, now.isoformat()
                    r["email_source"] = (r.get("email_source") or "") + " + MillionVerifier"
                    conn.execute("UPDATE contacts SET email_status=?, verified_at=?, email_source=? WHERE id=?",
                                 (status, r["verified_at"], r["email_source"], r["id"]))
            except MillionVerifierError as exc:
                db.finish_run(conn, run_id, "failed", 0, None, str(exc)[:300])
                raise
            db.finish_run(conn, run_id, "succeeded", len(stale), budget.estimate(cfg, PRICE_KEY, len(stale)))

    accepted = {s.upper() for s in rules["accepted_email_status"]}
    decided: list[tuple[dict, str, str | None]] = []
    for r in rows:
        reason = hard_check(rules, r, suppressed)
        if reason:
            decided.append((r, "rejected_l4", reason))
        elif is_stale(r, rules["freshness_days"], now):
            decided.append((r, "held", "stale_email:re-check with MillionVerifier"))
        elif needs_verification(rules, r):
            decided.append((r, "held", "unverified_email:run gate --recheck"))
        elif (r.get("email_status") or "").upper() not in accepted and r["tier"] not in rules["catch_all"]["allowed_tiers"]:
            decided.append((r, "held", f"catch_all_not_allowed_for_{r['tier']}"))
        else:
            decided.append((r, "ready", None))

    # Catch-all cap: at most max_share of the ready set, best accounts first (rows are ordered).
    ready = [d for d in decided if d[1] == "ready"]
    limit = int(rules["catch_all"]["max_share_of_ready"] * len(ready))
    used = 0
    final = []
    for r, status, reason in decided:
        if status == "ready" and (r.get("email_status") or "").upper() not in accepted:
            if used >= limit:
                status, reason = "held", "catch_all_cap_reached"
            else:
                used += 1
        if status == "ready" and rules.get("require_sender_consent", True) and not consent:
            status, reason = "held", "sender_consent_pending"
        final.append((r, status, reason))

    result = GateResult()
    ts = now.isoformat()
    for r, status, reason in final:
        conn.execute("UPDATE contacts SET status=?, status_reason=?, gate_checked_at=? WHERE id=?",
                     (status, reason, ts, r["id"]))
        result.counts[status] = result.counts.get(status, 0) + 1
        if reason:
            key = reason.split(":")[0]
            result.reasons[key] = result.reasons.get(key, 0) + 1
    conn.commit()
    return result
