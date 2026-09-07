"""Transform RDF/OWL into Microsoft Fabric Ontology definition parts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from transform import TransformConfig, transform


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/accelerator.yaml"))
    parser.add_argument("--workspace-id")
    parser.add_argument("--lakehouse-id")
    parser.add_argument("--display-name", default="Generated Fabric Ontology")
    return parser


def _fabric_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream) or {}
    return document.get("fabric") or {}


def _required(value: Any, option: str) -> str:
    if value is None or not str(value).strip() or str(value).startswith("<"):
        raise SystemExit(f"Missing '{option}'. Set it in config/accelerator.yaml or pass --{option}.")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fabric = _fabric_config(args.config)
    config = TransformConfig(
        ontology_path=args.ontology,
        mapping_path=args.mapping,
        output_dir=args.output_dir,
        workspace_id=_required(args.workspace_id or fabric.get("workspace"), "workspace-id"),
        lakehouse_id=_required(args.lakehouse_id or fabric.get("lakehouse"), "lakehouse-id"),
        display_name=args.display_name,
    )
    counts = transform(config)
    print(f"Fabric Ontology definition written to {config.output_dir}")
    print(json_summary(counts))
    return 0


def json_summary(counts: dict[str, int]) -> str:
    return ", ".join(f"{name.replace('_', ' ')}: {value}" for name, value in counts.items())


if __name__ == "__main__":
    raise SystemExit(main())