// Run against a loopback Vite dev server. Playwright is an external test tool.
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.AVA_PLAYWRIGHT_MODULE || 'playwright');
const origin = new URL(process.env.AVA_FRONTEND_TEST_URL || 'http://127.0.0.1:5173');
assert.equal(origin.hostname, '127.0.0.1', 'Use a loopback test server');
assert.equal(origin.protocol, 'http:');

const browser = await chromium.launch({ executablePath: process.env.AVA_CHROMIUM_EXECUTABLE });
try {
  const page = await browser.newPage({ viewport: { width: 320, height: 749 }, reducedMotion: 'reduce' });
  const jobPath = '/api/jobs/test';
  const question = 'When does the pilot launch?';
  const answer = 'The pilot launches on Monday.';
  const result = {
    title: 'Synthetic meeting',
    summary: 'Verify the budget and follow up with the team.',
    action_items: 'Owner to confirm the launch date.',
    key_decisions: '',
    open_questions: '',
    transcript: 'A synthetic transcript used in the layout regression test.',
  };
  const requests = [];
  const demoPath = '/demo-clips/llm-explained.mp3';
  let demoAttempts = 0;
  let releaseDemo;
  const demoReady = new Promise((resolve) => { releaseDemo = resolve; });
  let finished = false;
  let deletionAttempts = 0;
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (url.origin !== origin.origin) return route.abort();
    if (url.pathname === demoPath) {
      demoAttempts += 1;
      if (demoAttempts === 1) return route.fulfill({ status: 503 });
      await demoReady;
      return route.continue();
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    requests.push({ path: url.pathname, method, headers: request.headers(), body: request.postData() });
    if (url.pathname === '/api/demo-mode') return route.fulfill({ json: { mode: 'invited' } });
    if (method === 'POST' && url.pathname === '/api/jobs') {
      return route.fulfill({ status: 202, json: { job_id: 'test', job_token: 'test-capability' } });
    }
    if (method === 'GET' && url.pathname === jobPath) {
      return route.fulfill({ json: finished ? { status: 'done' } : { status: 'running', step: 'transcript' } });
    }
    if (method === 'GET' && url.pathname === `${jobPath}/result`) return route.fulfill({ json: result });
    if (method === 'POST' && url.pathname === `${jobPath}/chat`) {
      return route.fulfill({ json: { answer, citations: [{
        chunk_id: 'chunk-1', text: answer, start_ms: 7000, end_ms: 9000, timing_precision: 'segment',
      }] } });
    }
    if (method === 'DELETE' && url.pathname === jobPath) {
      deletionAttempts += 1;
      return deletionAttempts === 1
        ? route.fulfill({ status: 409, json: { detail: 'Session is busy.' } })
        : route.fulfill({ json: { deleted: true } });
    }
    return route.abort();
  });

  await page.goto(origin.href);
  const intro = page.getByText('Preparing the record');
  await intro.waitFor();
  await intro.waitFor({ state: 'hidden' });
  await page.getByRole('heading', { name: /Every word/ }).waitFor();
  assert.ok(await page.getByRole('button', { name: 'YouTube URL' }).isDisabled());
  const analyse = page.getByRole('button', { name: /Analyse/ });
  await page.locator('input[type=file]').setInputFiles({
    name: 'fixture.mp4', mimeType: 'video/mp4', buffer: Buffer.from('synthetic video'),
  });
  assert.ok(await analyse.isDisabled(), 'Upload requires an invite');
  assert.equal(await page.getByRole('checkbox').count(), 0, 'The upload acknowledgement has no separate control');
  await page.getByLabel(/invite code/i).fill('test-invite');
  assert.ok(await analyse.isEnabled(), 'The invite and selected file enable Analyse');
  assert.equal(requests.filter(({ method, path }) => method === 'POST' && path === '/api/jobs').length, 0);
  await analyse.click();
  await page.getByRole('heading', { name: 'Writing it down.' }).waitFor();
  finished = true;
  await page.getByRole('button', { name: 'Check status' }).click();

  const heading = page.getByRole('heading', { name: result.title });
  await heading.waitFor();
  const chat = page.getByRole('region', { name: 'Ask the meeting' });
  const summary = page.getByText(result.summary, { exact: true });
  const actionItem = page.getByText(result.action_items, { exact: true });
  const questionBox = page.getByRole('textbox', { name: 'Question about this meeting' });
  const ask = page.getByRole('button', { name: 'Ask', exact: true });
  const showTranscript = page.getByRole('button', { name: /Show full transcript/ });
  for (const width of [320, 1082]) {
    await page.setViewportSize({ width, height: 749 });
    const [chatBox, summaryBox, actionBox, questionBounds, askBox, transcriptBox] = await Promise.all(
      [chat, summary, actionItem, questionBox, ask, showTranscript].map((locator) => locator.boundingBox()),
    );
    const { clientWidth, scrollWidth } = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    assert.equal(scrollWidth, clientWidth);
    assert.ok(chatBox && summaryBox && actionBox && questionBounds && askBox && transcriptBox);
    for (const box of [questionBounds, askBox]) {
      assert.ok(box.x >= 0 && box.x + box.width <= clientWidth && box.y >= 0 && box.y + box.height <= 749,
        `Chat is ready without scrolling at ${width}px`);
    }
    if (width === 320) {
      assert.ok(chatBox.y + chatBox.height <= summaryBox.y, 'Chat comes before notes on mobile');
    } else {
      assert.ok(chatBox.x + chatBox.width <= summaryBox.x && summaryBox.y < chatBox.y + chatBox.height,
        'Notes sit beside chat on desktop');
    }
    assert.ok(transcriptBox.y >= Math.max(chatBox.y + chatBox.height, actionBox.y + actionBox.height),
      'The full transcript control follows chat and notes');
  }
  await page.setViewportSize({ width: 320, height: 749 });
  assert.equal(await showTranscript.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.getByText(result.transcript, { exact: true }).count(), 0);
  await showTranscript.click();
  assert.equal(await page.getByRole('button', { name: /Hide full transcript/ }).getAttribute('aria-expanded'), 'true');
  await page.getByText(result.transcript).waitFor();
  await questionBox.fill(question);
  await ask.click();
  // The mocked citation quotes the answer verbatim, so two elements match.
  await page.getByText(answer, { exact: true }).first().waitFor();
  await page.getByText(/0:07.*0:09.*The pilot launches on Monday/).waitFor();

  await page.reload();
  await heading.waitFor();
  page.on('dialog', (dialog) => dialog.accept());
  const reset = page.getByRole('button', { name: 'Delete session' });
  await reset.click();
  await page.getByRole('alert').filter({ hasText: 'Session is busy.' }).waitFor();
  assert.ok(await heading.isVisible(), 'Failed deletion retains the active session');
  await reset.click();
  await page.getByText('Live session deleted.').waitFor();
  await page.getByRole('heading', { name: /Every word/ }).waitFor();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('minutes.live-session')), null);

  const upload = requests.filter(({ method, path }) => method === 'POST' && path === '/api/jobs');
  assert.equal(upload.length, 1, 'Refresh resumes the job without uploading again');
  assert.equal(upload[0].headers['x-demo-invite'], 'test-invite');
  assert.match(upload[0].body, /name="file"; filename="fixture\.mp4"/);
  assert.match(upload[0].body, /name="language"\r\n\r\nenglish/);
  assert.match(upload[0].body, /name="demo_acknowledged"\r\n\r\ntrue/);
  assert.deepEqual(JSON.parse(requests.find(({ path }) => path === `${jobPath}/chat`).body), { question, tier: 'economy' });
  assert.equal(deletionAttempts, 2);
  for (const request of requests.filter(({ path }) => path.startsWith(jobPath))) {
    assert.equal(request.headers.authorization, 'Bearer test-capability');
  }

  const demo = page.getByRole('button', { name: /Large language models explained/ });
  await page.getByRole('button', { name: /Generative AI explained/ }).waitFor();
  const fileInput = page.locator('input[type=file]');
  await fileInput.setInputFiles({
    name: 'keep-on-failure.mp4', mimeType: 'video/mp4', buffer: Buffer.from('synthetic video'),
  });
  await demo.click();
  await page.getByRole('alert').waitFor();
  await page.getByText('keep-on-failure.mp4', { exact: true }).waitFor();

  await demo.click();
  try {
    await page.getByText('Loading demo clip…', { exact: true }).waitFor();
    assert.ok(await analyse.isDisabled());
    assert.equal(requests.filter(({ method, path }) => method === 'POST' && path === '/api/jobs').length, 1);
  } finally {
    releaseDemo();
  }
  await page.getByText('Demo clip loaded.', { exact: true }).waitFor();
  const selectedCard = page.getByRole('button', { name: /Remove/ }).locator('..');
  await selectedCard.getByText('Large language models explained', { exact: true }).waitFor();
  assert.ok(await analyse.isDisabled(), 'Demo clips still require an invite in invited mode');
  assert.equal(await page.getByRole('checkbox').count(), 0);
  await page.getByLabel(/invite code/i).fill('test-invite');
  assert.ok(await analyse.isEnabled(), 'The demo is ready for an explicit Analyse click');
  assert.equal(requests.filter(({ method, path }) => method === 'POST' && path === '/api/jobs').length, 1);
  const demoUpload = page.waitForRequest((request) =>
    request.method() === 'POST' && new URL(request.url()).pathname === '/api/jobs');
  await analyse.click();
  const demoRequest = await demoUpload;
  assert.equal(demoRequest.headers()['x-demo-invite'], 'test-invite');
  assert.match(demoRequest.postData(), /name="file"; filename="llm-explained\.mp3"/);
  assert.match(demoRequest.postData(), /name="demo_acknowledged"\r\n\r\ntrue/);
  console.log('Restored Minutes upload, progress, cited chat, mobile transcript, refresh, and authenticated deletion passed');
  console.log('Demo picker preserved the manual file on failure and uploaded the selected clip on Analyse');
} finally {
  await browser.close();
}
