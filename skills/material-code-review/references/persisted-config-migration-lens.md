# Persisted-configuration migration lens

Use only when the verified root-owned coverage plan assigns `migration_data_safety` or `api_config_compatibility` for a present `persisted_config_semantics` assessment.

## Compatibility matrix

Compare baseline and comparison behavior for a new-file default, a missing-key fallback, an explicit empty value, an explicit legacy value, and an explicit custom value.

## Downstream identity

Trace every semantic difference through serialization, durable local output, external target identity, remote mutation, and user-visible migration behavior. A previously accepted missing-key payload must not silently select a different external target without explicit migration authority.

## Counterevidence

Check schema requirements, version gates, migration documentation, creation-time normalization, baseline fixtures, and whether older writers always persisted the field. State residual compatibility exposure precisely.
