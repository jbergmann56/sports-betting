# ChatGPT-side NCAAFB attachment inventory — provenance, not production authority

**Audit date:** 2026-11-24. This is metadata and read-only column/row inspection of six user-provided files supplied to this ChatGPT project. **None of the six files was uploaded to or committed in GitHub by this audit.** Claude Code cannot infer access to them from this record. These hashes can be used to verify a user-supplied secure copy.

| Attachment filename | Bytes | SHA-256 | Rows | Context |
|---|---:|---|---:|---|
| `NCAAFB_2026_WEEK1_MODEL_INPUT_CORRECTED_COMPLETE(1).csv` | 7,152 | `cc74aae6b9b4d04985a6bfcbdaae2c1c4992059e65d55fc688cfc4a66e520302` | 40 | 2026 Week1 only; 45 columns |
| `NCAAFB_DB_CLEAN(3).csv` | 903,752 | `271b7290340747a5501a18728620de9485873a2922579852f944ecdef7272d23` | 4,572 | 2018, 2020-22, 2024-25; 45 columns |
| `NCAAFB_MASTER_RECONSTRUCTION_STAGING(2).csv` | 2,568,178 | `28f8e165afd35560ac9e32ad4e0919bea35f6f2c061e98c65f49d32e6d627784` | 6,079 | 2018, 2020-25; **staging**, 56 columns with provenance fields |
| `betting_2023(1).csv` | 51,738 | `cfed792e461bc619c466cef8033beb2f37e9b6af7e64f8f26efecfb1d7f93a54` | 911 | 2023 ESPN-era odds candidate, 9 fields |
| `betting_2023(1).parquet` | 10,130 | `7e6276f6c6a1cdff26c58c22d838f2ffff6594f856b58892085d4abe8880f20d` | **Not independently read** | Parquet library unavailable in this inspection environment |
| `cfb_schedules_2023.txt` | 884,855 | `7ffc245da1242fc44c021dae724029074aece78544ba498937cc7703417f0dff` | 3,734 | UTF-8 comma-separated 2023 schedules, 31 columns |

## Quality checks completed

- The 40-row Week1 2026 CSV has year=2026, 40 nonempty away/home SRS values and 40 away lines / associated quoted spread-odds records. **Both `Away Slope` and `Home Slope` are empty for all 40 rows**. Therefore it cannot directly reproduce the Week8+ slope/Z strategy without a documented feature build. No duplicate composite (year, week, away, home) keys in that 40-row sample.
- The 4,572-row “clean” CSV has **1,554 repeated** (year, week, away, home) composite keys; no full-row duplicates in the inspected pandas import. Only 553 rows have nonempty `Date` (nonempty ≈ 12%); approx 1,893 rows have a slope value. Repeated keys are **not necessarily duplicate physical games**: do not deduplicate without inspecting market/record semantics.
- The 6,079-row reconstruction **staging** CSV has **553 exact duplicate rows** and **2,209 repeated composite** (year, week, away, home) keys. Its `Reconstructed` field marks **101** rows `Yes` and 5,978 `No`. The 101 reconstructed rows are year 2023 and declare `Data Completeness = Partial 2023 season — do not treat as full 2023 master`. **Do not promote to authoritative history or drop repeated rows blindly.**
- 2023 betting CSV contains 911 unique `game_id` values, all of which join to the separate 3,734-row schedule by `game_id`; 882 have numeric spread and total, 29 are marked `summary_pickcenter` without the numeric fields; 882 are marked `core_odds_api`. The schedule file includes **792 FBS-v-FBS games**, but the 911 odds records are not asserted to be an exact FBS-v-FBS set; apply the explicit division, time, neutral-site and conference gates.
- No reliable independent confirmation was performed that any attachment's odds are pregame-frozen Bovada lines. The 2023 odds source labels are as in the CSV; do not rebrand them Bovada. No source-game-ID population exists in the 6,079-row staging file (the `Source Game ID` column is entirely empty).
- Some CSVs contain `Bet $`, `NET $`, `My Bet`, `OU $` and outcome fields; treat them as user-originated working data potentially containing actual wager information. **Do not commit raw files to the code repository** or mix these with unreconciled paper returns.

## Secure transfer to Claude

1. Keep originals unchanged and separately backed up. Create a local Git-ignored directory on the Claude development machine, e.g. `data/imports/ncaafb/2026-11-24/`, or a separate protected data root via `GAMBLING_DATA_DIR`.
2. Copy only the user's approved research datasets there; verify each SHA256 against the table before processing. On macOS/Linux use `shasum -a 256 <file>`; on Windows use PowerShell `Get-FileHash <file> -Algorithm SHA256`.
3. Import first to a **staging** dataset with source_file, source_sha256, original row number and raw row checksum. Investigate physical-game IDs and market lines before making any unique-key assumptions.
4. Keep actual betting columns and personally identifying account information out of synthetic shared fixtures and Git commits. Produce aggregate coverage/parity reports with anonymized examples.
5. For release-specific reproduction, retrieve missing original Oct 2026 `inputs/*` and posterior files separately; these attached files do not replace their frozen content.

**Audit limitations:** This was a schema/metadata and basic coverage check, not a statistical backtest, model improvement, validation of odds originality, or independent source verification. Parquet internal row/column metadata was not inspected.
