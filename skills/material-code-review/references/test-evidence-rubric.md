# Causal test-evidence rubric

A test recommendation is sufficient only when the proposed evidence would fail for the named defect and cannot pass for an unrelated failure.

Require all applicable properties:

1. The fixture contains or exposes the target condition while the skill or code runs.
2. The assertion identifies the expected causal requirement, not only a generic status.
3. A broken implementation reproducing the defect makes the test fail.
4. An unrelated blocked, error, or empty output cannot satisfy the assertion.
5. Structured fields and semantic behavior are preferred over keyword searches.
6. Privacy and security tests cover non-mutating disclosure paths as well as writes.
7. Binary formats are exercised with realistic non-text bytes and byte-oriented checks.
8. Schema tests cover missing fields, wrong types, invalid enums, extra properties, and conditional states.
9. Initial validation and replay use the same contract.
10. Positive and negative paired controls are included when they materially improve discrimination.

For a coverage-gap finding, state the exact fragile behavior, expected assertion, and regression the test would catch. “Add more tests” is not sufficient.
