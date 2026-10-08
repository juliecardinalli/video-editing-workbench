import {
  mergedCuts,
  stats,
  nextKeptTime,
  transcriptRows,
  toggleLine,
  timecode,
} from "./core.mjs";

const $ = (id) => document.getElementById(id);
let project,
  token,
  history = [],
  dirty = false,
  saving = false;
const video = $("video");

function message(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
}

function snapshot() {
  history.push(JSON.stringify(project));
  if (history.length > 40) history.shift();
  dirty = true;
  $("undo").disabled = false;
  message("Unsaved decisions · your source video is unchanged.");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function seek(time) {
  video.currentTime = time;
}

function drawTimeline() {
  if (!project) return;
  const canvas = $("timeline"),
    ctx = canvas.getContext("2d"),
    width = canvas.clientWidth;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(72 * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, 72);
  ctx.fillStyle = "#24463b";
  ctx.fillRect(0, 0, width, 38);
  for (const c of project.cuts.filter(
    (c) => !c.selected && c.kind !== "script",
  )) {
    ctx.fillStyle = "#d4b77c";
    ctx.fillRect(
      (c.start / project.duration) * width,
      0,
      ((c.end - c.start) / project.duration) * width,
      38,
    );
  }
  for (const c of mergedCuts(project.cuts)) {
    ctx.fillStyle = "#dba596";
    ctx.fillRect(
      (c.start / project.duration) * width,
      0,
      ((c.end - c.start) / project.duration) * width,
      38,
    );
  }
  ctx.fillStyle = "#172b24";
  ctx.fillRect(
    Math.min(width - 2, (video.currentTime / project.duration) * width),
    0,
    2,
    45,
  );
  ctx.font = "10px monospace";
  ctx.fillStyle = "#6b746e";
  for (let i = 0; i <= 4; i++) {
    ctx.textAlign = i === 4 ? "right" : i === 0 ? "left" : "center";
    ctx.fillText(timecode((project.duration * i) / 4), (width * i) / 4, 64);
  }
}

function refreshStats() {
  const s = stats(project);
  $("original").textContent = `${s.original.toFixed(1)}s`;
  $("edited").textContent = `${s.edited.toFixed(1)}s`;
  $("removed").textContent = `−${s.removed.toFixed(1)}s`;
  if (s.edited < 0.1)
    message(
      "All footage is selected for removal. Restore a cut before rendering.",
      true,
    );
  drawTimeline();
}

function renderLines() {
  const container = $("lines");
  container.replaceChildren();
  if (!project.segments.length) {
    container.append(
      el(
        "p",
        "empty",
        "No timed transcript yet. Import segment- or word-timestamp JSON to generate an interactive script. Silence review still works without one.",
      ),
    );
  }
  for (const [i, line] of project.segments.entries()) {
    const cut = project.cuts.find(
      (c) => c.id === `script-${line.id}` && c.selected,
    );
    const row = el("article", `line${cut ? " deleted" : ""}`);
    row.dataset.line = line.id;
    const side = el("div", "line-side");
    side.append(el("span", "line-number", String(i + 1).padStart(2, "0")));
    const timestamp = el("button", "timestamp", timecode(line.start));
    timestamp.setAttribute(
      "aria-label",
      `Seek to line ${i + 1} at ${timecode(line.start)}`,
    );
    timestamp.onclick = () => seek(line.start);
    side.append(timestamp);
    const body = el("div", "line-body");
    const text = el("textarea", "transcript-text");
    text.value = line.text;
    text.rows = 2;
    text.maxLength = 10000;
    text.setAttribute("aria-label", `Script line ${i + 1}`);
    text.onchange = () => {
      if (!text.value.trim()) {
        text.value = line.text;
        return message(
          "A script line cannot be blank. Use Cut line to remove footage.",
          true,
        );
      }
      snapshot();
      line.text = text.value.trim();
    };
    const note = el("input", "note");
    note.type = "text";
    note.value = line.notes ?? "";
    note.maxLength = 10000;
    note.placeholder = "Add a visual or editing note…";
    note.setAttribute("aria-label", `Visual note for line ${i + 1}`);
    note.onchange = () => {
      snapshot();
      line.notes = note.value;
    };
    body.append(text, note);
    const toggle = el(
      "button",
      cut ? "restore-line" : "cut-line",
      cut ? "Restore" : "Cut line",
    );
    toggle.setAttribute(
      "aria-label",
      `${cut ? "Restore" : "Cut"} line ${i + 1}`,
    );
    toggle.setAttribute("aria-pressed", String(Boolean(cut)));
    toggle.onclick = () => {
      snapshot();
      toggleLine(project, line);
      render();
    };
    row.append(side, body, toggle);
    container.append(row);
  }
}

function renderSuggestions() {
  $("suggestions").replaceChildren();
  const cuts = project.cuts.filter(
    (c) => c.kind === "edge" || c.kind === "pause",
  );
  if (!cuts.length)
    $("suggestions").append(
      el(
        "p",
        "helper",
        "No quiet sections were detected. This can also mean the source has no audio, or is entirely quiet.",
      ),
    );
  for (const cut of cuts) {
    const row = el("div", `suggestion${cut.selected ? " selected" : ""}`);
    const label = el("label");
    const checkbox = el("input");
    checkbox.type = "checkbox";
    checkbox.checked = cut.selected;
    checkbox.onchange = () => {
      snapshot();
      cut.selected = checkbox.checked;
      render();
    };
    const copy = el("span");
    copy.append(
      el("strong", "", cut.kind === "edge" ? "Clip edge" : "Internal pause"),
      el(
        "small",
        "",
        `${timecode(cut.start)} – ${timecode(cut.end)} · ${(cut.end - cut.start).toFixed(2)}s`,
      ),
    );
    label.append(checkbox, copy);
    const listen = el("button", "text-button", "Listen");
    listen.setAttribute("aria-label", `Listen near ${timecode(cut.start)}`);
    listen.onclick = () => {
      $("preview-cuts").checked = false;
      seek(Math.max(0, cut.start - 0.5));
      video.play().catch((e) => message(e.message, true));
    };
    row.append(label, listen);
    $("suggestions").append(row);
  }
}

function render() {
  renderLines();
  renderSuggestions();
  refreshStats();
  $("undo").disabled = !history.length;
}

function download(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = el("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ensureLoaded() {
  if (!project) throw new Error("The project has not loaded yet.");
}

$("undo").onclick = () => {
  if (!history.length) return;
  project = JSON.parse(history.pop());
  dirty = true;
  render();
  message("Undid the last change. Save to keep these decisions.");
};
$("save").onclick = async () => {
  if (!project || saving) return;
  saving = true;
  $("save").disabled = true;
  const saved = JSON.stringify({
    segments: project.segments,
    cuts: project.cuts,
  });
  try {
    const response = await fetch("/api/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Workbench-Token": token,
      },
      body: saved,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Save failed");
    dirty =
      saved !==
      JSON.stringify({ segments: project.segments, cuts: project.cuts });
    message(
      dirty
        ? "Saved. Newer changes are still unsaved."
        : "Decisions saved locally. The original video is untouched.",
    );
  } catch (e) {
    message(e.message, true);
  } finally {
    saving = false;
    $("save").disabled = false;
  }
};
$("edges").onclick = () => {
  if (!project) return;
  snapshot();
  project.cuts
    .filter((c) => c.kind === "edge")
    .forEach((c) => (c.selected = true));
  render();
};
$("restore").onclick = () => {
  if (!project) return;
  snapshot();
  project.cuts.forEach((c) => (c.selected = false));
  render();
};
$("import-button").onclick = () => $("transcript-file").click();
$("transcript-file").onchange = async (event) => {
  try {
    ensureLoaded();
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2_000_000)
      throw new Error("Transcript JSON must be smaller than 2 MB.");
    const rows = transcriptRows(
      JSON.parse(await file.text()),
      project.duration,
    );
    snapshot();
    project.segments = rows;
    project.cuts = project.cuts.filter((c) => c.kind !== "script");
    render();
    message(
      "Interactive script created. Previous script cuts were cleared; silence decisions were preserved.",
    );
  } catch (e) {
    message(e.message, true);
  } finally {
    event.target.value = "";
  }
};
$("download-edl").onclick = () => {
  if (!project) return;
  download(
    "reviewed.project.json",
    JSON.stringify(project, null, 2) + "\n",
    "application/json",
  );
  message(
    "Downloaded edit decisions. Keep the JSON beside the original project so the media path still resolves.",
  );
};
$("download-script").onclick = () => {
  if (!project) return;
  const header = `# ${project.title}\n\n${project.demo ? "Synthetic demo: illustrative text, not transcribed speech.\n\n" : ""}Source-timed script. Text corrections do not change the recording.\n\n`;
  const body = project.segments
    .map((line) => {
      const removed = project.cuts.some(
        (c) => c.id === `script-${line.id}` && c.selected,
      );
      return `## ${timecode(line.start)}–${timecode(line.end)}${removed ? " · CUT" : ""}\n\n${line.text}\n\nVisual note: ${line.notes || "—"}\n`;
    })
    .join("\n");
  download("reviewed-script.md", header + body, "text/markdown");
};
$("timeline").onclick = (event) => {
  if (!project) return;
  const rect = event.target.getBoundingClientRect();
  seek(
    Math.max(
      0,
      Math.min(
        project.duration,
        ((event.clientX - rect.left) / rect.width) * project.duration,
      ),
    ),
  );
};
video.addEventListener("timeupdate", () => {
  if (!project) return;
  $("clock").textContent = timecode(video.currentTime);
  for (const row of $("lines").children) {
    const line = project.segments.find((l) => l.id === row.dataset.line);
    row.classList.toggle(
      "active",
      Boolean(
        line && video.currentTime >= line.start && video.currentTime < line.end,
      ),
    );
  }
  drawTimeline();
});
function playback() {
  if (project && !video.paused && $("preview-cuts").checked) {
    const next = nextKeptTime(video.currentTime, project.cuts);
    if (next > video.currentTime) {
      video.currentTime = next;
      if (next >= project.duration - 0.01) video.pause();
    }
  }
  requestAnimationFrame(playback);
}
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
window.addEventListener("resize", drawTimeline);
try {
  const response = await fetch("/api/project");
  if (!response.ok) throw new Error("Could not load the local project.");
  const data = await response.json();
  project = data.project;
  token = data.token;
  $("demo-notice").hidden = !project.demo;
  render();
  const selected = project.cuts.filter((cut) => cut.selected).length;
  message(`${project.title} · ${selected} saved cut${selected === 1 ? "" : "s"} selected.`);
  playback();
} catch (e) {
  message(e.message, true);
}
