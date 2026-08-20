from pathlib import Path

import radiocharts.job_manager as job_manager
import radiocharts.job_runner as job_runner


def test_source_summary_counts_expected_errors():
    messages = [
        "RMF 1: OK (20 pozycji)",
        "RMF 2: TimeoutError: boom",
        "RMF 3: OK (20 pozycji)",
    ]
    assert job_runner._source_summary(messages, 4) == {
        "requested": 4,
        "ok": 2,
        "errors": 2,
        "reported_messages": 3,
    }


def test_append_log_persists_multiline_entry(tmp_path, monkeypatch):
    path = tmp_path / "abc.log"
    monkeypatch.setattr(job_runner, "_LOG_PATH", path)
    job_runner._append_log("ERROR", "OLIA: Timeout\nCall log:\n- body")
    text = path.read_text(encoding="utf-8")
    assert "[ERROR] OLIA: Timeout" in text
    assert "    Call log:" in text
    assert "    - body" in text


def test_read_job_log_can_return_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(job_manager, "JOB_DIR", tmp_path)
    path = tmp_path / "abc.log"
    path.write_text("first line\n" + ("x" * 200) + "\nlast line\n", encoding="utf-8")
    full = job_manager.read_job_log("abc")
    tail = job_manager.read_job_log("abc", max_bytes=40)
    assert full.startswith("first line")
    assert "last line" in tail
    assert "wcześniejsze wpisy" in tail
