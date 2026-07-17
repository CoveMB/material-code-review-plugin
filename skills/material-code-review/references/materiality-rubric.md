# Materiality and calibration rubric

A review candidate is not a finding merely because a different implementation is imaginable. First establish factual validity, then materiality.

## Behavioral confidence anchors

- `certain`: the cited code directly entails the claim; little or no interpretation is required.
- `high`: source, surrounding behavior, callers, and counterevidence were checked and a concrete negative consequence is strongly supported.
- `medium`: the concern is plausible and evidenced, but an important condition or impact remains uncertain. It is normally discarded unless blocker/high impact and paired with required pre-fix verification.
- `low`: do not emit except a blocker-risk candidate that must remain visible despite uncertainty.

Confidence is not severity. Severity describes consequence; confidence describes evidential support.

## Defect materiality

Keep a defect, risk, documentation gap, or coverage gap only when all are true:

1. Exact evidence exists in the frozen source, diff, test, contract, or documentation.
2. A plausible observable negative consequence is identified.
3. The concern is more than style, preference, or ordinary linter output.
4. The current change introduces it, exposes it, or directly relies on it.
5. Independent validation confirms it, or a blocker/high uncertain concern states exactly what must be verified before repair.
6. The root cause is supported rather than inferred from a symptom alone.

A serious defect is not discarded merely because the correct repair is substantial. Repair risk affects planning, not factual validity.

## Optional improvement materiality

An optional simplification, DRY, or architecture improvement must pass every defect-level gate and both additional gates:

- current cost is demonstrated now: meaningful branching, indirection, configuration surface, divergence, coupling, or recurring maintenance burden;
- benefit exceeds implementation churn, regression risk, and conceptual overhead.

Reject short-code preferences, small local duplication, speculative future extensibility, and abstractions that make the code harder to understand.

## Coverage gaps

Keep a test finding only when it names the exact fragile behavior, expected assertion, and plausible regression the test would catch. “Add more tests” is not a finding.

## Documentation gaps

Keep only mismatches that can mislead a user, caller, operator, or maintainer about real behavior, configuration, safety, or compatibility.

## Pre-existing code

Unchanged code is primary only when the current change directly calls it, changes its reachability, relies on its contract, or makes its dormant failure observable. Otherwise discard as `PRE_EXISTING_UNRELATED`.

## Severity

- `blocker`: exploitable security issue, data loss/corruption, core behavior failure, or merge-invalid state.
- `high`: likely defect or significant contract/maintenance failure under normal use.
- `medium`: meaningful bounded downside or fragile behavior with a clear fix.
- `low`: narrow consequence; keep only when it still clears every materiality gate.
