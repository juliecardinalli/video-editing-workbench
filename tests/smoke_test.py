"""Synthetic end-to-end test. No private footage or network access."""

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import (
    analyze,
    make_demo,
    probe,
    render,
    run,
    sha256,
    tool,
    write_new_json,
)


def main():
    with tempfile.TemporaryDirectory(prefix="video-workbench-test-") as tmp:
        root = Path(tmp)
        project = make_demo(root / "demo")
        source = root / "demo/demo.mp4"
        source_hash = sha256(source)
        data = json.loads(project.read_text())
        assert len(data["cuts"]) == 4, data["cuts"]
        assert all(not cut["selected"] for cut in data["cuts"])
        for cut in data["cuts"]:
            cut["selected"] = True
        reviewed = root / "demo/reviewed.project.json"
        write_new_json(reviewed, data)
        output = root / "edited.mp4"
        dry = render(reviewed, output)
        assert not output.exists() and not dry["executed"]
        report = render(reviewed, output, True)
        assert 8 < report["output_seconds_actual"] < 10
        assert (
            abs(report["output_seconds_actual"] - report["output_seconds_planned"])
            < 0.25
        )
        assert report["source_unchanged"] and sha256(source) == source_hash
        export_hash = sha256(output)
        try:
            render(reviewed, output, True)
        except ValueError:
            pass
        else:
            raise AssertionError("Overwrite was allowed")
        assert sha256(output) == export_hash
        data["cuts"] = [
            {
                "id": "all",
                "start": 0,
                "end": data["duration"],
                "selected": True,
                "kind": "manual",
            }
        ]
        all_cut = root / "demo/all-cut.project.json"
        write_new_json(all_cut, data)
        try:
            render(all_cut, root / "empty.mp4")
        except ValueError:
            pass
        else:
            raise AssertionError("All-cut edit was allowed")
        data["cuts"] = []
        data["media_sha256"] = "0" * 64
        changed = root / "demo/changed.project.json"
        write_new_json(changed, data)
        try:
            render(changed, root / "changed.mp4")
        except ValueError:
            pass
        else:
            raise AssertionError("Changed source was allowed")
        # A video with no audio must still be reviewable and renderable.
        silent = root / "silent.mp4"
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
                "color=c=blue:s=160x240:r=30:d=1",
                "-c:v",
                "libx264",
                str(silent),
            ]
        )
        silent_project = root / "silent.project.json"
        silent_data = analyze(silent, silent_project)
        assert not silent_data["has_audio"] and not silent_data["cuts"]
        silent_output = root / "silent-edited.mp4"
        render(silent_project, silent_output, True)
        assert not probe(silent_output)[1]
        print(
            json.dumps(
                {
                    "synthetic_pipeline": "passed",
                    "suggestions": 4,
                    "planned_seconds": report["output_seconds_planned"],
                    "rendered_seconds": report["output_seconds_actual"],
                    "source_preserved": True,
                    "overwrite_refused": True,
                    "changed_source_refused": True,
                    "all_cut_refused": True,
                    "silent_video_render": "passed",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
