from __future__ import annotations

import json
import os
from urllib.parse import quote, urlencode

from PyQt6.QtCore import Qt


YOUTUBE_VIEW_WIDTH = 356
YOUTUBE_VIEW_HEIGHT = 200
YOUTUBE_VIEW_PIP_MARGIN = 12


def _allow_qt_webengine_autoplay() -> None:
    flag = "--autoplay-policy=no-user-gesture-required"
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if flag not in existing.split():
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{existing} {flag}".strip()


def _set_webengine_autoplay_allowed(settings, settings_class) -> None:
    try:
        settings.setAttribute(settings_class.WebAttribute.PlaybackRequiresUserGesture, False)
    except Exception:
        return


def _make_youtube_view_non_interactive(view) -> None:
    view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)


def _set_youtube_view_size(view) -> None:
    view.setFixedSize(YOUTUBE_VIEW_WIDTH, YOUTUBE_VIEW_HEIGHT)


def _youtube_player_url(origin: str, video_id: str, status_message: str = "") -> str:
    query = {"video_id": video_id}
    if status_message:
        query["status"] = status_message
    return f"{origin.rstrip('/')}/youtube-player?{urlencode(query, quote_via=quote)}"


def _youtube_video_candidates(youtube: dict) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        video_id = str(value or "").strip()
        if not video_id or video_id in seen:
            return
        candidates.append(video_id)
        seen.add(video_id)

    add(youtube.get("default_video_id"))
    videos = youtube.get("videos")
    if not isinstance(videos, list):
        return candidates
    for video in videos:
        if not isinstance(video, dict):
            continue
        status = str(video.get("status") or "").strip()
        if status and status != "done":
            continue
        add(video.get("video_id") or video.get("videoId"))
    return candidates


def _youtube_player_html(video_id: str, origin: str, status_message: str = "") -> str:
    safe_video_id = json.dumps(video_id)
    safe_origin = json.dumps(origin.rstrip("/"))
    safe_status = json.dumps(status_message)
    return f"""
<!doctype html>
<html>
<head>
<meta name="referrer" content="strict-origin-when-cross-origin">
<style>
html, body, #player {{ width: 100%; height: 100%; margin: 0; background: #111; overflow: hidden; }}
body {{ position: relative; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
#status {{
  position: absolute;
  inset: 0;
  z-index: 10;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 18px;
  box-sizing: border-box;
  color: #f8fafc;
  background: rgba(17, 24, 39, 0.78);
  font-size: 14px;
  font-weight: 700;
  text-align: center;
  line-height: 1.35;
}}
</style>
</head>
<body>
<div id="player"></div>
<div id="status"></div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
const PLAYER_ORIGIN = {safe_origin};
const PLAYER_VIDEO_ID = {safe_video_id};
const INITIAL_STATUS = {safe_status};
document.body.dataset.youtubeVideoId = PLAYER_VIDEO_ID;
let player = null;
let pending = null;
function setStatus(message) {{
  const status = document.getElementById('status');
  if (!status) return;
  if (!message) {{
    status.textContent = '';
    status.style.display = 'none';
    return;
  }}
  status.textContent = message;
  status.style.display = 'flex';
}}
setStatus(INITIAL_STATUS);
function onYouTubeIframeAPIReady() {{
  player = new YT.Player('player', {{
    host: 'https://www.youtube-nocookie.com',
    width: '100%',
    height: '100%',
    videoId: {safe_video_id},
    playerVars: {{
      enablejsapi: 1,
      origin: PLAYER_ORIGIN,
      widget_referrer: PLAYER_ORIGIN,
      playsinline: 1,
      rel: 0,
      modestbranding: 1
    }},
    events: {{
      onReady: function() {{ document.body.dataset.youtubeReady = '1'; setStatus(''); if (pending) {{ playAt(pending.seconds, pending.rate); pending = null; }} }},
      onError: function(event) {{ document.body.dataset.youtubeError = String(event.data); document.body.dataset.youtubeErrorVideoId = PLAYER_VIDEO_ID; }}
    }}
  }});
}}
function ready() {{ return player && player.seekTo && player.playVideo; }}
function playAt(seconds, rate) {{
  if (!ready()) {{ pending = {{ seconds: seconds, rate: rate }}; return; }}
  try {{ player.setPlaybackRate(rate); }} catch (e) {{}}
  player.seekTo(seconds, true);
  player.playVideo();
}}
function seekToSeconds(seconds) {{
  if (!ready()) return;
  player.seekTo(seconds, true);
}}
function setRate(rate) {{
  if (!ready()) return;
  try {{ player.setPlaybackRate(rate); }} catch (e) {{}}
}}
function pauseVideo() {{
  if (!ready()) return;
  player.pauseVideo();
}}
</script>
</body>
</html>
"""
