import base64
import importlib.util
import json
import os
import subprocess
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


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.repo = "engimatic-systems/nix-engimatic-pkgs"
        self.pulls = [[]]
        self.base_sha = "trusted"
        self.colliding_branch = False
        self.responses = {
            "": {"default_branch": "main"},
            "/contents/releases/pi.json?ref=trusted": {
                "type": "file", "encoding": "base64", "sha": "file-sha",
                "content": base64.b64encode(json.dumps(OLD).encode()).decode(),
            },
        }
        mocks = [
            patch.dict(os.environ, {"GITHUB_REPOSITORY": self.repo,
                       "GITHUB_EVENT_NAME": "schedule", "GITHUB_SHA": "trusted"}),
            patch.object(updates, "api", side_effect=self.respond),
        ]
        for mock in mocks:
            self.api = mock.start()
            self.addCleanup(mock.stop)

    def respond(self, endpoint, method="GET", payload=None, paginate=False):
        path = endpoint.removeprefix(f"repos/{self.repo}")
        if path.startswith("/pulls?"):
            self.assertTrue(paginate)
            return self.pulls
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.base_sha}}
        if method != "GET":
            if self.colliding_branch and path == "/git/refs":
                raise subprocess.CalledProcessError(1, ["gh", "api"], stderr="Reference already exists")
            return {"html_url": "https://github.com/example/pr/1"}
        return self.responses[path]

    def writes(self):
        return [call.args for call in self.api.call_args_list
                if len(call.args) > 1 and call.args[1] != "GET"]

    def test_new_proposal_changes_only_metadata_on_a_new_versioned_branch(self):
        updates.publish(PROPOSAL)
        writes = self.writes()
        self.assertEqual([(url.removeprefix(f"repos/{self.repo}"), method)
                          for url, method, _ in writes],
                         [("/git/refs", "POST"), ("/contents/releases/pi.json", "PUT"), ("/pulls", "POST")])
        self.assertEqual(writes[0][2], {"ref": "refs/heads/automation/update-pi-1.1.0", "sha": "trusted"})
        self.assertEqual(json.loads(base64.b64decode(writes[1][2]["content"])), NEW)
        self.assertEqual(writes[1][2]["branch"], "automation/update-pi-1.1.0")
        self.assertEqual(writes[1][2]["sha"], "file-sha")
        self.assertEqual(writes[2][2]["base"], "main")
        self.assertEqual(writes[2][2]["head"], "automation/update-pi-1.1.0")

    def test_open_older_update_pr_is_untouched_even_on_a_later_page(self):
        self.pulls = [[], [{"head": {"ref": "automation/update-pi-1.0.1",
                                   "repo": {"full_name": self.repo}}}]]
        updates.publish(PROPOSAL)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.api.call_count, 1)

    def test_other_package_and_fork_prs_do_not_block_new_proposals(self):
        self.pulls = [[
            {"head": {"ref": "automation/update-codex-1.1.0", "repo": {"full_name": self.repo}}},
            {"head": {"ref": "automation/update-pi-1.1.0", "repo": {"full_name": "someone/fork"}}},
        ]]
        updates.publish(PROPOSAL)
        self.assertEqual(len(self.writes()), 3)

    def test_colliding_branch_stops_without_overwriting_or_recovering(self):
        self.colliding_branch = True
        with self.assertRaises(subprocess.CalledProcessError):
            updates.publish(PROPOSAL)
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(self.writes()[0][0].endswith("/git/refs"))

    def test_moved_base_and_untrusted_trigger_cannot_write(self):
        self.base_sha = "new-main"
        with self.assertRaisesRegex(ValueError, "moved"):
            updates.publish(PROPOSAL)
        self.assertEqual(self.writes(), [])
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request"}):
            with self.assertRaisesRegex(ValueError, "scheduled or manual"):
                updates.publish(PROPOSAL)
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main()
