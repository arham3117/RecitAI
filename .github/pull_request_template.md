## What this changes

<!-- One or two sentences. If it fixes an issue, link it. -->

## Why

<!-- The reasoning, not just the restatement. If this reverses an earlier decision, say
     which one (decision log, `D-0NN`). -->

## Checks

- [ ] `make lint` passes (ruff + black + mypy strict)
- [ ] `make test` passes
- [ ] `make reconcile` reports no orphans
- [ ] `cd frontend && npx tsc --noEmit && npx next build` pass
- [ ] No formatter was run over `frontend/` or `backend/recitai/constants.py`

## If this touches generation quality

- [ ] Measured with a seeded A/B (`make compare LOGS="before.txt after.txt"`)
- [ ] `make eval` still reports topic coverage ≥ 90%

<!-- A quality change without a measurement is an opinion. Two have already been reverted
     here on measurement: see D-013 and I-029 in the decision and issue logs. -->

## Logs updated

- [ ] Decision log — if a decision was taken
- [ ] Issue register — if a problem was found or closed
