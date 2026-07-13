import { X } from "lucide-react";
import { useEffect, useRef, type PropsWithChildren } from "react";

type WorkDrawerProps = PropsWithChildren<{
  open: boolean;
  title: string;
  onClose: () => void;
  footer?: React.ReactNode;
}>;

const focusableSelector = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function WorkDrawer({ open, title, onClose, footer, children }: WorkDrawerProps) {
  const drawerRef = useRef<HTMLElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const drawer = drawerRef.current;
    const firstFocusable = drawer?.querySelector<HTMLElement>(focusableSelector);
    firstFocusable?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !drawer) return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(focusableSelector));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      previousFocus.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="work-drawer-layer">
      <div className="work-drawer-backdrop" aria-hidden="true" onClick={onClose} />
      <section
        ref={drawerRef}
        className="work-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="work-drawer-title"
      >
        <header className="work-drawer__header">
          <h2 id="work-drawer-title">{title}</h2>
          <button className="work-drawer__close" type="button" aria-label="关闭工作抽屉" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="work-drawer__body">{children}</div>
        {footer ? <footer className="work-drawer__footer">{footer}</footer> : null}
      </section>
    </div>
  );
}
