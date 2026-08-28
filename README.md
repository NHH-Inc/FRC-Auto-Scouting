# FRC Video Scouting

Watches recorded FRC match video and produces per-robot scouting data.

Three components, one repo, no cross-imports. `docs/frc-scouting-0-contract.md` is the only
shared surface and nothing in `/contracts/` changes without all three people agreeing.

    [3] web  ──HTTP──▶  [2] ingest  ──exec──▶  [1] analysis
                             │                       │
                             ├── yt-dlp              └── events.jsonl, tracks.jsonl
                             ├── TBA API
                             └── Postgres

| Dir | Component | Language | Owns |
|---|---|---|---|
| `analysis/` | 1 | C++ | Detection, tracking, OCR, event extraction |
| `ingest/` | 2 | Python | yt-dlp, TBA/YouTube APIs, job queue, HTTP API, the database |
| `web/` | 3 | TypeScript | UI, player, overlay, corrections, Sheets export |
| `contracts/` | — | — | Shared schemas. **Owned by everyone.** |
| `fixtures/` | — | — | Golden test data. **Owned by everyone.** |
| `docs/` | — | — | The four context documents |

## Start here

1. `docs/frc-scouting-0-contract.md` — read before anything else
2. `contracts/README.md` — the schemas, and what changed when the three contract sets merged
3. `contracts/OPEN_QUESTIONS.md` — **thirteen items that need all three people.** Several
   will break the integration if they are not settled
4. `fixtures/README.md` — the one worked example every component builds against

## Running component 3 with no backend

    cd web && npm install && npm run dev

Serves the whole UI against `/fixtures/`, including a real 152-second match video. Ports are
doc 0 defaults: web `5173`, ingest `8080`, Postgres `5432`.

## Checking a component against the contracts

    cd web && npm run validate:fixtures
