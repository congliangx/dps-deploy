# 可选组件：4 rack GB300 BMC 模拟器

**有真实 BMC 时跳过本目录安装。** 按 [已有环境对接](../dps-install/existing-infrastructure.md) 提供真实 Redfish URL、账号、CA、设备模型与拓扑，并检查 Agent 到 BMC 的网络/TLS。

Lab 使用 SDK 官方 BMC Simulator 0.9，加载 /app/mockups/gb300 与 synthetic 插件，模拟 4 rack × 18 节点：72 BMC、288 GPU、144 CPU。只需要公开模板和固定镜像，不下载 SDK/vendor，也不由 SDK 安装 DPS。

## 参数与输出

在 root Bash、源码根加载环境：

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~


参数来自 [deployment.yaml](../deployment.yaml)；runtime_root 可由用户自选，布局规则见 [根 README](../README.md)。公开输入为 [nodes 模板](templates/nodes.json) 和 [拓扑模板](../dps-install/templates/topology-4rack-dps09.json)。

生成的 Compose/nginx/nodes/TLS 在 runtime/hardware-sim/runtime；URL/密码/CA/Secret/拓扑在 runtime/dps-install/config。日志与报告写入 runtime/verification，均不提交 Git。

## 安装：脚本或手工二选一

先完成 [installstep.md 第 0–1 节](../installstep.md) 的参数与主机依赖：Docker/Compose、Python/YAML、OpenSSL。单独安装 BMC 不需要 K3s、PG、LDAP 或 DPS。

### 一键脚本

~~~bash
bash hardware-sim/scripts/install-bmc.sh \
  --config "$DPS_SOURCE_ROOT/deployment.yaml"
~~~


入口下载两个固定 digest 镜像，生成随机密码、CA/leaf、72 URL/路由和拓扑，写 Compose 并启动模拟器/代理，最后检查 nginx 与 readiness。无需先执行手册生成配置；详细动作和产物见 [manual-install.md](manual-install.md)。

成功后直接做下方检查。脚本管理实例重入保留身份；手工/历史实例使用原配置维护。Secret 只落盘，后续 DPS 安装时应用；按 DPS 手册继续，不接续完整 fresh 链初始化已启动组件。

### 手工安装

不运行上述脚本，完整执行 [manual-install.md 第 1–4 节](manual-install.md)：镜像 → 密码/证书 → 节点/拓扑/凭据 → nginx/Compose 启动。第 4 节已启动服务，完成后只检查，不再执行 docker compose up。

## 安装后只读检查

任一安装路线成功后执行；可以重复查询，不生成身份或启停服务：

~~~bash
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
docker exec "$DPS_PROXY_CONTAINER" nginx -t
openssl verify -CAfile "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  -verify_ip "$DPS_HOST_IP" "$DPS_RUNTIME_ROOT/hardware-sim/runtime/tls/tls.crt"
jq 'length' "$DPS_RUNTIME_ROOT/hardware-sim/runtime/nodes.json"
stat -c '%a %n' "$DPS_RUNTIME_ROOT/dps-install/config/bmc-endpoints.csv" \
  "$DPS_RUNTIME_ROOT/dps-install/config/bmc-credentials.json"
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/redfish/v1/Systems/HGX_Baseboard_0" |
  jq '{Id,Status}'
~~~


预期两个服务健康、证书 OK、72 节点、凭据文件 600，以及第一个入口的 readiness/Redfish 响应。完整 72 节点库存与 Agent 网络检查见 [验证指南](../verification/README.md)。

默认端口 18443–18514，可配置。代理按端口自动映射节点，客户端无需设置 Host。外部严格验证项目 CA；私有 backend 自动证书与 proxy_ssl_verify off 的范围见手册。

## DPS 接入与维护

按 [DPS 手册](../dps-install/manual-install.md) 使用 runtime 的 BMC Secret/CA/拓扑，登记电源类型和 AgentId，导入 inactive 拓扑；验证 JSON 不是安装输入。URL、用户名和密码位置见 [bmc-access.md](bmc-access.md)。

日常查 Compose ps/logs；需要时按维护入口启停。restart 会丢失模拟器内存中的功率/session 状态，不应重新生成密码/CA。两服务采用 unless-stopped。

模拟器不强制认证，fixture 保留陈旧型号/UUID 标签；不代表真实 GB300 固件与认证行为。默认 inactive、不做功率 PATCH；Agent 网络 GET 与 Core→Agent 派发/动态控制分别验收。
