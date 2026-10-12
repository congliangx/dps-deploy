#!/usr/bin/env python3
"""Read-only DPS 0.9 installation checks; login/logout only mutate test sessions.

No topology import, activation, policy change, BMC write, or Helm mutation.
Private credentials remain in config/dpsctl; tokens and cookies are never reported.
"""

# Public deployment settings select source inputs and isolated runtime outputs.
import sys as _deployment_sys
from pathlib import Path as _DeploymentPath
_deployment_sys.dont_write_bytecode = True
_deployment_sys.path.insert(0, str(_DeploymentPath(__file__).resolve().parents[2] / 'dps-install/scripts'))
from deployment_context import context_from_cli as _deployment_context
CTX = _deployment_context()
SETTINGS = CTX.settings
SOURCE_ROOT = CTX.source_root
RUNTIME_ROOT = CTX.runtime_root
for _deployment_output in ('verification/reports', 'verification/logs', 'verification/archive'):
    CTX.runtime_path(_deployment_output).mkdir(parents=True, exist_ok=True, mode=0o700)
import datetime
import http.cookiejar
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import yaml
import urllib.error
import urllib.request

ROOT = CTX.runtime_root
CONFIG = ROOT / 'dps-install/config'
REPORT = ROOT / 'verification/reports/dps-installation.json'
CLI_LOG = ROOT / 'verification/logs/dpsctl.log'
CREDENTIALS = CONFIG / 'dpsctl/credentials.yaml'
CONTEXT = SETTINGS['kube_context']
NAMESPACE = SETTINGS['namespace']
checks = []
private_values = []
os.umask(0o077)
os.environ.update({
    'KUBECONFIG': str(CONFIG / 'kubernetes/kubeconfig.yaml'),
    'HELM_CONFIG_HOME': str(CONFIG / 'helm'),
    'HELM_CACHE_HOME': str(ROOT / 'dps-install/data/helm-cache'),
    'HELM_DATA_HOME': str(ROOT / 'dps-install/data/helm-data'),
    'DPSCTL_HOST': SETTINGS['api_name'], 'DPSCTL_PORT': '443',
    'DPSCTL_CA_CERT_PATH': str(CONFIG / 'tls/ca.crt'),
    'DPSCTL_CREDENTIALS_PATH': str(CREDENTIALS),
    'DPSCTL_LOG_FILE': str(CLI_LOG),
})
CREDENTIALS.parent.mkdir(exist_ok=True, mode=0o700)
CREDENTIALS.parent.chmod(0o700)
CLI_LOG.parent.mkdir(exist_ok=True)
CLI_LOG.touch(exist_ok=True, mode=0o600)
CLI_LOG.chmod(0o600)


def sanitize(text):
    for value in private_values:
        if value:
            text = text.replace(value, '[REDACTED]')
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED_JWT]', text)
    text = re.sub(r'(?i)(authorization[\"\s:=]+(?:bearer\s+)?)[^\s,\"}]+', r'\1[REDACTED]', text)
    return text


def check(name, ok, details):
    checks.append({'name': name, 'passed': bool(ok), 'details': details})
    print(('PASS ' if ok else 'FAIL ') + name, flush=True)


def run(args, stdin=None, json_result=True):
    result = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(sanitize(result.stderr[-1600:] or result.stdout[-1600:]))
    if not json_result:
        return result.stdout.strip()
    # Login may prepend a password-stdin prompt, so locate the JSON payload.
    content = result.stdout.strip()
    if content and content[0] not in '[{':
        positions = [x for x in (content.find('{'), content.find('[')) if x >= 0]
        if positions:
            content = content[min(positions):]
    return json.loads(content)


def kube(resource):
    return run(['kubectl', '--context', CONTEXT, '-n', NAMESPACE, 'get', resource, '-o', 'json'])


def cli(*args, stdin=None):
    return run(['dpsctl', '--no-retry', '--grpc-timeout', '45s', *args], stdin=stdin)


def leaf_strings(value):
    if isinstance(value, dict):
        return [s for x in value.values() for s in leaf_strings(x)]
    if isinstance(value, list):
        return [s for x in value for s in leaf_strings(x)]
    return [value] if isinstance(value, str) else []


def status_ok(response):
    return isinstance(response, dict) and response.get('status', {}).get('ok') is True


def attempt(name, function):
    try:
        function()
    except Exception as error:
        check(name, False, {'error': sanitize(str(error))})


def helm_check():
    release = run(['helm', '--kube-context', CONTEXT, 'list', '-n', NAMESPACE, '-o', 'json'])
    selected = [x for x in release if x['name'] == SETTINGS['release']]
    details = [{k: x.get(k) for k in ('name', 'namespace', 'revision', 'status', 'chart', 'app_version')} for x in selected]
    check('helm-release-0.9.0', len(selected) == 1 and selected[0]['status'] == 'deployed' and selected[0]['app_version'] == '0.9.0', details)


def workload_check():
    stateful = kube('statefulsets')['items']
    deployments = kube('deployments')['items']
    names = {x['metadata']['name'] for x in stateful + deployments}
    expected = {(SETTINGS['fullname'] + '-server'), (SETTINGS['fullname'] + '-server-agent'), (SETTINGS['fullname'] + '-ui')}
    status = []
    for item in stateful + deployments:
        wanted = item['spec'].get('replicas', 1)
        ready = item.get('status', {}).get('readyReplicas', 0)
        status.append({'name': item['metadata']['name'], 'wanted': wanted, 'ready': ready})
    check('core-agent-ui-ready', expected.issubset(names) and all(x['wanted'] == x['ready'] for x in status), status)
    pods = kube('pods')['items']
    unexpected = [x['metadata']['name'] for x in pods if any(v in x['metadata']['name'] for v in ('postgres', 'ldap', 'zapp', 'power-steering', 'prs-'))]
    check('no-internal-postgresql-or-disabled-integrations', not unexpected, {'unexpected_pods': unexpected})
    claims = kube('persistentvolumeclaims')['items']
    details = [{'name': x['metadata']['name'], 'phase': x.get('status', {}).get('phase'), 'storage_class': x['spec'].get('storageClassName'), 'capacity': x.get('status', {}).get('capacity')} for x in claims]
    check('core-persistent-storage-bound', bool(claims) and all(x['phase'] == 'Bound' for x in details), details)


def login_check():
    result = cli('login', '--username', username, '--password-stdin', stdin=password + '\n')
    check('dpsctl-authenticated-login', status_ok(result), {'status_ok': status_ok(result), 'username': username, 'authentication': authenticator})
    if CREDENTIALS.exists():
        CREDENTIALS.chmod(0o600)
    check('credentials-file-private', CREDENTIALS.exists() and CREDENTIALS.stat().st_mode & 0o777 == 0o600, {'path': str(CREDENTIALS), 'mode': oct(CREDENTIALS.stat().st_mode & 0o777) if CREDENTIALS.exists() else 'missing'})


def version_check():
    result = cli('server-version')
    allowed = {'version', 'application', 'application_version', 'build_date', 'git_commit', 'go_version', 'commit', 'date'}
    details = {k: v for k, v in result.items() if k in allowed} if isinstance(result, dict) else {}
    check('server-client-release-match', any(re.search(r'\bv?0\.9\.0\b', v) for v in leaf_strings(result)), details)


def component_check():
    result = cli('verify', '--dps-server', '--database', '--auth')
    statuses = {k: {'healthy': v.get('healthy'), 'message': sanitize(str(v.get('message', '')))} for k, v in result.items() if isinstance(v, dict) and k != 'status'}
    check('server-database-auth-healthy', status_ok(result) and bool(statuses) and all(v['healthy'] is True for v in statuses.values()), statuses)


def ui_cli_check():
    result = cli('verify', '--ui')
    statuses = {k: {'healthy': v.get('healthy'), 'message': sanitize(str(v.get('message', '')))} for k, v in result.items() if isinstance(v, dict) and k != 'status'}
    check('dpsctl-ui-ingress-check', status_ok(result) and bool(statuses) and all(v['healthy'] is True for v in statuses.values()), statuses)


def agent_check():
    result = cli('agent', 'list')
    agents = result if isinstance(result, list) else result.get('agents', [])
    filtered = []
    for agent in agents:
        filtered.append({k: agent.get(k) for k in ('agent_id', 'configured', 'connected', 'assigned_devices') if k in agent})
        filtered[-1]['session_count'] = len(agent.get('sessions', []))
    check('agent-mtls-connected', any(x.get('agent_id') == SETTINGS['agent_id'] and x.get('connected') is True for x in agents), filtered)


def topology_check():
    result = cli('topology', 'list')
    tops = result if isinstance(result, list) else result.get('topologies', [])
    check('topology-list-readonly', True, {'count': len(tops), 'topologies': [{'name': t.get('topology_name', t.get('name')), 'active': t.get('is_active', t.get('isActive'))} for t in tops], 'import_performed_by_this_script': False})


def ui_http_check():
    context = ssl.create_default_context(cafile=str(CONFIG / 'tls/ca.crt'))
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(cookies))
    base = ('https://' + SETTINGS['ui_name'])
    def request(path, body=None, token=None, session=False):
        headers = {'Accept': 'application/json', 'X-Client-Id': 'dps-ui-v2', 'X-Client-Version': '0.9.0', 'Origin': base}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if session:
            headers['X-DPS-Session'] = '1'
        data = json.dumps(body).encode() if body is not None else None
        with opener.open(urllib.request.Request(base + path, data=data, headers=headers, method='POST' if body is not None or session else 'GET'), timeout=45) as response:
            return response.status, response.headers, response.read()
    code, _, body = request('/')
    check('ui-https-page', code == 200 and b'<html' in body.lower(), {'url': base, 'http_status': code, 'ca_verified': True})
    code, _, body = request('/config.json')
    runtime = json.loads(body)
    check('ui-runtime-same-origin-proxy', runtime.get('api', {}).get('basePath') == '/api' and runtime.get('auth', {}).get('provider') == 'dps', {'api': runtime.get('api'), 'auth_provider': runtime.get('auth', {}).get('provider')})
    token = None
    try:
        code, _, body = request('/api/session/login', {'username': username, 'password': password}, session=True)
        result = json.loads(body)
        token = result.get('accessToken')
        if token:
            private_values.append(token)
        check('ui-session-login', code == 200 and isinstance(token, str) and bool(token), {'http_status': code, 'access_token_present': bool(token), 'cookie_count': len(cookies)})
        if not token:
            return
        code, _, body = request('/api/nvidia.dcpower.v1.VersionService/GetVersion', {}, token=token)
        result = json.loads(body)
        check('ui-proxy-authenticated-version', code == 200 and any(re.search(r'\bv?0\.9\.0\b', x) for x in leaf_strings(result)), {'http_status': code, 'version': result.get('version', result.get('application'))})
        code, _, body = request('/api/nvidia.dcpower.v1.TopologyManagementService/ListTopologies', {}, token=token)
        result = json.loads(body)
        check('ui-proxy-authenticated-topologies', code == 200 and status_ok(result), {'http_status': code, 'status_ok': status_ok(result), 'topology_count': len(result.get('topologies', []))})
    finally:
        if token:
            code, _, _ = request('/api/session/logout', token=token, session=True)
            check('ui-session-logout', code in (200, 204), {'http_status': code})
        cookies.clear()


try:
    access = json.loads((CONFIG / 'dps-access.json').read_text())
    login = access.get('login', access)
    username = login['username']
    password = login['password']
    private_values.append(password)
    authenticator = yaml.safe_load((CONFIG / 'values.yaml').read_text())['dps']['auth']['authenticatorType']
except Exception as error:
    sys.exit('Cannot load private authentication inputs: ' + sanitize(str(error)))

for name, function in [
    ('helm-release-0.9.0', helm_check), ('workload-readiness', workload_check),
    ('dpsctl-authenticated-login', login_check), ('server-client-release-match', version_check),
    ('server-database-auth-healthy', component_check), ('dpsctl-ui-ingress-check', ui_cli_check),
    ('agent-mtls-connected', agent_check), ('topology-list-readonly', topology_check),
    ('ui-https-and-session', ui_http_check),
]:
    attempt(name, function)
if CLI_LOG.exists():
    # dpsctl owns this protected log; scrub any access tokens/password on completion.
    CLI_LOG.write_text(sanitize(CLI_LOG.read_text(errors='replace')))
    CLI_LOG.chmod(0o600)
report = {'timestamp': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
          'namespace': NAMESPACE, 'context': CONTEXT, 'release': SETTINGS['release'], 'expected_version': SETTINGS['dps_version'],
          'scope': 'installation checks only; no topology import/activation or hardware writes',
          'authentication': authenticator,
          'checks': checks, 'passed': all(x['passed'] for x in checks),
          'counts': {'passed': sum(x['passed'] for x in checks), 'total': len(checks)}}
REPORT.write_text(sanitize(json.dumps(report, ensure_ascii=False, indent=2)) + '\n')
REPORT.chmod(0o600)
print(json.dumps({'report': str(REPORT), 'passed': report['passed'], 'counts': report['counts']}))
sys.exit(0 if report['passed'] else 1)
