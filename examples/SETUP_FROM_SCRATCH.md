# Audio Latency Measurement System - Complete Setup Guide

## Current Status
- ✅ Kind cluster created and running (ARM64)
- ✅ TC eBPF tracer built and deployed successfully
- ✅ Audio-relay service running
- ❌ Audio-source service crashing (WAV file read issue)

## Known Issues
1. The audio-source.yaml had wrong image name (audio-broadcast vs audio-source) - FIXED
2. The audio-source Go code has an unused import - FIXED
3. The audio-source is failing to read the WAV file with "EOF" error - INVESTIGATING

This guide will help you set up a complete audio latency measurement system using eBPF in Kubernetes.

## Prerequisites

- Docker Desktop running
- `kind` installed
- `kubectl` installed
- Go 1.21+ installed (for building locally if needed)

## Step 1: Clean Up Any Existing Resources

```bash
# Delete existing kind cluster
kind delete cluster --name audio-latency-demo

# Remove old Docker images
docker rmi audio-source:latest audio-relay:latest tc-audio-tracer:latest 2>/dev/null || true
```

## Step 2: Create Kind Cluster

```bash
cd /Users/navicore/git/navicore/fsm-px/examples

# Create the cluster
kind create cluster --name audio-latency-demo --config kind-config.yaml

# Verify cluster is running
kubectl cluster-info
kubectl get nodes
```

## Step 3: Build and Load Audio Services

```bash
# Build audio-source
cd audio-source
docker build -t audio-source:latest .
cd ..

# Build audio-relay
cd audio-relay
docker build -t audio-relay:latest .
cd ..

# Load images into kind
kind load docker-image audio-source:latest --name audio-latency-demo
kind load docker-image audio-relay:latest --name audio-latency-demo
```

## Step 4: Deploy Audio Services

```bash
# Deploy both services
kubectl apply -f audio-source.yaml
kubectl apply -f audio-relay.yaml

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=audio-source -n audio-demo --timeout=60s
kubectl wait --for=condition=ready pod -l app=audio-relay -n audio-demo --timeout=60s

# Verify services are running
kubectl get pods -n audio-demo
kubectl get svc -n audio-demo
```

## Step 5: Build and Deploy TC eBPF Tracer

```bash
cd bpf

# Build the TC eBPF tracer
docker build -t tc-audio-tracer:latest -f Dockerfile.tc .

# Load into kind
kind load docker-image tc-audio-tracer:latest --name audio-latency-demo

# Deploy the tracer
kubectl apply -f ../k8s/tc-ebpf-tracer.yaml

# Wait for DaemonSet to be ready
kubectl wait --for=condition=ready pod -l app=tc-ebpf-tracer --timeout=60s

# Verify tracer is running
kubectl get pods -l app=tc-ebpf-tracer
kubectl logs -l app=tc-ebpf-tracer --tail=20
```

## Step 6: Test the System

1. **Open Audio Source** (generates audio with interval IDs):
   ```
   http://localhost:30000
   ```
   - Click "Connect to Audio Stream"
   - You should hear audio playing

2. **Open Audio Relay** (adds configurable latency):
   ```
   http://localhost:30001
   ```
   - Click "Connect to Audio Stream"
   - Use the delay slider to add 0-15 seconds of latency
   - The measured latency should appear on screen

3. **View Captured Traces**:
   ```
   http://localhost:30088
   ```
   - Look for `tc_trace.csv` files
   - These contain captured interval_ids with timestamps

## Step 7: Verify eBPF Capture

```bash
# Check tracer logs for captured events
kubectl logs -l app=tc-ebpf-tracer --tail=50 | grep -E "Captured|Stats"

# View trace data from a specific node (example)
kubectl exec -it deployment/trace-viewer -- cat /traces/tc_trace.csv 2>/dev/null || echo "No traces captured yet"

# Or check a specific tracer pod
kubectl exec -it $(kubectl get pod -l app=tc-ebpf-tracer -o jsonpath='{.items[0].metadata.name}') -- cat /output/tc_trace.csv 2>/dev/null || echo "No traces captured yet"
```

## Expected Results

When audio is streaming between services, you should see:

1. **In the tracer logs**: Messages like "Captured: 10.244.x.x:8000 -> 10.244.x.x:xxxxx interval_id=<uuid>"
2. **In the CSV files**: Rows with timestamp, IPs, ports, interval_id, position, and direction
3. **In the browser**: Audio playing with latency measurements displayed

## Troubleshooting

### No events captured
- Make sure audio is actively streaming (press "Connect to Audio Stream" in browser)
- Check that services are in the same namespace or can communicate
- Verify TC is attached: `kubectl logs -l app=tc-ebpf-tracer | grep "Attached to interface"`

### Pods not starting
- Check logs: `kubectl logs -l app=<app-name>`
- Ensure images are loaded: `kind load docker-image <image-name> --name audio-latency-demo`

### Can't access services
- Verify NodePort services: `kubectl get svc -A | grep NodePort`
- Check firewall isn't blocking ports 30000, 30001, 30088

## Architecture Overview

```
Browser -> NodePort 30000 -> audio-source pod
                                    |
                                    v
                              SSE stream with interval_ids
                                    |
                                    v
                            TC eBPF tracer (captures packets)
                                    |
                                    v
Browser -> NodePort 30001 -> audio-relay pod (adds latency)
```

The TC eBPF tracer runs on each node and captures packets on veth interfaces, extracting interval_ids from SSE JSON payloads to measure latency between services.