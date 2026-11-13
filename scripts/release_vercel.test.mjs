import assert from 'node:assert/strict';
import test from 'node:test';
import { checkVercelDeployment, checkReleaseRouting, checkVercelTarget } from './release_vercel.mjs';

const sha = 'a'.repeat(40);
const deployment = { id: 'dpl_sample', projectId: 'prj_sample', readyState: 'READY',
  target: 'production', meta: { releaseSha: sha } };
const settings = {
  deploymentUrl: 'https://sample-build.vercel.app',
  webUrl: 'https://sample.vercel.app',
  renderUrl: 'https://sample.onrender.com',
  token: 'fixture',
  orgId: 'team_sample',
  projectId: 'prj_sample',
  sha,
};

test('Vercel deployment belongs to the target project and exact release SHA', async () => {
  const lookup = async (url, options) => {
    assert.equal(url.origin, 'https://api.vercel.com');
    assert.equal(url.pathname, '/v13/deployments/sample-build.vercel.app');
    assert.equal(url.searchParams.get('teamId'), 'team_sample');
    assert.equal(options.redirect, 'error');
    return Response.json(deployment);
  };
  assert.equal(await checkVercelDeployment(settings, lookup), deployment.id);
  for (const override of [{ projectId: 'prj_wrong' }, { meta: {} }, { readyState: 'ERROR' }, { target: null }]) {
    await assert.rejects(checkVercelDeployment(settings, async () => Response.json({ ...deployment, ...override })));
  }
  await assert.rejects(checkVercelDeployment({ ...settings, deploymentUrl: 'http://sample-build.vercel.app' }, lookup));
});

test('stable site serves the tested SHA and Render allows the exact production origin', async () => {
  const calls = [];
  const request = async (url, options) => {
    calls.push(url);
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers?.Authorization, undefined);
    if (url === settings.webUrl + '/_ava-release.json') return Response.json({ sha });
    assert.equal(url, settings.renderUrl + '/jobs');
    assert.equal(options.method, 'OPTIONS');
    assert.equal(options.headers.Origin, settings.webUrl);
    return new Response(null, { headers: { 'Access-Control-Allow-Origin': settings.webUrl } });
  };
  await checkReleaseRouting(settings, request);
  assert.equal(calls.length, 2);
  await assert.rejects(checkReleaseRouting(settings, async () => Response.json({ sha: 'b'.repeat(40) })));
  await assert.rejects(checkReleaseRouting(settings, async (url) => url.endsWith('.json')
    ? Response.json({ sha })
    : new Response(null, { headers: { 'Access-Control-Allow-Origin': '*' } })));
});

test('Vercel preflight rejects a different project or non-production domain', async () => {
  const request = async (url, options) => {
    assert.equal(url.origin, 'https://api.vercel.com');
    assert.equal(options.redirect, 'error');
    if (url.pathname.endsWith('/domains/sample.vercel.app')) {
      return Response.json({ projectId: settings.projectId, name: 'sample.vercel.app', verified: true });
    }
    assert.equal(url.pathname, '/v9/projects/prj_sample');
    return Response.json({ id: settings.projectId, rootDirectory: 'web' });
  };
  await checkVercelTarget(settings, request);
  await assert.rejects(checkVercelTarget(settings, async () => Response.json({
    id: settings.projectId, rootDirectory: 'unrelated',
  })));
});
