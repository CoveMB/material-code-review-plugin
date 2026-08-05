# Controlled review obligations

Use this guide to classify each change unit against every controlled risk before dispatch. Filenames are discovery hints only; positive and negative decisions require behavior- or contract-based evidence. The controller verifies plan completeness and result structure. Structural completion does not prove reviewer cognition or semantic quality.

Every positive `(unit_id, risk_code)` pair creates exactly one `review_obligation` and exactly one obligation assignment. The obligation's required lens and checks are fixed below. Negative decisions create no obligation. A low-risk plan therefore contains only the three core assignments.

The separate specialist roster is exactly `security_privacy`, `reliability`, `api_contract`, `migration_deployment`, `concurrency`, `performance`, `documentation`, and `architecture_simplification`. Every change unit classifies every specialist as selected or rejected. Under `depth:auto`, behavior evidence selects applicable lenses and ambiguous or unknown applicability selects rather than rejects. Under `depth:full`, every lens is selected for every unit. Each selected decision defines one or more plan-unique atomic scenarios with a bounded claim, exact in-unit evidence paths, and a concrete countercontrol. Each selected lens receives one specialist assignment over the exact selected units and their complete primary/context union, with the exact union of scenario codes as its required checks. Specialist assignments have no `obligation_id` and cannot satisfy a controlled obligation.

For every required check, return one outcome:

- `pass`: concrete observed evidence and no finding IDs;
- `finding_emitted`: concrete observed evidence plus one or more candidate-local finding IDs from the same assignment;
- `blocked`: the missing or inaccessible evidence. A blocked result does not complete the wave.

## `verification_mechanism_semantics`

**Positive trigger:** changed validators, parsers, checkers, or enforcement logic can accept invalid artifacts, reject valid artifacts, or inspect a non-authoritative representation.

**Non-trigger evidence:** the authoritative parser and value are identified, decoy text and duplicate definitions cannot satisfy the check, and positive and negative controls exercise the same path.

**Required lens:** `adversarial_verification`.

**Required checks:** `authoritative_parsing`, `decoy_duplicate_resistance`, `paired_control`.

A `pass` names the authoritative parse result and both controls. `finding_emitted` points to the local finding that records the bypass. `blocked` names the parser, fixture, or executable evidence that could not be inspected.

## `machine_contract_semantics`

**Positive trigger:** schemas, runtime validators, serializers, enums, or adapters jointly define a machine-facing input or output contract.

**Non-trigger evidence:** schema and runtime acceptance languages match, repository paths share one canonical spelling, required values have exact cardinality and uniqueness constraints, and affected privileged fields agree on exact runtime type and supported value domain.

**Required lens:** `api_config_compatibility`.

**Required checks:** `schema_runtime_parity`, `canonical_git_path_language`, `required_value_cardinality`, `privileged_field_type_exactness`.

`privileged_field_type_exactness` applies to an affected machine-facing field whose value controls authorization, ownership, deletion or cleanup, mutation, publication or external writes, migration, or schema/version interpretation. A `pass` identifies the field's exact runtime type and supported value domain and cites relevant serialized accepted and rejected controls, including boolean, integer/float cross-type, string, `null`, missing, and unsupported enum/version values where applicable. If no affected privileged field exists, the evidence names the inspected contract and explains why none of its fields controls consequential behavior.

A `pass` cites matching accepted/rejected examples and cardinality controls. `finding_emitted` points to the local mismatch finding. `blocked` identifies the missing schema, runtime owner, or executable contract evidence.

## `distribution_contract_integrity`

**Positive trigger:** changed package composition, manifests, validators, archive layouts, or shipped references can alter runtime or contract closure.

**Non-trigger evidence:** every runtime import and referenced file is transitively shipped, and removing any required entry makes validation fail.

**Required lens:** `reliability`.

**Required checks:** `manifest_reference_closure`, `remove_one_required_entry`, `paired_control`.

A `pass` cites the manifest-to-archive closure and the remove-one negative control. `finding_emitted` points to the local missing-entry finding. `blocked` names the archive, manifest, or validation route that was unavailable.

## `normative_workflow_coherence`

**Positive trigger:** changed procedures, command sequences, lifecycle states, prerequisites, mode-selection branches, configuration or client dependencies, or canonical workflow prose can change the permitted order of operations or make a disabled subsystem block otherwise permitted behavior.

**Non-trigger evidence:** every named step exists, prerequisites precede dependent steps, paired controls preserve mandatory gates, repeated canonical wording agrees, and either no optional or disabled subsystem boundary exists or disabled-subsystem configuration and client setup remain behind the applicable mode branch.

**Required lens:** `standards_alignment`.

**Required checks:** `normative_sequence`, `prerequisite_before_dependent_step`, `paired_control`, `disabled_mode_dependency_boundary`.

A `pass` cites the complete ordered sequence and its prerequisite control. `finding_emitted` points to the local omission or ordering finding. `blocked` identifies the missing canonical owner or conflicting authority.

`disabled_mode_dependency_boundary` traces configuration loading, parsing, validation, and external-client setup on every path before and after the mode-selection branch. A `pass` cites the branch and a malformed-or-missing disabled-subsystem configuration control that still permits unrelated local behavior, or cites an explicit canonical contract requiring global validation. If the reviewed workflow has no optional or disabled subsystem boundary, a `pass` names the inspected entry points and explains why the check is not applicable. `finding_emitted` identifies the disabled-subsystem dependency that blocks an otherwise permitted path. `blocked` names the unavailable mode branch, configuration owner, or negative control.

## `user_selectable_output_paths`

**Positive trigger:** changed behavior writes authoritative or auxiliary artifacts to a user-selectable local destination or selects a local or remote logical target at runtime, including a pre-existing destination or target that gains a writer, cleanup target, or write-order dependency.

**Non-trigger evidence:** resolved local and remote targets, applicable filesystem aliases, every runtime writer and cleanup target, ownership or precedence, cleanup behavior, and success/failure ordering show no new collision, retargeting, or data-loss opportunity.

**Required lens:** `reliability`.

**Required checks:** `destination_collision`, `canonical_filesystem_identity`, `runtime_writer_target_inventory`, `writer_cleanup_order`, `runtime_target_derivation_parity`, `validation_to_mutation_identity_stability`.

`destination_collision` covers direct configured or resolved collisions. `writer_cleanup_order` covers write, delete, success, and failure sequencing. A `pass` cites resolved destination identities and both ordering paths. `finding_emitted` points to the local collision or cleanup finding. `blocked` names the unresolved direct destination or unavailable ordering path.

`canonical_filesystem_identity` compares every applicable local destination using exact spelling, platform case folding, Unicode normalization, symlink or same-file resolution, and parent-child containment. A `pass` identifies the applicable identity classes and cites accepted and rejected alias controls. If no local destination is selected, a `pass` names the inspected runtime target selection and explains why no filesystem identity class applies. An applicable class that cannot be inspected or simulated is `blocked`, even when another destination collision has already emitted a finding.

`runtime_writer_target_inventory` enumerates every authoritative and auxiliary writer, cleanup target, retained or discovered artifact that can become an input or writer, and local or remote logical target selected at runtime. A `pass` cites the complete runtime inventory and proves unique ownership or explicit precedence for every target. `finding_emitted` identifies the conflicting runtime writers or target owners. `blocked` names the unresolved runtime selection or retained-artifact path.

`runtime_target_derivation_parity` traces every configured value, normalization, sanitization, collision suffix, reuse rule, affix, adapter, and writer selection that determines the final target. A `pass` identifies one authoritative derivation shared by validation and execution and cites paired equal/distinct final-identity controls. `finding_emitted` identifies a derivation mismatch or ownership collision. `blocked` names the unresolved transformation, target-selection owner, writer, or causal control.

`validation_to_mutation_identity_stability` traces the interval from the last accepted validation through every write, replace, rename, delete, cleanup, publication, or other mutation. A `pass` cites the invariant binding validation to mutation and a negative control at the latest meaningful replacement, rebinding, parent-change, stale-handle, or concurrent interleaving point. `finding_emitted` identifies a validate-then-mutate identity gap. `blocked` names the unavailable mutation boundary, platform control, or interleaving evidence.

## `persisted_config_semantics`

**Positive trigger:** changed behavior alters a persisted field's accepted shape, serialization, default, missing-key fallback, interpretation, migration, durable output, or downstream local/remote identity.

**Non-trigger evidence:** accepted shapes, missing and explicit-empty states, defaults, migrations, durable output, and downstream identity remain unchanged.

**Required lens:** `migration_data_safety`, with supporting lens `api_config_compatibility`.

**Required checks:** `accepted_shape_and_default`, `migration_and_identity`.

A `pass` cites the state matrix and identity-preserving migration evidence. `finding_emitted` points to the local compatibility or identity finding. `blocked` identifies the missing historical shape, migration path, or downstream identity evidence.
