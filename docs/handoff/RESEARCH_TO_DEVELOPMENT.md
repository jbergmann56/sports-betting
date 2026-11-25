# ChatGPT model research → Claude Code implementation protocol

**This is the intended permanent collaboration workflow.** Research happens in ChatGPT; Claude handles application engineering. Both use GitHub documents and versioned artifacts, not implicit shared chat memory.

## Stage A — ChatGPT research proposal

User and ChatGPT evaluate a model's forecast evidence on a **named immutable dataset**, with time cutoffs, release identifiers, paired same-price champion/challenger comparisons, holdout procedures, calibration scores, EV/log-growth uncertainty and known data leakage risks. ChatGPT records a recommendation with:
- Problem statement and reproducible sample IDs/selection criteria.
- Exact input dataset path, SHA256, column contract, source dates and exclusions.
- Champion release and candidate/challenger release/version/role; protected frozen archive reference.
- Mathematical transformation, feature definition, model specification, fitting parameters, overrides and market/push conventions.
- Side-by-side expected/model performance and segment breakdown; sample size/uncertainty.
- Tier and Kelly implications, if any; distinguish research inference from wagering authorization.
- **Decision:** reject, research only, shadow, promote after tests, or explicitly user-approved production change.
- Defined golden fixtures, success criteria, roll-back conditions and what must not change.

Use `RESEARCH_CHANGE_REQUEST_TEMPLATE.md`. Store a brief decision record under `docs/research/decisions/YYYY-MM-DD-<sport>-<topic>.md`; include references to exact supporting files rather than pasting huge data dumps into Git.

## Stage B — Claude implementation branch

Claude reads the research ticket, cross-checks artifact existence and time boundaries against repository. If a required parameter, historical file or approval is missing, **mark blocked**; do not silently approximate. Make only scoped work on `sport/<sport>` or a short-lived core/feature branch. Update affected code/fixtures, `docs/sports/<sport>.md`, model registry/status migration where justified, `docs/model-authority.md`, `docs/betsheets/shared-contract.md` as applicable, and `ROADMAP.md`.

Require a new immutable release ID for changed probabilities/calibration, and preserve original point-in-time observations. Run frozen parity, model verification, invariance and missing-input tests.

## Stage C — Claude implementation report returned to ChatGPT

Every PR's handback should contain:

| Required field | Example |
|---|---|
| Branch, PR, commit SHA | `sport/nba` / PR # / full SHA |
| Model / role / artifact hashes | exact release ID(s), champion vs challenger |
| Input source evidence | dataset SHA256, cutoff, exclusion list |
| What code changed | file paths, algorithms, conditional gates, new fixtures |
| How to reproduce | commands, environment, external-data requirements |
| Tests | count, result, source fixtures, known parity deviations |
| Before/after outputs | same rows/quotes: model P, EV, tier, Full/Adjusted Kelly, status |
| Promotion authorization | explicit decision or **not authorized** |
| Open issues | missing sources, uncertainties, baseline differences |

Save this as `docs/research/implementations/YYYY-MM-DD-<sport>-<topic>.md`. Then bring the PR/document link to ChatGPT for independent model evaluation.

## Stage D — ChatGPT evaluation after implementation

ChatGPT reviews exact code, frozen outputs and report; repeats or independently assesses sample results, leakage control, calibration and expected growth. If changes are unsatisfactory, raise a new ticket or reject promotion. **Do not edit the production scorer to make a backtest look better**. A PR merge is a code release; formal model wagering authorization is a separate recorded act.

## Communication rules

- Claude cannot read ChatGPT conversation history simply because it has access to this repository.
- ChatGPT cannot know current local changes in Claude's working tree unless committed, exported or supplied.
- A branch name is not an approval. Both assistants should always say whether they are looking at `main`, the active sport branch, or a named Git commit.
- Prefer a short dated research decision per meaningful refinement, not editing the global engineering policy for every experiment.
- Dataset version, release and quote cohorts must not drift between research and implementation without an explicit audit trail.
- Keep personal account and financial data out of Git; pass only privacy-safe, aggregated synthetic or redacted fixtures for engineering.
- Claude should not conduct unapproved research-based auto-refits; it may surface engineering or test anomalies for ChatGPT to assess.
