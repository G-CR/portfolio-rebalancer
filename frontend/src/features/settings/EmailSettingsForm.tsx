import { Mail, Save, Send } from "lucide-react";
import { useEffect, useState } from "react";

import type { EmailSecurity, EmailTestResult } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { useEmailSettings, useSaveEmailSettings, useTestEmailSettings } from "./api";
import styles from "../marketData/MarketData.module.css";

const TEST_ERROR_LABELS: Record<string, string> = {
  not_configured: "邮件尚未配置完整",
  smtp_connect_failed: "无法连接 SMTP 服务器",
  smtp_auth_failed: "SMTP 认证失败，请检查账号和授权码",
  smtp_recipient_rejected: "收件人被邮件服务器拒绝",
  smtp_timeout: "SMTP 连接超时",
  smtp_send_failed: "邮件发送失败",
};

export function EmailSettingsForm() {
  const settings = useEmailSettings();
  const save = useSaveEmailSettings();
  const test = useTestEmailSettings();
  const [enabled, setEnabled] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("465");
  const [security, setSecurity] = useState<EmailSecurity>("ssl");
  const [username, setUsername] = useState("");
  const [fromAddress, setFromAddress] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (!settings.data) return;
    setEnabled(settings.data.enabled);
    setRecipient(settings.data.recipient ?? "");
    setHost(settings.data.smtp_host ?? "");
    setPort(String(settings.data.smtp_port));
    setSecurity(settings.data.smtp_security);
    setUsername(settings.data.smtp_username ?? "");
    setFromAddress(settings.data.from_address ?? "");
  }, [settings.data?.updated_at]);

  async function submit() {
    await save.mutateAsync({
      enabled,
      recipient,
      smtp_host: host,
      smtp_port: Number(port),
      smtp_security: security,
      smtp_username: username,
      from_address: fromAddress || null,
      password: password || null,
    });
    setPassword("");
  }

  function testLabel(result: EmailTestResult) {
    return TEST_ERROR_LABELS[result.error_category ?? ""] ?? "测试邮件发送失败";
  }

  return (
    <section className={styles.generalSettings} aria-labelledby="email-settings-title">
      <header className={styles.sectionHeading}>
        <div><p>EMAIL NOTIFICATION</p><h2 id="email-settings-title">邮件通知</h2></div>
        <label className={styles.enabled}><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />启用每日邮件</label>
      </header>
      {settings.isPending ? <p className={styles.muted}>正在载入邮件设置...</p> : null}
      {settings.isError ? <p className={styles.error} role="alert">邮件设置加载失败。</p> : null}
      {settings.data ? <div className={styles.generalGrid}>
        <FormField label="收件人"><input type="email" value={recipient} onChange={(event) => setRecipient(event.target.value)} /></FormField>
        <FormField label="SMTP 服务器"><input value={host} onChange={(event) => setHost(event.target.value)} /></FormField>
        <FormField label="端口"><input inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value)} /></FormField>
        <FormField label="安全方式"><select value={security} onChange={(event) => setSecurity(event.target.value as EmailSecurity)}><option value="ssl">SSL</option><option value="starttls">STARTTLS</option></select></FormField>
        <FormField label="账号"><input value={username} onChange={(event) => setUsername(event.target.value)} /></FormField>
        <FormField label="授权码"><input type="password" autoComplete="new-password" value={password} placeholder={settings.data.password_masked ?? "输入授权码"} onChange={(event) => setPassword(event.target.value)} /></FormField>
        <FormField label="发件人（可选）"><input type="email" value={fromAddress} onChange={(event) => setFromAddress(event.target.value)} /></FormField>
      </div> : null}
      <div className={styles.providerActions}>
        <button type="button" className={styles.secondary} onClick={() => void test.mutateAsync()} disabled={test.isPending || save.isPending}><Send size={15} aria-hidden="true" />{test.isPending ? "正在发送" : "发送测试邮件"}</button>
        <button type="button" className={styles.primary} onClick={() => void submit()} disabled={save.isPending}><Save size={16} aria-hidden="true" />保存邮件设置</button>
      </div>
      {test.data ? <small className={test.data.status === "ok" ? styles.validationGood : styles.validationBad}>{test.data.status === "ok" ? "测试邮件已发送" : testLabel(test.data)}</small> : null}
      {save.isError ? <small className={styles.validationBad}>{save.error instanceof Error ? save.error.message : "邮件设置保存失败。"}</small> : null}
      <small className={styles.muted}><Mail size={12} aria-hidden="true" /> 每日刷新完成后，在工作日自动发送盈亏分析与再平衡建议邮件。</small>
    </section>
  );
}
