"""Compatibilité whisper.cpp pré/post v1.7 + erreurs binaires explicites.

Contexte : whisper.cpp v1.7 a supprimé -f/--file au profit de fichiers
d'entrée positionnels (`whisper-cli [options] file0.wav...`). Un -f codé
en dur = échec systématique muet. Le style est sniffé via --help (cache
par binaire), et tout exit non zéro remonte avec l'extrait stderr.
"""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from app import stt_providers as stt
from app.stt_providers import WhisperCppProvider, whisper_input_args, whisper_json_flags
from app.voice_service import VoiceService

OLD_HELP = """usage: main [options] ...

  -f FNAME,   --file FNAME        [    ] input file
  -of FNAME,  --output-file FNAME [    ] output file
"""

NEW_HELP = """usage: /opt/voice/bin/whisper-cli [options] file0.wav file1.wav ...

  -nf,       --no-fallback       [false  ] do not use temperature fallback
  -of FNAME, --output-file FNAME [    ] output file
  -otxt,     --output-txt        [false  ] output result in a text file
"""


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class InputStyleTest(unittest.TestCase):
    def test_old_binary_uses_file_flag(self) -> None:
        with patch.object(stt.subprocess, "run", return_value=_completed(OLD_HELP)):
            self.assertEqual(
                whisper_input_args("/bin/whisper-old", "/tmp/a.wav"),
                ["-f", "/tmp/a.wav"])

    def test_v17_binary_uses_positional(self) -> None:
        # -nf/-of présents : pas de faux positif sur "-f".
        with patch.object(stt.subprocess, "run", return_value=_completed(NEW_HELP)):
            self.assertEqual(
                whisper_input_args("/bin/whisper-new", "/tmp/a.wav"),
                ["/tmp/a.wav"])

    def test_help_failure_defaults_positional(self) -> None:
        with patch.object(stt.subprocess, "run", side_effect=OSError("boom")):
            self.assertEqual(
                whisper_input_args("/bin/whisper-broken", "/tmp/a.wav"),
                ["/tmp/a.wav"])

    def test_style_cached_per_binary(self) -> None:
        with patch.object(stt.subprocess, "run", return_value=_completed(OLD_HELP)) as m:
            whisper_input_args("/bin/whisper-cached", "/tmp/a.wav")
            whisper_input_args("/bin/whisper-cached", "/tmp/b.wav")
            self.assertEqual(m.call_count, 1)


V17_JSON_HELP = """usage: whisper-cli [options] file0.wav ...

  -f FNAME,  --file FNAME        [       ] input WAV file path
  -oj,       --output-json       [false  ] output result in a JSON file
  -ojf,      --output-json-full  [false  ] include more information in the JSON file
"""

OLD_JSON_HELP = """usage: main [options] ...

  -f FNAME,  --file FNAME        [       ] input file
  -ojson                         output result in a JSON file
"""


class JsonFlagSniffTest(unittest.TestCase):
    def test_v17_selects_dash_oj_not_ojson(self) -> None:
        # Régression réelle : "--output-json" seul sélectionnait "-ojson"
        # (inconnu en v1.7.4) et chaque appel échouait.
        with patch.object(stt.subprocess, "run", return_value=_completed(V17_JSON_HELP)):
            self.assertEqual(whisper_json_flags("/bin/whisper-v17"), ["-oj"])

    def test_legacy_selects_ojson(self) -> None:
        with patch.object(stt.subprocess, "run", return_value=_completed(OLD_JSON_HELP)):
            self.assertEqual(whisper_json_flags("/bin/whisper-legacy"), ["-ojson"])

    def test_no_json_flag_means_empty(self) -> None:
        with patch.object(stt.subprocess, "run", return_value=_completed("usage: x\n  -l LANG")):
            self.assertEqual(whisper_json_flags("/bin/whisper-nojson"), [])


class WhisperExitCodeTest(unittest.TestCase):
    def _provider(self) -> WhisperCppProvider:
        return WhisperCppProvider(binary="/bin/whisper", model="/models/x.bin")

    def test_nonzero_exit_raises_with_stderr(self) -> None:
        bad = _completed("", returncode=1, stderr="error: unknown argument: -f")
        with patch("app.stt_providers.os.path.isfile", return_value=True), \
                patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
                patch("app.stt_providers.whisper_json_flags", return_value=[]), \
                patch("app.stt_providers.whisper_input_args", return_value=["/tmp/n.wav"]), \
                patch("app.stt_providers.subprocess.run", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, r"code 1.*unknown argument: -f"):
                self._provider().transcribe(b"xx", "a.webm", "fr")

    def test_auto_nonzero_exit_raises(self) -> None:
        bad = _completed("", returncode=2, stderr="error: failed to load model")
        with patch("app.stt_providers.os.path.isfile", return_value=True), \
                patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
                patch("app.stt_providers.whisper_input_args", return_value=["/tmp/n.wav"]), \
                patch("app.stt_providers.subprocess.run", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, r"code 2.*failed to load model"):
                self._provider().transcribe_auto(b"xx", "a.webm")

    def test_input_file_is_last_argv(self) -> None:
        seen: list = []
        ok = _completed("fuite robinet")

        def fake_run(argv, **kwargs):
            seen.extend(argv)
            return ok

        isbin = lambda p: p in ("/bin/whisper", "/models/x.bin")  # noqa: E731
        with patch("app.stt_providers.os.path.isfile", side_effect=isbin), \
                patch("app.stt_providers.normalize_to_wav", return_value="/tmp/n.wav"), \
                patch("app.stt_providers.whisper_json_flags", return_value=[]), \
                patch("app.stt_providers.whisper_input_args", return_value=["/tmp/n.wav"]), \
                patch("app.stt_providers.subprocess.run", side_effect=fake_run):
            self._provider().transcribe(b"xx", "a.webm", "fr")
        self.assertEqual(seen[-1], "/tmp/n.wav")


class SttFailureLoggingTest(unittest.TestCase):
    def test_direct_failure_logs_driver_and_stays_guided(self) -> None:
        class BoomProvider:
            driver_name = "whisper_cpp"

            def transcribe(self, audio_bytes, filename, language):
                raise RuntimeError("whisper-cli a échoué (code 1) : boom")

        with patch("app.voice_service._probe_duration", return_value=None):
            with self.assertLogs("app.voice_service", level="WARNING") as logs:
                with self.assertRaisesRegex(RuntimeError, "STT_UNAVAILABLE"):
                    VoiceService().transcribe(b"RIFFfake", "a.ogg", "fr", stt=BoomProvider())
        self.assertTrue(any("whisper_cpp" in line and "boom" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
