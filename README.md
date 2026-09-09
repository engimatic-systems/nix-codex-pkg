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

For now, update the selected version and hash in `releases/<package>.json`,
verify the downloaded archive against the official release asset digest, and
run the builds/checks above. A hash establishes byte identity, not upstream
safety. Review release notes before adopting a new selection.

Restore the previous metadata commit to undo a package selection. Consumers
must separately restore their prior dependency lock and deploy the previous
host generation to roll back an installed update.

CI builds and checks the packages but publishes no binary cache. Nixpkgs
dependencies may come from the normal NixOS cache; custom package outputs are
built from the pinned official archives on each consumer unless an explicitly
trusted cache is configured.
