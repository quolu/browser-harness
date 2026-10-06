import ast
import json

from browser_harness import video_render


def test_start_export_downloads_into_webm_directory(tmp_path, monkeypatch):
    recording = tmp_path / "recording"
    recording.mkdir()
    webm = tmp_path / "exports" / "video.webm"
    captured = {}

    def fake_run_harness(code, timeout=30):
        captured["code"] = code
        return {"preflight": {}, "clicks": [], "started": True}

    monkeypatch.setattr(video_render, "run_harness", fake_run_harness)

    video_render._start_export(recording, "http://127.0.0.1:9/video.html", webm)

    assert webm.parent.is_dir()
    assignment = next(node for node in ast.parse(captured["code"]).body if isinstance(node, ast.Assign))
    payload = json.loads(ast.literal_eval(assignment.value.args[0]))
    assert payload["downloadPath"] == str(webm.parent.resolve())
    assert payload["filename"] == webm.name
