#!/usr/bin/env python3
"""Propose official release pins without executing downloaded code."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {
    "codex": ("openai/codex", "rust-v", "codex-package-x86_64-unknown-linux-musl.tar.gz"),
    "pi": ("earendil-works/pi", "v", "pi-linux-x64.tar.gz"),
}
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", re.ASCII)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def version_tuple(version):
    require(isinstance(version, str) and len(version) < 40 and VERSION.fullmatch(version),
            "expected a stable major.minor.patch version")
    return tuple(map(int, version.split(".")))


def validate_pin(pin):
    require(isinstance(pin, dict) and set(pin) == {"version", "hash"},
            "release pin must contain only version and hash")
    version_tuple(pin["version"])
    value = pin["hash"]
    require(isinstance(value, str) and value.startswith("sha256-"), "expected SHA-256 SRI")
    raw = base64.b64decode(value[7:], validate=True)
    require(len(raw) == 32 and base64.b64encode(raw).decode() == value[7:],
            "expected canonical SHA-256 SRI")
    return pin


def encode_pin(pin):
    return json.dumps(validate_pin(pin), indent=2) + "\n"


def api(endpoint, method="GET", payload=None, paginate=False):
    command = ["gh", "api", "--method", method, endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def release_urls(package, version):
    repo, prefix, asset = PACKAGES[package]
    tag = prefix + version
    return (f"https://github.com/{repo}/releases/tag/{tag}",
            f"https://github.com/{repo}/releases/download/{tag}/{asset}")


def select_asset(package, release):
    repo, prefix, name = PACKAGES[package]
    require(release.get("draft") is False and release.get("prerelease") is False,
            "refusing draft or prerelease")
    tag = release.get("tag_name", "")
    require(isinstance(tag, str) and tag.startswith(prefix), "unexpected release tag")
    version = tag[len(prefix):]
    version_tuple(version)
    release_url, asset_url = release_urls(package, version)
    require(release.get("html_url") == release_url, "unexpected release URL")
    assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
    require(len(assets) == 1, "expected exactly one platform archive")
    asset = assets[0]
    require(asset.get("browser_download_url") == asset_url, "unexpected archive URL")
    digest = asset.get("digest", "")
    require(isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
            "missing or invalid upstream SHA-256 digest")
    return version, asset_url, digest[7:]


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        require(urllib.parse.urlparse(newurl).scheme == "https", "non-HTTPS asset redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_digest(url):
    # No token is sent to release assets or their CDN redirects. Never extract/run them.
    digest = hashlib.sha256()
    size = 0
    opener = urllib.request.build_opener(HTTPSRedirects())
    with opener.open(url, timeout=60) as response:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            require(size <= 1024 * 1024 * 1024, "archive exceeds 1 GiB limit")
            digest.update(chunk)
    require(size > 0, "empty archive")
    return digest.hexdigest()


def candidate(package, current, release, fetch_digest=download_digest):
    validate_pin(current)
    version, url, expected = select_asset(package, release)
    require(version_tuple(version) >= version_tuple(current["version"]), "refusing downgrade")
    actual = fetch_digest(url)
    require(actual == expected, "downloaded archive does not match upstream digest")
    selected = {"version": version,
                "hash": "sha256-" + base64.b64encode(bytes.fromhex(actual)).decode()}
    if version == current["version"]:
        require(selected == current, "selected release archive changed; manual investigation required")
        return None
    return {"package": package, "previous": current, "selected": selected}


def validate_candidate(value):
    require(isinstance(value, dict) and set(value) == {"package", "previous", "selected"},
            "unexpected proposal fields")
    require(value["package"] in PACKAGES, "unknown package")
    validate_pin(value["previous"])
    validate_pin(value["selected"])
    require(version_tuple(value["selected"]["version"]) > version_tuple(value["previous"]["version"]),
            "proposal must advance the selected version")
    return value


def inspect(packages):
    proposals = []
    for package in packages:
        current = json.loads((ROOT / "releases" / f"{package}.json").read_text())
        release = api(f"repos/{PACKAGES[package][0]}/releases/latest")
        value = candidate(package, current, release)
        print(f"{package}: {current['version']} -> "
              f"{value['selected']['version'] if value else 'unchanged (digest verified)'}", file=sys.stderr)
        if value:
            proposals.append(value)
    return proposals


def contents(repo, path, ref):
    data = api(f"repos/{repo}/contents/{path}?ref={urllib.parse.quote(ref, safe='')}")
    require(data.get("type") == "file" and data.get("encoding") == "base64", "expected regular metadata file")
    return data, validate_pin(json.loads(base64.b64decode(data["content"])))


def publish(value):
    # 1. Validate the proposal and expected repository/workflow context.
    value = validate_candidate(value)
    package, previous, selected = value["package"], value["previous"], value["selected"]
    repo = os.environ["GITHUB_REPOSITORY"]
    require(repo == "engimatic-systems/nix-engimatic-pkgs", "unexpected destination repository")
    require(os.environ.get("GITHUB_EVENT_NAME") in {"schedule", "workflow_dispatch"},
            "publisher only runs from scheduled or manual workflows")

    # 2. Leave any open update PR for this package untouched.
    prefix = f"automation/update-{package}-"
    pages = api(f"repos/{repo}/pulls?state=open&per_page=100", paginate=True)
    if any(pull["head"]["ref"].startswith(prefix)
           and (pull["head"].get("repo") or {}).get("full_name") == repo
           for page in pages for pull in page):
        print(f"{package}: existing update PR left untouched")
        return

    # 3. Confirm the base commit and previous pin still match discovery.
    base = api(f"repos/{repo}")["default_branch"]
    base_ref = api(f"repos/{repo}/git/ref/heads/{base}")
    base_sha = base_ref["object"]["sha"]
    require(base_sha == os.environ["GITHUB_SHA"],
            "default branch moved since discovery; rerun the workflow")
    path = f"releases/{package}.json"
    file_data, base_pin = contents(repo, path, base_sha)
    require(base_pin == previous, "base selection changed; rediscover the release")

    # 4. Create a fresh versioned branch from the checked base commit.
    # Creation fails if this branch exists. Never reuse or overwrite a proposal.
    branch = prefix + selected["version"]
    api(f"repos/{repo}/git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": base_sha})

    # 5. Commit only the selected version/hash metadata on that branch.
    api(f"repos/{repo}/contents/{path}", "PUT", {
        "message": f"Update {package} to {selected['version']}", "branch": branch,
        "sha": file_data["sha"], "content": base64.b64encode(encode_pin(selected).encode()).decode(),
    })

    # 6. Open the PR with evidence and the human CI approval instructions.
    release_url, asset_url = release_urls(package, selected["version"])
    body = (f"Update {package} from {previous['version']} to {selected['version']}.\n\n"
            f"[Upstream release notes]({release_url}) · [Official archive]({asset_url})\n\n"
            f"Archive downloaded and SHA-256 checked against the upstream GitHub asset digest.\n"
            f"Pinned SRI: `{selected['hash']}`\n\n"
            "No downloaded code was executed during discovery or PR creation. "
            "Approve the PR workflows to run the offline package checks, then review "
            "the release before merging. Digest verification establishes byte identity, "
            "not upstream safety. A merge does not deploy any host.\n")
    pull = api(f"repos/{repo}/pulls", "POST", {
        "title": f"Update {package} to {selected['version']}", "body": body, "head": branch, "base": base,
    })
    print(pull["html_url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="download/hash official assets and print proposals; no writes")
    check.add_argument("package", choices=["all", *PACKAGES], default="all", nargs="?")
    check.add_argument("--github-output", action="store_true")
    commands.add_parser("publish", help="publish the validated PROPOSAL environment value from Actions")
    args = parser.parse_args()
    if args.command == "check":
        result = inspect(list(PACKAGES) if args.package == "all" else [args.package])
        encoded = json.dumps(result, separators=(",", ":"))
        print(encoded)
        if args.github_output:
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"proposals={encoded}\n")
    else:
        publish(json.loads(os.environ["PROPOSAL"]))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        # Avoid dumping subprocess payloads or authentication environment values.
        print(f"Update failed: {error}", file=sys.stderr)
        sys.exit(1)
