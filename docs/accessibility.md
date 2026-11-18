# Accessibility

PRODUCT_AMENDMENTS.md §8 asks for WCAG AA contrast, keyboard navigation and
screen-reader labels. Two browser tests check this on every run.

## What is checked

[`frontend/tests/e2e/a11y.spec.ts`](../frontend/tests/e2e/a11y.spec.ts) loads the
home page, Where Next, RouteCheck and admin screens, plus the options, option
detail and RouteCheck result. On each one it checks for:

- a `lang` on `<html>` and a page title;
- exactly one visible `h1`;
- `alt` on every image;
- a name on every visible button and link;
- a label on every visible input, select and text area.

It also tabs through the Where Next form to "Show me three trips" and sends it
with Enter.

[`frontend/tests/e2e/contrast.spec.ts`](../frontend/tests/e2e/contrast.spec.ts)
measures every visible piece of text against its background. Body text needs
4.5:1 and large text (24px, or 18.66px bold) needs 3:1. It runs the four forms in
light and dark schemes, then the result screens with the rejections and all
evidence opened.

## What it found

Small grey text (`ink-400`, 3.4 to 3.6:1) was used for:

- the header tagline;
- the demo adapters label;
- "estimated" in the RouteCheck timeline;
- the stop numbers in the RouteCheck editor;
- input placeholders;
- the error digest;
- two admin labels.

All of it now uses `ink-500`, which is above 4.5:1. `ink-400` is kept only for
icons, which need 3:1.

## Not checked

- Contrast inside images, and on hover and focus states.
- Screen-reader output itself. The tests check that names exist, not how a
  reader announces them.
