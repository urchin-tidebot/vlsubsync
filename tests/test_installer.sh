#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT

fake_bin="$tmp/fake-bin"
mkdir -p "$fake_bin"
ln -s "$(command -v python3)" "$fake_bin/python3"
printf '#!/usr/bin/env bash\nexit 0\n' > "$fake_bin/ffs"
printf '#!/usr/bin/env bash\nexit 0\n' > "$fake_bin/ffmpeg"
chmod +x "$fake_bin/ffs" "$fake_bin/ffmpeg"
test_path="$fake_bin:$PATH"

home="$tmp/home"
mkdir -p "$home/.local/bin"

sentinel="$tmp/sentinel"
printf 'safe\n' > "$sentinel"
ln -s "$sentinel" "$home/.local/bin/vlsubsync"

if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a symlinked CLI destination\n' >&2
  exit 1
fi

test "$(cat "$sentinel")" = safe

rm -rf -- "$home"
mkdir -p "$home/.local/bin" "$home/.local/share/vlc/lua/extensions"
ln -s "$sentinel" "$home/.local/share/vlc/lua/extensions/vlsubsync.lua"

if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a symlinked extension destination\n' >&2
  exit 1
fi

test "$(cat "$sentinel")" = safe

rm -rf -- "$home" "$tmp/outside-lua"
mkdir -p "$home/.local/bin" "$home/.local/share/vlc" "$tmp/outside-lua"
ln -s "$tmp/outside-lua" "$home/.local/share/vlc/lua"

if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a symlinked extension directory\n' >&2
  exit 1
fi

test ! -e "$tmp/outside-lua/extensions/vlsubsync.lua"

rm -rf -- "$home"
mkdir -p "$home/.local" "$tmp/outside"
ln -s "$tmp/outside" "$home/.local/bin"

if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a symlinked parent directory\n' >&2
  exit 1
fi

test ! -e "$tmp/outside/vlsubsync"

rm -rf -- "$home"
mkdir -m 0700 -- "$home"
chmod 0777 "$home"
if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a group/world-writable HOME\n' >&2
  exit 1
fi

rm -rf -- "$home"
mkdir -m 0700 -- "$home"
HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null
if [[ -x /usr/bin/env ]]; then
  "$home/.local/bin/vlsubsync" --help >/dev/null
else
  python3 "$home/.local/bin/vlsubsync" --help >/dev/null
fi
test "$(stat -c %a -- "$home/.local/bin/vlsubsync")" = 700
test "$(stat -c %a -- "$home/.local/share/vlc/lua/extensions/vlsubsync.lua")" = 600
cmp -s "$repo_dir/vlsubsync" "$home/.local/bin/vlsubsync"
cmp -s "$repo_dir/extension/vlsubsync.lua" \
  "$home/.local/share/vlc/lua/extensions/vlsubsync.lua"
IFS= read -r cli_shebang < "$home/.local/bin/vlsubsync"
test "$cli_shebang" = '#!/usr/bin/env python3'
test ! -e "$home/.local/libexec/vlsubsync"
printf 'installer security tests passed\n'
