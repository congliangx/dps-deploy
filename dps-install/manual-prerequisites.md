# 手工安装前置：先确认准备项，再选择安装步骤

本页先总结安装 DPS 前需要具备的服务、工具和输入，再给出缺少基础设施时的完整 Lab 新建步骤。已有的组件先检查并复用，只安装缺少的部分；是否具备这些条件与是否需要重新安装是两件事。

## 脚本路线在本页做什么

整套脚本的执行入口、暂停模式和参数示例统一在根 [installstep.md](../installstep.md)。选择脚本方式时，以下动作由入口执行；选择手工方式时按后续原生命令展开，两条路线无需重复执行。

| 脚本/阶段 | 实际动作 | 对应正文 |
| --- | --- | --- |
| install-from-zero.sh → install-host-dependencies.sh | 检查 root/amd64、Python/YAML、OpenSSL/curl/git/ss/jq/LDAP 客户端、Docker/Compose；缺少时安装 OS 依赖与 Docker，已有匹配安装复用 | 本页执行准备及第 1 节 |
| download-artifacts.py --component all | 校验/下载固定 chart、11 个镜像、17 个 Debian 包和 LDAP base/配方；构建或核对 LDAP 镜像并记录本次 image ID | 第 3–4 节 |
| install-tools.py / install-dpsctl.sh | 完整模式中安装缺少的 Helm/kubectl/dpsctl，并核对已有工具版本；下载/准备暂停模式还不执行此阶段 | 第 2 节，dpsctl 见 [DPS 手册](manual-install.md) |
| install-kubernetes.sh / refresh-kubeconfig.py | 默认完整模式下载固定 K3s binary/installer/airgap 包，配置 systemd、runtime 数据目录与 kubeconfig，等待物理节点 Ready | 第 5 节 |
| install-from-zero.py | 等待 Traefik CRD/Deployment，检查 API/UI 域名归属；核对 chart 引用的镜像并用 Docker save/k3s ctr 导入 K3s containerd | 第 5–6 节与 [DPS 手册](manual-install.md) |

--download-only 停在下载/LDAP 构建之后；--prepare-only 在此基础上继续四个配置/身份生产者后暂停。Shell 入口两种模式都先检查/补装宿主机依赖；下载阶段若构建 LDAP 镜像会产生构建容器；准备模式生成配置和身份，不启动业务服务，不能称为只读 dry run。业务 Compose、K3s 安装、namespace Secret apply 与 Helm 部署在完整模式中执行。

--kubeconfig 只跳过 K3s 初始化，复用的仍须是本机可使用 k3s ctr 的原生 K3s，并具备所需 Traefik/StorageClass 与权限；它不是任意发行版已有集群的通用选项。客户复用 PG/LDAP/真实 BMC 或自选 Kubernetes 时按 [已有环境对接](existing-infrastructure.md)，不运行完整 Lab 链。

## 只安装一个独立组件时怎么用脚本

先选择根 [installstep.md 第 0 节](../installstep.md) 的配置与环境，再只准备本页第 1 节的主机依赖；脚本方式为 bash dps-install/scripts/install-host-dependencies.sh。独立组件脚本使用 Compose up --wait，要求 Compose ≥ 2.18；已有 Docker 可保留，缺少符合要求的 Compose 插件时先按现有安装方式补齐。随后从 [BMC](../hardware-sim/manual-install.md)、[PostgreSQL](manual-postgresql.md) 或 [LDAP](manual-ldap.md) 手册顶部选择对应一键入口。组件脚本会取得自己的固定镜像/LDAP 构建包并生成配置、启动服务，无需先执行整份前置手册。

独立 BMC/PG/LDAP 不依赖 Helm、kubectl 或 K3s，也不用先下载 chart 与完整 11 镜像；只有继续安装 DPS 时才补相应工具、chart、集群与实际启用组件的镜像。LDAP 脚本自行构建固定镜像，手工 LDAP 路线才需要先执行本页第 4 节构建。下面的完整 Lab 手工细节和脚本动作表是可选路线的展开，不能全部再执行一遍。

## 安装 DPS 前需要准备什么

| 前置项 | 用途和需要达到的状态 | 已有时如何处理 / 缺少时去哪里 |
| --- | --- | --- |
| 部署工具与安装包 | kubectl、Helm、匹配 DPS 0.9 的 chart/dpsctl；具备实际启用组件的镜像访问权限，私有仓库按需提供 image pull Secret | 复用符合要求的工具/缓存；本页第 2–3 节给出 Lab 下载与校验，dpsctl 安装见 [DPS 手册](manual-install.md) |
| Kubernetes 与部署权限 | 目标 kubeconfig/context、namespace 和安装 chart 所需资源的权限；集群节点可用 | 已有集群跳过第 5–6 节的 K3s 初始化/导入，使用客户 registry 与拉取凭据；缺少时第 5 节给出单物理机示例 |
| 存储、入口、域名与网络 | 可用 StorageClass/持久存储、所选 Ingress/Gateway/DNS/TLS；Pod 可达 PG、身份服务、BMC，启 PRS 时还可达 S3/API | 使用客户已有方案；本页 K3s 的 local-path/Traefik 只是 Lab 选择，CRD 随所选入口而定 |
| PostgreSQL | Core 专用库、真实应用账号及 schema/migration 权限；启 PRS 再增加三个数据库；信任链与连接参数准备 | 已有 PG 只准备 DPS 所需库/权限和连接 Secret；缺少时见 [独立 PG 手册](manual-postgresql.md) |
| 身份服务 | 选 LDAP 或 OIDC；LDAP 需 URL、只读 bind、用户/组授权和 TLS 材料 | 复用客户目录/IdP，按实际 schema 配置；缺少且选择 LDAP 时本页第 4 节构建镜像，再见 [OpenLDAP 手册](manual-ldap.md) |
| BMC 与硬件输入 | 真实 Redfish URL、认证、受信 CA、设备规格/拓扑及 Agent 路由；Agent 能访问设备 | 有硬件直接接实机；无硬件才选 [4 rack 模拟器](../hardware-sim/manual-install.md)，不要求客户安装 SDK |
| DPS 身份、证书与 Secret | Core/Agent/所选 API/UI TLS、所选认证所需持久身份；在目标 namespace 创建或引用所需 Secret | 可复用 PKI/已有匹配 Secret；缺少的 DPS 身份按 [DPS 手册](manual-install.md) 准备，已有服务的凭据用真实值 |
| PRS 与对象存储（可选） | 仅启 PRS 时准备三库、S3 bucket/真实访问凭据、Controller 登录 DPS 的授权身份及网络 | 可复用外部 S3，不安装 SeaweedFS；不启 PRS 就跳过其额外准备，详见 [已有环境对接](existing-infrastructure.md) |

版本与完整 Lab 检查单已收录在本页后续章节。Ubuntu 22.04/24.04、root、Docker Compose、固定工具版本和整套镜像清单是下文 Lab 主机新建方案的选择；对接已有 Kubernetes 不要求客户重新安装 K3s/Docker 或取得节点 root 登录。

**复用服务仍需检查 DPS 的 Secret 是否就绪。** 已有 Secret 的 namespace、名称、key 和挂载路径与 values 一致时可直接引用；否则按实际启用功能供给。客户 PG/LDAP/BMC/S3 的已有密码和 CA 不重新生成，DPS 新缺少的证书/JWT 才按需创建。当前 Lab 的 13 个外部 Secret 不是所有用户的固定清单，具体原生命令见 [已有基础设施对接指南](existing-infrastructure.md)。

## 根据现有环境选择下一步

1. **Kubernetes、PG、身份服务和真实 BMC 已齐备：** 进入 [已有基础设施对接指南](existing-infrastructure.md)，配置 values/权限/Secret 后安装 DPS，跳过本页新建主机、第 5–6 节 K3s 初始化/专用导入、LDAP 镜像及整套 Lab 镜像下载；镜像由客户已有 registry/拉取机制提供。
2. **只缺少部分组件：** 仅取相应章节或 PG/LDAP 手册，保留现有服务，再汇总到自己的 DPS values；本页第 3 节是完整 Lab 镜像清单，客户只需准备实际 Helm 渲染引用的镜像。
3. **完整空白 Lab：** 继续下文执行准备与第 1–7 节；随后按对应手册准备 BMC、PG、LDAP、证书/Secret，再用 Helm 安装 DPS。Docker 用于独立 Lab 服务，K3s 使用自己的 containerd。

本页正文的第 1–6 节覆盖主机、工具/包、LDAP 镜像和原生 K3s；第 7 节链接独立数据库/目录服务手册。硬件模拟与 DPS 本体的完整安装步骤分别在上述手册中。

## 当前完整 Lab 的平台与版本

| 项目 | 当前完整 Lab |
| --- | --- |
| OS/节点 | Ubuntu22.04/24.04 amd64、systemd；物理单节点原生K3s |
| K3s | v1.34.12+k3s1，Docker外的containerd，local-path/Traefik |
| 工具 | Helm v3.22.0、kubectl v1.34.12、dpsctl0.9.0 |
| DPS | chart0.9.0、Core/Agent/UI0.9.0，同版本 |
| PG | 独立17.11，4库Owner dps、非superuser、SCRAM/TLS verify-full |
| LDAP | 独立OpenLDAP2.6.10，真实用户/组/只读bind，LDAPS |
| PRS | chart依赖PowerSteering2.1.0；SeaweedFS4.18内部S3 |
| BMC | SDK simulator0.9、GB300 mockup/synthetic，4rack72节点 |

NVIDIA0.9要求Kubernetes≥1.31、PowerSteering使用Helm≥3.12及PG≥17；此表是本方案实际固定版本，不据此宣称其他新版本全部兼容。依据：[官方安装要求](https://docs.nvidia.com/datacenter/dps/versions/0.9/guides/installation/deploy-guide.html)。

以下具体参数与安装命令面向这套完整 Lab。客户复用已有服务时依据所选 DPS 功能核对支持条件，继续使用自己的平台、数据库、认证和存储方案。

## 执行本页 Lab 步骤前

Lab 脚本参数统一在源码根 [deployment.yaml](../deployment.yaml)，由 deployment-env.sh 读取；客户对接内容写自己的 Helm values，目标集群由自己的 kubeconfig/context 选择。固定 chart/images/deb 来源与校验值见 [artifact-sources.json](config/artifact-sources.json)，公开 values/拓扑模板只读。

下载、生成配置/证书/Secret/kubeconfig、数据/备份与验证输出写入所选 DPS_RUNTIME_ROOT；验证报告不是安装依赖。必要应用输入在其 dps-install/config 或 hardware-sim/runtime，下载缓存在 dps-install/packages，持久数据在 dps-install/data。运行目录可同根、子目录或其他位置，生成物不提交 Git；当前 L20-12 路径和地址只是实例设置。

先完成根 [installstep.md 第 0 节](../installstep.md) 的配置与清点，包括 python3/python3-yaml 配置解析依赖和运行目录准备。以下主机新建命令在远端 root 的 Bash 会话执行；本仓库 Lab 参数集中在源码根 deployment.yaml，读取后生成路径使用 DPS_RUNTIME_ROOT。

~~~bash
set -euo pipefail
umask 077
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
test "$(id -u)" = 0
test "$(uname -m)" = x86_64
. /etc/os-release
test "$ID" = ubuntu
case "$VERSION_ID" in 22.04|24.04) ;; *) exit 1 ;; esac
ip -4 address show dev "$DPS_INTERFACE"
df -h "$DPS_RUNTIME_ROOT"
~~~

预期为 Ubuntu 22.04/24.04 amd64、systemd、配置中的实际管理网卡/IP。源码位置由当前仓库决定，runtime_root 可与源码同根（.）、选择仓库内专用子目录（.runtime）或其他目录（如 /srv/dps-lab）；配置中的相对路径按 deployment.yaml 所在目录解析。L20-12 的外置 runtime 是当前布局，已有运行数据，维护时直接使用原配置与身份，跳过本文“首次创建”。

## 1. 安装 OS 依赖和 Docker Compose v2

首次裸机使用 Docker 官方 Ubuntu 仓库。已有 Docker 时先检查版本与正在运行的容器，复用符合要求的安装，不卸载原 Docker。Docker 用于独立 BMC、PG、LDAP；K3s 使用自己的 containerd。

~~~bash
apt-get update
apt-get install -y ca-certificates curl gnupg openssl python3 python3-yaml jq \
  iproute2 util-linux ldap-utils
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $VERSION_CODENAME
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version
docker compose version
~~~

预期 daemon 可连接，Compose 为 v2。OS 包进入系统包管理；项目安装包缓存、配置、数据与验证输出进入 runtime_root。依据：[Docker Ubuntu 安装](https://docs.docker.com/engine/install/ubuntu/)。

## 2. 下载 Helm / kubectl，核对校验和

已有同版本工具可复用。以下首次下载到新缓存；缓存已存在时先校验，冲突文件保留排查，不覆盖。

~~~bash
tool_dir="$DPS_RUNTIME_ROOT/dps-install/packages/tools"
mkdir -p "$tool_dir/bin" "$DPS_RUNTIME_ROOT/dps-install/config"
curl -fLsS "https://get.helm.sh/helm-${DPS_HELM_VERSION}-linux-amd64.tar.gz" \
  -o "$tool_dir/helm.tar.gz"
curl -fLsS "https://get.helm.sh/helm-${DPS_HELM_VERSION}-linux-amd64.tar.gz.sha256sum" \
  -o "$tool_dir/helm.sha256sum"
printf '%s  %s\n' "$(awk '{print $1}' "$tool_dir/helm.sha256sum")" "$tool_dir/helm.tar.gz" |
  sha256sum -c -
tar -xOf "$tool_dir/helm.tar.gz" linux-amd64/helm > "$tool_dir/bin/helm"
curl -fLsS "https://dl.k8s.io/release/${DPS_KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
  -o "$tool_dir/bin/kubectl"
curl -fLsS "https://dl.k8s.io/release/${DPS_KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" \
  -o "$tool_dir/kubectl.sha256"
printf '%s  %s\n' "$(cat "$tool_dir/kubectl.sha256")" "$tool_dir/bin/kubectl" |
  sha256sum -c -
chmod 755 "$tool_dir/bin/helm" "$tool_dir/bin/kubectl"
export PATH="$tool_dir/bin:$PATH"
helm version --short
kubectl version --client=true -o json | jq '.clientVersion.gitVersion'
~~~

预期 Helm v3.22.0、kubectl v1.34.12。下载文件放在所选 DPS_RUNTIME_ROOT 的 packages 子目录，不覆盖公开模板，也不提交 Git。

## 3. 固定 DPS chart 与全部镜像

固定版本与官方 URL/digest 清单是源码 [artifact-sources.json](config/artifact-sources.json)。DPS chart/客户端为 0.9.0，Power Steering 为 2.1.0。以下校验已有缓存，或通过临时文件提交新缓存。

~~~bash
manifest="$DPS_SOURCE_ROOT/dps-install/config/artifact-sources.json"
chart="$DPS_RUNTIME_ROOT/dps-install/packages/dps-0.9.0.tgz"
mkdir -p "$(dirname "$chart")"
chart_sha=$(jq -r '.chart.sha256' "$manifest")
if test -e "$chart"; then
  printf '%s  %s\n' "$chart_sha" "$chart" | sha256sum -c -
else
  curl -fLsS --retry 3 "$(jq -r '.chart.url' "$manifest")" -o "$chart.partial"
  printf '%s  %s\n' "$chart_sha" "$chart.partial" | sha256sum -c -
  mv "$chart.partial" "$chart"
fi
helm show chart "$chart"
helm show values "$chart" > "$DPS_RUNTIME_ROOT/dps-install/config/chart-values-reference.yaml"

jq -r '.images[] | [.image_digest, (.tag // "")] | @tsv' "$manifest" |
while IFS="$(printf '\t')" read -r image tag; do
  docker pull --platform linux/amd64 "$image"
  docker image inspect "$image" |
    jq -e --arg ref "$image" '.[0].Architecture=="amd64" and (.[0].RepoDigests|index($ref)!=null)'
  if test -n "$tag"; then
    digest_id=$(docker image inspect --format '{{.Id}}' "$image")
    if docker image inspect "$tag" >/dev/null 2>&1; then
      test "$(docker image inspect --format '{{.Id}}' "$tag")" = "$digest_id"
    else
      docker tag "$image" "$tag"
    fi
  fi
done
~~~

chart SHA256 必须为 2fc7b6e098b17085bf9aaf010d86dfeaf62677fd0f80bb4c2702e91b0b3fd6ef。来源为 [NVIDIA NGC Helm](https://helm.ngc.nvidia.com/nvidia/index.yaml)。pull 后核对 digest 与 amd64；tag 只与 chart 匹配，不覆盖同名不同 ID 的镜像。

若 NGC 返回 401/403，按组织 entitlement 配置 Catalog 凭据。docker login 使用密码 stdin，API key 不写入文档、shell 历史或 values；保持 TLS 校验。清单覆盖 BMC/nginx/PG/Core/Agent/UI/dpsctl 和 PRS 的 5 个镜像；LDAP 镜像下面自行构建。

## 4. 构建独立 OpenLDAP 2.6.10 镜像

从 Debian 官方快照下载 17 个固定 .deb，再使用公开配方离线构建，不依赖旧 image ID 或旧 tar SHA。源码与运行目录同根时，三份配方文件跳过复制到自身，仍执行固定 SHA 校验；下载的 deb 和生成镜像包不提交 Git。已用于运行实例的 LDAP image ID 不替换。

~~~bash
ldap_build="$DPS_RUNTIME_ROOT/dps-install/packages/ldap/build"
mkdir -p "$ldap_build/debs"
for recipe in Dockerfile entrypoint.sh SHA256SUMS; do
  recipe_source="$DPS_SOURCE_ROOT/dps-install/packages/ldap/build/$recipe"
  recipe_runtime="$ldap_build/$recipe"
  # 同根布局时，配方已位于目标目录，不复制到自身。
  if ! test "$recipe_source" -ef "$recipe_runtime"; then
    cp "$recipe_source" "$recipe_runtime"
  fi
done
jq -r '.ldap.debs[] | [.filename,.url,.sha256] | @tsv' "$manifest" |
while IFS="$(printf '\t')" read -r name url sha; do
  file="$ldap_build/debs/$name"
  if test -e "$file"; then
    printf '%s  %s\n' "$sha" "$file" | sha256sum -c -
  else
    curl -fLsS --retry 3 "$url" -o "$file.partial"
    printf '%s  %s\n' "$sha" "$file.partial" | sha256sum -c -
    mv "$file.partial" "$file"
  fi
done
(cd "$ldap_build" && sha256sum -c SHA256SUMS)
ldap_base=$(jq -r '.ldap.base_image' "$manifest")
docker pull --platform linux/amd64 "$ldap_base"
ldap_tag="${DPS_INSTANCE_PREFIX}-openldap:2.6.10-manual"
if docker image inspect "$ldap_tag" >/dev/null 2>&1; then
  echo "已有镜像；先核对其固定配方，保留原 ID"
else
  docker build --network none --pull=false -t "$ldap_tag" "$ldap_build"
fi
ldap_id=$(docker image inspect --format '{{.Id}}' "$ldap_tag")
docker run --rm --entrypoint /usr/sbin/slapd "$ldap_id" -VV 2>&1
docker save "$ldap_id" -o "$DPS_RUNTIME_ROOT/dps-install/packages/ldap/openldap-2.6.10-runtime.tar"
mkdir -p "$DPS_RUNTIME_ROOT/dps-install/config/ldap"
jq -n --arg image "$ldap_tag" --arg id "$ldap_id" \
  '{image:$image,image_id:$id,recipe:"Debian 13 / OpenLDAP 2.6.10"}' \
  > "$DPS_RUNTIME_ROOT/dps-install/config/ldap/runtime-build.json"
~~~

预期 OpenLDAP 2.6.10，固定 Debian 13 base，实际 slapd UID 10001。Compose 固定本次读取的 image ID。源码配方与 SHA 留 Git，.deb/构建上下文/tar 留 runtime。不要重新标记原运行实例 dps-openldap:2.6.10-debian13。

## 5. 在物理机安装原生 K3s

这是空白主机分支。已有 K3s 时使用其 kubeconfig，核对物理节点、版本、StorageClass 与域名归属，跳过服务创建，不覆盖 unit/数据。配置依据：[K3s configuration](https://docs.k3s.io/installation/configuration)。

~~~bash
k3s_pkg="$DPS_RUNTIME_ROOT/dps-install/packages/k3s"
kube_cfg="$DPS_RUNTIME_ROOT/dps-install/config/kubernetes"
mkdir -p "$k3s_pkg" "$kube_cfg/systemd"
release_url="https://github.com/k3s-io/k3s/releases/download/${DPS_K3S_VERSION//+/%2B}"
curl -fLsS "$release_url/sha256sum-amd64.txt" -o "$k3s_pkg/sha256sum-amd64.txt"
printf '%s  %s\n' 2529ab5abe30b2d2db1e2f8018a67e75eb443381145316469538092d9958fbfd \
  "$k3s_pkg/sha256sum-amd64.txt" | sha256sum -c -
curl -fLsS "$release_url/k3s" -o "$k3s_pkg/k3s"
curl -fLsS "$release_url/k3s-airgap-images-amd64.tar.zst" \
  -o "$k3s_pkg/k3s-airgap-images-amd64.tar.zst"
(cd "$k3s_pkg" && sha256sum -c --ignore-missing sha256sum-amd64.txt)
curl -fLsS "https://raw.githubusercontent.com/k3s-io/k3s/${DPS_K3S_VERSION//+/%2B}/install.sh" \
  -o "$k3s_pkg/install.sh"
printf '%s  %s\n' 40b487f0d8ef4f5d1bf422e7bb6228cc7789c40ecc66c5ab067d396bbee9816e \
  "$k3s_pkg/install.sh" | sha256sum -c -

cat > "$kube_cfg/k3s.yaml" <<EOF
node-name: $DPS_KUBE_NODE
node-ip: $DPS_HOST_IP
advertise-address: $DPS_HOST_IP
bind-address: 0.0.0.0
https-listen-port: $DPS_KUBE_API_PORT
flannel-iface: $DPS_INTERFACE
cluster-cidr: $DPS_POD_CIDR
service-cidr: $DPS_SERVICE_CIDR
data-dir: $DPS_RUNTIME_ROOT/dps-install/data/kubernetes/k3s
default-local-storage-path: $DPS_RUNTIME_ROOT/dps-install/data/kubernetes/storage
kubelet-arg:
  - root-dir=$DPS_RUNTIME_ROOT/dps-install/data/kubernetes/kubelet
resolv-conf: $DPS_RESOLV_CONF
write-kubeconfig: $kube_cfg/k3s-admin.yaml
write-kubeconfig-mode: "0600"
tls-san:
  - $DPS_HOST_IP
  - $DPS_HOST_NAME
  - $DPS_KUBE_NODE
EOF
mkdir -p "$DPS_RUNTIME_ROOT/dps-install/data/kubernetes/k3s/agent/images" \
  "$DPS_RUNTIME_ROOT/dps-install/data/kubernetes/kubelet" \
  "$DPS_RUNTIME_ROOT/dps-install/data/kubernetes/storage"
ln -s "$k3s_pkg/k3s-airgap-images-amd64.tar.zst" \
  "$DPS_RUNTIME_ROOT/dps-install/data/kubernetes/k3s/agent/images/k3s-airgap-images-amd64.tar.zst"
test ! -e /usr/local/bin/k3s
test ! -e /etc/systemd/system/k3s.service
install -m 755 "$k3s_pkg/k3s" /usr/local/bin/k3s
mkdir -p /etc/systemd/system/k3s.service.d
printf '[Unit]\nRequiresMountsFor=%s\n' "$DPS_RUNTIME_ROOT" \
  > /etc/systemd/system/k3s.service.d/deploy-mount.conf
# 已校验固定 SHA 的官方 K3s installer，仅创建标准 systemd 集成。
# 上方逐项声明实际配置；这不是仓库自编部署脚本。
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  INSTALL_K3S_SKIP_DOWNLOAD=true INSTALL_K3S_SYMLINK=skip \
  INSTALL_K3S_EXEC="server --config $kube_cfg/k3s.yaml" \
  sh "$k3s_pkg/install.sh"
cp /etc/systemd/system/k3s.service "$kube_cfg/systemd/"
cp /etc/systemd/system/k3s.service.env "$kube_cfg/systemd/"
cp /etc/systemd/system/k3s.service.d/deploy-mount.conf "$kube_cfg/systemd/"
systemctl is-active k3s
~~~

将新生成管理员 kubeconfig 保存到 runtime，设置外部 API 地址和 context；不要输出 kubeconfig 内容。

~~~bash
kubectl --kubeconfig "$kube_cfg/k3s-admin.yaml" config view --raw --flatten > "$KUBECONFIG"
kubectl --kubeconfig "$KUBECONFIG" config set-cluster default \
  --server="https://${DPS_HOST_IP}:${DPS_KUBE_API_PORT}"
kubectl --kubeconfig "$KUBECONFIG" config rename-context default "$DPS_KUBE_CONTEXT"
chmod 600 "$KUBECONFIG"
kubectl --context "$DPS_KUBE_CONTEXT" wait --for=condition=Ready \
  "node/$DPS_KUBE_NODE" --timeout=180s
kubectl get nodes -o wide
kubectl get storageclass
# Node Ready 早于打包 Traefik/CRD 安装；先等两个 CRD 创建并 Established。
for attempt in $(seq 1 90); do
  if kubectl --request-timeout=5s get \
    crd/ingressroutes.traefik.io crd/ingressroutetcps.traefik.io >/dev/null 2>&1; then
    break
  fi
  if test "$attempt" = 90; then
    echo "Traefik CRD 未在等待窗口内创建" >&2
    exit 1
  fi
  sleep 2
done
kubectl wait --for=condition=Established \
  crd/ingressroutes.traefik.io crd/ingressroutetcps.traefik.io --timeout=180s
# 再等 Deployment 创建，不能在 CRD 刚就绪时假定 Deployment 已存在。
for attempt in $(seq 1 90); do
  if kubectl --request-timeout=5s -n kube-system get deployment/traefik >/dev/null 2>&1; then
    break
  fi
  if test "$attempt" = 90; then
    echo "Traefik Deployment 未在等待窗口内创建" >&2
    exit 1
  fi
  sleep 2
done
kubectl -n kube-system rollout status deployment/traefik --timeout=180s
~~~

预期两个 Traefik CRD Established、实际物理节点与 Traefik Ready、local-path 可用，没有 k3d/kind 外层节点容器。单节点不能证明多节点故障切换。

## 6. 将 chart 固定镜像导入 K3s containerd

Docker 与 K3s containerd 缓存独立。带 tag 的清单包括 chart 工作负载及 postgres:17 迁移客户端。

~~~bash
images_tar="$DPS_RUNTIME_ROOT/dps-install/packages/runtime-images.tar"
mapfile -t chart_tags < <(jq -r '.images[] | select(.tag != null) | .tag' "$manifest")
docker save "${chart_tags[@]}" -o "$images_tar"
k3s ctr --namespace k8s.io images import "$images_tar"
k3s ctr --namespace k8s.io images list
~~~

确认 DPS、PostgreSQL 客户端和 Power Steering/SeaweedFS tags 存在。此时还没有安装 DPS。

## 7. 创建独立 PostgreSQL 与 OpenLDAP

按 [手工 PostgreSQL](manual-postgresql.md) 创建 CA、密码、4 个数据库与 HBA，验证 verify-full；再按 [手工 OpenLDAP](manual-ldap.md) 创建真实用户/组、只读 bind、LDAPS 和 Core 客户端证书。同时确认真实 BMC 或所选 [模拟 BMC](../hardware-sim/manual-install.md) 已准备好。PG、LDAP 和所选硬件输入通过后，进入 [DPS 手工安装](manual-install.md) 准备当前完整 Lab 的 13 个 Secret 与 Helm release；客户配置按实际选择供给 Secret。

## 完整 Lab 安装前的状态检查

下列清单仅用于复现完整 Lab；在完成所选服务的对应手册后检查。已有客户环境按开头的准备项和 [对接指南](existing-infrastructure.md) 核对实际组件，不要求固定四 rack、LDAP-only 或 13 个 Secret。

1. 主机管理网卡/IP、磁盘、systemd、Docker Compose v2准备；现有服务/端口/子网先清点。
2. curl下载验证chart SHA、工具SHA与固定11镜像digest/amd64；Debian17deb SHA与公开配方构建LDAP，不要求旧imageID。
3. 原生K3s实际节点Ready、local-path与Traefik；Docker镜像导入K3s独立containerd；kubeconfig600。
4. BMC72URL严格CA GET；模拟器不强制密码行为独立标明。
5. 独立PG四库/权限/HBA与verify-full实际连接，管理员/应用密码分开；两个内建chart PG禁用。
6. LDAP真实用户与授权组/只读bind、严格LDAPS，完整CA/clientcert/key投射输入；OIDC关闭。
7. DPS13Secret、values无秘密；API/UI域名路由无其他实例占用；Core/PRS/Docker网络可通。

~~~bash
# 先进入实际 clone 的仓库根目录。
DPS_SOURCE_ROOT=$(git rev-parse --show-toplevel)
source "$DPS_SOURCE_ROOT/dps-install/scripts/deployment-env.sh"
kubectl --context "$DPS_KUBE_CONTEXT" get nodes -o wide
kubectl get storageclass
docker compose -p "$DPS_BMC_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/hardware-sim/runtime/compose.yaml" ps
docker compose -p "$DPS_PG_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/postgresql/compose.yaml" ps
docker compose -p "$DPS_LDAP_PROJECT" \
  -f "$DPS_RUNTIME_ROOT/dps-install/config/ldap/compose.yaml" ps
~~~

安装前“没有 DPS release”只适用于新实例。完成基础设施检查后，按 [DPS 手工安装](manual-install.md) 准备证书、Secret 和 values；第 7 项在这些输入准备完成、执行 Helm 前确认。独立 PG/LDAP 和所选 BMC 的部署分别由对应手册完成，SDK 仅模拟硬件。

## 验证范围

具体日期与验收记录见 [operation-history](../docs/operation-history.md)。已有新身份/新数据验证复用了 L20-12 的物理 K3s，没有在另一台空白 OS/K3s 上完成首装实测。单节点不代表多节点 HA；inactive 拓扑、Agent connected、BMC 严格 TLS GET 和 PRS 部署开启也不能替代真实硬件的 Core→Agent 派发或动态功率闭环验收。
