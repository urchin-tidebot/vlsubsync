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

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    substituteInPlace vlsubsync \
      --replace-fail '#!/usr/bin/env python3' '#!${python3}/bin/python3'
    install -Dm755 vlsubsync "$out/bin/vlsubsync"
    wrapProgram "$out/bin/vlsubsync" \
      --set VLSUBSYNC_FFS ${ffsubsync}/bin/ffs \
      --set PATH ${lib.makeBinPath [ ffmpeg ]}

    install -Dm644 extension/vlsubsync.lua \
      "$out/share/vlc/lua/extensions/vlsubsync.lua"
    substituteInPlace "$out/share/vlc/lua/extensions/vlsubsync.lua" \
      --replace-fail 'local packaged_cli = nil' \
      "local packaged_cli = \"$out/bin/vlsubsync\""
    runHook postInstall
  '';

  meta = {
    description = "One-click synchronization of VLC's current subtitles";
    homepage = "https://github.com/urchin-tidebot/vlsubsync";
    license = lib.licenses.mit;
    mainProgram = "vlsubsync";
    platforms = lib.platforms.linux;
  };
}
