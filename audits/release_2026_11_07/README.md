# Release execution evidence

Current summary: `verification_summary.json`; full-suite runs: `final_run_1`
and `final_run_2`; independent probes: `protocol/results.json`; maximum file:
`maximum_file.json`. See `../../docs/release_closure.md` for interpretation.

Failed baseline/candidate runs and before-fix logs are deliberately retained.
They are not current pass results. Successful unittest subtests are reported
separately from the90 collected methods. Original JUnit metadata in
`full_run_1.xml` counts subtests; its JSON includes both counts for clarity.

Captured TXT output is normalized to UTF-8/LF and trailing whitespace is removed
for Git review; diagnostic text, assertions, tracebacks and results are retained.
JSON/XML preserve commands, interpreter, durations and outcomes. `head` in these
records names the worktree parent during development; per-file hashes identify
tested working files. Only standalone `test_udp_streaming.py` changed after the
two90-method runs; it was independently rerun twice. The source mismatch and
reason are recorded explicitly in `verification_summary.json`.

`package_smoke.json` records the pre-commit candidate. The final archive is
rebuilt after commit; its separately delivered receipt identifies its exact
archive SHA-256 and commit, avoiding a self-referential archive hash.
