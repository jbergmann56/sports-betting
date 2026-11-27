# Odds API key quarantine (2026-11-26)

**Decision (user, 2026-11-26):** quarantine the Odds API key; the Odds API is not used until the user decides it is needed.

## Facts
- `legacy/v1_app/odds_api_historical_nfl_events.py` had a hard-coded Odds API key from the initial commit (`0cc1195`, 2026-11-06). It was moved under `legacy/v1_app/` in `39a8f89`. The repository is public, so the key is exposed in Git history.
- Two local Odds API scripts in the user's main checkout also contain a key. They were never committed.
- No other credential literal is in tracked files (scan on 2026-11-26).

## What was done
- The literal was removed from the tracked legacy script, which now stops immediately (`SystemExit`) if run. Git history is **not** rewritten. Rotation is what makes the exposed key useless; history rewriting would also conflict with the frozen-evidence rule.
- `tests/test_no_secrets.py` fails CI if a tracked file assigns a credential-looking literal (`API_KEY`, `apiKey`, `token`, `secret`, `password`).
- The scoring pipeline does not call the Odds API. Bovada remains the only quote source (CLAUDE.md rule 2).

## User actions
1. Regenerate the key on the Odds API account (this invalidates the public one).
2. Move the key out of the two local scripts into a file outside every repository, and disable the scripts. See the commands in the PR description.
3. If the API is approved later: read the key from the environment (`ODDS_API_KEY`) or a git-ignored file, never a literal.
