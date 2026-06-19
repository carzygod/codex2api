from __future__ import annotations

import base64
import json
import unittest

from codex_image.webui.oai4k_credentials import parse_oai4k_account_material


def _b64url(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _jwt(account_id: str = "acct-123") -> str:
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    return f"header.{_b64url(payload)}.sig"


class OAI4KCredentialParserTests(unittest.TestCase):
    def test_parse_raw_token_with_fallbacks(self) -> None:
        credentials = parse_oai4k_account_material(
            "opaque-token",
            fallback_name="manual",
            fallback_account_id="acct-manual",
            fallback_refresh_token="refresh",
        )

        self.assertEqual(len(credentials), 1)
        self.assertEqual(credentials[0].name, "manual")
        self.assertEqual(credentials[0].access_token, "opaque-token")
        self.assertEqual(credentials[0].refresh_token, "refresh")
        self.assertEqual(credentials[0].account_id, "acct-manual")
        self.assertEqual(credentials[0].source_format, "plain")

    def test_parse_cpa_flat_json(self) -> None:
        token = _jwt("acct-cpa")
        credentials = parse_oai4k_account_material(
            json.dumps(
                {
                    "type": "codex",
                    "name": "CPA Account",
                    "access_token": token,
                    "refresh_token": "refresh-cpa",
                    "chatgpt_account_id": "acct-cpa-explicit",
                }
            )
        )

        self.assertEqual(len(credentials), 1)
        self.assertEqual(credentials[0].source_format, "cpa")
        self.assertEqual(credentials[0].name, "CPA Account")
        self.assertEqual(credentials[0].access_token, token)
        self.assertEqual(credentials[0].refresh_token, "refresh-cpa")
        self.assertEqual(credentials[0].account_id, "acct-cpa-explicit")

    def test_parse_sub2api_multiple_accounts(self) -> None:
        payload = {
            "accounts": [
                {
                    "name": "Sub A",
                    "credentials": {
                        "access_token": _jwt("acct-a"),
                        "chatgpt_account_id": "acct-a",
                    },
                },
                {
                    "name": "Sub B",
                    "credentials": {
                        "access_token": _jwt("acct-b"),
                        "refresh_token": "refresh-b",
                    },
                },
            ]
        }

        credentials = parse_oai4k_account_material(json.dumps(payload))

        self.assertEqual([item.name for item in credentials], ["Sub A", "Sub B"])
        self.assertEqual([item.source_format for item in credentials], ["sub2api", "sub2api"])
        self.assertEqual([item.account_id for item in credentials], ["acct-a", "acct-b"])
        self.assertEqual(credentials[1].refresh_token, "refresh-b")

    def test_parse_codex_auth_json(self) -> None:
        token = _jwt("acct-auth")
        credentials = parse_oai4k_account_material(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "tokens": {
                        "access_token": token,
                        "refresh_token": "refresh-auth",
                        "account_id": "acct-auth-explicit",
                    },
                }
            ),
            fallback_name="auth-json",
        )

        self.assertEqual(len(credentials), 1)
        self.assertEqual(credentials[0].source_format, "auth.json")
        self.assertEqual(credentials[0].name, "auth-json")
        self.assertEqual(credentials[0].refresh_token, "refresh-auth")
        self.assertEqual(credentials[0].account_id, "acct-auth-explicit")

    def test_parse_codex_manager(self) -> None:
        credentials = parse_oai4k_account_material(
            json.dumps(
                {
                    "tokens": {
                        "access_token": _jwt("acct-manager"),
                        "refresh_token": "refresh-manager",
                    },
                    "meta": {"label": "manager-label", "chatgpt_account_id": "acct-manager-meta"},
                }
            )
        )

        self.assertEqual(len(credentials), 1)
        self.assertEqual(credentials[0].source_format, "codex-manager")
        self.assertEqual(credentials[0].name, "manager-label")
        self.assertEqual(credentials[0].account_id, "acct-manager-meta")


if __name__ == "__main__":
    unittest.main()
