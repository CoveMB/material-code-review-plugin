# Reliability and output-integrity lens

Use only when the verified root-owned coverage plan assigns `reliability` for a present `user_selectable_output_paths` assessment.

Use the controller-derived obligation `check_contracts`. Return every named `evidence_item` exactly once. In particular, `resolved_identity_matrix`, `writer_inventory`, and `derivation_trace` have `all_required_review_paths` scope: each must cite the complete assignment path set, not merely the files that contain the first apparent writer.

## Destination inventory

Enumerate authoritative outputs, metadata, splits, reports, debug logs, temporary files, cleanup targets, and publisher artifacts. Trace defaults and every user-selectable override on success and failure paths.

## Alias, ownership, and ordering checks

Check pairwise resolved-destination aliasing; relative, symlink-mediated, case-folded, Unicode-normalized, and relevant platform-specific path aliases; parent/child ownership overlap; success- and failure-path write ordering; and auxiliary or cleanup writes after authoritative writes. A successful command that can overwrite its own authoritative artifact is a material reliability defect.

Trace final-target derivation through every applicable configured value, transformation, collision adjustment, existing-target reuse rule, adapter, and writer selection. Validation and execution must use the same authoritative final identity; cite paired controls where raw identities diverge after transformation or distinct raw values collide after derivation.

Trace the last accepted validation through every final mutation. Check target and parent replacement, symlink rebinding, stale handles, rename/delete/cleanup, and relevant concurrent interleavings. Cite the invariant that binds the validated identity to mutation and a negative control at the latest meaningful interleaving point.

## Counterevidence

Check early path validation, atomic replacement semantics, no-follow behavior, ownership metadata, guarded cleanup, write ordering, and causal custom-path tests. Do not report a collision that the existing boundary rejects before authoritative mutation.
