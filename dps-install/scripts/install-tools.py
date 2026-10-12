#!/usr/bin/env python3
"""Install official Helm/kubectl using SHA256/version checks and atomic replacement."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, json, subprocess, tarfile, shutil, tempfile, os

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--only", choices=("helm", "kubectl"), help="Install one missing tool; preserve the other tool")
args = parser.parse_args()
B = Path('/raid/vince/deploy')
P = B/'dps-install/packages/tools'
V = json.loads((B/'dps-install/config/kubernetes/tool-versions.json').read_text())
names = [args.only] if args.only else ['kubectl', 'helm']

def check_links():
    for name in names:
        target = P/'bin'/name
        link = Path('/usr/local/bin')/name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RuntimeError('Unexpected project binary path: '+str(target))
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if link.exists() or link.is_symlink():
            raise RuntimeError('Existing unrelated system binary; preserve and stop: '+str(link))

check_links()
P.mkdir(parents=True, exist_ok=True)
(P/'bin').mkdir(exist_ok=True)
urls = {}
if 'helm' in names:
    urls.update({
        'helm.tar.gz': f'https://get.helm.sh/helm-{V["helm"]}-linux-amd64.tar.gz',
        'helm.sha256sum': f'https://get.helm.sh/helm-{V["helm"]}-linux-amd64.tar.gz.sha256sum',
    })
if 'kubectl' in names:
    urls.update({
        'kubectl': f'https://dl.k8s.io/release/{V["kubectl"]}/bin/linux/amd64/kubectl',
        'kubectl.sha256': f'https://dl.k8s.io/release/{V["kubectl"]}/bin/linux/amd64/kubectl.sha256',
    })

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

with tempfile.TemporaryDirectory(prefix='.tool-stage-', dir=P) as tmp:
    stage = Path(tmp)
    def fetch(item):
        name, url = item
        if (P/name).is_file():
            shutil.copy2(P/name, stage/name)
        else:
            subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '15',
                            '--max-time', '180', '-sS', url, '-o', str(stage/name)], check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch, urls.items()))
    checks = {}
    if 'helm' in names:
        checks['helm'] = sha(stage/'helm.tar.gz') == (stage/'helm.sha256sum').read_text().split()[0]
    if 'kubectl' in names:
        checks['kubectl'] = sha(stage/'kubectl') == (stage/'kubectl.sha256').read_text().strip()
    if not all(checks.values()):
        raise RuntimeError('SHA256 mismatch; existing tools unchanged')
    bins = stage/'bin'
    bins.mkdir()
    if 'kubectl' in names:
        shutil.copy2(stage/'kubectl', bins/'kubectl')
    if 'helm' in names:
        with tarfile.open(stage/'helm.tar.gz') as archive:
            with archive.extractfile('linux-amd64/helm') as src, (bins/'helm').open('wb') as dst:
                shutil.copyfileobj(src, dst)
    for name in names:
        (bins/name).chmod(0o755)
    actual = {}
    if 'helm' in names:
        actual['helm'] = subprocess.check_output([str(bins/'helm'), 'version', '--template', '{{.Version}}'], text=True).strip()
    if 'kubectl' in names:
        actual['kubectl'] = json.loads(subprocess.check_output([str(bins/'kubectl'), 'version', '--client=true', '-o', 'json'], text=True))['clientVersion']['gitVersion']
    if any(actual[name] != V[name] for name in names):
        raise RuntimeError('CLI version mismatch; existing tools unchanged')
    check_links()
    for name in names:
        os.replace(bins/name, P/'bin'/name)
    for name in names:
        link = Path('/usr/local/bin')/name
        if not link.is_symlink():
            link.symlink_to(P/'bin'/name)
    for name in urls:
        os.replace(stage/name, P/name)
report = {
    'versions': V, 'actual_cli_versions': actual, 'sha256_verified': checks,
    'official_urls': urls, 'installed': {name:str(P/'bin'/name) for name in names},
    'atomic_replacement': True, 'kubernetes_distribution': 'Native K3s installed separately',
}
(B/'verification/reports/tool-installation.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(actual))
print('Helm/kubectl checksum/version checks passed; selected tools atomically installed. Native Kubernetes is installed separately.')
