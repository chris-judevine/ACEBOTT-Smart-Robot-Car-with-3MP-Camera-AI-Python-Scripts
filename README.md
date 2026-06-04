# ESP32 Smart Car Control & Tracking System (ACEBOTT V1 and V2)

An intelligent control system written in Python that interfaces with an ESP32-CAM smart car. The system handles automated network profiles on Windows to establish car connectivity, streams live video over a threaded pipeline, and offers two unique tracking/control modes: deep learning object tracking via **MobileNetSSD** or dynamic chromatic tracking via **HSV thresholding**.

## Features

* **Dual Tracking Engines:**
* **AI Object Tracking:** Leverages a Caffe-based MobileNetSSD model to track complex objects (default: cats).
* **Chromatic HSV Tracking:** Automatically translates a command-line hex color into dynamic HSV bounds to follow physical objects.


* **Threaded Video Pipeline:** Offloads OpenCV frame grabbing to a background thread to maximize network frame rates and gracefully handle ESP32 socket backlog flushes.
* **Asynchronous Command Queue:** Minimizes main-loop latency by using a non-blocking `queue.Queue` background thread for outbound HTTP requests to the car's endpoints.
* **Automated Windows Network Engine:** Scans for, authenticates, and actively switches between primary (`ESP32-Car`) and fallback (`ESP32-Car002`) SSIDs by writing freshly built XML profiles to `netsh`.
* **Manual Override & Safety Systems:** Polled Windows Virtual Key codes provide immediate directional keyboard driving (Arrow keys) that overrides AI logic. Includes proximity **AI Braking** protection.

---

## Architecture Overview

* `esp32_wifi.py`: Helper Script to connect to and disconnect from ESP32 Robot Cars Wifi AP
* `ai_tracker.py`: Object Tacking via MobileNetSSD object classification.
* `color_tracker.py`: Color Tacking script.

---

## Hardware Configuration Defaults

The scripts expect the ESP32 camera and firmware controller to be listening on the ACEBOTT'S standard access point gateway configuration:

| Setting | Endpoint URL | Description |
| --- | --- | --- |
| **Base Control API** | `[http://192.168.4.1:81/control](http://192.168.4.1:81/control)` | Accepts speed, camera LED, servo angle, and directional queries. |
| **Video Stream AP** | `[http://192.168.4.1/Stream](http://192.168.4.1/Stream)` | MJPEG Video stream server channel. |

---

## Requirements & Dependencies

The control system depends on a standard Python 3.x environment alongside a **Windows OS architecture** (due to native calls to `ctypes.windll.user32` and `netsh`).
(To Port to different system the Key scanning routines need to be changed and Wifi autoconnect script need to be changed or removed).
```bash
python -m pip install opencv-python numpy requests

```

### Required AI Model Files (For Object Tracking Only)

To run the AI object tracking script, place the official MobileNetSSD pre-trained model files in your root directory:

* `MobileNetSSD_deploy.prototxt`
* `MobileNetSSD_deploy.caffemodel`

---

## Usage Instructions

Run the respective tracker scripts from your terminal. Both modules support dynamic configuration via command-line arguments.

### 1. Running the Deep Learning Object Tracker

By default, the script initializes to find and follow **cats**. You can optionally pass any supported MobileNetSSD target string class as a positional argument:

```bash
# Default (Tracks cats)
python ai_tracker.py

# Track a person or a car instead
python ai_tracker.py person
python ai_tracker.py car

```

### 2. Running the Chromatic Color Tracker

Pass a hexadecimal color value directly as a trailing command-line argument. The system will convert it into target HSV upper and lower bounds:

```bash
# Default (Track a red object)
python color_tracker.py

# Track a vibrant green object
python color_tracker.py #00FF00

```

### 3. Manual Keyboard Controls

Whenever a camera stream window is active, the system listens directly to your OS keystrokes:

* **Arrow Keys (`Up` / `Down` / `Left` / `Right`):** Instantly overrides the camera's auto-tracking routine to drive the vehicle manually.
* **`Q` Key:** Breaks loop execution, signals a safety halt to the vehicle, turns off the camera LED, and cleanly updates Windows to disconnect from the car access point.

---

## Core Software Toggles

Inside both tracking scripts, you can customize the vehicle's handling characteristics by toggling these global booleans:

```python
USE_AI_BRAKE = True         # Set to True to halt forward progression if target fills the frame

```
