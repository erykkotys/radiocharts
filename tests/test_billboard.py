from radiocharts.sources.billboard import parse_billboard_text


def test_billboard_shape():
    lines = ["Billboard Hot 100™", "Week of August 15, 2026", "THIS WEEK", "LAST WEEK", "PEAK POS.", "WKS ON CHART"]
    for i in range(1, 101):
        lines += [str(i), f"Song {i}", f"Artist {i}", str(i), "1", str(i+5)]
    d = parse_billboard_text("\n".join(lines))
    assert len(d["entries"]) == 100
    assert d["chart_date"] == "2026-08-15"
    assert d["entries"][1]["previous_position"] == 2
    assert d["entries"][1]["reported_weeks"] == 7

from radiocharts.sources.billboard import parse_billboard_html


def test_billboard_dom_rows_scope_metadata():
    rows = []
    for i in range(1, 101):
        lw = "-" if i == 2 else str(max(1, i-1))
        rows.append(f'''<div class="o-chart-results-list-row-container">
          <ul class="o-chart-results-list-row">
            <li><span>{i}</span></li>
            <li><h3 id="title-of-a-story">Song {i}</h3><span class="c-label">Artist {i}</span></li>
            <li><span>Last Week</span><span>{lw}</span></li>
            <li><span>Peak Pos.</span><span>{i}</span></li>
            <li><span>Wks on Chart</span><span>{i+10}</span></li>
          </ul>
        </div>''')
    html = '<html><body><div>Week of August 15, 2026</div>' + ''.join(rows) + '</body></html>'
    d = parse_billboard_html(html)
    assert len(d['entries']) == 100
    assert d['entries'][0] == {
        'position': 1, 'title': 'Song 1', 'artist': 'Artist 1',
        'previous_position': 1, 'reported_peak': 1, 'reported_weeks': 11,
    }
    assert 'previous_position' not in d['entries'][1]
    assert d['entries'][1]['reported_peak'] == 2
    assert d['entries'][1]['reported_weeks'] == 12
