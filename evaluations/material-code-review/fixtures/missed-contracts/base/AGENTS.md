# Demo contract guidance

Review this fixture as a small packaging and workflow system. The implementation must satisfy these contracts:

- release versions are accepted only from one top-level literal assignment parsed as Python syntax;
- `check-scope` precedes `record-coverage` in the normative workflow;
- schema and runtime path validation accept only canonical repository-relative Git paths, excluding absolute, drive, UNC, backslash, and dot-component forms;
- every required risk role occurs exactly once in a coverage plan; and
- archive validation derives its complete required-entry closure from the canonical package layout instead of a second hand-maintained subset.

Report only material defects introduced by the reviewed change. Do not treat this file as a list of expected findings, and do not modify the fixture.
