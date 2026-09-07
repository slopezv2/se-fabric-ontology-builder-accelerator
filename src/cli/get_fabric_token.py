"""Acquire a Microsoft Entra access token for Microsoft Fabric REST APIs."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential

from extract.client import FABRIC_SCOPE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("token", "bearer", "header"),
        default="token",
        help="Output a raw token, Bearer value, or complete Authorization header.",
    )
    return parser


def acquire_token(credential: Any | None = None) -> str:
    """Acquire a Fabric access token from the local Azure credential chain."""
    active_credential = credential or DefaultAzureCredential()
    return active_credential.get_token(FABRIC_SCOPE).token


def format_token(token: str, output_format: str) -> str:
    if output_format == "bearer":
        return f"Bearer {token}"
    if output_format == "header":
        return f"Authorization: Bearer {token}"
    return token


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        token = acquire_token()
    except ClientAuthenticationError as exc:
        print(
            "Unable to authenticate. Sign in with 'az login' and run this command again.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1
    print(format_token(token, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())