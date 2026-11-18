import { expect, test, type Page } from "@playwright/test";

/**
 * WCAG AA text contrast (PRODUCT_AMENDMENTS.md §8): 4.5:1 for body text and
 * 3:1 for large text (24px, or 18.66px bold), in light and dark colour schemes.
 */

async function lowContrast(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const parse = (c: string) => {
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const [r, g, b, a = "1"] = m[1].split(/[ ,/]+/).filter(Boolean);
      return [Number(r), Number(g), Number(b), Number(a)];
    };
    const lum = ([r, g, b]: number[]) => {
      const f = (v: number) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const background = (el: Element | null): number[] => {
      for (; el; el = el.parentElement) {
        const c = parse(getComputedStyle(el).backgroundColor);
        if (c && c[3] > 0.5) return c;
      }
      return [255, 255, 255, 1];
    };
    const out: string[] = [];
    const seen = new Set<Element>();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!el || seen.has(el) || !n.textContent?.trim()) continue;
      seen.add(el);
      const style = getComputedStyle(el);
      if (el.getClientRects().length === 0 || style.visibility === "hidden" || Number(style.opacity) === 0) continue;
      if (el.closest("[disabled], [aria-disabled=true], [aria-hidden=true], .sr-only")) continue;
      const fg = parse(style.color);
      if (!fg || fg[3] < 0.5) continue;
      const bg = background(el);
      const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
      const ratio = (l1 + 0.05) / (l2 + 0.05);
      const size = parseFloat(style.fontSize);
      const large = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700);
      if (ratio < (large ? 3 : 4.5)) {
        out.push(`${ratio.toFixed(2)}:1 "${n.textContent.trim().slice(0, 40)}" (${style.color} on rgb(${bg.slice(0, 3).join(",")}))`);
      }
    }
    return out;
  });
}

for (const scheme of ["light", "dark"] as const) {
  for (const path of ["/", "/plan", "/check", "/admin"]) {
    test(`${path} text meets AA contrast (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await lowContrast(page)).toEqual([]);
    });
  }
}

test("options, option detail and the RouteCheck result meet AA contrast", async ({ page }) => {
  await page.goto("/plan");
  await page.getByLabel("Travel month").selectOption("1");
  await page.getByLabel("Regional nights").selectOption("4");
  await page.getByRole("button", { name: "onsen", exact: true }).click();
  await page.getByRole("button", { name: "Show me three trips" }).click();
  await page.waitForURL(/\/plan\/[^/]+$/);
  await expect(page.getByRole("group", { name: "React to this option" })).toHaveCount(3);
  await page.getByText("Not for this trip").click();
  expect(await lowContrast(page), "options").toEqual([]);

  await page.getByRole("link", { name: "Day by day" }).first().click();
  await expect(page.getByRole("list", { name: "Day by day" })).toBeVisible();
  for (const summary of await page.locator("details > summary").all()) await summary.click();
  expect(await lowContrast(page), "option detail").toEqual([]);

  await page.goto("/check");
  await page.getByRole("textbox", { name: "Your itinerary" }).fill("Tokyo 2N, Ginzan Onsen 1N, Tokyo");
  await page.getByRole("button", { name: "Read my itinerary" }).click();
  await page.getByRole("combobox").filter({ hasText: "Choose a month" }).selectOption("1");
  await page.getByRole("button", { name: "This is right: check it" }).click();
  await expect(page.getByRole("list", { name: "Day by day" })).toBeVisible();
  expect(await lowContrast(page), "RouteCheck result").toEqual([]);
});
