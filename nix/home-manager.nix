{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.vlsubsync;
  defaultPackage = pkgs.callPackage ./package.nix { src = ../.; };
in
{
  options.programs.vlsubsync = {
    enable = lib.mkEnableOption "VLSubSync, one-click subtitle synchronization for VLC";

    package = lib.mkOption {
      type = lib.types.package;
      default = defaultPackage;
      description = "The VLSubSync package to install and expose to the VLC extension.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    xdg.dataFile."vlc/lua/extensions/vlsubsync.lua".source =
      "${cfg.package}/share/vlc/lua/extensions/vlsubsync.lua";
  };
}
