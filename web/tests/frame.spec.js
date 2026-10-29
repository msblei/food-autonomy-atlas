// The panel's frame (place, food, four-row card) must stand still while the reader clicks through
// a country: the same four rows in the same place for every food and every question, and back
// going up one step at a time.
import { expect, test } from "@playwright/test";

const card = (page) => page.locator("#card");
// The food menu opens from its button on wide screens.
async function pick(page, food) {
  await page.locator("#foods .current").click();
  await page.locator(`#foods [data-food='${food}']`).click();
}
async function cardTop(page) {
  return Math.round((await card(page).boundingBox()).y);
}

test("the card keeps its place and its four rows", async ({ page }) => {
  await page.goto("./#DEU");
  await expect(card(page).locator(".sum-row")).toHaveCount(4);
  const top = await cardTop(page);
  const steps = [
    () => pick(page, "fruit"),
    () => card(page).locator("[data-row='imports']").click(),
    () => card(page).locator("[data-row='exports']").click(),
    () => card(page).locator("[data-row='used']").click(),
    () => pick(page, "cereals"),
    () => pick(page, "fish"),
    () => pick(page, "all"),
    () => page.goto("./#POL/meat"),
    () => page.goto("./#JPN"),
    () => page.goto("./#EU27/dairy/used"),
  ];
  for (const step of steps) {
    await step();
    await page.waitForTimeout(150);
    await expect(card(page).locator(".sum-row")).toHaveCount(4);
    expect(await cardTop(page), `card moved after ${step}`).toBe(top);
  }
});

test("back goes up one step at a time", async ({ page }) => {
  await page.goto("./#DEU/fruit/sells");
  for (const want of ["#DEU/fruit", "#DEU", ""]) {
    await page.locator("#up").click();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe(want);
  }
});

test("the map and start page come from the small core file; the panel waits for the full one", async ({ page }) => {
  let release;
  const held = new Promise((r) => { release = r; });
  await page.route("**/data/ssr.json", async (route) => { await held; await route.continue(); });
  await page.goto("./#DEU/cereals");
  await expect(page.locator("#legend")).toContainText("would last"); // painted from ssr_core.json
  await expect(page.locator("#view")).toContainText("Loading");
  await expect(page.locator("#card")).toHaveAttribute("aria-busy", "true");
  release();
  await expect(page.locator("#view .answer")).toBeVisible();
  await expect(page.locator("#card")).toHaveAttribute("aria-busy", "false");
});

test("borders come as TopoJSON, and the GeoJSON still works when it is missing", async ({ page }) => {
  const got = [];
  page.on("response", (r) => { if (/countries\.(topo|geo)json/.test(r.url())) got.push(r.url().split("/").pop()); });
  await page.goto("./#DEU");
  await expect(page.locator("#view .answer")).toBeVisible();
  expect(got).toEqual(["countries.topojson"]);
  await page.route("**/data/countries.topojson", (route) => route.fulfill({ status: 404, body: "" }));
  await page.goto("./#FRA");
  await expect(page.locator("#view .answer")).toBeVisible();
  await expect(page.locator("#place")).toHaveText("France");
});

test("zoomed in close, the map shows every country's regions for the food; zoomed out, the months", async ({ page }) => {
  const key = page.locator("#legend .title");
  const zoom = async (dy) => {
    const box = await page.locator("#map canvas").boundingBox();
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.4);
    for (let i = 0; i < 8; i++) { await page.mouse.wheel(0, dy); await page.waitForTimeout(150); }
  };
  await page.goto("./#ITA/cereals");
  await expect(key).toContainText("How long its own cereals would last");
  await zoom(-300);
  await expect(key).toContainText("Where cereals grow, tonnes per km²", { timeout: 8000 });
  await zoom(300);
  await expect(key).toContainText("How long its own cereals would last", { timeout: 8000 });
  // the same on the world map, with no country picked
  await page.goto("./");
  await page.locator("#foods .current").click();
  await page.locator("#foods [data-food='cereals']").click();
  await zoom(-300);
  await expect(key).toContainText("Where cereals grow, tonnes per km²", { timeout: 8000 });
});
