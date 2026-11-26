# <Client>: launch plan

Run order (each paid step after its `--dry-run`; costs from the Quailworks playbook, docs/playbook.md):

1. Day 1, in parallel: client buys 2 domains x 3 mailboxes (warm-up starts); we write offer, ICP, scoring,
   sequence and decisions from the website and public data.
2. Days 1-3: `discover` / `discover-hiring` (Layer 1), `prefilter` + `jev` (Layer 2): Tier 1-2 companies.
3. Days 3-5: `contacts` (Layer 3), `gate --recheck` (Layer 4), `markets --refresh`, `draft` + `approve` (Layer 5).
4. Day 14+: `push` dry run, then `push --live` (campaigns stay paused), `start --i-confirm` after the "go".
5. Daily: `sync`, `handoff`; weekly: `funnel`, `learn`, `markets --refresh`; ramp per decisions.md T4.
