# Architecture and provenance

## The product problem

A talking-head edit can involve several separate decisions: which take says the right thing, where the delivery drags, which words should go, and what visuals should support them. Repeating those decisions in disconnected scripts and editors makes the work harder to review.

This project focuses on one handoff: **source video → timed script and cut suggestions → human decisions → reproducible rough cut**.

## Data flow

```text
Local video ── ffprobe + FFmpeg silencedetect ──┐
                                              ├─ Project JSON (source hash + timings)
Timed transcript ── timestamp validation ──────┘                 │
                                                                ▼
                                                   Local browser review
                                                     │              │
                                             Reviewed JSON     Markdown script
                                                     │          + visual notes
                                                     ▼
                                             CLI dry-run plan
                                                     │ --execute
                                                     ▼
                                              New MP4 export
```

The browser never receives an API key and cannot ask the server to render arbitrary commands. It can load only the active media, known static assets, and project state. A save request may update transcript rows and cut decisions, but not the active source path, source hash, or duration.

## Cut model

Every removal is a half-open source interval `[start, end)`, with a stable ID, kind, and explicit `selected` flag. Types are `edge`, `pause`, `script`, and `manual` (the latter is accepted in JSON; there is no freehand range authoring UI yet).

Selected intervals are sorted and unioned. The renderer subtracts that union from `[0, source_duration)` to calculate kept footage. This avoids double-counting or applying an overlapping silence/line removal twice.

Silence detection proposes edge removals and internal gaps. Small handles retain audio next to speech. An entirely quiet file does not produce an automatic full-video cut. All suggestions start off; selecting clip edges does not select internal pauses.

Transcript rows use supplied timestamps. There is no automatic alignment or interpolation. A word-timed import can support word-level decisions; a segment-timed import supports whole-segment decisions. Editing the words changes the document, not the audio.

## Persistence and exports

The project stores a relative local media path, its SHA-256, duration, detection settings, transcript, and decisions. The first browser save creates a `.before-save.json` backup. Subsequent saves atomically replace only that project JSON. Undo is an in-memory browser stack of 40 changes and does not survive reloads. This is not multi-user collaboration or a full version history.

Exports validate the media fingerprint and duration, encode kept pieces in a temporary directory, and concatenate them. The final output is created exclusively; an existing source or export is never overwritten. Video is normalized to 30 fps, square pixels, even dimensions, and H.264. Audio, when present, becomes stereo 48 kHz AAC. Technical completion is separate from visual/audio approval.

## What came from the working editing lab

The public workflow is derived from Julie's existing Python/FFmpeg tools:

- `tighten_talking_head_rough_cut.py`: edge silence detection, speech-side handles, trim reports.
- `render_internal_pause_tight_cut.py`: an explicit second-stage internal-pause review pass.
- `serve_visual_review_app.py`: timestamp-linked script editing, cut/restore decisions, visual notes, and preview review.
- `prepare_transcript_visual_stage.py`: turning transcript/timeline data into a script and visual-planning surface.

This release is a **new portable implementation of those core interactions**, not a copy of the private app's roughly 10,000-line server. It removes production-folder assumptions, external SSD dependencies, paid-provider adapters, uploaded-asset workflows, and unpublished projects. Source materials were inspected but are not included in public history.

The broader lab's script matching, automatic transcription adapters, asset sourcing, image generation, and overlay rendering are outside this repository's current implementation. They remain possible next steps, not advertised features.

## Useful next improvements

1. A short, explicitly approved real-speech demo with before/after playback.
2. More precise synchronized cut playback and a waveform.
3. Optional local transcription and alignment, behind a separately installed adapter.
4. Multi-clip assembly and versioned editorial history.

These are a roadmap, not implemented behavior.
