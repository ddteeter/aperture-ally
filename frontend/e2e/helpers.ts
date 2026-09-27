import { expect, type Page } from "@playwright/test";

export async function createSession(page: Page, name: string, opts: { simulated?: boolean } = {}) {
  await page.goto("/#sessions");
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Create and start shooting" }) });
  await form.getByLabel(/^Name/).fill(name);
  await form.getByRole("radio", { name: /^Mock/ }).check();
  // The replay scenarios use the running-shoe shot list (apparel is the UI default).
  await form.getByRole("radio", { name: /^Shoe product/ }).check();
  if (opts.simulated) await form.getByLabel(/Simulated practice run/).check();
  await form.getByRole("button", { name: "Create and start shooting" }).click();
  // Creating opens the session on the Shoot tab.
  await expect(page.getByRole("link", { name: "Shoot" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("session-name")).toHaveText(name);
  await expect(page.getByTestId("mock-banner")).toContainText("MOCK PROVIDER");
  await expect(page.getByTestId("connection-status")).toContainText("Mock · online");
}
