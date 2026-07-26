"""Tests for the CLI argument parser and routing."""

from __future__ import annotations

import pytest

from perfect_choice.cli import _build_parser, main


class TestParser:
    """Verify argparse configuration."""

    def test_no_command_returns_zero(self, capsys):
        assert main([]) == 0

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0

    def test_decide_command_parses(self):
        parser = _build_parser()
        args = parser.parse_args(["decide"])
        assert args.command == "decide"
        assert args.tier is None

    def test_decide_with_tier(self):
        parser = _build_parser()
        args = parser.parse_args(["decide", "--tier", "quick"])
        assert args.tier == "quick"

    def test_quick_command_parses(self):
        parser = _build_parser()
        args = parser.parse_args(["quick"])
        assert args.command == "quick"

    def test_list_command_defaults(self):
        parser = _build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"
        assert args.status is None
        assert args.limit == 20

    def test_list_with_status_filter(self):
        parser = _build_parser()
        args = parser.parse_args(["list", "--status", "completed"])
        assert args.status == "completed"

    def test_list_with_limit(self):
        parser = _build_parser()
        args = parser.parse_args(["list", "--limit", "5"])
        assert args.limit == 5

    def test_review_command(self):
        parser = _build_parser()
        args = parser.parse_args(["review", "abc123"])
        assert args.command == "review"
        assert args.id == "abc123"

    def test_replay_command(self):
        parser = _build_parser()
        args = parser.parse_args(["replay", "abc123"])
        assert args.command == "replay"
        assert args.id == "abc123"

    def test_export_command_defaults(self):
        parser = _build_parser()
        args = parser.parse_args(["export", "abc123"])
        assert args.command == "export"
        assert args.format == "markdown"
        assert args.output is None

    def test_export_json_format(self):
        parser = _build_parser()
        args = parser.parse_args(["export", "abc123", "--format", "json"])
        assert args.format == "json"

    def test_no_llm_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--no-llm", "decide"])
        assert args.no_llm is True

    def test_no_llm_default_false(self):
        parser = _build_parser()
        args = parser.parse_args(["decide"])
        assert args.no_llm is False


class TestDecideTemplateFlag:
    """Tests for --template flag on decide subcommand."""

    def test_decide_with_template(self):
        parser = _build_parser()
        args = parser.parse_args(["decide", "--template", "job_offer"])
        assert args.template == "job_offer"

    def test_decide_template_default_none(self):
        parser = _build_parser()
        args = parser.parse_args(["decide"])
        assert args.template is None

    def test_decide_invalid_template_rejected(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["decide", "--template", "nonexistent"])

    def test_all_templates_accepted(self):
        from perfect_choice.templates import list_templates

        parser = _build_parser()
        for name in list_templates():
            args = parser.parse_args(["decide", "--template", name])
            assert args.template == name


class TestImportCommand:
    """Tests for import subcommand parsing and execution."""

    def test_import_parses(self):
        parser = _build_parser()
        args = parser.parse_args(["import", "data.json"])
        assert args.command == "import"
        assert args.file == "data.json"

    def test_import_with_format(self):
        parser = _build_parser()
        args = parser.parse_args(["import", "data.txt", "--format", "csv"])
        assert args.fmt == "csv"

    def test_import_format_default_none(self):
        parser = _build_parser()
        args = parser.parse_args(["import", "data.json"])
        assert args.fmt is None

    def test_import_missing_file(self, tmp_path):
        result = main(["--no-llm", "import", str(tmp_path / "missing.json")])
        assert result == 1

    def test_import_valid_json_file(self, tmp_path):
        import json

        data = {
            "title": "Test",
            "alternatives": ["A", "B"],
            "criteria": [{"name": "C1", "weight": 1.0}],
            "scores": {"A": {"C1": 8}, "B": {"C1": 6}},
        }
        p = tmp_path / "test.json"
        p.write_text(json.dumps(data))
        result = main(["--no-llm", "import", str(p)])
        assert result == 0


class TestListCommand:
    """Test the list command with a real DB."""

    def test_list_empty_db(self, tmp_path, capsys):
        from perfect_choice.config import Config

        config = Config(db_path=str(tmp_path / "test.db"), no_llm=True)
        from perfect_choice.db import Database

        with Database(config.db_path):
            pass  # Just create schema

        # The list command should work even with empty db
        from perfect_choice.cli import _cmd_list

        class Args:
            limit = 20
            status = None

        result = _cmd_list(config, Args())
        assert result == 0
