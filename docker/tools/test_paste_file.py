"""Clipboard file URI contract for outbound uploads."""

import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


def test_paste_file_keeps_unicode_basename_in_clipboard_uri(tmp_path: Path) -> None:
    original = tmp_path / "《创始人行动手册》.pdf"
    original.write_bytes(b"%PDF-1.4")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "clipboard-uri"
    xclip = fake_bin / "xclip"
    xclip.write_text('#!/bin/sh\ncat > "$CLIPBOARD_CAPTURE"\n')
    xclip.chmod(0o755)
    xdotool = fake_bin / "xdotool"
    xdotool.write_text("#!/bin/sh\nexit 0\n")
    xdotool.chmod(0o755)

    output = tmp_path / "script-output"
    with output.open("w") as stdout, (tmp_path / "script-error").open("w") as stderr:
        subprocess.run(
            [str(Path(__file__).with_name("paste-file")), str(original)],
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "CLIPBOARD_CAPTURE": str(capture),
            },
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=5,
            check=True,
        )

    uri = capture.read_text()
    assert uri.isascii()
    assert unquote(urlsplit(uri).path) == str(original)
    assert "《创始人行动手册》.pdf" in output.read_text()
