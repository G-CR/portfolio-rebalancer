import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "../src/components/AppShell/AppShell";
import { FormField } from "../src/components/FormField/FormField";

const mobileQuery = "(max-width: 760px)";

function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const mediaQuery = {
    get matches() {
      return matches;
    },
    media: mobileQuery,
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener);
    },
    addListener: (listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeListener: (listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    dispatchEvent: () => true,
  } as MediaQueryList;

  vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));

  return {
    setMatches(nextMatches: boolean) {
      matches = nextMatches;
      const event = { matches, media: mobileQuery } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

const routeNames = [
  "总览",
  "资产配置",
  "持仓与成本",
  "盈亏分析",
  "再平衡",
  "历史快照",
  "数据源",
];

describe("AppShell", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the seven confirmed routes as labelled links", () => {
    installMatchMedia(false);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell />
      </MemoryRouter>,
    );

    for (const name of routeNames) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: "总览" })).toBeInTheDocument();
  });

  it("focuses the first route and isolates the background when mobile navigation opens", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/holdings"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);

    expect(screen.getByRole("link", { name: "总览" })).toHaveFocus();
    expect(screen.getByRole("dialog", { name: "主导航" })).toBeInTheDocument();
    expect(screen.getByRole("banner", { hidden: true })).toHaveAttribute("inert");
    expect(screen.getByRole("banner", { hidden: true })).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");
  });

  it("traps Tab and Shift+Tab within mobile navigation and close controls", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);

    const closeButton = screen.getByRole("button", { name: "关闭导航" });
    const firstRoute = screen.getByRole("link", { name: "总览" });
    const lastRoute = screen.getByRole("link", { name: "数据源" });
    expect(firstRoute).toHaveFocus();
    await user.tab({ shift: true });
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(lastRoute).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab();
    expect(firstRoute).toHaveFocus();
  });

  it("closes mobile navigation with Escape and restores trigger focus", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
  });

  it("closes mobile navigation after a route click and restores trigger focus", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    await user.click(screen.getByRole("link", { name: "再平衡" }));

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it("clears modal state without focusing the hidden trigger at the desktop breakpoint", async () => {
    const media = installMatchMedia(true);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    const firstRoute = screen.getByRole("link", { name: "总览" });
    expect(firstRoute).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "关闭导航" })).toHaveFocus();

    act(() => media.setMatches(false));

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    expect(firstRoute).toHaveFocus();
  });
});

describe("shared form surfaces", () => {
  it("connects field help and errors to the control", () => {
    render(
      <FormField label="允许偏离" hint="目标上下浮动范围" error="请输入有效比例" required>
        <input id="tolerance" />
      </FormField>,
    );

    const input = screen.getByRole("textbox", { name: "允许偏离" });
    expect(input).toHaveAccessibleDescription("目标上下浮动范围 请输入有效比例");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-required", "true");
  });
});
