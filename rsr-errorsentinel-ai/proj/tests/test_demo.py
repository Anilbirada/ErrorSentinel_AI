from app.demo import run_demo


def test_demo_scenario(tmp_path):
    lines = []
    r = run_demo(tmp_path / "demo", out=lines.append)
    assert [len(x.new_codes) for x in r] == [2, 0, 1, 1, 0]
    assert r[2].registry_status == "UNCHANGED" and r[2].notification_status == "FAILED"
    assert r[3].registry_status == "COMMITTED"


def test_cli_check_config_reports_problems(monkeypatch, capsys):
    import main
    for k in ("EMAIL_PROVIDER", "ALERT_RECIPIENTS", "GMAIL_USER"):
        monkeypatch.delenv(k, raising=False)
    assert main.main(["--check-config"]) == 1
    assert "GMAIL_USER is required" in capsys.readouterr().out
