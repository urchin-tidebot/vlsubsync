# VLSubSync

A standalone VLC Lua extension that adds a **Resync current subtitles** button. It aligns the most likely external subtitle beside the playing media using [ffsubsync](https://github.com/smacke/ffsubsync), writes a corrected subtitle without modifying the original, and loads it into VLC.

VLSubSync does **not** modify or depend on VLSub. Download or load subtitles normally, then open VLSubSync from VLC's extension menu.

## V1 behavior

1. Reads the current local media path from VLC.
2. Finds related `.srt`, `.ass`, `.ssa`, or `.vtt` files beside the media.
3. Prefers an exact filename match, then the selected VLC 4 subtitle-track name, then the newest related file.
4. Refuses to guess if equally plausible candidates remain.
5. Runs `ffs`, writes `<subtitle>.synced.<ext>` into a private per-user cache directory, and atomically publishes it without replacing existing filesystem objects.
6. Loads the corrected subtitle into VLC while preserving the original.

VLC 3 does not expose selected subtitle-track metadata to Lua, so filename and modification time are used there. VLC 4 also uses the selected track name when available.

## Requirements

- Linux (V1 target)
- VLC 3 or 4
- Python 3.10+
- `ffsubsync` (`ffs` command)
- FFmpeg

## Try without installing

```bash
nix develop
python -m unittest discover -s tests -v
lua tests/test_extension.lua
```

## Home Manager (recommended)

Add VLSubSync as a flake input and follow your existing `nixpkgs`:

```nix
{
  inputs.vlsubsync = {
    url = "github:urchin-tidebot/vlsubsync";
    inputs.nixpkgs.follows = "nixpkgs";
  };
}
```

Import the module in your Home Manager configuration and enable it:

```nix
{ inputs, ... }:
{
  imports = [ inputs.vlsubsync.homeManagerModules.default ];

  programs.vlsubsync.enable = true;
}
```

For Home Manager embedded in a NixOS configuration:

```nix
{
  home-manager.users.shazow = {
    imports = [ inputs.vlsubsync.homeManagerModules.default ];
    programs.vlsubsync.enable = true;
  };
}
```

The module installs the helper and declaratively links the extension to
`$XDG_DATA_HOME/vlc/lua/extensions/vlsubsync.lua`. The Nix-built extension
contains the helper's absolute store path, so desktop-launched VLC does not
need to inherit a particular `PATH`.

To override the package:

```nix
programs.vlsubsync.package = inputs.vlsubsync.packages.${pkgs.system}.vlsubsync;
```

### Without adding a flake input

You can fetch the repository from an ordinary Home Manager module and wire the
package and VLC extension directly. Because `callPackage` uses your existing
`pkgs`, VLSubSync reuses the same `pkgs.ffmpeg`, `pkgs.ffsubsync`, and
`pkgs.python3` derivations selected by your configuration:

```nix
{ pkgs, ... }:

let
  src = pkgs.fetchFromGitHub {
    owner = "urchin-tidebot";
    repo = "vlsubsync";
    rev = "d7902ae177753b50e435389b38416001dd1dd3f9";
    hash = "sha256-wuTXphIeYBQEbbykwX7WxrfRw17io8y1uJFmKPwGkIg=";
  };

  vlsubsync = pkgs.callPackage "${src}/nix/package.nix" {
    inherit src;
  };
in
{
  home.packages = [
    pkgs.vlc
    pkgs.ffmpeg
    vlsubsync
  ];

  xdg.dataFile."vlc/lua/extensions/vlsubsync.lua".source =
    "${vlsubsync}/share/vlc/lua/extensions/vlsubsync.lua";
}
```

Update `rev` and `hash` together when upgrading. Importing `package.nix` from a
`fetchFromGitHub` result uses import-from-derivation, which must be enabled in
the evaluating Nix configuration.

## Other flake outputs

The flake also exports:

- `packages.<system>.default` and `packages.<system>.vlsubsync`
- `overlays.default`, which adds `pkgs.vlsubsync`
- `homeManagerModules.default` and `homeManagerModules.vlsubsync`

Package-only installation is available:

```bash
nix profile install github:urchin-tidebot/vlsubsync
```

However, VLC does not consistently scan profile-provided data directories for
Lua extensions. Prefer the Home Manager module, or manually link the packaged
extension into the per-user VLC extension directory.

## Portable per-user install

With Python, `ffs`, and FFmpeg already on `PATH`:

```bash
./scripts/install-user
```

The installer resolves and records the absolute Python, `ffs`, and FFmpeg paths, constructs a minimal runtime `PATH`, and refuses symlinked installation directories or destination files. It intentionally supports only user-owned directories that are not writable by group or others under `~/.local`. Because dependency selection happens at installation time, run the installer only with a trusted `PATH`.

Restart VLC, then choose **View → VLSubSync** and click **Resync current subtitles**. Depending on the desktop integration, VLC extensions may instead appear under **Tools → Plugins and extensions**.

Synchronization analyzes the media's audio and commonly takes tens of seconds. Playback can continue while it runs, although the extension dialog remains busy.

## Safety

- Media and subtitle inputs must be ordinary files; symbolic links, FIFOs, devices, and other special files are rejected.
- Subtitle content is copied into the private cache before parsing, and the media inode is pinned through an open file descriptor during synchronization.
- Original subtitle files are never overwritten. Generated output is published atomically without replacing any existing file, symlink, or other object.
- Subtitle and generated-output sizes, helper diagnostics, and Lua protocol responses are bounded; synchronization is terminated after 15 minutes.
- Previously generated `.synced` files are excluded from candidate discovery.
- Ambiguous candidates produce an error instead of a guess.
- Only local media files are supported in V1.

`ffmpeg` and `ffsubsync` still parse untrusted media and subtitle content. Keep those dependencies updated. VLSubSync constrains their inputs, output, runtime, diagnostics, and lingering child processes, but it does not place them in an OS-level privilege sandbox; a successful parser code-execution vulnerability would therefore run with the user's access. Use an externally sandboxed VLC/helper environment when processing media that requires stronger isolation.

## Development

```bash
nix flake check
nix build
```

The helper tests use Python's standard-library `unittest`; Lua tests run against Lua 5.1, matching VLC's embedded Lua version.

## License

VLSubSync is MIT licensed. `ffsubsync` is a separate MIT-licensed dependency. VLC is distributed under GPL/LGPL terms depending on the component.
