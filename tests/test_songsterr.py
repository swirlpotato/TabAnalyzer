import tempfile
from pathlib import Path
import unittest

from tab_analyzer.songsterr import (
    _default_youtube_video,
    _extract_song_links,
    _extract_state,
    _export_filename,
    _part_url,
    _songsterr_details,
    _youtube_videos,
    details_path_for_gp,
    load_cookie_header,
    save_details_file,
    save_cookie_header,
    update_youtube_default_video,
    update_youtube_sync_offset,
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

    def test_details_path_uses_gp_filename_stem(self):
        self.assertEqual(details_path_for_gp(Path("Queen-Bohemian.gp")).name, "Queen-Bohemian_details.json")

    def test_details_file_can_be_saved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            gp_path = Path(temp_dir) / "Song.gp"

            details_path = save_details_file(gp_path, {"youtube": {"default_video_id": "abc"}})

            self.assertEqual(details_path, Path(temp_dir) / "Song_details.json")
            self.assertEqual(details_path.read_text(encoding="utf-8"), '{\n  "youtube": {\n    "default_video_id": "abc"\n  }\n}')

    def test_promotes_successful_youtube_video_to_default(self):
        details = {
            "youtube": {
                "default_video_id": "bad",
                "videos": [
                    {"video_id": "bad", "url": "https://www.youtube.com/watch?v=bad"},
                    {"video_id": "good", "url": "https://www.youtube.com/watch?v=good"},
                ],
            }
        }

        changed = update_youtube_default_video(details, "good")

        self.assertTrue(changed)
        self.assertEqual(details["youtube"]["default_video_id"], "good")
        self.assertEqual(details["youtube"]["default_video_url"], "https://www.youtube.com/watch?v=good")
        self.assertEqual([video["video_id"] for video in details["youtube"]["videos"]], ["good", "bad"])

    def test_updates_youtube_sync_offset(self):
        details = {"youtube": {"sync": {"offset_seconds": 0.0}}}

        changed = update_youtube_sync_offset(details, 0.01)

        self.assertTrue(changed)
        self.assertEqual(details["youtube"]["sync"]["offset_seconds"], 0.01)

    def test_songsterr_details_include_youtube_videos(self):
        meta = {
            "songId": 270,
            "revisionId": 6534342,
            "artist": "Queen",
            "title": "Bohemian Rhapsody",
            "videos": [
                {"id": 1, "status": "done", "feature": "backing", "videoId": "backing123"},
                {"id": 2, "status": "done", "feature": None, "videoId": "main456"},
            ],
        }
        result = type(
            "Result",
            (),
            {
                "song_id": 270,
                "artist": "Queen",
                "title": "Bohemian Rhapsody",
                "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                "default_track": 0,
                "popular_track": 0,
            },
        )()

        details = _songsterr_details(result, meta)

        self.assertEqual(details["youtube"]["default_video_id"], "main456")
        self.assertEqual(details["youtube"]["videos"][0]["url"], "https://www.youtube.com/watch?v=backing123")
        self.assertEqual(details["youtube"]["sync"]["offset_seconds"], 0.0)

    def test_youtube_video_parser_prefers_main_done_video(self):
        videos = _youtube_videos(
            {
                "videos": [
                    {"status": "done", "feature": "alternative", "videoId": "alt"},
                    {"status": "done", "feature": None, "videoId": "main"},
                ]
            }
        )

        self.assertEqual(_default_youtube_video(videos)["video_id"], "main")


if __name__ == "__main__":
    unittest.main()
