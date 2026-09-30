import { useState } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { EmailSettingsForm } from "../src/features/settings/EmailSettingsForm";
import { emailSettingsFixture } from "./fixtures";
import { renderWithProviders } from "./testProviders";

function handlers() {
  return [
    http.get("/api/settings/email", () => HttpResponse.json(emailSettingsFixture)),
  ];
}

function PageSwitcher() {
  const [visible, setVisible] = useState(true);
  return <><button onClick={() => setVisible((value) => !value)}>切换页面</button>{visible ? <EmailSettingsForm /> : <p>其他页面</p>}</>;
}

function responseGate() {
  let finish!: () => void;
  const promise = new Promise<void>((resolve) => { finish = resolve; });
  return { promise, finish };
}

it("restores a pending digest after navigation and prevents duplicate submission", async () => {
  const gate = responseGate();
  let requests = 0;
  let aborted = false;
  renderWithProviders(<PageSwitcher />, { handlers: [
    ...handlers(),
    http.post("/api/email/digest", async ({ request }) => {
      requests += 1;
      request.signal.addEventListener("abort", () => { aborted = true; });
      await gate.promise;
      return HttpResponse.json({ status: "sent", sent_at: "2026-09-30T00:00:00Z" });
    }),
  ] });
  const user = userEvent.setup();
  try {
    await user.click(screen.getByRole("button", { name: "立即发送日报" }));
    await screen.findByRole("button", { name: "正在刷新并发送..." });
    await user.click(screen.getByRole("button", { name: "切换页面" }));
    await user.click(screen.getByRole("button", { name: "切换页面" }));
    const pending = screen.getByRole("button", { name: "正在刷新并发送..." });
    expect(pending).toBeDisabled();
    await user.click(pending);
    expect(requests).toBe(1);
    expect(aborted).toBe(false);
  } finally {
    gate.finish();
  }
  expect(await screen.findByText("日报已发送")).toBeInTheDocument();
});

it.each(["success", "error"] as const)("restores a digest %s that completed while away", async (outcome) => {
  const gate = responseGate();
  const { queryClient } = renderWithProviders(<PageSwitcher />, { handlers: [
    ...handlers(),
    http.post("/api/email/digest", async () => {
      await gate.promise;
      return outcome === "success"
        ? HttpResponse.json({ status: "sent", sent_at: "2026-09-30T00:00:00Z" })
        : HttpResponse.json({ detail: { code: "SMTP_FAILED", message: "SMTP 连接失败" } }, { status: 502 });
    }),
  ] });
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "立即发送日报" }));
  await screen.findByRole("button", { name: "正在刷新并发送..." });
  await user.click(screen.getByRole("button", { name: "切换页面" }));
  gate.finish();
  await waitFor(() => expect(queryClient.isMutating()).toBe(0));
  await user.click(screen.getByRole("button", { name: "切换页面" }));

  expect(await screen.findByText(outcome === "success" ? "日报已发送" : "SMTP 连接失败")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "立即发送日报" })).toBeEnabled();
});

it("renders the email notification form and saves the payload", async () => {
  let received: Record<string, unknown> | null = null;
  renderWithProviders(<EmailSettingsForm />, {
    handlers: [
      ...handlers(),
      http.put("/api/settings/email", async ({ request }) => {
        received = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          ...emailSettingsFixture,
          enabled: true,
          recipient: "owner@example.com",
          smtp_host: "smtp.qq.com",
          smtp_username: "owner@qq.com",
          password_masked: "****code",
        });
      }),
    ],
  });
  const user = userEvent.setup();

  await screen.findByLabelText("收件人");
  await user.click(screen.getByRole("checkbox", { name: "启用邮件通知" }));
  await user.type(screen.getByLabelText("收件人"), "owner@example.com");
  await user.type(screen.getByLabelText("SMTP 服务器"), "smtp.qq.com");
  await user.type(screen.getByLabelText("账号"), "owner@qq.com");
  await user.type(screen.getByLabelText("授权码"), "smtp-auth-code");
  await user.click(screen.getByRole("button", { name: "保存邮件设置" }));

  expect(received).toMatchObject({
    enabled: true,
    recipient: "owner@example.com",
    smtp_host: "smtp.qq.com",
    smtp_username: "owner@qq.com",
    password: "smtp-auth-code",
  });
});

it("sends a test email and shows the result", async () => {
  renderWithProviders(<EmailSettingsForm />, {
    handlers: [
      ...handlers(),
      http.post("/api/settings/email/test", () => HttpResponse.json({ status: "ok", error_category: null })),
    ],
  });
  const user = userEvent.setup();

  await screen.findByRole("heading", { name: "邮件通知" });
  await user.click(screen.getByRole("button", { name: "发送测试邮件" }));

  expect(await screen.findByText("测试邮件已发送")).toBeInTheDocument();
});

it("triggers a manual digest and shows the sent result", async () => {
  renderWithProviders(<EmailSettingsForm />, {
    handlers: [
      ...handlers(),
      http.post("/api/email/digest", () => HttpResponse.json({ status: "sent", sent_at: "2026-08-04T00:00:00Z" })),
    ],
  });
  const user = userEvent.setup();

  await screen.findByRole("heading", { name: "邮件通知" });
  await user.click(screen.getByRole("button", { name: "立即发送日报" }));

  expect(await screen.findByText("日报已发送")).toBeInTheDocument();
});

it("shows the not-configured result for a manual digest", async () => {
  renderWithProviders(<EmailSettingsForm />, {
    handlers: [
      ...handlers(),
      http.post("/api/email/digest", () => HttpResponse.json({ status: "not_configured", sent_at: null })),
    ],
  });
  const user = userEvent.setup();

  await screen.findByRole("heading", { name: "邮件通知" });
  await user.click(screen.getByRole("button", { name: "立即发送日报" }));

  expect(await screen.findByText("请先完成邮件配置")).toBeInTheDocument();
});
