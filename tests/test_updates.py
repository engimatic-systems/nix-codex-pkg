import base64
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "updates", Path(__file__).resolve().parents[1] / "scripts/update_releases.py")
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)

DIGEST = "ab" * 32
HASH = "sha256-" + base64.b64encode(bytes.fromhex(DIGEST)).decode()
OLD = {"version": "1.0.0", "hash": HASH}
NEW = {"version": "1.1.0", "hash": HASH}
PROPOSAL = {"package": "pi", "previous": OLD, "selected": NEW}


def release(package="pi", version="1.1.0"):
    repo, prefix, asset = updates.PACKAGES[package]
    notes, url = updates.release_urls(package, version)
    return {"tag_name": prefix + version, "draft": False, "prerelease": False,
            "html_url": notes, "assets": [{"name": asset,
            "browser_download_url": url, "digest": "sha256:" + DIGEST}]}


class DiscoveryTests(unittest.TestCase):
    def test_each_package_proposes_only_validated_metadata(self):
        for package in updates.PACKAGES:
            result = updates.candidate(package, OLD, release(package), lambda url: DIGEST)
            self.assertEqual(result, {**PROPOSAL, "package": package})

    def test_same_release_is_noop_but_still_downloads_and_checks(self):
        calls = []
        self.assertIsNone(updates.candidate("pi", NEW, release(),
                          lambda url: calls.append(url) or DIGEST))
        self.assertEqual(len(calls), 1)

    def test_changed_selected_archive_and_mismatched_digest_fail(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            updates.candidate("pi", OLD, release(), lambda url: "cd" * 32)
        changed = {**NEW, "hash": "sha256-" + base64.b64encode(b"x" * 32).decode()}
        with self.assertRaisesRegex(ValueError, "archive changed"):
            updates.candidate("pi", changed, release(), lambda url: DIGEST)

    def test_unexpected_release_metadata_fails_before_download(self):
        cases = []
        for field in ("draft", "prerelease"):
            item = release()
            item[field] = True
            cases.append(item)
        for version in ("1.1.0-rc.1", "$(touch /tmp/no)", "01.1.0"):
            item = release()
            item["tag_name"] = "v" + version
            cases.append(item)
        item = release()
        item["assets"] = []
        cases.append(item)
        item = release()
        item["assets"] *= 2
        cases.append(item)
        for field, value in (("browser_download_url", "https://example.org/asset"),
                             ("digest", None), ("digest", "sha256:bad")):
            item = release()
            item["assets"][0][field] = value
            cases.append(item)
        item = release()
        item["html_url"] = "https://example.org/release"
        cases.append(item)
        cases.append(release(version="0.9.0"))
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                updates.candidate("pi", OLD, item,
                                  lambda url: self.fail("must reject before downloading"))

    def test_privileged_input_rejects_paths_extra_fields_and_invalid_hashes(self):
        cases = [{**PROPOSAL, "package": "../../workflow"},
                 {**PROPOSAL, "command": "run me"},
                 {**PROPOSAL, "selected": OLD},
                 {**PROPOSAL, "selected": {**NEW, "hash": "sha256-YQ=="}},
                 {**PROPOSAL, "selected": {**NEW, "url": "https://example.org"}}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                updates.validate_candidate(value)


class FakeGitHub:
    """Model remote branch/file/PR state and record all write operations."""

    def __init__(self):
        self.branch = None
        self.pull = None
        self.files = []
        self.base_sha = "trusted"
        self.writes = []

    def api(self, endpoint, method="GET", payload=None):
        prefix = "repos/engimatic-systems/nix-engimatic-pkgs"
        path = endpoint.removeprefix(prefix)
        if method != "GET":
            self.writes.append((path, method, payload))
        if path == "":
            return {"default_branch": "main"}
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.base_sha}}
        if path == "/git/ref/heads/automation/update-pi":
            return {"object": {"sha": "branch"}} if self.branch else None
        if path == "/git/refs":
            self.branch = deepcopy(OLD)
            return {"object": {"sha": self.base_sha}}
        if path == "/git/commits/trusted":
            return {"tree": {"sha": "trusted-tree"}}
        if path == "/git/trees":
            assert payload["base_tree"] == "trusted-tree"
            assert len(payload["tree"]) == 1
            entry = payload["tree"][0]
            assert (entry["path"], entry["mode"], entry["type"]) == ("releases/pi.json", "100644", "blob")
            self.pending = json.loads(entry["content"])
            return {"sha": "new-tree"}
        if path == "/git/commits":
            assert payload["tree"] == "new-tree"
            assert "trusted" in payload["parents"]
            return {"sha": "new-commit"}
        if path == "/git/refs/heads/automation/update-pi":
            assert payload == {"sha": "new-commit", "force": False}
            self.branch = self.pending
            self.files = [{"filename": "releases/pi.json", "status": "modified"}]
            return {}
        if path.startswith("/compare/"):
            return {"status": "ahead", "files": self.files}
        if path.startswith("/contents/releases/pi.json"):
            pin = OLD if path.endswith("ref=main") else self.branch
            return {"type": "file", "encoding": "base64", "sha": "file-sha",
                    "content": base64.b64encode(json.dumps(pin).encode()).decode()}
        if path.startswith("/pulls?"):
            return [self.pull] if self.pull else []
        if path == "/pulls" or path == "/pulls/1":
            self.pull = {**payload, "number": 1, "html_url": "https://github.com/example/pr/1"}
            return self.pull
        raise AssertionError((endpoint, method, payload))


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        for mock in (
            patch.dict(os.environ, {"GITHUB_REPOSITORY": "engimatic-systems/nix-engimatic-pkgs",
                       "GITHUB_EVENT_NAME": "schedule", "GITHUB_SHA": "trusted"}),
            patch.object(updates, "api", self.github.api),
            patch.object(updates, "optional_api", self.github.api),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def test_create_then_repeat_is_noop_and_interrupted_pr_creation_recovers(self):
        updates.publish(PROPOSAL)
        self.assertEqual(self.github.branch, NEW)
        self.assertEqual([method for _, method, _ in self.github.writes],
                         ["POST", "POST", "POST", "PATCH", "POST"])
        self.github.writes.clear()
        updates.publish(PROPOSAL)
        self.assertEqual(self.github.writes, [])
        self.github.pull = None
        updates.publish(PROPOSAL)
        self.assertEqual([(path, method) for path, method, _ in self.github.writes],
                         [("/pulls", "POST")])

    def test_existing_pr_advances_without_a_second_pr(self):
        updates.publish(PROPOSAL)
        self.github.writes.clear()
        updates.publish({**PROPOSAL, "selected": {**NEW, "version": "1.2.0"}})
        self.assertEqual([(path, method) for path, method, _ in self.github.writes],
                         [("/git/trees", "POST"), ("/git/commits", "POST"),
                          ("/git/refs/heads/automation/update-pi", "PATCH"), ("/pulls/1", "PATCH")])

    def test_non_metadata_edits_are_not_overwritten(self):
        self.github.branch = OLD
        self.github.files = [{"filename": ".github/workflows/check.yml", "status": "modified"}]
        with self.assertRaisesRegex(ValueError, "non-metadata"):
            updates.publish(PROPOSAL)
        self.assertEqual(self.github.writes, [])

    def test_moved_base_and_untrusted_trigger_cannot_write(self):
        self.github.base_sha = "new-main"
        with self.assertRaisesRegex(ValueError, "moved"):
            updates.publish(PROPOSAL)
        self.assertEqual(self.github.writes, [])
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request"}):
            with self.assertRaisesRegex(ValueError, "scheduled or manual"):
                updates.publish(PROPOSAL)
        self.assertEqual(self.github.writes, [])


if __name__ == "__main__":
    unittest.main()
