# Using bpftrace for Audio Latency Measurement

This approach uses bpftrace (100% open source) instead of Pixie for measuring audio latency between pods.

## Architecture

1. **bpftrace DaemonSet**: Runs on each node, traces kernel TCP functions
2. **Output Files**: Writes trace data to host volume (`/var/log/audio-tracer/`)
3. **Rust Analyzer**: Reads trace files, correlates interval_ids, calculates latency

## Benefits over Pixie

- ✅ Completely open source (GPL v2)
- ✅ No external dependencies or cloud services
- ✅ Direct kernel access to packet data
- ✅ Lightweight (just bpftrace binary)
- ✅ Full control over data collection

## Deployment

```bash
# Deploy bpftrace DaemonSet
kubectl apply -f k8s/bpftrace-daemonset.yaml

# Verify it's running
kubectl get pods -l app=audio-latency-tracer

# Check trace output (on any node)
kubectl exec -it <tracer-pod> -- tail -f /output/trace.log
```

## How It Works

1. bpftrace hooks into `tcp_v4_do_rcv` to catch incoming TCP packets
2. Filters for ports 8000 (source) and 8001 (relay)
3. When SSE data arrives, extracts the interval_id from JSON
4. Writes: `timestamp,source,dest,interval_id,position`
5. Rust analyzer reads these files and matches interval_ids to calculate latency

## Next Steps

1. Enhance bpftrace script to properly parse SSE JSON data
2. Add IP address extraction for multi-node scenarios
3. Create Rust file watcher to process trace output in real-time
4. Add Prometheus metrics export for visualization

## Alternative: tc-bpf

For even more control, we could use tc-bpf (traffic control BPF) which can:
- Inspect packets at the network interface level
- Parse HTTP headers and payloads
- Work with any protocol (not just TCP)

But bpftrace is simpler to get started with and sufficient for this use case.