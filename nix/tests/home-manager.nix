{
  pkgs,
  home-manager,
  module,
}:
let
  configuration = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    modules = [
      module
      {
        home = {
          username = "vlsubsync-test";
          homeDirectory = "/home/vlsubsync-test";
          stateVersion = "24.11";
        };
        programs.vlsubsync.enable = true;
      }
    ];
  };

  cfg = configuration.config;
  package = cfg.programs.vlsubsync.package;
  extension = cfg.xdg.dataFile."vlc/lua/extensions/vlsubsync.lua";

  customPackage = pkgs.runCommand "custom-vlsubsync" { } ''
    mkdir -p "$out/share/vlc/lua/extensions"
    touch "$out/share/vlc/lua/extensions/vlsubsync.lua"
  '';
  customConfiguration = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    modules = [
      module
      {
        home = {
          username = "vlsubsync-custom-test";
          homeDirectory = "/home/vlsubsync-custom-test";
          stateVersion = "24.11";
        };
        programs.vlsubsync = {
          enable = true;
          package = customPackage;
        };
      }
    ];
  };
  customCfg = customConfiguration.config;
  customExtension = customCfg.xdg.dataFile."vlc/lua/extensions/vlsubsync.lua";

  disabledConfiguration = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    modules = [
      module
      {
        home = {
          username = "vlsubsync-disabled-test";
          homeDirectory = "/home/vlsubsync-disabled-test";
          stateVersion = "24.11";
        };
      }
    ];
  };
  disabledCfg = disabledConfiguration.config;
in
assert package.pname == "vlsubsync";
assert builtins.elem package cfg.home.packages;
assert toString extension.source == "${package}/share/vlc/lua/extensions/vlsubsync.lua";
assert builtins.elem customPackage customCfg.home.packages;
assert toString customExtension.source == "${customPackage}/share/vlc/lua/extensions/vlsubsync.lua";
assert !(builtins.elem disabledCfg.programs.vlsubsync.package disabledCfg.home.packages);
assert !(disabledCfg.xdg.dataFile ? "vlc/lua/extensions/vlsubsync.lua");
pkgs.runCommand "vlsubsync-home-manager-module-test" { } ''
  grep -F 'local packaged_helper = "${package}/bin/vlsubsync-helper"' \
    ${extension.source}
  test -f ${customExtension.source}
  touch "$out"
''
