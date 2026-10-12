# 手工安装前置：主机、安装包与物理 Kubernetes

这是首次安装步骤。先完成根目录 [installstep.md](../installstep.md) 的配置与清点；以下命令在远端 root 的 Bash 会话执行。仅修改源码根 deployment.yaml，再读取配置。生成路径都在 DPS_RUNTIME_ROOT。

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

预期为 Ubuntu 22.04/24.04 amd64、systemd、配置中的实际管理网卡/IP。源码必须在 runtime_root 外。L20-12 已有运行数据，维护时直接使用原配置与身份，跳过本文“首次创建”。

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

预期 Helm v3.22.0、kubectl v1.34.12。不要把下载文件写入源码目录。

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

从 Debian 官方快照下载 17 个固定 .deb，再使用公开配方离线构建，不依赖旧 image ID 或旧 tar SHA。已用于运行实例的 LDAP image ID 不替换。

~~~bash
ldap_build="$DPS_RUNTIME_ROOT/dps-install/packages/ldap/build"
mkdir -p "$ldap_build/debs"
cp "$DPS_SOURCE_ROOT/dps-install/packages/ldap/build/Dockerfile" "$ldap_build/Dockerfile"
cp "$DPS_SOURCE_ROOT/dps-install/packages/ldap/build/entrypoint.sh" "$ldap_build/entrypoint.sh"
cp "$DPS_SOURCE_ROOT/dps-install/packages/ldap/build/SHA256SUMS" "$ldap_build/SHA256SUMS"
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

按 [手工 PostgreSQL](manual-postgresql.md) 创建 CA、密码、4 个数据库与 HBA，验证 verify-full；再按 [手工 OpenLDAP](manual-ldap.md) 创建真实用户/组、只读 bind、LDAPS 和 Core 客户端证书。两个服务都通过后，进入 [DPS 手工安装](manual-install.md) 创建 13 个 Secret 与 Helm release。
