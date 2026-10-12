# 对接已有基础设施：选择组件、配置和 Secret

本页适用于客户已经具备部分或全部 Kubernetes、真实 BMC、PostgreSQL、LDAP/PKI/S3 的情况。先按根 [README](../README.md) 选择组件；没有的部分才进入相应新建手册。安装 Kubernetes 是获得集群的一种方式，模拟 BMC 是缺硬件时的实验选择，不是 DPS 使用真实硬件的前置。

本仓库的 install-from-zero / prepare-*-fresh 入口生成的是完整 Lab 配置，不会自动发现企业服务、数据库权限或 LDAP schema。已有环境按本页准备自选的 Helm values 和 Secret，再执行原生 Helm 命令。deployment.yaml 统一 Lab 脚本的主机与路径参数；企业服务的 endpoint、认证、StorageClass、网络和 Secret 引用属于 DPS 应用 values。不要运行完整 Lab 生产者去重写客户的对接配置。

已有服务无需重新安装，但已有服务不代表 DPS 的数据库、账号、信任链和 namespace 内 Secret 已准备好。已有 Secret 的名称、namespace、类型和 key 与所选 values 一致时可以直接引用；不需再生成同一份秘密。Secret 不跨 namespace 引用，可由客户已有 External Secrets/cert-manager 等控制器在目标 namespace 供给。下面的名字仅为本页示例；当前 Lab 的 13 个外部 Secret 不是固定数量。

## 1. 先选择复用项并准备输入

| 部分 | 复用已有时准备 | 缺少时的新建说明 |
| --- | --- | --- |
| Kubernetes | 有权限的 kubeconfig/context、namespace、可用 StorageClass、Ingress/Gateway、DNS及集群到外部服务的网络 | [主机/K3s](manual-prerequisites.md)，仅空白实验主机需要 |
| 真实 BMC | 真实 Redfish URL、支持的认证方式、账号或 token、服务 CA、硬件拓扑和 Agent 路由 | [模拟器](../hardware-sim/manual-install.md)，仅无硬件时选用 |
| PostgreSQL | endpoint/port、DPS 专用数据库、真实应用账号密码、schema/migration 权限和 CA | [独立 PG](manual-postgresql.md)，不覆盖客户 PGDATA |
| LDAP | LDAPS URL、只读 bind 账号、base DN、用户/组查询规则、授权组和 CA/客户端证书材料 | [独立 LDAP](manual-ldap.md)，不重建客户目录 |
| DPS TLS/JWT | PKI/cert-manager 签发的 Core/Agent/API/UI 材料和已有 JWT；缺少 DPS 身份时才创建 | [DPS 证书步骤](manual-install.md)，只取新身份部分 |
| PRS | 是否启用；启用后增加三个数据库、Controller 的 DPS 身份与 S3 bucket/权限 | [实验 PRS](manual-install.md)；外部 S3 见下文 |
| 镜像访问 | 对所选 chart 实际引用镜像的访问权限、必要的 image pull Secret 或镜像镜像源 | [固定 artifact 来源](config/artifact-sources.json) |

已有集群不需要为 DPS 安装 K3s、Docker 或改动节点系统。DPS 0.9 的 Kubernetes 下限为 1.31.x；Helm 3.7 起，PRS 需 Helm 3.12 起；启用 PRS 时 PostgreSQL 需 17 或更高并验证所选版本。版本和现有集群要求见 [官方部署说明](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html)。StorageClass、Ingress、镜像认证和网络策略按客户平台选择，不固定为 local-path、Traefik 或单台主机 IP。

在部署工作站的 Bash 中选择已有集群，使用自己的路径和名字替换示例：

~~~bash
export KUBECONFIG=/path/to/customer-kubeconfig
KUBE_CONTEXT=customer-context
DPS_NAMESPACE=dps
DPS_RELEASE=dps
DPS_RUNTIME_ROOT=/srv/dps-lab
config="$DPS_RUNTIME_ROOT/dps-install/config"
inputs="$config/customer-inputs"
umask 077
mkdir -p "$inputs" "$DPS_RUNTIME_ROOT/verification"
chmod 700 "$inputs"
kubectl --context "$KUBE_CONTEXT" get nodes
kubectl --context "$KUBE_CONTEXT" get storageclass,ingressclass
kubectl --context "$KUBE_CONTEXT" auth can-i create statefulsets -n "$DPS_NAMESPACE"
# 目标 namespace 不存在时才创建；存在时核对归属及部署权限。
if ! kubectl --context "$KUBE_CONTEXT" get namespace "$DPS_NAMESPACE" >/dev/null 2>&1; then
  kubectl --context "$KUBE_CONTEXT" create namespace "$DPS_NAMESPACE"
fi
~~~

如果先加载了 Lab 的 deployment-env.sh，它会指向项目 kubeconfig；在本流程重新选择客户 KUBECONFIG/context，不能把 Lab kubeconfig 当作客户集群。安装身份需有 chart 所需资源的权限，节点无需 root 登录。IngressRoute 等 CRD 只在所选 controller/chart 路由使用它们时需要。

## 2. PostgreSQL、LDAP、BMC 接入准备

**PostgreSQL。** 保留服务、数据和已有管理员账号。由数据库管理员为 DPS 准备 Core 数据库和迁移所需权限；开启 PRS 再准备 Config、staged Config、Controller 三个数据库。示例名称为 dps、dps_prs_config、dps_prs_config_staged、dps_prs_controller，可通过 values 修改。应用不需 superuser；角色需要连接及目标 schema 的创建/迁移权限。数据库创建与授权 SQL 参考 [PG 手册第 3 节](manual-postgresql.md)，只执行客户新建的 DPS 专用库/角色部分，不执行服务初始化或改动其他业务库。

**LDAP。** 复用现有目录中的只读 bind 账号和 DPS 用户/组。按实际 LDAP schema 修改 serverUrl、bindDn、baseDn、userFilter、groupProfile、groupFilter、groupAttribute、auth_required_groups 和 groupRoleMapping。以下示例使用 uid + groupOfNames/member；客户目录不匹配时不能照抄。LDAP bind 账号用于目录查询，PRS Controller 的身份是能够登录并获授权的 DPS 用户，两者不同。按预期角色配置允许组，避免同一用户同时命中管理员和自动化允许组，并用实际登录/授权负例核对。OIDC 也是 chart 支持的另一选择；若使用 OIDC，应按照 [用户账户说明](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/concepts/user_accounts.html) 配置 issuer/JWKS/audience/UI，关闭 LDAP，不把本页 LDAP Secret 清单当作 OIDC 的固定要求。

**BMC。** 跳过 hardware-sim 安装和模拟 CA/密码生成。自行准备真实硬件拓扑，为每个 ComputerSystem 设置真实 Redfish.URL/SecretName，在 Topology.Entities 设置负责它的 AgentId。共享账号可使用 defaultSecretName；不同账号应分 Secret 并由拓扑引用。认证 method 按固件能力选择，不因模拟器接受任意密码就认为真实 BMC 也如此。不要导入本仓库 72 个虚构节点或实验电源型号来替代真实设备规格。

**信任和网络。** 复用 PG/LDAP/BMC 已有服务证书和发行 CA，不给客户服务换 CA、密码或 leaf。Core/Agent 要有到 PG、身份服务、真实 BMC 或代理的连通性；PRS 还需 S3 和 Kubernetes API。替换 Lab 单机/Docker bridge 的 NetworkPolicy egress，按真实 DNS/IP、Pod/namespace selector 和实际目标端口设计。外部 S3 使用 HTTPS 时也应提供运行容器所需信任链；不要通过关闭验证解决证书或网络问题。

## 3. 按选择创建或引用 Secret

| 用途 / 示例 Secret | 本页 keys | 何时需要 |
| --- | --- | --- |
| dps-postgresql | password；启 PRS 时再有 database-password | 外部 PG，填真实应用密码；本例 Core/PRS 共用同一账号 |
| dps-postgresql-ca | ca.crt | 选择 verify-full 且通过自定义文件挂载信任 PG 时 |
| bmc-rack-a | bmc = JSON username/password，标签匹配凭据 selector | 真实 BMC 使用 session/basic 账号；按实际账号划分，可有多个 |
| dps-bmc-ca | ca.crt | 私有 BMC 信任链或 values 指定自定义 CA 文件时 |
| dps-ldap-bind | bind-password | 选择 LDAP 及只读 bind 查询时 |
| dps-ldap-ca；dps-ldap-client-tls | ca.crt；tls.crt/tls.key | 本页 Core LDAP 文件配置需要完整材料；服务器是否要求 mTLS 另按目录策略核对 |
| dps-server-tls；dps-agent-tls | ca.crt、tls.crt、tls.key | 本页安全 Core TLS + Agent mTLS 方案 |
| dps-api-ingress-tls；dps-ui-ingress-tls | tls.crt、tls.key | 本页 NGINX 终止 API/UI HTTPS；其他路由方案按实际引用 |
| dps-api-backend-tls | ca.crt、tls.crt、tls.key | 本页 NGINX 验证 Core 后端；客户端 leaf 专用，不用服务端私钥 |
| dps-jwt-keys | private-key.pem | 选择外部持久 RSA 签名 Secret；也可用 chart 首次生成并保留的方式 |
| dps-prs-s3 | admin_access_key_id、admin_secret_access_key | 仅启 PRS；来自已有 S3 实际签发的 bucket 凭据 |
| dps-prs-dps-auth | ldap-credentials = JSON username/password | 仅启 PRS 且 Controller 使用 LDAP 登录 DPS |
| 客户 registry Secret | .dockerconfigjson | 私有仓库需要；可直接复用客户已有镜像拉取 Secret |

已有 CA 被镜像信任时，部分独立 CA Secret 可省略，但也必须去掉对应自定义 caFile/path 和挂载引用，保留证书验证。Secret 可以按客户管理方式合并或改名，同时修改所有 values key/path 引用。LDAP 在当前 Core 流程保留 client cert/key 文件配置；不能只因为 LDAPS 服务器不要求客户端 mTLS 就删掉这些输入。本例 API/UI TLS Secret 与 Traefik Lab 的 Secret 布局不同。

**以下仅在目标 Secret 尚未准备时执行。** 从客户秘密管理系统把已有材料放入受限 inputs；以下输入文件应为 600，不提交 Git。已有匹配 Secret 时跳过，避免覆盖其身份。

PostgreSQL 和 LDAP 使用客户已经配置的真实密码。手动输入时避免出现在 argv：

~~~bash
read -r -s -p '已有 DPS PostgreSQL 应用密码: ' pg_password
printf '\n'
printf '%s' "$pg_password" > "$inputs/pg.password"
unset pg_password
read -r -s -p '已有 LDAP 只读 bind 密码: ' bind_password
printf '\n'
printf '%s' "$bind_password" > "$inputs/ldap-bind.password"
unset bind_password
chmod 600 "$inputs/pg.password" "$inputs/ldap-bind.password"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-postgresql \
  --from-file="password=$inputs/pg.password" \
  --from-file="database-password=$inputs/pg.password"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-ldap-bind \
  --from-file="bind-password=$inputs/ldap-bind.password"
~~~

上述 PG 两键保存同一真实应用密码；不是创建或更改 PostgreSQL 密码。就算服务已存在，若 DPS 库/角色不存在，仍需先在数据库端由管理员准备。不要使用随机新密码冒充已有 PG/LDAP/BMC/S3 账号密码。

将客户提供的信任材料放入 inputs/pg-ca.crt、bmc-ca.crt、ldap-ca.crt 和 ldap-client/tls.crt、tls.key。TLS 文件来自客户现有 PKI 或申请签发；LDAP mTLS 要求的 client leaf 必须被目录信任：

~~~bash
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-postgresql-ca \
  --from-file="ca.crt=$inputs/pg-ca.crt"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-bmc-ca \
  --from-file="ca.crt=$inputs/bmc-ca.crt"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-ldap-ca \
  --from-file="ca.crt=$inputs/ldap-ca.crt"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-ldap-client-tls \
  --from-file="tls.crt=$inputs/ldap-client/tls.crt" \
  --from-file="tls.key=$inputs/ldap-client/tls.key"
~~~

真实 BMC 账号 JSON 可由秘密管理系统导出，也可交互生成 JSON 文件；生成的是凭据载体，不是新建 BMC 用户：

~~~bash
python3 -c 'import getpass,json,os,sys; p=sys.argv[1]; u=input("真实 BMC 用户名: "); w=getpass.getpass("真实 BMC 密码: "); open(p,"w").write(json.dumps({"username":u,"password":w})); os.chmod(p,0o600)' "$inputs/bmc-rack-a.json"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic bmc-rack-a \
  --from-file="bmc=$inputs/bmc-rack-a.json"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" label secret bmc-rack-a \
  app.kubernetes.io/component=bmc-credentials
~~~

重复创建每组所需 BMC 凭据，拓扑 Redfish.SecretName 引用其名称。如果实际使用 bearerToken，则按 chart 的 bearerToken.existingSecret/existingSecretKey 配置其载体，不把 username/password JSON 当 token。

Core/Agent 使用独立于客户 BMC/PG/LDAP 的 DPS 身份。已有匹配的 namespace Secret 时直接引用，跳过本节生成和创建；已有 PKI/cert-manager 时按客户流程取得证书文件，放入 inputs/server、inputs/agent 后执行下面的 Secret 创建命令。本例 Core/Agent 由同一 DPS 信任链签发，Core SAN 包含其 service DNS 和 API 域名；Agent 为 clientAuth，CN 等于 agent.agentID，并出现在 dps.grpcServiceMTLSCN 的 Agent Service 允许列表中。

**可选：新的实验实例缺少全部 DPS TLS/JWT 身份时，使用本地 DPS CA。** 此分支保留当前客户 KUBECONFIG/context，不 source Lab 的 deployment-env.sh，不改变客户 PG/LDAP/BMC 的 CA。仅用于新建 DPS 身份；已有任一相关 key/证书/Secret 时保留原身份，按实际 PKI 单独补齐缺项，不能整段重跑。

先明确这份客户 values 的证书参数；下面与本页示例对应。更改 release/fullnameOverride、namespace、API/UI 域名或 AgentId 时同步修改。DPS_HOST_IP 在此仅作为 DPS leaf 的 IP SAN；192.0.2.10 是文档地址，替换为实际入口 IP：

~~~bash
export DPS_RUNTIME_ROOT DPS_NAMESPACE
export DPS_FULLNAME=dps
export DPS_API_NAME=api.dps.customer.example
export DPS_UI_NAME=ui.dps.customer.example
export DPS_AGENT_ID=customer-agent
export DPS_HOST_IP=192.0.2.10
~~~

保持此会话，仅执行 [manual-install.md 第 1 节](manual-install.md) 的 openssl 证书/JWT代码块；不要执行该手册的 Lab 环境加载、服务生成或后续固定 Lab Secret/values。该代码块使用上面明确的参数，把新 Core/Agent/Ingress leaf 与 JWT 保存到 config/tls。再将同一身份映射到本页的输入布局：

~~~bash
tls="$config/tls"
mkdir -p "$inputs/server" "$inputs/agent" "$inputs/api-ingress" \
  "$inputs/ui-ingress" "$inputs/api-backend"
for identity in server agent; do
  test ! -e "$inputs/$identity/tls.key"
  install -m 644 "$tls/ca.crt" "$inputs/$identity/ca.crt"
  install -m 644 "$tls/$identity.crt" "$inputs/$identity/tls.crt"
  install -m 600 "$tls/$identity.key" "$inputs/$identity/tls.key"
done
for ingress in api-ingress ui-ingress; do
  test ! -e "$inputs/$ingress/tls.key"
  install -m 644 "$tls/ingress.crt" "$inputs/$ingress/tls.crt"
  install -m 600 "$tls/ingress.key" "$inputs/$ingress/tls.key"
done
test ! -e "$inputs/jwt-private-key.pem"
install -m 600 "$tls/jwt-private-key.pem" "$inputs/jwt-private-key.pem"
# NGINX 后端认证使用独立 clientAuth leaf，保留 Core/Agent 私钥各自用途。
test ! -e "$inputs/api-backend/tls.key"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$inputs/api-backend/tls.key"
openssl req -new -key "$inputs/api-backend/tls.key" \
  -out "$inputs/api-backend/client.csr" -subj "/CN=$DPS_FULLNAME-ingress-client"
printf '%s\n' 'basicConstraints=critical,CA:FALSE' \
  'keyUsage=critical,digitalSignature,keyEncipherment' 'extendedKeyUsage=clientAuth' \
  > "$inputs/api-backend/client.ext"
openssl x509 -req -in "$inputs/api-backend/client.csr" \
  -CA "$tls/ca.crt" -CAkey "$tls/ca.key" -CAcreateserial -sha256 -days 825 \
  -extfile "$inputs/api-backend/client.ext" -out "$inputs/api-backend/tls.crt"
install -m 644 "$tls/ca.crt" "$inputs/api-backend/ca.crt"
chmod 600 "$inputs/api-backend/tls.key"
openssl verify -CAfile "$inputs/api-backend/ca.crt" -purpose sslclient \
  "$inputs/api-backend/tls.crt"
~~~

上述本地 CA 分支生成的 API/UI ingress leaf 同时包含两域名，后端 leaf 由同一 DPS CA 签发；JWT 后续直接复用 inputs/jwt-private-key.pem。客户 PKI 分支跳过上面整个本地 CA 生成与映射流程，并按实际方案提供同名输入或已有匹配 Secret。

~~~bash
for identity in server agent; do
  kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic "dps-$identity-tls" \
    --from-file="ca.crt=$inputs/$identity/ca.crt" \
    --from-file="tls.crt=$inputs/$identity/tls.crt" \
    --from-file="tls.key=$inputs/$identity/tls.key"
done
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret tls dps-api-ingress-tls \
  --cert="$inputs/api-ingress/tls.crt" --key="$inputs/api-ingress/tls.key"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret tls dps-ui-ingress-tls \
  --cert="$inputs/ui-ingress/tls.crt" --key="$inputs/ui-ingress/tls.key"
~~~

API/UI ingress leaf 覆盖相应客户端域名。若使用 API TLS passthrough，按所选 controller 路由配置且使用 Core 服务端证书；不强制照上面创建额外 API 终止 TLS 的 Secret。

本页 NGINX 示例还验证 Ingress→Core 的后端证书。由 PKI 提供信任 Core 的 CA 和单独的 clientAuth leaf/key，放入 inputs/api-backend；不把 Core 服务端私钥当客户端身份复制给 Ingress。namespace/Secret 与后端 DNS 随客户 release 一起修改。相关注解依据 [Ingress-NGINX 后端证书认证](https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/#backend-certificate-authentication)；使用别的 controller 时按它的安全后端或 passthrough 机制配置。

~~~bash
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-api-backend-tls \
  --from-file="ca.crt=$inputs/api-backend/ca.crt" \
  --from-file="tls.crt=$inputs/api-backend/tls.crt" \
  --from-file="tls.key=$inputs/api-backend/tls.key"
~~~

选择外部 JWT 时，先复用已有 RSA key；仅新实例没有该 key/Secret 时生成，然后持续保留：

~~~bash
if test ! -f "$inputs/jwt-private-key.pem"; then
  openssl genrsa -out "$inputs/jwt-private-key.pem" 3072
fi
chmod 600 "$inputs/jwt-private-key.pem"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-jwt-keys \
  --from-file="private-key.pem=$inputs/jwt-private-key.pem"
~~~

若选择 chart 管理 JWT，移除现有外部 Secret 引用并按固定 chart 的 lookup/生成行为管理首次安装；不要每次维护新建 key。企业通过控制器供给的 Secret 同样需先在 namespace 就绪。

## 4. 配置已有 PG/LDAP/真实 BMC：Core + Agent + UI，先不启 PRS

将下面内容保存为所选 runtime 的 dps-install/config/values.yaml，替换客户 endpoint、身份组、StorageClass、域名、AgentId 和 Secret 名称。它是外部服务的示例 overlay，不调用 Docker、K3s 或模拟 SDK。Chart/key 已核对本仓库固定 dps-0.9.0.tgz；现有值文件的 Lab bridge egress、local-path/Traefik 和固定四 rack 不应直接复用。

~~~yaml
fullnameOverride: dps
global:
  defaultStorageClass: customer-storage
  postgresql:
    host: postgres.customer.example
    service:
      ports:
        postgresql: "5432"
    sslMode: verify-full
    sslRootCert: /secrets/postgresql/ca.crt
    auth:
      username: dps
      database: dps
      existingSecret: dps-postgresql
      secretKeys:
        passwordKey: password
        userPasswordKey: database-password
postgresql:
  enabled: false
power-steering:
  enabled: false
  postgresql:
    enabled: false
dps:
  enabled: true
  persistence:
    storageClass: customer-storage
  serverTLS:
    transportSecurity: tls
    existingSecret: dps-server-tls
  ingress:
    enabled: true
    className: nginx
    hostname: api.dps.customer.example
    tlsPassthrough: false
    grpcAnnotations:
      nginx.ingress.kubernetes.io/proxy-ssl-verify: "on"
      nginx.ingress.kubernetes.io/proxy-ssl-secret: dps/dps-api-backend-tls
      nginx.ingress.kubernetes.io/proxy-ssl-name: dps-server-grpc.dps.svc.cluster.local
      nginx.ingress.kubernetes.io/proxy-ssl-server-name: "on"
      nginx.ingress.kubernetes.io/proxy-ssl-verify-depth: "3"
    tls:
    - hosts: [api.dps.customer.example]
      secretName: dps-api-ingress-tls
  cors:
    allowedOrigins: https://ui.dps.customer.example
  auth:
    authenticatorType: ldap
    auth_required_groups: dps-admins,dps-automation
    oidc:
      enabled: false
    jwt:
      existingSecret: dps-jwt-keys
      existingSecretKey: private-key.pem
  ldap:
    enabled: true
    serverUrl: ldaps://ldap.customer.example:636
    bindDn: uid=dps-bind,ou=services,dc=customer,dc=example
    baseDn: dc=customer,dc=example
    userFilter: (&(objectClass=person)(uid={username}))
    groupProfile: groupOfNames
    groupFilter: (&(objectClass=groupOfNames)(member={userdn}))
    groupAttribute: cn
    defaultRole: ""
    groupRoleMapping: dps-admins=admin,dps-automation=automation
    bindPassword:
      existingSecret: dps-ldap-bind
      existingSecretKey: bind-password
      mountSecret: true
    certSource: file
    tlsCaCert: /secrets/ldap/ca.crt
    tlsClientCert: /secrets/ldap/tls.crt
    tlsClientKey: /secrets/ldap/tls.key
    volumes:
    - name: ldap-certs
      projected:
        sources:
        - secret:
            name: dps-ldap-ca
            items:
            - key: ca.crt
              path: ca.crt
        - secret:
            name: dps-ldap-client-tls
            items:
            - key: tls.crt
              path: tls.crt
            - key: tls.key
              path: tls.key
    volumeMounts:
    - name: ldap-certs
      mountPath: /secrets/ldap
      readOnly: true
  credentialsStore: k8sSecret
  k8sSecret:
    labelSelector: app.kubernetes.io/component=bmc-credentials
  redfish:
    auth:
      method: session
      defaultSecretName: bmc-rack-a
    tls:
      transportSecurity: tls
      insecureSkipVerify: false
      certs:
        caFile: /secrets/bmc/ca.crt
  bmcTLS:
    caCertPath: /secrets/bmc/ca.crt
  secrets:
  - name: dps-postgresql-ca
    secretKey: ca.crt
    mountPath: /secrets/postgresql/ca.crt
  - name: dps-bmc-ca
    secretKey: ca.crt
    mountPath: /secrets/bmc/ca.crt
  telemetry:
    metrics:
      source: bmc
  prs:
    enabled: false
  agent:
    allowHandshakeFallback: false
  grpcServiceMTLSCN:
    nvidia.dcpower.v1.DPSAgentService:
    - customer-agent
agent:
  enabled: true
  agentID: customer-agent
  tls:
    transportSecurity: mtls
    existingSecret: dps-agent-tls
    insecureSkipVerify: false
ui:
  enabled: true
  ingress:
    enabled: true
    className: nginx
    hostname: ui.dps.customer.example
    tls:
    - hosts: [ui.dps.customer.example]
      secretName: dps-ui-ingress-tls
  api:
    proxyEnabled: true
    scheme: http
    hostname: dps-server-http.dps.svc.cluster.local
    port: "8000"
~~~

示例假设 release/namespace 都为 dps；若更改，更新 UI/Core 内部 service DNS、Core SAN 和 Agent 关系。私有镜像访问时设置 global.imagePullSecrets；PRS 另有 power-steering.global.image.pullSecrets，不把工作站 docker login 当作 Kubernetes 已有拉取凭据。输入的 registry .dockerconfigjson 可由客户平台创建同名 Secret，例如使用 kubectl create secret generic 的 --type=kubernetes.io/dockerconfigjson 与 --from-file；不得把 NGC key 写入 values。

## 5. 选择 PRS 时追加准备，已有 S3 不安装 SeaweedFS

仅开启 PRS 时准备三库和真实 S3 bucket/读写权限；填已有 S3 服务实际签发的 access key，不通过本地随机数生成服务不认识的凭据。Controller 的 ldap-credentials 使用有 DPS 权限的自动化用户，而不是只读 bind 用户。使用企业凭据管理供给以下文件后创建：

~~~bash
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-prs-s3 \
  --from-file="admin_access_key_id=$inputs/s3/access-key" \
  --from-file="admin_secret_access_key=$inputs/s3/secret-key"
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" create secret generic dps-prs-dps-auth \
  --from-file="ldap-credentials=$inputs/prs/dps-account.json"
~~~

dps-account.json 的结构为 username/password JSON，由客户凭据管理输出或采用前面交互写 JSON 的方式填真实 DPS 用户。外部 S3 Secret 只需客户端 key；seaweedfs_s3_config 是实验内置 SeaweedFS 的服务端账号配置，对接已有 S3 不需要此 key。

将下面另存为 runtime 中的 values-prs.yaml，并与基础 values 叠加。示例固定 service 名为 dps-power-config/controller，保持与 hostPort 对应；更改 release/namespace 时同步命名。192.0.2.40/32、203.0.113.50/32 和 198.51.100.20/32 是文档地址，必须改成客户 PG、私网 S3、Kubernetes API 的实际目标/端口。若 endpoint 使用集群内服务或动态地址，应按实际网络模型使用合适 selector/egress，不把示例 IP 当真实可达地址。

~~~yaml
global:
  database:
    user: dps
    names:
      config: dps_prs_config
      configStaged: dps_prs_config_staged
      controller: dps_prs_controller
  storage:
    s3Endpoint: https://s3.customer.example
    region: customer-region
    bucketName: customer-dps-prs
    existingSecret: dps-prs-s3
    accessKeyIdKey: admin_access_key_id
    secretAccessKeyKey: admin_secret_access_key
power-steering:
  enabled: true
  postgresql:
    enabled: false
  global:
    image:
      tag: 2.1.0
    lgtm: false
  seaweedfs:
    enabled: false
  config:
    fullnameOverride: dps-power-config
    extraEnv:
    - name: PGSSLMODE
      value: verify-full
    - name: PGSSLROOTCERT
      value: /secrets/postgresql/ca.crt
    extraVolumes:
    - name: postgresql-ca
      secret:
        secretName: dps-postgresql-ca
        items:
        - key: ca.crt
          path: ca.crt
    extraVolumeMounts:
    - name: postgresql-ca
      mountPath: /secrets/postgresql
      readOnly: true
    extraEgressRules:
    - to:
      - ipBlock:
          cidr: 192.0.2.40/32
      ports:
      - port: 5432
        protocol: TCP
    - to:
      - ipBlock:
          cidr: 203.0.113.50/32
      ports:
      - port: 443
        protocol: TCP
  controller:
    fullnameOverride: dps-power-controller
    cluster:
      dps:
        host: dps-server-grpc
        port: 8080
        tls:
          insecure: false
          skipVerify: false
          caCertPath: /secrets/dps/ca.crt
        auth:
          enabled: true
          secretName: dps-prs-dps-auth
    extraEnv:
    - name: PGSSLMODE
      value: verify-full
    - name: PGSSLROOTCERT
      value: /secrets/postgresql/ca.crt
    extraVolumes:
    - name: postgresql-ca
      secret:
        secretName: dps-postgresql-ca
        items:
        - key: ca.crt
          path: ca.crt
    - name: dps-ca
      secret:
        secretName: dps-server-tls
        items:
        - key: ca.crt
          path: ca.crt
    extraVolumeMounts:
    - name: postgresql-ca
      mountPath: /secrets/postgresql
      readOnly: true
    - name: dps-ca
      mountPath: /secrets/dps
      readOnly: true
    extraEgressRules:
    - to:
      - ipBlock:
          cidr: 192.0.2.40/32
      ports:
      - port: 5432
        protocol: TCP
    - to:
      - ipBlock:
          cidr: 203.0.113.50/32
      ports:
      - port: 443
        protocol: TCP
    - to:
      - ipBlock:
          cidr: 198.51.100.20/32
      ports:
      - port: 6443
        protocol: TCP
dps:
  prs:
    enabled: true
    hostPort: http://dps-power-config.dps.svc.cluster.local:8000
    controllerHostPort: http://dps-power-controller.dps.svc.cluster.local:8001
~~~

两个 PRS Pod 的 PG CA 挂载路径与 PGSSLROOTCERT 一致，Controller 的 DPS CA 与 caCertPath 一致；global.postgresql 继承基础 overlay 的外部数据库连接和真实应用密码。外部 S3 HTTPS 私有 CA 的额外信任材料由客户按运行镜像机制供给，不能将本例服务 URL 当作证书已被信任。完整 PRS 选择说明见 [官方 PRS 文档](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/concepts/power-reservation-steering.html)。

仅启 PRS Config/Controller、复用外部 S3 时没有内置 SeaweedFS 的三个 PVC/四个 workload；验收按实际渲染结果，不要求 Lab 九个 workload/四个 PVC。完成 PRS 身份、网络与服务验收后再决定持久 prs_enabled 和功率策略，不能把安装成功当作真实硬件动态功率闭环完成。

## 6. 渲染、安装与针对性验收

先获取匹配 DPS 0.9 chart/客户端和所选镜像；不下载无关的模拟器、LDAP Debian 包或 K3s 安装包。已有 chart 可复用，核对 [固定来源/SHA](config/artifact-sources.json)。以下安装命令只安装所选 chart 组件，不会部署独立 PG、LDAP、K3s 或 BMC：

~~~bash
chart="$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
values="$config/values.yaml"
helm lint "$chart" --values "$values"
helm template "$DPS_RELEASE" "$chart" --namespace "$DPS_NAMESPACE" --values "$values" \
  > "$DPS_RUNTIME_ROOT/verification/customer-rendered.yaml"
# 审阅引用的 Secret、镜像、StorageClass、PVC、Ingress 和 NetworkPolicy。
helm upgrade --install "$DPS_RELEASE" "$chart" --namespace "$DPS_NAMESPACE" \
  --kube-context "$KUBE_CONTEXT" --values "$values" --wait --timeout 20m
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" get deployment,statefulset,pvc
helm --kube-context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" status "$DPS_RELEASE"
# 仅列 Secret 的键名，不输出值；目标 Secret 名称取自 values。
kubectl --context "$KUBE_CONTEXT" -n "$DPS_NAMESPACE" get secret dps-postgresql \
  -o json | python3 -c 'import json,sys; x=json.load(sys.stdin); print(sorted(x.get("data",{})))'
~~~

选择 PRS 时，上面 lint/template/install 命令都同时传入第二个值文件；不要只把 PRS 字段写入文件但漏掉 -f：

~~~bash
prs_values="$config/values-prs.yaml"
helm lint "$chart" --values "$values" --values "$prs_values"
helm template "$DPS_RELEASE" "$chart" --namespace "$DPS_NAMESPACE" \
  --values "$values" --values "$prs_values" \
  > "$DPS_RUNTIME_ROOT/verification/customer-prs-rendered.yaml"
helm upgrade --install "$DPS_RELEASE" "$chart" --namespace "$DPS_NAMESPACE" \
  --kube-context "$KUBE_CONTEXT" --values "$values" --values "$prs_values" \
  --wait --timeout 20m
~~~

确认实际工作负载 Ready、数据库迁移成功、LDAP 正确/错误密码和角色授权符合预期、API/UI TLS 与 Agent mTLS 成功、Agent 到实际 BMC 的严格 TLS GET/Redfish 库存健康。启 PRS 再检查三库、Controller 身份与 S3 签名读写。复用客户服务时备份/recovery继续由客户既有机制管理；DPS 需纳入对应数据库与持久化备份范围。

先准备/校验真实硬件的设备规格和拓扑，之后才注册与导入；本流程不自动激活拓扑或写 BMC 功率。Lab 的验证器假设本机 Docker、固定名称、四 rack 等，不能直接作为所有客户环境验收；原生命令及按实际启用组件的检查见 [verification](../verification/README.md)。

核对依据：[固定 0.9 chart 清单](config/artifact-sources.json)、[官方 Secret 说明](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/tasks/credentials-and-secrets-configuration.html)、[官方数据库 TLS](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/tasks/database-tls.html)。官方页面补充场景说明，具体 values/key 以已下载并固定 SHA 的 chart 为准。
