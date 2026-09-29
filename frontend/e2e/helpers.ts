import { expect, type Page } from "@playwright/test";

export async function createSession(page: Page, name: string, opts: { simulated?: boolean } = {}) {
  await page.goto("/#newshoot");
  // The shoot is named after the product plus the date ("Pegasus 42 · 28 Sep").
  await page.getByPlaceholder("e.g. Pegasus 42").fill(name);
  // The replay scenarios use the running-shoe shot list (apparel is the UI default).
  await page.getByRole("button", { name: /^Shoe review/ }).click();
  await page.getByRole("button", { name: "Change…" }).click();
  await page.getByLabel("Coach", { exact: true }).selectOption("mock");
  if (opts.simulated) await page.getByLabel(/Simulated practice run/).check();
  await page.getByRole("button", { name: /^Start (outdoor )?shoot/ }).click();
  // Starting opens the shoot on the Shoot tab.
  await expect(page.getByRole("link", { name: "Shoot" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("session-name")).toHaveText(new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} · `));
  await expect(page.getByTestId("mock-banner")).toContainText("MOCK PROVIDER");
  await expect(page.getByTestId("connection-status")).toContainText("Mock · online");
}
