{
  lib,
  stdenvNoCC,
  fetchurl,
  autoPatchelfHook,
  makeWrapper,
  stdenv,
  bash,
  ripgrep,
  fd,
  jq,
  nodejs,
}:

let
  release = builtins.fromJSON (builtins.readFile ./releases/pi.json);
in
stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "pi";
  inherit (release) version;

  src = fetchurl {
    url = "https://github.com/earendil-works/pi/releases/download/v${finalAttrs.version}/pi-linux-x64.tar.gz";
    inherit (release) hash;
  };

  sourceRoot = "pi";
  dontBuild = true;
  # Bun's standalone executable includes an appended application payload.
  dontStrip = true;
  strictDeps = true;
  nativeBuildInputs = [ autoPatchelfHook makeWrapper ];
  buildInputs = [ stdenv.cc.cc.lib ];
  nativeInstallCheckInputs = [ jq nodejs ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/libexec/pi" "$out/bin"
    cp -a . "$out/libexec/pi/"
    makeWrapper "$out/libexec/pi/pi" "$out/bin/pi" \
      --prefix PATH : ${lib.makeBinPath [ bash ripgrep fd ]} \
      --set PI_PACKAGE_DIR "$out/libexec/pi" \
      --set-default PI_SKIP_VERSION_CHECK 1 \
      --set-default PI_TELEMETRY 0
    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME="$TMPDIR/pi-check-home"
    export PI_OFFLINE=1
    mkdir -p "$HOME"
    test "$("$out/bin/pi" --version)" = "${finalAttrs.version}"
    "$out/bin/pi" --help > /dev/null
    jq -e --arg version "${finalAttrs.version}" \
      '.name == "@earendil-works/pi-coding-agent" and .version == $version' \
      "$out/libexec/pi/package.json" > /dev/null
    test -s "$out/libexec/pi/photon_rs_bg.wasm"
    test -s "$out/libexec/pi/theme/dark.json"
    test -s "$out/libexec/pi/export-html/template.html"
    test -s "$out/libexec/pi/docs/extensions.md"
    test -d "$out/libexec/pi/examples"
    # Exercise the native addon loader without needing a graphical clipboard.
    node -e 'require(process.argv[1])' \
      "$out/libexec/pi/node_modules/@mariozechner/clipboard/clipboard.linux-x64-gnu.node"
    runHook postInstall
  '';

  meta = {
    description = "Pi coding agent with its official standalone release resources";
    homepage = "https://pi.dev/";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "pi";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
})
