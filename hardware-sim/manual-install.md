# 手工启动 4 rack GB300 BMC 模拟器

SDK 仅提供 BMC 模拟，不安装 DPS。使用固定 0.9 simulator 镜像和公开节点/拓扑模板，无需 SDK checkout 或 vendor。先按 [主机/下载步骤](../dps-install/manual-prerequisites.md) 准备 Docker、镜像和环境变量。以下是新实例原生命令；已有 TLS、凭据、runtime 配置时直接使用，不重新生成。

## 1. 下载固定镜像，准备目录与密码

~~~bash
sim="$DPS_RUNTIME_ROOT/hardware-sim/runtime"
config="$DPS_RUNTIME_ROOT/dps-install/config"
test ! -e "$sim/authority/ca.key"
test ! -e "$config/bmc-credentials.json"
mkdir -p "$sim/authority" "$sim/tls" "$config"
chmod 700 "$sim/authority" "$config"
docker pull --platform linux/amd64 \
  nvcr.io/nvidia/dps-bmc-simulator@sha256:3f81152ee055b95e0bda512227cd6ecbb4813f97dad0c654477a4afbf8caff7e
docker pull --platform linux/amd64 \
  nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
openssl rand -hex 36 | tr -d '\n' > "$config/bmc.password"
chmod 600 "$config/bmc.password"
~~~

这份密码供 DPS Secret 与访问清单使用。模拟器不强制认证，因此不能拿 GET 成功证明真实 BMC 密码认证。Docker 镜像 digest 校验步骤见上述下载文档。

## 2. 为外部 72 个 HTTPS 入口签发证书

~~~bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$sim/authority/ca.key"
openssl req -new -x509 -sha256 -days 3650 -key "$sim/authority/ca.key" \
  -out "$sim/authority/ca.crt" -subj "/CN=DPS BMC Simulator CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$sim/tls/tls.key"
openssl req -new -key "$sim/tls/tls.key" -out "$sim/tls/tls.csr" -subj "/CN=simulator"
cat > "$sim/tls/tls.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$DPS_HOST_IP,IP:127.0.0.1,DNS:simulator,DNS:$DPS_HOST_NAME
EOF
openssl x509 -req -in "$sim/tls/tls.csr" -CA "$sim/authority/ca.crt" \
  -CAkey "$sim/authority/ca.key" -CAcreateserial -sha256 -days 825 \
  -extfile "$sim/tls/tls.ext" -out "$sim/tls/tls.crt"
cp "$sim/authority/ca.crt" "$sim/tls/ca.crt"
cp "$sim/authority/ca.crt" "$config/simulator-ca.crt"
chmod 755 "$sim/tls"
chmod 600 "$sim/authority/ca.key" "$sim/tls/tls.key"
chmod 644 "$sim/authority/ca.crt" "$sim/tls/"*.crt "$config/simulator-ca.crt"
openssl verify -CAfile "$config/simulator-ca.crt" -verify_ip "$DPS_HOST_IP" "$sim/tls/tls.crt"
~~~

nginx 挂载 leaf cert/key，CA 签名私钥不挂容器。SDK mock 的 ssl 设置会自行生成 backend 私有证书；不把项目 leaf/key 挂 mock。私有 Docker backend 使用 proxy_ssl_verify off；DPS/宿主机访问外部 72 入口均严格验证项目 CA 与 IP/SAN。这是两段不同的 TLS 信任范围。

## 3. 渲染 72 个节点与 DPS 0.9 拓扑

下面内联代码只转换公开 JSON 模板和生成访问清单，全部内容可审阅；没有调用 SDK 安装任务或自编部署入口。拓扑 AgentId 放在 Topology.Entities 的关系对象中。

~~~bash
python3 - <<'PY'
import os,json,csv
from pathlib import Path
source=Path(os.environ["DPS_SOURCE_ROOT"]); root=Path(os.environ["DPS_RUNTIME_ROOT"])
sim=root/"hardware-sim/runtime"; c=root/"dps-install/config"
nodes=json.loads((source/"hardware-sim/templates/nodes.json").read_text())
topology=json.loads((source/"dps-install/config/topology-4rack-dps09.json").read_text())
assert len(nodes)==72 and not topology.get("Policies")
for i,n in enumerate(nodes):
 n["port"]=int(os.environ["DPS_BMC_START_PORT"])+i
 n["bmc_url"]=f'https://{os.environ["DPS_HOST_IP"]}:{n["port"]}'
 n["secret_name"]="bmc-shared-secret"
by_name={n["node_id"]:n for n in nodes}
for e in topology["Entities"]:
 if e["Type"]=="ComputerSystem":
  e["Redfish"]={"URL":by_name[e["Name"]]["bmc_url"],"SecretName":"bmc-shared-secret"}
topology["Topology"]["Name"]=os.environ["DPS_TOPOLOGY_NAME"]
for e in topology["Topology"]["Entities"]:
 if e["Name"] in by_name: e["AgentId"]=os.environ["DPS_AGENT_ID"]
(sim/"nodes.json").write_text(json.dumps(nodes,indent=2)+"\n")
(c/"topology-4rack-dps09.json").write_text(json.dumps(topology,indent=2)+"\n")
cred={"username":"admin","password":(c/"bmc.password").read_text()}
(c/"bmc-credentials.json").write_text(json.dumps(cred,indent=2)+"\n")
(c/"bmc-credentials.json").chmod(0o600)
with (c/"bmc-endpoints.csv").open("w",newline="") as f:
 w=csv.DictWriter(f,fieldnames=["rack_id","node_id","bmc_url","redfish_system_url","username","password"])
 w.writeheader()
 for n in nodes:
  w.writerow({k:n[k] for k in ["rack_id","node_id","bmc_url"]}|
   {"redfish_system_url":n["bmc_url"]+"/redfish/v1/Systems/HGX_Baseboard_0"}|cred)
(c/"bmc-endpoints.csv").chmod(0o600)
mock={"port":8443,"default_dir":"/app/mockups/gb300",
 "dirs":{n["node_id"]:"/app/mockups/gb300" for n in nodes},
 "ssl":True,"debug":False,"host":"0.0.0.0",
 "update_workload_power_profile_delay":"25s","metrics":{"plugin":"synthetic"}}
(sim/"config.yaml").write_text(json.dumps(mock,indent=2)+"\n")
(sim/"config.yaml").chmod(0o644)
print("Prepared: 4 racks / 72 unique nodes / 72 AgentId relations")
PY
~~~

默认范围 18443–18514；以 deployment.yaml 的 bmc_start_port 为准。110 个实体中有 72 ComputerSystem、32 PowerSupply、4 PDU、2 PowerDomain，GPU/CPU 通过每个节点 Redfish 暴露。安装必要 JSON/Secret/访问清单留 runtime config；验证报告不作为启动输入。

## 4. 明确配置 nginx 与 Compose

~~~bash
cat > "$sim/nginx.conf" <<'EOF'
worker_processes 2;
error_log /dev/stderr warn;
pid /var/run/nginx.pid;
events { worker_connections 4096; }
http {
access_log /dev/stdout;
upstream gb300_backend { server simulator:8443; keepalive 256; }
ssl_certificate /etc/bmc-tls/tls.crt;
ssl_certificate_key /etc/bmc-tls/tls.key;
ssl_protocols TLSv1.2 TLSv1.3;
EOF
jq -r '.[] | [.port,.node_id] | @tsv' "$sim/nodes.json" |
while IFS="$(printf '\t')" read -r port node; do
  cat >> "$sim/nginx.conf" <<EOF
server {
  listen $port ssl;
  server_name $node;
  location / {
    proxy_pass https://gb300_backend;
    proxy_set_header Host $node;
    proxy_set_header X-Forwarded-Host $node;
    proxy_set_header Connection "";
    proxy_http_version 1.1;
    proxy_ssl_verify off;
    proxy_read_timeout 60s;
  }
}
EOF
done
printf '}\n' >> "$sim/nginx.conf"
bmc_last_port=$((DPS_BMC_START_PORT+71))
cat > "$sim/compose.yaml" <<EOF
services:
  simulator:
    image: nvcr.io/nvidia/dps-bmc-simulator@sha256:3f81152ee055b95e0bda512227cd6ecbb4813f97dad0c654477a4afbf8caff7e
    container_name: $DPS_BMC_CONTAINER
    restart: unless-stopped
    command: [-c, /app/config.yaml, -d, /app/mockups/gb300, --host, 0.0.0.0, --port, "8443", --max-active-requests=4096, --power-snapshot-interval=5s]
    volumes: ["$sim/config.yaml:/app/config.yaml:ro"]
    networks: [bmc]
    cpus: 4
    mem_limit: 6g
    logging:
      driver: json-file
      options: {max-size: "20m", max-file: "3"}
  proxy:
    image: nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
    container_name: $DPS_PROXY_CONTAINER
    restart: unless-stopped
    depends_on: [simulator]
    entrypoint: [nginx, -g, "daemon off;"]
    volumes:
      - $sim/nginx.conf:/etc/nginx/nginx.conf:ro
      - $sim/tls:/etc/bmc-tls:ro
    ports: ["$DPS_HOST_IP:$DPS_BMC_START_PORT-$bmc_last_port:$DPS_BMC_START_PORT-$bmc_last_port"]
    networks: [bmc]
    cpus: 2
    mem_limit: 512m
    logging:
      driver: json-file
      options: {max-size: "20m", max-file: "3"}
    healthcheck:
      test: [CMD, wget, -q, --no-check-certificate, -O, /dev/null, "https://127.0.0.1:$DPS_BMC_START_PORT/readyz"]
      interval: 15s
      timeout: 5s
      retries: 3
networks:
  bmc:
    name: $DPS_BMC_NETWORK
EOF
docker compose -p "$DPS_BMC_PROJECT" -f "$sim/compose.yaml" config --quiet
docker compose -p "$DPS_BMC_PROJECT" -f "$sim/compose.yaml" up -d --wait
docker exec "$DPS_PROXY_CONTAINER" nginx -t
docker exec "$DPS_PROXY_CONTAINER" nginx -s reload
docker compose -p "$DPS_BMC_PROJECT" -f "$sim/compose.yaml" ps
~~~

SDK backend 默认非 root 用户运行，只读取 644 config，不需要在镜像内运行 shell/id。proxy 本地 liveness 使用自签 endpoint 的简单检查；这不代替下一节严格 CA 验证。

## 5. 只读检查与 DPS 接入

~~~bash
curl --fail --silent --show-error --cacert "$config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
curl --fail --silent --show-error --cacert "$config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/redfish/v1/Systems/HGX_Baseboard_0" |
  jq '{Id,Status,Processors}'
while read -r url; do
  curl --fail --silent --show-error --cacert "$config/simulator-ca.crt" \
    "$url/readyz" > /dev/null
  curl --fail --silent --show-error --cacert "$config/simulator-ca.crt" \
    "$url/redfish/v1/Systems/HGX_Baseboard_0" > /dev/null
done < <(jq -r '.[].bmc_url' "$sim/nodes.json")
~~~

预期 72 个唯一入口均严格 CA 验证成功，每个节点有 4 GPU、2 CPU；完整库存/功率/健康检查见 [verification](../verification/README.md)。fixture 中固定型号/UUID 标签与模拟器不强制认证的限制见 [bmc-access.md](bmc-access.md)。

DPS 接入时创建 bmc-shared-secret 与 dps-bmc-ca，注册 33kW/95% PowerSupply 类型、验证/导入拓扑，步骤见 [DPS 手工安装](../dps-install/manual-install.md)。默认 inactive，不发送 BMC PATCH。宿主机或 Agent Pod GET 通过不代表 Core→Agent 派发/动态功率控制已经验证。
