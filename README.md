# Fabric Ontology Builder Accelerator

The Fabric Ontology Builder Accelerator converts Microsoft Fabric Lakehouse
metadata into a deterministic, human-reviewable RDF/OWL ontology, transforms
that ontology into a native Fabric Ontology item definition, and publishes it
through the Fabric REST API.

The implemented workflow is:

```text
Fabric Lakehouse metadata
	-> business rules
	-> RDF/XML OWL + Turtle + source mapping
	-> Fabric Ontology definition parts
	-> published Fabric Ontology item
```

RDF/OWL is the canonical semantic artifact. The Fabric JSON definition is a
reproducible generated output and should not be edited by hand. See
[plan.md](plan.md) for the phased design and [architecture.png](architecture.png)
for the component diagram.

## Implementation status

| Stage | Interface | Status |
|---|---|---|
| Extract Lakehouse metadata | `uv run extract-metadata` | Implemented |
| Extract business rules | GitHub Copilot `extract-business-rules` skill | Implemented |
| Generate and validate RDF/OWL | GitHub Copilot `create-ontology` skill or Python module | Implemented |
| Transform OWL to Fabric definition | `uv run transform-ontology` | Implemented |
| Validate and publish to Fabric | `uv run publish-ontology` | Implemented |

There is currently no single `run` command or standalone `validate` command.
Run the stages below in order. Generation performs RDF validation, and
`publish-ontology --dry-run` validates the generated Fabric request envelope.

## Prerequisites

- Python 3.12 or later.
- [`uv`](https://docs.astral.sh/uv/) for dependency management and execution.
- VS Code with GitHub Copilot Chat in Agent mode to use the repository skills.
- Azure CLI for interactive local authentication to Fabric.
- A Fabric workspace on supported capacity, with permission to run the source
	notebook, read the Lakehouse and OneLake output, and create or update
	Ontology items.
- The extractor notebook imported into Fabric from
	`notebooks/nb_extract_tables_metadata.ipynb`. Mark its input cell as a
	parameter cell so the job API can inject the requested tables and output
	path.

Install the Python environment from the repository root:

```powershell
uv sync
```

Create the local configuration file from the safe example:

```powershell
Copy-Item config/accelerator.example.yaml config/accelerator.yaml
```

Edit `config/accelerator.yaml` and set `fabric.workspace`, `fabric.notebook`,
and `fabric.lakehouse` to their Fabric item GUIDs. Replace the sample table in
`extract.tables` with one or more fully qualified
`catalog.schema.table` names. The local configuration is ignored by Git and
must not contain tokens or client secrets.

Authenticate before commands that call Fabric:

```powershell
az login
```

`DefaultAzureCredential` is used by the extractor, token helper, and publisher.
Managed identity or another supported Azure Identity credential can be used in
automation instead of Azure CLI authentication.

## Run the complete workflow

The process combines deterministic CLI stages with two repository-local
GitHub Copilot skills. Run commands from the repository root.

### 1. Extract metadata

```powershell
uv run extract-metadata
```

The default output is `inputs/lakehouse_tables/metadata.json`.

### 2. Extract business rules with Copilot

Open GitHub Copilot Chat in **Agent** mode. Skills are selected automatically
from `.github/skills/` based on the request; naming the skill explicitly makes
the intended workflow unambiguous. Use a prompt such as:

```text
Use the extract-business-rules skill with
inputs/lakehouse_tables/metadata.json. Generate the complete English report at
out/business_rules/business_rules.md and validate relationship coverage against
the source metadata.
```

Review the generated report, especially all Proposed interpretations, before
using it as ontology input.

### 3. Generate and validate the ontology with Copilot

In the same Agent chat, provide the exact metadata, rules, and output paths:

```text
Use the create-ontology skill with
inputs/lakehouse_tables/metadata.json and
out/business_rules/business_rules.md. Generate and validate
out/ontologies/lakehouse_ontology.owl, its Turtle serialization, and its JSON
source mapping. Report the table, property, relationship, rule, and metric
counts and the deterministic validation results.
```

This produces:

```text
out/ontologies/lakehouse_ontology.owl
out/ontologies/lakehouse_ontology.ttl
out/ontologies/lakehouse_ontology_mapping.json
```

The direct Python command documented under **Ontology generation** is available
when the business-rules report already exists and no Copilot enrichment pass is
needed.

### 4. Transform RDF/OWL to a Fabric definition

```powershell
uv run transform-ontology `
	--ontology out/ontologies/lakehouse_ontology.owl `
	--mapping out/ontologies/lakehouse_ontology_mapping.json `
	--output-dir out/ontology-definition `
	--display-name "Lakehouse Ontology"
```

This creates decoded definition parts for review and
`out/ontology-definition/fabric-definition.json` for the REST API.

### 5. Validate the publication payload

```powershell
uv run publish-ontology --definition out/ontology-definition --dry-run
```

Dry-run validation does not authenticate or call Fabric.

### 6. Publish or update the Fabric Ontology

```powershell
uv run publish-ontology --definition out/ontology-definition
```

The publisher creates the item when the normalized name is absent and updates
the single exact-name match when it already exists. For an unambiguous update,
pass `--item-id <ontology-item-guid>`.

## Local inputs and generated outputs

The `inputs/` and `out/` directories are local pipeline workspaces and are
intentionally excluded from Git by `.gitignore`. They can contain customer
schema details, business terminology, source identifiers, and generated
artifacts tied to a specific Fabric workspace. Commit reusable examples under
`examples/` or sanitized test data under `tests/fixtures/` instead.

```text
inputs/
└── lakehouse_tables/          # Metadata supplied to ontology generation

out/
├── business_rules/            # Extracted or authored semantic rules
├── ontologies/                # Canonical RDF/OWL and source mappings
├── ontology-definition/       # Decoded Fabric definition parts for a run
└── ontology-definition-*/     # Additional named transformation variants
```

### `inputs/`

`inputs/` is the local landing zone for source material consumed by the
pipeline. It is not generated ontology output.

- `inputs/lakehouse_tables/` stores normalized `metadata.json` downloaded by
	the extractor, or SQL/JSON metadata files supplied directly to the generator.
	These files describe catalogs, schemas, tables, columns, types, comments,
	primary keys, and foreign-key hints.
- The extractor creates the configured local output parent directories when
	needed. Files may also be placed here manually for an offline generation run.

### `out/`

`out/` contains reviewable artifacts produced by successive pipeline stages.
Each stage writes files instead of passing only in-memory data so a result can
be inspected, versioned externally, or rerun independently.

- `out/business_rules/` contains Markdown reports derived from source metadata.
	They capture table and field semantics, relationships, metrics, restrictions,
	data-quality rules, and test scenarios used during ontology generation.
- `out/ontologies/` contains the canonical `.ttl` and `.owl` semantic models
	plus adjacent `*_mapping.json` provenance. The mapping connects ontology
	classes and properties back to physical Lakehouse tables and columns.
- `out/ontology-definition/` contains decoded Fabric Ontology definition parts
	and the `fabric-definition.json` `InlineBase64` request envelope produced by
	the transformer.
- Directories such as `out/ontology-definition-specific/` are separate output
	variants selected with `--output-dir`. They have the same structure and let
	multiple ontology scopes coexist without overwriting one another.

Because both directory trees are ignored, a fresh clone starts without them.
Run the relevant pipeline stage or create the required local directories before
supplying offline inputs. Do not remove the ignore rules unless every file has
been reviewed and sanitized for publication.

## Metadata extraction

The extractor runs `notebooks/nb_extract_tables_metadata.ipynb` as a Fabric
on-demand notebook job, polls the job through the Fabric REST API, and downloads
the schema-versioned JSON output from OneLake through its REST data plane.

Copy `config/accelerator.example.yaml` to `config/accelerator.yaml`, then set
the Fabric workspace, notebook, lakehouse, and source tables. The CLI reads the
`extract` section by default; command-line arguments override values from the
YAML file. Authentication uses
`DefaultAzureCredential`, so the local environment must have an Azure CLI,
managed identity, or another supported Azure Identity credential available.

Run the extraction with:

```powershell
uv sync
uv run extract-metadata
```

To use another configuration file:

```powershell
uv run extract-metadata --config config/accelerator.yaml
```

To override one configured value:

```powershell
uv run extract-metadata --table catalog.schema.table_name
```

The default local output is `inputs/lakehouse_tables/metadata.json`.

In Fabric, mark the notebook's parameter cell as a parameter cell before
running it as a job so `tables_to_extract` and `metadata_file_location` are
injected by the job request.

## Fabric REST API token

For local development, sign in with the Azure CLI and print a short-lived
Microsoft Entra access token scoped to the Fabric REST API:

```powershell
az login
uv run fabric-token
```

The default output is the raw token for tools whose authentication type is
already set to **Bearer Token**. Other copy/paste formats are available:

```powershell
uv run fabric-token --format bearer
uv run fabric-token --format header
```

The command uses `DefaultAzureCredential` and requests
`https://api.fabric.microsoft.com/.default`; it does not store credentials or
tokens. Treat the printed token as a secret and do not commit it, save it in
logs, or share it.

## Ontology generation

The ontology generator reads the extracted Fabric table metadata and the
business-rules report, then produces deterministic RDF/XML OWL, an equivalent
Turtle serialization, and a provenance mapping. Input and output paths are
explicit CLI arguments, so multiple ontology variants can coexist without
overwriting one another. To run the deterministic generator directly after the
business-rules skill has produced its report:

```powershell
uv run python -m generate.create_ontology `
	--metadata inputs/lakehouse_tables/metadata.json `
	--rules out/business_rules/business_rules.md `
	--output out/ontologies/lakehouse_ontology.owl
```

The adjacent Turtle and mapping paths are derived automatically from the OWL
path. Use `--mapping <path>` only when the mapping needs a different location.

The generator maps tables to `owl:Class`, columns to datatype properties, and
declared foreign keys to object properties. It preserves source identities,
ordered primary and composite keys, nullability, original SQL types,
business-rule evidence, metrics, and provenance annotations. English table
labels come from the business-rules report. Rules are parsed from the
data-quality table, and named metric rows receive stable IDs such as `MET-001`
when the report does not provide IDs. Exact source table, field, target, and
constraint names remain in ontology annotations and the mapping JSON.

Validate the generated OWL with `owlready2`:

```powershell
uv run python -c "from pathlib import Path; from owlready2 import get_ontology; p=Path('out/ontologies/lakehouse_ontology.owl').resolve(); o=get_ontology(str(p)).load(); print(len(list(o.classes())), len(list(o.object_properties())), len(list(o.data_properties())))"
```

`BusinessRule`, `Metric`, and `TableEntity` are support classes and are not
counted as source tables.

Validation checks `owlready2==0.51` loading, exact source table/column/PK/FK
coverage, mapping counts, RDF/XML-to-Turtle graph isomorphism with `rdflib`, and
byte-identical output hashes across repeated runs. Turtle serialization uses
`rdflib`; RDF/XML is canonicalized to keep unchanged runs deterministic.

## Fabric Ontology transformation

Transform the specific OWL ontology and its mapping into Fabric Ontology
definition parts:

```powershell
uv run transform-ontology `
	--ontology out/ontologies/example_storage_specific/example_storage_specific_ontology.owl `
	--mapping out/ontologies/example_storage_specific/example_storage_specific_ontology_mapping.json `
	--output-dir out/ontology-definition-specific `
	--display-name "example storage Specific Ontology"
```

Workspace and lakehouse IDs default to the `fabric` section of
`config/accelerator.yaml`; `--workspace-id` and `--lakehouse-id` override them.
The output directory contains decoded `.platform`, entity, property-binding,
relationship, and contextualization parts for review. Its
`fabric-definition.json` contains the same files as sorted `InlineBase64`
payloads and is ready for the Fabric REST create or update-definition request.

OWL is authoritative for semantic types and relationship endpoints. The
adjacent mapping JSON is authoritative for Lakehouse schemas, tables, columns,
ordered primary keys, and foreign-key bindings. Transformation fails when the
two inputs disagree or a source reference cannot be resolved.

Fabric entity and property names are projected from exact source table and
column identifiers, not from translated business labels. Valid source names
are preserved exactly; only Fabric-incompatible characters, invalid leading
characters, excessive length, and collisions are normalized deterministically.
English business labels remain available as semantic descriptions.

The specific fixture produces 31 entity types, 496 properties, 64 relationship
types, 31 DataBindings, 64 Contextualizations, and 192 API definition parts.
Fabric only accepts `String` and `BigInt` entity-key properties. The transformer
preserves every source primary-key component and order, but projects other key
types such as `xsd:date` to Fabric `String` while retaining the original RDF and
source datatypes in semantic-enrichment attributes. Generated JSON also
preserves discriminator order, including `sourceType` as the first source-table
property required by the current Fabric importer.

## Fabric Ontology publication

Validate the generated envelope without authenticating or calling Fabric:

```powershell
uv run publish-ontology --definition out/ontology-definition-specific --dry-run
```

Create the ontology when its exact normalized name is absent, or update the
single exact-name match when it already exists:

```powershell
az login
uv run publish-ontology --definition out/ontology-definition-specific
```

To update a known item without name resolution:

```powershell
uv run publish-ontology `
	--definition out/ontology-definition-specific `
	--item-id <ontology-item-guid>
```

Authentication uses `DefaultAzureCredential` with the Fabric REST scope. The
publisher validates all `InlineBase64` parts, follows paginated name lookup,
polls long-running operations, retrieves asynchronous create results, and
retries transient HTTP `408`, `429`, `502`, `503`, and `504` responses.

Fabric Ontology item names must start with a letter, contain only letters,
numbers, and underscores, and be shorter than 90 characters. The publisher
normalizes the requested name deterministically and updates the in-memory
`.platform` metadata to match. For example, `storage Specific Ontology` is
published as `storage_Specific_Ontology`. Readable RDF labels and exact source
identifiers are not modified.

Current relationship contextualization supports direct, single-column foreign
keys. Grouped composite foreign keys, time-series bindings, inheritance, and
junction/n-ary relationships remain planned extensions.

Known limitations:

- The parser currently targets three-part backtick-qualified SQL identifiers
	and common JSON layouts.
- Informational or `NOT ENFORCED` constraints are modeled as declared metadata;
	runtime data integrity is not proven.
- Optional Pellet reasoning requires a compatible Java runtime; RDF/XML loading
	with `owlready2` and RDF graph equivalence are the required validation gates.

## Command reference and tests

Show every supported CLI option without calling Fabric:

```powershell
uv run extract-metadata --help
uv run fabric-token --help
uv run python -m generate.create_ontology --help
uv run transform-ontology --help
uv run publish-ontology --help
```

Run the automated test suite with:

```powershell
uv run pytest
```

The token helper is optional for the pipeline because live CLI stages acquire
credentials directly. Use it when manually calling the Fabric REST API from a
separate client.

## Disclaimer

This project is provided **AS IS**, without warranty of any kind, express or
implied, including warranties of merchantability, fitness for a particular
purpose, and noninfringement. Use it at your own risk. The authors and
copyright holders are not liable for claims, damages, or other liability
arising from the software or its use. This project is not an official Microsoft
product and does not provide support or service-level commitments.

## License

This project is open source under the [MIT License](LICENSE).
