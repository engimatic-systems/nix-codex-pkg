{
  description = "The official Codex CLI bundle packaged for Nix";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      codex = pkgs.callPackage ./package.nix { };
    in
    {
      packages.${system} = {
        inherit codex;
        default = codex;
      };

      # Building the package runs its offline installation checks.
      checks.${system}.codex = codex;
    };
}
