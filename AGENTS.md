# AGENTS.md

## What this project is

Fabric Ontology Builder Accelerator: a pipeline that turns Microsoft Fabric
lakehouse metadata (mirrored Databricks Unity Catalog) into an RDF/OWL
ontology, validates it, transforms it into a Fabric Ontology item definition
(JSON parts), and publishes it via the Fabric REST API. RDF/OWL is the
canonical, human-reviewable artifact — the Fabric JSON definition is a
generated output, never hand-edited.

Full architecture, phased roadmap, and design rationale live in `plan.md`.
Read it before making non-trivial changes; keep it updated when scope or
architecture decisions change.

## Tech stack & tooling

- Python >= 3.12, managed with **uv** (not pip/poetry). Use `uv add <pkg>` to
  add dependencies, `uv sync` to install, `uv run <cmd>` to execute anything.
- Build backend: `uv_build`. Installable package lives at
  `src/se_fabric_ontology_builder_accelerator/`.
- Planned libs (see `plan.md` §7): `rdflib`, `owlready2`, `pySHACL`, `pydantic`,
  `httpx`, `msal`, `pyyaml`, `pytest`.

## How to build, run, test

- Install deps: `uv sync`
- Run the CLI (once implemented): `uv run se-fabric-ontology-builder-accelerator`
- Run tests: `uv run pytest`
- Add a runtime dependency: `uv add <package>`
- Add a dev-only dependency: `uv add --dev <package>`

There is no separate lint/format command configured yet — if you add one,
document it here.

## Pipeline stages (one command per stage)

`extract -> generate -> validate -> transform -> publish`, orchestrated by
`run`. Each stage reads/writes files under `out/` so it can be re-run and
reviewed independently. Don't skip a stage's file output to "optimize" the
pipeline — file-based hand-off is intentional for reviewability.

## Working conventions

- Treat RDF/OWL (`out/ontology.ttl` / `.owl`) as the source of truth; the
  Fabric Ontology definition JSON is derived and must stay reproducible from
  it (deterministic IDs — see `plan.md` §3.4 and §6 risks).
- Keep `ontology-instructions.md` (the LLM steering doc for ontology
  generation) in sync with any change to naming/mapping rules in
  `src/generate` or `src/transform`.
- New stage logic goes in its matching `src/<stage>/` package
  (`extract`, `generate`, `validate`, `transform`, `publish`, `cli`, `common`).
- Fixtures/golden files for a stage belong in `tests/fixtures/`; add a
  matching unit or golden test in `tests/unit/` when you change mapping or
  transform logic.
- Follow existing code patterns and formatting in the repo rather than
  introducing a new style.
