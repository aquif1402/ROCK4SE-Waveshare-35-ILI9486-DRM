#!/bin/bash
# Startup wrapper for Brightness Overlay and Compositor
export DISPLAY=:0
export XAUTHORITY=/home/radxa/.Xauthority

echo "Waiting for Xorg display :0..."
for i in $(seq 1 30); do
    if xset q >/dev/null 2>&1 || xdpyinfo >/dev/null 2>&1; then
        echo "Xorg is ready on :0."
        break
    fi
    sleep 1
done

# Ensure xcompmgr compositor is running with proper compositing flags
if ! pgrep -x "xcompmgr" >/dev/null; then
    echo "Starting xcompmgr compositor (-c -C -F)..."
    nohup xcompmgr -c -C -F </dev/null >/dev/null 2>&1 &
    sleep 1
fi

echo "Launching Brightness Overlay daemon..."
exec /usr/bin/python3 /home/radxa/brightness_overlay.py
