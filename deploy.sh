#!/usr/bin/env bash
set -euo pipefail

GCP_KEY=""
VALUES_FILE=""

usage() {
  echo "Usage: $0 [--gcp-key <path>] [--values <path>]"
  echo ""
  echo "Options:"
  echo "  --gcp-key <path>   Path to GCP service account JSON key"
  echo "  --values <path>    Path to Helm values override file (e.g. helm/values-secret.yaml)"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --gcp-key) GCP_KEY="$2"; shift 2 ;;
    --values) VALUES_FILE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

# Build summary
echo ""
echo "This will:"
if [[ -n "$GCP_KEY" ]]; then
  echo "  - Create/update K8s secret 'gcp-credentials' from $GCP_KEY"
fi
HELM_CMD="helm upgrade --install your-podcast ./helm"
if [[ -n "$VALUES_FILE" ]]; then
  HELM_CMD="$HELM_CMD -f $VALUES_FILE"
fi
echo "  - Run: helm dependency update helm/"
echo "  - Run: $HELM_CMD"
echo ""

read -rp "Continue? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

# Create GCP secret if provided
if [[ -n "$GCP_KEY" ]]; then
  echo "==> Creating/updating gcp-credentials secret..."
  kubectl create secret generic gcp-credentials \
    --from-file=sa-key.json="$GCP_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# Pull subchart dependencies
echo "==> Updating Helm dependencies..."
helm dependency update helm/

# Deploy
echo "==> Deploying with Helm..."
$HELM_CMD

echo "==> Done!"
