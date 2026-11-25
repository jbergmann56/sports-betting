# legacy_models/ — archived reference code (read-only)

Original model source packages and release evidence carried over from the
ChatGPT-era workflow. They are **not imported** by the `gambling` package and
must not be edited or "cleaned up": their bytes are evidence, and several files
are referenced by recorded hashes (see `nba_r4/RELEASE_HASHES.json`).

Porting a model means writing a new adapter under `gambling/` that reproduces
these outputs exactly against golden fixtures (ROADMAP Phase 2).
