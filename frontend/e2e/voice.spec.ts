import { expect, test } from "@playwright/test";
import { createSession } from "./helpers";

test("push-to-talk: hold the button with a queued mock transcript → listening → answer", async ({ page }) => {
  await createSession(page, `E2E voice ${Date.now()}`);

  // Queue the transcript the mock transcriber will "hear".
  await page.getByRole("link", { name: "Diagnostics" }).click();
  await page.getByLabel("Mock transcript for the next voice question").fill("Why does the glare matter here?");
  await page.getByRole("button", { name: "Queue transcript" }).click();
  await expect(page.getByText(/Queued \(1 waiting\)/)).toBeVisible();

  await page.getByRole("link", { name: "Shoot" }).click();
  const ptt = page.getByTestId("ptt");
  await expect(ptt).toBeEnabled();
  await expect(page.getByTestId("voice-state")).toContainText("Idle");

  await ptt.hover();
  await page.mouse.down();
  await expect(page.getByTestId("voice-state")).toContainText("Listening…");
  await expect(ptt).toHaveText("Release to send");
  await page.waitForTimeout(700);
  await expect(page.getByTestId("voice-state")).toContainText(/held \d\.\ds/);
  await page.mouse.up();

  await expect(page.getByTestId("voice-transcript")).toContainText("Why does the glare matter here?");
  await expect(page.getByTestId("voice-answer")).toContainText("mock answer to: Why does the glare matter here?");
  await expect(page.getByTestId("voice-state")).not.toContainText("Listening…");
});
