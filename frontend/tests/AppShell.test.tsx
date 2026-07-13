import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "../src/components/AppShell/AppShell";
import { FormField } from "../src/components/FormField/FormField";
import { WorkDrawer } from "../src/components/WorkDrawer/WorkDrawer";

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
  it("renders the seven confirmed routes as labelled links", () => {
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

  it("opens and closes the compact navigation menu", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/holdings"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    expect(toggle).toHaveAccessibleName("关闭导航");
    await user.click(screen.getByRole("link", { name: "再平衡" }));
    expect(toggle).toHaveAccessibleName("打开导航");
  });

  it("closes the compact navigation menu with Escape", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const toggle = screen.getByRole("button", { name: "打开导航" });
    await user.click(toggle);
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAccessibleName("打开导航");
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

  it("exposes the work drawer as a labelled modal and closes it", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <WorkDrawer open title="追加买入 SPY" onClose={onClose}>
        <p>本次成交</p>
      </WorkDrawer>,
    );

    expect(screen.getByRole("dialog", { name: "追加买入 SPY" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭工作抽屉" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
