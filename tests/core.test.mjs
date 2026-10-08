import test from "node:test";
import assert from "node:assert/strict";
import {
  mergedCuts,
  stats,
  nextKeptTime,
  transcriptRows,
  toggleLine,
  timecode,
} from "../web/core.mjs";

test("overlapping cuts are counted once", () => {
  const cuts = [
    { start: 1, end: 3, selected: true },
    { start: 2, end: 4, selected: true },
    { start: 8, end: 9, selected: false },
  ];
  assert.deepEqual(mergedCuts(cuts), [{ start: 1, end: 4 }]);
  assert.deepEqual(stats({ duration: 12, cuts }), {
    original: 12,
    edited: 9,
    removed: 3,
  });
  assert.equal(nextKeptTime(2.5, cuts), 4);
  assert.equal(nextKeptTime(4, cuts), 4);
});
test("toggle line preserves timestamps and can be undone", () => {
  const p = { cuts: [] },
    line = { id: "line-1", start: 1, end: 3 };
  toggleLine(p, line);
  assert.equal(p.cuts[0].start, 1);
  assert.equal(p.cuts[0].end, 3);
  assert.equal(p.cuts[0].selected, true);
  toggleLine(p, line);
  assert.equal(p.cuts.length, 1);
  assert.equal(p.cuts[0].selected, false);
});
test("words and segments import without character-based timing estimates", () => {
  assert.equal(
    transcriptRows({ words: [{ start: 1, end: 2, word: "Hi" }] }, 12)[0].text,
    "Hi",
  );
  assert.throws(() => transcriptRows([{ text: "Untimed" }], 12));
  assert.throws(() =>
    transcriptRows(
      [
        { start: 0, end: 2, text: "A" },
        { start: 1, end: 3, text: "B" },
      ],
      12,
    ),
  );
  assert.throws(() => transcriptRows([{ start: 0, end: 13, text: "A" }], 12));
  assert.throws(() => transcriptRows([{ start: 0, end: 2, text: "" }], 12));
});
test("timecodes roll over without :60", () => {
  assert.equal(timecode(59.999), "1:00.00");
  assert.equal(timecode(1.23), "0:01.23");
});
