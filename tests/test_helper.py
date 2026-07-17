from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from vlsubsync.helper import (
    AmbiguousSubtitleError,
    SubtitleDiscoveryError,
    discover_subtitle,
    make_output_path,
    synchronize,
)


class DiscoverSubtitleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.media = self.root / "Example.Movie.2024.mkv"
        self.media.touch()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def touch(self, name: str, mtime: float) -> Path:
        path = self.root / name
        path.write_text("subtitle", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_prefers_exact_media_stem(self) -> None:
        exact = self.touch("Example.Movie.2024.srt", 10)
        self.touch("Example.Movie.2024.en.srt", 20)

        self.assertEqual(discover_subtitle(self.media), exact)

    def test_uses_selected_track_name_to_disambiguate_language(self) -> None:
        self.touch("Example.Movie.2024.en.srt", 10)
        french = self.touch("Example.Movie.2024.fr.srt", 20)

        self.assertEqual(
            discover_subtitle(self.media, selected_track_name="French (fr)"), french
        )

    def test_uses_newest_related_subtitle_when_track_name_is_unhelpful(self) -> None:
        self.touch("Example.Movie.2024.en.srt", 10)
        newest = self.touch("Example.Movie.2024.fr.srt", 30)

        self.assertEqual(
            discover_subtitle(self.media, selected_track_name="Track 1"), newest
        )

    def test_rejects_equally_plausible_candidates_with_same_timestamp(self) -> None:
        self.touch("Example.Movie.2024.en.srt", 10)
        self.touch("Example.Movie.2024.fr.srt", 10)

        with self.assertRaises(AmbiguousSubtitleError):
            discover_subtitle(self.media)

    def test_rejects_unrelated_file_containing_short_media_stem(self) -> None:
        self.media = self.root / "Up.mkv"
        self.media.touch()
        self.touch("backup.srt", 10)

        with self.assertRaises(SubtitleDiscoveryError):
            discover_subtitle(self.media)

    def test_rejects_unrelated_file_matching_only_track_language(self) -> None:
        self.touch("French.srt", 10)

        with self.assertRaises(SubtitleDiscoveryError):
            discover_subtitle(self.media, selected_track_name="French")

    def test_ignores_previous_synced_outputs(self) -> None:
        source = self.touch("Example.Movie.2024.en.srt", 10)
        self.touch("Example.Movie.2024.en.synced.srt", 20)

        self.assertEqual(discover_subtitle(self.media), source)


class SynchronizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.media = self.root / "movie.mkv"
        self.subtitle = self.root / "movie.en.srt"
        self.media.touch()
        self.subtitle.write_text("subtitle", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_output_path_is_next_to_source_and_does_not_overwrite(self) -> None:
        first = make_output_path(self.subtitle)
        self.assertEqual(first, self.root / "movie.en.synced.srt")
        first.touch()
        self.assertEqual(
            make_output_path(self.subtitle), self.root / "movie.en.synced-2.srt"
        )

    def test_runs_ffs_with_explicit_paths(self) -> None:
        calls: list[list[str]] = []

        def fake_run(argv: list[str]) -> None:
            calls.append(argv)
            Path(argv[argv.index("-o") + 1]).write_text("synced", encoding="utf-8")

        output = synchronize(self.media, self.subtitle, run_command=fake_run)

        self.assertEqual(
            calls,
            [[
                "ffs",
                str(self.media),
                "-i",
                str(self.subtitle),
                "-o",
                str(output),
            ]],
        )
        self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
