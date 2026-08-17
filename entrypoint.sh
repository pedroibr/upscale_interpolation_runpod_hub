#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Start ComfyUI in the background
echo "Starting ComfyUI in the background..."
python /ComfyUI/main.py --listen &

# Wait for ComfyUI to be ready
echo "Waiting for ComfyUI to be ready..."
max_wait=120  # 최대 2분 대기
wait_count=0
while [ $wait_count -lt $max_wait ]; do
    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "ComfyUI is ready!"
        break
    fi
    echo "Waiting for ComfyUI... ($wait_count/$max_wait)"
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "Error: ComfyUI failed to start within $max_wait seconds"
    exit 1
fi

# RunPod uses the same image for two different workflows:
#
#   MODE_TO_RUN=serverless (default)
#       The SDK owns the foreground process and receives jobs from RunPod.
#   MODE_TO_RUN=pod
#       Keep ComfyUI alive for interactive HTTP/GUI smoke tests.  Starting
#       handler.py here would make the SDK look for test_input.json and exit,
#       which caused the Pod to restart in a loop.
mode="${MODE_TO_RUN:-serverless}"
case "$mode" in
  serverless)
    echo "Starting the Serverless handler..."
    exec python handler.py
    ;;
  pod)
    echo "Pod mode enabled; ComfyUI is ready on port 8188."
    echo "The handler is intentionally not started in Pod mode."
    exec tail -f /dev/null
    ;;
  *)
    echo "Invalid MODE_TO_RUN='$mode' (expected 'serverless' or 'pod')" >&2
    exit 2
    ;;
esac
