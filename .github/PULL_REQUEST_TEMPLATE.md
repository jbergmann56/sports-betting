## Scope and authority

- Workstream (sport/UI/shared):
- Model release(s), role, original authorization (or N/A):
- Historical scored records, betting tiers, EV/Kelly, wagers/P&L changed? (yes/no; describe):
- Explicitly preserved frozen evidence and any archived files:

## Documentation updated in this PR

- [ ] `ROADMAP.md` — actual status / next steps
- [ ] `docs/sports/<sport>.md` when changing a sport model or bet sheet
- [ ] `docs/model-authority.md` when changing scoring models or release rules
- [ ] `docs/betsheets/shared-contract.md` when changing bet-sheet format or eligibility
- [ ] `docs/architecture.md` for shared core/data changes
- [ ] `docs/streamlit.md` for UI changes
- [ ] `docs/cleanup-inventory.md` for archive/untracking changes

If not applicable, state why rather than checking boxes indiscriminately.

## Validation evidence

- [ ] `python -m unittest discover -s tests -v`
- [ ] `python -m gambling audit` (where evidence baseline available)
- [ ] `python -m gambling models verify` (for release/model changes)
- [ ] Frozen-score, EV, tier and adjusted-Kelly parity tests (for scoring changes)
- [ ] Documentation change gate

Commands/results and exceptions:

## Data hygiene

- [ ] No secrets, cookies, personal account exports or runtime SQLite are committed.
- [ ] No destructive changes to historic evidence.
- [ ] Any file untracked as "obsolete" has independently verified local backup/checksum and restore test.
