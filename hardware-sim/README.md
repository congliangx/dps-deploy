# 4 rack GB300 硬件模拟

本组件使用 SDK 官方 BMC Simulator 0.9，加载 /app/mockups/gb300 + synthetic 插件。4 rack×18节点=72 BMC、288GPU、144CPU；不调用 SDK task deploy/sdk/setup 安装 DPS。公开 nodes/topology 模板与镜像足够启动，无需下载 SDK/vendor。

完整首次步骤在 [manual-install.md](manual-install.md)，根流程在 [installstep.md](../installstep.md)。以下原生命令顺序是下载→密码/CA→节点/路由配置→Compose→严格只读检查；配置细节都在手册可审阅。

## 唯一配置与输入

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
~~~

部署参数从根 [deployment.yaml](../deployment.yaml) 读取，runtime_root由用户选择：.runtime为仓库内专用子目录，.为源码与运行材料同根，/srv/dps-lab为自选绝对目录，源码上级目录也可用。配置中的相对路径按deployment.yaml所在目录解析，生成物不提交Git。公开节点模板 [templates/nodes.json](templates/nodes.json)、DPS拓扑 [topology-4rack-dps09.json](../dps-install/templates/topology-4rack-dps09.json) 在源码。生成Compose/nginx/nodes/TLS在runtime/hardware-sim/runtime，必要凭据/URL/CA/拓扑在runtime/dps-install/config；验证在runtime/verification。

## 1. 下载固定镜像

~~~bash
docker pull --platform linux/amd64 \
  nvcr.io/nvidia/dps-bmc-simulator@sha256:3f81152ee055b95e0bda512227cd6ecbb4813f97dad0c654477a4afbf8caff7e
docker pull --platform linux/amd64 \
  nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
docker image inspect \
  nvcr.io/nvidia/dps-bmc-simulator@sha256:3f81152ee055b95e0bda512227cd6ecbb4813f97dad0c654477a4afbf8caff7e \
  --format '{{.Id}} {{.Architecture}} {{json .RepoDigests}}'
~~~

镜像摘要以 artifact-sources.json 为准；独立步骤直接 inspect 同一 digest，不依赖本地 tag 是否建立。Docker镜像实际amd64。完整tag匹配与缓存冲突处理在下载手册。

## 2. 密码、CA与72个路由

[手册第1–4节](manual-install.md) 明确用 openssl rand/genpkey/req/x509、公开JSON转换、nginx72 server块和Compose生成新实例输入；不要求已有私密文件。示例关键检查：

~~~bash
openssl verify -CAfile "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  -verify_ip "$DPS_HOST_IP" "$DPS_RUNTIME_ROOT/hardware-sim/runtime/tls/tls.crt"
jq 'length' "$DPS_RUNTIME_ROOT/hardware-sim/runtime/nodes.json"
stat -c '%a %n' "$DPS_RUNTIME_ROOT/dps-install/config/bmc-endpoints.csv" \
  "$DPS_RUNTIME_ROOT/dps-install/config/bmc-credentials.json"
~~~

预期证书OK、72、凭据文件600。nginx外部strictCA，私有backend自动证书/proxy_ssl_verify off；项目leaf/key仅挂nginx、CA签名私钥不挂容器。原有身份不覆盖生成。

## 3. 启动与原生检查

~~~bash
compose="$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml"
docker compose -p "$DPS_BMC_PROJECT" -f "$compose" config --quiet
docker compose -p "$DPS_BMC_PROJECT" -f "$compose" up -d --wait
docker exec "$DPS_PROXY_CONTAINER" nginx -t
docker exec "$DPS_PROXY_CONTAINER" nginx -s reload
docker compose -p "$DPS_BMC_PROJECT" -f "$compose" ps
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/readyz"
curl -fSs --cacert "$DPS_RUNTIME_ROOT/dps-install/config/simulator-ca.crt" \
  "https://$DPS_HOST_IP:$DPS_BMC_START_PORT/redfish/v1/Systems/HGX_Baseboard_0" |
  jq '{Id,Status}'
~~~

预期2Docker服务、72入口；默认18443–18514，配置可改变起点。每URL不需客户端自设Host，nginx自动映射唯一节点。详细库存/健康/功率GET可选见 [verification](../verification/README.md)。

## 4. DPS接入与维护

BMC Secret/CA、33kW/95%电源类型、AgentId关系与inactive拓扑导入在 [DPS手册](../dps-install/manual-install.md)。后续DPS安装需要runtime中的Secret/CA/拓扑；verification的JSON报告不需要。

只查状态用docker compose ps/logs；明确stop后可start恢复，restart会丢模拟器内存功率/session状态。两服务unless-stopped。不用维护操作重新生成密码/CA。读取URL/用户密码见 [bmc-access.md](bmc-access.md)；密码不入Markdown、Git或日志。

模拟器不强制认证且保留官方fixture陈旧型号/UUID标签；实机GB300、固件和BMC认证不在模拟验证范围。默认inactive、不做PATCH；Agent网络GET与Core→Agent派发/动态功率控制分别报告。
