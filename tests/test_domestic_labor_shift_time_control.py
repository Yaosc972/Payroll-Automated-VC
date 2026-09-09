"""Verify the single range control's inferred payroll-day offsets."""
from pathlib import Path
import subprocess


def test_shift_relative_time_ranges():
    source = (Path(__file__).resolve().parents[1] / "bonus_platform/static/domestic-labor.js").read_text()
    function = source.split("function resolveMissingShiftPeriod(", 1)[1].split("\nfunction collectMissingShiftBreakSegments", 1)[0]
    script = "function resolveMissingShiftPeriod(" + function + r'''
const assert = require('node:assert/strict');
assert.equal(resolveMissingShiftPeriod('23:30','00:15','18:00-27:00;').period,'23:30-24:15');
assert.equal(resolveMissingShiftPeriod('01:00','01:30','18:00-27:00;').period,'25:00-25:30');
assert.equal(resolveMissingShiftPeriod('12:00','13:00','08:00-17:00;').period,'12:00-13:00');
assert.equal(resolveMissingShiftPeriod('06:00','06:30','20:00-32:00;').category,'早上休息');
assert.equal(resolveMissingShiftPeriod('01:00','01:30','18:00-27:00;').label,'次日 01:00 — 次日 01:30');
assert.throws(()=>resolveMissingShiftPeriod('01:00','01:00','18:00-27:00;'));
assert.throws(()=>resolveMissingShiftPeriod('01:00','01:30',''));
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
