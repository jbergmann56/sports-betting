# Branch strategy — sports, UI, and shared core

- `main`: only validated integrated code; never use for unfinished scoring research.
- `reorg/v1`: staging branch for the first structural/documentation migration. Do not alter model probability/tier behavior here.
- `sport/nfl`, `sport/ncaafb`, `sport/nba`, `sport/nhl`, `sport/ncaabb`: independent sport workstreams.
- `ui/streamlit`: UI workstream consuming shared model and accounting interfaces, not a divergent implementation of those interfaces.
- `feature/core-<topic>`, `feature/accounting-<topic>`, `feature/parlays-<topic>`: short-lived shared branches.

## Workflow

1. Sync with `main`; scope the change to the relevant sport or shared module.
2. Update tests and sport/bet-sheet specs in the same PR as code changes.
3. Preserve frozen releases and original observations; introduce new release IDs for changed model algorithms.
4. Run `python -m unittest discover -s tests -v`, frozen replay/registry checks when applicable, and targeted sport parity fixtures. Record actual results.
5. Merge only after review and passing checks; update the branch from `main` to avoid long-lived divergence.
6. Delete completed temporary topic branches only after ensuring no unique commits remain. Keep archival branches until provenance is confirmed.

**Important:** Sports modules persist in `main`; sports branches are not five separate applications. A branch cannot independently become production authority without an reviewed merge. Branches must share consistent database and quote contracts.

## Initial migration gate

Compare `feature/rolling-sqlite`, `reorg/phase0`, and `main`; preserve all distinct commits, run tests, and review the reorganization PR before promoting to `main`. Create permanent sport/UI branches from the validated integrated baseline. If validation cannot be completed, keep `reorg/v1` as draft and do not mislabel `main` as current.
