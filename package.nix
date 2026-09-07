{
  lib,
  stdenvNoCC,
  fetchurl,
  autoPatchelfHook,
  installShellFiles,
  ncurses,
  jq,
}:

stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "codex";
  version = "0.153.4";

  src = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rust-v${finalAttrs.version}/codex-package-x86_64-unknown-linux-musl.tar.gz";
    hash = "sha256-qCIYfhokIMYcWSZyG/vYeHAe2VVHybsNTeRJiha6GCE=";
  };

  sourceRoot = ".";
  dontBuild = true;
  # Preserve upstream static binaries; only patch dynamic runtime dependencies.
  dontStrip = true;
  strictDeps = true;

  nativeBuildInputs = [
    autoPatchelfHook
    installShellFiles
  ];
  buildInputs = [ ncurses ];
  nativeInstallCheckInputs = [ jq ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    # Codex discovers helpers and resources relative to this package layout.
    cp -a bin codex-package.json codex-path codex-resources "$out/"
    installShellCompletion --cmd codex \
      --bash <("$out/bin/codex" completion bash) \
      --fish <("$out/bin/codex" completion fish) \
      --zsh <("$out/bin/codex" completion zsh)
    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME="$TMPDIR/codex-check-home"
    mkdir -p "$HOME"

    test "$("$out/bin/codex" --version)" = "codex-cli ${finalAttrs.version}"
    "$out/bin/codex" --help > /dev/null
    "$out/bin/codex-code-mode-host" --help > /dev/null
    "$out/codex-path/rg" --version
    "$out/codex-resources/bwrap" --version
    "$out/codex-resources/zsh/bin/zsh" -f -c 'test "$((6 * 7))" = 42'

    jq -e --arg version "${finalAttrs.version}" '
      .layoutVersion == 1 and .version == $version and
      .target == "x86_64-unknown-linux-musl" and .variant == "codex" and
      .entrypoint == "bin/codex" and
      .resourcesDir == "codex-resources" and .pathDir == "codex-path"
    ' "$out/codex-package.json" > /dev/null

    test -s "$out/share/bash-completion/completions/codex.bash"
    test -s "$out/share/fish/vendor_completions.d/codex.fish"
    test -s "$out/share/zsh/site-functions/_codex"
    runHook postInstallCheck
  '';

  meta = {
    description = "Codex CLI with its official prebuilt helpers and resources";
    homepage = "https://github.com/openai/codex";
    license = lib.licenses.asl20;
    platforms = [ "x86_64-linux" ];
    mainProgram = "codex";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
})
