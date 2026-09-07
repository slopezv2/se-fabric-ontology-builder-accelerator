import base64
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

import httpx

from extract.client import FABRIC_API_BASE, FABRIC_SCOPE
from cli.publish_ontology import main
from publish import FabricOntologyPublisher, PublishConfig, fabric_item_name


WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
ITEM_ID = "22222222-2222-2222-2222-222222222222"
OPERATION_ID = "33333333-3333-3333-3333-333333333333"


class FakeCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> SimpleNamespace:
        self.scopes.append(scope)
        return SimpleNamespace(token="test-token")


class FailingCredential:
    def get_token(self, _scope: str) -> SimpleNamespace:
        raise AssertionError("Dry-run must not request a token")


def encoded(payload: dict[str, object]) -> str:
    content = (json.dumps(payload) + "\n").encode("utf-8")
    return base64.b64encode(content).decode("ascii")


def write_definition(root: Path) -> Path:
    definition = {
        "parts": [
            {
                "path": ".platform",
                "payload": encoded({"metadata": {"type": "Ontology", "displayName": "TestOntology"}}),
                "payloadType": "InlineBase64",
            },
            {
                "path": "definition.json",
                "payload": encoded({}),
                "payloadType": "InlineBase64",
            },
        ]
    }
    path = root / "fabric-definition.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    return path


class FabricOntologyPublisherTests(TestCase):
    def test_fabric_item_name_normalizes_and_limits_names(self) -> None:
        self.assertEqual(fabric_item_name("example storage Specific Ontology"), "example_storage_Specific_Ontology")
        self.assertEqual(fabric_item_name("123 ontology"), "Ontology_123_ontology")
        self.assertLess(len(fabric_item_name("Ontology " + "x" * 100)), 90)

    def test_cli_dry_run_uses_generated_display_name(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            definition_path = write_definition(Path(temporary_directory))
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--definition",
                        str(definition_path),
                        "--workspace-id",
                        WORKSPACE_ID,
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["action"], "create-or-update")
            self.assertEqual(result["display_name"], "TestOntology")

    def test_dry_run_validates_definition_without_authentication(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            definition_path = write_definition(Path(temporary_directory))
            config = PublishConfig(WORKSPACE_ID, definition_path, dry_run=True)

            with FabricOntologyPublisher(config, credential=FailingCredential()) as publisher:
                result = publisher.publish()

            self.assertEqual(result.action, "create-or-update")
            self.assertEqual(result.display_name, "TestOntology")
            self.assertEqual(result.parts, 2)
            self.assertIsNone(result.item_id)

    def test_publish_creates_ontology_synchronously(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            definition_path = write_definition(Path(temporary_directory))
            credential = FakeCredential()

            def handler(request: httpx.Request) -> httpx.Response:
                self.assertEqual(request.headers["Authorization"], "Bearer test-token")
                if request.method == "GET":
                    return httpx.Response(200, json={"value": []})
                payload = json.loads(request.content)
                self.assertEqual(payload["displayName"], "TestOntology")
                self.assertEqual(len(payload["definition"]["parts"]), 2)
                return httpx.Response(
                    201,
                    json={"id": ITEM_ID, "displayName": "TestOntology", "type": "Ontology"},
                )

            http_client = httpx.Client(transport=httpx.MockTransport(handler))
            config = PublishConfig(WORKSPACE_ID, definition_path, description="Test ontology")
            with FabricOntologyPublisher(config, credential, http_client, sleeper=lambda _: None) as publisher:
                result = publisher.publish()
            http_client.close()

            self.assertEqual(result.action, "created")
            self.assertEqual(result.item_id, ITEM_ID)
            self.assertTrue(credential.scopes)
            self.assertTrue(all(scope == FABRIC_SCOPE for scope in credential.scopes))

    def test_publish_gets_asynchronous_create_result(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            definition_path = write_definition(Path(temporary_directory))
            operation_url = f"{FABRIC_API_BASE}/operations/{OPERATION_ID}"
            result_url = f"{operation_url}/result"
            requests: list[tuple[str, str]] = []

            def handler(request: httpx.Request) -> httpx.Response:
                requests.append((request.method, str(request.url)))
                if request.method == "GET" and "/ontologies" in request.url.path:
                    return httpx.Response(200, json={"value": []})
                if request.method == "POST":
                    return httpx.Response(
                        202,
                        headers={"Location": operation_url, "x-ms-operation-id": OPERATION_ID, "Retry-After": "0"},
                    )
                if str(request.url) == operation_url:
                    return httpx.Response(200, headers={"Location": result_url}, json={"status": "Succeeded"})
                if str(request.url) == result_url:
                    return httpx.Response(200, json={"id": ITEM_ID, "displayName": "TestOntology"})
                raise AssertionError(f"Unexpected request: {request.method} {request.url}")

            http_client = httpx.Client(transport=httpx.MockTransport(handler))
            config = PublishConfig(WORKSPACE_ID, definition_path, poll_interval_seconds=0)
            with FabricOntologyPublisher(config, FakeCredential(), http_client, sleeper=lambda _: None) as publisher:
                result = publisher.publish()
            http_client.close()

            self.assertEqual(result.item_id, ITEM_ID)
            self.assertIn(("GET", result_url), requests)

    def test_publish_resolves_paginated_item_and_updates_definition(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            definition_path = write_definition(Path(temporary_directory))
            first_url = f"{FABRIC_API_BASE}/workspaces/{WORKSPACE_ID}/ontologies"
            second_url = f"{first_url}?continuationToken=next"
            operation_url = f"{FABRIC_API_BASE}/operations/{OPERATION_ID}"
            update_seen = False

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal update_seen
                url = str(request.url)
                if request.method == "GET" and url == first_url:
                    return httpx.Response(200, json={"value": [], "continuationUri": second_url})
                if request.method == "GET" and url == second_url:
                    return httpx.Response(200, json={"value": [{"id": ITEM_ID, "displayName": "TestOntology"}]})
                if request.method == "POST" and request.url.path.endswith("/updateDefinition"):
                    update_seen = True
                    self.assertEqual(request.url.params["updateMetadata"], "true")
                    self.assertIn("definition", json.loads(request.content))
                    return httpx.Response(
                        202,
                        headers={"Location": operation_url, "x-ms-operation-id": OPERATION_ID, "Retry-After": "0"},
                    )
                if request.method == "GET" and url == operation_url:
                    return httpx.Response(200, json={"status": "Succeeded"})
                raise AssertionError(f"Unexpected request: {request.method} {request.url}")

            http_client = httpx.Client(transport=httpx.MockTransport(handler))
            config = PublishConfig(WORKSPACE_ID, definition_path, poll_interval_seconds=0)
            with FabricOntologyPublisher(config, FakeCredential(), http_client, sleeper=lambda _: None) as publisher:
                result = publisher.publish()
            http_client.close()

            self.assertTrue(update_seen)
            self.assertEqual(result.action, "updated")
            self.assertEqual(result.item_id, ITEM_ID)