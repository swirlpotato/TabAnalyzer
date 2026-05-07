from __future__ import annotations

import json
import os
from urllib.parse import quote

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


def _youtube_player_url(origin: str, video_id: str) -> str:
    return f"{origin.rstrip('/')}/youtube-player?video_id={quote(video_id, safe='')}"


def _youtube_player_html(video_id: str, origin: str) -> str:
    safe_video_id = json.dumps(video_id)
    safe_origin = json.dumps(origin.rstrip("/"))
    return f"""
<!doctype html>
<html>
<head>
<meta name="referrer" content="strict-origin-when-cross-origin">
<style>
html, body, #player {{ width: 100%; height: 100%; margin: 0; background: #111; overflow: hidden; }}
</style>
</head>
<body>
<div id="player"></div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
const PLAYER_ORIGIN = {safe_origin};
let player = null;
let pending = null;
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
      onReady: function() {{ if (pending) {{ playAt(pending.seconds, pending.rate); pending = null; }} }},
      onError: function(event) {{ document.body.dataset.youtubeError = String(event.data); }}
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
