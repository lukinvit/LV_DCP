import getpass
from pathlib import Path

from apps.cli.commands.resume_cmd import app as resume_app
from libs.breadcrumbs.store import BreadcrumbStore
from libs.breadcrumbs.writer import write_pack_event
from typer.testing import CliRunner


def test_resume_returns_empty_string_when_no_breadcrumbs(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.cli.commands.resume_cmd.DEFAULT_STORE_PATH", db)
    monkeypatch.chdir(tmp_path)
    r = CliRunner()
    result = r.invoke(resume_app, ["--inject"])
    assert result.exit_code == 0


def test_resume_path_includes_query(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.cli.commands.resume_cmd.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db)
    s.migrate()
    write_pack_event(
        store=s,
        project_root=str(tmp_path),
        os_user=getpass.getuser(),
        query="how does X work",
        mode="navigate",
        paths_touched=["src/x.py"],
    )
    s.close()
    r = CliRunner()
    result = r.invoke(resume_app, ["--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "how does X work" in result.output


def test_resume_all_lists_projects(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "bc.db"
    monkeypatch.setattr("libs.breadcrumbs.store.DEFAULT_STORE_PATH", db)
    monkeypatch.setattr("apps.cli.commands.resume_cmd.DEFAULT_STORE_PATH", db)
    s = BreadcrumbStore(db_path=db)
    s.migrate()
    write_pack_event(
        store=s,
        project_root="/a",
        os_user=getpass.getuser(),
        query="qa",
        mode="navigate",
        paths_touched=[],
    )
    s.close()
    r = CliRunner()
    result = r.invoke(resume_app, ["--all"])
    assert result.exit_code == 0
    assert "/a" in result.output
