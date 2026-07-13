import { render, screen } from "@testing-library/react";

import { CalibrationRail } from "../src/components/CalibrationRail/CalibrationRail";

describe("CalibrationRail", () => {
  it("renders textual values for every marker", () => {
    render(
      <CalibrationRail
        assetName="标普 500"
        target={30}
        actual={31.8}
        fxNeutral={30.7}
        planned={30.2}
        tolerance={2}
      />,
    );

    expect(screen.getByText("目标 30.0%")).toBeInTheDocument();
    expect(screen.getByText("实际 31.8%")).toBeInTheDocument();
    expect(screen.getByText("剔汇率 30.7%")).toBeInTheDocument();
    expect(screen.getByText("计划 30.2%")).toBeInTheDocument();
    expect(screen.getByText("+1.8pp")).toBeInTheDocument();
  });

  it("shows an overflow indicator without compressing the scale", () => {
    render(
      <CalibrationRail assetName="标普 500" target={30} actual={36} tolerance={2} />,
    );

    expect(
      screen.getByLabelText("实际占比超出右侧刻度，真实值 36.0%"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("actual-marker")).toHaveStyle({ left: "100%" });
  });

  it("clamps optional markers independently at either edge", () => {
    render(
      <CalibrationRail
        assetName="标普 500"
        target={30}
        actual={30}
        fxNeutral={24}
        planned={35}
        tolerance={1}
      />,
    );

    expect(
      screen.getByLabelText("剔汇率占比超出左侧刻度，真实值 24.0%"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("计划占比超出右侧刻度，真实值 35.0%"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("fx-neutral-marker")).toHaveStyle({ left: "0%" });
    expect(screen.getByTestId("planned-marker")).toHaveStyle({ left: "100%" });
  });
});
