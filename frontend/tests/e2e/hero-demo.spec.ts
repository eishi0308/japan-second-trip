import { expect, test, type Page } from "@playwright/test";

/**
 * The hero demos from PRODUCT_AMENDMENTS.md §10, end to end in a real browser
 * against the real API and the seeded catalogue. Nothing is stubbed.
 *
 * Needs both servers running (see playwright.config.ts). The API must be on
 * demo providers and allow many requests (RATE_LIMIT_PER_MINUTE), as CI sets.
 */

const CHARACTERS = ["Classic", "Unexpected", "Slow-paced"];

async function optionTitles(page: Page): Promise<string[]> {
  const cards = page.getByRole("group", { name: "React to this option" });
  await expect(cards).toHaveCount(3);
  return page.locator("article h2, article h3").allInnerTexts();
}

test.describe("hero demo: Australian couple, third visit, January", () => {
  test("plan, compare, what-if, day by day, pin and swap, save and share", async ({ page }) => {
    await page.goto("/plan");
    await page.getByLabel("Travel month").selectOption("1");
    await page.getByLabel("Regional nights").selectOption("4");
    await page.getByLabel("Arrival city").selectOption("Tokyo");
    await page.getByLabel("Departure city").selectOption("Tokyo");
    for (const interest of ["onsen", "snow", "food"]) {
      await page.getByRole("button", { name: interest, exact: true }).click();
    }
    await expect(page.getByRole("radiogroup", { name: "Getting around" }).getByRole("button", { name: "No car" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.getByRole("button", { name: "Show me three trips" }).click();

    // Three distinct options, in character order.
    await page.waitForURL(/\/plan\/[^/]+$/);
    for (const character of CHARACTERS) {
      await expect(page.getByText(character, { exact: true }).first()).toBeVisible();
    }
    const titles = await optionTitles(page);
    expect(new Set(titles).size).toBe(titles.length);

    // Kyushu is ruled out, with the change that would bring it back.
    await page.getByText("Not for this trip").click();
    const kyushu = page.getByRole("listitem").filter({ hasText: /^Kyushu/ });
    await expect(kyushu).toContainText("If you can fly out of Fukuoka");

    // Compare, then a what-if toggle recomputes the table.
    const planUrl = page.url();
    await page.getByRole("link", { name: "Compare side by side" }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("rowheader", { name: "Total travel time" }).or(page.getByText("Total travel time"))).toBeVisible();
    const drive = page.getByRole("button", { name: "If I can drive" });
    await drive.click();
    await expect(drive).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Showing the changed trip")).toBeVisible();

    // Option detail: a day-by-day timeline and a fragile-link warning with dated evidence.
    await page.goto(planUrl);
    await page.getByRole("link", { name: "Day by day" }).first().click();
    const timeline = page.getByRole("list", { name: "Day by day" });
    await expect(timeline).toBeVisible();
    expect(await timeline.locator(":scope > li").count()).toBe(5);
    const evidence = page.locator("details").filter({ has: page.getByText("Evidence", { exact: true }) });
    expect(await evidence.count()).toBeGreaterThan(0);
    await evidence.first().locator("summary").click();
    await expect(evidence.first()).toContainText(/checked \d{1,2} [A-Z][a-z]{2} \d{4}|being checked|no verified info/);
    const dated = page.getByText(/checked \d{1,2} [A-Z][a-z]{2} \d{4}/);
    expect(await dated.count()).toBeGreaterThan(0);

    // Pin the first stop, swap another: each change re-runs the check, the pin stays.
    const editor = page.getByRole("region", { name: "Stops" }).or(page.locator("section[aria-labelledby=stops]"));
    const firstPin = editor.getByRole("button", { name: "Pin", exact: true }).first();
    await firstPin.click();
    await expect(editor.getByRole("button", { name: "Pinned" }).first()).toHaveAttribute("aria-pressed", "true");
    // Swap the last unpinned stop: the alternatives are real places, and picking one re-runs the check.
    const swap = editor.locator("button:not([disabled])", { hasText: /^Swap$/ }).last();
    await swap.click();
    const alternatives = editor.getByRole("list", { name: /^Alternatives to / });
    await expect(alternatives).toBeVisible();
    const choice = alternatives.getByRole("button").first();
    const name = (await choice.innerText()).trim();
    await choice.click();
    await expect(alternatives).toHaveCount(0);
    await expect(editor).toContainText(name);
    await expect(editor.getByRole("button", { name: "Pinned" }).first()).toBeVisible();
    await expect(timeline).toBeVisible();

    // Save, land on the trip page, open the read-only share link.
    await page.getByLabel("Trip name").fill("Our January onsen trip");
    await page.getByRole("button", { name: "Save trip" }).click();
    await page.waitForURL(/\/trip\/[^/#]+/);
    await expect(page.getByRole("heading", { name: "Our January onsen trip" })).toBeVisible();
    const share = await page.getByLabel("Read-only share link").inputValue();
    expect(share).toMatch(/\/share\/[\w-]+$/);
    await page.goto(new URL(share).pathname);
    await expect(page.getByRole("heading", { name: "Our January onsen trip" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Day by day" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save trip" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Apply this fix" })).toHaveCount(0);
  });

  test("RouteCheck never removes pinned Ginzan Onsen", async ({ page }) => {
    await page.goto("/check");
    await page
      .getByRole("textbox", { name: "Your itinerary" })
      .fill("Tokyo 3N, Sendai 1N, Ginzan Onsen 1N, Aomori 1N, Hakodate 1N, Tokyo");
    await page.getByRole("button", { name: "Read my itinerary" }).click();

    const ginzanRow = page.getByRole("row").filter({ has: page.locator('input[value="Ginzan Onsen"]') });
    await expect(ginzanRow).toBeVisible();
    await ginzanRow.getByRole("checkbox").check();
    await page.getByRole("combobox").filter({ hasText: "Choose a month" }).selectOption("1");
    await page.getByRole("button", { name: "This is right: check it" }).click();

    const timeline = page.getByRole("list", { name: "Day by day" });
    await expect(timeline).toBeVisible();
    const editor = page.locator("section[aria-labelledby=stops]");
    await expect(editor.getByRole("button", { name: "Pinned" })).toHaveCount(1);
    await expect(editor).toContainText("Ginzan");

    // Apply every fix offered, one at a time: Ginzan stays pinned throughout.
    await expect(page.getByRole("button", { name: "Apply this fix" }).first()).toBeVisible();
    for (let i = 0; i < 3; i++) {
      const apply = page.getByRole("button", { name: "Apply this fix" });
      if ((await apply.count()) === 0) break;
      await apply.first().click();
      await expect(timeline).toBeVisible();
      await expect(editor).toContainText("Ginzan");
      await expect(editor.getByRole("button", { name: "Pinned" })).toHaveCount(1);
      await expect(editor.getByRole("button", { name: /^Remove Ginzan/ })).toBeDisabled();
    }
  });
});

test.describe("second hero demo: the vague user", () => {
  test("season choice, then three options with assumptions, and reactions regenerate", async ({ page }) => {
    await page.goto("/plan");
    // Every required field stays "Not decided yet".
    await expect(page.getByLabel("Travel month")).toHaveValue("");
    await page.getByLabel("Best moment on your last Japan trip").fill("Loved Nishiki Market food walks, tired of crowds");
    await page.getByRole("button", { name: "Snowy onsen town" }).click();
    await page.getByRole("button", { name: "Fishing village" }).click();
    await page.getByRole("button", { name: "Show me three trips" }).click();

    await page.waitForURL(/\/plan\/[^/]+$/);
    await expect(page.getByRole("heading", { name: "Pick a season" })).toBeVisible();
    await expect(page.getByText("Assumed: Tokyo in/out").first()).toBeVisible();

    await page.getByRole("button", { name: /^Choose / }).first().click();
    // Length is undecided too, so the next screen offers a shorter and a longer trip.
    await expect(page.getByRole("heading", { name: "How many nights?" })).toBeVisible();
    await page.getByRole("button", { name: /^Go with \d+ nights$/ }).first().click();
    await expect(page.getByRole("group", { name: "React to this option" })).toHaveCount(3);
    await expect(page.getByText("Assumed: Tokyo in/out").first()).toBeVisible();
    const before = await optionTitles(page);
    const url = page.url();

    await page.getByRole("group", { name: "React to this option" }).first().getByRole("button", { name: "Not for me" }).click();
    await expect.poll(() => page.url(), { timeout: 30_000 }).not.toBe(url);
    await expect(page.getByRole("group", { name: "React to this option" })).toHaveCount(3);
    const after = await optionTitles(page);
    expect(after).not.toEqual(before);
  });
});
