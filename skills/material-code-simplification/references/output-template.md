# Output templates

## Gate A presentation

### Scope and limits

- Run ID and artifact directory
- Scope mode, selected prefixes, exclusions, refs/working tree, untracked policy
- Scope hash and snapshot limitations
- Architecture/behavior-map coverage and unknowns
- Reviewer/validator identities, actual independence groups, and degraded modes

### Action posture

State the shared controller verdict and translate it for codebase mode where necessary. Do not claim merge blocking unless an actual merge is in scope.

### Kept opportunities

For every `F###`:

- title, category, severity, confidence;
- exact evidence;
- present complexity cost and trigger scenario;
- behavior/contracts to preserve;
- proposed reduction class and bounded replacement shape;
- “leave as is” and smaller alternatives checked;
- validation result and counterevidence;
- estimated risk and unresolved assumptions;
- recommended action.

### Discarded candidates

List every group with candidate IDs, title, discard code, and specific reason. Include validator rejection, harmless duplication, justified boundary, missing behavior evidence, poor tradeoff, and rewrite rejection explicitly.

### Decision request

Ask the user to approve, reject, or defer each kept ID. Stop.

## Gate B presentation

For every approved ID show:

- transformation class and why it is the smallest sufficient shape;
- behavior and contracts to preserve;
- ordered steps;
- exact changed/new/deleted paths;
- dependency/configuration/migration effects;
- characterization sequence;
- exact commands, working directories, timeouts, and purposes;
- success evidence, rollback, risk controls, and attempt limit.

Show plan hash and request explicit approval or rejection. Stop.

## Final report

### Result

- Controller state and action posture
- Fixed, rolled back, blocked, unresolved, user-rejected, user-deferred, and record-only IDs
- Why each retained delta is net simpler

### Evidence chain

- Scope hash
- Candidate bundle and ledger hashes
- Gate A receipt hash and faithful user statement
- Plan hash
- Gate B receipt hash and faithful user statement
- Fix summary and verification hashes

### Delta

- Changed, new, and deleted paths attributable to approved items
- Concepts/paths/states/dependencies/configuration removed
- Behavior/contracts preserved
- Any compatibility bridge retained and why

### Verification

- Exact test commands, exit codes, timeouts, and log paths
- Characterization before/after evidence
- Broader suite/build/static checks
- Independent verifier result and repair rounds

### Residual risk

- Unverified behavior and environment limits
- Areas requiring human domain/security/data/concurrency review
- Record-only unrelated observations
- Hallucination/incorrect-inference risk, especially around dynamic reachability and undocumented intent

Use `No material simplifications recommended.` only for an adjudicated empty material set explicitly accepted at Gate A.
