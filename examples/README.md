# Audio Broadcast Demo

A Kubernetes application that demonstrates audio streaming with latency measurement. Includes:
- **Audio Source**: Continuously broadcasts voice audio in a loop
- **Audio Relay**: Connects to source and re-broadcasts with configurable latency

## Quick Start

1. **Create a Kind cluster:**
   ```bash
   kind create cluster --config kind-config.yaml
   ```

2. **Build the Docker images:**
   ```bash
   # Build audio source
   docker build -t audio-broadcast:latest audio-source/
   
   # Build audio relay
   docker build -t audio-relay:latest audio-relay/
   ```

3. **Load images into Kind:**
   ```bash
   kind load docker-image audio-broadcast:latest --name audio-latency-demo
   kind load docker-image audio-relay:latest --name audio-latency-demo
   ```

4. **Deploy to Kubernetes:**
   ```bash
   # Deploy audio source
   kubectl apply -f audio-source.yaml
   
   # Deploy audio relay
   kubectl apply -f audio-relay.yaml
   ```

5. **Access the services directly (no port forwarding needed!):**
   - Audio Source: http://localhost:30080
   - Audio Relay: http://localhost:30081

## What It Does

### Audio Source
- Continuously broadcasts voice audio (final_notice.wav) in a loop
- Each loop has a unique `interval_id` for tracking
- Supports multiple simultaneous listeners
- Provides HTTP streaming API via Server-Sent Events

### Audio Relay
- Connects to the audio source as a client
- Re-broadcasts the audio stream on port 8001
- Injects configurable latency (default: 2 seconds)
- Shows measured latency between source and relay
- Perfect for testing latency measurement tools

## Directory Structure

```
examples/
├── audio-source/           # Audio broadcast service
│   ├── Dockerfile
│   ├── audio-loop-server.py
│   └── final_notice.wav
├── audio-relay/            # Audio relay service
│   ├── Dockerfile
│   └── audio-relay-server.py
├── audio-source.yaml       # K8s manifest for source
├── audio-relay.yaml        # K8s manifest for relay
├── kind-config.yaml        # Kind cluster config
└── README.md
```

## API Endpoints

- `/` - Web player interface
- `/stream` - Server-Sent Events audio stream
- `/status` - JSON status of current playback

## Complete Setup from Scratch

```bash
# 1. Delete any existing cluster
kind delete cluster --name audio-latency-demo

# 2. Create new Kind cluster
kind create cluster --config kind-config.yaml

# 3. Build both Docker images
docker build -t audio-broadcast:latest audio-source/
docker build -t audio-relay:latest audio-relay/

# 4. Load both images into Kind
kind load docker-image audio-broadcast:latest --name audio-latency-demo
kind load docker-image audio-relay:latest --name audio-latency-demo

# 5. Deploy both services
kubectl apply -f audio-source.yaml
kubectl apply -f audio-relay.yaml

# 6. Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=audio-source -n audio-demo --timeout=60s
kubectl wait --for=condition=ready pod -l app=audio-relay -n audio-demo --timeout=60s

# 7. Check status
kubectl get all -n audio-demo
```

Now access:
- Audio Source: http://localhost:30080
- Audio Relay: http://localhost:30081 (2 second delay)

## Clean Up

```bash
kubectl delete -f audio-source.yaml audio-relay.yaml
kind delete cluster --name audio-latency-demo
```