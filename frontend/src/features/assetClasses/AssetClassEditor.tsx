import { ArrowDown, ArrowUp, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../../api/client";
import type { AssetClass, AssetClassUpdate } from "../../api/types";
import { percentDifference, percentToRatio, ratioToPercent } from "./decimalPercent";
import styles from "./AssetClassEditor.module.css";

type EditableAssetClass = AssetClass & { targetPercent: string };

type Props = {
  initialItems: readonly AssetClass[];
  onSave: (items: AssetClassUpdate[]) => Promise<unknown>;
  saving?: boolean;
};

function editable(items: readonly AssetClass[]): EditableAssetClass[] {
  return [...items]
    .sort((a, b) => a.display_order - b.display_order)
    .map((item) => ({ ...item, targetPercent: ratioToPercent(item.target_weight) }));
}

export function AssetClassEditor({ initialItems, onSave, saving = false }: Props) {
  const [items, setItems] = useState(() => editable(initialItems));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => setItems(editable(initialItems)), [initialItems]);
  const difference = useMemo(
    () => percentDifference(items.map((item) => item.targetPercent)),
    [items],
  );
  const valid = Boolean(difference?.valid) && items.every((item) => item.name.trim());

  function update(id: string, patch: Partial<EditableAssetClass>) {
    setSaved(false);
    setError(null);
    setItems((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item));
  }

  function move(index: number, direction: -1 | 1) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= items.length) return;
    setSaved(false);
    setItems((current) => {
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  }

  async function save() {
    if (!valid) return;
    setError(null);
    setSaved(false);
    try {
      await onSave(items.map((item, index) => ({
        id: item.id,
        name: item.name.trim(),
        target_weight: percentToRatio(item.targetPercent),
        display_order: index + 1,
        notes: item.notes?.trim() || null,
      })));
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "资产配置保存失败，请重试。");
    }
  }

  return (
    <section className={styles.editor} aria-labelledby="asset-editor-title">
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>ACTIVE STRATEGY</p>
          <h2 id="asset-editor-title">当前启用资产配置</h2>
          <p>目标比例按启用类别合计，保存时必须精确等于 100%。</p>
        </div>
        <span className={styles.count}>{items.length} 类资产</span>
      </header>

      {error ? <div className={styles.alert} role="alert">{error}</div> : null}
      {saved ? <div className={styles.success} role="status">资产配置已保存</div> : null}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">顺序</th>
              <th scope="col">资产类别</th>
              <th scope="col">目标比例</th>
              <th scope="col">状态</th>
              <th scope="col">备注</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={item.id}>
                <td>
                  <div className={styles.orderControls}>
                    <span>{index + 1}</span>
                    <button type="button" title="上移" aria-label={`上移${item.name}`} disabled={index === 0} onClick={() => move(index, -1)}>
                      <ArrowUp size={15} aria-hidden="true" />
                    </button>
                    <button type="button" title="下移" aria-label={`下移${item.name}`} disabled={index === items.length - 1} onClick={() => move(index, 1)}>
                      <ArrowDown size={15} aria-hidden="true" />
                    </button>
                  </div>
                </td>
                <td>
                  <label className={styles.srOnly} htmlFor={`asset-name-${item.id}`}>{item.name}名称</label>
                  <input id={`asset-name-${item.id}`} value={item.name} onChange={(event) => update(item.id, { name: event.target.value })} />
                </td>
                <td>
                  <label className={styles.srOnly} htmlFor={`asset-target-${item.id}`}>{item.name}目标比例</label>
                  <div className={styles.percentInput}>
                    <input
                      id={`asset-target-${item.id}`}
                      type="text"
                      inputMode="decimal"
                      value={item.targetPercent}
                      onChange={(event) => update(item.id, { targetPercent: event.target.value })}
                    />
                    <span aria-hidden="true">%</span>
                  </div>
                </td>
                <td>
                  <label className={styles.activeState} title="当前 API 维护启用配置集合">
                    <input type="checkbox" checked readOnly aria-label={`${item.name}启用状态`} />
                    <span>启用中</span>
                  </label>
                </td>
                <td>
                  <label className={styles.srOnly} htmlFor={`asset-note-${item.id}`}>{item.name}备注</label>
                  <input id={`asset-note-${item.id}`} value={item.notes ?? ""} placeholder="可选" onChange={(event) => update(item.id, { notes: event.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className={styles.footer}>
        <div>
          <strong>目标比例合计 {difference?.total ?? "输入有误"}%</strong>
          {!difference ? <p className={styles.invalid}>请输入有效的非负比例</p> : null}
          {difference && !difference.valid ? (
            <p className={difference.deficit ? styles.warning : styles.invalid}>
              {difference.deficit
                ? `还差 ${difference.display}% 才达到 100%`
                : `超出 ${difference.display}%，请调减至 100%`}
            </p>
          ) : null}
          {difference?.valid ? <p className={styles.valid}>比例校验通过，可以保存。</p> : null}
        </div>
        <button className={styles.saveButton} type="button" disabled={!valid || saving} onClick={() => void save()}>
          <Save size={16} aria-hidden="true" />
          {saving ? "正在保存" : "保存资产配置"}
        </button>
      </footer>
    </section>
  );
}
