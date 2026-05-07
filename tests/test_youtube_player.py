import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt

from tab_analyzer.ui import (
    YOUTUBE_VIEW_HEIGHT,
    YOUTUBE_VIEW_WIDTH,
    _allow_qt_webengine_autoplay,
    _make_youtube_view_non_interactive,
    _set_youtube_view_size,
    _youtube_player_html,
    _youtube_player_url,
)


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


class YouTubePlayerHtmlTests(unittest.TestCase):
    def test_player_html_includes_embed_origin_and_referrer(self):
        html = _youtube_player_html("abc123", "http://127.0.0.1:43210")

        self.assertIn('meta name="referrer"', html)
        self.assertIn("enablejsapi: 1", html)
        self.assertIn("host: 'https://www.youtube-nocookie.com'", html)
        self.assertIn("origin: PLAYER_ORIGIN", html)
        self.assertIn("widget_referrer: PLAYER_ORIGIN", html)
        self.assertIn('"http://127.0.0.1:43210"', html)
        self.assertIn('"abc123"', html)

    def test_player_url_is_served_from_local_origin(self):
        self.assertEqual(
            _youtube_player_url("http://127.0.0.1:43210", "abc 123"),
            "http://127.0.0.1:43210/youtube-player?video_id=abc%20123",
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


if __name__ == "__main__":
    unittest.main()
