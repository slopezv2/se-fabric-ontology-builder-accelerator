---
name: create-ontology
description: "Generate and validate deterministic, Fabric-publishable RDF/XML OWL, Turtle, and JSON mapping artifacts from caller-selected Fabric Lakehouse SQL/JSON metadata and a business-rules Markdown report. Use when creating ontology classes, datatype properties, foreign-key object properties, ordered identity metadata, Fabric-compatible names, business-rule resources, metrics, provenance, or validating generated ontologies with owlready2 and rdflib."
---

# Create Ontology

You are a senior ontology engineer, data modeler, and business-domain analyst.
Your task is to generate a valid OWL ontology from two caller-selected repository
files:

1. A table metadata file, normally under `inputs/lakehouse_tables/`.
   - Spark SQL or Databricks SQL DDL, or JSON objects describing Fabric
     Lakehouse tables, columns, primary keys, foreign keys, and relationships.
   - The content may be written in Spanish, English, or a mixture of languages.
   - Use the exact path supplied by the caller. Do not substitute the default
     fixture or another similarly named file.
2. A business-rules Markdown report, normally under `out/business_rules/`.
   - Business descriptions, business rules, restrictions, data-quality rules,
  metrics, measures, assumptions, and open questions derived from the table
  metadata. Use the exact caller-supplied path.

The OWL ontology is a generated, human-reviewable semantic model. The source
table identities and column identities are authoritative for data bindings and
must remain traceable in the ontology. Business rules may guide the ontology,
but they must not silently change the source schema.

## Objective

Generate an OWL ontology that represents:

- Each source table as an ontology class.
- Each source column as a datatype property of its table class, with a
  business-friendly property name and exact source identity retained as
  provenance.
- Each declared foreign key as a business-friendly object property between the
  corresponding table classes, with exact constraint and join columns retained.
- Primary keys and composite keys as identity metadata for the table class.
- Business concepts, descriptions, restrictions, and metrics from the business
  rules document, while preserving their source-table and source-column
  provenance.
- Data types, nullability, identifiers, relationships, and source lineage in a
  deterministic and downstream-consumable form.

Write the resulting RDF/XML OWL file to the caller-requested output path. If no
path is supplied, use:

`out/ontologies/example_storage_ontology.owl`

Also write a Turtle serialization beside the OWL file using the same base name,
for example
`out/ontologies/example_storage_ontology.ttl`.

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

For reports produced by the `extract-business-rules` skill:

- Read English table labels from the `Table Inventory` rows using the fully
  qualified source table as the key.
- Read rules from `Business Restrictions and Data-Quality Rules`, preserving
  the rule ID, title, scope/type/severity, test logic, evidence, and source
  references.
- Read metrics from `Business Metrics for Testing`. If rows do not provide
  explicit metric IDs, assign deterministic IDs in report order (`MET-001`,
  `MET-002`, and so on). Preserve the name, question/formula, grain/dimensions,
  null handling/unit, evidence, and source references.
- Do not silently emit zero metric resources merely because metric IDs are not
  present in the Markdown.

The business-rules document is guidance and enrichment. It cannot override a
source table or column identity. A business rule that refers to an identifier
not found in the metadata must be represented as an unresolved annotation, not
as a new fabricated property.

## Namespace and identity rules

Use a stable namespace. Unless a repository configuration explicitly provides a
different namespace, use:

`https://example.com/fabric-ontology/`

When the caller supplies an output name such as `example_storage_ontology`, preserve it
exactly under the requested output directory. Do not overwrite another
ontology output merely because the default name is `ontology.owl`.

Use deterministic IRIs with these stable patterns, but use business-friendly
labels for classes, properties, and relationships:

- Ontology: `https://example.com/fabric-ontology/ontology`
- Table class: `.../table/{catalog}/{schema}/{table}`
- Column datatype property: `.../property/{catalog}/{schema}/{table}/{column}`
- Foreign-key object property: `.../relationship/{source_catalog}/{source_schema}/{source_table}/{source_column}__{target_catalog}/{target_schema}/{target_table}/{target_column}`
- Business rule: `.../rule/{rule_id}`
- Metric: `.../metric/{metric_id}`
- Business concept: `.../concept/{stable_slug}`

Business-friendly naming rules:

- Prefer English business names from the business-rules report.
- Otherwise use the English translation of the source comment when available.
- Otherwise humanize identifiers by splitting underscores, hyphens, and camel
  case.
- Keep exact source identifiers in annotations such as `sourceTableName` and
  `sourceColumnName`; never replace provenance with a friendly name.
- Relationship labels should describe the business relationship while retaining
  source and target tables, columns, and constraint name.
- Friendly labels must be deterministic; do not invent random names or UUIDs.

### Fabric-compatible naming projection

Keep these three naming layers distinct:

- **Source identity**: preserve catalog, schema, table, column, and constraint
  names exactly in mapping fields and provenance annotations.
- **RDF identity**: percent-encode source identifiers in stable IRIs. Never
  rewrite an IRI merely to satisfy a Fabric display-name constraint.
- **Presentation and Fabric names**: keep `rdfs:label` and business names
  readable. The transformer derives strict Fabric identifiers from them.

When proposing or validating downstream Fabric names:

- Ontology item names must match `^[A-Za-z][A-Za-z0-9_]{0,88}$`. Normalize
  whitespace, hyphens, punctuation, and path separators to `_`; remove
  diacritics; prefix `Ontology_` when the result does not start with a letter.
- Entity type, property, and relationship names must match
  `^[A-Za-z][A-Za-z0-9_-]{0,127}$`. Derive entity and property names from exact
  source table and column identifiers, and relationship names from exact source
  constraint names when available. Never substitute an English or translated
  business label. Preserve valid names exactly and normalize only when needed
  for Fabric compatibility.
- Normalize first, then resolve collisions within the relevant scope by adding
  `_` plus a stable hash derived from the full source IRI. Never use encounter
  order, random UUIDs, or numeric counters for collision suffixes.
- Truncate before appending the stable hash so the final name remains inside
  its limit. Apply normalization consistently to create, exact-name lookup,
  `.platform` metadata, and update operations.
- Do not force Fabric-safe identifiers into `rdfs:label`; readable labels may
  contain spaces and Unicode. Store or derive target names separately.
- Prefer lowercase `snake_case` for generated output directory and file stems
  to make CLI paths portable. An explicit caller-supplied path always wins.

Fabric entity identities currently accept only properties projected as
`String` or `BigInt`. Preserve every source primary-key component and its order.
If an identity component has another RDF datatype, record that source datatype
unchanged and require the transformer to project only its Fabric value type to
`String`; never drop the component or silently replace it with a non-key field.

Percent-encode or safely encode identifiers in IRIs while preserving the exact
original identifier in annotations. Do not use random UUIDs. The same input
identifiers must produce the same IRIs on every run.

For every table class, include annotations containing:

- Fully qualified source table name.
- Original catalog, schema, and table names.
- Original table comment, when available.
- English business name and description, when available.
- The actual caller-supplied source file path.
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
- Because repeated RDF annotation values are unordered, also include one
  deterministic ordered identity annotation (for example, a JSON array in
  `primaryKeyDefinition`) and preserve the same ordered array in the mapping.
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

## Mapping export

Alongside the OWL and Turtle files, write a deterministic JSON mapping file with
the same base name, for example:

`out/ontologies/example_storage_ontology_mapping.json`

The mapping must contain:

- `tables`: fully qualified source table, business-friendly class name, class
  IRI, and primary-key columns.
- `fields`: source table, exact source column, business-friendly property name,
  property IRI, and original data type.
- `relationships`: constraint name, business-friendly relationship name, source
  table/column, target table/column, and object-property IRI.

The mapping is a reviewable provenance artifact, not a replacement for OWL.

Create an ontology-level annotation summarizing:

- Both input file paths.
- Generation timestamp.
- Namespace.
- Number of tables, columns, primary keys, foreign keys, business rules, and
  metrics processed.
- Any parse errors, conflicts, missing references, or unresolved assumptions.

Use the latest input-file modification time as the generation timestamp when a
stable timestamp is needed. Do not inject the wall-clock run time into otherwise
deterministic artifacts.

## OWL validation with owlready2

Before declaring the ontology complete, install the required libraries through
the repository-managed environment. `owlready2` validates OWL loading and
`rdflib` serializes Turtle and compares RDF graphs:

```powershell
uv sync
```

Run validation against the generated file with Python and `owlready2`.

### owlready2 implementation tips

- Avoid `from owlready2 import *`. It can shadow standard-library names such as
  `datetime` and makes datatype failures difficult to diagnose. Prefer explicit
  imports such as `get_ontology`, `Thing`, `DataProperty`, `ObjectProperty`,
  `AnnotationProperty`, and `types`.
- Do not assume an `XSD` symbol is exported by the installed `owlready2`
  version. For datatype ranges, use supported Python classes: `str`, `bool`,
  `int`, `float`, `datetime.date`, and `datetime.datetime`. Keep the original
  SQL type in a source annotation.
- If using `datetime`, import it with an alias such as `import datetime as dt`
  so it cannot be replaced by a wildcard import.
- Define dynamic classes and properties inside the ontology context with
  `types.new_class`. Give each entity a stable `.iri`; do not rely on random
  generated names.
- Define custom annotation properties as `AnnotationProperty` entities in the
  ontology before assigning annotations such as source table names, evidence,
  or provenance.
- Use a native Windows path string with `get_ontology(str(path)).load()` on
  Windows. `Path.as_uri()` can produce a `/C:/...` URI that `owlready2` may try
  to open as an invalid filesystem path.
- Validate the serialized RDF/XML, not only in-memory Python objects. If an
  annotation accessor raises an `owlready2` internal error, inspect the OWL/XML
  or reload it in a fresh ontology instead of treating the file as invalid.
- Count support classes separately from source table classes. A generated
  ontology may also contain classes such as `BusinessRule` and `Metric`.

Example:

```python
from pathlib import Path
from owlready2 import get_ontology

ontology_path = Path("out/ontologies/example_storage_ontology.owl").resolve()
onto = get_ontology(str(ontology_path)).load()

# Confirm the RDF/XML can be loaded and inspect the generated vocabulary.
print("Classes:", len(list(onto.classes())))
print("Object properties:", len(list(onto.object_properties())))
print("Datatype properties:", len(list(onto.data_properties())))

# Run Pellet only when Java and the Pellet dependencies are available.
# from owlready2 import sync_reasoner_pellet
# sync_reasoner_pellet([onto], infer_property_values=True, infer_data_property_values=True)
```

Validation requirements:

1. The caller-requested OWL output exists and is non-empty.
2. `owlready2` version `0.51` is installed or the environment reports a clear
   installation blocker.
3. `get_ontology(...).load()` succeeds without RDF/XML parse errors.
4. Every source table has exactly one corresponding `owl:Class`.
5. Every source column is represented as a datatype property or has a documented
   alternative representation.
6. Every explicit primary key and foreign key is represented.
7. Composite keys and composite foreign keys are not truncated.
8. Source identity annotations are present and point to the input metadata.
9. Business-rule and metric resources have provenance and evidence levels.
10. Optional Pellet reasoning is run only when Java/Pellet is available; a
    missing reasoner must be reported separately from an RDF/XML parse failure.
11. The mapping JSON exists and contains table, field, and relationship entries.
12. RDF/XML and Turtle parse to isomorphic graphs with the same triple count.
13. A second generation run with unchanged inputs produces identical hashes for
  the OWL, Turtle, and mapping JSON files.
14. Proposed Fabric item/member names satisfy their respective patterns and
  deterministic collision checks.
15. Every primary-key component is marked for a Fabric `String` or `BigInt`
  identity projection without changing its RDF datatype or source provenance.

Count source table classes by their source identity annotation. Do not compare
the raw class total directly with the table count because `TableEntity`,
`BusinessRule`, and `Metric` are support classes. Count rule and metric
individuals by their explicit RDF types; do not rely on fragile attribute access
after loading into a reused Owlready2 world.

Serialize Turtle with `rdflib`. Canonicalize RDF/XML element and attribute order
before final validation so semantically identical graphs are also byte-stable.

## Required output

Write only the generated OWL RDF/XML content to the caller-requested output
path. Derive the Turtle and mapping names from the OWL base name. For example,
if the caller requests
`out/ontologies/example_storage_specific/example_storage_specific_ontology.owl`, write:

- `out/ontologies/example_storage_specific/example_storage_specific_ontology.owl`
- `out/ontologies/example_storage_specific/example_storage_specific_ontology.ttl`
- `out/ontologies/example_storage_specific/example_storage_specific_ontology_mapping.json`

The caller-supplied directory and base name take precedence over defaults. Do
not overwrite another ontology variant. Do not return prose, Markdown, JSON, or
code as a substitute for the required files. If an OWL serializer is
unavailable, report the blocker instead of pretending that the OWL file was
generated.

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

## Final validation checklist

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
10. `owlready2==0.51` validation completes, with optional reasoner status
    reported separately.
11. The output files exist at the required paths.
12. Fabric naming projections are valid, unique in scope, and deterministic.
13. Primary-key order is preserved and no Fabric-incompatible identity type is
  passed downstream without an explicit `String` projection rule.

## Input files

Read the exact paths supplied by the caller. If the caller supplies no paths,
use these defaults:

### Table and relationship metadata

```text
inputs/lakehouse_tables/example_storage_tables.txt
```

### Business rules and metrics

```text
out/business_rules/business_rules.md
```
