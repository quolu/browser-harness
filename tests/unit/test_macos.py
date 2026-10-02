import os
from pathlib import Path

from browser_harness import macos


def _enable_chrome_toggle(monkeypatch):
    chrome_root = Path("/tmp/Google Chrome")
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: chrome_root)
    monkeypatch.setattr(
        macos,
        "remote_debugging_toggle_profiles",
        lambda: [chrome_root],
    )


def _no_ready_daemon(monkeypatch):
    monkeypatch.setattr(macos, "daemon_browser_ready", lambda: False)


def _on_macos_with_target(monkeypatch, pid=12827):
    monkeypatch.setattr(macos.platform, "system", lambda: "Darwin")
    _no_ready_daemon(monkeypatch)
    _enable_chrome_toggle(monkeypatch)
    monkeypatch.setattr(macos, "_approval_target", lambda: (pid, None))


def _record_presses(monkeypatch, result="ready"):
    calls = []
    monkeypatch.setattr(
        macos,
        "press_allow_sheet",
        lambda pid, titles, labels: calls.append((pid, titles, labels)) or result,
    )
    return calls


def _refuse_presses(monkeypatch):
    def refuse(*args):
        raise AssertionError("should not press")

    monkeypatch.setattr(macos, "press_allow_sheet", refuse)


def test_mac_approve_requires_the_persistent_chrome_checkbox(monkeypatch):
    monkeypatch.setattr(macos.platform, "system", lambda: "Darwin")
    _no_ready_daemon(monkeypatch)
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: Path("/tmp/Google Chrome"))
    monkeypatch.setattr(macos, "remote_debugging_toggle_profiles", lambda: [Path("/tmp/Edge")])
    _refuse_presses(monkeypatch)

    status, detail = macos.approve_remote_debugging()

    assert status == "setup-required"
    assert "chrome://inspect/#remote-debugging" in detail


def test_mac_approve_presses_only_on_the_target_pid(monkeypatch):
    _on_macos_with_target(monkeypatch, pid=12827)
    calls = _record_presses(monkeypatch)

    assert macos.approve_remote_debugging() == ("ready", None)
    assert [pid for pid, _, _ in calls] == [12827]


def test_mac_approve_does_not_press_when_no_target_is_confirmed(monkeypatch):
    monkeypatch.setattr(macos.platform, "system", lambda: "Darwin")
    _no_ready_daemon(monkeypatch)
    _enable_chrome_toggle(monkeypatch)
    monkeypatch.setattr(macos, "_approval_target", lambda: (None, "the daemon connects to /tmp/Edge"))
    _refuse_presses(monkeypatch)

    status, detail = macos.approve_remote_debugging()

    assert status == "not-found"
    assert detail.startswith("the daemon connects to /tmp/Edge")
    assert "retry the browser command" in detail


def test_mac_approve_reports_ready_when_the_target_check_races_an_accept(monkeypatch):
    monkeypatch.setattr(macos.platform, "system", lambda: "Darwin")
    _enable_chrome_toggle(monkeypatch)
    readiness = iter([False, True])
    monkeypatch.setattr(macos, "daemon_browser_ready", lambda: next(readiness))
    monkeypatch.setattr(macos, "_approval_target", lambda: (None, "no running Google Chrome holds /tmp"))
    _refuse_presses(monkeypatch)

    assert macos.approve_remote_debugging() == ("ready", None)


def test_mac_approve_refuses_when_the_daemon_uses_a_non_local_browser(monkeypatch):
    _on_macos_with_target(monkeypatch)
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:9333")
    _refuse_presses(monkeypatch)

    status, detail = macos.approve_remote_debugging()

    assert status == "unsupported"
    assert "BU_CDP_URL" in detail


def test_mac_approve_maps_a_slow_accessibility_walk_to_an_error(monkeypatch):
    _on_macos_with_target(monkeypatch)

    def slow(*args):
        raise TimeoutError("the Accessibility walk took longer than 5s")

    monkeypatch.setattr(macos, "press_allow_sheet", slow)

    status, detail = macos.approve_remote_debugging()

    assert status == "error"
    assert "TimeoutError" in detail


def test_mac_approve_passes_chromes_localized_sheet_strings(monkeypatch):
    _on_macos_with_target(monkeypatch)
    monkeypatch.delenv("BH_ALLOW_SHEET_TITLES", raising=False)
    monkeypatch.delenv("BH_ALLOW_LABELS", raising=False)
    calls = _record_presses(monkeypatch)

    macos.approve_remote_debugging()

    _, titles, labels = calls[0]
    assert "Allow remote debugging?" in titles
    assert "リモート デバッグを許可しますか？" in titles
    assert "Allow" in labels
    assert "許可する" in labels
    assert "Cancel" not in labels
    assert "キャンセル" not in labels
    assert "Turn off in settings" not in labels


def test_mac_approve_extends_tables_from_env(monkeypatch):
    _on_macos_with_target(monkeypatch)
    monkeypatch.setenv("BH_ALLOW_SHEET_TITLES", "Fernwartung erlauben? , Ander titel")
    monkeypatch.setenv("BH_ALLOW_LABELS", "Ja,Oui")
    calls = _record_presses(monkeypatch)

    macos.approve_remote_debugging()

    _, titles, labels = calls[0]
    assert titles[-2:] == ("Fernwartung erlauben?", "Ander titel")
    assert "Allow remote debugging?" in titles
    assert labels[-2:] == ("Ja", "Oui")
    assert "Allow" in labels


def test_mac_approve_maps_missing_accessibility_access_to_guidance(monkeypatch):
    _on_macos_with_target(monkeypatch)

    def denied(*args):
        raise macos.AccessibilityDenied

    monkeypatch.setattr(macos, "press_allow_sheet", denied)

    status, detail = macos.approve_remote_debugging()

    assert status == "accessibility-required"
    assert "Accessibility" in detail


def test_mac_approve_returns_not_found_without_a_prompt(monkeypatch):
    _on_macos_with_target(monkeypatch)
    _record_presses(monkeypatch, result="not-found")

    status, detail = macos.approve_remote_debugging()

    assert status == "not-found"
    assert "retry the browser command" in detail


def test_mac_approve_returns_ready_without_pressing(monkeypatch):
    monkeypatch.setattr(macos.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(macos, "daemon_browser_ready", lambda: True)
    _refuse_presses(monkeypatch)

    assert macos.approve_remote_debugging() == ("ready", None)


def test_mac_approve_detects_user_accepting_while_it_checks(monkeypatch):
    monkeypatch.setattr(macos.platform, "system", lambda: "Darwin")
    _enable_chrome_toggle(monkeypatch)
    monkeypatch.setattr(macos, "_approval_target", lambda: (12827, None))
    readiness = iter([False, True])
    monkeypatch.setattr(macos, "daemon_browser_ready", lambda: next(readiness))
    _record_presses(monkeypatch, result="not-found")

    assert macos.approve_remote_debugging() == ("ready", None)


def _chrome_root(tmp_path, pid, port=9555):
    root = tmp_path / "Google Chrome"
    root.mkdir()
    os.symlink(f"host.local-{pid}", root / "SingletonLock")
    (root / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/fixture\n")
    return root


def test_approval_target_is_the_singleton_pid_listening_on_the_daemons_port(monkeypatch, tmp_path):
    pid = os.getpid()
    root = _chrome_root(tmp_path, pid)
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: root)
    monkeypatch.setattr(macos, "_daemon_target_profile", lambda: root)
    ports = []
    monkeypatch.setattr(macos, "_port_listener_pids", lambda port: ports.append(port) or {pid})

    assert macos._approval_target() == (pid, None)
    assert ports == [9555]


def test_approval_target_rejects_a_port_held_by_another_chrome(monkeypatch, tmp_path):
    root = _chrome_root(tmp_path, os.getpid())
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: root)
    monkeypatch.setattr(macos, "_daemon_target_profile", lambda: root)
    monkeypatch.setattr(macos, "_port_listener_pids", lambda port: {63433})

    pid, reason = macos._approval_target()

    assert pid is None
    assert "not the process listening" in reason


def test_approval_target_rejects_when_the_daemon_uses_another_profile(monkeypatch, tmp_path):
    root = _chrome_root(tmp_path, os.getpid())
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: root)
    monkeypatch.setattr(macos, "_daemon_target_profile", lambda: tmp_path / "Edge")
    monkeypatch.setattr(macos, "_port_listener_pids", lambda port: {os.getpid()})

    pid, reason = macos._approval_target()

    assert pid is None
    assert "Edge" in reason


def test_approval_target_counts_a_chrome_it_cannot_signal_as_running(monkeypatch, tmp_path):
    root = _chrome_root(tmp_path, 1)
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: root)
    monkeypatch.setattr(macos, "_daemon_target_profile", lambda: root)
    monkeypatch.setattr(macos, "_port_listener_pids", lambda port: {1})

    assert macos._approval_target() == (1, None)


def test_approval_target_rejects_a_stale_singleton_lock(monkeypatch, tmp_path):
    root = _chrome_root(tmp_path, 2**22 + 12345)
    monkeypatch.setattr(macos, "_google_chrome_root", lambda: root)

    pid, reason = macos._approval_target()

    assert pid is None
    assert "no running Google Chrome" in reason


def test_daemon_target_profile_is_the_first_live_profile(monkeypatch, tmp_path):
    first, second, third = (tmp_path / name for name in ("Chrome", "Canary", "Edge"))
    monkeypatch.setattr(macos, "PROFILES", [first, second, third])
    monkeypatch.setattr(macos, "_devtools_port_live", lambda base: base in (second, third))

    assert macos._daemon_target_profile() == second


def test_mac_approve_cli_treats_ready_as_success(monkeypatch, capsys):
    monkeypatch.setattr(macos, "approve_remote_debugging", lambda: ("ready", None))

    assert macos.run_cli([]) == 0
    assert capsys.readouterr().out == "ready\n"


def test_mac_approve_is_unavailable_off_macos(monkeypatch):
    monkeypatch.setattr(macos.platform, "system", lambda: "Linux")

    assert macos.approve_remote_debugging() == (
        "unsupported",
        "mac-approve is only available on macOS",
    )
