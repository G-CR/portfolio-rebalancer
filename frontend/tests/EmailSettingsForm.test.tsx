import { screen } from "@testing-library/react";
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
  await user.click(screen.getByRole("checkbox", { name: "启用每日邮件" }));
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
