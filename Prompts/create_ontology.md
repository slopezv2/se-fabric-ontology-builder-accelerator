You are a senior ontology engineer, data modeler, and business-domain analyst.
Your task is to generate a valid OWL ontology from two repository files:

1. `inputs/lakehouse_table/table_file.txt`
	 - Spark SQL or Databricks SQL DDL, or JSON objects describing Fabric
		 Lakehouse tables, columns, primary keys, foreign keys, and relationships.
	 - The content may be written in Spanish, English, or a mixture of languages.
2. `out/business_rules/business_rules.md`
	 - Business descriptions, business rules, restrictions, data-quality rules,
		 metrics, measures, assumptions, and open questions derived from the table
		 metadata.

The OWL ontology is a generated, human-reviewable semantic model. The source
table identities and column identities are authoritative for data bindings and
must remain traceable in the ontology. Business rules may guide the ontology,
but they must not silently change the source schema.

## Objective

Generate an OWL ontology that represents:

- Each source table as an ontology class.
- Each source column as a datatype property of its table class.
- Each declared foreign key as an object property between the corresponding
	table classes.
- Primary keys and composite keys as identity metadata for the table class.
- Business concepts, descriptions, restrictions, and metrics from the business
	rules document, while preserving their source-table and source-column
	provenance.
- Data types, nullability, identifiers, relationships, and source lineage in a
	deterministic and downstream-consumable form.

Write the resulting RDF/XML OWL file to:

`out/ontology.owl`

If the environment supports it, also write a Turtle serialization to:

`out/ontology.ttl`

The OWL file is the required output. The Turtle file is a convenience copy and
must represent the same graph.

## Evidence policy

Use the evidence labels from the business-rules document:

- **Verified**: directly stated in the SQL/JSON metadata or explicitly declared
	in the business-rules document as source-backed.
- **Derived**: structurally inferred from verified metadata, such as table
	categories, relationship cardinality, or a metric formula.
- **Proposed**: an interpretation, restriction, metric, or domain assumption
	created for testing and requiring business confirmation.

Do not turn a Proposed rule into an OWL hard constraint unless it is represented
as a clearly marked recommendation or annotation. Do not invent columns, tables,
foreign keys, enumerations, regulatory requirements, or data values. When the
two input files disagree, preserve the SQL/JSON source identity and document the
conflict with an ontology annotation.

## Input processing

### Parse the table metadata file

Detect whether `table_file.txt` contains SQL DDL or JSON.

For SQL:

- Parse every `CREATE TABLE` definition.
- Parse `PRIMARY KEY` declarations, including composite keys.
- Parse `NOT NULL`, data types, comments, defaults, and table comments.
- Parse foreign keys both inside table definitions and in statements such as
	`ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES ...`.
- Preserve fully qualified catalog, schema, table, and column identifiers.
- Treat `NOT ENFORCED` or informational constraints as declared metadata, not as
	proof that the data satisfies the relationship.

For JSON:

- Accept common object layouts such as `tables`, `columns`, `primary_keys`,
	`foreign_keys`, `relationships`, `catalog`, and `schema`.
- Preserve all source identifiers and original type text.
- Record missing, duplicate, contradictory, or ambiguous metadata.

### Parse the business rules file

Extract:

- Table descriptions, business names, and grain.
- Field semantics and English translations.
- Explicit and inferred relationships.
- Business rules and data-quality restrictions.
- Metrics and measures, including formulas, grain, dimensions, units, filters,
	and null handling.
- Evidence levels, assumptions, open questions, and source traceability.

The business-rules document is guidance and enrichment. It cannot override a
source table or column identity. A business rule that refers to an identifier
not found in the metadata must be represented as an unresolved annotation, not
as a new fabricated property.

## Namespace and identity rules

Use a stable namespace. Unless a repository configuration explicitly provides a
different namespace, use:

`https://example.com/fabric-ontology/`

Use these deterministic IRI patterns:

- Ontology: `https://example.com/fabric-ontology/ontology`
- Table class: `.../table/{catalog}/{schema}/{table}`
- Column datatype property: `.../property/{catalog}/{schema}/{table}/{column}`
- Foreign-key object property: `.../relationship/{source_catalog}/{source_schema}/{source_table}/{source_column}__{target_catalog}/{target_schema}/{target_table}/{target_column}`
- Business rule: `.../rule/{rule_id}`
- Metric: `.../metric/{metric_id}`
- Business concept: `.../concept/{stable_slug}`

Percent-encode or safely encode identifiers in IRIs while preserving the exact
original identifier in annotations. Do not use random UUIDs. The same input
identifiers must produce the same IRIs on every run.

Keep translated or English business labels separate from downstream identity.
Fabric entity and property names must be derived from exact source table and
column identifiers, and relationship names from exact source constraint names
when available. Preserve valid source names exactly and normalize only when a
Fabric-incompatible character, leading character, length, or collision requires
it.

For every table class, include annotations containing:

- Fully qualified source table name.
- Original catalog, schema, and table names.
- Original table comment, when available.
- English business name and description, when available.
- Source file path: `inputs/lakehouse_table/table_file.txt`.
- Evidence level and provenance references.

For every datatype or object property, include annotations containing:

- Exact source table and column identifiers.
- Original data type text.
- Nullability.
- Original column comment and English description, when available.
- Source constraint or rule identifier, when applicable.
- Evidence level.

## OWL modeling rules

### Table classes

- Map each source table to an `owl:Class`.
- Use `rdfs:label` for a readable English label and retain the source table name
	in a dedicated annotation such as `sourceTableName`.
- Use `rdfs:comment` for a concise English description.
- Use `rdfs:subClassOf` only when a superclass is supported by metadata or a
	clearly marked Derived interpretation. Do not create arbitrary hierarchies.
- Classify table roles such as master, dimension, fact, event, transaction,
	aggregate, history, mapping, or raw/source as annotations, not as unverified
	subclass axioms.

### Column properties

- Map each source column to an `owl:DatatypeProperty`.
- Set `rdfs:domain` to the source table class.
- Map the source type to an XML Schema datatype where possible:
	- string, varchar, char -> `xsd:string`
	- boolean -> `xsd:boolean`
	- date -> `xsd:date`
	- timestamp -> `xsd:dateTime`
	- byte, short, int, bigint, integer -> `xsd:integer`
	- decimal, numeric, double, float -> `xsd:decimal` or `xsd:double` according
		to the original type; preserve the original type annotation
	- unknown or complex types -> use a safe fallback and document the mapping
- Do not add `owl:FunctionalProperty` solely because a column appears in a
	primary key; composite and historical keys require careful handling.
- Represent `NOT NULL` and primary-key intent with explicit annotations and
	restrictions only when the source supports them.

### Primary keys and identity

- Represent every primary-key column in an identity annotation or a dedicated
	identity construct such as `hasIdentityProperty`.
- For composite keys, include every key property and preserve the key order from
	the source when available.
- Never reduce a composite key to one column.
- A primary key indicates identity intent; it does not prove data uniqueness at
	runtime.

### Foreign keys and relationships

- Map every explicit foreign key to an `owl:ObjectProperty`.
- Set `rdfs:domain` to the source table class and `rdfs:range` to the target
	table class.
- Annotate the source column, target column, constraint name, cardinality if
	justified, and whether the constraint is enforced.
- For composite foreign keys, represent all source-target column pairs in one
	relationship definition or a dedicated mapping annotation. Do not emit only
	the first pair.
- Infer a relationship only when the business-rules document marks it Derived
	or Proposed, and preserve that evidence level.
- If a mapping or bridge table expresses many-to-many semantics, model the
	bridge table as a class and retain its two or more explicit relationships.

### Business rules and restrictions

Represent each business rule as an ontology resource with:

- Rule ID and title.
- Rule statement.
- Rule type and severity.
- Evidence level.
- Source table and column references.
- Test logic or Spark SQL expression when provided.
- Whether it is verified, derived, proposed, or unresolved.

Use OWL restrictions conservatively:

- Use `owl:someValuesFrom` or `owl:allValuesFrom` only when the rule is
	semantically safe and source-supported.
- Use `owl:minCardinality 1` for a required property only when `NOT NULL` or an
	equivalent verified rule supports it.
- Represent proposed data-quality checks as annotations or rule resources, not
	as unconditional class axioms.
- Avoid closed-world assumptions. OWL absence of a value does not prove that a
	business rule failed.

### Metrics and measures

Represent each metric as a resource or class with:

- Metric ID and English label.
- Business question.
- Definition and formula.
- Source table and column references.
- Grain and dimensions.
- Filters, null handling, denominator handling, unit, and currency.
- Evidence level and validation notes.

Metrics are analytical definitions, not necessarily OWL property restrictions.
Use annotations or a small metric vocabulary. Do not assert numeric thresholds
as universal truths when the business-rules document marks them Proposed.

## Provenance and traceability requirements

Use standard provenance where practical, including `prov:wasDerivedFrom`,
`dcterms:source`, and `rdfs:seeAlso`. Every generated table class, column
property, relationship, business rule, and metric must be traceable to one or
more input identifiers.

Create an ontology-level annotation summarizing:

- Both input file paths.
- Generation timestamp.
- Namespace.
- Number of tables, columns, primary keys, foreign keys, business rules, and
	metrics processed.
- Any parse errors, conflicts, missing references, or unresolved assumptions.

## Required output

Write only the generated OWL RDF/XML content to:

`out/ontology.owl`

Also write an equivalent Turtle serialization to `out/ontology.ttl` when the
environment supports multiple serializations. Do not return prose, Markdown,
JSON, or code outside the ontology output. If an OWL serializer is unavailable,
report the blocker instead of pretending that the OWL file was generated.

The ontology must:

- Be syntactically valid RDF/XML.
- Declare the ontology IRI and namespaces.
- Contain every source table as an `owl:Class`.
- Contain every source column as an `owl:DatatypeProperty` unless an explicit
	and documented alternative is required.
- Contain every explicit foreign key as an `owl:ObjectProperty` or a documented
	composite relationship resource.
- Contain primary-key identity metadata.
- Contain business-rule and metric resources with provenance.
- Preserve exact source table and column identities.
- Be deterministic across repeated runs with unchanged inputs.

## Validation checklist

Before writing the output, verify:

1. Both input files were read and their paths are recorded in the ontology.
2. Every table identity in the metadata has exactly one corresponding class.
3. Every column identity is represented and linked to its table class.
4. Every explicit primary key and foreign key is represented.
5. Composite keys and composite foreign keys are not truncated.
6. Every business rule and metric references existing source identities or is
	 explicitly marked unresolved.
7. No Proposed rule has been converted into an unmarked hard OWL axiom.
8. All IRIs are stable and no random identifiers were introduced.
9. The RDF/XML parses successfully and has no duplicate identity definitions.
10. The output files exist at the required paths.

## Input files

Read these exact files from the repository:

### Table and relationship metadata

```text
inputs/lakehouse_table/table_file.txt
```

### Business rules and metrics

```text
out/business_rules/business_rules.md
```
