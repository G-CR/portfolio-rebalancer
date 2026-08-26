# Manual Snapshot Entry Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the low-frequency manual snapshot action from the global topbar while retaining and clarifying the complete manual-capture workflow on the history page.

**Architecture:** Keep the existing snapshot mutation, drawer state, query-parameter compatibility, validation, and API behavior unchanged. Make only presentation-level changes in `AppShell` and `SnapshotsPage`, with focused component tests proving the global action is absent and the history-local workflow still opens, submits, and supports the legacy deep link.

**Tech Stack:** React 19, TypeScript, React Router, TanStack Query, Vitest, Testing Library, MSW, Vite

## Global Constraints

- The global topbar must not render or navigate through a “保存快照” action.
- The history-page entry and drawer title must read “记录当前时点”.
- The idle submit label must read “确认记录”; the pending label must read “正在记录”.
- `/history?capture=manual` must continue to open the manual-capture drawer and consume the `capture` query parameter.
- The note field, stale/manual-data note requirement, structured API errors, note preservation on failure, snapshot mutation, history refresh, backend API, and database schema must remain unchanged.
- Automatic daily snapshots and before/after rebalance snapshots must remain unchanged.
- Do not access or mutate production data while testing.

---

### Task 1: Remove the global manual-snapshot command

**Files:**
- Modify: `frontend/tests/AppShell.test.tsx`
- Modify: `frontend/src/components/AppShell/AppShell.tsx`

**Interfaces:**
- Consumes: `AppShell()` and its existing topbar market-data refresh behavior.
- Produces: An `AppShell` topbar whose only action button is the market-data refresh command; no snapshot route or snapshot icon is referenced by the shell.

- [ ] **Step 1: Write the failing AppShell test**

Add this test immediately after the route-rendering test in `frontend/tests/AppShell.test.tsx`:

```tsx
  it("does not expose manual snapshot capture as a global command", () => {
    installMatchMedia(false);
    renderShell();

    expect(screen.queryByRole("button", { name: "保存快照" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("保存当前快照")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
Set-Location frontend
npm test -- AppShell.test.tsx -t "does not expose manual snapshot capture as a global command"
```

Expected: FAIL because the current topbar still contains the button named `保存快照` and title `保存当前快照`.

- [ ] **Step 3: Remove the global command and unused router/icon dependencies**

Change the imports at the top of `frontend/src/components/AppShell/AppShell.tsx` to:

```tsx
import { Menu, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
```

Remove this declaration from `AppShell()`:

```tsx
  const navigate = useNavigate();
```

Remove this button from `styles.topbarCommands`, leaving the existing refresh button untouched:

```tsx
          <button className={styles.primaryCommand} type="button" title="保存当前快照" onClick={() => navigate("/history?capture=manual")}>
            <Save size={16} aria-hidden="true" />
            <span>保存快照</span>
          </button>
```

- [ ] **Step 4: Run the complete AppShell test file**

Run:

```powershell
Set-Location frontend
npm test -- AppShell.test.tsx
```

Expected: PASS for every test in `AppShell.test.tsx`, including the new absence assertion and all existing refresh/navigation behavior.

- [ ] **Step 5: Commit the global-entry removal**

```powershell
git add frontend/tests/AppShell.test.tsx frontend/src/components/AppShell/AppShell.tsx
git commit -m "refactor: remove global snapshot command"
```

### Task 2: Clarify the history-page manual-capture workflow

**Files:**
- Modify: `frontend/tests/SnapshotsPage.test.tsx`
- Modify: `frontend/src/pages/SnapshotsPage.tsx`

**Interfaces:**
- Consumes: `useCreateManualSnapshot()`, `WorkDrawer`, `useSearchParams()`, and the existing `POST /api/snapshots/manual` contract `{ note: string | null }`.
- Produces: A history-local button and drawer named `记录当前时点`, with `确认记录`/`正在记录` submit labels; the deep link still opens that drawer and removes `capture=manual` from the address.

- [ ] **Step 1: Add failing tests for the local entry and submit labels**

Add this test inside the `SnapshotsPage` describe block before the deep-link test in `frontend/tests/SnapshotsPage.test.tsx`:

```tsx
  it("records the current point from the history-local workflow", async () => {
    const user = userEvent.setup();
    let resolveCapture!: (response: Response) => void;
    const captureResponse = new Promise<Response>((resolve) => {
      resolveCapture = resolve;
    });
    renderWithProviders(<SnapshotsPage />, { handlers: [
      ...handlers(),
      http.post("/api/snapshots/manual", () => captureResponse),
    ] });

    await user.click(await screen.findByRole("button", { name: "记录当前时点" }));
    const dialog = await screen.findByRole("dialog", { name: "记录当前时点" });
    expect(within(dialog).getByRole("button", { name: "确认记录" })).toBeEnabled();

    await user.type(within(dialog).getByLabelText("快照备注"), "临时复核");
    await user.click(within(dialog).getByRole("button", { name: "确认记录" }));
    expect(await within(dialog).findByRole("button", { name: "正在记录" })).toBeDisabled();

    resolveCapture(HttpResponse.json(detail, { status: 201 }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "记录当前时点" })).not.toBeInTheDocument();
    });
  });
```

- [ ] **Step 2: Strengthen the existing deep-link compatibility test**

Replace the existing `opens the manual capture workflow from the shell command URL` test with:

```tsx
  it("opens manual capture from the legacy deep link and consumes the query parameter", async () => {
    renderWithProviders(<SnapshotsPage />, { route: "/history?capture=manual", handlers: handlers() });

    expect(await screen.findByRole("dialog", { name: "记录当前时点" })).toBeInTheDocument();
    expect(screen.getByLabelText("快照备注")).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.search).toBe("");
    });
  });
```

- [ ] **Step 3: Run the two focused tests and verify they fail for copy only**

Run:

```powershell
Set-Location frontend
npm test -- SnapshotsPage.test.tsx -t "records the current point|opens manual capture from the legacy deep link"
```

Expected: FAIL because the current page uses `保存当前快照`, `保存手动快照`, `保存快照`, and `正在保存`. The query-parameter behavior itself should remain compatible.

- [ ] **Step 4: Change only the history workflow copy**

In `frontend/src/pages/SnapshotsPage.tsx`, replace the history header action with:

```tsx
        <button className={styles.primaryButton} type="button" onClick={() => setManualOpen(true)}><Camera size={16} aria-hidden="true" />记录当前时点</button>
```

Change the manual drawer title to:

```tsx
      <WorkDrawer open={manualOpen} title="记录当前时点" onClose={() => setManualOpen(false)}>
```

Within the drawer’s primary submit button, retain its icon, pending state, disabled state, and click handler, but replace the label expression with:

```tsx
{createManual.isPending ? "正在记录" : "确认记录"}
```

Do not alter `saveManual()`, the textarea, its note rules, error rendering, `useEffect()` query-parameter consumption, or any snapshot API hook.

- [ ] **Step 5: Run the complete SnapshotsPage test file**

Run:

```powershell
Set-Location frontend
npm test -- SnapshotsPage.test.tsx
```

Expected: PASS for every test in `SnapshotsPage.test.tsx`, including capture invalidation, error/empty states, accessibility, the new local workflow, and legacy deep-link compatibility.

- [ ] **Step 6: Commit the history-workflow copy change**

```powershell
git add frontend/tests/SnapshotsPage.test.tsx frontend/src/pages/SnapshotsPage.tsx
git commit -m "refactor: clarify manual snapshot workflow"
```

### Task 3: Verify the complete frontend

**Files:**
- Verify only: `frontend/src/components/AppShell/AppShell.tsx`
- Verify only: `frontend/src/pages/SnapshotsPage.tsx`
- Verify only: `frontend/tests/AppShell.test.tsx`
- Verify only: `frontend/tests/SnapshotsPage.test.tsx`

**Interfaces:**
- Consumes: The completed Task 1 and Task 2 frontend changes.
- Produces: Evidence that the complete frontend test suite and production build remain healthy without any backend or production-data access.

- [ ] **Step 1: Run the full frontend unit/integration suite**

Run:

```powershell
Set-Location frontend
npm test
```

Expected: All Vitest files and tests PASS. No production service or production database is contacted because tests use MSW handlers.

- [ ] **Step 2: Run the production frontend build**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: TypeScript and Vite complete successfully and emit the production bundle without unused-import or type errors.

- [ ] **Step 3: Confirm the final diff is scoped and clean**

Run from the repository root:

```powershell
git diff --check HEAD~2..HEAD
git diff --stat HEAD~2..HEAD
git status --short
```

Expected: `git diff --check` emits no output; the diff contains only the four frontend source/test files from Tasks 1–2; the working tree is clean.

