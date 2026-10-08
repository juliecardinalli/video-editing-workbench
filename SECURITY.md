# Local-only security model

Run this tool only on your own trusted computer. Do not expose the server through a tunnel, bind it to a public interface, or use it as a multi-user service. Anyone able to access your loopback server may read the active video and project. The session token is a cross-site request defense, not user authentication.

The server binds to `127.0.0.1`, rejects unexpected Host and Origin headers, uses a session token for saves, limits JSON input, and serves an exact list of files. It does not provide arbitrary filesystem browsing, remote asset downloads, or shell-command endpoints. Transcript content is inserted using DOM text/value properties, not interpreted as HTML.

Media parsing is performed by your installed FFmpeg/ffprobe. Keep those tools updated and use trusted media. Parsing complex media formats is not risk-free. The Python development server is not a hardened public hosting solution. Analysis/render subprocesses have a timeout, but this is not a resource-isolated sandbox.

The repository ignores `.env` files, local work directories, and common audio/video files. An ignore file is not a secret scanner: review every commit before publishing. Do not commit your source footage, transcripts, generated project JSON, access tokens, or unpublished scripts. Public examples use only synthetic media and illustrative text.

No telemetry, network providers, external fonts, or automatic uploads are used by the application. GitHub hosts repository assets and CI independently of the local editor.

For a security concern, use GitHub's private vulnerability reporting if enabled, or contact the maintainer through the public portfolio. Do not include private media or credentials in an issue.
