import { expect, test } from "@playwright/test";

/**
 * The human review loop (M5) in a real browser: a saved trip meets a disputed
 * fact, an admin confirms it in /admin, and the trip shows the update.
 *
 * It resolves the seeded Ginzan Onsen last-bus conflict, so it needs a freshly
 * seeded database (as CI has) and runs after the hero demos (files run in name
 * order, one worker). Re-running it locally needs a re-seed.
 */

const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN ?? "";

test("a reviewer confirms a disputed fact and the saved trip is updated", async ({ page }, info) => {
  test.skip(!ADMIN_TOKEN, "set E2E_ADMIN_TOKEN to the API's ADMIN_TOKEN");
  test.skip(info.project.name !== "desktop", "resolving the fact is one-off; run it once");

  // 1. Check and save a trip that includes Ginzan Onsen.
  await page.goto("/check");
  await page.getByRole("textbox", { name: "Your itinerary" }).fill("Tokyo 2N, Ginzan Onsen 2N, Tokyo");
  await page.getByRole("button", { name: "Read my itinerary" }).click();
  await page.getByRole("combobox").filter({ hasText: "Choose a month" }).selectOption("1");
  await page.getByRole("button", { name: "This is right: check it" }).click();
  await expect(page.getByRole("list", { name: "Day by day" })).toBeVisible();
  await expect(page.getByText(/being checked/i).first()).toBeVisible();
  await page.getByLabel("Trip name").fill("Ginzan in the snow");
  await page.getByRole("button", { name: "Save trip" }).click();
  await page.waitForURL(/\/trip\/[^/#]+/);
  const tripUrl = page.url();
  const share = await page.getByLabel("Read-only share link").inputValue();

  // 2. The admin queue lists the disputed fact, with the trip that depends on it.
  await page.goto("/admin");
  await page.getByLabel("Admin token").fill(ADMIN_TOKEN);
  await page.getByRole("button", { name: "Open the queue" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Ginzan Onsen" }).filter({ hasText: "Reported values" });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Being checked");
  await expect(row).toContainText(/[1-9]\d* saved trips? depend on this/);

  // 3. Confirm a time, with a source.
  await row.getByPlaceholder("HH:MM").fill("17:00");
  await row.getByPlaceholder("https://").fill("https://example.com/ginzan-bus");
  await row.getByRole("button", { name: "Confirm this time" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Ginzan Onsen" }).filter({ hasText: "Reported values" })).toHaveCount(0);

  // 4. The owner sees the update, and can mark it read.
  await page.goto(tripUrl);
  const updates = page.locator("section[aria-labelledby=updates]");
  await expect(updates).toContainText("Updates to your trip");
  await expect(updates).toContainText(/Ginzan Onsen: .* confirmed as 17:00/);
  await updates.getByRole("button", { name: "Mark as read" }).click();
  await expect(updates).not.toContainText("new)");

  // 5. So does anyone with the share link, read-only.
  await page.goto(new URL(share).pathname);
  await expect(page.locator("section[aria-labelledby=updates]")).toContainText("confirmed as 17:00");
  await expect(page.getByRole("button", { name: "Mark as read" })).toHaveCount(0);
});
