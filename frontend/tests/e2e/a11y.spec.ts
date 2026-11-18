import { expect, test, type Page } from "@playwright/test";

/**
 * Accessibility basics from PRODUCT_AMENDMENTS.md §8 (WCAG AA, keyboard
 * navigation, screen-reader labels), checked on every top-level screen.
 */

const PAGES = ["/", "/plan", "/check", "/admin"];

async function problems(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const visible = (el: Element) => (el as HTMLElement).offsetParent !== null || el.getClientRects().length > 0;
    if (!document.documentElement.lang) out.push("<html> has no lang");
    if (!document.title.trim()) out.push("page has no title");
    const h1s = [...document.querySelectorAll("h1")].filter(visible);
    if (h1s.length !== 1) out.push(`expected one visible h1, found ${h1s.length}`);
    for (const img of document.querySelectorAll("img")) {
      if (!img.hasAttribute("alt")) out.push(`img without alt: ${img.src}`);
    }
    for (const el of document.querySelectorAll("button, a[href]")) {
      if (!visible(el)) continue;
      const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim() || el.getAttribute("title");
      if (!name) out.push(`unnamed ${el.tagName.toLowerCase()}: ${el.outerHTML.slice(0, 80)}`);
    }
    for (const el of document.querySelectorAll("input, select, textarea")) {
      const input = el as HTMLInputElement;
      if (input.type === "hidden" || !visible(el)) continue;
      const labelled =
        input.labels?.length ||
        el.getAttribute("aria-label") ||
        el.getAttribute("aria-labelledby") ||
        el.getAttribute("title");
      if (!labelled) out.push(`unlabelled ${el.tagName.toLowerCase()}: ${el.outerHTML.slice(0, 80)}`);
    }
    return out;
  });
}

for (const path of PAGES) {
  test(`${path} has a title, one h1, and named controls`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await problems(page)).toEqual([]);
  });
}

test("the options, option detail and RouteCheck result pass the same checks", async ({ page }) => {
  await page.goto("/plan");
  await page.getByLabel("Travel month").selectOption("1");
  await page.getByLabel("Regional nights").selectOption("4");
  await page.getByRole("button", { name: "onsen", exact: true }).click();
  await page.getByRole("button", { name: "Show me three trips" }).click();
  await page.waitForURL(/\/plan\/[^/]+$/);
  await expect(page.getByRole("group", { name: "React to this option" })).toHaveCount(3);
  expect(await problems(page), "options").toEqual([]);

  await page.getByRole("link", { name: "Day by day" }).first().click();
  await expect(page.getByRole("list", { name: "Day by day" })).toBeVisible();
  expect(await problems(page), "option detail").toEqual([]);

  await page.goto("/check");
  await page.getByRole("textbox", { name: "Your itinerary" }).fill("Tokyo 2N, Kanazawa 2N, Tokyo");
  await page.getByRole("button", { name: "Read my itinerary" }).click();
  await page.getByRole("combobox").filter({ hasText: "Choose a month" }).selectOption("5");
  await page.getByRole("button", { name: "This is right: check it" }).click();
  await expect(page.getByRole("list", { name: "Day by day" })).toBeVisible();
  expect(await problems(page), "RouteCheck result").toEqual([]);
});

test("the plan form can be reached and sent with the keyboard alone", async ({ page }) => {
  await page.goto("/plan");
  const submit = page.getByRole("button", { name: "Show me three trips" });
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press("Tab");
    if (await submit.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(submit).toBeFocused();
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/plan\/[^/]+$/);
});
