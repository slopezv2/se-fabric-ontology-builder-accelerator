"""Run the Fabric metadata notebook and download its OneLake output."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from azure.identity import DefaultAzureCredential


FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
ONELAKE_SCOPE = "https://storage.azure.com/.default"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
ONELAKE_ACCOUNT_URL = "https://onelake.dfs.fabric.microsoft.com"


@dataclass(frozen=True)
class ExtractConfig:
    """Configuration required to run the Fabric notebook extraction."""

    workspace_id: str
    notebook_id: str
    lakehouse_id: str
    metadata_file: str = "Files/raw_metadata/metadata.json"
    local_output: Path = Path("inputs/lakehouse_tables/metadata.json")
    tables: tuple[str, ...] = ()
    timeout_seconds: int = 1800
    poll_interval_seconds: int = 5


class FabricMetadataExtractor:
    """Submit a Fabric notebook job and download its normalized metadata."""

    def __init__(
        self,
        config: ExtractConfig,
        credential: Any | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.credential = credential or DefaultAzureCredential()
        self.http_client = http_client or httpx.Client(timeout=60)

    def close(self) -> None:
        self.http_client.close()

    def __enter__(self) -> "FabricMetadataExtractor":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _fabric_headers(self) -> dict[str, str]:
        token = self.credential.get_token(FABRIC_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _onelake_headers(self) -> dict[str, str]:
        token = self.credential.get_token(ONELAKE_SCOPE).token
        return {"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}

    def run(self) -> Path:
        job_url = self._start_notebook_job()
        self._wait_for_job(job_url)
        return self._download_metadata()

    def _start_notebook_job(self) -> str:
        url = (
            f"{FABRIC_API_BASE}/workspaces/{self.config.workspace_id}"
            f"/items/{self.config.notebook_id}/jobs/instances?jobType=RunNotebook"
        )
        arguments = {"metadata_file_location": self.config.metadata_file}
        if self.config.tables:
            arguments["tables_to_extract"] = ",".join(self.config.tables)
        payload = {"executionData": {"parameters": arguments}}
        response = self.http_client.post(url, headers=self._fabric_headers(), json=payload)
        response.raise_for_status()
        location = response.headers.get("Location") or response.headers.get("location")
        if location:
            return location
        body = response.json()
        job_url = body.get("jobInstanceUrl") or body.get("id")
        if job_url and str(job_url).startswith("http"):
            return str(job_url)
        if job_url:
            return f"{FABRIC_API_BASE}/workspaces/{self.config.workspace_id}/jobs/instances/{job_url}"
        raise RuntimeError("Fabric did not return a notebook job instance location")

    def _wait_for_job(self, job_url: str) -> None:
        deadline = time.monotonic() + self.config.timeout_seconds
        terminal_success = {"completed", "succeeded", "success"}
        terminal_failure = {"failed", "cancelled", "canceled", "timeout"}
        while time.monotonic() < deadline:
            response = self.http_client.get(job_url, headers=self._fabric_headers())
            response.raise_for_status()
            body = response.json()
            status = str(body.get("status") or body.get("state") or "").lower()
            if status in terminal_success:
                return
            if status in terminal_failure:
                raise RuntimeError(f"Fabric notebook job ended with status '{status}': {body}")
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else self.config.poll_interval_seconds
            time.sleep(delay)
        raise TimeoutError(f"Fabric notebook job did not finish within {self.config.timeout_seconds}s")

    def _download_metadata(self) -> Path:
        relative_path = self.config.metadata_file.lstrip("/")
        encoded_path = quote(relative_path, safe="/")
        url = (
            f"{ONELAKE_ACCOUNT_URL}/{self.config.workspace_id}/"
            f"{self.config.lakehouse_id}/{encoded_path}"
        )
        response = self.http_client.get(url, headers=self._onelake_headers())
        response.raise_for_status()
        content = response.content
        try:
            metadata = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("The Fabric output is not valid JSON metadata") from exc
        self.config.local_output.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_output.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.config.local_output