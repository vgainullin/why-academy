from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from frozen_task_store import FrozenTaskStore, FrozenTaskStoreError  # noqa: E402


BUNDLE = DERIVATIONS / "practice" / "algebra_linear_8th_grade_summer.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(directory: Path, value: object) -> Path:
    path = directory / "bundle.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return path


class FrozenTaskStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle_sha256 = _sha256(BUNDLE)

    def test_loads_full_pinned_bundle_and_returns_defensive_task_copies(self) -> None:
        store = FrozenTaskStore.load(BUNDLE, self.bundle_sha256)

        self.assertEqual(240, store.task_count)
        self.assertEqual(240, len(store.task_ids))
        self.assertEqual(self.bundle_sha256, store.bundle_sha256)

        task_id = store.task_ids[0]
        first = store.get_task(task_id)
        first["givens"].clear()
        first["display"]["prompt"] = "mutated"
        second = store.get_task(task_id)

        self.assertTrue(second["givens"])
        self.assertNotEqual("mutated", second["display"]["prompt"])

    def test_accepts_prefixed_full_hash_but_rejects_missing_or_wrong_pins(self) -> None:
        store = FrozenTaskStore.load(BUNDLE, f"sha256:{self.bundle_sha256}")
        self.assertEqual(self.bundle_sha256, store.bundle_sha256)

        invalid = ["", "abc", "0" * 64]
        for expected in invalid:
            with self.subTest(expected=expected):
                with self.assertRaises(FrozenTaskStoreError):
                    FrozenTaskStore.load(BUNDLE, expected)

    def test_hashes_exact_raw_bytes_before_trusting_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "bundle.json"
            copied.write_bytes(BUNDLE.read_bytes() + b"\n")

            with self.assertRaisesRegex(FrozenTaskStoreError, "SHA-256 mismatch"):
                FrozenTaskStore.load(copied, self.bundle_sha256)

    def test_rejects_invalid_schema_count_contracts_and_manifest(self) -> None:
        original = json.loads(BUNDLE.read_text())
        mutations = []

        wrong_schema = json.loads(json.dumps(original))
        wrong_schema["schema_version"] = "grade8_algebra_linear_practice.v2"
        mutations.append(wrong_schema)

        short = json.loads(json.dumps(original))
        short["tasks"].pop()
        short["total_tasks"] = 239
        mutations.append(short)

        duplicate = json.loads(json.dumps(original))
        duplicate["tasks"][1]["id"] = duplicate["tasks"][0]["id"]
        mutations.append(duplicate)

        invalid_contract = json.loads(json.dumps(original))
        invalid_contract["tasks"][0]["expected"]["values"][0]["numerator"] += 1
        mutations.append(invalid_contract)

        bad_manifest = json.loads(json.dumps(original))
        first_id = bad_manifest["tasks"][0]["id"]
        bad_manifest["contract_manifest"][first_id] = "sha256:" + "0" * 64
        mutations.append(bad_manifest)

        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            for index, bundle in enumerate(mutations):
                with self.subTest(index=index):
                    path = _write_bundle(directory, bundle)
                    with self.assertRaises(FrozenTaskStoreError):
                        FrozenTaskStore.load(path, _sha256(path))

    def test_selection_digest_is_deterministic_ordered_and_bundle_bound(self) -> None:
        store = FrozenTaskStore.load(BUNDLE, self.bundle_sha256)
        first, second = store.task_ids[:2]

        digest = store.selected_task_list_digest([first, second])

        self.assertEqual(digest, store.selected_task_list_digest((first, second)))
        self.assertNotEqual(digest, store.selected_task_list_digest([second, first]))
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

    def test_selection_and_lookup_fail_closed(self) -> None:
        store = FrozenTaskStore.load(BUNDLE, self.bundle_sha256)
        first = store.task_ids[0]

        invalid_selections = [[], [first, first], ["unknown-task"], [None], "not-a-list"]
        for selected in invalid_selections:
            with self.subTest(selected=selected):
                with self.assertRaises(FrozenTaskStoreError):
                    store.selected_task_list_digest(selected)  # type: ignore[arg-type]

        for task_id in ("", "unknown-task"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(FrozenTaskStoreError):
                    store.get_task(task_id)

    def test_rejects_duplicate_json_keys_even_with_matching_byte_pin(self) -> None:
        raw = b'{"schema_version":"grade8_algebra_linear_practice.v3","schema_version":"grade8_algebra_linear_practice.v3"}'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bundle.json"
            path.write_bytes(raw)

            with self.assertRaisesRegex(FrozenTaskStoreError, "duplicate key"):
                FrozenTaskStore.load(path, hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
