import { expect, test } from "@playwright/test";
import { createSession } from "./helpers";

test("replay basic_loop → comparison improved → accept keeper with confirm → coverage accepted", async ({ page }) => {
  test.setTimeout(180_000);
  await createSession(page, `E2E replay ${Date.now()}`, { simulated: true });
  await expect(page.getByText("SIMULATED", { exact: true })).toBeVisible();

  // Run the replay from the Diagnostics tab control.
  await page.getByRole("link", { name: "Diagnostics" }).click();
  await page.getByRole("radio", { name: /basic_loop/ }).check();
  await page.getByRole("button", { name: "Start replay" }).click();
  await expect(page.getByTestId("replay-status")).toHaveText("Replay completed.", { timeout: 120_000 });

  // Back to the shoot loop: the first shot of the replay got a glare fix → retake → comparison.
  await page.getByRole("link", { name: "Shoot" }).click();
  await page.getByRole("radio", { name: /Upper texture/ }).check();
  const coach = page.getByTestId("coach-panel");
  await expect(coach.getByRole("heading", { name: "Coach — photo #2" })).toBeVisible();
  await expect(coach.getByTestId("comparison")).toContainText("Comparison vs #1");
  await expect(coach.getByTestId("comparison")).toContainText("improved");
  await expect(page.getByTestId("before-after")).toBeVisible();
  await expect(page.getByTestId("received")).toContainText("Received ✓ photo #");

  // Hero shot: AI verdict is advisory; the shot stays unresolved until Drew accepts a keeper.
  await page.getByRole("radio", { name: /Hero/ }).check();
  await expect(coach.getByRole("heading", { name: "Coach — photo #7" })).toBeVisible();
  await expect(coach).toContainText("No keeper yet");
  await coach.getByRole("button", { name: "Accept photo #7 as keeper for Hero (3/4 lateral)" }).click();
  // Explicit confirm step.
  await expect(coach.getByText("Accept photo #7 as the keeper for Hero (3/4 lateral)?")).toBeVisible();
  await coach.getByRole("button", { name: "Yes, accept photo #7" }).click();
  await expect(coach).toContainText("Current keeper: photo #7");
  await expect(coach).toContainText("✓ Photo #7 is the accepted keeper.");

  await page.getByRole("link", { name: "Coverage" }).click();
  const row = page.getByTestId("coverage-row-Hero (3/4 lateral)");
  await expect(row).toContainText("Keeper");
  await expect(row).toContainText("#7");
  await expect(page.getByTestId("coverage-row-Upper texture (mesh close-up)")).toContainText("Keeper");
  await expect(page.getByRole("heading", { name: "Not yet — 2 shots still missing" })).toBeVisible();
  await expect(page.getByText("4 of 6 shots have a keeper")).toBeVisible();
  await expect(page.getByText("AI verdicts are advisory; only accepted keepers resolve a shot.")).toBeVisible();
});
