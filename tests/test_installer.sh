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
chmod 0777 "$fake_bin"
if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted an executable from a writable directory\n' >&2
  exit 1
fi
chmod 0755 "$fake_bin"

sentinel="$tmp/sentinel"
printf 'safe\n' > "$sentinel"
ln -s "$sentinel" "$home/.local/bin/vlsubsync-helper"

if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a symlinked wrapper destination\n' >&2
  exit 1
fi

test "$(cat "$sentinel")" = safe

rm -rf -- "$home"
mkdir -p "$home/.local" "$tmp/outside"
ln -s "$tmp/outside" "$home/.local/bin"

if HOME="$home" PATH="$test_path" bash "$repo_dir/scripts/install-user" >/dev/null 2>&1; then
  printf 'installer unexpectedly accepted a symlinked parent directory\n' >&2
  exit 1
fi

test ! -e "$tmp/outside/vlsubsync-helper"

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
"$home/.local/bin/vlsubsync-helper" --help >/dev/null
test "$(stat -c %a -- "$home/.local/bin/vlsubsync-helper")" = 700
test "$(stat -c %a -- "$home/.local/libexec/vlsubsync/vlsubsync-helper.pyz")" = 600
test "$(stat -c %a -- "$home/.local/share/vlc/lua/extensions/vlsubsync.lua")" = 600
printf 'installer security tests passed\n'
