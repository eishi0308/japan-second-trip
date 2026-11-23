import { expect, test, type Page } from "@playwright/test";

/**
 * Keyboard focus must always be visible (PRODUCT_AMENDMENTS.md §8). Tab through
 * each screen and check that every element that takes focus shows a ring or an
 * outline.
 */

async function invisibleFocus(page: Page, maxTabs = 60): Promise<string[]> {
  const out = new Set<string>();
  for (let i = 0; i < maxTabs; i++) {
    await page.keyboard.press("Tab");
    const result = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return { done: true, bad: null };
      // The Next.js dev overlay is not part of the product.
      if (el.tagName.toLowerCase() === "nextjs-portal") return { done: false, bad: null };
      const s = getComputedStyle(el);
      const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0;
      const ring = s.boxShadow !== "none" && s.boxShadow !== "";
      const label = (el.getAttribute("aria-label") ?? el.textContent ?? el.getAttribute("name") ?? "").trim().slice(0, 40);
      return { done: false, bad: outline || ring ? null : `${el.tagName.toLowerCase()} "${label}"` };
    });
    if (result.done) break;
    if (result.bad) out.add(result.bad);
  }
  return [...out];
}

for (const path of ["/", "/plan", "/check", "/admin"]) {
  test(`${path}: every focused control shows a focus ring`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await invisibleFocus(page)).toEqual([]);
  });
}
