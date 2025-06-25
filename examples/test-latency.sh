#!/bin/bash
# Test script to measure latency between audio source and relay

echo "Testing audio latency measurement..."

# Get the current interval_id from source
SOURCE_STATUS=$(curl -s http://localhost:30080/status)
INTERVAL_ID=$(echo $SOURCE_STATUS | jq -r .interval_id)
POSITION=$(echo $SOURCE_STATUS | jq -r .current_position)

echo "Source interval_id: $INTERVAL_ID at position $POSITION"

# Check relay status
RELAY_STATUS=$(curl -s http://localhost:30081/status)
echo "Relay status:"
echo $RELAY_STATUS | jq .

# Start capturing SSE events from both
echo "Capturing SSE events..."

# Capture from source
timeout 5 curl -s http://localhost:30080/stream | grep "data:" | head -5 > /tmp/source_events.txt &

# Capture from relay  
timeout 5 curl -s http://localhost:30081/stream | grep "data:" | head -5 > /tmp/relay_events.txt &

wait

echo -e "\nSource events:"
cat /tmp/source_events.txt | jq -r '. | select(.interval_id) | "\(.timestamp) \(.interval_id) pos=\(.position)"' 2>/dev/null || cat /tmp/source_events.txt

echo -e "\nRelay events:"
cat /tmp/relay_events.txt | jq -r '. | select(.interval_id) | "\(.relay_timestamp) \(.interval_id) pos=\(.position) delay=\(.configured_delay_ms)ms"' 2>/dev/null || cat /tmp/relay_events.txt

# Extract timestamps and calculate latency
echo -e "\nCalculating latencies..."

# Simple latency calculation
SOURCE_TS=$(cat /tmp/source_events.txt | head -1 | grep -o '"timestamp":[0-9]*' | cut -d: -f2)
RELAY_TS=$(cat /tmp/relay_events.txt | head -1 | grep -o '"relay_timestamp":[0-9]*' | cut -d: -f2)

if [ ! -z "$SOURCE_TS" ] && [ ! -z "$RELAY_TS" ]; then
    LATENCY=$((RELAY_TS - SOURCE_TS))
    echo "Measured latency: ${LATENCY}ms"
else
    echo "Could not calculate latency - missing timestamps"
fi