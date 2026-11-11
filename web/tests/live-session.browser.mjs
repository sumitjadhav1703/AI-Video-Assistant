// Run against a loopback Vite dev server. Playwright is an external test tool.
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.AVA_PLAYWRIGHT_MODULE || 'playwright');
const origin = new URL(process.env.AVA_FRONTEND_TEST_URL || 'http://127.0.0.1:5173');
assert.equal(origin.hostname, '127.0.0.1', 'Use a loopback test server');
assert.equal(origin.protocol, 'http:');

const browser = await chromium.launch({ executablePath: process.env.AVA_CHROMIUM_EXECUTABLE });
try {
  const page = await browser.newPage({ viewport: { width: 320, height: 800 }, reducedMotion: 'reduce' });
  const reads = [];
  const result = {
    title: 'Synthetic meeting',
    summary: 'Verify the budget and follow up with the team.',
    action_items: 'Owner to confirm the launch date.',
    key_decisions: '',
    open_questions: '',
    transcript: 'A synthetic transcript used in the layout regression test.',
  };
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin.origin) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    reads.push(url.pathname);
    if (url.pathname === '/api/jobs/test/result') return route.fulfill({ json: result });
    if (url.pathname === '/api/jobs/test') return route.fulfill({ json: { status: 'done' } });
    return route.abort();
  });
  await page.addInitScript(() => {
    sessionStorage.setItem('minutes.live-session', JSON.stringify({ id: 'test', token: 'test' }));
    history.replaceState({ resumeLiveDemo: true }, '');
  });
  await page.goto(origin.href);
  const heading = page.getByRole('heading', { name: 'Synthetic meeting' });
  await heading.waitFor();
  const layout = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  const ask = await page.getByRole('button', { name: 'Ask', exact: true }).boundingBox();
  console.log('Live layout', { ...layout, askRight: ask.x + ask.width });
  assert.equal(layout.scrollWidth, layout.viewport);
  assert.ok(ask.x + ask.width <= layout.viewport, 'Ask stays inside the viewport');
  assert.equal(reads.at(-1), '/api/jobs/test/result');
  const initialReads = reads.length;

  const showTranscript = page.getByRole('button', { name: /Show full transcript/ });
  assert.equal(await showTranscript.getAttribute('aria-expanded'), 'false');
  await showTranscript.click();
  assert.equal(await page.getByRole('button', { name: /Hide full transcript/ }).getAttribute('aria-expanded'), 'true');
  await page.getByText(result.transcript).waitFor();

  await page.getByRole('button', { name: 'Explore a sample' }).click();
  await page.getByRole('button', { name: 'When does the pilot launch?' }).click();
  await page.getByRole('button', { name: 'Jump to 0:00' }).waitFor();
  assert.equal(reads.length, initialReads, 'The prepared sample is local');
  await page.getByRole('button', { name: 'Resume live session' }).click();
  await heading.waitFor();
  assert.equal(reads.length, initialReads, 'Resume uses the loaded result');
  console.log('Prepared sample, transcript disclosure, and completed-session resume passed');
} finally {
  await browser.close();
}
