import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackupRestorePanel } from "../src/features/backups/BackupRestorePanel";
import { renderWithProviders } from "./testProviders";

const preview = {
  exported_at: "2026-08-23T10:20:30Z",
  source_application_version: "1.4.0",
  source_format_version: 1,
  current_format_version: 1,
  record_counts: { "data/holdings.json": 4, "data/snapshots.json": 12 },
  current_record_counts: { "data/holdings.json": 3, "data/snapshots.json": 10 },
  count_comparison: {
    "data/holdings.json": { backup: 4, current: 3, delta: 1 },
    "data/snapshots.json": { backup: 12, current: 10, delta: 2 },
  },
  warnings: ["恢复会覆盖当前全部业务数据。"],
  credential_categories: ["AKShare", "SMTP"],
  restore_token: "one-time-token",
  expires_at: "2026-08-23T10:50:30Z",
};

const safety = {
  id: "c0000000-0000-4000-8000-000000000001",
  exported_at: "2026-08-22T08:00:00Z",
  source_application_version: "1.3.0",
  format_version: 1,
  size_bytes: 1536,
  record_counts: { "data/holdings.json": 3, "data/snapshots.json": 10 },
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("BackupRestorePanel", () => {
  it("keeps the plaintext warning visible and exports, polls, downloads, then revokes the object URL", async () => {
    const user = userEvent.setup();
    let polls = 0;
    const createObjectURL = vi.fn(() => "blob:backup");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    renderWithProviders(<BackupRestorePanel />, { handlers: [
      http.post("/api/backups/export", () => HttpResponse.json({ id: "export-1", kind: "export", status: "pending", stage: "validated", download_ready: false, error: null, safety_backup_id: null }, { status: 202 })),
      http.get("/api/backups/operations/export-1", () => {
        polls += 1;
        return HttpResponse.json({ id: "export-1", kind: "export", status: "succeeded", stage: "completed", download_ready: true, error: null, safety_backup_id: null });
      }),
      http.get("/api/backups/operations/export-1/download", () => new HttpResponse(new Blob(["archive"]), { headers: { "Content-Disposition": "attachment; filename=\"portfolio-backup-20260823.portfolio-backup\"" } })),
    ] });

    expect(screen.getByText(/备份文件包含明文 API 密钥和邮箱密码/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "导出完整备份" }));
    expect(await screen.findByText("完整备份已下载")).toBeVisible();
    expect(polls).toBeGreaterThan(0);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:backup");
  });

  it("uploads raw bytes and presents metadata, comparisons, and credential category names without values", async () => {
    const user = userEvent.setup();
    let contentType = "";
    let filename = "";
    renderWithProviders(<BackupRestorePanel />, { handlers: [
      http.post("/api/backups/upload", async ({ request }) => {
        contentType = request.headers.get("Content-Type") ?? "";
        filename = request.headers.get("X-Backup-Filename") ?? "";
        expect((await request.arrayBuffer()).byteLength).toBeGreaterThan(0);
        return HttpResponse.json(preview);
      }),
    ] });

    const file = new File(["backup bytes"], "mine.portfolio-backup", { type: "application/octet-stream" });
    await user.upload(screen.getByLabelText("选择备份文件"), file);

    const dialog = await screen.findByRole("dialog", { name: "恢复备份预览" });
    expect(contentType).toBe("application/octet-stream");
    expect(filename).toBe(file.name);
    expect(dialog).toHaveTextContent("1.4.0");
    expect(dialog).toHaveTextContent("格式 1 → 当前格式 1");
    expect(dialog).toHaveTextContent("持仓");
    expect(dialog).toHaveTextContent("4");
    expect(dialog).toHaveTextContent("当前 3");
    expect(dialog).toHaveTextContent("AKShare");
    expect(dialog).toHaveTextContent("SMTP");
    expect(dialog).not.toHaveTextContent("one-time-token");
  });

  it("requires the exact confirmation, reports all six restore stages, and reloads after clearing cached queries", async () => {
    const user = userEvent.setup();
    const stages = ["validated", "locking_data", "creating_safety_backup", "writing_data", "verifying_integrity", "completed"];
    let poll = 0;
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    const { queryClient } = renderWithProviders(<BackupRestorePanel />, { handlers: [
      http.post("/api/backups/upload", () => HttpResponse.json(preview)),
      http.post("/api/backups/restore", async ({ request }) => {
        expect(await request.json()).toEqual({ restore_token: "one-time-token", confirmation: "恢复" });
        return HttpResponse.json({ id: "restore-1", kind: "restore", status: "pending", stage: "validated", download_ready: false, error: null, safety_backup_id: null }, { status: 202 });
      }),
      http.get("/api/backups/operations/restore-1", () => {
        const stage = stages[Math.min(poll, stages.length - 1)];
        poll += 1;
        return HttpResponse.json({ id: "restore-1", kind: "restore", status: stage === "completed" ? "succeeded" : "running", stage, download_ready: false, error: null, safety_backup_id: stage === "completed" ? safety.id : null });
      }),
    ] });
    queryClient.setQueryData(["sentinel"], { secret: "stale" });

    await user.upload(screen.getByLabelText("选择备份文件"), new File(["x"], "restore.portfolio-backup"));
    const dialog = await screen.findByRole("dialog", { name: "恢复备份预览" });
    const confirm = within(dialog).getByLabelText("输入“恢复”以确认");
    const start = within(dialog).getByRole("button", { name: "开始恢复" });
    expect(start).toBeDisabled();
    await user.type(confirm, "恢");
    expect(start).toBeDisabled();
    await user.type(confirm, "复");
    expect(start).toBeEnabled();
    await user.click(start);

    for (const label of ["校验完成", "锁定数据", "创建安全备份", "写入数据", "完整性复核", "完成"]) {
      expect(await screen.findByText(label, {}, { timeout: 7000 })).toBeVisible();
    }
    expect(await screen.findByText(/安全备份.*c0000000/, {}, { timeout: 8000 })).toBeVisible();
    await waitFor(() => expect(queryClient.getQueryData(["sentinel"])).toBeUndefined());
    expect(reload).toHaveBeenCalledTimes(1);
  }, 15000);

  it.each([
    ["BACKUP_CORRUPT", "备份文件已损坏"],
    ["BACKUP_FUTURE_VERSION", "备份版本高于当前系统"],
    ["BACKUP_INCOMPATIBLE", "备份结构不兼容"],
    ["BACKUP_RELATIONSHIP_INVALID", "备份中的数据关系无效"],
    ["BACKUP_RESOURCE_LIMIT", "备份超出资源限制"],
    ["BACKUP_OPERATION_CONFLICT", "已有备份任务正在运行"],
    ["BACKUP_ROLLBACK", "恢复失败，当前数据已保持不变"],
    ["BACKUP_OPERATION_INTERRUPTED", "任务因服务中断而停止"],
  ])("localizes %s without exposing backend detail", async (code, expected) => {
    const user = userEvent.setup();
    renderWithProviders(<BackupRestorePanel />, { handlers: [
      http.post("/api/backups/export", () => HttpResponse.json({ detail: { code, message: "C:\\secret\\db password=raw" } }, { status: 409 })),
    ] });
    await user.click(screen.getByRole("button", { name: "导出完整备份" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.getByRole("alert")).not.toHaveTextContent("secret");
  });

  it("disables backup actions only while active and supports retry", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    renderWithProviders(<><BackupRestorePanel /><button type="button">历史筛选仍可用</button></>, { handlers: [
      http.post("/api/backups/export", () => {
        attempts += 1;
        if (attempts === 1) return HttpResponse.json({ detail: { code: "BACKUP_RESOURCE_LIMIT", message: "no space" } }, { status: 507 });
        return HttpResponse.json({ id: "export-2", kind: "export", status: "pending", stage: "validated", download_ready: false, error: null, safety_backup_id: null }, { status: 202 });
      }),
      http.get("/api/backups/operations/export-2", async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json({ id: "export-2", kind: "export", status: "running", stage: "validated", download_ready: false, error: null, safety_backup_id: null });
      }),
    ] });
    await user.click(screen.getByRole("button", { name: "导出完整备份" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("备份超出资源限制");
    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "导出完整备份" })).toBeDisabled());
    expect(screen.getByLabelText("选择备份文件")).toBeDisabled();
    expect(screen.getByRole("button", { name: "历史筛选仍可用" })).toBeEnabled();
  });

  it("offers a status retry when operation polling temporarily fails", async () => {
    const user = userEvent.setup();
    let polls = 0;
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:retry"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderWithProviders(<BackupRestorePanel />, { handlers: [
      http.post("/api/backups/export", () => HttpResponse.json({ id: "export-retry", kind: "export", status: "pending", stage: "validated", download_ready: false, error: null, safety_backup_id: null }, { status: 202 })),
      http.get("/api/backups/operations/export-retry", () => {
        polls += 1;
        if (polls === 1) return HttpResponse.json({ detail: { code: "HTTP_ERROR", message: "gateway path C:\\private" } }, { status: 504 });
        return HttpResponse.json({ id: "export-retry", kind: "export", status: "succeeded", stage: "completed", download_ready: true, error: null, safety_backup_id: null });
      }),
      http.get("/api/backups/operations/export-retry/download", () => new HttpResponse(new Blob(["archive"]))),
    ] });

    await user.click(screen.getByRole("button", { name: "导出完整备份" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("任务状态暂时无法更新");
    await user.click(screen.getByRole("button", { name: "重试查询状态" }));
    expect(await screen.findByText("完整备份已下载")).toBeVisible();
    expect(polls).toBe(2);
  });

  it("lists, downloads, previews/restores, and separately confirms deletion of safety backups", async () => {
    const user = userEvent.setup();
    let deleted = false;
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:safety"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderWithProviders(<BackupRestorePanel />, { handlers: [
      http.get("/api/backups/safety", () => HttpResponse.json(deleted ? [] : [safety])),
      http.get(`/api/backups/safety/${safety.id}/download`, () => new HttpResponse(new Blob(["safe"]), { headers: { "Content-Disposition": "attachment; filename=\"safety.portfolio-backup\"" } })),
      http.post(`/api/backups/safety/${safety.id}/preview`, () => HttpResponse.json(preview)),
      http.delete(`/api/backups/safety/${safety.id}`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("confirm")).toBe("true");
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    ] });

    await user.click(screen.getByRole("button", { name: "管理恢复前安全备份" }));
    const row = await screen.findByRole("row", { name: /1\.5 KB/ });
    expect(row).toHaveTextContent("1.3.0");
    await user.click(within(row).getByRole("button", { name: "下载" }));
    await user.click(within(row).getByRole("button", { name: "恢复" }));
    expect(await screen.findByRole("dialog", { name: "恢复备份预览" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "关闭工作抽屉" }));
    await user.click(within(row).getByRole("button", { name: "删除" }));
    const deletion = await screen.findByRole("dialog", { name: "删除安全备份" });
    expect(within(deletion).getByText(/不会使用恢复令牌/)).toBeVisible();
    await user.click(within(deletion).getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(screen.queryByRole("row", { name: /1\.5 KB/ })).not.toBeInTheDocument());
  });
});
