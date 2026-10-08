# Public Video Editing Workbench

- This is a public, portable edition of a private editing workflow. Never copy private media, transcripts, drafts, credentials, local account paths, or production archives into this repository.
- Keep all media processing local. Do not add uploads, paid API calls, or automatic publishing.
- Preserve original media. Rendering is dry-run by default and must refuse existing output files.
- Treat silence detection as a suggestion, not proof that speech can be removed. Preserve internal pauses unless explicitly selected.
- Do not estimate word timestamps from character counts. Transcript edits do not synthesize or change spoken audio.
- Run the unit tests, synthetic integration test, and browser checks before publishing changes. Describe implemented functionality and limitations honestly.
