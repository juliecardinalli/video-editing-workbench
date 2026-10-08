export function mergedCuts(cuts) {
  const result = [];
  for (const cut of cuts
    .filter((c) => c.selected)
    .sort((a, b) => a.start - b.start)) {
    const last = result.at(-1);
    if (last && cut.start <= last.end) last.end = Math.max(last.end, cut.end);
    else result.push({ start: cut.start, end: cut.end });
  }
  return result;
}

export function stats(project) {
  const removed = mergedCuts(project.cuts).reduce(
    (total, c) => total + c.end - c.start,
    0,
  );
  return {
    original: project.duration,
    removed,
    edited: Math.max(0, project.duration - removed),
  };
}

export function nextKeptTime(time, cuts) {
  return (
    mergedCuts(cuts).find((c) => time >= c.start && time < c.end)?.end ?? time
  );
}

export function transcriptRows(data, duration) {
  const rows = Array.isArray(data) ? data : (data?.segments ?? data?.words);
  if (!Array.isArray(rows) || rows.length > 10000)
    throw new Error(
      "Use JSON with a segments or words array (at most 10,000 rows).",
    );
  let previousEnd = 0;
  return rows.map((row, i) => {
    const text = row?.text ?? row?.word;
    const start = row?.start,
      end = row?.end;
    if (
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      start < 0 ||
      end <= start ||
      end > duration + 0.02 ||
      start < previousEnd - 0.001
    ) {
      throw new Error(
        "Timestamps must be chronological, non-overlapping, and inside the video.",
      );
    }
    if (typeof text !== "string" || !text.trim() || text.length > 10000)
      throw new Error("Every row needs text (at most 10,000 characters).");
    const notes = row.notes ?? "";
    if (typeof notes !== "string" || notes.length > 10000)
      throw new Error("Notes must be text (at most 10,000 characters).");
    previousEnd = end;
    return {
      id: `line-${i + 1}`,
      start,
      end: Math.min(duration, end),
      text: text.trim(),
      notes,
    };
  });
}

export function toggleLine(project, line) {
  const id = `script-${line.id}`;
  const old = project.cuts.find((c) => c.id === id);
  if (old) old.selected = !old.selected;
  else
    project.cuts.push({
      id,
      start: line.start,
      end: line.end,
      kind: "script",
      reason: "Reviewed transcript cut",
      selected: true,
    });
}

export function timecode(value) {
  const centiseconds = Math.round(value * 100);
  return `${Math.floor(centiseconds / 6000)}:${String(Math.floor(centiseconds / 100) % 60).padStart(2, "0")}.${String(centiseconds % 100).padStart(2, "0")}`;
}
