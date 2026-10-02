"""macOS-only helpers for local Chrome automation."""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
from pathlib import Path

from .admin import daemon_browser_ready
from .daemon import PROFILES, _devtools_port_live, remote_debugging_toggle_profiles, singleton_pid
from .macos_ax import AccessibilityDenied, press_allow_sheet

# Chrome localizes the per-connection sheet, so the sheet cannot be matched by
# English literals. These are Chromium's own strings for
# IDS_DEV_TOOLS_CONNECTION_DIALOG_TITLE and IDS_DEV_TOOLS_CONNECTION_DIALOG_ALLOW_TEXT
# (chrome/app/generated_resources.grd and resources/generated_resources_<locale>.xtb).
# BH_ALLOW_SHEET_TITLES and BH_ALLOW_LABELS (comma-separated) extend the tables for
# a Chrome UI language that is not listed.
ALLOW_SHEET_TITLES = (
    "Allow remote debugging?",  # en
    "リモート デバッグを許可しますか？",  # ja
    "要允许远程调试吗？",  # zh-CN
    "允許遠端偵錯嗎？",  # zh-TW
    "원격 디버깅을 허용하시겠습니까?",  # ko
    "Remote-Fehlerbehebung zulassen?",  # de
    "Autoriser le débogage à distance ?",  # fr
    "¿Permitir depuración remota?",  # es
    "¿Deseas permitir la depuración remota?",  # es-419
    "Permitir a depuração remota?",  # pt-BR
    "Permitir depuração remota?",  # pt-PT
    "Vuoi consentire il debug remoto?",  # it
    "Foutopsporing op afstand toestaan?",  # nl
    "Czy zezwalać na debugowanie zdalne?",  # pl
    "Разрешить удаленную отладку?",  # ru
    "Дозволити дистанційне налагодження?",  # uk
    "Povolit vzdálené ladění?",  # cs
    "Uzaktan hata ayıklamaya izin verilsin mi?",  # tr
    "Cho phép gỡ lỗi từ xa?",  # vi
    "อนุญาตให้ใช้การแก้ไขข้อบกพร่องจากระยะไกลใช่ไหม",  # th
    "Izinkan proses debug jarak jauh?",  # id
    "السماح بتصحيح الأخطاء عن بُعد؟",  # ar
    "לאפשר ניפוי באגים מרחוק?",  # he
    "क्या आपको बाहरी ऐप्लिकेशन के ज़रिए डिबग करने की अनुमति देनी है?",  # hi
    "Vill du tillåta fjärrfelsökning?",  # sv
    "Vil du tillade ekstern fejlretning?",  # da
    "Vil du tillate ekstern feilsøking?",  # nb
    "Sallitaanko vianetsintä etänä?",  # fi
    "Να επιτρέπεται η απομακρυσμένη αποσφαλμάτωση;",  # el
)

ALLOW_BUTTON_LABELS = (
    "Allow",  # en
    "許可する",  # ja
    "允许",  # zh-CN
    "允許",  # zh-TW
    "허용",  # ko
    "Zulassen",  # de
    "Autoriser",  # fr
    "Permitir",  # es, es-419, pt-BR, pt-PT
    "Consenti",  # it
    "Toestaan",  # nl
    "Zezwalaj",  # pl
    "Разрешить",  # ru
    "Дозволити",  # uk
    "Povolit",  # cs
    "İzin ver",  # tr
    "Cho phép",  # vi
    "อนุญาต",  # th
    "Izinkan",  # id
    "سماح",  # ar
    "זה בסדר",  # he
    "अनुमति दें",  # hi
    "Tillåt",  # sv
    "Tillad",  # da
    "Tillat",  # nb
    "Salli",  # fi
    "Επιτρέπεται",  # el
)

_NON_LOCAL_BROWSER_ENV = ("BU_CDP_WS", "BU_CDP_URL", "BU_BROWSER_ID")

_ACCESSIBILITY_DETAIL = (
    "allow the app launching browser-harness (for example Terminal, iTerm, or Codex) "
    "in System Settings > Privacy & Security > Accessibility"
)


def _extra_strings(env_name: str) -> tuple[str, ...]:
    raw = os.environ.get(env_name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def allow_sheet_titles() -> tuple[str, ...]:
    return ALLOW_SHEET_TITLES + _extra_strings("BH_ALLOW_SHEET_TITLES")


def allow_button_labels() -> tuple[str, ...]:
    return ALLOW_BUTTON_LABELS + _extra_strings("BH_ALLOW_LABELS")


def _google_chrome_root() -> Path:
    return Path.home() / "Library/Application Support/Google/Chrome"


def _google_chrome_toggle_enabled() -> bool:
    """Only accept the toggle from the Google Chrome root."""
    return _google_chrome_root() in remote_debugging_toggle_profiles()


def _devtools_port(root: Path) -> int | None:
    try:
        return int((root / "DevToolsActivePort").read_text(encoding="utf-8", errors="replace").splitlines()[0].strip())
    except (OSError, ValueError, IndexError):
        return None


def _daemon_target_profile() -> Path | None:
    """The profile a local daemon connects to: the first one with a live DevTools port, as in get_ws_url()."""
    return next((base for base in PROFILES if _devtools_port_live(base)), None)


def _port_listener_pids(port: int) -> set[int] | None:
    try:
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return {int(line) for line in completed.stdout.split()}
    except ValueError:
        return None


def _approval_target() -> tuple[int | None, str | None]:
    """The pid whose sheet may be answered, or why none can be.

    The pid must hold the Google Chrome root (SingletonLock), that root must be
    the profile the daemon connects to, and the pid must be the process
    listening on the root's DevTools port. Anything else would answer another
    browser's prompt.
    """
    root = _google_chrome_root()
    pid = singleton_pid(root)
    if pid is None:
        return None, f"no running Google Chrome holds {root}"
    target = _daemon_target_profile()
    if target != root:
        return None, f"the daemon connects to {target or 'no local profile'}, not {root}"
    port = _devtools_port(root)
    listeners = _port_listener_pids(port) if port else None
    if not listeners or pid not in listeners:
        return None, f"Google Chrome pid {pid} is not the process listening on the DevTools port of {root}"
    return pid, None


def approve_remote_debugging() -> tuple[str, str | None]:
    """Press Chrome's exact per-connection Allow sheet on the instance the daemon waits on, without activating Chrome."""
    if platform.system() != "Darwin":
        return "unsupported", "mac-approve is only available on macOS"

    if daemon_browser_ready():
        return "ready", None

    if not _google_chrome_toggle_enabled():
        return (
            "setup-required",
            'first enable "Allow remote debugging for this browser instance" at '
            "chrome://inspect/#remote-debugging, then run `browser-harness mac-approve` again",
        )

    if configured := [name for name in _NON_LOCAL_BROWSER_ENV if os.environ.get(name)]:
        return "unsupported", f"mac-approve answers only local Google Chrome; {configured[0]} is set"

    pid, reason = _approval_target()
    if pid is None:
        if daemon_browser_ready():
            return "ready", None
        return "not-found", f"{reason}; retry the browser command and run `browser-harness mac-approve` when the prompt appears"

    try:
        status = press_allow_sheet(pid, allow_sheet_titles(), allow_button_labels())
    except AccessibilityDenied:
        return "accessibility-required", _ACCESSIBILITY_DETAIL
    except (OSError, AttributeError, TypeError, ValueError, ctypes.ArgumentError) as exc:
        return "error", f"{type(exc).__name__}: {exc}"

    if status == "ready":
        return "ready", None
    # The user may have accepted the sheet while it was being looked up.
    if daemon_browser_ready():
        return "ready", None
    return (
        "not-found",
        "retry the browser command and run `browser-harness mac-approve` when the prompt appears",
    )


def run_cli(args: list[str]) -> int:
    if args:
        print("usage: browser-harness mac-approve", flush=True)
        return 2

    status, detail = approve_remote_debugging()
    if detail:
        print(f"{status}: {detail}", flush=True)
    else:
        print(status, flush=True)
    return 0 if status == "ready" else 1
