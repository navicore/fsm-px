#!/bin/bash
# Deploy Pixie using Helm

# Add Pixie Helm repo
helm repo add pixie https://pixie-helm-charts.storage.googleapis.com
helm repo update

# Create namespace
kubectl create namespace pl

# Deploy Pixie
# Note: You'll need to set YOUR_PIXIE_DEPLOY_KEY from https://app.pixielabs.ai/admin/keys
helm install pixie pixie/pixie-operator-chart \
  --namespace pl \
  --set deployKey=YOUR_PIXIE_DEPLOY_KEY \
  --set clusterName=fsm-px-demo

echo "Remember to:"
echo "1. Get your deploy key from https://app.pixielabs.ai/admin/keys"
echo "2. Replace YOUR_PIXIE_DEPLOY_KEY in the helm command above"
echo "3. Wait for all pods in 'pl' namespace to be ready"