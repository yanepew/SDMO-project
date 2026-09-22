
#!/usr/bin/env bash

set -e

echo "Starting cloud service..."
python -m cloud.cloud_service &
CLOUD_PID=$!

sleep 2

echo "Starting gateway service..."
python -m gateway.gateway_service &
GATEWAY_PID=$!

sleep 2

echo "Starting legacy device..."
python -m device.legacy_device

echo "Stopping background services..."
kill "$GATEWAY_PID" "$CLOUD_PID" 2>/dev/null || true
