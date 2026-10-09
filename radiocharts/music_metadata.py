from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from radiocharts.db import (
    normalize,
    save_external_song_metadata,
    songs_missing_external_metadata,
)

MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
LB_SPOTIFY_BY_MBID_URL = "https://labs.api.listenbrainz.org/spotify-id-from-mbid/json"
LB_SPOTIFY_BY_METADATA_URL = "https://labs.api.listenbrainz.org/spotify-id-from-metadata/json"
USER_AGENT = "RadioCharts/1.2.26 (music metadata enrichment; non-commercial local research tool)"


@dataclass(frozen=True)
class RecordingMatch:
    mbid: str = ""
    release_date: str = ""
    release_precision: str = ""
    score: int = 0


def _quoted(value: str) -> str:
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _base_title(value: str) -> str:
    text = str(value or "")
    # Version/remaster/live suffixes vary wildly across sources.  Keep the full
    # title for the MusicBrainz query, but use a less brittle key for validation.
    text = re.sub(r"\s*[\[(](?:radio edit|edit|remaster(?:ed)?(?: \d{4})?|version|single version|album version)[^\])]*[\])]\s*$", "", text, flags=re.I)
    return normalize(text)


def _artist_credit_text(recording: dict[str, Any]) -> str:
    out: list[str] = []
    for item in recording.get("artist-credit") or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(str(item.get("name") or (item.get("artist") or {}).get("name") or ""))
            out.append(str(item.get("joinphrase") or ""))
    return "".join(out).strip()


def _match_score(recording: dict[str, Any], artist: str, title: str) -> int:
    api_score = int(recording.get("score") or 0)
    want_title = _base_title(title)
    got_title = _base_title(str(recording.get("title") or ""))
    want_artist = normalize(artist)
    got_artist = normalize(_artist_credit_text(recording))

    score = api_score
    if want_title and got_title == want_title:
        score += 35
    elif want_title and got_title and (want_title in got_title or got_title in want_title):
        score += 15
    else:
        score -= 30

    wanted_tokens = {x for x in want_artist.split() if len(x) >= 3}
    got_tokens = set(got_artist.split())
    overlap = len(wanted_tokens & got_tokens)
    if want_artist and got_artist == want_artist:
        score += 25
    elif overlap >= 2:
        score += 14
    elif overlap == 1:
        score += 6
    else:
        score -= 20
    return score


def lookup_musicbrainz_recording(artist: str, title: str, *, isrc: str = "", timeout: float = 12.0) -> RecordingMatch | None:
    """Return a conservative MusicBrainz recording match and earliest release date."""
    if not str(artist or "").strip() or not str(title or "").strip():
        return None
    clean_isrc = re.sub(r"[^A-Za-z0-9]", "", str(isrc or "")).upper()
    # ISRC is the strongest identifier we normally have in the local catalogue.
    # MusicBrainz supports it directly in the recording search index; fall back
    # to artist+title only when it is unavailable.
    query = f"isrc:{clean_isrc}" if clean_isrc else f"recording:{_quoted(title)} AND artist:{_quoted(artist)}"
    response = requests.get(
        MUSICBRAINZ_SEARCH_URL,
        params={"query": query, "fmt": "json", "limit": 6},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    recordings = response.json().get("recordings") or []
    if not recordings:
        return None
    best = max(recordings, key=lambda row: _match_score(row, artist, title))
    score = _match_score(best, artist, title)
    # Below this threshold a wrong old recording is worse than no date at all.
    if score < 95:
        return None
    release = str(best.get("first-release-date") or "").strip()
    precision = ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", release):
        precision = "day"
    elif re.fullmatch(r"\d{4}-\d{2}", release):
        precision = "month"
    elif re.fullmatch(r"\d{4}", release):
        precision = "year"
    else:
        release = ""
    return RecordingMatch(
        mbid=str(best.get("id") or ""),
        release_date=release,
        release_precision=precision,
        score=score,
    )


def _spotify_id_from_response(payload: Any) -> str:
    if not isinstance(payload, list):
        return ""
    for row in payload:
        if not isinstance(row, dict):
            continue
        ids = row.get("spotify_track_ids") or []
        for track_id in ids:
            track_id = str(track_id or "").strip()
            if re.fullmatch(r"[A-Za-z0-9]{15,30}", track_id):
                return track_id
    return ""


def spotify_id_from_mbid(mbid: str, *, timeout: float = 12.0) -> str:
    if not mbid:
        return ""
    response = requests.post(
        LB_SPOTIFY_BY_MBID_URL,
        json=[{"recording_mbid": str(mbid)}],
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return _spotify_id_from_response(response.json())


def spotify_id_from_metadata(artist: str, title: str, release_name: str = "", *, timeout: float = 12.0) -> str:
    if not str(artist or "").strip() or not str(title or "").strip():
        return ""
    response = requests.post(
        LB_SPOTIFY_BY_METADATA_URL,
        json=[{
            "artist_name": str(artist).strip(),
            "track_name": str(title).strip(),
            "release_name": str(release_name or "").strip(),
        }],
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return _spotify_id_from_response(response.json())


def resolve_spotify_url(artist: str, title: str, mbid: str = "") -> str:
    """Resolve an exact Spotify track URL through the public ListenBrainz index."""
    track_id = ""
    if mbid:
        try:
            track_id = spotify_id_from_mbid(mbid)
        except Exception:
            track_id = ""
    if not track_id:
        track_id = spotify_id_from_metadata(artist, title)
    return f"https://open.spotify.com/track/{track_id}" if track_id else ""


def enrich_missing_metadata(limit: int = 10, *, musicbrainz_delay: float = 1.05) -> dict[str, int]:
    """Fill missing release dates and cache exact Spotify track URLs.

    MusicBrainz explicitly limits clients to one request per second, so this is a
    deliberately small incremental job.  Candidate/Watch songs are prioritised by
    the DB query, then the newest remaining catalogue rows.
    """
    rows = songs_missing_external_metadata(limit=max(1, int(limit)))
    result = {"checked": 0, "release_dates": 0, "spotify_urls": 0, "misses": 0, "errors": 0}
    for idx, row in enumerate(rows):
        result["checked"] += 1
        song_id = int(row["song_id"])
        artist = str(row.get("artist") or "")
        title = str(row.get("title") or "")
        release_date = str(row.get("release_date") or "").strip()
        mbid = str(row.get("musicbrainz_recording_mbid") or "").strip()
        spotify_url = str(row.get("spotify_url") or "").strip()
        match: RecordingMatch | None = None
        last_error = ""

        try:
            if not mbid or not release_date:
                match = lookup_musicbrainz_recording(artist, title, isrc=str(row.get("isrc") or ""))
                if match:
                    mbid = match.mbid or mbid
                    if not release_date and match.release_date:
                        release_date = match.release_date
                        result["release_dates"] += 1
                # Respect MusicBrainz's <=1 request/s application limit.
                if idx < len(rows) - 1 and musicbrainz_delay > 0:
                    time.sleep(float(musicbrainz_delay))
        except Exception as exc:
            last_error = f"MusicBrainz: {type(exc).__name__}: {exc}"[:500]
            result["errors"] += 1

        spotify_id = str(row.get("spotify_track_id") or "").strip()
        if not spotify_url:
            try:
                if mbid:
                    spotify_id = spotify_id_from_mbid(mbid)
                if not spotify_id:
                    spotify_id = spotify_id_from_metadata(artist, title)
                if spotify_id:
                    spotify_url = f"https://open.spotify.com/track/{spotify_id}"
                    result["spotify_urls"] += 1
            except Exception as exc:
                if not last_error:
                    last_error = f"ListenBrainz: {type(exc).__name__}: {exc}"[:500]
                result["errors"] += 1

        if not release_date and not spotify_url:
            result["misses"] += 1

        save_external_song_metadata(
            song_id,
            musicbrainz_recording_mbid=mbid or None,
            spotify_track_id=spotify_id or None,
            spotify_url=spotify_url or None,
            release_date=release_date or None,
            release_date_source="MusicBrainz" if match and match.release_date else None,
            release_date_precision=match.release_precision if match and match.release_date else None,
            release_checked=True,
            spotify_checked=True,
            last_error=last_error,
        )
    return result
