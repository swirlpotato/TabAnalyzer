import tempfile
from pathlib import Path
import unittest

from tab_analyzer.songsterr import (
    _extract_song_links,
    _extract_state,
    _export_filename,
    _part_url,
    load_cookie_header,
    save_cookie_header,
)


class SongsterrParsingTests(unittest.TestCase):
    def test_extracts_search_results_from_embedded_state(self):
        html = """
        <html>
          <a href="/a/wsa/queen-bohemian-rhapsody-tab-s270">Queen</a>
          <script id="state" type="application/json">
            {"songs":{"songs":{"list":[{"songId":270,"artist":"Queen","title":"Bohemian Rhapsody",
            "difficulty":4,"defaultTrack":2,"popularTrack":2,
            "tracks":[{"instrumentId":27,"isGuitar":true},{"instrumentId":33}] }]}}}
          </script>
        </html>
        """

        state = _extract_state(html)
        links = _extract_song_links(html)

        self.assertEqual(state["songs"]["songs"]["list"][0]["songId"], 270)
        self.assertEqual(links[270], "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270")

    def test_part_url_matches_songsterr_hosts(self):
        self.assertEqual(
            _part_url(270, 6534342, 2, "v0-3-2-example-stage"),
            "https://d3d3l6a6rcgkaf.cloudfront.net/270/6534342/v0-3-2-example-stage/2.json",
        )
        self.assertEqual(
            _part_url(270, 6534342, 2, "v0-3-2-example"),
            "https://dqsljvtekg760.cloudfront.net/270/6534342/v0-3-2-example/2.json",
        )
        self.assertEqual(
            _part_url(270, 6534342, 2, None),
            "https://d3rrfvx08uyjp1.cloudfront.net/part/6534342/2",
        )

    def test_export_filename_uses_revision_date(self):
        name = _export_filename(
            {
                "artist": "Queen",
                "title": "Bohemian Rhapsody",
                "createdAt": "2026-04-28T20:51:52.084Z",
            }
        )

        self.assertEqual(name, "Queen-Bohemian Rhapsody-04-28-2026.gp")

    def test_cookie_header_can_be_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "songsterr_session.json"

            save_cookie_header("session=abc; other=123", path)

            self.assertEqual(load_cookie_header(path), "session=abc; other=123")


if __name__ == "__main__":
    unittest.main()
