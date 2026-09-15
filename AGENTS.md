# AGENTS.md

## What this project is

Fabric Ontology Builder Accelerator: a pipeline that turns Microsoft Fabric
lakehouse metadata (mirrored Databricks Unity Catalog) into an RDF/OWL
ontology, validates it, transforms it into a Fabric Ontology item definition
(JSON parts), and publishes it via the Fabric REST API. RDF/OWL is the
canonical, human-reviewable artifact; the Fabric JSON definition is a
generated output, never hand-edited.

Full architecture, phased roadmap, and design rationale live in `plan.md`.
Read it before making non-trivial changes; keep it updated when scope or
architecture decisions change.

## Tech stack & tooling

- Python >= 3.12, managed with **uv** (not pip or Poetry). Use `uv add <pkg>` to
  add dependencies, `uv sync` to install, `uv run <cmd>` to execute anything.
- Build backend: `uv_build`. Installable package lives at
  `src/se_fabric_ontology_builder_accelerator/`.
- Runtime libraries are declared in `pyproject.toml`; currently they include
  `azure-identity`, `httpx`, `pyyaml`, `owlready2`, and `rdflib`.
- Tests use `pytest` from the development dependency group.
- Use `DefaultAzureCredential` for Fabric authentication. Never commit tokens,
  client secrets, or populated local configuration values.

## How to build, run, test

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- Extract metadata: `uv run extract-metadata --help`
- Generate ontology: `uv run python -m generate.create_ontology --help`
- Transform OWL: `uv run transform-ontology --help`
- Validate a publish payload: `uv run publish-ontology --definition <path> --dry-run`
- Publish to Fabric: `uv run publish-ontology --definition <path>`
- Add a runtime dependency: `uv add <package>`
- Add a dev-only dependency: `uv add --dev <package>`

There is no separate lint/format command configured yet; if you add one,
document it here.

## Pipeline stages (one command per stage)

`extract -> generate and validate -> transform -> publish`. There is currently
no single `run` command or standalone `validate` command. Generation validates
RDF/OWL, and `publish-ontology --dry-run` validates the Fabric definition
envelope. Each stage reads or writes reviewable files under `inputs/` and
`out/`. Do not bypass these file hand-offs.

## Working conventions

- Treat RDF/OWL (`out/ontology.ttl` / `.owl`) as the source of truth; the
  Fabric Ontology definition JSON is derived and must stay reproducible from
  it using deterministic IDs and names. See `plan.md` for design details and
  risks.
- Treat mapping JSON as the authority for exact source schemas, tables,
  columns, ordered primary keys, constraints, and physical bindings.
- Preserve source-language table, column, and constraint identifiers in Fabric
  member names. Do not replace them with translated business labels. Normalize
  only characters, leading positions, lengths, or collisions that violate
  Fabric naming rules.
- Keep readable English labels and descriptions in OWL labels and semantic
  enrichment; they are presentation metadata, not source identity.
- Keep `ontology-instructions.md` (the LLM steering doc for ontology
  generation) in sync with any change to naming/mapping rules in
  `src/generate` or `src/transform`.
- New stage logic goes in its matching `src/<stage>/` package
  (`extract`, `generate`, `validate`, `transform`, `publish`, `cli`, `common`).
- Fixtures/golden files for a stage belong in `tests/fixtures/`; add a
  matching unit or golden test in `tests/unit/` when you change mapping or
  transform logic.
- Run the narrowest relevant test immediately after an edit, then run
  `uv run pytest tests/unit -q` for changes that cross stage or publishing
  boundaries.
- Run `publish-ontology --dry-run` before a live publish. Prefer `--item-id`
  when updating a known ontology; otherwise verify the normalized display name
  used for exact-name resolution.
- Never hand-edit generated files under `out/`. Change the owning source code,
  prompt, skill, mapping, or source metadata and regenerate the artifacts.
- Keep repository text files UTF-8. Use ASCII punctuation in code and project
  guidance unless non-ASCII text is required for source data or multilingual
  labels.
- Follow existing code patterns and formatting in the repo rather than
  introducing a new style.
