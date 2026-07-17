{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  ffsubsync,
  ffmpeg,
  src,
}:
stdenvNoCC.mkDerivation {
  pname = "vlsubsync";
  version = "0.1.0";
  inherit src;

  nativeBuildInputs = [ makeWrapper ];

  buildPhase = ''
    runHook preBuild
    # Nix normalizes source mtimes to the Unix epoch, but ZIP requires 1980+.
    touch -d '1980-01-02 UTC' vlsubsync/__init__.py vlsubsync/helper.py
    ${python3}/bin/python -m zipapp vlsubsync \
      -m 'helper:main' -o vlsubsync-helper.pyz
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm644 vlsubsync-helper.pyz \
      "$out/libexec/vlsubsync-helper.pyz"
    makeWrapper ${python3}/bin/python "$out/bin/vlsubsync-helper" \
      --add-flags "$out/libexec/vlsubsync-helper.pyz" \
      --set VLSUBSYNC_FFS ${ffsubsync}/bin/ffs \
      --set PATH ${lib.makeBinPath [ ffmpeg ]}

    install -Dm644 vlsubsync.lua \
      "$out/share/vlc/lua/extensions/vlsubsync.lua"
    substituteInPlace "$out/share/vlc/lua/extensions/vlsubsync.lua" \
      --replace-fail 'local packaged_helper = nil' \
      "local packaged_helper = \"$out/bin/vlsubsync-helper\""
    runHook postInstall
  '';

  meta = {
    description = "One-click synchronization of VLC's current subtitles";
    homepage = "https://github.com/urchin-tidebot/vlsubsync";
    license = lib.licenses.mit;
    mainProgram = "vlsubsync-helper";
    platforms = lib.platforms.linux;
  };
}
