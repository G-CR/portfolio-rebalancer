import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useState } from "react";

import { WorkDrawer } from "../src/components/WorkDrawer/WorkDrawer";
import { registerDrawer } from "../src/components/WorkDrawer/drawerStack";

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

function IndependentDrawer({ title, onClose }: { title: string; onClose: () => void }) {
  const [open, setOpen] = useState(true);

  return (
    <WorkDrawer
      open={open}
      title={title}
      onClose={() => {
        onClose();
        setOpen(false);
      }}
    >
      <button type="button">{title}操作</button>
    </WorkDrawer>
  );
}

function StrictDrawer({ show, onClose }: { show: boolean; onClose: () => void }) {
  return show ? (
    <WorkDrawer open title="严格模式抽屉" onClose={onClose}>严格模式内容</WorkDrawer>
  ) : null;
}

function createRootContainer(name: string) {
  const container = document.createElement("div");
  container.dataset.drawerTestRoot = name;
  document.body.append(container);
  return container;
}

describe("WorkDrawer", () => {
  afterEach(() => {
    cleanup();
    document.querySelectorAll("[data-drawer-test-root]").forEach((element) => element.remove());
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

  it("keeps identities and top-only Escape behavior correct across separate React roots", async () => {
    const user = userEvent.setup();
    const firstContainer = createRootContainer("first");
    const closeFirst = vi.fn();
    const closeSecond = vi.fn();
    document.body.style.overflow = "clip";

    render(<IndependentDrawer title="第一根抽屉" onClose={closeFirst} />, {
      container: firstContainer,
    });
    const secondContainer = createRootContainer("second");
    render(<IndependentDrawer title="第二根抽屉" onClose={closeSecond} />, {
      container: secondContainer,
    });

    const dialogs = screen.getAllByRole("dialog", { hidden: true });
    const titleIds = dialogs.map((dialog) => dialog.getAttribute("aria-labelledby"));
    expect(new Set(titleIds).size).toBe(2);
    expect(screen.getByRole("dialog", { name: "第二根抽屉" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "第一根抽屉", hidden: true })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(closeSecond).toHaveBeenCalledOnce();
    expect(closeFirst).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "第二根抽屉" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "第一根抽屉" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    expect(firstContainer).toHaveAttribute("inert");
    expect(secondContainer).toHaveAttribute("inert");

    await user.keyboard("{Escape}");

    expect(closeFirst).toHaveBeenCalledOnce();
    expect(document.body.style.overflow).toBe("clip");
    expect(firstContainer).not.toHaveAttribute("inert");
    expect(secondContainer).not.toHaveAttribute("inert");
  });

  it("unregisters the exact cross-root entry when the top root unmounts", () => {
    const firstContainer = createRootContainer("first");
    const secondContainer = createRootContainer("second");
    document.body.style.overflow = "scroll";
    const firstRoot = render(
      <WorkDrawer open title="第一根抽屉" onClose={() => undefined}>第一根</WorkDrawer>,
      { container: firstContainer },
    );
    const secondRoot = render(
      <WorkDrawer open title="第二根抽屉" onClose={() => undefined}>第二根</WorkDrawer>,
      { container: secondContainer },
    );

    secondRoot.unmount();

    expect(screen.getByRole("dialog", { name: "第一根抽屉" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    expect(firstContainer).toHaveAttribute("inert");

    firstRoot.unmount();

    expect(document.body.style.overflow).toBe("scroll");
    expect(firstContainer).not.toHaveAttribute("inert");
    expect(secondContainer).not.toHaveAttribute("inert");
  });

  it("cleans and reacquires stack ownership across StrictMode unmount and remount", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    document.body.style.overflow = "clip";
    const { container, rerender, unmount } = render(
      <StrictMode>
        <StrictDrawer show onClose={onClose} />
      </StrictMode>,
    );
    const firstTitleId = screen
      .getByRole("dialog", { name: "严格模式抽屉" })
      .getAttribute("aria-labelledby");
    expect(document.body.style.overflow).toBe("hidden");
    expect(container).toHaveAttribute("inert");

    rerender(
      <StrictMode>
        <StrictDrawer show={false} onClose={onClose} />
      </StrictMode>,
    );

    expect(screen.queryByRole("dialog", { name: "严格模式抽屉" })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("clip");
    expect(container).not.toHaveAttribute("inert");
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    rerender(
      <StrictMode>
        <StrictDrawer show onClose={onClose} />
      </StrictMode>,
    );

    const secondTitleId = screen
      .getByRole("dialog", { name: "严格模式抽屉" })
      .getAttribute("aria-labelledby");
    expect(secondTitleId).not.toBe(firstTitleId);
    expect(document.body.style.overflow).toBe("hidden");
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();

    unmount();
    expect(document.body.style.overflow).toBe("clip");
    expect(container).not.toHaveAttribute("inert");
  });

  it("unregisters the exact opaque stack entry even when textual labels collide", () => {
    const firstIdentity = {};
    const secondIdentity = {};
    const closeFirst = vi.fn();
    const closeSecond = vi.fn();
    const firstLayer = document.createElement("div");
    const secondLayer = document.createElement("div");
    const firstPanel = document.createElement("section");
    const secondPanel = document.createElement("section");
    firstLayer.dataset.workDrawerLayer = "same-text-id";
    secondLayer.dataset.workDrawerLayer = "same-text-id";
    firstPanel.append(document.createElement("button"));
    secondPanel.append(document.createElement("button"));
    firstLayer.append(firstPanel);
    secondLayer.append(secondPanel);
    document.body.append(firstLayer, secondLayer);

    const unregisterFirst = registerDrawer({
      identity: firstIdentity,
      layer: firstLayer,
      panel: firstPanel,
      close: closeFirst,
    });
    const unregisterSecond = registerDrawer({
      identity: secondIdentity,
      layer: secondLayer,
      panel: secondPanel,
      close: closeSecond,
    });

    try {
      unregisterSecond();
      expect(firstLayer).not.toHaveAttribute("inert");
      expect(firstPanel).toHaveAttribute("aria-modal", "true");

      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      expect(closeFirst).toHaveBeenCalledOnce();
      expect(closeSecond).not.toHaveBeenCalled();
    } finally {
      unregisterSecond();
      unregisterFirst();
      firstLayer.remove();
      secondLayer.remove();
    }
  });
});
