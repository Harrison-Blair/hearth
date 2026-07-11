"""Tests for hearth.app CLI entry point."""
from hearth import __version__
from hearth.app import main


def test_version_command(capsys):
    exit_code = main(["--version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == __version__
