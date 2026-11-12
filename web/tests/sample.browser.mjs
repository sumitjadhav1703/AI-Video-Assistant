import assert from 'node:assert/strict';

const { chromium } = await import(process.env.AVA_PLAYWRIGHT_MODULE || 'playwright');
const origin = new URL(process.env.AVA_FRONTEND_TEST_URL);
const backend = new URL(process.env.AVA_BACKEND_TEST_URL);
assert.notEqual(origin.origin, backend.origin);
const browser = await chromium.launch({ executablePath: process.env.AVA_CHROMIUM_EXECUTABLE });
try {
  const page = await browser.newPage({ serviceWorkers: 'block' });
  let backendRequests = 0;
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin === backend.origin || (url.origin === origin.origin && url.pathname.startsWith('/api/'))) {
      backendRequests += 1;
      return route.abort();
    }
    if (url.origin === origin.origin) return route.continue();
    return route.abort();
  });
  const response = await page.goto(new URL('/sample', origin).href);
  assert.ok(response?.ok(), 'Sample page responded successfully');
  await page.getByRole('heading', { name: 'Onboarding pilot review' }).first().waitFor();
  await page.getByRole('button', { name: 'Who will send the invitations?' }).click();
  await page.getByRole('button', { name: 'Jump to 0:07' }).click();
  const video = page.getByLabel('Onboarding pilot sample video');
  await page.waitForFunction(() => {
    const element = document.querySelector('video');
    return element?.readyState >= 1 && Math.abs(element.currentTime - 7) < 0.5;
  });
  assert.equal(await video.count(), 1);
  assert.equal(backendRequests, 0, 'The prepared sample works without backend access');
  console.log('Prepared sample and citation seek passed');
} finally {
  await browser.close();
}
