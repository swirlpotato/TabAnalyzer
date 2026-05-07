"""Songsterr search and official Guitar Pro export helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import unescape
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request


SONGSTERR_BASE_URL = "https://www.songsterr.com"
USER_AGENT = "Mozilla/5.0"
COOKIE_STORE_PATH = Path.home() / ".tab_analyzer" / "songsterr_session.json"

_PROD_PART_HOSTS = ("dqsljvtekg760", "d34shlm8p2ums2", "d3cqchs6g3b5ew")
_LEGACY_PART_HOSTS = ("d3rrfvx08uyjp1", "dodkcbujl0ebx", "dj1usja78sinh")
_STAGE_PART_HOST = "d3d3l6a6rcgkaf"


@dataclass(frozen=True)
class SongsterrResult:
    song_id: int
    artist: str
    title: str
    url: str
    default_track: int | None = None
    popular_track: int | None = None
    difficulty: int | None = None
    track_count: int = 0
    guitar_track_count: int = 0

    @property
    def display_label(self) -> str:
        track_text = f"{self.guitar_track_count} guitar / {self.track_count} tracks"
        difficulty = f", diff {self.difficulty}" if self.difficulty else ""
        return f"{self.artist} - {self.title} ({track_text}{difficulty}, s{self.song_id})"


class SongsterrError(RuntimeError):
    """Base class for Songsterr integration failures."""


class SongsterrAuthError(SongsterrError):
    """Raised when Songsterr requires a logged-in/authorized session."""


def details_path_for_gp(path: str | Path) -> Path:
    gp_path = Path(path)
    return gp_path.with_name(f"{gp_path.stem}_details.json")


def load_cookie_header(path: str | Path = COOKIE_STORE_PATH) -> str | None:
    cookie_path = Path(path)
    if not cookie_path.exists():
        return None
    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cookie = data.get("cookie")
    return str(cookie) if cookie else None


def save_cookie_header(cookie: str, path: str | Path = COOKIE_STORE_PATH) -> Path:
    cookie = cookie.strip()
    if not cookie:
        raise SongsterrError("Songsterr login cookie is empty.")
    cookie_path = Path(path)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(json.dumps({"cookie": cookie}, ensure_ascii=False, indent=2), encoding="utf-8")
    return cookie_path


def search_tabs(query: str, limit: int = 20) -> tuple[SongsterrResult, ...]:
    query = " ".join(query.split())
    if not query:
        return ()

    url = f"{SONGSTERR_BASE_URL}/?{urllib.parse.urlencode({'pattern': query})}"
    html = _http_get_text(url)
    state = _extract_state(html)
    raw_results = state.get("songs", {}).get("songs", {}).get("list", [])
    link_by_song_id = _extract_song_links(html)

    results: list[SongsterrResult] = []
    seen: set[int] = set()
    for raw in raw_results:
        song_id = _as_int(raw.get("songId"))
        if song_id is None or song_id in seen:
            continue
        seen.add(song_id)

        tracks = raw.get("tracks") if isinstance(raw.get("tracks"), list) else []
        guitar_count = sum(1 for track in tracks if _is_guitar_track(track))
        result_url = link_by_song_id.get(song_id) or _fallback_song_url(raw, song_id)
        results.append(
            SongsterrResult(
                song_id=song_id,
                artist=str(raw.get("artist") or "Unknown Artist"),
                title=str(raw.get("title") or f"Song {song_id}"),
                url=result_url,
                default_track=_as_int(raw.get("defaultTrack")),
                popular_track=_as_int(raw.get("popularTrack")),
                difficulty=_as_int(raw.get("difficulty")),
                track_count=len(tracks),
                guitar_track_count=guitar_count,
            )
        )
        if len(results) >= limit:
            break
    return tuple(results)


def download_guitar_pro(
    result: SongsterrResult,
    output_dir: str | Path,
    cookie: str | None = None,
) -> Path:
    """Download a Songsterr result through Songsterr's official GP export API."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    meta = _load_meta(result.song_id)
    parts = _load_parts(meta)
    lyrics = _load_lyrics_if_needed(meta, parts)
    exported = _export_guitar_pro(meta, parts, lyrics, cookie=cookie)
    if not _looks_like_guitar_pro(exported):
        raise SongsterrError("Songsterr did not return a Guitar Pro file.")

    file_path = _unique_path(output_path / _export_filename(meta))
    file_path.write_bytes(exported)
    _write_details_file(file_path, result, meta)
    return file_path


def load_details_file(path: str | Path) -> dict:
    details_path = details_path_for_gp(path)
    if not details_path.exists():
        return {}
    try:
        data = json.loads(details_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_details_file(file_path: Path, result: SongsterrResult, meta: dict) -> Path:
    details = _songsterr_details(result, meta)
    details_path = details_path_for_gp(file_path)
    details_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    return details_path


def _songsterr_details(result: SongsterrResult, meta: dict) -> dict:
    videos = _youtube_videos(meta)
    default_video = _default_youtube_video(videos)
    youtube: dict[str, object] = {
        "videos": videos,
        "sync": {
            "offset_seconds": 0.0,
        },
    }
    if default_video is not None:
        youtube["default_video_id"] = default_video["video_id"]
        youtube["default_video_url"] = default_video["url"]
    return {
        "source": "songsterr",
        "songsterr": {
            "song_id": _as_int(meta.get("songId")) or result.song_id,
            "revision_id": _as_int(meta.get("revisionId")),
            "artist": str(meta.get("artist") or result.artist),
            "title": str(meta.get("title") or result.title),
            "url": result.url,
            "default_track": _as_int(meta.get("defaultTrack")) if meta.get("defaultTrack") is not None else result.default_track,
            "popular_track": _as_int(meta.get("popularTrack")) if meta.get("popularTrack") is not None else result.popular_track,
        },
        "youtube": youtube,
    }


def _youtube_videos(meta: dict) -> list[dict]:
    raw_videos = meta.get("videos")
    if not isinstance(raw_videos, list):
        return []
    videos: list[dict] = []
    for raw in raw_videos:
        if not isinstance(raw, dict):
            continue
        video_id = str(raw.get("videoId") or "").strip()
        if not video_id:
            continue
        videos.append(
            {
                "id": _as_int(raw.get("id")),
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "status": str(raw.get("status") or ""),
                "feature": raw.get("feature"),
            }
        )
    return videos


def _default_youtube_video(videos: list[dict]) -> dict | None:
    if not videos:
        return None
    for video in videos:
        if video.get("status") == "done" and video.get("feature") is None:
            return video
    for video in videos:
        if video.get("status") == "done":
            return video
    return videos[0]


def _extract_state(html: str) -> dict:
    match = re.search(r'<script[^>]+id=["\']state["\'][^>]*>(.*?)</script>', html, flags=re.S | re.I)
    if not match:
        raise SongsterrError("Songsterr search state was not found.")
    try:
        state = json.loads(unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise SongsterrError("Songsterr search state could not be parsed.") from exc
    return state if isinstance(state, dict) else {}


def _extract_song_links(html: str) -> dict[int, str]:
    links: dict[int, str] = {}
    for raw_link in re.findall(r'href=["\']([^"\']*tab-s\d+[^"\']*)["\']', html):
        match = re.search(r"tab-s(\d+)", raw_link)
        if not match:
            continue
        song_id = int(match.group(1))
        if song_id in links:
            continue
        links[song_id] = urllib.parse.urljoin(SONGSTERR_BASE_URL, unescape(raw_link))
    return links


def _load_meta(song_id: int) -> dict:
    return _http_get_json(f"{SONGSTERR_BASE_URL}/api/meta/{song_id}")


def _load_parts(meta: dict) -> list[dict]:
    song_id = int(meta["songId"])
    revision_id = int(meta["revisionId"])
    image = meta.get("image")
    tracks = meta.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise SongsterrError("Songsterr metadata does not contain tracks.")

    parts: list[dict] = []
    for index, track in enumerate(tracks):
        part_id = _as_int(track.get("partId")) if isinstance(track, dict) else None
        if part_id is None:
            part_id = index
        parts.append(_http_get_json(_part_url(song_id, revision_id, part_id, image)))
    return parts


def _load_lyrics_if_needed(meta: dict, parts: list[dict]) -> list[dict]:
    if not meta.get("lyrics"):
        return []
    needs_legacy_lyrics = any(
        part.get("withLyrics") and not _first_new_lyrics_text(part)
        for part in parts
        if isinstance(part, dict)
    )
    if not needs_legacy_lyrics:
        return []
    lyrics = _http_get_json(_lyrics_url(int(meta["songId"]), int(meta["revisionId"]), meta.get("image")))
    return lyrics if isinstance(lyrics, list) else []


def _export_guitar_pro(
    meta: dict,
    parts: list[dict],
    lyrics: list[dict],
    cookie: str | None,
) -> bytes:
    body = json.dumps(
        {
            "songId": int(meta["songId"]),
            "revisionId": int(meta["revisionId"]),
            "parts": parts,
            "lyrics": [json.dumps(item, separators=(",", ":")) for item in lyrics],
            "midi": False,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/octet-stream",
        "Content-Type": "application/json",
    }
    if cookie:
        headers["Cookie"] = cookie

    try:
        return _http_request_bytes(
            f"{SONGSTERR_BASE_URL}/api/edits/download",
            data=body,
            headers=headers,
            method="POST",
            timeout=180,
        )
    except urllib.error.HTTPError as exc:
        payload = _decode_error_payload(exc)
        if exc.code in (401, 403):
            raise SongsterrAuthError(
                "Songsterr Guitar Pro export requires a logged-in account or export permission."
            ) from exc
        raise SongsterrError(f"Songsterr export failed ({exc.code}): {payload}") from exc


def _part_url(song_id: int, revision_id: int, part_id: int, image: object, attempt: int = 0) -> str:
    image_text = str(image) if image else ""
    if image_text.endswith("-stage"):
        return f"https://{_STAGE_PART_HOST}.cloudfront.net/{song_id}/{revision_id}/{image_text}/{part_id}.json"
    if image_text:
        host = _PROD_PART_HOSTS[attempt % len(_PROD_PART_HOSTS)]
        return f"https://{host}.cloudfront.net/{song_id}/{revision_id}/{image_text}/{part_id}.json"
    host = _LEGACY_PART_HOSTS[attempt % len(_LEGACY_PART_HOSTS)]
    return f"https://{host}.cloudfront.net/part/{revision_id}/{part_id}"


def _lyrics_url(song_id: int, revision_id: int, image: object, attempt: int = 0) -> str:
    image_text = str(image) if image else ""
    if image_text.endswith("-stage"):
        return f"https://{_STAGE_PART_HOST}.cloudfront.net/{song_id}/{revision_id}/{image_text}/lyrics.json"
    if image_text:
        host = _PROD_PART_HOSTS[attempt % len(_PROD_PART_HOSTS)]
        return f"https://{host}.cloudfront.net/{song_id}/{revision_id}/{image_text}/lyrics.json"
    host = _LEGACY_PART_HOSTS[attempt % len(_LEGACY_PART_HOSTS)]
    return f"https://{host}.cloudfront.net/lyrics/{revision_id}"


def _http_get_text(url: str) -> str:
    try:
        return _http_request_bytes(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}).decode("utf-8")
    except Exception:
        return _curl_get_text(url)


def _http_get_json(url: str) -> dict | list:
    data = _http_request_bytes(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    return json.loads(data.decode("utf-8"))


def _http_request_bytes(
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    timeout: int = 60,
) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        encoding = response.headers.get("Content-Encoding", "")
    if encoding == "gzip" or payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload)
    return payload


def _curl_get_text(url: str) -> str:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise SongsterrError("Songsterr page could not be fetched and curl was not found.")
    completed = subprocess.run(
        [
            curl,
            "-L",
            "--compressed",
            "-A",
            USER_AGENT,
            url,
        ],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SongsterrError(f"Songsterr page could not be fetched: {error}")
    return completed.stdout.decode("utf-8", errors="replace")


def _decode_error_payload(exc: urllib.error.HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return exc.reason
    return payload[:500] or exc.reason


def _looks_like_guitar_pro(data: bytes) -> bool:
    if len(data) < 8 or data.lstrip().startswith(b"{"):
        return False
    return data.startswith(b"PK") or data.startswith(b"FICHIER GUITAR PRO")


def _export_filename(meta: dict) -> str:
    artist = _sanitize_filename(str(meta.get("artist") or "Songsterr"))
    title = _sanitize_filename(str(meta.get("title") or f"song-{meta.get('songId', '')}"))
    date_text = _revision_date(meta.get("createdAt"))
    return f"{artist}-{title}-{date_text}.gp"


def _revision_date(value: object) -> str:
    if not value:
        return datetime.now().strftime("%m-%d-%Y")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%m-%d-%Y")
    except ValueError:
        return datetime.now().strftime("%m-%d-%Y")


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise SongsterrError(f"Could not create a unique filename for {path.name}.")


def _fallback_song_url(raw: dict, song_id: int) -> str:
    slug = _slugify(f"{raw.get('artist', '')}-{raw.get('title', '')}")
    return f"{SONGSTERR_BASE_URL}/a/wsa/{slug}-tab-s{song_id}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return slug.strip("-") or "songsterr-tab"


def _sanitize_filename(value: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text or "Songsterr"


def _is_guitar_track(track: object) -> bool:
    if not isinstance(track, dict):
        return False
    if track.get("isGuitar"):
        return True
    instrument_id = _as_int(track.get("instrumentId"))
    return instrument_id is not None and 24 <= instrument_id <= 31


def _first_new_lyrics_text(part: dict) -> str:
    new_lyrics = part.get("newLyrics")
    if not isinstance(new_lyrics, list) or not new_lyrics:
        return ""
    first = new_lyrics[0]
    if not isinstance(first, dict):
        return ""
    return str(first.get("text") or "")


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
