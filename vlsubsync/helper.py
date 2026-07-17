"""Core discovery and synchronization logic for VLSubSync."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
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


class SubtitleDiscoveryError(RuntimeError):
    """No safe subtitle choice could be made."""


class AmbiguousSubtitleError(SubtitleDiscoveryError):
    """More than one subtitle is equally plausible."""


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

    media = Path(media).expanduser().resolve()
    if not media.is_file():
        raise SubtitleDiscoveryError(f"media file does not exist: {media}")

    candidates = [
        path
        for path in media.parent.iterdir()
        if path.is_file()
        and path.suffix.casefold() in SUBTITLE_EXTENSIONS
        and not _is_synced_output(path)
    ]
    if not candidates:
        raise SubtitleDiscoveryError(
            f"no external subtitle files found beside {media.name}"
        )

    track_tokens = _track_tokens(selected_track_name)
    ranked = sorted(
        (
            _candidate_score(media, path, track_tokens),
            path.stat().st_mtime_ns,
            path,
        )
        for path in candidates
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

    return best_path


def make_output_path(subtitle: Path | str) -> Path:
    subtitle = Path(subtitle)
    candidate = subtitle.with_name(f"{subtitle.stem}.synced{subtitle.suffix}")
    counter = 2
    while candidate.exists():
        candidate = subtitle.with_name(
            f"{subtitle.stem}.synced-{counter}{subtitle.suffix}"
        )
        counter += 1
    return candidate


def _run_ffs(argv: list[str]) -> None:
    completed = subprocess.run(argv, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"ffs exited with status {completed.returncode}")


def synchronize(
    media: Path | str,
    subtitle: Path | str,
    *,
    run_command: Callable[[list[str]], None] = _run_ffs,
) -> Path:
    media = Path(media).expanduser().resolve()
    subtitle = Path(subtitle).expanduser().resolve()
    output = make_output_path(subtitle)
    run_command(["ffs", str(media), "-i", str(subtitle), "-o", str(output)])
    if not output.is_file():
        raise RuntimeError("ffsubsync reported success but did not create an output file")
    return output


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
