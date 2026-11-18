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
