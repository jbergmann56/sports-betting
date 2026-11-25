# File cleanup inventory — backup gate before untracking

The reorganization may identify low-value historical files. A Git-ignored directory is **not** a backup and cannot be created remotely for the user's machine by committing to GitHub. No tracked file is deleted/untracked in V1 until an independent backup is verified, with SHA256 and a restoration test. Historical Git retention alone is insufficient for personal exports and secrets; if sensitive material was ever committed, additional remediation may be required.

## Candidate review list (not yet approved for deletion)

| Path | Proposed handling | Gate |
|---|---|---|
| `SPSS_R_DecisionTree.JPG`, `gambling_state_laws.jpg`, `lotto.sas`, `ps history.txt` | Assess relevance; copy to local ignored archive if unrelated | Verify backup and any references |
| `legacy_models/nba_r4/data/.corrected_historical_master.csv.*` | Likely temporary partial artifacts; preserve until canonical parity and SHA review | Verify not release inputs |
| `legacy_models/nba_r4/evidence/.ml_spread_predictions.csv.*` | Likely temporary partial artifacts; preserve until parity and SHA review | Verify not release inputs |
| Root `schema.sql` | Investigate whether this is a v1-app-only schema | Verify root package has no dependence |

**Must remain tracked:** `legacy_models/` published artifacts and hashes, `legacy_ops/` audit scripts, `legacy/v1_app/` historic code, `data/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip`, tests/fixtures, numbered SQLite migrations and release registry. These are evidence, even if not needed at runtime.

## Safe local archival procedure

1. Make an independent snapshot of repository and non-Git data; verify checksums/restoration.
2. Create `.local_archive/` on the developer machine, copy reviewed files there, and record `path -> checksum -> reason -> backup location` in a local manifest (do **not** upload sensitive paths/data).
3. Only then prepare a PR to remove those files from Git tracking. Git history retains former copies; remediation is required if files contain secrets.
4. Never move already committed credentials into an ignored folder and assume history is clean. Rotate exposed credentials and explicitly remediate old commits if applicable.

`.gitignore` blocks future additions to `.local_archive/`; it does not untrack already committed files.
