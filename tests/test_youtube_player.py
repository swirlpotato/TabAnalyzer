import os
import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from tab_analyzer.ui import (
    YouTubeTabPlayer,
    YOUTUBE_VIEW_HEIGHT,
    YOUTUBE_VIEW_WIDTH,
    _allow_qt_webengine_autoplay,
    _is_songsterr_ad_request_host,
    _make_youtube_view_non_interactive,
    _set_youtube_view_size,
    _youtube_player_html,
    _youtube_player_url,
    _youtube_video_candidates,
)
from tests.helpers import beat, measure, song_with_measures, tab_note

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeWebView:
    def __init__(self) -> None:
        self.attributes = {}
        self.focus_policy = None
        self.context_menu_policy = None
        self.fixed_size = None

    def setAttribute(self, attribute, enabled: bool) -> None:
        self.attributes[attribute] = enabled

    def setFocusPolicy(self, policy) -> None:
        self.focus_policy = policy

    def setContextMenuPolicy(self, policy) -> None:
        self.context_menu_policy = policy

    def setFixedSize(self, width: int, height: int) -> None:
        self.fixed_size = (width, height)


class FakePage:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def runJavaScript(self, script: str, *args) -> None:
        self.scripts.append(script)


class FakePlayerView:
    def __init__(self) -> None:
        self.fake_page = FakePage()

    def page(self) -> FakePage:
        return self.fake_page


class YouTubePlayerHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_player_html_includes_embed_origin_and_referrer(self):
        html = _youtube_player_html("abc123", "http://127.0.0.1:43210", "Changing")

        self.assertIn('meta name="referrer"', html)
        self.assertIn("enablejsapi: 1", html)
        self.assertIn("host: 'https://www.youtube-nocookie.com'", html)
        self.assertIn("origin: PLAYER_ORIGIN", html)
        self.assertIn("widget_referrer: PLAYER_ORIGIN", html)
        self.assertIn("setStatus(INITIAL_STATUS)", html)
        self.assertIn('"Changing"', html)
        self.assertIn('"http://127.0.0.1:43210"', html)
        self.assertIn('"abc123"', html)

    def test_player_url_is_served_from_local_origin(self):
        self.assertEqual(
            _youtube_player_url("http://127.0.0.1:43210", "abc 123"),
            "http://127.0.0.1:43210/youtube-player?video_id=abc%20123",
        )

    def test_player_url_can_include_status_message(self):
        self.assertEqual(
            _youtube_player_url("http://127.0.0.1:43210", "abc123", "다른 영상으로 변경 중입니다."),
            "http://127.0.0.1:43210/youtube-player?video_id=abc123&status=%EB%8B%A4%EB%A5%B8%20%EC%98%81%EC%83%81%EC%9C%BC%EB%A1%9C%20%EB%B3%80%EA%B2%BD%20%EC%A4%91%EC%9E%85%EB%8B%88%EB%8B%A4.",
        )

    def test_video_candidates_start_with_default_and_continue_with_alternatives_only(self):
        self.assertEqual(
            _youtube_video_candidates(
                {
                    "default_video_id": "main",
                    "videos": [
                        {"video_id": "backing", "status": "done"},
                        {"video_id": "alt", "status": "done", "feature": "alternative"},
                        {"video_id": "main", "status": "done"},
                        {"video_id": "pending", "status": "processing"},
                        {"videoId": "legacy", "status": "done", "feature": "alternative"},
                    ],
                }
            ),
            ["main", "alt", "legacy"],
        )

    def test_qt_webengine_autoplay_flag_is_enabled(self):
        with patch.dict("os.environ", {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu"}, clear=True):
            _allow_qt_webengine_autoplay()
            self.assertEqual(
                " ".join(sorted(__import__("os").environ["QTWEBENGINE_CHROMIUM_FLAGS"].split())),
                "--autoplay-policy=no-user-gesture-required --disable-gpu",
            )

    def test_youtube_view_is_not_user_clickable(self):
        view = FakeWebView()

        _make_youtube_view_non_interactive(view)

        self.assertTrue(view.attributes[Qt.WidgetAttribute.WA_TransparentForMouseEvents])
        self.assertEqual(view.focus_policy, Qt.FocusPolicy.NoFocus)
        self.assertEqual(view.context_menu_policy, Qt.ContextMenuPolicy.NoContextMenu)

    def test_youtube_view_uses_pip_size(self):
        view = FakeWebView()

        _set_youtube_view_size(view)

        self.assertEqual(view.fixed_size, (YOUTUBE_VIEW_WIDTH, YOUTUBE_VIEW_HEIGHT))
        self.assertEqual(view.fixed_size, (356, 200))

    def test_sync_offset_change_replays_current_youtube_tick(self):
        with patch("tab_analyzer.ui.playback_core.YouTubeTabPlayer._load_web_engine", return_value=None):
            player = YouTubeTabPlayer()
        view = FakePlayerView()
        player.view = view
        player.song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
        player.current_tick = 960.0
        player.speed_percent = 100
        player.playing = True

        player.set_offset_milliseconds(4000)

        self.assertEqual(view.fake_page.scripts[-1], "playAt(4.500, 1.000);")

    def test_sync_offset_change_updates_pending_play_command_while_loading(self):
        with patch("tab_analyzer.ui.playback_core.YouTubeTabPlayer._load_web_engine", return_value=None):
            player = YouTubeTabPlayer()
        player.song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
        player.current_tick = 960.0
        player.speed_percent = 75
        player.playing = True
        player._loading_video = True

        player.set_offset_milliseconds(4000)

        self.assertEqual(player._pending_player_script, "playAt(4.500, 0.750);")


class SongsterrAdRequestTests(unittest.TestCase):
    def test_ad_request_hosts_are_blocked(self):
        blocked_hosts = [
            "googleads.g.doubleclick.net",
            "pagead2.googlesyndication.com",
            "securepubads.g.doubleclick.net",
            "imasdk.googleapis.com",
            "ads.pubmatic.com",
        ]

        for host in blocked_hosts:
            with self.subTest(host=host):
                self.assertTrue(_is_songsterr_ad_request_host(host))

    def test_media_hosts_are_not_blocked(self):
        allowed_hosts = [
            "www.songsterr.com",
            "www.youtube.com",
            "www.youtube-nocookie.com",
            "i.ytimg.com",
            "rr1---sn-ab5l6n6z.googlevideo.com",
        ]

        for host in allowed_hosts:
            with self.subTest(host=host):
                self.assertFalse(_is_songsterr_ad_request_host(host))


if __name__ == "__main__":
    unittest.main()
