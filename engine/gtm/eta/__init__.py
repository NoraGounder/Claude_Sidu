"""ETA search: find, read and screen companies to buy (clients/eta).

Milestone 1, registry sourcing and sieve 1, all from public data:

    discover  -> Companies House advanced search by SIC code and age      (eta-discover)
    profile   -> company profile: accounts type, overdue, insolvency       (eta-enrich)
    accounts  -> latest filed accounts (iXBRL) into numbers per year       (eta-enrich)
    owners    -> persons with significant control and directors            (eta-enrich)
    screen    -> sieve-1 hard checks, 0-100 score, evidence ledger         (eta-screen)
    list      -> ranked CSV in data/eta/                                   (eta-list)

Everything lands in data/engine.db (gitignored) in eta_* tables, apart from the shared runs ledger.
"""
