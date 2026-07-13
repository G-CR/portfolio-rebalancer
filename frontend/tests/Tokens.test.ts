import tokens from "../src/styles/tokens.css?raw";

function tokenValue(name: string) {
  const match = tokens.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!match) throw new Error(`Missing color token: ${name}`);
  return match[1];
}

function luminance(hex: string) {
  const channels = hex.match(/[0-9a-fA-F]{2}/g)!.map((channel) => {
    const value = Number.parseInt(channel, 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground: string, background: string) {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

it("keeps target text contrast at WCAG AA for normal text", () => {
  expect(contrastRatio(tokenValue("color-target"), tokenValue("color-surface"))).toBeGreaterThanOrEqual(4.5);
});
