#!/usr/bin/env python3
"""GET-only BMC verification from the actual DPS Agent Pod network namespace.

The host Python interpreter runs via nsenter --net only; no debug container,
Pod change, Kubernetes resource mutation, topology activation, or BMC write.
Private Secret values and CA material pass only through subprocess stdin.
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
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request

ROOT = CTX.runtime_root
SCRIPT = Path(__file__).resolve()
REPORT = ROOT / 'verification/reports/dps-pod-bmc-connectivity.json'
CONFIG = ROOT / 'dps-install/config'


def inside(payload):
    observed_net = os.readlink('/proc/self/ns/net')
    observed_mnt = os.readlink('/proc/self/ns/mnt')
    context = ssl.create_default_context(cadata=payload['ca'])
    basic = base64.b64encode((payload['credentials']['username'] + ':' + payload['credentials']['password']).encode()).decode()

    def verify(node):
        result = {'node_id': node['node_id'], 'rack_id': node['rack_id'], 'bmc_url': node['bmc_url'],
                  'passed': False, 'requests': 0, 'gpu_count': 0, 'cpu_count': 0, 'errors': []}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        def get(path):
            if not path.startswith('/redfish/v1'):
                raise ValueError('Unexpected non-Redfish path')
            with opener.open(urllib.request.Request(node['bmc_url'] + path, headers={
                'Authorization': 'Basic ' + basic, 'Accept': 'application/json'}), timeout=20) as response:
                result['requests'] += 1
                if response.status != 200:
                    raise ValueError('Unexpected HTTP status')
                return json.loads(response.read())
        try:
            root = get('/redfish/v1')
            if not root.get('@odata.type', '').startswith('#ServiceRoot.'):
                raise ValueError('Incorrect Redfish service root')
            systems = get(root['Systems']['@odata.id'])
            paths = [e['@odata.id'] for e in systems['Members']]
            system_path = '/redfish/v1/Systems/HGX_Baseboard_0'
            if system_path not in paths:
                raise ValueError('HGX ComputerSystem absent')
            computer = get(system_path)
            if not computer.get('@odata.type', '').startswith('#ComputerSystem.'):
                raise ValueError('Incorrect ComputerSystem type')
            if computer.get('Status', {}).get('Health') != 'OK':
                raise ValueError('HGX ComputerSystem health is not OK')
            result['fixture_model'] = computer.get('Model')
            processors = get(computer['Processors']['@odata.id'])
            inventory = []
            for member in processors['Members']:
                processor = get(member['@odata.id'])
                metrics = get(processor['EnvironmentMetrics']['@odata.id'])
                power = metrics.get('PowerWatts', {}).get('Reading')
                limits = metrics.get('PowerLimitWatts', {})
                setpoint = limits.get('SetPoint')
                if not isinstance(power, (int, float)) or not math.isfinite(power) or power < 0:
                    raise ValueError('Invalid read-only power telemetry')
                if not isinstance(setpoint, (int, float)) or not math.isfinite(setpoint):
                    raise ValueError('Invalid read-only power setpoint')
                inventory.append({'id': processor['Id'], 'type': processor.get('ProcessorType'),
                                  'power_watts': power, 'power_limit_setpoint_watts': setpoint})
            result['gpu_count'] = sum(p['type'] == 'GPU' for p in inventory)
            result['cpu_count'] = sum(p['type'] == 'CPU' for p in inventory)
            result['processors'] = inventory
            if result['gpu_count'] != 4 or result['cpu_count'] != 2:
                raise ValueError('Expected 4 GPUs and 2 CPUs')
            if {p['id'] for p in inventory} != {f'GPU_{i}' for i in range(4)} | {f'CPU_{i}' for i in range(2)}:
                raise ValueError('Unexpected processor IDs')
            result['passed'] = True
        except Exception as error:
            result['errors'].append(type(error).__name__ + ': ' + str(error))
        return result

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(verify, payload['nodes']))
    rack_counts = dict(Counter(n['rack_id'] for n in payload['nodes']))
    expected_racks = {f'gb300-rack-{r:02}': 18 for r in range(1, 5)}
    summary = {'timestamp': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
               'scope': 'Actual DPS Agent Pod network namespace -> direct BMC HTTPS GET only. This does not invoke DPS Core -> Agent -> BMC dispatch.',
               'execution': {'method': 'host nsenter --target sandbox_pid --net python3; host mount namespace retained',
                             'agent_pod': payload['pod_name'], 'agent_pod_uid': payload['pod_uid'],
                             'agent_sandbox_id': payload['sandbox_id'], 'sandbox_pid': payload['sandbox_pid'],
                             'expected_network_namespace': payload['netns'], 'observed_network_namespace': observed_net,
                             'host_mount_namespace': payload['host_mntns'], 'observed_mount_namespace': observed_mnt,
                             'namespace_match': observed_net == payload['netns'], 'host_mount_retained': observed_mnt == payload['host_mntns'],
                             'pod_spec_modified': False, 'ephemeral_containers_created': False},
               'tls_ca_verified': True, 'credentials_source': 'Kubernetes Secret '+payload['namespace']+'/bmc-shared-secret key bmc',
               'ca_source': 'Kubernetes Secret '+payload['namespace']+'/dps-bmc-ca key ca.crt', 'http_methods': ['GET'],
               'mutating_requests_sent': False, 'node_count': len(results),
               'unique_endpoints': len({n['bmc_url'] for n in payload['nodes']}), 'rack_counts': rack_counts,
               'passed_nodes': sum(n['passed'] for n in results), 'failed_nodes': sum(not n['passed'] for n in results),
               'gpu_count': sum(n['gpu_count'] for n in results), 'cpu_count': sum(n['cpu_count'] for n in results),
               'request_count': sum(n['requests'] for n in results),
               'topology_active': False, 'dps_core_agent_bmc_dispatch_tested': False,
               'limitations': ['The simulator accepts credentials but does not enforce authentication; this verifies credentials are supplied, not real access restriction.',
                              'Shared upstream GB300 fixture model text can say GB200 NVL. Endpoint identities use the configured unique ports and mapping; repeated fixture IDs/serials are not distinct physical hardware.',
                              'Inactive-topology DPS connection/health dispatch is not claimed as passed. This independent test only establishes actual Agent Pod network reachability and CA-verified Redfish inventory/telemetry GETs.'],
               'nodes': results}
    summary['passed'] = (observed_net == payload['netns'] and observed_mnt == payload['host_mntns']
                         and len(results) == 72 and summary['unique_endpoints'] == 72
                         and rack_counts == expected_racks and summary['failed_nodes'] == 0
                         and summary['gpu_count'] == 288 and summary['cpu_count'] == 144)
    return summary


if '--inside' in sys.argv:
    print(json.dumps(inside(json.load(sys.stdin))))
    sys.exit(0)

os.umask(0o077)
os.environ['KUBECONFIG'] = str(CONFIG / 'kubernetes/kubeconfig.yaml')
base = ['kubectl', '--context', SETTINGS['kube_context'], '-n', SETTINGS['namespace']]
def read_json(args):
    return json.loads(subprocess.check_output(args, text=True))
pods = read_json(base + ['get', 'pods', '-l', ('app=' + SETTINGS['fullname'] + '-server-agent'), '-o', 'json'])['items']
if len(pods) != 1:
    raise RuntimeError('Expected one DPS Agent Pod')
pod = pods[0]
cri_config = ROOT / 'dps-install/data/kubernetes/k3s/agent/etc/crictl.yaml'
cri = ['k3s', 'crictl', '--config', str(cri_config)]
sandboxes = read_json(cri + ['pods', '-o', 'json'])['items']
selected = [s for s in sandboxes if s['metadata']['name'] == pod['metadata']['name'] and s['metadata']['namespace'] == SETTINGS['namespace']]
if len(selected) != 1:
    raise RuntimeError('Expected exactly one Agent sandbox')
sandbox = selected[0]
inspection = read_json(cri + ['inspectp', sandbox['id']])
pid = inspection['info']['pid']
secret = read_json(base + ['get', 'secret', 'bmc-shared-secret', '-o', 'json'])
ca = read_json(base + ['get', 'secret', 'dps-bmc-ca', '-o', 'json'])
payload = {'namespace': SETTINGS['namespace'], 'nodes': json.loads((ROOT / 'hardware-sim/runtime/nodes.json').read_text()),
           'credentials': json.loads(base64.b64decode(secret['data']['bmc'])),
           'ca': base64.b64decode(ca['data']['ca.crt']).decode(),
           'pod_name': pod['metadata']['name'], 'pod_uid': pod['metadata']['uid'],
           'sandbox_id': sandbox['id'], 'sandbox_pid': pid,
           'netns': os.readlink(f'/proc/{pid}/ns/net'), 'host_mntns': os.readlink('/proc/self/ns/mnt')}
result = subprocess.run(['nsenter', '--target', str(pid), '--net', sys.executable, str(SCRIPT), '--inside'],
                        input=json.dumps(payload), text=True, capture_output=True, timeout=180)
if result.returncode:
    raise RuntimeError('Namespace verification failed; no credential-bearing input was logged')
report = json.loads(result.stdout)
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
REPORT.chmod(0o600)
print(json.dumps({k: report[k] for k in ('passed', 'node_count', 'unique_endpoints', 'rack_counts', 'passed_nodes', 'failed_nodes', 'gpu_count', 'cpu_count', 'request_count')}))
print('Report:', REPORT)
sys.exit(0 if report['passed'] else 1)
