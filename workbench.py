#!/usr/bin/env python3
"""A local, review-first transcript and dead-air editing workbench."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
MAX_JSON_BYTES = 2_000_000


def number(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, timeout=600):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f"{Path(command[0]).name} failed: {result.stderr[-1800:]}")
    return result


def tool(name):
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"Install {name} and make it available on PATH first.")
    return executable


def probe(path):
    data = json.loads(
        run(
            [
                tool("ffprobe"),
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )
    if not any(s["codec_type"] == "video" for s in data["streams"]):
        raise ValueError("The input must contain video.")
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Media duration must be positive and finite.")
    return duration, any(s["codec_type"] == "audio" for s in data["streams"])


def parse_silence(log, duration):
    """Parse ffmpeg silencedetect, including quiet audio through end of file."""
    intervals, pending = [], None
    for line in log.splitlines():
        start = re.search(r"silence_start:\s*(-?[0-9.]+)", line)
        end = re.search(r"silence_end:\s*(-?[0-9.]+)", line)
        if start:
            pending = max(0.0, float(start[1]))
        if end and pending is not None:
            stop = min(duration, float(end[1]))
            if stop > pending:
                intervals.append((pending, stop))
            pending = None
    if pending is not None and pending < duration:
        intervals.append((pending, duration))
    return intervals


def suggest_cuts(intervals, duration, handle=0.12):
    """Retain a small speech-side handle. Never auto-select an edit."""
    handle = number(handle, "handle")
    if handle < 0:
        raise ValueError("handle cannot be negative")
    result = []
    for start, end in intervals:
        at_head, at_tail = start <= 0.06, end >= duration - 0.08
        if at_head and at_tail:  # Completely quiet input is not an editing decision.
            continue
        left = 0.0 if at_head else start + handle
        right = duration if at_tail else end - handle
        if right - left >= 0.04:
            result.append(
                {
                    "id": f"silence-{len(result)+1}",
                    "start": round(left, 4),
                    "end": round(right, 4),
                    "kind": "edge" if at_head or at_tail else "pause",
                    "reason": (
                        "Quiet clip edge"
                        if at_head or at_tail
                        else "Internal pause — review delivery"
                    ),
                    "selected": False,
                }
            )
    return result


def normalize_transcript(data, duration):
    """Accept segment or word timestamps; never infer timings from text length."""
    if isinstance(data, dict):
        rows = data.get("segments", data.get("words"))
    else:
        rows = data
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError(
            "Transcript must contain a segments or words array (at most 10,000 rows)."
        )
    normalized, previous_end = [], 0.0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Each transcript row must be an object.")
        start, end = number(row.get("start"), "start"), number(row.get("end"), "end")
        text = row.get("text", row.get("word"))
        if not 0 <= start < end <= duration + 0.02 or start < previous_end - 0.001:
            raise ValueError(
                "Transcript rows must be chronological, non-overlapping, and inside the video."
            )
        if not isinstance(text, str) or not text.strip() or len(text) > 10000:
            raise ValueError(
                "Each transcript row needs non-empty text (at most 10,000 characters)."
            )
        notes = row.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 10000:
            raise ValueError("Notes must be text (at most 10,000 characters).")
        normalized.append(
            {
                "id": f"line-{i+1}",
                "start": start,
                "end": min(duration, end),
                "text": text.strip(),
                "notes": notes,
            }
        )
        previous_end = end
    return normalized


def validate_project(project):
    if not isinstance(project, dict) or project.get("version") != 1:
        raise ValueError("Expected a version 1 workbench project.")
    duration = number(project.get("duration"), "duration")
    if duration <= 0:
        raise ValueError("duration must be positive")
    if not isinstance(project.get("media"), str) or not project["media"]:
        raise ValueError("media must be a local file path")
    fingerprint = project.get("media_sha256", "")
    if not isinstance(fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", fingerprint
    ):
        raise ValueError(
            "A source SHA-256 is required. Create the project with analyze."
        )
    project["segments"] = normalize_transcript(project.get("segments", []), duration)
    title = project.get("title", "Untitled project")
    if not isinstance(title, str) or len(title) > 500:
        raise ValueError("title must be text (at most 500 characters)")
    project["title"] = title
    cuts = project.get("cuts", [])
    if not isinstance(cuts, list) or len(cuts) > 5000:
        raise ValueError("cuts must be an array of at most 5,000 decisions")
    seen = set()
    for cut in cuts:
        if not isinstance(cut, dict):
            raise ValueError("Each cut must be an object.")
        ident = cut.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("Cut IDs must be unique, non-empty strings.")
        seen.add(ident)
        start, end = number(cut.get("start"), "cut start"), number(
            cut.get("end"), "cut end"
        )
        if not 0 <= start < end <= duration:
            raise ValueError("Cut ranges must be inside the video.")
        if type(cut.get("selected")) is not bool:
            raise ValueError("Cut selected must be true or false.")
        if cut.get("kind") not in ("edge", "pause", "script", "manual"):
            raise ValueError("Unrecognized cut kind.")
    return project


def keep_ranges(duration, cuts):
    """Union selected cuts and subtract them from the source timeline."""
    merged = []
    for start, end in sorted((c["start"], c["end"]) for c in cuts if c["selected"]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    keep, cursor = [], 0.0
    for start, end in merged:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep.append((cursor, duration))
    return keep


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON file is too large (maximum 2 MB).")
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_json(path, data):
    path = Path(path)
    if path.exists():
        raise ValueError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")


def analyze(media, output, transcript=None, threshold=-35, min_silence=0.35):
    media, output = Path(media).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Project already exists; choose a new output filename.")
    if (
        not -90 <= number(threshold, "threshold") <= -5
        or not 0.05 <= number(min_silence, "min_silence") <= 10
    ):
        raise ValueError(
            "Use a threshold between -90 and -5 dB and a minimum silence of 0.05–10 seconds."
        )
    duration, audio = probe(media)
    intervals = []
    if audio:
        result = run(
            [
                tool("ffmpeg"),
                "-nostdin",
                "-hide_banner",
                "-i",
                str(media),
                "-map",
                "0:a:0",
                "-af",
                f"silencedetect=noise={threshold}dB:d={min_silence}",
                "-f",
                "null",
                "-",
            ]
        )
        intervals = parse_silence(result.stderr, duration)
    project = {
        "version": 1,
        "title": media.stem,
        "media": os.path.relpath(media, output.parent),
        "media_sha256": sha256(media),
        "duration": duration,
        "has_audio": audio,
        "analysis": {
            "threshold_db": threshold,
            "minimum_silence": min_silence,
            "handle": 0.12,
        },
        "segments": (
            normalize_transcript(read_json(transcript), duration) if transcript else []
        ),
        "cuts": suggest_cuts(intervals, duration),
        "demo": False,
    }
    write_new_json(output, validate_project(project))
    return project


def source_path(project, project_file):
    path = (Path(project_file).resolve().parent / project["media"]).resolve()
    if not path.is_file():
        raise ValueError(
            "Source video is missing. Keep the project and media together."
        )
    return path


def render(project_file, output, execute=False):
    project = validate_project(read_json(project_file))
    source, output = source_path(project, project_file), Path(output).resolve()
    if output.suffix.lower() != ".mp4" or output.exists() or output == source:
        raise ValueError(
            "Choose a new .mp4 output path. Existing files and sources are protected."
        )
    if sha256(source) != project["media_sha256"]:
        raise ValueError(
            "Source media changed since analysis; analyze it again before rendering."
        )
    duration, audio = probe(source)
    if abs(duration - project["duration"]) > 0.02:
        raise ValueError("Project duration does not match the source video.")
    keep = keep_ranges(duration, project["cuts"])
    if not keep or sum(b - a for a, b in keep) < 0.1:
        raise ValueError(
            "The edit removes the entire video (or leaves less than 0.1 seconds)."
        )
    if len(keep) > 200:
        raise ValueError("This rough-cut renderer supports at most 200 kept ranges.")
    report = {
        "source_seconds": duration,
        "output_seconds_planned": round(sum(b - a for a, b in keep), 4),
        "keep_ranges": keep,
        "output": str(output),
        "executed": execute,
    }
    if not execute:
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = tool("ffmpeg")
    # Encode each segment with the same settings, then concatenate. No shell commands.
    with tempfile.TemporaryDirectory(prefix="workbench-", dir=output.parent) as temp:
        temp = Path(temp)
        for i, (start, end) in enumerate(keep):
            command = [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-i",
                str(source),
                "-ss",
                str(start),
                "-t",
                str(end - start),
                "-map",
                "0:v:0",
                "-map_metadata",
                "-1",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
            ]
            command += (
                ["-map", "0:a:0", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
                if audio
                else ["-an"]
            )
            run(command + [str(temp / f"part-{i:04d}.mp4")])
        (temp / "concat.txt").write_text(
            "".join(f"file 'part-{i:04d}.mp4'\n" for i in range(len(keep))),
            encoding="utf-8",
        )
        run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(temp / "concat.txt"),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temp / "finished.mp4"),
            ]
        )
        # Exclusive creation also prevents races from overwriting an existing export.
        with (temp / "finished.mp4").open("rb") as source_file, output.open(
            "xb"
        ) as destination:
            shutil.copyfileobj(source_file, destination)
    report["output_seconds_actual"] = probe(output)[0]
    report["source_unchanged"] = sha256(source) == project["media_sha256"]
    report["review"] = "Technical export complete; watch and listen before using it."
    return report


def make_demo(directory):
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Choose a new or empty demo directory.")
    directory.mkdir(parents=True, exist_ok=True)
    media, transcript, project = (
        directory / "demo.mp4",
        directory / "transcript.json",
        directory / "demo.project.json",
    )
    # Entirely synthetic: no personal footage, recorded speech, or outside assets.
    run(
        [
            tool("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x203c35:s=540x960:r=30:d=12,drawgrid=w=90:h=90:t=1:c=0xffffff@0.08,drawbox=x=80:y=320:w=380:h=220:c=0xcfe5a7:t=4",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=if(between(t\\,1\\,3)+between(t\\,4.2\\,7)+between(t\\,8\\,11)\\,0.2*sin(2*PI*440*t)\\,0):s=48000:d=12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(media),
        ]
    )
    lines = [
        {
            "start": 1,
            "end": 3,
            "text": "Good edits start with a clear idea.",
            "notes": "Open on the speaker.",
        },
        {
            "start": 4.2,
            "end": 7,
            "text": "Cut the waiting. Keep the personality.",
            "notes": "Show a before-and-after timeline.",
        },
        {
            "start": 8,
            "end": 11,
            "text": "Review every decision before you export.",
            "notes": "End on the edit review screen.",
        },
    ]
    write_new_json(transcript, {"segments": lines})
    data = analyze(media, project, transcript)
    data.update(title="A little less waiting", demo=True)
    # This file was just generated here, not a user-supplied project.
    project.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return project


def create_server(project_file, port=8765):
    project_file = Path(project_file).resolve()
    state = validate_project(read_json(project_file))
    media = source_path(state, project_file)
    token, lock = secrets.token_urlsafe(32), threading.Lock()
    assets = {
        "/": (ROOT / "web/index.html", "text/html"),
        "/app.js": (ROOT / "web/app.js", "text/javascript"),
        "/core.mjs": (ROOT / "web/core.mjs", "text/javascript"),
        "/style.css": (ROOT / "web/style.css", "text/css"),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def allowed(self):
            # Reject DNS rebinding and cross-site requests. This is a local tool, not a hosted service.
            host = self.headers.get("Host", "")
            return host in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def respond(self, code, body, content_type="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return self.respond(403, {"error": "Local requests only."})
            path = urlparse(self.path).path
            if path == "/api/project":
                with lock:
                    return self.respond(200, {"project": state, "token": token})
            if path == "/media":
                total = media.stat().st_size
                start, end, partial = 0, total - 1, False
                header = self.headers.get("Range")
                if header:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
                    if not match or not any(match.groups()):
                        return self.respond(416, {"error": "Unsupported byte range."})
                    if match[1]:
                        start = int(match[1])
                        end = min(total - 1, int(match[2])) if match[2] else total - 1
                    else:
                        start = max(0, total - int(match[2]))
                    if start > end or start >= total:
                        return self.respond(416, {"error": "Range outside media."})
                    partial = True
                self.send_response(206 if partial else 200)
                self.send_header(
                    "Content-Type", mimetypes.guess_type(media.name)[0] or "video/mp4"
                )
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                self.end_headers()
                try:
                    with media.open("rb") as handle:
                        handle.seek(start)
                        remaining = end - start + 1
                        while remaining:
                            chunk = handle.read(min(65536, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path in assets:
                file, content_type = assets[path]
                return self.respond(200, file.read_bytes(), content_type)
            return self.respond(404, {"error": "Not found."})

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-Workbench-Token") != token:
                return self.respond(403, {"error": "Invalid local session."})
            origin = self.headers.get("Origin")
            if origin and origin not in {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }:
                return self.respond(
                    403, {"error": "Cross-origin requests are not allowed."}
                )
            if self.path != "/api/save":
                return self.respond(404, {"error": "Not found."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_JSON_BYTES:
                    raise ValueError("Project must be smaller than 2 MB.")
                submitted = json.loads(self.rfile.read(length))
                if not isinstance(submitted, dict):
                    raise ValueError("The save payload must be an object.")
                with lock:
                    updated = copy.deepcopy(state)
                    # A browser can edit decisions, not source paths or source fingerprints.
                    updated["segments"] = normalize_transcript(
                        submitted.get("segments", []), state["duration"]
                    )
                    updated["cuts"] = submitted.get("cuts", [])
                    validate_project(updated)
                    backup = project_file.with_name(
                        project_file.name + ".before-save.json"
                    )
                    if not backup.exists():
                        write_new_json(backup, state)
                    fd, temp_name = tempfile.mkstemp(
                        prefix=".workbench-", suffix=".json", dir=project_file.parent
                    )
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as handle:
                            json.dump(updated, handle, indent=2, allow_nan=False)
                        os.replace(temp_name, project_file)
                    finally:
                        if os.path.exists(temp_name):
                            os.unlink(temp_name)
                    state.clear()
                    state.update(updated)
                return self.respond(200, {"saved": True})
            except (ValueError, TypeError, KeyError, OSError) as exc:
                return self.respond(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo", help="Generate synthetic media and a demo project"
    )
    demo.add_argument("directory", type=Path)
    analysis = commands.add_parser(
        "analyze", help="Inspect local video and propose quiet sections"
    )
    analysis.add_argument("media", type=Path)
    analysis.add_argument("--output", type=Path, required=True)
    analysis.add_argument("--transcript", type=Path)
    analysis.add_argument("--threshold-db", type=float, default=-35)
    analysis.add_argument("--min-silence", type=float, default=0.35)
    serve = commands.add_parser("serve", help="Open the local interactive editor")
    serve.add_argument("project", type=Path)
    serve.add_argument("--port", type=int, default=8765)
    export = commands.add_parser(
        "render", help="Review an export plan; add --execute to render"
    )
    export.add_argument("project", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            print(make_demo(args.directory))
        elif args.command == "analyze":
            data = analyze(
                args.media,
                args.output,
                args.transcript,
                args.threshold_db,
                args.min_silence,
            )
            print(
                f"Created {args.output}: {len(data['cuts'])} unselected suggestions; source untouched."
            )
        elif args.command == "render":
            print(json.dumps(render(args.project, args.output, args.execute), indent=2))
        else:
            server = create_server(args.project, args.port)
            print(
                f"Video Editing Workbench: http://127.0.0.1:{server.server_port}",
                flush=True,
            )
            print(
                "Local only. Ctrl+C to stop. Rendering is a separate, explicit CLI step.",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
