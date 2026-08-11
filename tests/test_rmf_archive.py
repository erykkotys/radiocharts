from types import SimpleNamespace

from radiocharts.sources import rmf


class FakeResponse:
    def __init__(self, html: str, url: str, status_code: int = 200):
        self.text = html
        self.url = url
        self.status_code = status_code
        self.ok = 200 <= status_code < 400


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response


def _html(issue: int, date: str = "2026-08-04") -> str:
    rows = "".join(
        f"<div>{i}</div><div>Artist {i}</div><div>Title {i}</div>" for i in range(1, 21)
    )
    return f"<html><body><div>{issue} / {date}</div>{rows}<div>PROPOZYCJE</div></body></html>"


def test_archive_uses_stable_issue_path():
    issue = 6178
    response = FakeResponse(_html(issue), f"https://www.rmf.fm/poplista,{issue}.html")
    session = FakeSession(response)
    current = FakeResponse(_html(6182, "2026-08-10"), rmf.CURRENT_URL)

    got, attempts = rmf._request_archive(session, current, issue, 10)

    assert session.urls[0] == f"https://www.rmf.fm/poplista,{issue}.html"
    assert got is response
    assert attempts[0]["detected"] == issue
