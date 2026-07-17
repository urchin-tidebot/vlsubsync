# VLSubSync

A standalone VLC Lua extension that adds a **Resync current subtitles** button. It aligns the most likely external subtitle beside the playing media using [ffsubsync](https://github.com/smacke/ffsubsync), writes a corrected subtitle without modifying the original, and loads it into VLC.

VLSubSync does **not** modify or depend on VLSub. Download or load subtitles normally, then open VLSubSync from VLC's extension menu.

## V1 behavior

1. Reads the current local media path from VLC.
2. Finds related `.srt`, `.ass`, `.ssa`, or `.vtt` files beside the media.
3. Prefers an exact filename match, then the selected VLC 4 subtitle-track name, then the newest related file.
4. Refuses to guess if equally plausible candidates remain.
5. Runs `ffs` and writes `<subtitle>.synced.<ext>`.
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

## Install from the Nix flake

Add the package to your profile or Home Manager packages:

```bash
nix profile install .
```

The package provides:

- `bin/vlsubsync-helper`
- `share/vlc/lua/extensions/vlsubsync.lua`

If VLC does not discover profile-provided extension data on your setup, symlink the extension into the per-user directory:

```bash
mkdir -p ~/.local/share/vlc/lua/extensions
ln -s "$(nix build --no-link --print-out-paths)/share/vlc/lua/extensions/vlsubsync.lua" \
  ~/.local/share/vlc/lua/extensions/vlsubsync.lua
```

## Portable per-user install

With Python, `ffs`, and FFmpeg already on `PATH`:

```bash
./scripts/install-user
```

Restart VLC, then choose **View → VLSubSync** and click **Resync current subtitles**. Depending on the desktop integration, VLC extensions may instead appear under **Tools → Plugins and extensions**.

Synchronization analyzes the media's audio and commonly takes tens of seconds. Playback can continue while it runs, although the extension dialog remains busy.

## Safety

- Original subtitle files are never overwritten.
- Previously generated `.synced` files are excluded from candidate discovery.
- Ambiguous candidates produce an error instead of a guess.
- Only local media files are supported in V1.

## Development

```bash
nix flake check
nix build
```

The helper tests use Python's standard-library `unittest`; Lua tests run against Lua 5.1, matching VLC's embedded Lua version.

## License

VLSubSync is MIT licensed. `ffsubsync` is a separate MIT-licensed dependency. VLC is distributed under GPL/LGPL terms depending on the component.
