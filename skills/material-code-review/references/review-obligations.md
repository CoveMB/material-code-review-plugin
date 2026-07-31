# Controlled review obligations

Use this guide to classify each change unit against every controlled risk before dispatch. Filenames are discovery hints only; positive and negative decisions require behavior- or contract-based evidence. The controller verifies plan completeness and result structure. Structural completion does not prove reviewer cognition or semantic quality.

Every positive `(unit_id, risk_code)` pair creates exactly one `review_obligation` and exactly one obligation assignment. The obligation's required lens and checks are fixed below. Negative decisions create no obligation. A low-risk plan therefore contains only the three core assignments.

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

**Non-trigger evidence:** schema and runtime acceptance languages match, repository paths share one canonical spelling, and required values have exact cardinality and uniqueness constraints.

**Required lens:** `api_config_compatibility`.

**Required checks:** `schema_runtime_parity`, `canonical_git_path_language`, `required_value_cardinality`.

A `pass` cites matching accepted/rejected examples and cardinality controls. `finding_emitted` points to the local mismatch finding. `blocked` identifies the missing schema, runtime owner, or executable contract evidence.

## `distribution_contract_integrity`

**Positive trigger:** changed package composition, manifests, validators, archive layouts, or shipped references can alter runtime or contract closure.

**Non-trigger evidence:** every runtime import and referenced file is transitively shipped, and removing any required entry makes validation fail.

**Required lens:** `reliability`.

**Required checks:** `manifest_reference_closure`, `remove_one_required_entry`, `paired_control`.

A `pass` cites the manifest-to-archive closure and the remove-one negative control. `finding_emitted` points to the local missing-entry finding. `blocked` names the archive, manifest, or validation route that was unavailable.

## `normative_workflow_coherence`

**Positive trigger:** changed procedures, command sequences, lifecycle states, prerequisites, or canonical workflow prose can change the permitted order of operations.

**Non-trigger evidence:** every named step exists, prerequisites precede dependent steps, paired controls preserve mandatory gates, and repeated canonical wording agrees.

**Required lens:** `standards_alignment`.

**Required checks:** `normative_sequence`, `prerequisite_before_dependent_step`, `paired_control`.

A `pass` cites the complete ordered sequence and its prerequisite control. `finding_emitted` points to the local omission or ordering finding. `blocked` identifies the missing canonical owner or conflicting authority.

## `user_selectable_output_paths`

**Positive trigger:** changed behavior writes authoritative or auxiliary artifacts to a user-selectable destination, including a pre-existing destination that gains a writer, cleanup target, or write-order dependency.

**Non-trigger evidence:** resolved destinations, aliases, writers, cleanup behavior, and success/failure ordering show no new collision or data-loss opportunity.

**Required lens:** `reliability`.

**Required checks:** `destination_collision`, `writer_cleanup_order`.

A `pass` cites resolved destination identities and both ordering paths. `finding_emitted` points to the local collision or cleanup finding. `blocked` names the unresolved platform alias or unavailable writer path.

## `persisted_config_semantics`

**Positive trigger:** changed behavior alters a persisted field's accepted shape, serialization, default, missing-key fallback, interpretation, migration, durable output, or downstream local/remote identity.

**Non-trigger evidence:** accepted shapes, missing and explicit-empty states, defaults, migrations, durable output, and downstream identity remain unchanged.

**Required lens:** `migration_data_safety`, with supporting lens `api_config_compatibility`.

**Required checks:** `accepted_shape_and_default`, `migration_and_identity`.

A `pass` cites the state matrix and identity-preserving migration evidence. `finding_emitted` points to the local compatibility or identity finding. `blocked` identifies the missing historical shape, migration path, or downstream identity evidence.
