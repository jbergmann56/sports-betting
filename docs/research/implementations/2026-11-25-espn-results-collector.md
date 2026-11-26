# Implementation report: ESPN results collector

**Date:** 2026-11-25 · **Branch:** `feature/espn-results`, stacked on `sport/ncaabb` (PR #13) · **Model changes:** none

## Files

- `gambling/db/migrations/0007_espn_results.sql`: `espn_result_captures`, `espn_result_observations`, `espn_result_conflicts` (all append-only), and the view `espn_latest_observation`.
- `gambling/results/espn.py`: `scoreboard_url`, `fetch`, `parse`, `record`, `collect`, `nba_history_rows`, `write_nba_history`.
- `gambling/cli.py`: `results fetch --sport S [--sport S ...] --date D [--through D2]`, `results conflicts`, `results nba-history`.
- `tests/test_espn_results.py` (10 tests).
- Docs: `docs/architecture.md`, `docs/sports/nba.md`, `ROADMAP.md`.

## How it fits the existing data model

The collector writes into the existing `official_game_results` (0001; PK `(sport, espn_game_id)`):
- **Format:** the same columns and conventions as the rows already there (US/Eastern game date, ESPN team display names, `status='Final'`). The source is `espn:<capture id>`.
- **Existing rows are never overwritten.** A later observation that disagrees is recorded in `espn_result_conflicts`, and `results conflicts` exits 1 until it is reviewed.
- **Separation:** wager and account tables are not touched.

## Verification

- Archived ESPN responses (NCAABB Nov 1–2, NCAAFB Oct 27) are parsed. Captures are stored byte-for-byte, and finals are recorded once (reruns count as already recorded). A changed score becomes a conflict, not an overwrite. Unfinished games are observed but not recorded. An Eastern late game keeps its date, and a failed parse leaves nothing behind.
- 0007 on a copy of the user database (after 0006): 31 existing tables hash identically; integrity and foreign-key checks are clean.
- Reconciliation: the user database's 15 NBA finals (Nov 8–9) agree with the manually transcribed R4 history. The only key mismatch is the Clippers name.

## Limitations

- The sandbox cannot reach ESPN, so the first live fetch must run on the user PC.
- NBA history rows use ESPN names verbatim. The feed blocks on names the base history never used.
- Settlement of quotes (`quote_outcomes`) and links to Bovada events (`settlements.game_key`) are separate follow-ups. Results are never equated with money won or lost (CLAUDE.md rule 1).
