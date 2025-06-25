#!/usr/bin/env bash

kind delete cluster --name audio-latency-demo
docker rmi audio-source:latest audio-relay:latest tc-audio-tracer:latest 2>/dev/null || true
kind create cluster --name audio-latency-demo --config kind-config.yaml

docker build -t audio-source:latest ./audio-source/
kind load docker-image audio-source:latest --name audio-latency-demo

docker build -t audio-relay:latest ./audio-relay/
kind load docker-image audio-relay:latest --name audio-latency-demo

kubectl apply -f audio-source.yaml
kubectl apply -f audio-relay.yaml

kubectl wait --for=condition=ready pod -l app=audio-source -n audio-demo --timeout=60s
kubectl wait --for=condition=ready pod -l app=audio-relay -n audio-demo --timeout=60s

cd bpf
docker build -t tc-audio-tracer:latest -f Dockerfile.tc .
kind load docker-image tc-audio-tracer:latest --name audio-latency-demo
kubectl apply -f ../k8s/tc-ebpf-tracer.yaml
kubectl wait --for=condition=ready pod -l app=tc-ebpf-tracer --timeout=60s

# http://localhost:30000
   ```
# http://localhost:30001
   ```
# http://localhost:30088

#   - Look for `tc_trace.csv` files
#   - These contain captured interval_ids with timestamps

#kubectl logs -l app=tc-ebpf-tracer --tail=50 | grep -E "Captured|Stats"

# View trace data from a specific node (example)
#kubectl exec -it deployment/trace-viewer -- cat /traces/tc_trace.csv 2>/dev/null || echo "No traces captured yet"

