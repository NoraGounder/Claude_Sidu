"""Deletion schedule from the data processing agreement (Annex 1). Local data only; free.

- People found but never emailed: deleted 90 days after they were found.
- People emailed who never replied and have no deal: deleted 12 months after their upload.
- Reply texts: emptied 12 months after receipt (the category stays for the statistics).
- Deals and the do-not-contact list are kept for the duration of the Services.

`run(..., apply=False)` only counts; `apply=True` deletes. Suppression rows are never touched, so an
opt-out keeps working after the person's other data is gone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gtm.config import ClientConfig

NOT_EMAILED_DAYS = 90
NO_REPLY_DAYS = 365
REPLY_TEXT_DAYS = 365


def _cutoff(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).replace(microsecond=0).isoformat()


def run(cfg: ClientConfig, conn, apply: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    not_emailed = [r[0] for r in conn.execute(
        "SELECT id FROM contacts WHERE client=? AND created_at < ?"
        " AND id NOT IN (SELECT contact_id FROM outbound) AND id NOT IN (SELECT contact_id FROM deals)",
        (cfg.slug, _cutoff(now, NOT_EMAILED_DAYS)))]
    no_reply = [r[0] for r in conn.execute(
        "SELECT o.contact_id FROM outbound o WHERE o.client=? AND o.pushed_at < ? AND o.status <> 'replied'"
        " AND o.contact_id NOT IN (SELECT contact_id FROM deals)"
        " AND o.contact_id NOT IN (SELECT contact_id FROM replies)",
        (cfg.slug, _cutoff(now, NO_REPLY_DAYS)))]
    old_replies = conn.execute(
        "SELECT COUNT(*) FROM replies WHERE client=? AND text IS NOT NULL AND COALESCE(received_at, created_at) < ?",
        (cfg.slug, _cutoff(now, REPLY_TEXT_DAYS))).fetchone()[0]
    summary = {"not_emailed": len(not_emailed), "no_reply": len(no_reply), "reply_texts": old_replies,
               "applied": apply}
    if apply:
        ids = not_emailed + no_reply
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM outbound WHERE contact_id IN ({marks})", chunk)
            conn.execute(f"DELETE FROM drafts WHERE contact_id IN ({marks})", chunk)
            conn.execute(f"DELETE FROM contacts WHERE id IN ({marks})", chunk)
        conn.execute("UPDATE replies SET text=NULL WHERE client=? AND text IS NOT NULL"
                     " AND COALESCE(received_at, created_at) < ?", (cfg.slug, _cutoff(now, REPLY_TEXT_DAYS)))
        conn.commit()
    return summary
