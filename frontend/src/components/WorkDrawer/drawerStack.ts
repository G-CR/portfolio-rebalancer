type DrawerEntry = {
  id: string;
  layer: HTMLElement;
  panel: HTMLElement;
  close: () => void;
};

type ElementState = {
  inert: boolean;
  ariaHidden: string | null;
};

const focusableSelector = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const drawerStack: DrawerEntry[] = [];
const backgroundState = new Map<HTMLElement, ElementState>();
let originalBodyOverflow: string | null = null;

function setInaccessible(element: HTMLElement, inaccessible: boolean) {
  if (inaccessible) {
    element.setAttribute("inert", "");
    element.setAttribute("aria-hidden", "true");
  } else {
    element.removeAttribute("inert");
    element.removeAttribute("aria-hidden");
  }
}

function syncDrawerLayers() {
  const topIndex = drawerStack.length - 1;
  drawerStack.forEach((entry, index) => {
    const isTop = index === topIndex;
    setInaccessible(entry.layer, !isTop);
    if (isTop) entry.panel.setAttribute("aria-modal", "true");
    else entry.panel.removeAttribute("aria-modal");
  });
}

function lockBackground() {
  originalBodyOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  for (const child of Array.from(document.body.children)) {
    if (!(child instanceof HTMLElement) || child.matches("[data-work-drawer-layer]")) {
      continue;
    }
    backgroundState.set(child, {
      inert: child.hasAttribute("inert"),
      ariaHidden: child.getAttribute("aria-hidden"),
    });
    setInaccessible(child, true);
  }
}

function restoreBackground() {
  for (const [element, state] of backgroundState) {
    if (state.inert) element.setAttribute("inert", "");
    else element.removeAttribute("inert");

    if (state.ariaHidden === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", state.ariaHidden);
  }
  backgroundState.clear();

  if (originalBodyOverflow !== null) {
    document.body.style.overflow = originalBodyOverflow;
    originalBodyOverflow = null;
  }
}

function trapFocus(panel: HTMLElement, event: KeyboardEvent) {
  const focusable = Array.from(panel.querySelectorAll<HTMLElement>(focusableSelector));
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!first || !last) return;

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  } else if (!panel.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  }
}

function handleStackKeyDown(event: KeyboardEvent) {
  const topDrawer = drawerStack.at(-1);
  if (!topDrawer) return;

  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    topDrawer.close();
  } else if (event.key === "Tab") {
    trapFocus(topDrawer.panel, event);
  }
}

export function registerDrawer(entry: DrawerEntry) {
  if (drawerStack.length === 0) {
    lockBackground();
    document.addEventListener("keydown", handleStackKeyDown);
  }

  drawerStack.push(entry);
  syncDrawerLayers();
  entry.panel.querySelector<HTMLElement>(focusableSelector)?.focus();

  return () => {
    const index = drawerStack.findIndex((drawer) => drawer.id === entry.id);
    if (index === -1) return;

    drawerStack.splice(index, 1);
    syncDrawerLayers();

    if (drawerStack.length === 0) {
      document.removeEventListener("keydown", handleStackKeyDown);
      restoreBackground();
    }
  };
}

export function isTopDrawer(id: string) {
  return drawerStack.at(-1)?.id === id;
}

export function canRestoreFocus(element: HTMLElement | null) {
  return Boolean(
    element?.isConnected
      && !element.closest("[inert]")
      && !element.closest('[aria-hidden="true"]'),
  );
}
