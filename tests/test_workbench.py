import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from workbench import (
    create_server,
    keep_ranges,
    normalize_transcript,
    parse_silence,
    sha256,
    suggest_cuts,
    validate_project,
    write_new_json,
)


def fixture():
    return {
        "version": 1,
        "title": "Example",
        "duration": 12,
        "media": "source.mp4",
        "media_sha256": "a" * 64,
        "segments": [{"start": 1, "end": 3, "text": "Example line"}],
        "cuts": [],
    }


def cut(start, end, selected=True, ident="cut-1"):
    return {
        "id": ident,
        "start": start,
        "end": end,
        "selected": selected,
        "kind": "manual",
    }


class EditTests(unittest.TestCase):
    def test_silence_parser_and_open_end(self):
        log = "silence_start: 0\nsilence_end: 1.25\nsilence_start: 8\n"
        self.assertEqual(parse_silence(log, 10), [(0, 1.25), (8, 10)])

    def test_silence_clamped_to_media(self):
        self.assertEqual(
            parse_silence("silence_start: -0.02\nsilence_end: 15", 12), [(0, 12)]
        )

    def test_edge_handles_and_internal_review(self):
        result = suggest_cuts([(0, 1), (3, 4), (11, 12)], 12)
        self.assertEqual(
            [(r["start"], r["end"], r["kind"]) for r in result],
            [(0, 0.88, "edge"), (3.12, 3.88, "pause"), (11.12, 12, "edge")],
        )
        self.assertTrue(all(not r["selected"] for r in result))

    def test_entirely_quiet_video_is_not_automatically_deleted(self):
        self.assertEqual(suggest_cuts([(0, 12)], 12), [])

    def test_short_silence_and_invalid_handle(self):
        self.assertEqual(suggest_cuts([(2, 2.1)], 12), [])
        with self.assertRaises(ValueError):
            suggest_cuts([], 12, -0.1)

    def test_overlaps_and_adjacent_ranges_are_unioned(self):
        self.assertEqual(
            keep_ranges(12, [cut(1, 3), cut(2, 4), cut(4, 5), cut(7, 8, False)]),
            [(0, 1), (5, 12)],
        )

    def test_full_removal(self):
        self.assertEqual(keep_ranges(12, [cut(0, 12)]), [])

    def test_no_cuts(self):
        self.assertEqual(keep_ranges(12, []), [(0, 12)])

    def test_word_and_segment_import(self):
        words = normalize_transcript(
            {"words": [{"start": 0.1, "end": 0.6, "word": "Hello"}]}, 12
        )
        self.assertEqual(words[0]["text"], "Hello")
        self.assertEqual(words[0]["id"], "line-1")
        self.assertEqual(normalize_transcript({"segments": []}, 12), [])

    def test_transcript_rejects_untimed_and_overlapping_rows(self):
        invalid = [
            {"segments": [{"text": "No timestamps"}]},
            [
                {"start": 0, "end": 2, "text": "One"},
                {"start": 1, "end": 3, "text": "Two"},
            ],
            [{"start": 0, "end": 13, "text": "Too long"}],
            [{"start": True, "end": 3, "text": "Boolean"}],
            [{"start": 0, "end": float("nan"), "text": "NaN"}],
            [{"start": 0, "end": 1, "text": ""}],
            "plain text",
        ]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                normalize_transcript(item, 12)

    def test_invalid_project_cuts(self):
        invalid = [
            cut(-1, 2),
            cut(5, 5),
            cut(1, 13),
            cut(float("nan"), 3),
            cut(True, 3),
            cut(1, 3, "yes"),
        ]
        for item in invalid:
            data = fixture()
            data["cuts"] = [item]
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_project(data)

    def test_duplicate_cut_ids(self):
        data = fixture()
        data["cuts"] = [cut(1, 2), cut(4, 5)]
        with self.assertRaises(ValueError):
            validate_project(data)

    def test_source_fingerprint_required(self):
        data = fixture()
        data["media_sha256"] = ""
        with self.assertRaises(ValueError):
            validate_project(data)

    def test_normalized_segment_ids(self):
        self.assertEqual(validate_project(fixture())["segments"][0]["id"], "line-1")

    def test_non_overwriting_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            write_new_json(path, {"first": 1})
            before = sha256(path)
            with self.assertRaises(ValueError):
                write_new_json(path, {"second": 2})
            self.assertEqual(sha256(path), before)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.media = self.root / "source.mp4"
        self.media.write_bytes(b"0123456789")
        data = fixture()
        data["media_sha256"] = sha256(self.media)
        self.path = self.root / "edit.project.json"
        write_new_json(self.path, data)
        self.server = create_server(self.path, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return result

    def test_only_allowlisted_files_are_served(self):
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/core.mjs")[0], 200)
        for path in [
            "/../workbench.py",
            "/workbench.py",
            "/media?path=/etc/passwd",
            "/.env",
        ]:
            response = self.request("GET", path)
            if path.startswith("/media?"):
                self.assertEqual(response[2], b"0123456789")
            else:
                self.assertEqual(response[0], 404)

    def test_byte_ranges(self):
        status, headers, body = self.request(
            "GET", "/media", headers={"Range": "bytes=2-5"}
        )
        self.assertEqual((status, body), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(
            self.request("GET", "/media", headers={"Range": "bytes=-3"})[2], b"789"
        )
        self.assertEqual(
            self.request("GET", "/media", headers={"Range": "bytes=99-100"})[0], 416
        )

    def test_reject_dns_rebinding(self):
        self.assertEqual(
            self.request("GET", "/api/project", headers={"Host": "evil.example"})[0],
            403,
        )

    def test_reject_write_without_token_and_cross_origin(self):
        self.assertEqual(self.request("POST", "/api/save", "{}")[0], 403)
        token = json.loads(self.request("GET", "/api/project")[2])["token"]
        self.assertEqual(
            self.request(
                "POST",
                "/api/save",
                "{}",
                {"X-Workbench-Token": token, "Origin": "https://evil.example"},
            )[0],
            403,
        )

    def test_save_preserves_source_and_first_backup(self):
        data = json.loads(self.request("GET", "/api/project")[2])
        payload = copy.deepcopy(data["project"])
        original = self.path.read_bytes()
        source_before = self.media.read_bytes()
        payload["segments"][0]["text"] = "Changed script"
        payload["media"] = "/etc/passwd"
        payload["cuts"] = [cut(3, 4)]
        response = self.request(
            "POST",
            "/api/save",
            json.dumps(payload),
            {"X-Workbench-Token": data["token"]},
        )
        self.assertEqual(response[0], 200)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["media"], "source.mp4")
        self.assertEqual(saved["segments"][0]["text"], "Changed script")
        self.assertEqual(self.media.read_bytes(), source_before)
        backup = json.loads(
            (self.root / "edit.project.json.before-save.json").read_text()
        )
        self.assertEqual(backup["segments"][0]["text"], "Example line")
        self.assertNotEqual(self.path.read_bytes(), original)

    def test_invalid_save_does_not_change_project(self):
        data = json.loads(self.request("GET", "/api/project")[2])
        before = self.path.read_bytes()
        data["project"]["cuts"] = [cut(0, 999)]
        self.assertEqual(
            self.request(
                "POST",
                "/api/save",
                json.dumps(data["project"]),
                {"X-Workbench-Token": data["token"]},
            )[0],
            400,
        )
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
