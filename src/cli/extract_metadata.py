"""Command-line entry point for Fabric metadata extraction."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from extract.client import ExtractConfig, FabricMetadataExtractor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/accelerator.yaml"))
    parser.add_argument("--workspace-id")
    parser.add_argument("--notebook-id")
    parser.add_argument("--lakehouse-id")
    parser.add_argument("--metadata-file")
    parser.add_argument("--local-output", type=Path)
    parser.add_argument("--table", action="append", dest="tables")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--poll-interval-seconds", type=int)
    return parser


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream) or {}
    extract = document.get("extract") or {}
    fabric = document.get("fabric") or {}
    return {
        "workspace_id": extract.get("workspace_id", fabric.get("workspace")),
        "notebook_id": extract.get("notebook_id", fabric.get("notebook")),
        "lakehouse_id": extract.get("lakehouse_id", fabric.get("lakehouse")),
        "metadata_file": extract.get("metadata_file", "Files/raw_metadata/metadata.json"),
        "local_output": extract.get("local_output", "inputs/lakehouse_tables/metadata.json"),
        "tables": extract.get("tables", []),
        "timeout_seconds": extract.get("timeout_seconds", 1800),
        "poll_interval_seconds": extract.get("poll_interval_seconds", 5),
    }


def _required(value: Any, name: str) -> str:
    if value is None or str(value).startswith("<"):
        raise SystemExit(f"Missing '{name}'. Set it in config/accelerator.yaml or pass --{name.replace('_', '-')}")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    values = _load_config(args.config)
    for name in (
        "workspace_id",
        "notebook_id",
        "lakehouse_id",
        "metadata_file",
        "local_output",
        "tables",
        "timeout_seconds",
        "poll_interval_seconds",
    ):
        override = getattr(args, name)
        if override is not None:
            values[name] = override
    config = ExtractConfig(
        workspace_id=_required(values.get("workspace_id"), "workspace_id"),
        notebook_id=_required(values.get("notebook_id"), "notebook_id"),
        lakehouse_id=_required(values.get("lakehouse_id"), "lakehouse_id"),
        metadata_file=str(values["metadata_file"]),
        local_output=Path(values["local_output"]),
        tables=tuple(values.get("tables") or ()),
        timeout_seconds=int(values["timeout_seconds"]),
        poll_interval_seconds=int(values["poll_interval_seconds"]),
    )
    with FabricMetadataExtractor(config) as extractor:
        output = extractor.run()
    print(f"Metadata written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())