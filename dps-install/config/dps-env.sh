# Source on L20-12 before kubectl/Helm/dpsctl operations.
export KUBECONFIG=/raid/vince/deploy/dps-install/config/kubernetes/kubeconfig.yaml
export DPS_KUBE_CONTEXT=dps-l20-12
export DPS_KUBE_NODE=l20-12
export XDG_CONFIG_HOME=/raid/vince/deploy/dps-install/config/tools
export HELM_CONFIG_HOME=/raid/vince/deploy/dps-install/config/helm
export HELM_CACHE_HOME=/raid/vince/deploy/dps-install/data/helm-cache
export HELM_DATA_HOME=/raid/vince/deploy/dps-install/data/helm-data
export DPSCTL_HOST=api.dps.lab
export DPSCTL_PORT=443
export DPSCTL_CA_CERT_PATH=/raid/vince/deploy/dps-install/config/tls/ca.crt

# Keep DPS login credentials and logs inside this project.
export DPSCTL_CREDENTIALS_PATH=/raid/vince/deploy/dps-install/config/dpsctl/credentials.yaml
export DPSCTL_LOG_FILE=/raid/vince/deploy/verification/logs/dpsctl.log
