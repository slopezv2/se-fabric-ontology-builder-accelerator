from types import SimpleNamespace
from unittest import TestCase

from cli.get_fabric_token import acquire_token, format_token
from extract.client import FABRIC_SCOPE


class FakeCredential:
    def __init__(self) -> None:
        self.scope: str | None = None

    def get_token(self, scope: str) -> SimpleNamespace:
        self.scope = scope
        return SimpleNamespace(token="test-token")


class GetFabricTokenTests(TestCase):
    def test_acquire_token_uses_fabric_scope(self) -> None:
        credential = FakeCredential()

        token = acquire_token(credential)

        self.assertEqual(token, "test-token")
        self.assertEqual(credential.scope, FABRIC_SCOPE)

    def test_format_token_supports_copy_paste_formats(self) -> None:
        self.assertEqual(format_token("test-token", "token"), "test-token")
        self.assertEqual(format_token("test-token", "bearer"), "Bearer test-token")
        self.assertEqual(
            format_token("test-token", "header"),
            "Authorization: Bearer test-token",
        )