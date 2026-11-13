import assert from 'node:assert/strict';

// Checks /eval, /usage and /pipeline with the backend blocked: the pages must render from bundled data,
// degrade cleanly where live data is missing, and keep their controls working.
const { chromium } = await import(process.env.AVA_PLAYWRIGHT_MODULE || 'playwright');
const origin = new URL(process.env.AVA_FRONTEND_TEST_URL);
const backend = new URL(process.env.AVA_BACKEND_TEST_URL);
assert.notEqual(origin.origin, backend.origin);
const browser = await chromium.launch({ executablePath: process.env.AVA_CHROMIUM_EXECUTABLE });

async function openPage(path, options = {}) {
  const context = await browser.newContext({ serviceWorkers: 'block', ...options });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    // Blocked backend calls log network failures; anything else is a real error.
    if (message.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::/.test(message.text())) errors.push(message.text());
  });
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin === origin.origin && !url.pathname.startsWith('/api/')) return route.continue();
    return route.abort();
  });
  const response = await page.goto(new URL(path, origin).href);
  assert.ok(response?.ok(), `${path} responded successfully`);
  return { context, page, errors };
}

try {
  {
    const { context, page, errors } = await openPage('/eval');
    await page.getByRole('heading', { level: 1 }).waitFor();
    await page.getByText('43/45').first().waitFor();
    const row = page.locator('.info-q button[aria-expanded]').first();
    await row.click();
    assert.equal(await row.getAttribute('aria-expanded'), 'true', 'Question explorer row opens');
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, errors } = await openPage('/usage');
    await page.getByText('Live limits are unavailable right now').waitFor();
    await page.getByRole('heading', { name: 'One analysis, step by step' }).waitFor();
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, errors } = await openPage('/pipeline', { reducedMotion: 'reduce' });
    const count = page.locator('.pipe-count');
    await count.waitFor();
    const before = await count.textContent();
    await page.getByRole('button', { name: 'Next step' }).click();
    assert.notEqual(await count.textContent(), before, 'Next advances the pipeline');
    await page.getByRole('tab', { name: 'Answering a question' }).click();
    await page.getByRole('button', { name: 'Not in the recording' }).click();
    await page.locator('.pipe-steps button').last().click();
    await page.getByRole('heading', { name: 'Or it says it does not know' }).waitFor();
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page } = await openPage('/sample');
    await page.getByText('Drop a recording here.').waitFor();
    await page.getByRole('link', { name: 'How it works' }).first().waitFor();
    await context.close();
  }
  console.log('Evaluation, usage and pipeline pages passed');
} finally {
  await browser.close();
}
