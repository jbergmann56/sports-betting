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
