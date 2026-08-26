# Task 2 report: Clarify the history-page manual-capture workflow

## Implementation

- Added the requested history-local workflow test for opening `记录当前时点`, submitting a note, observing the disabled `正在记录` state, and closing after a successful `201` response.
- Replaced the legacy deep-link test with coverage for opening `记录当前时点` from `/history?capture=manual`, preserving and asserting query-parameter consumption.
- Updated only the history action, drawer title, and submit labels in `SnapshotsPage.tsx`; mutation logic, note handling, error rendering, query consumption, and API hooks are unchanged.

## Files changed

- `frontend/tests/SnapshotsPage.test.tsx`
- `frontend/src/pages/SnapshotsPage.tsx`

## Verification

RED command:

```powershell
Set-Location frontend
npm test -- SnapshotsPage.test.tsx -t "records the current point|opens manual capture from the legacy deep link"
```

RED result: FAIL, 2 tests failed and 11 skipped. The expected copy-only failures were inability to find `记录当前时点` and `记录当前时点` dialog because the implementation still rendered `保存当前快照` / `保存手动快照` (and old submit labels). The rendered page showed the legacy labels; the query path was still being consumed.

GREEN focused command:

```powershell
Set-Location frontend
npm test -- SnapshotsPage.test.tsx -t "records the current point|opens manual capture from the legacy deep link"
```

GREEN result: PASS, 2 tests passed, 11 skipped.

GREEN complete-file command:

```powershell
Set-Location frontend
npm test -- SnapshotsPage.test.tsx
```

GREEN result: PASS, 13 tests passed, 0 failed.

## Self-review

- `git diff --check` passed with no whitespace errors.
- The patch is limited to the two requested source/test files and the required report.
- Existing manual snapshot behavior and compatibility hooks remain intact.

## Concerns

None.
