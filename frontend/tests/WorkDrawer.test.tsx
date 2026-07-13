import { render, screen } from "@testing-library/react";
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

describe("WorkDrawer", () => {
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
});
