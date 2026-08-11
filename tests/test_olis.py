from radiocharts.sources.olis import parse_olis_html


def test_parse_olis_table():
    rows = "".join(
        f"<tr><td></td><td>{i}</td><td>Title {i}</td><td>Artist {i}</td><td>Label</td><td>Info</td></tr>"
        for i in range(1, 21)
    )
    html = f"""
    <html><body>
    <div>zmień zakres od–do: &lt; 01.08.2026 07.08.2026 &gt;</div>
    <table>
      <thead><tr><th>okładka</th><th>pozycja</th><th>tytuł</th><th>wykonawca</th><th>wydawca / dystrybutor</th><th>informacje</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </body></html>
    """
    data = parse_olis_html(html, "OLIA")
    assert data["chart_date"] == "2026-08-07"
    assert data["issue_key"] == "2026-08-01_2026-08-07"
    assert len(data["entries"]) == 20
    assert data["entries"][0]["artist"] == "Artist 1"
