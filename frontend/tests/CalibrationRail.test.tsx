import { render, screen } from "@testing-library/react";

import { CalibrationRail } from "../src/components/CalibrationRail/CalibrationRail";

describe("CalibrationRail", () => {
  it("renders textual values for every marker", () => {
    render(
      <CalibrationRail
        assetName="标普 500"
        target={30}
        actual={31.8}
        planned={30.2}
        tolerance={2}
      />,
    );

    expect(screen.getByText("目标 30.0%")).toBeInTheDocument();
    expect(screen.getByText("实际 31.8%")).toBeInTheDocument();
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
        planned={35}
        tolerance={1}
      />,
    );

    expect(
      screen.getByLabelText("计划占比超出右侧刻度，真实值 35.0%"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("planned-marker")).toHaveStyle({ left: "100%" });
  });

  it("expands the scale to show the full tolerance", () => {
    render(
      <CalibrationRail assetName="标普 500" target={30} actual={30} tolerance={6} />,
    );

    const description = "允许偏离目标正负 6.0 个百分点";
    expect(screen.getByTestId("tolerance-band")).toHaveAccessibleName(description);
    expect(screen.getByTestId("tolerance-band")).toHaveStyle({ left: "0%", width: "100%" });
    expect(screen.getByText("-6.0pp")).toBeInTheDocument();
    expect(screen.getByText("+6.0pp")).toBeInTheDocument();
    expect(screen.queryByText(description)).not.toBeInTheDocument();
  });

  it("normalizes a negative tolerance to zero and discloses the normalization", () => {
    render(
      <CalibrationRail assetName="标普 500" target={30} actual={30} tolerance={-2} />,
    );

    const description = "允许偏离目标正负 0.0 个百分点；输入值 -2.0 个百分点已按 0.0 个百分点显示";
    expect(screen.getByText(description)).toBeInTheDocument();
    expect(screen.getByTestId("tolerance-band")).toHaveAccessibleName(description);
    expect(screen.getByTestId("tolerance-band")).toHaveStyle({ left: "50%", width: "0%" });
  });
});
