# 手工安装 DPS 0.9、LDAP 认证与 PRS

先准备 [Kubernetes/工具与包](manual-prerequisites.md)，按需要用脚本或手工方式部署 [4 rack BMC](../hardware-sim/manual-install.md)、[独立 PG](manual-postgresql.md)、[独立 LDAP](manual-ldap.md)；已有服务直接对接。本页安装新的 namespace/release；已有实例使用原身份、原 values 和数据，不能重播“首次生成”。

配置依据是实际 0.9 chart 与 [NVIDIA 部署文档](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html)。DPS 由下面明确的 Helm 命令安装，SDK 不参与部署。

## 脚本路线在本页做什么

整套 Lab 脚本与只安装 DPS 的简短入口均在 [installstep.md](../installstep.md)。下面说明各自实际执行范围；后续章节保留完整的 openssl、kubectl、Helm 和 dpsctl 展开步骤。

| 脚本/阶段 | 实际动作和产物 | 对应正文 |
| --- | --- | --- |
| prepare-dps-fresh.py | 根据已生成的 PG/BMC/LDAP 输入创建或复用 DPS CA/Core/Agent/UI leaf、持久 JWT、S3/Controller 凭据和 Secret YAML；渲染 Lab values | 第 1–4 节 |
| install-from-zero.py 完整模式 | 创建/核对归属 namespace，apply 13 个外部 Secret；解析 chart 镜像并核对固定 digest，导入本机 K3s containerd，直接执行 Helm upgrade --install | 第 3–5 节 |
| 同一完整入口 | 使用真实 LDAP 账号通过 stdin 登录；注册电源类型，首次导入 inactive 四 rack 拓扑，核对/更新 Agent 路由，写 PRS=true/-15/5 | 第 6–8 节 |
| prepare-namespace.sh | 写入前核对域名、namespace 读取权限及既有 Secret 数据/类型；冲突则拒绝 apply，不隐式更换保留身份 | 第 3 节 |
| install-dps.sh | 已完成 Lab 前置、values/Secret/镜像准备时，核对 chart SHA、K3s/node、LDAP 和 PRS 配置后仅执行 Helm upgrade --install | 第 5 节 |
| dps-login.sh / register-devices.sh / update-topology.sh | 单独的 Lab 登录/设备注册/安全路由更新入口；不意味着已经完成整套安装 | 第 6–8 节 |

prepare-namespace.sh 的保护针对脚本 apply；手工 kubectl 步骤由用户明确管理创建或身份变更，脚本不会接管这类变更。

整套脚本固定启用 PRS 和独立 Lab PG/LDAP/模拟器。prepare-only 生成输入，尚未 apply Secret 或执行 Helm；安装脚本本身不会自动运行 verification 全栈验收。install-dps.sh 不创建密码/证书/namespace Secret，不安装 PG、LDAP 或 BMC，也不执行后续登录/拓扑/PRS 开关；它仍按本机原生 K3s + LDAP + Lab PRS 库名校验，不能作为任意客户环境的通用 Helm 包装。

重复执行只有在同一 bootstrap 配置、路径和归属保持一致时复用身份/数据；手工创建或其他安装归属的 namespace/身份不由 fresh 链接管。客户使用真实硬件、自选 PG/IdP 或 Kubernetes 方案时，使用 [已有基础设施对接](existing-infrastructure.md) 的原生 Helm 和条件性 Secret。整套脚本保持拓扑 inactive，不创建 ResourceGroup 或执行 BMC 功率 PATCH；动态闭环与额外验收另行选择。

## 分组件安装后如何进入本页

如果 BMC/PG/LDAP 已通过各自一键入口或完整手工步骤安装完成，保留它们的既有密码、CA、证书与数据，直接使用 runtime 中已有的连接输入和 Secret YAML；不要回到这些组件的手册重新生成身份。若其中某项是客户已有服务，则按 [对接指南](existing-infrastructure.md) 使用其真实连接信息。

本页第 1–2 节只准备尚缺的 DPS 自身 TLS/JWT 与所选 PRS 输入；第 3–4 节负责目标 namespace 内 Secret 和 values。组件脚本的 Secret YAML 只是落盘文件，须核对 namespace、名称/key、CA/凭据与实际 values 一致，再创建/应用或引用已有 Secret。完成后第 5 节的 Helm 原生命令和 install-dps.sh 二选一，第 6–8 节完成客户端登录与实际所需登记。使用全量 install-from-zero 且已经成功时这些安装动作都完成，直接进入根 [installstep.md 第 9 节](../installstep.md) 的只读检查。

## 1. 新建 DPS CA、server/agent/ingress 证书和 JWT

~~~bash
config="$DPS_RUNTIME_ROOT/dps-install/config"
tls="$config/tls"
mkdir -p "$tls" "$config/prs" "$config/dpsctl" "$DPS_RUNTIME_ROOT/verification/logs"
chmod 700 "$tls" "$config/prs" "$config/dpsctl"
test ! -e "$tls/jwt-private-key.pem"
test ! -e "$tls/ca.key"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$tls/ca.key"
openssl req -new -x509 -sha256 -days 3650 -key "$tls/ca.key" \
  -out "$tls/ca.crt" -subj "/CN=DPS Lab CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
for name in server agent ingress; do
  case "$name" in
    server)
      cn="$DPS_FULLNAME-server-grpc"; usage=serverAuth
      sans="DNS:$DPS_API_NAME,DNS:$DPS_FULLNAME-server-grpc,DNS:$DPS_FULLNAME-server-grpc.$DPS_NAMESPACE,DNS:$DPS_FULLNAME-server-grpc.$DPS_NAMESPACE.svc,DNS:$DPS_FULLNAME-server-grpc.$DPS_NAMESPACE.svc.cluster.local,IP:$DPS_HOST_IP" ;;
    agent)
      cn="$DPS_AGENT_ID"; usage=clientAuth; sans="DNS:$DPS_AGENT_ID" ;;
    ingress)
      cn="$DPS_UI_NAME"; usage=serverAuth
      sans="DNS:$DPS_UI_NAME,DNS:$DPS_API_NAME,IP:$DPS_HOST_IP" ;;
  esac
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$tls/$name.key"
  openssl req -new -key "$tls/$name.key" -out "$tls/$name.csr" -subj "/CN=$cn"
  cat > "$tls/$name.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=$usage
subjectAltName=$sans
EOF
  openssl x509 -req -in "$tls/$name.csr" -CA "$tls/ca.crt" -CAkey "$tls/ca.key" \
    -CAcreateserial -sha256 -days 825 -extfile "$tls/$name.ext" -out "$tls/$name.crt"
done
openssl genrsa -out "$tls/jwt-private-key.pem" 3072
openssl pkey -in "$tls/jwt-private-key.pem" -check -noout
chmod 600 "$tls/"*.key "$tls/jwt-private-key.pem"
chmod 644 "$tls/"*.crt
openssl verify -CAfile "$tls/ca.crt" -purpose sslserver \
  -verify_hostname "$DPS_API_NAME" "$tls/server.crt"
openssl verify -CAfile "$tls/ca.crt" -purpose sslclient "$tls/agent.crt"
~~~

server 是 API/Core CA 信任；Agent client CN 必须等于 agent_id。UI ingress leaf 覆盖 UI/API 域名。JWT RSA 签名身份持续保留，普通维护不重新生成；本流程直接安装 LDAP，不经过历史 alwaysAllow 迁移。

## 2. 创建 PRS S3 和 Controller 凭据文件

这里只生成 JSON 输入，无服务写入。SeaweedFS S3 使用随机 access/secret key；Controller 复用 LDAP dps-lab 密码。

~~~bash
test ! -e "$config/prs/s3-credentials.json"
openssl rand -hex 18 | tr -d '\n' > "$config/prs/s3-access-key"
openssl rand -hex 40 | tr -d '\n' > "$config/prs/s3-secret-key"
python3 - <<'PY'
import json,os
from pathlib import Path
c=Path(os.environ["DPS_RUNTIME_ROOT"])/"dps-install/config"; p=c/"prs"
key=(p/"s3-access-key").read_text(); password=(p/"s3-secret-key").read_text()
(p/"s3-credentials.json").write_text(json.dumps({
 "bucket":"dps-prs","secret_name":"dps-prs-s3",
 "admin_access_key_id":key,"admin_secret_access_key":password},indent=2)+"\n")
(p/"seaweedfs-s3.json").write_text(json.dumps({"identities":[{
 "name":"dps-prs","credentials":[{"accessKey":key,"secretKey":password}],
 "actions":["Admin","Read","Write"]}]})+"\n")
a=json.loads((c/"dps-access.json").read_text())
(p/"ldap-credentials.json").write_text(json.dumps({"username":a["username"],"password":a["password"]})+"\n")
for q in p.iterdir():
 if q.is_file(): q.chmod(0o600)
PY
~~~

S3 凭据只在私密文件/Secret 中。bucket dps-prs、anonymousRead=false、S3 服务仅 ClusterIP；不创建公网 Ingress。

## 3. 原生 kubectl 创建 namespace 与 13 个外部 Secret

先确认目标 namespace/release 未被其他安装占用。新 namespace 创建一次；已有自己所属 namespace 可复用。以下 --from-file 避免密码进入命令参数，输出 YAML 保存在 runtime 且为 600。

~~~bash
kubectl create namespace "$DPS_NAMESPACE"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-postgresql \
  --from-file="password=$config/postgresql/secrets/dps-password" \
  --from-file="database-password=$config/postgresql/secrets/dps-password" \
  --dry-run=client -o yaml > "$config/postgresql-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-postgresql-ca \
  --from-file="ca.crt=$config/postgresql-ca.crt" \
  --dry-run=client -o yaml > "$config/postgresql-ca-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic bmc-shared-secret \
  --from-file="bmc=$config/bmc-credentials.json" \
  --dry-run=client -o yaml > "$config/bmc-shared-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-bmc-ca \
  --from-file="ca.crt=$config/simulator-ca.crt" \
  --dry-run=client -o yaml > "$config/bmc-ca-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-ldap-bind \
  --from-file="bind-password=$config/ldap/bind.password" \
  --dry-run=client -o yaml > "$config/ldap/dps-ldap-bind-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-ldap-ca \
  --from-file="ca.crt=$config/ldap/tls/ca.crt" \
  --dry-run=client -o yaml > "$config/ldap/dps-ldap-ca-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-ldap-client-tls \
  --from-file="ca.crt=$config/ldap/tls/ca.crt" \
  --from-file="tls.crt=$config/ldap/dps-client.crt" \
  --from-file="tls.key=$config/ldap/dps-client.key" \
  --dry-run=client -o yaml > "$config/ldap/dps-ldap-client-tls-secret.yaml"
for identity in server agent ingress; do
  kubectl -n "$DPS_NAMESPACE" create secret generic "dps-$identity-tls" \
    --from-file="ca.crt=$tls/ca.crt" --from-file="tls.crt=$tls/$identity.crt" \
    --from-file="tls.key=$tls/$identity.key" \
    --dry-run=client -o yaml > "$tls/dps-$identity-tls-secret.yaml"
done
kubectl -n "$DPS_NAMESPACE" create secret generic dps-jwt-keys \
  --from-file="private-key.pem=$tls/jwt-private-key.pem" \
  --dry-run=client -o yaml > "$tls/dps-jwt-keys-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-prs-s3 \
  --from-file="admin_access_key_id=$config/prs/s3-access-key" \
  --from-file="admin_secret_access_key=$config/prs/s3-secret-key" \
  --from-file="seaweedfs_s3_config=$config/prs/seaweedfs-s3.json" \
  --dry-run=client -o yaml > "$config/prs/s3-secret.yaml"
kubectl -n "$DPS_NAMESPACE" create secret generic dps-prs-dps-auth \
  --from-file="ldap-credentials=$config/prs/ldap-credentials.json" \
  --dry-run=client -o yaml > "$config/prs/dps-auth-secret.yaml"

for file in "$config/postgresql-secret.yaml" "$config/postgresql-ca-secret.yaml" \
  "$config/bmc-shared-secret.yaml" "$config/bmc-ca-secret.yaml" \
  "$config/ldap/dps-ldap-bind-secret.yaml" "$config/ldap/dps-ldap-ca-secret.yaml" \
  "$config/ldap/dps-ldap-client-tls-secret.yaml" "$tls/dps-server-tls-secret.yaml" \
  "$tls/dps-agent-tls-secret.yaml" "$tls/dps-ingress-tls-secret.yaml" \
  "$tls/dps-jwt-keys-secret.yaml" "$config/prs/s3-secret.yaml" "$config/prs/dps-auth-secret.yaml"; do
  chmod 600 "$file"
  kubectl apply -f "$file"
done
kubectl -n "$DPS_NAMESPACE" label secret bmc-shared-secret \
  app.kubernetes.io/component=bmc-credentials --overwrite
kubectl -n "$DPS_NAMESPACE" get secret
~~~

预期 13 个外部 Secret；不要 kubectl get secret -o yaml 输出其值。PG password/database-password 两键均为非 superuser 应用用户 dps 的密码，postgres 管理密码只用于独立 PG 初始化。

## 4. 从公开模板明确渲染 values

公开 [values.example.yaml](config/values.example.yaml) 包含真实 0.9 chart 配置块，不包含密码。以下仅替换 deployment.yaml 导出的主机/服务参数，并明确设置 PG/LDAP TLS、PRS 服务名与 NetworkPolicy。生成 values 留 runtime；不编辑公开模板为 live secret/config。

先从实际 Docker 网络取得 PG bridge IP，避免只猜测 DNAT 目标地址：

~~~bash
export DPS_PG_BRIDGE_IP=$(
  docker inspect "$DPS_PG_CONTAINER" |
    jq -r --arg network "$DPS_PG_NETWORK" '.[0].NetworkSettings.Networks[$network].IPAddress'
)
test -n "$DPS_PG_BRIDGE_IP"
python3 - <<'PY'
import os,copy,yaml
from pathlib import Path
e=os.environ; c=Path(e["DPS_RUNTIME_ROOT"])/"dps-install/config"
v=yaml.safe_load((Path(e["DPS_SOURCE_ROOT"])/"dps-install/config/values.example.yaml").read_text())
full=e["DPS_FULLNAME"]; ns=e["DPS_NAMESPACE"]; release=e["DPS_RELEASE"]
v["fullnameOverride"]=full
v["global"]["postgresql"]["host"]=e["DPS_HOST_IP"]
v["global"]["postgresql"]["service"]["ports"]["postgresql"]=e["DPS_PG_PORT"]
v["global"]["postgresql"]["sslMode"]="verify-full"
v["postgresql"]["enabled"]=False
v["power-steering"]["postgresql"]["enabled"]=False
v["dps"]["ingress"]["hostname"]=e["DPS_API_NAME"]
v["ui"]["ingress"]["hostname"]=e["DPS_UI_NAME"]
v["ui"]["ingress"]["tls"][0]["hosts"]=[e["DPS_UI_NAME"]]
v["ui"]["api"]["hostname"]=f"{full}-server-http.{ns}.svc.cluster.local"
v["dps"]["cors"]["allowedOrigins"]="https://"+e["DPS_UI_NAME"]
v["dps"]["auth"]["authenticatorType"]="ldap"
v["dps"]["auth"]["oidc"]["enabled"]=False
v["dps"]["ldap"]["serverUrl"]=f'ldaps://{e["DPS_HOST_IP"]}:{e["DPS_LDAP_PORT"]}'
v["agent"]["agentID"]=e["DPS_AGENT_ID"]
v["dps"]["grpcServiceMTLSCN"]["nvidia.dcpower.v1.DPSAgentService"]=[e["DPS_AGENT_ID"]]
power=v["power-steering"]
power["enabled"]=True
power["controller"]["cluster"]["dps"]["host"]=full+"-server-grpc"
power["config"]["fullnameOverride"]=release+"-power-config"
power["controller"]["fullnameOverride"]=release+"-power-controller"
v["dps"]["prs"]["enabled"]=True
v["dps"]["prs"]["hostPort"]=f"http://{release}-power-config.{ns}.svc.cluster.local:8000"
v["dps"]["prs"]["controllerHostPort"]=f"http://{release}-power-controller.{ns}.svc.cluster.local:8001"
egress=[{"to":[{"ipBlock":{"cidr":e["DPS_HOST_IP"]+"/32"}}],
         "ports":[{"port":int(e["DPS_PG_PORT"]),"protocol":"TCP"}]},
        {"to":[{"ipBlock":{"cidr":e["DPS_PG_BRIDGE_IP"]+"/32"}}],
         "ports":[{"port":5432,"protocol":"TCP"}]}]
power["config"]["extraEgressRules"]=copy.deepcopy(egress)
power["controller"]["extraEgressRules"]=copy.deepcopy(egress)+[
 {"to":[{"ipBlock":{"cidr":e["DPS_HOST_IP"]+"/32"}}],
  "ports":[{"port":int(e["DPS_KUBE_API_PORT"]),"protocol":"TCP"}]}]
(c/"values.yaml").write_text(yaml.safe_dump(v,sort_keys=False))
(c/"values.yaml").chmod(0o600)
PY
~~~

人工审阅 values 的下列有效配置；密码仍来自 Secret：

| 连接/组件 | 必需配置 |
| --- | --- |
| PostgreSQL | global.postgresql 指向独立 PG，verify-full，dps-postgresql / dps-postgresql-ca；两个内建 PG enabled=false |
| LDAP | enabled=true；只读 bind；groupOfNames/member 查询；dcpower-users=admin；defaultRole 为空；CA/client cert/key projected 挂载 |
| BMC | metrics.source=bmc；session；bmc-shared-secret；dps-bmc-ca；insecureSkipVerify=false；Zapp disabled |
| DPS/Agent | server TLS；Agent mTLS；CN=agent_id；固定 JWT Secret；UI HTTPS/CORS |
| PRS | 两层 enabled=true；2.1.0；3 个独立 PG 库；两 Pod PGSSLMODE=verify-full / PGSSLROOTCERT |
| Controller | dps-prs-dps-auth LDAP 凭据；严格 DPS CA；API 访问读取自身 Secret |
| SeaweedFS | 4.18；dps-prs bucket；匿名读关闭；PVC 1Gi/1Gi/10Gi，logs emptyDir |

## 5. 检查域名归属、渲染 chart、手动 Helm 安装

API/UI 域名已被另一 namespace/release 路由占用时必须换 deployment.yaml 中域名，不能抢占现有路由。清点普通 Ingress、Traefik HTTP 路由与 TCP HostSNI 路由；本 Lab 的 API TLS passthrough 使用 IngressRouteTCP。原生只读清点：

~~~bash
kubectl get ingress -A -o json |
  jq -r '.items[] | [.metadata.namespace,.metadata.name,
    ([.spec.rules[]?.host]|join(","))] | @tsv'
traefik_resources=$(kubectl api-resources --api-group=traefik.io -o name)
for route_resource in ingressroutes.traefik.io ingressroutetcps.traefik.io; do
  if printf '%s\n' "$traefik_resources" | grep -Fxq "$route_resource"; then
    kubectl get "$route_resource" -A -o json |
      jq -r '.items[] | [.kind,.metadata.namespace,.metadata.name,
        ([.spec.routes[]?.match]|join(","))] | @tsv'
  fi
done
chart="$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
values="$config/values.yaml"
helm lint "$chart" --values "$values"
helm template "$DPS_RELEASE" "$chart" --namespace "$DPS_NAMESPACE" --values "$values" \
  > "$DPS_RUNTIME_ROOT/verification/logs/dps-rendered.yaml"
helm upgrade --install "$DPS_RELEASE" "$chart" \
  --kube-context "$DPS_KUBE_CONTEXT" --namespace "$DPS_NAMESPACE" \
  --values "$values" --wait --timeout 20m --history-max 10
helm -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
kubectl -n "$DPS_NAMESPACE" get pods,pvc,service,ingress
kubectl -n "$DPS_NAMESPACE" get deployment,statefulset
~~~

预期 release deployed、9 个工作负载 Ready；独立 PG/LDAP/BMC 不由 chart 重建。Core server PVC 与 SeaweedFS 3 PVC Bound，local-path 实际存储在 runtime/data/kubernetes/storage。render 通过只证明配置可渲染，运行 Ready/集成检查另做。

## 6. 安装匹配 dpsctl，真实 LDAP 登录

~~~bash
cli_ref=$(jq -r '.images[]|select(.name=="dpsctl")|.image_digest' \
  "$DPS_SOURCE_ROOT/dps-install/config/artifact-sources.json")
cli_container=$(docker create "$cli_ref")
docker cp "$cli_container:/dpsctl" "$DPS_RUNTIME_ROOT/dps-install/packages/tools/bin/dpsctl"
docker rm "$cli_container"
chmod 755 "$DPS_RUNTIME_ROOT/dps-install/packages/tools/bin/dpsctl"
export PATH="$DPS_RUNTIME_ROOT/dps-install/packages/tools/bin:$PATH"
dpsctl --version
# 本机 DNS/hosts 缺失时才添加；现有错误地址先人工核对，不覆盖。
for dns_name in "$DPS_API_NAME" "$DPS_UI_NAME"; do
  if resolved=$(getent ahostsv4 "$dns_name"); then
    test "$(printf '%s\n' "$resolved" | awk 'NR==1 {print $1}')" = "$DPS_HOST_IP"
  else
    printf '%s %s\n' "$DPS_HOST_IP" "$dns_name" >> /etc/hosts
  fi
done
dpsctl --output json login --username dps-lab --password-stdin \
  < "$config/ldap/user.password" > "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
chmod 600 "$DPSCTL_CREDENTIALS_PATH" "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
jq '.status' "$DPS_RUNTIME_ROOT/verification/logs/dps-login.json"
dpsctl server-version
dpsctl agent list
~~~

预期 client/server 0.9.0、LDAP admin 登录成功、Agent connected。登录输出含 token，故只展示 status，不 cat 整个 JSON。DPSCTL_CA_CERT_PATH/credentials/log 由 deployment-env.sh 设为 runtime 路径。访问 UI：配置中的 https://ui.dps.lab；客户端需要同样 hosts/DNS 与信任 runtime/config/tls/ca.crt。UI 身份是 LDAP dps-lab，密码查私密 dps-access.json。

## 7. 注册电源类型，验证并导入 4 rack inactive 拓扑

~~~bash
dpsctl --output json device upsert \
  "$DPS_SOURCE_ROOT/dps-install/config/gb300-power-shelf-devices.yaml"
dpsctl --output json topology validate "$config/topology-4rack-dps09.json"
dpsctl --output json topology import "$config/topology-4rack-dps09.json"
dpsctl --output json topology list
~~~

预期 33kW/95% PowerSupply 类型可用、语义验证 status.ok=true、4 rack/72 ComputerSystem/110 实体，is_active=false。已有同名拓扑不能再 import，也不删除重建。

0.9 CLI export 会省略 AgentId，CLI update 实测可能误走 create；必须用官方 API 原始回读验证关系路由。以下 curl 访问本机可达的 Core HTTP gateway，header 由私密 token 文件生成，token 不进命令参数或输出：

~~~bash
routing="$DPS_RUNTIME_ROOT/verification/logs/topology-routing"
mkdir -p "$routing"
python3 - <<'PY'
import os,yaml
from pathlib import Path
c=yaml.safe_load(Path(os.environ["DPSCTL_CREDENTIALS_PATH"]).read_text())
p=Path(os.environ["DPS_RUNTIME_ROOT"])/"verification/logs/topology-routing/auth.header"
p.write_text("Authorization: Bearer "+c["token"]["access_token"]+"\n");p.chmod(0o600)
PY
http_ip=$(kubectl -n "$DPS_NAMESPACE" get service "$DPS_FULLNAME-server-http" \
  -o jsonpath='{.spec.clusterIP}')
http_port=$(kubectl -n "$DPS_NAMESPACE" get service "$DPS_FULLNAME-server-http" -o json |
  jq -r '.spec.ports[]|select(.name=="dps-http")|.port')
topo_api="http://$http_ip:$http_port/nvidia.dcpower.v1.TopologyManagementService"
jq -n --arg name "$DPS_TOPOLOGY_NAME" '{topology_name:$name}' > "$routing/get.json"
curl -fSs --header @"$routing/auth.header" -H 'Content-Type: application/json' \
  --data-binary @"$routing/get.json" "$topo_api/GetTopologyModel" > "$routing/model.ndjson"
jq -s --arg agent "$DPS_AGENT_ID" \
  '[.[]|.result.entities[]?|select(.entity.AgentId==$agent)]|length' "$routing/model.ndjson"
~~~

预期 72。若不是 72，先确认仍 inactive，然后以服务端当前 hash 显式更新关系，禁止 force/delete：

~~~bash
dpsctl --output json topology list
topology_hash=$(jq -sr '[.[]|.result.header? |select(.!=null)][0].topologyHash' "$routing/model.ndjson")
test "$topology_hash" != null
jq -n --arg name "$DPS_TOPOLOGY_NAME" --arg hash "$topology_hash" \
  '{updateTopology:{topologyName:$name,topologyHash:$hash,forceUpdate:false}}' \
  -c > "$routing/update.ndjson"
jq -c '{entities:[.Topology.Entities[]|
  {entity:(del(.Children)),children:(.Children//[])}]}' \
  "$config/topology-4rack-dps09.json" >> "$routing/update.ndjson"
curl -fSs --header @"$routing/auth.header" -H 'Content-Type: application/json' \
  --data-binary @"$routing/update.ndjson" "$topo_api/CreateUpdateTopology" |
  jq '.result.status // .status'
curl -fSs --header @"$routing/auth.header" -H 'Content-Type: application/json' \
  --data-binary @"$routing/get.json" "$topo_api/GetTopologyModel" > "$routing/model.ndjson"
jq -s --arg agent "$DPS_AGENT_ID" \
  '[.[]|.result.entities[]?|select(.entity.AgentId==$agent)]|length' "$routing/model.ndjson"
dpsctl --output json topology list
~~~

预期 status.ok=true、72 关系 AgentId 正确、拓扑仍 inactive。此修正仅在回读缺少路由时执行；已匹配时不写。安装不执行 activate、创建 ResourceGroup、切换策略或功率 PATCH。inactive 不能用 dpsctl check connection/bmc-health 当作 Core→Agent 健康派发已完成。

## 8. 明确打开持久 PRS 开关，检查与安装后备份

~~~bash
dpsctl settings update --set prs_enabled=true \
  --set prs_headroom_percent=-15 --set prs_scheduler_interval_seconds=5
dpsctl settings list
kubectl -n "$DPS_NAMESPACE" get pods,pvc
dpsctl resource-group list
~~~

预期持久 prs_enabled=true、headroom=-15%、scheduler=5 秒。当前没有活跃 ResourceGroup/PRS domain，scheduler 在周期之间 idle 合理；部署成功不能写成动态功率闭环验证成功。按 [PG](manual-postgresql.md) 与 [LDAP](manual-ldap.md) 的原生命令再次备份，检查 dump catalog/LDAP 条目，所有备份只在 runtime。可选独立验收见 [verification](../verification/README.md)；验收脚本或报告不是安装输入。
