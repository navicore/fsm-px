kind delete cluster --name audio-latency-demo
kind create cluster --config kind-config.yaml

docker build -t audio-broadcast:latest audio-source/
docker build -t audio-relay:latest audio-relay/

kind load docker-image audio-broadcast:latest --name audio-latency-demo
kind load docker-image audio-relay:latest --name audio-latency-demo

kubectl apply -f audio-source.yaml
kubectl apply -f audio-relay.yaml

kubectl wait --for=condition=ready pod -l app=audio-source -n audio-demo --timeout=60s
kubectl wait --for=condition=ready pod -l app=audio-relay -n audio-demo --timeout=60s

