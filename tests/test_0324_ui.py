from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "radiocharts" / "app.py").read_text(encoding="utf-8")


def test_0324_player_moves_down_50px():
    assert "bottom:75px" in APP
    assert "bottom:125px" not in APP


def test_0324_wide_grids_duplicate_horizontal_scrollbar_under_header():
    assert "TOP_HSCROLL_INSTALLER" in APP
    assert "rc-top-hscroll" in APP
    assert "parent.insertBefore(bar, header.nextSibling)" in APP
    assert APP.count("floating_hscroll=True") >= 2


def test_0324_dashboard_count_shares_filter_row():
    assert "ctl_count, ctl_period, ctl_scope, ctl_status, ctl_dl, ctl_layout, ctl_fam, ctl_mom, ctl_unheard = st.columns" in APP
    assert "dashboard_count_slot = ctl_count.empty()" in APP
    assert "Utwory (filtr / okres)" in APP
