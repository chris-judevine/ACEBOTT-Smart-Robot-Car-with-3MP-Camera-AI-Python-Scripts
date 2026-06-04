import cv2
import numpy as np
import requests
import time
from time import sleep
import threading
import queue
import ctypes
import argparse  # Added for handling command-line arguments
import sys

# Import WiFi helper module
import esp32_wifi

# Windows virtual key codes
VK_UP = 0x26
VK_DOWN = 0x28
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_Q = 0x51

user32 = ctypes.windll.user32

def get_manual_key():
    if user32.GetAsyncKeyState(VK_UP) & 0x8000:
        return "UP"
    if user32.GetAsyncKeyState(VK_DOWN) & 0x8000:
        return "DOWN"
    if user32.GetAsyncKeyState(VK_LEFT) & 0x8000:
        return "LEFT"
    if user32.GetAsyncKeyState(VK_RIGHT) & 0x8000:
        return "RIGHT"
    return None

def quit_pressed():
    return user32.GetAsyncKeyState(VK_Q) & 0x8000


# Base URL configuration
BASE_URL = "http://192.168.4.1:81/control"
STREAM_URL = "http://192.168.4.1/Stream"

USE_AUTO_STOP_CMD = False   # firmware brake needs custom test firmware
USE_SLOW_PULSE = True       # extra slow scanning
USE_AI_BRAKE = True         # AI brake


# THREADED VIDEO PIPELINE
class ThreadedVideoGrabber:
    def __init__(self, stream_url):
        self.stream_url = stream_url
        self.cap = cv2.VideoCapture(stream_url)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.ret = False
        self.frame = None
        self.is_running = True
        self.failed_frames = 0

        self.thread = threading.Thread(target=self._grab_frame_worker, daemon=True)
        self.thread.start()

    def _grab_frame_worker(self):
        while self.is_running:
            ret, frame = self.cap.read()
            if ret:
                self.ret = True
                self.frame = frame
                self.failed_frames = 0
            else:
                self.failed_frames += 1
                if self.failed_frames < 60:
                    time.sleep(0.01)
                else:
                    print("\n[Stream Warning] Stream timed out. Allowing ESP32 to flush socket backlog...")
                    self.ret = False
                    self.cap.release()
                    time.sleep(2.0)
                    print("[Stream Recovery] Re-opening video stream socket...")
                    self.cap = cv2.VideoCapture(self.stream_url)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    self.failed_frames = 0

    def read(self):
        return self.ret, self.frame

    def release(self):
        self.is_running = False
        if self.cap.isOpened():
            self.cap.release()


# Asynchronous Network Command Queue
cmd_queue = queue.Queue()

def network_cmd_worker():
    while True:
        try:
            endpoint, timeout_val = cmd_queue.get(timeout=1.0)
            if endpoint is None:
                break
            url = f"{BASE_URL}?{endpoint}"
            requests.get(url, timeout=timeout_val)
            cmd_queue.task_done()
        except queue.Empty:
            continue
        except requests.exceptions.RequestException:
            pass

network_thread = threading.Thread(target=network_cmd_worker, daemon=True)
network_thread.start()


def send_cmd(endpoint, is_startup=False):
    timeout_val = 0.5 if is_startup else 0.15
    cmd_queue.put((endpoint, timeout_val))


def get_movement_cmd(direction):
    cmd_type = "car-auto-stop" if USE_AUTO_STOP_CMD else "car"
    return f"cmd={cmd_type}&direction={direction}"


def clamp_number(num, a, b):
    return max(min(num, max(a, b)), min(a, b))


# KEY STATE
active_manual_key = None
last_manual_key = None


def main():
    global active_manual_key, last_manual_key

    # INITIALIZE AI MODEL CLASSES
    CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
               "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
               "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
               "sofa", "train", "tvmonitor"]

    # SET UP COMMAND LINE ARGUMENT PARSING
    parser = argparse.ArgumentParser(description="AI Object Detector Tracker Car Control System")
    parser.add_argument(
        "target", 
        type=str, 
        nargs="?", 
        default="cat", 
        choices=CLASSES,
        help="The target object class from MobileNetSSD to track (default: cat)"
    )
    args = parser.parse_args()

    TARGET_CLASS_IDX = CLASSES.index(args.target)
    # increase this to decrease false positives .10 is 10 percent goes up to 1 but then it will only lock if it's 100 percent positive of target
    CONFIDENCE_THRESHOLD = 0.10

    print(f"Target selected: Tracking '{args.target.upper()}' (Index: {TARGET_CLASS_IDX})")

    # INTEGRATED: WIFI CONNECT LOOP
    print("Checking WiFi...")
    start_time = time.time()
    connected = False

    while time.time() - start_time < 60:   # Try for up to 60 seconds
        if esp32_wifi.scan_for_ssid(esp32_wifi.PRIMARY_SSID):
            print("Connecting to ESP32-Car...")
            esp32_wifi.connect_to_primary()
            sleep(3)
            connected = True
            break
        elif esp32_wifi.scan_for_ssid(esp32_wifi.FALLBACK_SSID):
            print("Primary not found. Connecting to ESP32-Car002...")
            esp32_wifi.connect_to_fallback()
            sleep(3)
            connected = True
            break
        else:
            print("ESP32 not found. Make sure the car is powered on...")
            sleep(2)

    if not connected:
        print("ERROR: Could not connect to ESP32 after 60 seconds.")
        return

    print("Loading Deep Learning AI Model...")
    net = cv2.dnn.readNetFromCaffe("MobileNetSSD_deploy.prototxt", "MobileNetSSD_deploy.caffemodel")

    print(f"Spawning background thread engine for stream: {STREAM_URL}")
    stream_engine = ThreadedVideoGrabber(STREAM_URL)

    # Hardware Startup Sequence
    sleep(0.5)
    send_cmd("cmd=CAM_LED&value=1", is_startup=True)
    sleep(0.3) 
    current_speed = 3
    send_cmd(f"cmd=speed&value={current_speed}", is_startup=True)
    sleep(0.2)
    y_angle = 90
    send_cmd(f"cmd=servo&angle={y_angle}", is_startup=True)

    # Core Tracking Variables
    current_state = "stop"

    override_active = False
    override_pause_until = 0.0

    # DEBOUNCE RATE LIMITER
    last_movement_cmd_time = 0.0
    MIN_CMD_COOLDOWN = 0.25

    # Pulse scanning variables
    last_pulse_time = time.time()
    pulse_state = True
    PULSE_INTERVAL = 1.0  # 1 second ON, 1 second OFF

    print("Use ARROW KEYS to drive. Press Q to quit.")

    while True:
        ret, frame = stream_engine.read()
        current_time = time.time()

        if not ret or frame is None:
            sleep(0.01)
            continue

        # NON-BLOCKING WINDOWS API KEY POLLING
        active_manual_key = get_manual_key()
        key_changed = (active_manual_key != last_manual_key)
        last_manual_key = active_manual_key

        # QUIT HANDLER
        if quit_pressed():
            send_cmd(get_movement_cmd("stop"))
            sleep(0.05)
            break

        skip_ai_logic = False

        height, width, _ = frame.shape
        center_x = width // 2

        # OVERRIDE LOGIC
        if active_manual_key is not None:

            if not override_active:
                override_active = True
                override_pause_until = 0.0

            if active_manual_key == "UP":
                target_state = "Forward"
            elif active_manual_key == "DOWN":
                target_state = "Backward"
            elif active_manual_key == "LEFT":
                target_state = "Anticlockwise"
            elif active_manual_key == "RIGHT":
                target_state = "Clockwise"
            else:
                target_state = current_state

            if key_changed or current_state != target_state:
                if current_time - last_movement_cmd_time >= MIN_CMD_COOLDOWN:
                    current_state = target_state

                    if current_speed != 3:
                        current_speed = 3
                        send_cmd(f"cmd=speed&value={current_speed}")

                    send_cmd(get_movement_cmd(current_state))
                    last_movement_cmd_time = current_time

            skip_ai_logic = True

        else:
            if override_active:

                if key_changed and current_state != "stop":
                    if current_time - last_movement_cmd_time >= MIN_CMD_COOLDOWN:
                        current_state = "stop"
                        send_cmd(get_movement_cmd("stop"))
                        last_movement_cmd_time = current_time

                if current_time < override_pause_until:
                    cv2.putText(frame, "OVERRIDE RELEASED - PAUSING...", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    skip_ai_logic = True
                else:
                    override_pause_until = 0.0
                    override_active = False

        # COMPUTER VISION AI LOGIC
        if not skip_ai_logic:
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)),
                0.007843,
                (300, 300),
                127.5
            )
            net.setInput(blob)
            detections = net.forward()

            detect_object = False
            coordinate_x = 0
            coordinate_y = 0
            object_area = 0

            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]

                if confidence > CONFIDENCE_THRESHOLD:
                    class_id = int(detections[0, 0, i, 1])

                    # Target evaluated against dynamic argument selection
                    if class_id == TARGET_CLASS_IDX:
                        detect_object = True

                        box = detections[0, 0, i, 3:7] * np.array([width, height, width, height])
                        (startX, startY, endX, endY) = box.astype("int")

                        coordinate_x = (startX + endX) // 2
                        coordinate_y = (startY + endY) // 2
                        
                        # Calculate area for proximity brake logic
                        object_area = (endX - startX) * (endY - startY)

                        label = f"{args.target}: {confidence * 100:.1f}%"
                        cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0), 2)
                        cv2.circle(frame, (coordinate_x, coordinate_y), 5, (0, 0, 255), -1)
                        cv2.putText(frame, label, (startX, startY - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                        break

            # TARGET FOUND
            if detect_object:

                if current_speed != 3:
                    current_speed = 3
                    send_cmd(f"cmd=speed&value={current_speed}")

                # CONDITIONALLY APPLY BRAKING LOGIC BASED ON THE BOOLEAN TOGGLE
                if USE_AI_BRAKE and object_area > 400000:
                    if current_state != "stop":
                        current_state = "stop"
                        send_cmd(get_movement_cmd("stop"))

                    cv2.putText(frame, "TOO CLOSE - STOPPING", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

                    error_y = coordinate_y - (height // 2)
                    if abs(error_y) > 30:
                        y_angle += 2 if error_y > 0 else -2
                        y_angle = clamp_number(y_angle, 0, 180)
                        send_cmd(f"cmd=servo&angle={y_angle}")

                    cv2.imshow("AI Object Detector Tracker", frame)
                    cv2.waitKey(1)
                    continue

                # Camera tilt tracking
                error_y = coordinate_y - (height // 2)
                if abs(error_y) > 30:
                    y_angle += 3 if error_y > 0 else -3
                    y_angle = clamp_number(y_angle, 0, 180)
                    send_cmd(f"cmd=servo&angle={y_angle}")

                # Wheel tracking
                deadzone_width = 60
                left_bound = center_x - deadzone_width
                right_bound = center_x + deadzone_width

                if coordinate_x < left_bound:
                    target_state = "Anticlockwise"
                elif coordinate_x > right_bound:
                    target_state = "Clockwise"
                else:
                    target_state = "Forward"

                if target_state != current_state:
                    current_state = target_state
                    send_cmd(get_movement_cmd(target_state))

            # NO TARGET FOUND ? CLEAN PULSE SCANNING
            else:
                # Toggle pulse every 1 second
                if current_time - last_pulse_time >= PULSE_INTERVAL:
                    pulse_state = not pulse_state
                    last_pulse_time = current_time

                if pulse_state:
                    status_msg = f"SCANNING FOR {args.target.upper()} (1s)"
                    target_state = "Clockwise"
                else:
                    status_msg = "SCAN MODE: PAUSED (1s)"
                    target_state = "stop"

                cv2.putText(frame, status_msg, (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 165, 0), 2)

                # Reset camera tilt
                if y_angle != 90:
                    y_angle = 90
                    send_cmd(f"cmd=servo&angle={y_angle}")

                # Slow scan speed
                if current_speed != 1:
                    current_speed = 1
                    send_cmd(f"cmd=speed&value={current_speed}")

                if current_state != target_state:
                    current_state = target_state
                    send_cmd(get_movement_cmd(target_state))

        cv2.imshow("AI Object Detector Tracker", frame)
        cv2.waitKey(1)

    # CLEAN SHUTDOWN (LED & WIFI DISCONNECT)
    print("\nShutting down...")
    send_cmd(get_movement_cmd("stop"))
    sleep(0.1)

    send_cmd("cmd=CAM_LED&value=0")
    sleep(0.1)

    # Stop the queue worker thread
    cmd_queue.put((None, 0.1))
    stream_engine.release()

    # INTEGRATED: DISCONNECT WIFI ON SHUTDOWN
    print("Disconnecting WiFi...")
    esp32_wifi.disconnect_wifi()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        try:
            requests.get(f"{BASE_URL}?cmd=car&direction=stop", timeout=0.5)
            requests.get(f"{BASE_URL}?cmd=CAM_LED&value=0", timeout=0.5)
            esp32_wifi.disconnect_wifi()
        except:
            pass
        print("\nProgram forced stopped safely.")
