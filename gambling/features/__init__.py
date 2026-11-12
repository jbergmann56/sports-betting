"""Per-sport point-in-time feature builders.

Plan Phase 5. Each job takes ``as_of_utc`` and writes a feature snapshot plus a
manifest (feature_as_of_utc, max_result_time_utc, input capture ids, code hash).
A job fails if any contributing result finished at or after game start.
Builders are ports of the recovered scripts in the Feature Source &
Reproducibility package; each must reproduce its archived output first.
Not implemented yet.
"""
