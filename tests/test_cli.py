from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

CLI_PATH = Path(__file__).resolve().parents[1] / "vlsubsync"
CLI_LOADER = importlib.machinery.SourceFileLoader("vlsubsync_cli", str(CLI_PATH))
CLI_SPEC = importlib.util.spec_from_loader(CLI_LOADER.name, CLI_LOADER)
assert CLI_SPEC is not None
cli_module = importlib.util.module_from_spec(CLI_SPEC)
CLI_LOADER.exec_module(cli_module)

AmbiguousSubtitleError = cli_module.AmbiguousSubtitleError
SubtitleDiscoveryError = cli_module.SubtitleDiscoveryError
_run_ffs = cli_module._run_ffs
discover_subtitle = cli_module.discover_subtitle
make_output_path = cli_module.make_output_path
synchronize = cli_module.synchronize


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

    def test_rejects_symlinked_media(self) -> None:
        link = self.root / "linked.mkv"
        link.symlink_to(self.media)
        self.touch("linked.srt", 10)

        with self.assertRaisesRegex(SubtitleDiscoveryError, "symbolic link"):
            discover_subtitle(link)

    def test_rejects_symlinked_subtitle(self) -> None:
        target = self.root / "unrelated.txt"
        target.write_text("not a subtitle", encoding="utf-8")
        (self.root / "Example.Movie.2024.srt").symlink_to(target)

        with self.assertRaises(SubtitleDiscoveryError):
            discover_subtitle(self.media)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_rejects_fifo_subtitle(self) -> None:
        os.mkfifo(self.root / "Example.Movie.2024.srt")

        with self.assertRaises(SubtitleDiscoveryError):
            discover_subtitle(self.media)


class SynchronizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.media = self.root / "movie.mkv"
        self.subtitle = self.root / "movie.en.srt"
        self.output_dir = self.root / "output"
        self.output_dir.mkdir(mode=0o700)
        self.media.touch()
        self.subtitle.write_text("subtitle", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_output_path_uses_private_directory_and_does_not_overwrite(self) -> None:
        first = make_output_path(self.subtitle, directory=self.output_dir)
        self.assertEqual(first, self.output_dir / "movie.en.synced.srt")
        first.touch()
        self.assertEqual(
            make_output_path(self.subtitle, directory=self.output_dir),
            self.output_dir / "movie.en.synced-2.srt",
        )

    def test_runs_ffs_with_pinned_private_inputs(self) -> None:
        calls: list[list[str]] = []
        captured_inputs: list[tuple[bytes, str]] = []

        def fake_run(argv: list[str]) -> None:
            calls.append(argv)
            captured_inputs.append(
                (
                    Path(argv[1]).read_bytes(),
                    Path(argv[argv.index("-i") + 1]).read_text(encoding="utf-8"),
                )
            )
            Path(argv[argv.index("-o") + 1]).write_text("synced", encoding="utf-8")

        output = synchronize(
            self.media,
            self.subtitle,
            run_command=fake_run,
            output_directory=self.output_dir,
        )

        self.assertEqual(len(calls), 1)
        self.assertRegex(calls[0][1], r"^/proc/\d+/fd/\d+$")
        private_subtitle = Path(calls[0][3])
        self.assertEqual(private_subtitle.parent, self.output_dir)
        self.assertEqual(private_subtitle.suffix, self.subtitle.suffix)
        self.assertEqual(captured_inputs, [(b"", "subtitle")])
        temporary_output = Path(calls[0][5])
        self.assertEqual(temporary_output.parent, self.output_dir)
        self.assertNotEqual(temporary_output, output)
        self.assertFalse(private_subtitle.exists())
        self.assertTrue(output.exists())

    def test_dangling_output_symlink_is_never_followed_or_replaced(self) -> None:
        sentinel = self.root / "sentinel"
        sentinel.write_text("safe", encoding="utf-8")
        dangerous = self.output_dir / "movie.en.synced.srt"
        dangerous.symlink_to(sentinel)

        def fake_run(argv: list[str]) -> None:
            Path(argv[-1]).write_text("synced", encoding="utf-8")

        output = synchronize(
            self.media,
            self.subtitle,
            run_command=fake_run,
            output_directory=self.output_dir,
        )

        self.assertEqual(output.name, "movie.en.synced-2.srt")
        self.assertTrue(dangerous.is_symlink())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "safe")

    def test_rejects_symlink_created_by_sync_engine(self) -> None:
        sentinel = self.root / "sentinel"
        sentinel.write_text("safe", encoding="utf-8")

        def fake_run(argv: list[str]) -> None:
            temporary_output = Path(argv[-1])
            temporary_output.unlink()
            temporary_output.symlink_to(sentinel)

        with self.assertRaisesRegex(RuntimeError, "regular file"):
            synchronize(
                self.media,
                self.subtitle,
                run_command=fake_run,
                output_directory=self.output_dir,
            )

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "safe")

    def test_rejects_hard_link_created_by_sync_engine(self) -> None:
        sentinel = self.root / "sentinel"
        sentinel.write_text("safe", encoding="utf-8")

        def fake_run(argv: list[str]) -> None:
            temporary_output = Path(argv[-1])
            temporary_output.unlink()
            os.link(sentinel, temporary_output)

        with self.assertRaisesRegex(RuntimeError, "hard-link count"):
            synchronize(
                self.media,
                self.subtitle,
                run_command=fake_run,
                output_directory=self.output_dir,
            )

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "safe")

    def test_rejects_symlinked_explicit_subtitle(self) -> None:
        link = self.root / "movie.link.srt"
        link.symlink_to(self.subtitle)
        called = False

        def fake_run(_argv: list[str]) -> None:
            nonlocal called
            called = True

        with self.assertRaisesRegex(SubtitleDiscoveryError, "symbolic link"):
            synchronize(
                self.media,
                link,
                run_command=fake_run,
                output_directory=self.output_dir,
            )
        self.assertFalse(called)

    def test_rejects_cross_user_writable_cache_ancestor(self) -> None:
        unsafe = self.root / "unsafe-cache-parent"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        called = False

        def fake_run(_argv: list[str]) -> None:
            nonlocal called
            called = True

        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(unsafe / "cache")}):
            with self.assertRaisesRegex(RuntimeError, "writable by group or others"):
                synchronize(self.media, self.subtitle, run_command=fake_run)
        self.assertFalse(called)

    def test_rejects_oversized_subtitle(self) -> None:
        with mock.patch.object(cli_module, "MAX_SUBTITLE_BYTES", 4):
            with self.assertRaisesRegex(SubtitleDiscoveryError, "too large"):
                synchronize(
                    self.media,
                    self.subtitle,
                    run_command=lambda _argv: None,
                    output_directory=self.output_dir,
                )

    def test_ffs_timeout_terminates_the_process(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            _run_ffs(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout_seconds=0.05,
            )

    def test_ffs_success_terminates_lingering_process_group(self) -> None:
        marker = self.root / "lingering-child-ran"
        child_code = (
            "import pathlib,time; time.sleep(0.2); "
            f"pathlib.Path({str(marker)!r}).write_text('unsafe')"
        )
        parent_code = (
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
        )

        _run_ffs([sys.executable, "-c", parent_code])
        time.sleep(0.3)

        self.assertFalse(marker.exists())


class CliTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = cli_module.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_default_output_is_the_synchronized_subtitle_path(self) -> None:
        output = Path("/tmp/Movie.en.synced.srt")
        with (
            mock.patch.object(
                cli_module, "discover_subtitle", return_value=Path("Movie.en.srt")
            ),
            mock.patch.object(cli_module, "synchronize", return_value=output),
        ):
            result, stdout, stderr = self.run_main(["Movie.mkv"])

        self.assertEqual(result, 0)
        self.assertEqual(stdout, f"{output}\n")
        self.assertEqual(stderr, "")

    def test_protocol_output_remains_hex_encoded_for_lua(self) -> None:
        output = Path("/tmp/Movie.en.synced.srt")
        with (
            mock.patch.object(
                cli_module, "discover_subtitle", return_value=Path("Movie.en.srt")
            ),
            mock.patch.object(cli_module, "synchronize", return_value=output),
        ):
            result, stdout, stderr = self.run_main(["--protocol", "Movie.mkv"])

        self.assertEqual(result, 0)
        self.assertEqual(
            stdout,
            f"VLSUBSYNC_OK_HEX\t{str(output).encode('utf-8').hex()}\n",
        )
        self.assertEqual(stderr, "")

    def test_protocol_errors_remain_hex_encoded_for_lua(self) -> None:
        message = "no matching subtitle\nwith injected marker"
        with mock.patch.object(
            cli_module,
            "discover_subtitle",
            side_effect=SubtitleDiscoveryError(message),
        ):
            result, stdout, stderr = self.run_main(["--protocol", "Movie.mkv"])

        self.assertEqual(result, 1)
        self.assertEqual(
            stdout,
            f"VLSUBSYNC_ERROR_HEX\t{message.encode('utf-8').hex()}\n",
        )
        self.assertEqual(stderr, "")

    def test_default_errors_are_human_readable(self) -> None:
        with mock.patch.object(
            cli_module,
            "discover_subtitle",
            side_effect=SubtitleDiscoveryError("no matching subtitle"),
        ):
            result, stdout, stderr = self.run_main(["Movie.mkv"])

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "vlsubsync: no matching subtitle\n")


if __name__ == "__main__":
    unittest.main()
