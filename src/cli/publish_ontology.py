"""Create or update a Microsoft Fabric Ontology from generated definition parts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import yaml
from azure.core.exceptions import ClientAuthenticationError

from publish import FabricOntologyPublisher, PublishConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--definition",
        type=Path,
        default=Path("out/ontology-definition-specific"),
        help="Definition directory or fabric-definition.json path.",
    )
    parser.add_argument("--config", type=Path, default=Path("config/accelerator.yaml"))
    parser.add_argument("--workspace-id")
    parser.add_argument("--item-id", help="Update this ontology directly instead of resolving it by display name.")
    parser.add_argument("--display-name", help="Override metadata.displayName from the .platform part.")
    parser.add_argument("--description")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--poll-interval-seconds", type=float)
    parser.add_argument("--max-retries", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Validate and report the planned action without calling Fabric.")
    return parser


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream) or {}
    if not isinstance(document, dict):
        raise ValueError(f"Configuration root must be an object: {path}")
    return document


def _required(value: Any, option: str) -> str:
    if value is None or not str(value).strip() or str(value).startswith("<"):
        raise ValueError(f"Missing '{option}'. Set it in config/accelerator.yaml or pass --{option}.")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = _load_config(args.config)
        fabric = document.get("fabric") or {}
        publish = document.get("publish") or {}
        config = PublishConfig(
            workspace_id=_required(args.workspace_id or publish.get("workspace_id") or fabric.get("workspace"), "workspace-id"),
            definition_path=args.definition,
            item_id=args.item_id or publish.get("item_id"),
            display_name=args.display_name or publish.get("display_name"),
            description=args.description if args.description is not None else publish.get("description"),
            timeout_seconds=args.timeout_seconds or int(publish.get("timeout_seconds", 1800)),
            poll_interval_seconds=(
                args.poll_interval_seconds
                if args.poll_interval_seconds is not None
                else float(publish.get("poll_interval_seconds", 5))
            ),
            max_retries=args.max_retries if args.max_retries is not None else int(publish.get("max_retries", 5)),
            dry_run=args.dry_run,
        )
        with FabricOntologyPublisher(config) as publisher:
            result = publisher.publish()
    except (ClientAuthenticationError, httpx.HTTPError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Unable to publish Fabric Ontology: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())