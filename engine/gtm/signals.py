"""Layer 2 evidence rules: find buying signals in crawled pages, with the source URL and a
short quote for each, so Layer 5 can only personalise from facts we can point to."""

from __future__ import annotations

import re
from dataclasses import dataclass

from gtm.crawl import SiteCrawl

# Each rule: signal name -> list of (label, regex). Dutch first; English for international sites.
RULES: dict[str, list[tuple[str, str]]] = {
    "admin_job_ad": [
        ("administratief medewerker", r"administratief\s+medewerk\w*|medewerk\w*\s+administratie"),
        ("crediteurenadministratie", r"crediteuren\s*-?\s*administrat\w*|crediteurenbeheer"),
        ("debiteurenadministratie", r"debiteuren\s*-?\s*administrat\w*|debiteurenbeheer"),
        ("financieel administratief", r"financieel\s*-?\s*administratie\w*|financi[eë]le administratie"),
        ("orderverwerking", r"order\s*-?\s*verwerk\w*|orderadministrat\w*|order\s*desk|orderdesk"),
        ("inkoopadministratie", r"inkoopadministrat\w*|inkoop\s*-?\s*assistent"),
        ("backoffice", r"back\s*-?\s*office\s*medewerk\w*|medewerk\w*\s*back\s*-?\s*office"),
        ("data entry", r"data\s*-?\s*entry|data\s*-?\s*invoer"),
        ("accounts payable", r"accounts\s+payable|accounts\s+receivable|order\s+entry\s+clerk"),
    ],
    "manual_process_language": [
        ("Excel", r"\bexcel\b"),
        ("handmatig", r"handmatig\w*|met de hand"),
        ("papier", r"papieren\s+\w+|op papier"),
        ("dubbel invoeren / overtypen", r"dubbel\s+invoer\w*|overtyp\w*"),
        ("manual (EN)", r"\bmanual(ly)?\s+(data|entry|process|input)"),
    ],
    "erp_mention": [
        ("Exact", r"exact\s+(online|globe|synergy)"),
        ("AFAS", r"\bafas\b"),
        ("SAP", r"(?-i:\bSAP\b)(\s+business\s+one|\s+s/?4\w*)?"),   # case-sensitive: "sap" is Dutch for juice
        ("Microsoft Dynamics", r"dynamics\s+(nav|365|ax|business central)|business\s+central|navision"),
        ("Twinfield", r"\btwinfield\b"),
        ("Unit4", r"\bunit\s?4\b"),
        ("Isah / Ridder iQ / King", r"\bisah\b|ridder\s+iq|\bking\s+erp\b"),
    ],
    "headcount_growth": [
        ("uitbreiding", r"nieuwe\s+vestiging|uitbreiding van ons team|we\s+groeien|wij\s+groeien|snel\s+groeiend"),
        ("new site (EN)", r"new\s+(warehouse|distribution\s+cent(er|re)|facility)|we\s+are\s+growing"),
    ],
    "subsidiary_of_large_group": [
        # Keywords in any case, group name capitalised (1-3 words), e.g. "Part of the Groot Machine Group".
        ("onderdeel van", r"(?i:onderdeel\s+van\s+(de\s+)?)[A-Z][\w&\-]+(\s+[A-Z][\w&\-]+){0,2}\s+(?i:groep|group)"),
        ("part of (EN)", r"(?i:(part|member|subsidiary)\s+of\s+(the\s+)?)[A-Z][\w&\-]+(\s+[A-Z][\w&\-]+){0,2}\s+(?i:group)"),
    ],
}

DUTCH_WORDS = re.compile(r"\b(de|het|een|en|van|voor|wij|onze|bij|naar|over)\b", re.I)

# Signals that only count on careers or vacancy pages, and signals matched case-sensitively.
# These are the defaults; a client can define its own rules in scoring.yaml (see `rules_for`).
JOB_PAGE_SIGNALS = frozenset({"admin_job_ad"})
CASE_SENSITIVE = frozenset({"subsidiary_of_large_group"})


@dataclass(frozen=True)
class SignalRules:
    rules: dict[str, list[tuple[str, str]]]
    job_page_signals: frozenset[str]
    case_sensitive: frozenset[str]


DEFAULT_RULES = SignalRules(RULES, JOB_PAGE_SIGNALS, CASE_SENSITIVE)


def rules_for(scoring: dict | None) -> SignalRules:
    """The client's evidence rules. Without a `detect` section in scoring.yaml, the defaults above apply.

    scoring.yaml:
      detect:                        # replaces the default rules entirely
        sales_job_ad:
          - {label: "SDR", pattern: "sales\\s+development\\s+rep"}
        subsidiary_of_large_group:
          - {label: "part of (EN)", pattern: "...", }
      job_page_signals: [sales_job_ad]          # count only on careers or vacancy pages
      case_sensitive_signals: [subsidiary_of_large_group]
    """
    detect = (scoring or {}).get("detect")
    if not detect:
        return DEFAULT_RULES
    rules = {signal: [(r["label"], r["pattern"]) for r in entries] for signal, entries in detect.items()}
    return SignalRules(rules,
                       frozenset(scoring.get("job_page_signals", [])),
                       frozenset(scoring.get("case_sensitive_signals", [])))


@dataclass
class Evidence:
    signal: str
    label: str
    url: str
    quote: str


def _quote(text: str, match: re.Match, width: int = 90) -> str:
    start, end = max(0, match.start() - width), min(len(text), match.end() + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def extract(site: SiteCrawl, rules: SignalRules = DEFAULT_RULES) -> list[Evidence]:
    found: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    job_urls = {p.url for p in site.jobs}
    careers_url = site.careers.url if site.careers else None
    for page in site.pages:
        if not page.ok:
            continue
        on_job_page = page.url in job_urls or page.url == careers_url
        for signal, signal_rules in rules.rules.items():
            # Job-ad signals only count on careers or vacancy pages: on a homepage the words usually
            # describe services offered to customers, not jobs.
            if signal in rules.job_page_signals and not on_job_page:
                continue
            for label, pattern in signal_rules:
                flags = 0 if signal in rules.case_sensitive else re.I
                m = re.search(pattern, page.text, flags)
                if m and (signal, label) not in seen:
                    seen.add((signal, label))
                    found.append(Evidence(signal, label, page.url, _quote(page.text, m)))
    return found


def is_dutch(site: SiteCrawl) -> bool:
    if site.home.lang.startswith("nl"):
        return True
    sample = site.home.text[:4000]
    words = max(1, len(sample.split()))
    return len(DUTCH_WORDS.findall(sample)) / words > 0.06
