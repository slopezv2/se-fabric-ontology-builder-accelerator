"""Publish generated ontology definitions through the Microsoft Fabric REST API."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
from azure.identity import DefaultAzureCredential

from extract.client import FABRIC_API_BASE, FABRIC_SCOPE


TRANSIENT_STATUS_CODES = {408, 429, 502, 503, 504}
TERMINAL_FAILURE_STATES = {"cancelled", "canceled", "failed"}
ITEM_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,88}$")


@dataclass(frozen=True)
class PublishConfig:
    workspace_id: str
    definition_path: Path
    item_id: str | None = None
    display_name: str | None = None
    description: str | None = None
    timeout_seconds: int = 1800
    poll_interval_seconds: float = 5.0
    max_retries: int = 5
    dry_run: bool = False


@dataclass(frozen=True)
class PublishResult:
    action: str
    display_name: str
    parts: int
    item_id: str | None = None


def fabric_item_name(value: str) -> str:
    """Return a deterministic name accepted by the Fabric Ontology API."""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", ascii_value).strip("_") or "Ontology"
    if not name[0].isalpha():
        name = f"Ontology_{name}"
    if len(name) > 89:
        suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
        name = f"{name[:78]}_{suffix}"
    if not ITEM_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Unable to create a valid Fabric Ontology name from '{value}'")
    return name


def _set_platform_display_name(envelope: dict[str, Any], display_name: str) -> None:
    for part in envelope["parts"]:
        if part["path"] != ".platform":
            continue
        platform = json.loads(base64.b64decode(part["payload"], validate=True))
        platform["metadata"]["displayName"] = display_name
        content = (json.dumps(platform, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        part["payload"] = base64.b64encode(content).decode("ascii")
        return
    raise ValueError("Fabric definition envelope is missing the .platform part")


def load_definition(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate a transformer-generated Fabric definition envelope."""
    definition_path = path / "fabric-definition.json" if path.is_dir() else path
    if not definition_path.is_file():
        raise ValueError(f"Fabric definition envelope not found: {definition_path}")
    try:
        envelope = json.loads(definition_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Fabric definition envelope is not valid JSON: {definition_path}") from exc

    parts = envelope.get("parts") if isinstance(envelope, dict) else None
    if not isinstance(parts, list) or not parts:
        raise ValueError("Fabric definition envelope must contain a non-empty 'parts' array")

    paths: set[str] = set()
    platform: dict[str, Any] | None = None
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise ValueError(f"Definition part at index {index} must be an object")
        part_path = part.get("path")
        if not isinstance(part_path, str) or not part_path:
            raise ValueError(f"Definition part at index {index} has no path")
        if part_path in paths:
            raise ValueError(f"Duplicate definition part path: {part_path}")
        paths.add(part_path)
        if part.get("payloadType") != "InlineBase64":
            raise ValueError(f"Definition part '{part_path}' must use InlineBase64")
        try:
            decoded = base64.b64decode(part.get("payload", ""), validate=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Definition part '{part_path}' has invalid base64") from exc
        if part_path == ".platform":
            try:
                platform = json.loads(decoded)
            except json.JSONDecodeError as exc:
                raise ValueError("The .platform definition part is not valid JSON") from exc

    missing = {".platform", "definition.json"} - paths
    if missing:
        raise ValueError(f"Fabric definition envelope is missing required parts: {sorted(missing)}")
    metadata = platform.get("metadata") if isinstance(platform, dict) else None
    display_name = metadata.get("displayName") if isinstance(metadata, dict) else None
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("The .platform part must contain metadata.displayName")
    if metadata.get("type") != "Ontology":
        raise ValueError("The .platform part metadata.type must be 'Ontology'")
    return envelope, display_name


class FabricOntologyPublisher:
    """Create or update a Fabric Ontology from a generated definition envelope."""

    def __init__(
        self,
        config: PublishConfig,
        credential: Any | None = None,
        http_client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.credential = credential or DefaultAzureCredential()
        self.http_client = http_client or httpx.Client(timeout=60)
        self.sleeper = sleeper
        self._owns_http_client = http_client is None
        self._validate_config()

    def _validate_config(self) -> None:
        for name, value in (("workspace_id", self.config.workspace_id), ("item_id", self.config.item_id)):
            if value is None:
                continue
            try:
                uuid.UUID(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be a valid GUID: '{value}'") from exc
        if self.config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.config.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")
        if self.config.max_retries < 0:
            raise ValueError("max_retries cannot be negative")

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def __enter__(self) -> "FabricOntologyPublisher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        token = self.credential.get_token(FABRIC_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int, fallback: float) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return max(fallback, min(2.0**attempt, 30.0))

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            request_id = response.headers.get("requestId") or response.headers.get("x-ms-request-id")
            try:
                detail = response.json()
            except json.JSONDecodeError:
                detail = response.text
            suffix = f" Request ID: {request_id}." if request_id else ""
            raise RuntimeError(f"Fabric API returned HTTP {response.status_code}: {detail}.{suffix}") from exc

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            response = self.http_client.request(method, url, headers=self._headers(), **kwargs)
            if response.status_code not in TRANSIENT_STATUS_CODES or attempt == self.config.max_retries:
                self._raise_for_status(response)
                return response
            self.sleeper(self._retry_delay(response, attempt, self.config.poll_interval_seconds))
        raise AssertionError("Retry loop exited unexpectedly")

    def _list_ontologies(self) -> list[dict[str, Any]]:
        url: str | None = f"{FABRIC_API_BASE}/workspaces/{self.config.workspace_id}/ontologies"
        ontologies: list[dict[str, Any]] = []
        while url:
            response = self._request("GET", url)
            body = response.json()
            values = body.get("value", [])
            if not isinstance(values, list):
                raise RuntimeError("Fabric ontology list response has no 'value' array")
            ontologies.extend(item for item in values if isinstance(item, dict))
            continuation_uri = body.get("continuationUri")
            url = str(continuation_uri) if continuation_uri else None
        return ontologies

    def _resolve_item_id(self, display_name: str) -> str | None:
        matches = [item for item in self._list_ontologies() if item.get("displayName") == display_name]
        if len(matches) > 1:
            raise RuntimeError(f"Multiple Fabric ontologies have the display name '{display_name}'")
        if not matches:
            return None
        item_id = matches[0].get("id")
        if not isinstance(item_id, str):
            raise RuntimeError(f"Fabric ontology '{display_name}' has no item ID")
        return item_id

    def _wait_for_operation(self, response: httpx.Response, expect_result: bool) -> dict[str, Any] | None:
        location = response.headers.get("Location")
        operation_id = response.headers.get("x-ms-operation-id")
        if not location and operation_id:
            location = f"{FABRIC_API_BASE}/operations/{operation_id}"
        if not location:
            raise RuntimeError("Fabric returned HTTP 202 without Location or x-ms-operation-id")

        deadline = time.monotonic() + self.config.timeout_seconds
        delay = self._retry_delay(response, 0, self.config.poll_interval_seconds)
        while time.monotonic() < deadline:
            self.sleeper(delay)
            operation_response = self._request("GET", location)
            operation = operation_response.json()
            status = str(operation.get("status") or "").lower()
            if status == "succeeded":
                if not expect_result:
                    return operation
                result_url = operation_response.headers.get("Location")
                if not result_url or not result_url.rstrip("/").endswith("/result"):
                    if not operation_id:
                        operation_id = operation_response.headers.get("x-ms-operation-id")
                    if not operation_id:
                        raise RuntimeError("Completed Fabric operation did not provide a result URL")
                    result_url = f"{FABRIC_API_BASE}/operations/{operation_id}/result"
                return self._request("GET", result_url).json()
            if status in TERMINAL_FAILURE_STATES:
                raise RuntimeError(f"Fabric operation ended with status '{status}': {operation}")
            next_location = operation_response.headers.get("Location")
            if next_location:
                location = next_location
            delay = self._retry_delay(operation_response, 0, self.config.poll_interval_seconds)
        raise TimeoutError(f"Fabric operation did not finish within {self.config.timeout_seconds}s")

    def publish(self) -> PublishResult:
        envelope, platform_display_name = load_definition(self.config.definition_path)
        display_name = fabric_item_name(self.config.display_name or platform_display_name)
        _set_platform_display_name(envelope, display_name)
        if self.config.dry_run:
            action = "update" if self.config.item_id else "create-or-update"
            return PublishResult(action=action, display_name=display_name, parts=len(envelope["parts"]), item_id=self.config.item_id)

        item_id = self.config.item_id or self._resolve_item_id(display_name)
        if item_id:
            url = (
                f"{FABRIC_API_BASE}/workspaces/{self.config.workspace_id}/ontologies/"
                f"{item_id}/updateDefinition"
            )
            response = self._request(
                "POST",
                url,
                params={"updateMetadata": "true"},
                json={"definition": envelope},
            )
            if response.status_code == 202:
                self._wait_for_operation(response, expect_result=False)
            return PublishResult("updated", display_name, len(envelope["parts"]), item_id)

        payload: dict[str, Any] = {"displayName": display_name, "definition": envelope}
        if self.config.description is not None:
            payload["description"] = self.config.description
        url = f"{FABRIC_API_BASE}/workspaces/{self.config.workspace_id}/ontologies"
        response = self._request("POST", url, json=payload)
        created = self._wait_for_operation(response, expect_result=True) if response.status_code == 202 else response.json()
        created_id = created.get("id") if isinstance(created, dict) else None
        if not isinstance(created_id, str):
            raise RuntimeError("Fabric create response did not contain the ontology item ID")
        return PublishResult("created", display_name, len(envelope["parts"]), created_id)