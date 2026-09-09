{
  description = "Official tool releases packaged for Nix by Engimatic Systems";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      codex = pkgs.callPackage ./codex.nix { };
      pi = pkgs.callPackage ./pi.nix { };
    in
    {
      packages.${system} = {
        inherit codex pi;
        default = codex;
      };

      # Building the package runs its offline installation checks.
      checks.${system} = { inherit codex pi; };
    };
}
