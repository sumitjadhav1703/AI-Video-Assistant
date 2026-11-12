"""Deploy the tested sample stack SHA to its configured Render service."""

import http.client
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

_PENDING = {'created', 'queued', 'build_in_progress', 'pre_deploy_in_progress', 'update_in_progress'}
_FAILED = {'build_failed', 'pre_deploy_failed', 'update_failed', 'canceled', 'deactivated'}
_MAX_RESPONSE = 64 * 1024


class DeploymentError(RuntimeError):
    pass


def request_json(url, *, token=None, payload=None, expected_type=dict):
    target = urlsplit(url)
    label = 'Render API' if token else 'Render sample check'
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    # HTTPSConnection never forwards the Render key to redirect targets.
    connection = http.client.HTTPSConnection(target.hostname, timeout=30)
    try:
        path = target.path + ('?' + target.query if target.query else '')
        connection.request('GET' if payload is None else 'POST', path,
                           body=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise DeploymentError(f'{label} returned HTTP {response.status}')
        body = response.read(_MAX_RESPONSE + 1)
        if len(body) > _MAX_RESPONSE:
            raise DeploymentError(f'{label} returned an oversized response')
        if response.status == 202 and payload is not None and not body:
            return {}
        data = json.loads(body)
    except (OSError, ValueError, http.client.HTTPException):
        raise DeploymentError(f'{label} request failed') from None
    finally:
        connection.close()
    if not isinstance(data, expected_type):
        raise DeploymentError(f'{label} returned an invalid response')
    return data


def queued_deployment(api, token, sha, created_after, deadline):
    # Render can acknowledge a queued deploy with an empty 202.
    query = urlencode({'createdAfter': created_after, 'limit': 20})
    while time.monotonic() < deadline:
        entries = request_json(f'{api}/deploys?{query}', token=token, expected_type=list)
        matches = []
        for entry in entries:
            deployment = entry.get('deploy') if isinstance(entry, dict) else None
            if not isinstance(deployment, dict) or deployment.get('trigger') != 'api':
                continue
            commit = deployment.get('commit')
            if isinstance(commit, dict) and commit.get('id') == sha:
                matches.append(deployment)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DeploymentError('Render returned multiple API deployments for the queued commit')
        time.sleep(10)
    raise DeploymentError('Render timed out locating the queued deployment')


def deploy(service_id, origin, repository, sha, token, summary, *, timeout=900):
    if not (
        re.fullmatch(r'srv-[a-z0-9]+', service_id)
        and re.fullmatch(r'https://[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', origin)
        and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
        and re.fullmatch(r'[a-f0-9]{40}', sha)
        and re.fullmatch(r'[!-~]+', token)
    ):
        raise DeploymentError('Render release configuration is missing or invalid')

    api = f'https://api.render.com/v1/services/{service_id}'
    service = request_json(api, token=token)
    details = service.get('serviceDetails')
    source = service.get('repo')
    auto_deploy = service.get('autoDeployTrigger', 'off' if service.get('autoDeploy') == 'no' else None)
    if (
        service.get('id') != service_id
        or service.get('type') != 'web_service'
        or service.get('branch') != 'main'
        or auto_deploy != 'off'
        or not isinstance(source, str)
        or source.rstrip('/').removesuffix('.git').lower() != f'https://github.com/{repository.lower()}'
        or not isinstance(details, dict)
        or details.get('url') != origin
        or details.get('runtime') != 'docker'
        or details.get('plan') != 'free'
        or details.get('region') != 'singapore'
        or details.get('healthCheckPath') != '/health'
    ):
        raise DeploymentError('Render service does not match the approved Singapore Free Docker target on GitHub main')

    for key, value in (('ENABLE_PROVIDER_CALLS', 'false'), ('DEMO_LIVE_MODE', 'sample')):
        flag = request_json(f'{api}/env-vars/{key}', token=token)
        if flag.get('key') != key or flag.get('value') != value:
            raise DeploymentError(f'Render service must set {key} directly to {value}')

    created_after = datetime.now(timezone.utc).isoformat(timespec='seconds')
    deadline = time.monotonic() + timeout
    deployment = request_json(f'{api}/deploys', token=token, payload={'commitId': sha})
    if not deployment:
        deployment = queued_deployment(api, token, sha, created_after, deadline)
    deployment_id = deployment.get('id')
    if not isinstance(deployment_id, str) or not re.fullmatch(r'dep-[a-z0-9]+', deployment_id):
        raise DeploymentError('Render API did not return a valid deployment ID')
    print(f'Render accepted deployment {deployment_id} for {sha}', flush=True)
    print(f'- Render deployment `{deployment_id}` for `{sha}`', file=summary, flush=True)

    while time.monotonic() < deadline:
        deployment = request_json(f'{api}/deploys/{deployment_id}', token=token)
        status = deployment.get('status')
        commit = deployment.get('commit')
        if deployment.get('id') != deployment_id or (
            commit is not None and (not isinstance(commit, dict) or commit.get('id') != sha)
        ):
            raise DeploymentError('Render deployment does not match the requested ID and commit')
        if status == 'live':
            if not commit:
                raise DeploymentError('Render live deployment did not identify its commit')
            break
        if isinstance(status, str) and status in _FAILED:
            raise DeploymentError(f'Render deployment ended with status {status}')
        if not isinstance(status, str) or status not in _PENDING:
            raise DeploymentError('Render API returned an unexpected deployment status')
        time.sleep(10)
    else:
        raise DeploymentError('Render deployment timed out before going live')

    for path, expected in (
        ('/health', {'status': 'ok'}),
        ('/ready', {'status': 'ok'}),
        ('/demo-mode', {'mode': 'sample'}),
    ):
        if request_json(origin + path) != expected:
            raise DeploymentError(f'Render {path} did not return the expected sample response')
    print('- Render is live. Health, readiness and sample mode passed.', file=summary, flush=True)


if __name__ == '__main__':
    try:
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            deploy(os.getenv('RENDER_SERVICE_ID', ''), os.getenv('RENDER_URL', ''),
                   os.getenv('GITHUB_REPOSITORY', ''), os.getenv('RELEASE_SHA', ''),
                   os.getenv('RENDER_API_KEY', ''), summary)
    except DeploymentError as error:
        raise SystemExit(str(error)) from None
    except (KeyError, OSError):
        raise SystemExit('GitHub step summary is unavailable') from None
