{
  description = "One-click subtitle synchronization for VLC";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "vlsubsync";
            version = "0.1.0";
            src = self;
            nativeBuildInputs = [ pkgs.makeWrapper ];

            buildPhase = ''
              runHook preBuild
              # Nix normalizes source mtimes to the Unix epoch, but ZIP requires 1980+.
              touch -d '1980-01-02 UTC' vlsubsync/__init__.py vlsubsync/helper.py
              ${pkgs.python3}/bin/python -m zipapp vlsubsync \
                -m 'helper:main' -o vlsubsync-helper.pyz
              runHook postBuild
            '';

            installPhase = ''
              runHook preInstall
              install -Dm644 vlsubsync.lua \
                "$out/share/vlc/lua/extensions/vlsubsync.lua"
              install -Dm644 vlsubsync-helper.pyz \
                "$out/libexec/vlsubsync-helper.pyz"
              makeWrapper ${pkgs.python3}/bin/python "$out/bin/vlsubsync-helper" \
                --add-flags "$out/libexec/vlsubsync-helper.pyz" \
                --prefix PATH : ${
                  pkgs.lib.makeBinPath [
                    pkgs.ffsubsync
                    pkgs.ffmpeg
                  ]
                }
              runHook postInstall
            '';

            meta = {
              description = "One-click synchronization of VLC's current subtitles";
              homepage = "https://github.com/urchin-tidebot/vlsubsync";
              license = pkgs.lib.licenses.mit;
              mainProgram = "vlsubsync-helper";
              platforms = pkgs.lib.platforms.linux;
            };
          };
        }
      );

      checks = forAllSystems (system: {
        unit =
          nixpkgs.legacyPackages.${system}.runCommand "vlsubsync-tests"
            {
              nativeBuildInputs = with nixpkgs.legacyPackages.${system}; [
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
      });

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
