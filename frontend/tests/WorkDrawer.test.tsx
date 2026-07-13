import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { WorkDrawer } from "../src/components/WorkDrawer/WorkDrawer";

function DrawerHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开成本抽屉</button>
      <WorkDrawer
        open={open}
        title="追加买入 SPY"
        onClose={() => setOpen(false)}
        footer={<button type="button">更新 SPY 持仓</button>}
      >
        <label htmlFor="quantity">新增份额</label>
        <input id="quantity" />
      </WorkDrawer>
    </>
  );
}

function NestedDrawerHarness() {
  const [outerOpen, setOuterOpen] = useState(false);
  const [innerOpen, setInnerOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOuterOpen(true)}>打开外层抽屉</button>
      <WorkDrawer
        open={outerOpen}
        title="编辑 SPY"
        onClose={() => setOuterOpen(false)}
        footer={<button type="button">保存外层调整</button>}
      >
        <button type="button" onClick={() => setInnerOpen(true)}>打开费用确认</button>
        <button type="button">外层次要操作</button>
        <WorkDrawer
          open={innerOpen}
          title="确认费用"
          onClose={() => setInnerOpen(false)}
          footer={<button type="button">确认费用设置</button>}
        >
          <label htmlFor="fee">实际费用</label>
          <input id="fee" />
        </WorkDrawer>
      </WorkDrawer>
    </>
  );
}

function ParallelDrawers({ outerOpen, innerOpen }: { outerOpen: boolean; innerOpen: boolean }) {
  return (
    <>
      <WorkDrawer open={outerOpen} title="外层抽屉" onClose={() => undefined}>外层</WorkDrawer>
      <WorkDrawer open={innerOpen} title="内层抽屉" onClose={() => undefined}>内层</WorkDrawer>
    </>
  );
}

describe("WorkDrawer", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("locks body scroll and restores the exact prior overflow when closed", () => {
    document.body.style.overflow = "clip";
    const { rerender } = render(
      <WorkDrawer open title="追加买入 SPY" onClose={() => undefined}>内容</WorkDrawer>,
    );

    expect(document.body.style.overflow).toBe("hidden");
    rerender(
      <WorkDrawer open={false} title="追加买入 SPY" onClose={() => undefined}>内容</WorkDrawer>,
    );
    expect(document.body.style.overflow).toBe("clip");
    document.body.style.overflow = "";
  });

  it("restores the exact prior overflow when unmounted while open", () => {
    document.body.style.overflow = "scroll";
    const { unmount } = render(
      <WorkDrawer open title="追加买入 SPY" onClose={() => undefined}>内容</WorkDrawer>,
    );

    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("scroll");
    document.body.style.overflow = "";
  });

  it("loops focus in both directions within the drawer", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    await user.click(screen.getByRole("button", { name: "打开成本抽屉" }));
    const closeButton = screen.getByRole("button", { name: "关闭工作抽屉" });
    const input = screen.getByRole("textbox", { name: "新增份额" });
    const confirmButton = screen.getByRole("button", { name: "更新 SPY 持仓" });
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirmButton).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab();
    expect(input).toHaveFocus();
  });

  it("closes with Escape and restores focus to the opener", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    const opener = screen.getByRole("button", { name: "打开成本抽屉" });
    await user.click(opener);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "追加买入 SPY" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("uses unique stable labelling ids for stacked dialogs", async () => {
    const user = userEvent.setup();
    render(<NestedDrawerHarness />);

    await user.click(screen.getByRole("button", { name: "打开外层抽屉" }));
    await user.click(screen.getByRole("button", { name: "打开费用确认" }));

    const dialogs = screen.getAllByRole("dialog", { hidden: true });
    expect(dialogs).toHaveLength(2);
    const labelledByIds = dialogs.map((dialog) => dialog.getAttribute("aria-labelledby"));
    expect(new Set(labelledByIds).size).toBe(2);
    for (const [index, dialog] of dialogs.entries()) {
      const heading = within(dialog).getByRole("heading", { hidden: true });
      expect(labelledByIds[index]).toBe(heading.id);
      expect(document.getElementById(heading.id)).toBe(heading);
    }
  });

  it("gives only the inner drawer focus ownership and closes one layer per Escape", async () => {
    const user = userEvent.setup();
    const { container } = render(<NestedDrawerHarness />);

    const outerOpener = screen.getByRole("button", { name: "打开外层抽屉" });
    await user.click(outerOpener);
    const innerOpener = screen.getByRole("button", { name: "打开费用确认" });
    await user.click(innerOpener);

    const innerDialog = screen.getByRole("dialog", { name: "确认费用" });
    const outerDialog = screen.getByRole("dialog", { name: "编辑 SPY", hidden: true });
    const innerClose = within(innerDialog).getByRole("button", { name: "关闭工作抽屉" });
    const innerConfirm = within(innerDialog).getByRole("button", { name: "确认费用设置" });
    expect(innerClose).toHaveFocus();
    expect(container).toHaveAttribute("inert");
    expect(container).toHaveAttribute("aria-hidden", "true");
    expect(outerDialog.parentElement).toHaveAttribute("inert");
    expect(outerDialog.parentElement).toHaveAttribute("aria-hidden", "true");
    expect(outerDialog).not.toHaveAttribute("aria-modal");
    expect(innerDialog).toHaveAttribute("aria-modal", "true");

    await user.tab({ shift: true });
    expect(innerConfirm).toHaveFocus();
    await user.tab();
    expect(innerClose).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "确认费用" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "编辑 SPY" })).toBeInTheDocument();
    expect(innerOpener).toHaveFocus();
    expect(outerDialog.parentElement).not.toHaveAttribute("inert");
    expect(outerDialog).toHaveAttribute("aria-modal", "true");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "编辑 SPY" })).not.toBeInTheDocument();
    expect(outerOpener).toHaveFocus();
    expect(container).not.toHaveAttribute("inert");
    expect(container).not.toHaveAttribute("aria-hidden");
  });

  it("keeps scroll locked until the last drawer closes regardless of close order", () => {
    document.body.style.overflow = "clip";
    const { rerender, unmount } = render(
      <ParallelDrawers outerOpen innerOpen />,
    );

    expect(document.body.style.overflow).toBe("hidden");
    rerender(<ParallelDrawers outerOpen={false} innerOpen />);
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("clip");
  });
});
