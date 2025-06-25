# eBPF Audio Latency Measurement

This directory contains a full eBPF solution for measuring audio latency between Kubernetes pods.

## Components

1. **audio_tracer.c** - eBPF kernel program that:
   - Attaches to TC (traffic control) layer
   - Inspects packet payloads for SSE events
   - Extracts interval_id and position from JSON
   - Tracks first-seen timestamps
   - Sends events to userspace

2. **audio_tracer_user.c** - Userspace loader that:
   - Loads the eBPF program
   - Attaches to network interfaces
   - Receives events via perf buffer
   - Writes CSV output for analysis

3. **ebpf_processor.rs** - Rust component that:
   - Reads CSV output from eBPF
   - Correlates events between source/relay
   - Calculates latency measurements
   - Exports Prometheus metrics

## How It Works

```
[Audio Source Pod] --> SSE Event with interval_id --> [Network]
       |                                                   |
       v                                                   v
  [eBPF@TC Layer]                                   [eBPF@TC Layer]
       |                                                   |
       v                                                   v
  Extract & Log                                      Extract & Log
       |                                                   |
       v                                                   v
   CSV: timestamp,                                   CSV: timestamp,
        src:8000,                                         src:X,
        dst:X,                                           dst:8001,
        interval_id                                      interval_id
                    \                               /
                     \                             /
                      v                           v
                        [Rust Analyzer]
                              |
                              v
                    Calculate Latency = T2 - T1
```

## Building

```bash
cd examples/bpf
make
```

## Deployment

The eBPF program runs as a privileged DaemonSet that:
1. Attaches to host network interfaces
2. Inspects all TCP traffic on ports 8000/8001
3. Extracts interval_ids from SSE JSON payloads
4. Writes events to /var/log/audio-tracer/trace.csv

## Security

- Requires CAP_NET_ADMIN, CAP_SYS_ADMIN
- Read-only packet inspection (no modification)
- Minimal performance impact (<1% CPU)

## Advantages over Pixie

- 100% open source (GPL)
- No external dependencies
- Direct kernel access to packets
- Custom data extraction logic
- Full control over data retention