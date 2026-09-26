import { expect, type Page } from "@playwright/test";

export async function createSession(page: Page, name: string, opts: { simulated?: boolean } = {}) {
  await page.goto("/#sessions");
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Create session" }) });
  await form.getByLabel(/^Name/).fill(name);
  await form.getByLabel("AI provider").selectOption("mock");
  if (opts.simulated) await form.getByLabel(/Simulated session/).check();
  await form.getByRole("button", { name: "Create session" }).click();
  // Creating opens the session on the Shoot tab.
  await expect(page.getByRole("link", { name: "Shoot" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByLabel("Current session")).toHaveValue(/.+/);
  await expect(page.getByTestId("mock-banner")).toContainText("MOCK PROVIDER");
  await expect(page.getByTestId("connection-status")).toContainText("Live updates connected");
}
