# Audio Latency Measurement System - Project Memory

## Project Overview
A Rust-based distributed system for measuring audio processing latency across Kubernetes pods using Pixie's eBPF instrumentation. Designed to identify multi-second latency issues in audio streaming services.

## Architecture Summary
- **Deployment Model**: Kubernetes DaemonSet (one pod per node)
- **Data Collection**: Pixie eBPF for packet capture (already deployed)
- **Processing**: Rust pods query Pixie API for local traffic only
- **Coordination**: Lightweight signature broadcasts between DaemonSet pods
- **Output**: Prometheus metrics with latency measurements

## Key Design Decisions

### 1. DaemonSet over Sidecar
- Originally considered sidecar pattern but determined unnecessary
- DaemonSet provides single approval path and efficient resource usage
- Each pod processes only local node traffic via Pixie API

### 2. Distributed Signature Detection
- Source pods (telephony) detect "signature-worthy" audio moments
- Broadcast only signatures (64-bit hash + metadata), not audio data
- Other pods search their local traffic for matching signatures
- Prevents doubling network load from audio streams

### 3. Metadata Association
- Audio packets contain UUIDs (interval_id, segment_id) in envelopes
- Extraction patterns defined in YAML config
- Supports both binary and JSON envelope formats
- Associates latency measurements with user context

## Technical Stack
- **Language**: Rust (async with Tokio)
- **Data Source**: Pixie's vizier-query-broker gRPC API
- **Data Format**: Arrow Flight batches
- **Metrics**: Prometheus histograms
- **Configuration**: YAML with PxL scripts

## Current Implementation Status

### Completed
- ✅ Configuration system for flexible measurement definitions
- ✅ Signature detection with multiple VAD modes
- ✅ Metadata extraction from packet envelopes
- ✅ Basic orchestration logic for distributed detection
- ✅ Project structure with dependencies

### TODO
- 🔲 Implement actual Pixie gRPC client connection
- 🔲 Add inter-pod communication (gRPC or Redis pub/sub)
- 🔲 Implement robust stream reassembly for multi-packet signatures
- 🔲 Add production-ready VAD algorithms
- 🔲 Create Kubernetes manifests for DaemonSet
- 🔲 Add Prometheus metrics endpoint
- 🔲 Implement TTL cleanup for orphaned signatures
- 🔲 Add health checks and readiness probes

## Important File Locations
- `src/config.rs` - Configuration structures and measurement definitions
- `src/signature_detector.rs` - Audio signature detection logic
- `src/main.rs` - Main orchestration and Pixie integration
- `example-config.yaml` - Example measurement configuration
- `notes.txt` - Original architecture notes and Pixie integration examples

## Pixie Integration Notes
- Pixie PEMs already capture all TCP/TLS traffic via eBPF
- Query using PxL scripts to filter relevant audio packets
- Use `socket_data` table with filters on port/pod names
- Arrow Flight gRPC streaming for efficient data transfer
- No need to modify Pixie or run additional eBPF

## Audio Processing Approach
1. Buffer packets to accumulate sufficient audio duration
2. Apply VAD (Voice Activity Detection) to find speech segments
3. Generate perceptual hash as signature
4. Extract metadata (UUIDs) from packet envelopes
5. Broadcast signature events to other pods

## Configuration Philosophy
- Measurements defined declaratively in YAML
- PxL scripts embedded for Pixie queries
- Pluggable VAD modes (energy, zero-crossing, spectral, ML)
- Flexible metadata extraction patterns
- Per-measurement TTL and grouping settings

## Testing Strategy
- Start with energy-based VAD for simplicity
- Use port 15000 (Pulsar) as initial target
- Test with 10 parallel audio streams
- Verify signature matching across 3+ pods
- Monitor Prometheus metrics for latency distribution

## Performance Considerations
- Pixie already deduplicates and batches data
- Expected throughput: 1-2 MB/s per pod
- Sampling rate configurable to reduce processing
- P95 overhead target: <1ms per audio frame
- Memory bounded by signature TTL settings