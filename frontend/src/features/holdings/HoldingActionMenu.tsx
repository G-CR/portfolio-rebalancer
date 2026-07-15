import { Archive, History, MoreHorizontal, Pencil, TrendingDown } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { Holding } from "../../api/types";
import styles from "./HoldingsTable.module.css";

export type HoldingCommand = "purchase" | "sell" | "correction" | "history" | "archive";

type MenuPosition = {
  top: number;
  left: number;
  placement: "top" | "bottom";
};

export function calculateMenuPosition(
  trigger: DOMRect,
  menu: { width: number; height: number },
  viewport: { width: number; height: number },
): MenuPosition {
  const margin = 8;
  const gap = 4;
  const below = viewport.height - trigger.bottom - margin;
  const above = trigger.top - margin;
  const placement = below >= menu.height || below >= above ? "bottom" : "top";
  const rawTop = placement === "bottom"
    ? Math.min(trigger.bottom + gap, viewport.height - menu.height - margin)
    : Math.max(margin, trigger.top - menu.height - gap);
  const top = Math.max(margin, rawTop);
  const maxLeft = Math.max(margin, viewport.width - menu.width - margin);
  const left = Math.min(
    Math.max(margin, trigger.right - menu.width),
    maxLeft,
  );
  return { top, left, placement };
}

export function HoldingActionMenu({
  holding,
  onCommand,
}: {
  holding: Holding;
  onCommand: (holding: Holding, command: HoldingCommand) => void;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ top: 0, left: 0, placement: "bottom" });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const updatePosition = useCallback(() => {
    if (!triggerRef.current || !menuRef.current) return;
    const trigger = triggerRef.current.getBoundingClientRect();
    const menu = menuRef.current.getBoundingClientRect();
    setPosition(calculateMenuPosition(
      trigger,
      { width: menu.width, height: menu.height },
      { width: window.innerWidth, height: window.innerHeight },
    ));
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const closeWithKeyboard = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeWithKeyboard);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeWithKeyboard);
    };
  }, [open, updatePosition]);

  function run(command: HoldingCommand) {
    setOpen(false);
    onCommand(holding, command);
    triggerRef.current?.focus();
  }

  const menu = open ? (
    <div
      ref={menuRef}
      id={menuId}
      className={styles.portalMenu}
      role="menu"
      data-placement={position.placement}
      style={{ top: position.top, left: position.left }}
    >
      <button type="button" role="menuitem" onClick={() => run("sell")}><TrendingDown size={15} aria-hidden="true" />卖出调整</button>
      <button type="button" role="menuitem" onClick={() => run("correction")}><Pencil size={15} aria-hidden="true" />人工修正</button>
      <button type="button" role="menuitem" onClick={() => run("history")}><History size={15} aria-hidden="true" />调整历史</button>
      {holding.is_active ? <button className={styles.dangerItem} type="button" role="menuitem" onClick={() => run("archive")}><Archive size={15} aria-hidden="true" />归档持仓</button> : null}
    </div>
  ) : null;

  return (
    <>
      <button
        ref={triggerRef}
        className={styles.iconButton}
        type="button"
        title="更多操作"
        aria-label={`更多 ${holding.symbol} 操作`}
        aria-controls={open ? menuId : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <MoreHorizontal size={17} aria-hidden="true" />
      </button>
      {menu ? createPortal(menu, document.body) : null}
    </>
  );
}
