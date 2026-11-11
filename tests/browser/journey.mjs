// Run with PLAYWRIGHT_MODULE pointing to a locally installed Playwright package.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({ executablePath: process.env.AVA_CHROMIUM_EXECUTABLE });
try {
  const page = await browser.newPage();
  const app = 'http://127.0.0.1:55173';
  const backend = 'http://127.0.0.1:55800';
  let polls = 0;
  let injectedFailure = false;
  const requestCounts = {};
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === backend) {
      const endpoint = url.pathname.replace(/\/jobs\/[a-f0-9]{32}/, '/jobs/:id');
      const key = `${request.method()} ${endpoint}`;
      requestCounts[key] = (requestCounts[key] || 0) + 1;
      if (request.method() === 'GET' && endpoint === '/jobs/:id') {
        polls += 1;
        if (polls === 1) {
          injectedFailure = true;
          return route.abort('failed');
        }
      }
    }
    if ([app, backend].includes(url.origin) || url.protocol === 'data:') return route.continue();
    return route.abort('blockedbyclient');
  });

  await page.goto(app);
  await page.getByRole('button', { name: 'Analyze your own clip' }).click();
  await page.getByLabel('Audio or video file').setInputFiles(process.env.AVA_BROWSER_MEDIA);
  await page.getByRole('checkbox').check();
  const startedAt = Date.now();
  await page.getByRole('button', { name: 'Analyze clip' }).click();
  await page.getByRole('button', { name: 'Delete session' }).waitFor();
  await page.getByText('Synthetic Release Review', { exact: true }).first().waitFor();
  const resultMs = Date.now() - startedAt;
  await page.getByText('The operations team owns the Friday release.', { exact: false }).first().waitFor();
  const chatStartedAt = Date.now();
  await page.getByRole('textbox', { name: 'Question about this meeting' }).fill('When will the team ship the demo?');
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  await page.getByText('Sources', { exact: true }).waitFor();
  const chatMs = Date.now() - chatStartedAt;
  await page.getByText(/0:00–0:01.*The operations team will ship the demo on Friday/).waitFor();
  assert.ok(injectedFailure && polls >= 2, 'polling recovered after a transport failure');
  const deleted = page.waitForResponse(response => response.request().method() === 'DELETE');
  await page.getByRole('button', { name: 'Delete session' }).click();
  assert.equal((await deleted).status(), 200);
  await page.getByText('Live session deleted.', { exact: true }).waitFor();
  console.log(JSON.stringify({ resultMs, chatMs, polls, injectedFailure, requestCounts }));
} finally {
  await browser.close();
}
