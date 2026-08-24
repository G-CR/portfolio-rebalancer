import { AlertTriangle, Archive, ChevronDown, Download, FileUp, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import type { BackupOperation, BackupPreview, BackupStage, SafetyBackup } from "../../api/types";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import {
  backupKeys,
  saveBackupDownload,
  useBackupOperation,
  useBackupUpload,
  useDeleteSafetyBackup,
  useSafetyBackups,
  useSafetyPreview,
  useStartBackupExport,
  useStartBackupRestore,
} from "./api";
import styles from "./BackupRestore.module.css";

const stages: { id: BackupStage; label: string }[] = [
  { id: "validated", label: "校验完成" },
  { id: "locking_data", label: "锁定数据" },
  { id: "creating_safety_backup", label: "创建安全备份" },
  { id: "writing_data", label: "写入数据" },
  { id: "verifying_integrity", label: "完整性复核" },
  { id: "completed", label: "完成" },
];

const memberLabels: Record<string, string> = {
  "data/asset_classes.json": "资产类别",
  "data/holdings.json": "持仓",
  "data/holding_defaults.json": "持仓默认值",
  "data/market_data.json": "行情历史",
  "data/market_data_overrides.json": "手动行情",
  "data/cost_adjustments.json": "成本调整",
  "data/snapshots.json": "历史快照",
  "data/snapshot_items.json": "快照明细",
  "data/rebalance_plans.json": "再平衡方案",
  "data/settings.json": "系统设置",
};

const errorLabels: Record<string, string> = {
  BACKUP_CORRUPT: "备份文件已损坏，请重新选择有效文件。",
  BACKUP_ARCHIVE_INVALID: "备份文件已损坏，请重新选择有效文件。",
  BACKUP_FUTURE_VERSION: "备份版本高于当前系统，请先升级应用。",
  BACKUP_VERSION_FUTURE: "备份版本高于当前系统，请先升级应用。",
  BACKUP_INCOMPATIBLE: "备份结构不兼容，无法在当前版本恢复。",
  BACKUP_RELATIONSHIP_INVALID: "备份中的数据关系无效，未修改当前数据。",
  BACKUP_INVALID_RELATIONSHIP: "备份中的数据关系无效，未修改当前数据。",
  BACKUP_RESOURCE_LIMIT: "备份超出资源限制，或服务器可用空间不足。",
  BACKUP_OPERATION_CONFLICT: "已有备份任务正在运行，请稍后重试。",
  BACKUP_CONFLICT: "已有备份任务正在运行，请稍后重试。",
  BACKUP_ROLLBACK: "恢复失败，当前数据已保持不变。",
  BACKUP_RESTORE_FAILED: "恢复失败，当前数据已保持不变。",
  BACKUP_OPERATION_INTERRUPTED: "任务因服务中断而停止，请重试。",
  BACKUP_INTERRUPTED: "任务因服务中断而停止，请重试。",
  BACKUP_SAFETY_NOT_FOUND: "安全备份已不存在，请刷新列表。",
  BACKUP_SAFETY_IN_USE: "该安全备份正在被恢复任务使用，暂时无法删除。",
  BACKUP_STATUS_UNAVAILABLE: "任务状态暂时无法更新，请重试查询。",
};

type FailureState = {
  error: unknown;
  retry?: () => void;
};

function localizedError(error: unknown) {
  if (error instanceof ApiError) return errorLabels[error.code] ?? "备份操作失败，请稍后重试。";
  if (error && typeof error === "object" && "code" in error) {
    const code = String((error as { code: unknown }).code);
    return errorLabels[code] ?? "备份操作失败，请稍后重试。";
  }
  return "备份操作失败，请稍后重试。";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function totalRecords(counts: Record<string, number>) {
  return Object.values(counts).reduce((sum, count) => sum + count, 0);
}

function PreviewContent({ preview, confirmation, onConfirmation }: {
  preview: BackupPreview;
  confirmation: string;
  onConfirmation: (value: string) => void;
}) {
  return <div className={styles.preview}>
    <div className={styles.previewMeta}>
      <div><span>导出时间</span><strong>{formatDate(preview.exported_at)}</strong></div>
      <div><span>来源应用</span><strong>{preview.source_application_version}</strong></div>
      <div><span>格式兼容</span><strong>格式 {preview.source_format_version} → 当前格式 {preview.current_format_version}</strong></div>
      <div><span>恢复凭据</span><strong>{preview.credential_categories.length ? preview.credential_categories.join("、") : "无外部凭据"}</strong></div>
    </div>
    <p className={styles.secretNotice}><AlertTriangle size={16} aria-hidden="true" />文件内的 API 密钥和邮箱密码将写入当前服务，请确保文件来源可信。</p>
    <div className={styles.comparisonWrap}>
      <table className={styles.comparison} aria-label="备份与当前数据数量比较">
        <thead><tr><th>数据</th><th>备份</th><th>当前</th><th>变化</th></tr></thead>
        <tbody>{Object.entries(preview.count_comparison).map(([member, item]) => <tr key={member}><th scope="row">{memberLabels[member] ?? member}</th><td>{item.backup}</td><td>当前 {item.current}</td><td>{item.delta > 0 ? `+${item.delta}` : item.delta}</td></tr>)}</tbody>
      </table>
    </div>
    {preview.warnings.map((warning) => <p className={styles.warningLine} key={warning}>{warning}</p>)}
    <label className={styles.confirmField}>输入“恢复”以确认<input autoComplete="off" value={confirmation} onChange={(event) => onConfirmation(event.target.value)} placeholder="恢复" /></label>
  </div>;
}

function SafetyRow({ item, disabled, onPreview, onDelete, onError }: {
  item: SafetyBackup;
  disabled: boolean;
  onPreview: (item: SafetyBackup) => void;
  onDelete: (item: SafetyBackup) => void;
  onError: (item: SafetyBackup, error: unknown) => void;
}) {
  return <tr>
    <td><time dateTime={item.exported_at}>{formatDate(item.exported_at)}</time></td>
    <td>{item.source_application_version} / v{item.format_version}</td>
    <td>{formatBytes(item.size_bytes)}</td>
    <td>{totalRecords(item.record_counts)}</td>
    <td><div className={styles.rowActions}>
      <button type="button" disabled={disabled} onClick={() => void saveBackupDownload(`/api/backups/safety/${item.id}/download`).catch((error) => onError(item, error))}><Download size={14} aria-hidden="true" />下载</button>
      <button type="button" disabled={disabled} onClick={() => onPreview(item)}>恢复</button>
      <button className={styles.dangerText} type="button" disabled={disabled} onClick={() => onDelete(item)}><Trash2 size={14} aria-hidden="true" />删除</button>
    </div></td>
  </tr>;
}

export function BackupRestorePanel() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const downloadedOperation = useRef<string | null>(null);
  const completedRestore = useRef<string | null>(null);
  const invalidatedSafetyOperation = useRef<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [acceptedOperation, setAcceptedOperation] = useState<BackupOperation | null>(null);
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [restoreFailure, setRestoreFailure] = useState<unknown>(null);
  const [confirmation, setConfirmation] = useState("");
  const [safetyOpen, setSafetyOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SafetyBackup | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [failure, setFailure] = useState<FailureState | null>(null);

  const exportMutation = useStartBackupExport();
  const uploadMutation = useBackupUpload();
  const restoreMutation = useStartBackupRestore();
  const safetyPreview = useSafetyPreview();
  const deleteSafety = useDeleteSafetyBackup();
  const operation = useBackupOperation(operationId);
  const safetyBackups = useSafetyBackups(safetyOpen);
  const operationData = operation.data;
  const visibleOperation = operationData ?? acceptedOperation;
  const active = exportMutation.isPending || uploadMutation.isPending || restoreMutation.isPending
    || safetyPreview.isPending || deleteSafety.isPending
    || visibleOperation?.status === "pending" || visibleOperation?.status === "running";
  const displayedError = operation.isError ? { code: "BACKUP_STATUS_UNAVAILABLE" } : failure?.error ?? null;

  const beginExport = () => {
    setFailure(null); setMessage(null); setOperationId(null); setAcceptedOperation(null);
    exportMutation.mutate(undefined, {
      onSuccess: (result) => { setAcceptedOperation(result); setOperationId(result.id); },
      onError: (error) => setFailure({ error, retry: beginExport }),
    });
  };

  const uploadFile = (file: File) => {
    setFailure(null); setMessage(null); setOperationId(null); setAcceptedOperation(null);
    uploadMutation.mutate(file, {
      onSuccess: (result) => { setPreview(result); setConfirmation(""); },
      onError: (error) => setFailure({ error, retry: () => uploadFile(file) }),
    });
  };

  const downloadExport = (result: BackupOperation) => {
    downloadedOperation.current = result.id;
    void saveBackupDownload(`/api/backups/operations/${result.id}/download`)
      .then(() => { setFailure(null); setMessage("完整备份已下载"); })
      .catch((error) => {
        downloadedOperation.current = null;
        setFailure({ error, retry: () => downloadExport(result) });
      });
  };

  useEffect(() => {
    if (!operationData || operationData.kind !== "export" || operationData.status !== "succeeded" || !operationData.download_ready) return;
    if (downloadedOperation.current === operationData.id) return;
    downloadExport(operationData);
  }, [operationData]);

  useEffect(() => {
    if (!operationData || operationData.status === "pending" || operationData.status === "running" || operationData.status === "succeeded") return;
    setFailure({ error: operationData.error ?? { code: operationData.status === "interrupted" ? "BACKUP_OPERATION_INTERRUPTED" : "BACKUP_RESTORE_FAILED" } });
  }, [operationData]);

  useEffect(() => {
    if (!operationData || operationData.kind !== "restore") return;
    const terminal = operationData.status === "succeeded" || operationData.status === "failed" || operationData.status === "interrupted";
    if (!terminal || invalidatedSafetyOperation.current === operationData.id) return;
    invalidatedSafetyOperation.current = operationData.id;
    void queryClient.invalidateQueries({ queryKey: backupKeys.safety });
  }, [operationData, queryClient]);

  useEffect(() => {
    if (!operationData || operationData.kind !== "restore" || operationData.status !== "succeeded") return;
    if (completedRestore.current === operationData.id) return;
    completedRestore.current = operationData.id;
    setMessage(`恢复完成；恢复前安全备份：${operationData.safety_backup_id ?? "已创建"}`);
    const reloadTimer = window.setTimeout(() => {
      queryClient.clear();
      window.location.reload();
    }, 800);
    return () => window.clearTimeout(reloadTimer);
  }, [operationData, queryClient]);

  const beginRestore = () => {
    if (!preview || confirmation !== "恢复") return;
    setFailure(null); setRestoreFailure(null);
    restoreMutation.mutate({ token: preview.restore_token, confirmation }, {
      onSuccess: (result) => { setPreview(null); setAcceptedOperation(result); setOperationId(result.id); setConfirmation(""); },
      onError: (restoreError) => setRestoreFailure(restoreError),
    });
  };

  const openSafetyPreview = (item: SafetyBackup) => {
    setFailure(null); setMessage(null); setOperationId(null); setAcceptedOperation(null);
    safetyPreview.mutate(item.id, {
      onSuccess: (result) => { setRestoreFailure(null); setPreview(result); setConfirmation(""); },
      onError: (error) => setFailure({ error, retry: () => openSafetyPreview(item) }),
    });
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    deleteSafety.mutate(target.id, {
      onSuccess: () => { setFailure(null); setDeleteTarget(null); },
      onError: (error) => { setDeleteTarget(null); setFailure({ error, retry: () => setDeleteTarget(target) }); },
    });
  };

  const handleSafetyDownloadError = (item: SafetyBackup, error: unknown) => {
    setFailure({
      error,
      retry: () => void saveBackupDownload(`/api/backups/safety/${item.id}/download`)
        .then(() => setFailure(null))
        .catch((nextError) => handleSafetyDownloadError(item, nextError)),
    });
  };

  const restoreActive = Boolean(visibleOperation?.kind === "restore" && (visibleOperation.status === "pending" || visibleOperation.status === "running" || visibleOperation.status === "succeeded"));
  const stageIndex = visibleOperation ? stages.findIndex((stage) => stage.id === visibleOperation.stage) : -1;

  return <section className={styles.panel} aria-labelledby="backup-restore-title" aria-busy={active}>
    <div className={styles.summary}>
      <div className={styles.heading}><Archive size={18} aria-hidden="true" /><div><h3 id="backup-restore-title">完整备份与恢复</h3><p>导出或完整替换当前业务数据</p></div></div>
      <div className={styles.actions}>
        <button className={styles.primaryButton} type="button" disabled={active} onClick={beginExport}>{exportMutation.isPending ? <RefreshCw className={styles.spin} size={16} aria-hidden="true" /> : <Download size={16} aria-hidden="true" />}导出完整备份</button>
        <button className={styles.secondaryButton} type="button" disabled={active} onClick={() => fileInput.current?.click()}><FileUp size={16} aria-hidden="true" />选择备份文件</button>
        <input ref={fileInput} className={styles.srOnly} type="file" accept=".portfolio-backup" aria-label="选择备份文件" disabled={active} onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadFile(file); event.currentTarget.value = ""; }} />
      </div>
    </div>
    <p className={styles.permanentWarning}><AlertTriangle size={16} aria-hidden="true" /><span><strong>敏感文件：</strong>备份文件包含明文 API 密钥和邮箱密码。下载后请妥善保管，勿上传到网盘或代码仓库。</span></p>

    {active || operationData || message || displayedError ? <div className={styles.statusArea} aria-live="polite">
      {active ? <p role="status"><RefreshCw className={styles.spin} size={15} aria-hidden="true" />{visibleOperation?.kind === "restore" ? "正在恢复完整数据" : visibleOperation?.kind === "export" ? "正在生成备份文件" : "正在校验备份文件"}</p> : null}
      {restoreActive ? <ol className={styles.stages}>{stages.map((stage, index) => <li key={stage.id} aria-current={index === stageIndex && visibleOperation?.status !== "succeeded" ? "step" : undefined} data-state={index < stageIndex || visibleOperation?.status === "succeeded" ? "done" : index === stageIndex ? "current" : "pending"}><i aria-hidden="true" />{stage.label}</li>)}</ol> : null}
      {message ? <p className={styles.success}><ShieldCheck size={15} aria-hidden="true" />{message}</p> : null}
      {displayedError ? <div className={styles.error} role="alert"><span>{localizedError(displayedError)}</span>{operation.isError ? <button type="button" onClick={() => void operation.refetch()}>重试查询状态</button> : failure?.retry && !active ? <button type="button" onClick={failure.retry}>重试</button> : null}</div> : null}
    </div> : null}

    <button className={styles.safetyToggle} type="button" aria-expanded={safetyOpen} disabled={active} onClick={() => setSafetyOpen((open) => !open)}><ChevronDown size={15} aria-hidden="true" />管理恢复前安全备份</button>
    {safetyOpen ? <div className={styles.safetySection}>
      {safetyBackups.isPending ? <div className={styles.skeletons} role="status" aria-label="正在载入安全备份"><i /><i /></div> : null}
      {safetyBackups.isError ? <div className={styles.error} role="alert"><span>安全备份列表暂时无法载入。</span><button type="button" onClick={() => void safetyBackups.refetch()}>重试</button></div> : null}
      {safetyBackups.data?.length === 0 ? <p className={styles.empty}>还没有恢复前安全备份。每次确认恢复前，系统会自动保留一份当前状态。</p> : null}
      {safetyBackups.data?.length ? <div className={styles.tableWrap}><table className={styles.safetyTable} aria-label="恢复前安全备份"><thead><tr><th>导出时间</th><th>应用 / 格式</th><th>文件大小</th><th>记录数</th><th>操作</th></tr></thead><tbody>{safetyBackups.data.map((item) => <SafetyRow key={item.id} item={item} disabled={active} onPreview={openSafetyPreview} onDelete={setDeleteTarget} onError={handleSafetyDownloadError} />)}</tbody></table></div> : null}
    </div> : null}

    <WorkDrawer open={Boolean(preview)} title="恢复备份预览" closeDisabled={restoreMutation.isPending} onClose={() => { setPreview(null); setRestoreFailure(null); setConfirmation(""); }} footer={<div className={styles.drawerActions}><button className={styles.secondaryButton} type="button" disabled={restoreMutation.isPending} onClick={() => { setPreview(null); setRestoreFailure(null); setConfirmation(""); }}>取消</button><button className={styles.dangerButton} type="button" disabled={confirmation !== "恢复" || restoreMutation.isPending} onClick={beginRestore}>{restoreMutation.isPending ? "正在启动" : "开始恢复"}</button></div>}>
      {preview ? <><PreviewContent preview={preview} confirmation={confirmation} onConfirmation={setConfirmation} />{restoreFailure ? <p className={styles.previewError} role="alert">{localizedError(restoreFailure)}</p> : null}</> : null}
    </WorkDrawer>

    <WorkDrawer open={Boolean(deleteTarget)} title="删除安全备份" closeDisabled={deleteSafety.isPending} onClose={() => setDeleteTarget(null)} footer={<div className={styles.drawerActions}><button className={styles.secondaryButton} type="button" disabled={deleteSafety.isPending} onClick={() => setDeleteTarget(null)}>取消</button><button className={styles.dangerButton} type="button" disabled={deleteSafety.isPending} onClick={confirmDelete}>{deleteSafety.isPending ? "正在删除" : "确认删除"}</button></div>}>
      <div className={styles.deleteCopy}><p>删除后无法从服务器找回此安全备份，但不会影响当前业务数据。</p>{deleteTarget ? <dl><div><dt>导出时间</dt><dd>{formatDate(deleteTarget.exported_at)}</dd></div><div><dt>备份 ID</dt><dd>{deleteTarget.id}</dd></div></dl> : null}<p>此操作单独确认，不会使用恢复令牌。</p></div>
    </WorkDrawer>
  </section>;
}
