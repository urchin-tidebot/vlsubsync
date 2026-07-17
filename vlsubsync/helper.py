"""Core discovery and synchronization logic for VLSubSync."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
LANGUAGE_ALIASES = {
    "english": "en",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "spanish": "es",
    "portuguese": "pt",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
}
MAX_SUBTITLE_BYTES = 52_428_800
MAX_OUTPUT_BYTES = 52_428_800
MAX_DIAGNOSTIC_BYTES = 65_536
SYNC_TIMEOUT_SECONDS = 900
MAX_OUTPUT_ATTEMPTS = 1_000


class SubtitleDiscoveryError(RuntimeError):
    """No safe subtitle choice could be made."""


class AmbiguousSubtitleError(SubtitleDiscoveryError):
    """More than one subtitle is equally plausible."""


def _absolute_path(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _validate_regular_file(
    path: Path | str,
    label: str,
    *,
    maximum_bytes: int | None = None,
) -> tuple[Path, os.stat_result]:
    path = _absolute_path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SubtitleDiscoveryError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise SubtitleDiscoveryError(f"{label} must not be a symbolic link: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise SubtitleDiscoveryError(f"{label} is not a regular file: {path}")
    if maximum_bytes is not None and metadata.st_size > maximum_bytes:
        raise SubtitleDiscoveryError(
            f"{label} is too large ({metadata.st_size} bytes; limit {maximum_bytes})"
        )
    return path, metadata


def _open_pinned_regular_file(
    path: Path,
    label: str,
    *,
    maximum_bytes: int | None = None,
) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SubtitleDiscoveryError(f"could not safely open {label}: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        current = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise SubtitleDiscoveryError(f"{label} is not a regular file: {path}")
        if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
            raise SubtitleDiscoveryError(
                f"{label} changed while it was being opened: {path}"
            )
        if maximum_bytes is not None and metadata.st_size > maximum_bytes:
            raise SubtitleDiscoveryError(
                f"{label} is too large ({metadata.st_size} bytes; limit {maximum_bytes})"
            )
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _copy_pinned_subtitle(descriptor: int, subtitle: Path, directory: Path) -> Path:
    output_descriptor, output_name = tempfile.mkstemp(
        prefix=".vlsubsync-input-", suffix=subtitle.suffix, dir=directory
    )
    copied = 0
    try:
        with os.fdopen(output_descriptor, "wb") as output:
            while chunk := os.read(descriptor, 65_536):
                copied += len(chunk)
                if copied > MAX_SUBTITLE_BYTES:
                    raise SubtitleDiscoveryError(
                        "subtitle file grew beyond the safety limit"
                    )
                output.write(chunk)
            os.fchmod(output.fileno(), 0o600)
    except Exception:
        Path(output_name).unlink(missing_ok=True)
        raise
    return Path(output_name)


def _ensure_private_directory(path: Path) -> Path:
    path = _absolute_path(path)
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else None

    missing: list[Path] = []
    cursor = path
    while not os.path.lexists(cursor):
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            raise RuntimeError(f"no existing ancestor for output directory: {path}")
        cursor = parent

    child_owner: int | None = None
    while True:
        metadata = cursor.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"unsafe output-directory ancestor: {cursor}")
        at_filesystem_root = cursor.parent == cursor
        if (
            effective_uid is not None
            and metadata.st_uid not in {0, effective_uid}
            and not at_filesystem_root
        ):
            raise RuntimeError(
                f"output-directory ancestor has an unsafe owner: {cursor}"
            )
        mode = stat.S_IMODE(metadata.st_mode)
        writable_by_others = bool(mode & 0o022)
        safe_sticky_parent = bool(
            mode & stat.S_ISVTX
            and effective_uid is not None
            and child_owner == effective_uid
        )
        if writable_by_others and not safe_sticky_parent:
            raise RuntimeError(
                f"output-directory ancestor is writable by group or others: {cursor}"
            )
        child_owner = metadata.st_uid
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent

    for component in reversed(missing):
        component.mkdir(mode=0o700)
        metadata = component.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or (effective_uid is not None and metadata.st_uid != effective_uid)
        ):
            raise RuntimeError(
                f"could not securely create output directory: {component}"
            )

    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"output directory is not a real directory: {path}")
    if effective_uid is not None and metadata.st_uid != effective_uid:
        raise RuntimeError(f"output directory is not owned by the current user: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        path.chmod(0o700)
    return path


def _default_output_directory(media: Path, subtitle: Path) -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    if configured:
        cache_root = Path(configured).expanduser()
        if not cache_root.is_absolute():
            raise RuntimeError("XDG_CACHE_HOME must be an absolute path")
    else:
        cache_root = Path.home() / ".cache"
    cache_root = _ensure_private_directory(cache_root)
    base = _ensure_private_directory(cache_root / "vlsubsync")
    identity = os.fsencode(str(media)) + b"\0" + os.fsencode(str(subtitle))
    return _ensure_private_directory(base / hashlib.sha256(identity).hexdigest()[:24])


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _track_tokens(value: str | None) -> set[str]:
    tokens = _tokens(value or "")
    tokens |= {alias for name, alias in LANGUAGE_ALIASES.items() if name in tokens}
    return tokens - {"track", "subtitle", "subtitles", "sub", "spu"}


def _is_synced_output(path: Path) -> bool:
    return bool(re.search(r"\.synced(?:-\d+)?$", path.stem, re.IGNORECASE))


def _candidate_score(media: Path, candidate: Path, track_tokens: set[str]) -> int:
    media_stem = media.stem.casefold()
    candidate_stem = candidate.stem.casefold()
    if candidate_stem == media_stem:
        return 1000

    if not candidate_stem.startswith(media_stem):
        return 0
    boundary = candidate_stem[len(media_stem) : len(media_stem) + 1]
    if not boundary or boundary.isalnum():
        return 0

    score = 500
    candidate_tokens = _tokens(candidate_stem)
    score += 100 * len(candidate_tokens & track_tokens)
    return score


def discover_subtitle(
    media: Path | str, selected_track_name: str | None = None
) -> Path:
    """Choose the external subtitle most likely loaded for ``media``.

    Exact filename matches win. Otherwise selected-track language/name tokens are
    considered, then modification time. If the best candidates remain tied, the
    function refuses to guess.
    """

    media, _media_metadata = _validate_regular_file(media, "media file")

    candidates: list[tuple[Path, os.stat_result]] = []
    for path in media.parent.iterdir():
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISREG(metadata.st_mode)
            and path.suffix.casefold() in SUBTITLE_EXTENSIONS
            and not _is_synced_output(path)
        ):
            candidates.append((path, metadata))
    if not candidates:
        raise SubtitleDiscoveryError(
            f"no regular external subtitle files found beside {media.name}"
        )

    track_tokens = _track_tokens(selected_track_name)
    ranked = sorted(
        (
            _candidate_score(media, path, track_tokens),
            metadata.st_mtime_ns,
            path,
        )
        for path, metadata in candidates
    )
    ranked.reverse()
    best_score, best_mtime, best_path = ranked[0]
    if best_score == 0:
        raise SubtitleDiscoveryError(
            f"no subtitle filename appears related to {media.name}"
        )

    if len(ranked) > 1:
        next_score, next_mtime, _ = ranked[1]
        if best_score == next_score and best_mtime == next_mtime:
            names = ", ".join(sorted((best_path.name, ranked[1][2].name)))
            raise AmbiguousSubtitleError(f"subtitle choice is ambiguous: {names}")

    return _validate_regular_file(
        best_path, "subtitle file", maximum_bytes=MAX_SUBTITLE_BYTES
    )[0]


def make_output_path(
    subtitle: Path | str, *, directory: Path | str | None = None
) -> Path:
    subtitle = Path(subtitle)
    parent = Path(directory) if directory is not None else subtitle.parent
    candidate = parent / f"{subtitle.stem}.synced{subtitle.suffix}"
    counter = 2
    while os.path.lexists(candidate):
        if counter > MAX_OUTPUT_ATTEMPTS:
            raise RuntimeError("too many existing synchronized subtitle outputs")
        candidate = parent / f"{subtitle.stem}.synced-{counter}{subtitle.suffix}"
        counter += 1
    return candidate


def _terminate_process_group(process_group: int) -> None:
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return
    for _attempt in range(100):
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)


def _run_ffs(argv: list[str], *, timeout_seconds: float = SYNC_TIMEOUT_SECONDS) -> None:
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    diagnostic = bytearray()

    def drain_output() -> None:
        assert process.stdout is not None
        while chunk := process.stdout.read(8192):
            diagnostic.extend(chunk)
            if len(diagnostic) > MAX_DIAGNOSTIC_BYTES:
                del diagnostic[:-MAX_DIAGNOSTIC_BYTES]

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process.pid)
        process.wait()
        raise RuntimeError(
            f"ffsubsync timed out after {timeout_seconds:g} seconds"
        ) from exc
    finally:
        _terminate_process_group(process.pid)
        reader.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
    if returncode != 0:
        detail = bytes(diagnostic).decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"ffs exited with status {returncode}")


def _ffs_executable() -> str:
    configured = os.environ.get("VLSUBSYNC_FFS")
    if not configured:
        return "ffs"
    configured_path = Path(configured).expanduser()
    if not configured_path.is_absolute():
        raise RuntimeError("VLSUBSYNC_FFS must name an absolute executable file")
    path, _metadata = _validate_regular_file(
        configured_path, "configured ffs executable"
    )
    if not os.access(path, os.X_OK):
        raise RuntimeError("VLSUBSYNC_FFS must name an absolute executable file")
    return str(path)


def _snapshot_generated_output(path: Path, directory: Path) -> Path:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("ffsubsync output is not a regular file") from exc

    snapshot_descriptor: int | None = None
    snapshot: Path | None = None
    try:
        metadata = os.fstat(descriptor)
        current = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or (metadata.st_dev, metadata.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            raise RuntimeError("ffsubsync output is not a stable regular file")
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise RuntimeError("ffsubsync output is not owned by the current user")
        if metadata.st_nlink != 1:
            raise RuntimeError("ffsubsync output has an unsafe hard-link count")
        if metadata.st_size <= 0 or metadata.st_size > MAX_OUTPUT_BYTES:
            raise RuntimeError(
                f"ffsubsync output size is outside the allowed range: {metadata.st_size}"
            )

        snapshot_descriptor, snapshot_name = tempfile.mkstemp(
            prefix=".vlsubsync-publish-", suffix=path.suffix, dir=directory
        )
        snapshot = Path(snapshot_name)
        copied = 0
        with os.fdopen(snapshot_descriptor, "wb") as output:
            snapshot_descriptor = None
            while chunk := os.read(descriptor, 65_536):
                copied += len(chunk)
                if copied > MAX_OUTPUT_BYTES:
                    raise RuntimeError("ffsubsync output grew beyond the safety limit")
                output.write(chunk)
            os.fchmod(output.fileno(), 0o600)
        if copied <= 0:
            raise RuntimeError("ffsubsync produced an empty output")
        return snapshot
    except Exception:
        if snapshot_descriptor is not None:
            os.close(snapshot_descriptor)
        if snapshot is not None:
            snapshot.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def _publish_output(temporary: Path, subtitle: Path, directory: Path) -> Path:
    for _attempt in range(MAX_OUTPUT_ATTEMPTS):
        output = make_output_path(subtitle, directory=directory)
        try:
            os.link(temporary, output, follow_symlinks=False)
        except FileExistsError:
            continue
        temporary.unlink()
        return output
    raise RuntimeError("could not reserve a synchronized subtitle output name")


def synchronize(
    media: Path | str,
    subtitle: Path | str,
    *,
    run_command: Callable[[list[str]], None] = _run_ffs,
    output_directory: Path | str | None = None,
) -> Path:
    media, _media_metadata = _validate_regular_file(media, "media file")
    subtitle, _subtitle_metadata = _validate_regular_file(
        subtitle, "subtitle file", maximum_bytes=MAX_SUBTITLE_BYTES
    )
    directory = _ensure_private_directory(
        Path(output_directory)
        if output_directory is not None
        else _default_output_directory(media, subtitle)
    )
    media_descriptor = _open_pinned_regular_file(media, "media file")
    subtitle_descriptor: int | None = None
    subtitle_copy: Path | None = None
    temporary: Path | None = None
    publishable: Path | None = None
    try:
        subtitle_descriptor = _open_pinned_regular_file(
            subtitle, "subtitle file", maximum_bytes=MAX_SUBTITLE_BYTES
        )
        subtitle_copy = _copy_pinned_subtitle(subtitle_descriptor, subtitle, directory)
        os.close(subtitle_descriptor)
        subtitle_descriptor = None

        output_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".vlsubsync-output-", suffix=subtitle.suffix, dir=directory
        )
        os.close(output_descriptor)
        temporary = Path(temporary_name)
        temporary.chmod(0o600)
        run_command(
            [
                _ffs_executable(),
                f"/proc/{os.getpid()}/fd/{media_descriptor}",
                "-i",
                str(subtitle_copy),
                "-o",
                str(temporary),
            ]
        )
        publishable = _snapshot_generated_output(temporary, directory)
        return _publish_output(publishable, subtitle, directory)
    finally:
        if subtitle_descriptor is not None:
            os.close(subtitle_descriptor)
        os.close(media_descriptor)
        for transient in (subtitle_copy, temporary, publishable):
            if transient is not None and os.path.lexists(transient):
                transient.unlink()


def _selected_track_from_args(value: str | None) -> str | None:
    return value if value and value != "-" else None


def _protocol_encode(value: str) -> str:
    return value.encode("utf-8", errors="surrogateescape").hex()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize VLC's current subtitles")
    parser.add_argument("media", type=Path)
    parser.add_argument("--track-name", default=None)
    parser.add_argument("--subtitle", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        subtitle = args.subtitle or discover_subtitle(
            args.media, _selected_track_from_args(args.track_name)
        )
        output = synchronize(args.media, subtitle)
    except Exception as exc:
        print(f"VLSUBSYNC_ERROR_HEX\t{_protocol_encode(str(exc))}")
        return 1

    print(f"VLSUBSYNC_OK_HEX\t{_protocol_encode(str(output))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
