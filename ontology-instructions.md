# Ontology Generation Instructions

Generate the RDF/OWL ontology as the canonical semantic artifact. Preserve
source identities exactly and keep target-platform naming concerns in a
separate deterministic projection.

## Names and identities

- Use percent-encoded source identifiers in stable table, property, and
	relationship IRIs.
- Keep exact catalog, schema, table, column, and constraint names in mapping
	fields and provenance annotations.
- Use readable English `rdfs:label` values; labels may contain spaces and
	Unicode and do not need to be valid Fabric identifiers.
- Fabric item names must match `^[A-Za-z][A-Za-z0-9_]{0,88}$`.
- Fabric entity, property, and relationship names must match
	`^[A-Za-z][A-Za-z0-9_-]{0,127}$`.
- Normalize Fabric names deterministically and use a stable source-IRI hash for
	collisions or truncation. Never use random IDs or encounter-order suffixes.

## Fabric identity compatibility

- Preserve all primary-key columns and their source order in OWL annotations
	and mapping JSON.
- Fabric entity key properties must be projected as `String` or `BigInt`.
- When a source identity uses another datatype, retain the original RDF and
	source datatypes and project only the Fabric definition value type to
	`String`.
- Never remove a composite-key component or substitute a non-key field merely
	to satisfy Fabric constraints.

## Determinism

- Sort source resources by stable source identity before serialization.
- Keep generated names, IRIs, IDs, mapping arrays, and output paths stable for
	unchanged inputs.
- Preserve deliberate JSON property order in Fabric definitions because some
	discriminator fields, including `sourceType`, must be emitted first.
