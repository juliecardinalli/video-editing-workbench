# Video Editing Workbench

[![Tests](https://github.com/juliecardinalli/video-editing-workbench/actions/workflows/tests.yml/badge.svg)](https://github.com/juliecardinalli/video-editing-workbench/actions/workflows/tests.yml)

**Cut dead air. Edit by script. Keep control of the final video.**

A local video editor that turns timestamped transcripts into an interactive script. Review quiet sections, cut unwanted lines, add visual notes, and render the approved edit with FFmpeg. Your footage stays on your computer.

I built editing tools for my own short-form videos because assembling takes, tightening pauses, and tracking visual ideas meant doing the same work repeatedly. This repository packages that workflow into a small, runnable public project. The automation proposes cuts; the person making the video decides what stays.

## Try it in a few minutes

You need **Python 3.10+** and **FFmpeg / ffprobe** on your PATH, with H.264 (`libx264`) and AAC encoding. No Python packages, Node build, API keys, or cloud account are needed to run the app. Use macOS or Linux; Windows has not been tested.

```sh
git clone https://github.com/juliecardinalli/video-editing-workbench.git
cd video-editing-workbench

# Generate a 12-second test video, timed example script, and edit project.
python3 workbench.py demo .local/demo

# Open http://127.0.0.1:8765 in your browser.
python3 workbench.py serve .local/demo/demo.project.json
```

The demo uses generated shapes and tones. Its script is **illustrative text, not transcribed speech**. It includes no private footage or unpublished content.

In the editor:

1. Listen to a suggested quiet section. Select **clip edges** or individually approve an internal pause.
2. Click a script timestamp to seek. Use **Cut line** / **Restore** to remove or keep that exact timestamp range.
3. Correct transcript text and add visual notes. These text changes do not alter the recorded speech.
4. Preview playback with selected cuts skipped. Undo changes, download the script, or export the decision JSON.
5. **Save decisions**, then use a second terminal to review and render:

```sh
# Dry run: prints the kept ranges and planned duration; creates no video.
python3 workbench.py render .local/demo/demo.project.json .local/demo/edited.mp4

# Explicit render. Existing files are never overwritten.
python3 workbench.py render .local/demo/demo.project.json .local/demo/edited.mp4 --execute
```

Watch and listen to the entire export before using it. The browser's skipped-cut preview is not frame-accurate playback of the rendered file.

## What works

| Feature              | What it does                                                                                           |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| Dead-air suggestions | Detects quiet audio with FFmpeg; adds 120 ms speech-side handles. All suggestions start unselected.    |
| Interactive script   | Imports timestamped `segments` or `words`; connects each row to its source video time.                 |
| Transcript-led cuts  | Removes / restores a line's footage without deleting or rewriting the original media.                  |
| Review controls      | Timeline seeking, playback cut-skipping, undo, editable text, and per-line visual notes.               |
| Portable decisions   | Saves JSON decisions and downloads a timestamped Markdown script with cut labels.                      |
| Local MP4 export     | Unions overlapping cuts, renders kept ranges, and produces H.264/AAC output.                           |
| Source protection    | Checks the source SHA-256, refuses existing output files, and retains a pre-first-save project backup. |

**Not included:** built-in transcription, AI-written scripts, voice generation, automatic semantic take selection, rendered visual overlays, caption burn-in, multi-camera timelines, or social publishing. Visual notes are a planning handoff, not rendered graphics. Script timing comes from supplied timestamps—not estimates based on character counts.

## Use your own video

```sh
python3 workbench.py analyze /path/to/your-video.mp4 \
  --transcript /path/to/timed-transcript.json \
  --output .local/my-video/edit.project.json

python3 workbench.py serve .local/my-video/edit.project.json
```

`--transcript` is optional. You can review silence suggestions without it, or import a timed transcript in the browser later. Use an existing transcript from your own transcription tool; this app makes no transcription API calls.

Transcript format ([example](examples/transcript.json)):

```json
{
  "segments": [
    {
      "start": 1.0,
      "end": 3.0,
      "text": "A complete thought.",
      "notes": "Optional visual idea."
    },
    { "start": 4.2, "end": 7.0, "text": "The next thought." }
  ]
}
```

Rows must have numeric start/end times, be ordered, not overlap, and fit inside the video. A `words` array with `word`, `start`, and `end` also works; each word becomes an editable row. Untimed plain text is intentionally rejected.

If silence detection needs tuning, rerun analysis into a **new** project:

```sh
python3 workbench.py analyze /path/to/your-video.mp4 \
  --threshold-db -40 --min-silence 0.5 \
  --output .local/my-video/alternate.project.json
```

Quiet speech, background music, and noisy rooms can all affect detection. Review with headphones. Cutting an internal pause can change meaning or delivery even when no words are removed.

Paths inside a project are relative to the project's directory. The render output path is relative to the terminal's current directory. Keep a downloaded decision JSON **beside its original project** so its media reference still resolves. Reimporting a transcript clears previous script-line cuts, while preserving silence decisions.

## Why these choices

- **Review first:** silence is a signal, not editorial judgment.
- **An explicit edit list:** overlapping removals are combined into a single source timeline; no hidden edits.
- **Local by default:** no uploads, analytics, API keys, or accounts. The server listens only on `127.0.0.1`.
- **Portable core:** standard-library Python, plain browser JavaScript, and FFmpeg. No application build step.
- **Safety is testable:** source hashes, no-overwrite exports, loopback-only serving, allowlisted files, and token-protected saves.

The original private lab also explored script-to-take matching, visual sourcing boards, overlay plans, and transcription adapters. This public edition **refactors a focused subset** of that work into a smaller editor; it is not the original private app or a claim that every experiment shipped. See [architecture and provenance](docs/architecture.md).

## Tests

```sh
python3 -m unittest discover -s tests -v
node --test tests/core.test.mjs  # Node 20+ is needed only for these tests.
python3 tests/smoke_test.py
```

Tests cover cut boundaries and overlap, transcript validation, source protection, no-overwrite behavior, local-server guards, byte-range video streaming, frontend editing logic, and a real synthetic FFmpeg render—including a video with no audio. CI runs the same checks on Linux.

The synthetic integration fixture produces four suggestions. Selecting all four plans **8.52 seconds** from a 12-second input; the initial local encoded output was **8.54 seconds**. This demonstrates the pipeline, not a measured productivity result or a guarantee of speech quality. Encoder timing can differ slightly across versions.

## Repository map

```text
workbench.py        Analysis, project validation, loopback server, CLI, MP4 rendering
web/                Browser editor and independently tested timeline logic
examples/           Synthetic transcript format example
tests/              Python / JavaScript tests and real FFmpeg smoke test
docs/               Architecture, security model, and public-edition boundaries
.github/workflows/  Automated test workflow
```

This is a single-video rough-cut tool, not a replacement for a full nonlinear editor. Long videos and large transcripts can be slow; the renderer caps kept ranges at 200. It normalizes video to 30 fps and re-encodes it, so it is not a lossless or HDR-preserving workflow. The local server is for one trusted user, not public hosting. See [security notes](SECURITY.md).

Built by [Julie Cardinalli](https://jcardinalli.work/). Related: [Julie Content Studio](https://github.com/juliecardinalli/julie-content-studio), the broader research-to-production toolkit.
