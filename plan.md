# Fabric Ontology Builder Accelerator — Development Plan

> Automate creation of an ontology from **Microsoft Fabric** lakehouse metadata (mirrored
> Azure Databricks Unity Catalog surfaced via OneLake shortcuts), authoring an
> **RDF/OWL** ontology as the canonical artifact, then transforming it into a
> **Fabric Ontology item** definition and publishing it through the Fabric REST API.
> Built in **VS Code + GitHub Copilot** using the **Fabric MCP Server** and the
> **Fabric Data Engineering** extension.

---

## 1. Goal & scope

**Objective.** Given one or more Fabric lakehouses whose tables are Delta shortcuts to a
mirrored Databricks Unity Catalog, generate a semantically meaningful ontology and publish
it as a native **Fabric Ontology item** — with minimal manual authoring.

**Primary flow.**

```
Unity Catalog / Lakehouse metadata
      │  (extract table + column descriptions, types, keys)
      ▼
metadata.json  (normalized catalog snapshot)
      │  (LLM guided by ontology-instructions.md  +  deterministic rules)
      ▼
ontology.ttl / ontology.owl   ← CANONICAL, human-reviewable RDF/OWL artifact
      │  (transformer: OWL → Fabric Ontology definition parts)
      ▼
Fabric Ontology item definition  (definition.json, .platform, EntityTypes/*, RelationshipTypes/*, DataBindings/*)
      │  (Fabric REST: POST /v1/workspaces/{id}/ontologies  +  updateDefinition)
      ▼
Published Fabric Ontology item  → Explorer / Power BI / Real-Time Dashboards
```

**In scope**
- Metadata extraction from lakehouse / mirrored Unity Catalog (tables, columns, types, comments, keys).
- Rule- + LLM-assisted generation of RDF/OWL (Turtle is canonical; RDF/XML export supported).
- Validation of the RDF/OWL (syntax, reasoner consistency, SHACL profile).
- A deterministic **RDF/OWL → Fabric Ontology definition** transformer.
- Publish/update via Fabric REST API with idempotent, CI/CD-friendly behavior.
- VS Code / Copilot developer experience wired to Fabric MCP Server + Fabric DE extension.

**Out of scope (v1)**
- Instance-data / knowledge-graph materialization (only the schema-level ontology + data bindings).
- Digital Twin Builder item or DTB flow definitions (explicitly **not** used — target is the standalone Ontology item).
- Two-way sync / drift reconciliation beyond re-publish (tracked as a v2 stretch goal).

---

## 2. Key findings that shape the design (from research)

| Area | Finding | Design impact |
|---|---|---|
| **Fabric Ontology item** | Standalone item type exists (Preview). REST service `/v1/workspaces/{id}/ontologies`; discriminator `"type":"Ontology"`. | Publish target is the Ontology item, **not** Digital Twin Builder. |
| **Definition format** | Proprietary **JSON only** via base64 "definition parts": `definition.json`, `.platform`, `EntityTypes/{id}/definition.json`, `EntityTypes/{id}/DataBindings/{guid}.json`, `RelationshipTypes/{id}/definition.json`, `RelationshipTypes/{id}/Contextualizations/{guid}.json`. **No RDF/OWL/CSV import.** | We keep RDF/OWL as the canonical artifact and build our own transformer to the JSON parts. |
| **EntityType schema** | `id` (unique BigInt), `namespace=usertypes`, `name` (`^[A-Za-z][A-Za-z0-9_-]{0,127}$`), `entityIdParts`, `displayNamePropertyId`, `properties[]` with `valueType ∈ {String, Boolean, DateTime, Object, BigInt, Double}`, plus `timeseriesProperties[]`, `untypedProperties[]`. Supports inheritance via `baseEntityTypeId`. | OWL Class → EntityType; datatype property → property; map XSD → the 6 value types; OWL subclass → `baseEntityTypeId`. |
| **RelationshipType** | `id`, `namespace=usertypes`, `name`, `source.entityTypeId`, `target.entityTypeId`. | OWL ObjectProperty (with domain/range) → RelationshipType. |
| **Data binding** | `DataBindings/{guid}.json` maps a Lakehouse Delta table (`workspaceId`,`itemId`,`sourceTableName`,`sourceSchema`) columns → entity property IDs (`propertyBindings[]`); `NonTimeSeries` / `TimeSeries`. Relationship instances via `Contextualizations` join tables. | Each class keeps a back-reference to its source table so we can emit bindings automatically. |
| **Auth** | Ontology REST operations **support service principals & managed identities** (unlike DTB). Create needs Contributor + scope `Item.ReadWrite.All`; workspace on supported capacity. LRO (202 + poll). | Unattended CI/CD publish is possible with an SPN. |
| **Metadata source** | Mirroring replicates **structure only** (no data copy); tables surface as Delta shortcuts under lakehouse `Tables/`. Comment/description propagation to Fabric is **not guaranteed** — read descriptions from the Databricks/Unity Catalog side (`information_schema.columns.COMMENT` / `tables.COMMENT`) or `DESCRIBE TABLE EXTENDED ... AS JSON`. | Extractor supports two sources: Fabric Spark `DESCRIBE`, and direct Unity Catalog `information_schema`. |
| **Tooling** | Official **Fabric MCP Server** (`microsoft/mcp` → `Fabric.Mcp.Server`) exposes `onelake_list-tables`, `onelake_get-table`, `core_search-catalog`, `core_create-item`, `docs_item-api-spec`, etc. **Fabric DE extension** (`SynapseVSCode.synapse`) authors/runs notebooks & browses lakehouses. | Use MCP for discovery/codegen + item ops; use DE extension to run the extractor notebook on Fabric Spark. |
| **RDF generation prior art** | W3C **Direct Mapping** (table→class, column→property, FK→object-property), **R2RML/RML** for custom vocab; **rdflib**/**owlready2** for authoring; **pySHACL**/HermiT for validation; LLMs4OL task decomposition (term typing / taxonomy / relations). | Deterministic direct-mapping baseline + LLM enrichment for labels/types/relations; validate in a loop. |

> ⚠️ **Preview caveats to verify empirically during Phase 0:** no conceptual landing page yet
> (API-reference-only); GA date unknown; Fabric CLI support for the Ontology item unverified;
> confirm Fabric Spark runtime supports `DESCRIBE ... AS JSON` (fallback to classic `DESCRIBE
> TABLE EXTENDED`). Treat the Ontology definition schema as subject to change.

---

## 3. Architecture components

1. **Metadata Extractor** (`src/extract/`) — a Fabric PySpark notebook + a local Python module.
   Enumerates lakehouse tables and emits a normalized `metadata.json`
   (catalog, schema, table, table-description, columns[name, type, nullable, comment], candidate keys, FK hints).
   - Source A: Fabric Spark on the mirrored lakehouse — `SHOW TABLES` + `DESCRIBE TABLE EXTENDED ... AS JSON`.
   - Source B: direct Unity Catalog `information_schema.tables/columns` (most reliable for comments).
   - Discovery assist: Fabric MCP `onelake_list-tables` / `onelake_get-table`.
   - Orchestration: local `src/extract` submits the Fabric notebook as an on-demand item job via REST,
     polls the job instance, then downloads the JSON output from OneLake via its REST data plane into
     `inputs/lakehouse_tables/`.

2. **Ontology Generator** (`src/generate/`) — turns `metadata.json` into RDF/OWL.
   - **Deterministic core**: W3C Direct-Mapping-style rules (table→`owl:Class`, column→datatype property,
     FK/junction→object property, comments→`rdfs:label`/`rdfs:comment`/`dcterms:description`) via `rdflib`/`owlready2`.
   - **LLM enrichment** (GitHub Copilot, guided by `ontology-instructions.md`): better class/property names,
     class hierarchy (taxonomy), object-property naming, vocabulary reuse (schema.org/DC/SKOS), junction-table
     detection. LLM emits **structured JSON**, not raw Turtle; the deterministic serializer renders valid RDF.
    - Output: `out/ontology.ttl` (canonical) + `out/ontology.owl` (RDF/XML) + `out/mapping.json`
       (class/property/relationship ↔ source table/column provenance, needed for data bindings).
    - Current executable: `uv run python -m generate.create_ontology`, which accepts
       SQL/JSON metadata, business rules, and an explicit OWL output path. It writes
       an adjacent Turtle serialization and validates the generated RDF/XML with `owlready2`.
    - Current specific example UDV example outputs
       `out/ontologies/example_udv_specific/example_udv_specific_ontology.owl`,
       `out/ontologies/example_udv_specific/example_udv_specific_ontology.ttl`, and
       `out/ontologies/example_udv_specific/example_udv_specific_ontology_mapping.json` from
       `inputs/lakehouse_tables/example_udv_specific_tables.txt` and
       `out/business_rules/business_rules_specific.md`.
       Ontology labels are business-friendly; exact source identities remain in provenance and mapping.

3. **Validator** (`src/validate/`) — `rdflib` round-trip (syntax), OWL reasoner (HermiT/Pellet via `owlready2`)
   for consistency, `pySHACL` against an accelerator SHACL profile (naming, required labels, domain/range present,
   value types within the Fabric-supported set). Gate publish on pass; feed errors back to the LLM for a repair pass.

4. **Transformer** (`src/transform/`) — **RDF/OWL → Fabric Ontology definition parts**.
    - Treat OWL as the semantic authority for classes, property kinds, datatypes, domains, and ranges; treat
       mapping JSON as the physical binding authority for source schemas, tables, columns, ordered PKs, and FK endpoints.
    - Assign stable positive signed 64-bit IDs (SHA-256 of IRI, masked to `2^63 - 1`, emitted as decimal strings)
       for entity types, properties, and relationship types; fail on collisions.
   - `owl:Class` → `EntityTypes/{id}/definition.json` (name sanitized to Fabric regex; `entityIdParts` from PK;
       `displayNamePropertyId` from a name/description field, then PK, then first property).
   - Datatype property → entity `properties[]`; XSD→value-type map
     (`xsd:string→String`, `xsd:boolean→Boolean`, `xsd:dateTime→DateTime`, `xsd:integer/long→BigInt`,
       `xsd:double/decimal/float→Double`, unknown→`untypedProperties`/`Any`).
   - `owl:ObjectProperty` → `RelationshipTypes/{id}/definition.json` (source/target entity type ids from domain/range).
    - Emit a deterministic UUIDv5 `DataBindings/{guid}.json` per class from mapping JSON (`NonTimeSeries`
       Lakehouse table: workspaceId, itemId,
     sourceTableName, sourceSchema; `propertyBindings[]` column→propertyId).
    - Emit a deterministic UUIDv5 `Contextualizations/{guid}.json` per direct FK. The source table supplies both
       its PK bindings and the FK column that references the target property.
    - Write decoded `.platform`, root, entity, binding, relationship, and contextualization parts for review;
       base64-encode the same sorted bytes into `fabric-definition.json` using `InlineBase64`.
    - Validate GUIDs, OWL/mapping kinds and endpoints, PK/FK resolution, duplicate mappings, name uniqueness,
       ID collisions, and supported XSD mappings before output.
    - Composite-FK grouping, time-series bindings, inheritance, and junction/n-ary contextualizations are deferred
       until their source metadata and Fabric Preview representation are explicitly modeled.

5. **Publisher** (`src/publish/`) — Fabric REST client.
   - `POST /v1/workspaces/{id}/ontologies` (create) or resolve existing by name → `updateDefinition`.
   - Handle LRO (202 + `Retry-After` poll), idempotency (create-or-update), auth via SPN/MSAL device code.
   - Optional `core_create-item` via MCP as an alternative path.

6. **Orchestrator / CLI** (`src/cli/`) — `ontobuilder <extract|generate|validate|transform|publish|run>`.
   `run` chains the full pipeline; each stage is independently runnable and file-based for reviewability.

7. **Instruction asset** (`ontology-instructions.md`) — the human-authored markdown that steers the LLM:
   namespace/URI conventions, naming rules, vocabulary-reuse policy, table→class / column→property / FK→relationship
   rules, junction-table (n-ary) handling, few-shot examples, and the required structured-JSON output schema.

8. **Dev environment config** — `.vscode/mcp.json` (Fabric MCP Server), recommended extensions
   (`SynapseVSCode.synapse`, GitHub Copilot Chat), `.github/copilot-instructions.md` pointing Copilot at the accelerator conventions.

---

## 4. Repository layout (target)

```
se-fabric-ontology-builder-accelerator/
├─ plan.md
├─ architecture.excalidraw            # editable source
├─ architecture.png                   # exported render
├─ README.md
├─ ontology-instructions.md           # LLM steering doc (the "instructions" markdown)
├─ pyproject.toml / requirements.txt
├─ .vscode/
│  ├─ mcp.json                        # Fabric MCP Server config
│  └─ extensions.json                 # recommend Synapse + Copilot
├─ .github/
│  └─ copilot-instructions.md
├─ config/
│  ├─ accelerator.yaml                # workspace ids, lakehouse ids, namespace, capacity
│  └─ shapes.shacl.ttl                # validation profile
├─ notebooks/
│  └─ 01_extract_metadata.ipynb       # Fabric DE extension → Fabric Spark
├─ src/
│  ├─ extract/   generate/   validate/   transform/   publish/   cli/   common/
├─ tests/
│  ├─ unit/                           # rules, xsd map, id hashing, base64 parts
│  ├─ fixtures/                       # sample metadata.json, golden ttl, golden parts
│  └─ integration/                    # live workspace smoke test (gated)
└─ examples/
   └─ retail-lakehouse/               # end-to-end worked example
```

---

## 5. Phased plan & milestones

### Phase 0 — Foundations & spikes (verify Preview reality)
- Confirm access: Fabric workspace on supported capacity, a mirrored Databricks lakehouse, SPN with `Item.ReadWrite.All`.
- Wire dev env: install Fabric DE extension + Fabric MCP Server in VS Code; validate Copilot Agent mode sees MCP tools.
- **Spike A**: create a trivial Ontology item via REST (empty definition `{}`, base64 `.platform`), then `getDefinition` round-trip. Capture exact API version, LRO behavior, error shapes.
- **Spike B**: run `DESCRIBE TABLE EXTENDED ... AS JSON` on the mirrored lakehouse; confirm comments are present, else fall back to Unity Catalog `information_schema`.
- **Exit**: a known-good minimal Ontology definition round-trips; a real table's metadata is extractable. Document any schema deltas vs. research.

### Phase 1 — Metadata extraction
- Build `notebooks/01_extract_metadata.ipynb` + `src/extract` producing `metadata.json` (schema-versioned).
- Two sources (Spark `DESCRIBE`, UC `information_schema`) behind one interface; key/FK heuristics.
- Unit tests on parsing; fixture `metadata.json` for downstream stages.
- **Exit**: deterministic `metadata.json` for the example lakehouse.

### Phase 2 — Ontology generation (RDF/OWL)
- Implement deterministic direct-mapping core (`rdflib`/`owlready2`), namespace/URI design, XSD typing, label/comment mapping.
- Author `ontology-instructions.md`; implement LLM enrichment producing structured JSON → serializer.
- Produce `ontology.ttl` + `ontology.owl` + `mapping.json` (provenance).
- **Exit**: canonical RDF/OWL for the example, human-reviewable, with provenance retained;
   the current example UDV fixture produces 100 table classes, 2,194 datatype properties,
   and 64 object properties and loads successfully with `owlready2==0.51`.

### Phase 3 — Validation
- Syntax round-trip; reasoner consistency (HermiT/Pellet); `pySHACL` against `config/shapes.shacl.ttl`.
- Repair loop: on failure, structured errors → LLM correction pass (bounded retries) → re-validate.
- **Exit**: example ontology passes all three checks; CI job runs validation on fixtures.

### Phase 4 — Transformer (OWL → Fabric Ontology definition)
- **Implemented**: deterministic IDs and names; class/property/relationship mapping;
   `entityIdParts`/`displayNamePropertyId` selection; EntityTypes, RelationshipTypes, `NonTimeSeries`
   Lakehouse DataBindings, direct-FK Contextualizations, decoded parts, and sorted InlineBase64 assembly.
- **Implemented Fabric compatibility**: preserve JSON discriminator insertion order; project non-`String`/`BigInt`
   primary-key properties to Fabric `String` without changing their canonical RDF/source datatype provenance;
   validate every emitted entity-key property against the supported key types.
- **Implemented validation**: cross-check OWL and mapping identities/endpoints, resolve every PK/FK/property reference,
   reject duplicate mappings and ID/name collisions, and verify every envelope payload round-trips to its decoded file.
- **Tests to complete**: golden files plus focused cases for ID/name collisions, XSD fallback, composite PK order,
   display-property selection, invalid endpoints, and API schema drift.
- **Deferred**: grouped composite FKs, time-series bindings, inheritance, and junction/n-ary relationships.
- **Current evidence**: the specific example UDV fixture produces 31 entity types, 496 properties, 64 relationship
   types, 31 DataBindings, 64 Contextualizations, and 192 definition parts deterministically.
- **Exit**: `out/ontology-definition/example_udv_specific/` is reproducible; decoded parts match the documented Preview
   schema; the API envelope passes a Fabric `create`/`updateDefinition` round-trip in a development workspace.

### Phase 5 — Publisher & end-to-end
- **Implemented**: Fabric REST client using `DefaultAzureCredential`; local envelope validation; deterministic
   Fabric item-name normalization; paginated exact-name resolution; create-or-update; explicit item-ID update;
   LRO polling and create-result retrieval; transient retries; configurable timeout/polling; and offline dry-run.
- **Live evidence**: created and then explicitly updated `example_UDV_Specific_Ontology` in the configured development
   workspace from the 192-part `out/ontology-definition-specific` envelope. The live importer confirmed that
   source-table discriminators must be serialized first and entity-key value types are limited to `String`/`BigInt`.
- `ontobuilder run` chains all stages from `config/accelerator.yaml`.
- **Remaining smoke check**: open the published item in Fabric and confirm entity/relationship types and bindings render.
- **Exit**: one command turns a lakehouse into a published, browsable Fabric Ontology item.

### Phase 6 — DX, CI/CD, docs, hardening
- GitHub Actions: lint, unit/golden tests, validation; gated integration job (SPN secrets) that publishes to a scratch workspace.
- `README.md`, quickstart, the worked `examples/retail-lakehouse/`, troubleshooting (Preview quirks).
- Telemetry-free logging, clear errors, config validation.
- **Exit**: a new user completes the quickstart end-to-end from the README.

### Phase 7 — Stretch (v2)
- Instance/KG materialization (RML/Morph-KGC) for relationship `Contextualizations` at scale.
- Drift detection & incremental re-publish; multi-lakehouse ontologies; vocabulary-reuse packs; Power BI/RTI wiring; optional Fabric CLI path once supported.

---

## 6. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Ontology item is **Preview**; schema/API may change | High | Pin API version; Phase-0 spikes; isolate the definition schema in `src/transform` behind a versioned adapter; golden tests catch drift. |
| Table/column **comments don't propagate** through mirroring | Med | Read descriptions from Unity Catalog `information_schema` directly; make comments optional with graceful degradation. |
| **LLM output** inconsistent / invalid RDF | Med | LLM emits structured JSON (not raw Turtle); deterministic serializer; validation-in-the-loop repair. |
| **64-bit id** collisions / instability across runs | Low | Deterministic IRI→id hash with collision check; persist id map in `mapping.json`. |
| **XSD → 6 value types** lossy | Med | Explicit mapping table; unmapped → `untypedProperties`/`Any`; warn in report. |
| **Junction / n-ary** relationships mismodeled | Med | Detect FK-only tables; apply W3C n-ary pattern (reify as class) vs. naive object property. |
| Fabric **CLI** for Ontology unverified | Low | Use REST + MCP `core_create-item`; add CLI path only after confirmation. |
| **Auth/capacity** blockers in CI | Med | SPN (supported for Ontology ops); document capacity requirement; dry-run mode offline. |

---

## 7. Tech stack

- **Python 3.11+**: `rdflib`, `owlready2`, `pySHACL`, `pandas`, `requests`/`httpx`, `msal`, `pydantic`, `pyyaml`, `pytest`.
- **Fabric Spark** (PySpark) for extraction via the **Fabric Data Engineering** VS Code extension.
- **Fabric MCP Server** (`@microsoft/fabric-mcp`) in VS Code Copilot Agent mode for discovery, docs, and item ops.
- **Fabric REST API** (`api.fabric.microsoft.com/v1`) for publishing the Ontology item.
- **GitHub Actions** for CI/CD.

---

## 8. Definition of done (v1)

- `ontobuilder run` extracts metadata from a mirrored-Databricks lakehouse, generates a validated
  `ontology.ttl`/`.owl`, transforms it to Fabric Ontology definition parts, and publishes a browsable
  **Fabric Ontology item** — reproducibly, from config, with the RDF/OWL artifact preserved for review.
- All stages independently runnable and file-based; unit + golden tests green; one worked example documented.
