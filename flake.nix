{
  description = "One-click subtitle synchronization for VLC";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      overlays.default = final: _prev: {
        vlsubsync = final.callPackage ./nix/package.nix { src = self; };
      };

      homeManagerModules = {
        default = import ./nix/home-manager.nix;
        vlsubsync = self.homeManagerModules.default;
      };

      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        rec {
          default = vlsubsync;
          vlsubsync = pkgs.callPackage ./nix/package.nix { src = self; };
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          unit =
            pkgs.runCommand "vlsubsync-tests"
              {
                nativeBuildInputs = with pkgs; [
                  python3
                  lua5_1
                ];
              }
              ''
                cp -r ${self} source
                chmod -R u+w source
                cd source
                python -m unittest discover -s tests -v
                lua tests/test_extension.lua
                touch "$out"
              '';

          home-manager = import ./nix/tests/home-manager.nix {
            inherit pkgs home-manager;
            module = self.homeManagerModules.default;
          };

          overlay =
            let
              overlayPkgs = import nixpkgs {
                inherit system;
                overlays = [ self.overlays.default ];
              };
              fakeFfsubsync = pkgs.runCommand "fake-ffsubsync" { } ''
                mkdir -p "$out/bin"
                touch "$out/bin/ffs"
                chmod +x "$out/bin/ffs"
              '';
              composedPkgs = import nixpkgs {
                inherit system;
                overlays = [
                  (_final: _prev: { ffsubsync = fakeFfsubsync; })
                  self.overlays.default
                ];
              };
            in
            assert overlayPkgs.vlsubsync == self.packages.${system}.vlsubsync;
            assert self.packages.${system}.default == self.packages.${system}.vlsubsync;
            pkgs.runCommand "vlsubsync-overlay-test" { } ''
              test -x ${overlayPkgs.vlsubsync}/bin/vlsubsync-helper
              grep -R -F '${fakeFfsubsync}/bin' ${composedPkgs.vlsubsync}/bin
              touch "$out"
            '';
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);

      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.mkShell {
          packages = with nixpkgs.legacyPackages.${system}; [
            ffmpeg
            ffsubsync
            lua5_1
            python3
            shellcheck
            vlc
          ];
        };
      });
    };
}
