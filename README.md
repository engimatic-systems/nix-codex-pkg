# nix-codex-pkg

The official Codex CLI release bundle, packaged for **x86_64 Linux** with Nix.
The package includes the CLI, code-mode helper, bundled tools and resources,
and shell completions. It does not compile Codex from source.

## Build and try it

Requires Nix with `nix-command` and `flakes` enabled. From a checkout:

```sh
nix build .#codex --no-update-lock-file
./result/bin/codex --version
nix run .#codex --no-update-lock-file -- --help
nix flake check --no-update-lock-file --print-build-logs
```

`nix build` creates an immutable package in `/nix/store` and a `result` symlink
to it. `nix run` executes that package without installing it into your normal
shell's `PATH`. Neither command switches the NixOS configuration.

## How the package works

- `package.nix` is the build recipe, called a **derivation**. It selects the
  Codex version, downloads an archive with an exact SHA-256, preserves the
  upstream directory layout, and patches dynamic ELF dependencies for Nix.
- `flake.nix` exposes that recipe as `packages.x86_64-linux.codex` and
  `packages.x86_64-linux.default`. Both names refer to the same package.
- `flake.lock` pins Nixpkgs, which supplies the build tools and runtime
  libraries. The release hash pins the downloaded archive; the lock file pins
  the tools used to package it.

The bundle contains static and dynamic executables. In particular, its bundled
zsh needs Nix's loader and ncurses libraries. `autoPatchelfHook` repairs dynamic
dependencies; `dontStrip` preserves the upstream static binaries. Installing
only `bin/codex` would discard its helper and resource layout.

Installation checks run without credentials or model requests. They verify the
CLI version, launch the helper, ripgrep, and bubblewrap, execute a command in
bundled zsh, and check package metadata and completions. These checks establish
that the bundled programs start; an authenticated agent task and actual sandbox
operation still require testing on the intended host.

## Use it from NixOS

For a NixOS configuration already using flakes, add this input to its existing
`inputs` attribute set. The repository is private, so fetching it requires
GitHub access; this example uses SSH authentication.

```nix
inputs.codex-pkg.url =
  "git+ssh://git@github.com/engimatic-systems/nix-codex-pkg?ref=main";
```

Accept `codex-pkg` in the existing flake's `outputs` function, then add an inline
module to the selected host's `nixosSystem.modules` list:

```nix
({ pkgs, ... }: {
  environment.systemPackages = [
    codex-pkg.packages.${pkgs.stdenv.hostPlatform.system}.codex
  ];
})
```

This consumes the package built with **this repository's locked Nixpkgs**,
even if the host uses another Nixpkgs revision. Unsupported architectures have
no package output. This first milestone provides a package, not a host module.

The consuming flake's lock file records the exact package-repository revision.
Following `main` in the input URL does not make an existing lock auto-update.
When intentionally upgrading, run `nix flake update codex-pkg` in that consuming
repository, review its lock change, and use its normal NixOS deployment path.

Existing npm installs, mise shims, or standalone copies can take precedence over
the system package. Check both `command -v codex` and `codex --version` in the
intended user's shell after deployment. Authentication, user configuration,
sessions, and project tools remain outside this package.

## How it gets distributed

This Git repository distributes the **recipe and pinned inputs**. A consumer
with access fetches the recipe, and Nix either substitutes the resulting store
path from a configured trusted binary cache or builds it. Here, building means
downloading and adapting the pinned upstream binary bundle.

The CI workflow builds and checks the package on Linux. It does **not** publish
a binary cache. Upstream Nixpkgs dependencies can use the normal NixOS cache;
do not assume that this custom Codex output is available there. A future cache
could distribute the package and its runtime dependencies without each host
repackaging the archive.

To change the release today, update `version` and `src.hash` in `package.nix`,
then run the build and checks above. Verify the archive's SHA-256 against the
upstream release asset digest before adopting it.

Automated release updates, publication of passing revisions, and sys deployment
records are subsequent work. They will let sys select a published package
without routine pin edits in sys; that deployment mechanism is not implemented
by this first package PR.
