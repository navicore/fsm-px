# Audio Latency Measurement System (fsm-px)

A distributed system for measuring audio processing latency across Kubernetes pods using Pixie's eBPF instrumentation. This project helps identify where multi-second latency is introduced in audio streaming pipelines.

## Problem Statement

In our Kubernetes-based audio streaming SaaS, we're experiencing multi-second latency between audio source and downstream processing components. Traditional APM tools lack the granularity to track individual audio segments across distributed systems. We need to:

1. Identify specific points in audio streams (signatures)
2. Track when those exact points are processed by different services
3. Measure the latency between processing stages
4. Associate measurements with user context (interval/segment IDs)

## Solution Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Kubernetes Node A                          │
│  ┌─────────────┐         ┌────────────────────────────┐    │
│  │ Telephony   │ ←────── │ Pixie PEM (eBPF capture)  │    │
│  │   Pod       │         └────────────────────────────┘    │
│  └─────────────┘                      │                     │
│                                       ↓                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Audio Latency Sensor (Rust DaemonSet Pod)           │   │
│  │ • Queries local Pixie for telephony traffic         │   │
│  │ • Detects signature-worthy audio moments            │   │
│  │ • Broadcasts: "Look for signature XYZ at time T"    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────┘
                  │ Lightweight signature broadcast
┌─────────────────▼───────────────────────────────────────────┐
│                   Kubernetes Node B                          │
│  ┌─────────────┐         ┌────────────────────────────┐    │
│  │ Processing  │ ←────── │ Pixie PEM (eBPF capture)  │    │
│  │   Pod       │         └────────────────────────────┘    │
│  └─────────────┘                      │                     │
│                                       ↓                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Audio Latency Sensor (Rust DaemonSet Pod)           │   │
│  │ • Receives signature broadcast                      │   │
│  │ • Searches local traffic for matching audio        │   │
│  │ • Records: "Found XYZ at time T+Δ"                 │   │
│  │ • Exports latency metrics to Prometheus            │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Key Features

- **Zero application changes**: Uses Pixie's existing eBPF instrumentation
- **Distributed detection**: Each node processes only its local traffic
- **Efficient coordination**: Only 64-bit signatures broadcast between nodes
- **Flexible configuration**: YAML-based measurement definitions
- **User context aware**: Extracts UUIDs from packet envelopes
- **Multiple measurements**: Track different latency types simultaneously

## Quick Start

1. **Prerequisites**
   - Kubernetes cluster with Pixie installed
   - Prometheus for metrics collection
   - Audio services using TCP/TLS (captured by Pixie)

2. **Configure measurements**
   ```yaml
   # config.yaml
   measurements:
     - name: "call_start_latency"
       signature_rules:
         stream_filter: |
           df = px.DataFrame(table='socket_data')
           df = df[df.pod_name.contains('telephony')]
         audio_criteria:
           min_duration_ms: 500
           energy_threshold: 0.3
       metadata_extraction:
         id_patterns:
           - pattern: "interval_id\":\"([a-f0-9-]{36})"
             id_type: "interval_id"
   ```

3. **Deploy as DaemonSet**
   ```bash
   kubectl apply -f k8s/daemonset.yaml
   ```

4. **View metrics**
   ```
   audio_latency_seconds{measurement="call_start_latency", interval_id="...", pod="..."}
   ```

## How It Works

1. **Signature Detection**
   - Telephony pods generate audio that flows through the system
   - Local sensor detects "interesting" audio moments (speech start, energy spike)
   - Generates perceptual hash as signature
   - Extracts metadata (interval_id) from packet envelope

2. **Signature Broadcasting**
   - Detected signatures broadcast to all sensor pods
   - Message contains: signature hash, timestamp, metadata
   - Typical size: <1KB per signature

3. **Matching & Measurement**
   - Each sensor searches its local traffic for matching signatures
   - When found, calculates latency from original timestamp
   - Records metric with full context (interval_id, pod names)

## Configuration

See `example-config.yaml` for detailed configuration options:
- PxL scripts for traffic filtering
- Audio detection criteria (VAD modes, thresholds)
- Metadata extraction patterns
- Measurement grouping and TTL settings

## Development

```bash
# Install dependencies
cargo build

# Run tests
cargo test

# Run locally (requires Pixie access)
PIXIE_CLUSTER=your-cluster cargo run
```

## Monitoring

The system exports Prometheus metrics:
- `audio_latency_seconds`: Histogram of processing latency
- `signatures_detected_total`: Counter of detected signatures
- `signatures_matched_total`: Counter of successful matches
- `active_signatures`: Gauge of signatures being tracked

## Design Rationale

- **Why not sidecar?** No need for traffic interception; Pixie already captures everything
- **Why DaemonSet?** Efficient local processing, single approval needed
- **Why Rust?** Performance for audio processing, memory safety, good async support
- **Why broadcast signatures?** Avoids shipping all audio data between nodes

## Future Enhancements

- [ ] ML-based VAD for better speech detection
- [ ] Support for encrypted audio protocols
- [ ] Real-time latency alerting
- [ ] Web UI for signature visualization
- [ ] Historical latency analysis

## Contributing

This is an internal project. For questions or contributions, contact the platform team.

## License

Proprietary - Internal Use Only