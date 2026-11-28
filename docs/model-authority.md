# Model authority registry and migration controls

## Current repository evidence

The existing SQLite migration files `0004_model_registry.sql` and `0005_seed_model_registry.sql` register **18 historical releases**, map **29 legacy aliases**, and attribute the **10,173 archived score rows**. The `model_predictions` view deduplicates 858 shared NCAAFB component observations without altering the original `model_scores` rows. These are results documented in the current branch; a fresh automated audit is required when promoting to `main`.

**Do not assume all archived releases can score current games.** `PARTIAL` and `ARTIFACTS_MISSING` releases are historical evidence only until new validated adapters reproduce frozen outputs. NHL Day-0 research and archived challenger scores are not automatically production-authorized.

## Immutable identities

`event_id` → `quote_id` → `score_observation_id` → `release_id` → optional `recommendation_id` → `wager_id` → `transaction_id` → `settlement_id`.

Attribution records must retain both `original_prebet_release_id/tier/authorization` and any separately versioned `retrospective_release_id/tier`; never overwrite either when scoring versions change.

For each new model release document: sport, market, source artifact SHA256, data cutoff, feature values/time, fit/train/holdout boundary, probability calibration, tier policy, pricing source and time, EV and Kelly methodology, original authorization, frozen parity, and out-of-sample assessment.

## Source and audit commands

```bash
python -m gambling models list
python -m gambling models attribution
python -m gambling models verify
python -m gambling audit
python -m unittest discover -s tests -v
```

Track missing artifacts, exceptions, and any observed discrepancy under the corresponding sport document. A command in this document is a required verification step, not evidence that it has already passed.

## Adapter status (append-only log)

| Date | Release(s) | Adapter | Evidence | Authority change |
|---|---|---|---|---|
| 2026-11-25 | `NFL_REV2_CAL_20261024`, `NFL_W8_FULL_SLOPE_20261026` | `gambling/models/nfl/rev2_legacy.py` (frozen replay) | Golden `NFL_20261110_072712CST`; 72/72 archived score rows match | **None** — roles, tiers, probabilities and wagering flags unchanged |
| 2026-11-25 | `NHL_ML_DAY0_V1_20261025`, `NHL_PL_DAY0_V1_20261025`, `NHL_OU_DAY0_V1_20261025`, `NHL_ML_V3`, `NHL_PL_V1`, `NHL_V15_CONDITIONAL_COUNT` | `gambling/models/nhl/day0_legacy.py` (frozen replay) | Golden `NHL_DAY0_20261112`; 132/132 archived rows; EV/Full Kelly recomputed by shared pricing equal archived values | **None**: Day-0 remains scoreboard champion with `wagering_authorized=false`; challengers unchanged; PL V1/V15 stay UNSCORED |
| 2026-11-25 | `NCAAFB_SPREAD_PP_V2_20261028`, `NCAAFB_SPREAD_CONTINUOUS_V1_20261023`, `NCAAFB_ML_W8PLUS_RULE`, `NCAAFB_OU_RESEARCH` | `gambling/models/ncaafb/w8plus_legacy.py` (frozen replay) | Golden `NCAAFB_20261102`; 186/186 archived rows; rerun identical within 1e-9 | **None**: PP-V2 and ML rule stay wager-authorized as registered; continuous V1 stays challenger (not authorized); OU stays research with zero allocation |
| 2026-11-25 | `NBA_R4_V27_20261030` (champion), `NBA_R3_20261029` (challenger) | `gambling/models/nba/r4_legacy.py` (frozen replay) | Golden `NBA_R4_20261112`; 12/12 archived rows; rerun identical within 1e-9 | **None**: R4 stays wager-authorized champion; portfolio Adjusted Kelly stays shadow/not certified; R3 shown BLOCKED (artifacts missing) |
| 2026-11-25 | `NCAABB_V4_PROD_THROUGH2025` | `gambling/models/ncaabb/v4_legacy.py` (frozen replay + master append) | Golden `NCAABB_V4_20261101`; 35/35 archived rows; full rerun identical | **None**: V4 stays wager-authorized champion; action classes follow the recorded `stake_eligible` (7 tier-Lean rows eligible), flagged for review; V5 shadow and V4 validation release not on the sheet (no scorer for this board) |
| 2026-11-28 | `NFL_REV2_CAL_20261024`, `NFL_W8_FULL_SLOPE_20261026` | `gambling/models/nfl/live.py` + `gambling/pipeline/nfl.py` (week driver: frozen `score.py`, only Week-10 literals parameterized; `UNVALIDATED_GENERALIZED_WRAPPER`) | Week-10 driver text byte-identical to the frozen file; Nov 10 board reproduced by the converter; 36/36 archived rows reproduced by daily runs (1e-12) | **None** — releases, tiers, calibration and wagering flags unchanged; new weeks are not yet validated (M3/M4) |
