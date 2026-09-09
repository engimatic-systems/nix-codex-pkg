# nix-engimatic-pkgs

Official Codex and Pi release bundles packaged for **x86_64 Linux** with Nix.
This repository was formerly named `nix-codex-pkg`. The `codex` and `default`
outputs retain their existing meaning; `pi` exposes the Pi coding agent.

## Build and try

Requires Nix with `nix-command` and `flakes` enabled:

```sh
nix build .#pi --no-update-lock-file
./result/bin/pi --version
nix run .#pi --no-update-lock-file -- --help
nix build .#codex --no-update-lock-file
nix flake check --no-update-lock-file --print-build-logs
```

Building adds an immutable package to `/nix/store`; running executes it without
installing it into your normal `PATH`. Neither operation switches NixOS.

## Packaging and verification

`codex.nix` packages Codex; `pi.nix` packages Pi. `releases/codex.json` and
`releases/pi.json` select exact versions and archive SHA-256 hashes. Both
recipes fetch only the designated official upstream release archives.
`flake.lock` separately pins Nixpkgs and the packaging tools/runtime libraries.
These packages adapt upstream binaries; they do not compile the agents from
source or install packages through npm.

Codex retains its helpers, bundled tools, resources, and shell completions.
Its checks verify the CLI version, helper startup, ripgrep, bubblewrap, bundled
zsh, package metadata, and completions.

Pi preserves the complete standalone release under `libexec/pi`, including
themes, HTML export assets, image WASM, documentation, examples, and its native
clipboard addon. The wrapper supplies Bash, ripgrep, and fd and sets
`PI_PACKAGE_DIR`. ELF dependencies are patched for Nix; stripping is disabled
to preserve the standalone executable's embedded payload. Checks verify CLI
startup/version, metadata, required resources, and native addon loading.

Pi's version checks and install telemetry default off; updates belong to this
flake. Users can explicitly override `PI_SKIP_VERSION_CHECK` or `PI_TELEMETRY`.
`PI_OFFLINE=1` additionally disables startup network operations when desired.

Installation checks run offline without credentials or model requests. They
do not establish authenticated model access, graphical clipboard operation,
or the suitability of every extension. Authentication, sessions, settings,
and project tools remain user-local. A fresh Pi session can use `/login`.

## Consume from NixOS

Add an input to your existing flake:

```nix
inputs.engimatic-pkgs.url = "github:engimatic-systems/nix-engimatic-pkgs";
```

Accept `engimatic-pkgs` in `outputs`, then select packages in a host module:

```nix
({ pkgs, ... }: {
  environment.systemPackages = [
    engimatic-pkgs.packages.${pkgs.stdenv.hostPlatform.system}.codex
    engimatic-pkgs.packages.${pkgs.stdenv.hostPlatform.system}.pi
  ];
})
```

Packages use this repository's locked Nixpkgs independently of the host's OS
selection. Only `x86_64-linux` is currently supported. Existing consumers can
keep the local input name `codex-pkg` while updating its repository URL.

The consumer's lock records an exact package-repository revision. To adopt
updates, run `nix flake update engimatic-pkgs` in the consuming repository,
review that lock change, build, and follow the host's normal deployment path.
A package PR merge alone changes no consumer lock or running host. Check
`command -v pi` / `pi --version` and the corresponding Codex commands after
deployment for older npm installs or shims taking precedence.

## Update and recover

The **Propose release updates** workflow runs daily at 09:23 UTC or manually
from the Actions page on the default branch. GitHub schedules are best-effort;
a manual run provides the same behavior. It uses the repository's built-in
`GITHUB_TOKEN`; no separate bot account, personal token, or GitHub App is needed.

Keep organization/repository token defaults read-only and enable **Allow GitHub
Actions to create and approve pull requests**. Only the PR-writing job requests
`contents: write` and `pull-requests: write`. It never approves or merges PRs.

The read-only discovery job queries each official repository's latest stable
release, checks the expected tag and archive URL, downloads the archive without
extracting or running it, and compares its SHA-256 against GitHub's release asset
digest. Missing digests/assets, prereleases, downgrades, digest mismatches, and
changed bytes for the currently selected release fail for manual investigation.

The separate writer validates the small version/hash proposal again and writes
only `releases/<package>.json` on `automation/update-<package>`. It opens or
refreshes one PR per package with upstream links and digest evidence. It
preserves branch ancestry and constructs the candidate from current main plus
that one metadata file, including when an earlier update was squash-merged.
Non-metadata edits on an update branch stop automation for manual review.
Neither job builds or executes the proposed binaries, and no candidate code is
checked out by the writer. Actions are pinned to commits.

**Human approval before CI is intentional.** PRs created or updated with
`GITHUB_TOKEN` cause the `pull_request` checks to wait for approval. Select
**Approve workflows to run** on the PR, inspect the offline checks and upstream
release notes, then separately decide whether to merge. Do not replace the
token or add workflow dispatch to bypass this gate. See
[GitHub's workflow-trigger contract](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow).
A matching hash establishes byte identity, not upstream safety.

For a read-only local check (Python 3.10+ and authenticated `gh`):

```sh
python3 scripts/update_releases.py check all
python3 scripts/update_releases.py check pi
python3 -m unittest discover -s tests -v
```

This prints proposed metadata and verifies downloads without changing files or
creating PRs. You can copy a reviewed selection into `releases/<package>.json`
and run the builds above for a manual update. No-op runs still verify the
currently selected release digest. Repeating a pending proposal creates no
extra commit or PR; interrupted PR creation can recover on the next run.

If main moved during discovery, rerun. If an update branch has manual edits or
a conflicting hash, inspect and reconcile it before rerunning; automation will
not force-overwrite it. Close the PR and delete its update branch to start
fresh after preserving any needed work. Closing alone does not suppress a
release: the next run proposes it again. Disable the update workflow while
investigating a release you do not want to adopt.

Restore the previous metadata commit to undo a package selection. Consumers
must separately restore their prior dependency lock and deploy the previous
host generation to roll back an installed update.

CI builds and checks the packages but publishes no binary cache. Nixpkgs
dependencies may come from the normal NixOS cache; custom package outputs are
built from the pinned official archives on each consumer unless an explicitly
trusted cache is configured.
