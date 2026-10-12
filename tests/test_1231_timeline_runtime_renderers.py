from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def _function_block(name: str, next_name: str) -> str:
    start = APP.index(f"def {name}(")
    end = APP.index(f"def {next_name}(", start)
    return APP[start:end]


def test_schedule_timeline_renderer_does_not_reference_compare_only_runtime_vars():
    block = _function_block("_local_timeline_row_html", "_local_with_toh_separators")
    assert "runtime_override" not in block
    assert "runtime_delta" not in block
    assert 'runtime = str(row.get("runtime_raw") or "")' in block
    assert "runtime_html = html.escape(runtime)" in block


def test_compare_renderer_initializes_runtime_html_with_override_and_delta():
    block = _function_block("_local_log_row_html", "_local_compare_pair_html")
    assert 'runtime = str(runtime_override or row.get("runtime_raw") or "")' in block
    assert "runtime_html = html.escape(runtime)" in block
    assert "if runtime_delta:" in block
    assert "rc-log-runtime-delta" in block
