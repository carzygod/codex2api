from __future__ import annotations

import ast
import unittest
from pathlib import Path


SOURCE_PATH = Path(__file__).resolve().parents[1] / "codex_image" / "webui" / "oai4k_api.py"


def _module_tree() -> ast.Module:
    return ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))


def _literal_assignment(name: str):
    for node in _module_tree().body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} assignment not found")


def _normalize_model_aliases() -> dict[str, str]:
    for node in _module_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == "_normalize_model":
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and target.id == "aliases":
                            return ast.literal_eval(child.value)
    raise AssertionError("_normalize_model aliases assignment not found")


class OAI4KModelContractTests(unittest.TestCase):
    def test_public_models_are_4k_suffixed(self) -> None:
        OAI4K_MODELS = _literal_assignment("OAI4K_MODELS")
        ids = [str(item["id"]) for item in OAI4K_MODELS]

        self.assertEqual(ids, ["gpt-image-2-4k", "oai-4k-gpt-image-2-4k"])
        self.assertTrue(all(model_id.endswith("-4k") for model_id in ids))
        self.assertTrue(all(item["provider_model"] == "gpt-image-2" for item in OAI4K_MODELS))

    def test_public_and_legacy_aliases_normalize_to_provider_model(self) -> None:
        aliases = _normalize_model_aliases()
        for model in (
            "gpt-image-2-4k",
            "oai-4k-gpt-image-2-4k",
            "codex-gpt-image-2-4k",
            "pro-codex-gpt-image-2-4k",
            "gpt-image-2",
            "oai-4k-gpt-image-2",
            "codex-gpt-image-2",
            "pro-codex-gpt-image-2",
        ):
            with self.subTest(model=model):
                normalized = aliases.get(model, model)
                self.assertEqual(normalized, "gpt-image-2")


if __name__ == "__main__":
    unittest.main()
