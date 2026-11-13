import { appendFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

function httpsOrigin(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Expected an HTTPS origin');
  }
  return url.origin;
}

const requestOptions = () => ({ redirect: 'error', signal: AbortSignal.timeout(20_000) });

async function vercelGet(path, settings, request) {
  const url = new URL(path, 'https://api.vercel.com');
  if (settings.orgId.startsWith('team_')) url.searchParams.set('teamId', settings.orgId);
  const response = await request(url, { ...requestOptions(), headers: { Authorization: `Bearer ${settings.token}` } });
  if (!response.ok) throw new Error(`Vercel API returned HTTP ${response.status}`);
  return response.json();
}

export async function checkVercelTarget(settings, request = fetch) {
  httpsOrigin(settings.renderUrl);
  const domain = new URL(httpsOrigin(settings.webUrl));
  if (domain.port || !/^prj_[A-Za-z0-9_]+$/.test(settings.projectId)) {
    throw new Error('Invalid Vercel target configuration');
  }
  const projectPath = '/v9/projects/' + settings.projectId;
  const project = await vercelGet(projectPath, settings, request);
  if (project.id !== settings.projectId || project.rootDirectory !== 'web') {
    throw new Error('Vercel project must use the web root');
  }
  const target = await vercelGet(projectPath + '/domains/' + domain.hostname, settings, request);
  if (target.projectId !== settings.projectId || target.name !== domain.hostname ||
      !target.verified || target.redirect || target.gitBranch || target.customEnvironmentId) {
    throw new Error('Vercel URL must be a verified production domain on the target project');
  }
}

export async function checkVercelDeployment(settings, request = fetch) {
  const deployment = new URL(httpsOrigin(settings.deploymentUrl));
  if (!deployment.hostname.endsWith('.vercel.app')) throw new Error('Expected a Vercel deployment URL');
  const result = await vercelGet('/v13/deployments/' + deployment.hostname, settings, request);
  if (!/^dpl_[A-Za-z0-9]+$/.test(result.id) || result.projectId !== settings.projectId ||
      result.meta?.releaseSha !== settings.sha || result.readyState !== 'READY' || result.target !== 'production') {
    throw new Error('Vercel did not report the requested production deployment and SHA');
  }
  return result.id;
}

export async function checkReleaseRouting(settings, request = fetch) {
  const webOrigin = httpsOrigin(settings.webUrl);
  const backend = httpsOrigin(settings.renderUrl);
  const release = await request(webOrigin + '/_ava-release.json', { ...requestOptions(), cache: 'no-store' });
  if (!release.ok || (await release.json()).sha !== settings.sha) {
    throw new Error('The configured production URL does not serve the tested commit');
  }
  const cors = await request(backend + '/jobs', {
    ...requestOptions(), method: 'OPTIONS', headers: {
      Origin: webOrigin, 'Access-Control-Request-Method': 'POST',
      'Access-Control-Request-Headers': 'authorization,content-type,x-demo-invite',
    },
  });
  if (!cors.ok || cors.headers.get('Access-Control-Allow-Origin') !== webOrigin) {
    throw new Error('Render did not allow the exact Vercel production origin');
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const settings = {
    deploymentUrl: process.env.VERCEL_DEPLOYMENT_URL, webUrl: process.env.VERCEL_URL,
    renderUrl: process.env.RENDER_URL, token: process.env.VERCEL_TOKEN,
    orgId: process.env.VERCEL_ORG_ID, projectId: process.env.VERCEL_PROJECT_ID, sha: process.env.RELEASE_SHA,
  };
  try {
    if (process.argv[2] === '--check-target') {
      await checkVercelTarget(settings);
    } else {
      const id = await checkVercelDeployment(settings);
      if (process.env.GITHUB_STEP_SUMMARY) {
        appendFileSync(process.env.GITHUB_STEP_SUMMARY, `- Vercel deployment \`${id}\` for \`${settings.sha}\`.\n`);
      }
      await checkReleaseRouting(settings);
    }
  } catch {
    console.error('Vercel deployment or release routing verification failed.');
    process.exitCode = 1;
  }
}
