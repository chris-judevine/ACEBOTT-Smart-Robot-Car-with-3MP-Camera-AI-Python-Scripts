import cv2
import numpy as np
import requests
import time
from time import sleep
import ctypes
import threading
import argparse  

# Import WiFi helper module
import esp32_wifi

# Command set toggle
USE_AUTO_STOP_CMD = False   # firmware brake requires custom firmware

# AI Brake Toggle
USE_AI_BRAKE = True         # True enables AI brake if too close

def get_movement_cmd(direction):
    """Return correct command based on toggle."""
    cmd_type = "car-auto-stop" if USE_AUTO_STOP_CMD else "car"
    return f"cmd={cmd_type}&direction={direction}"


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

def send_cmd(endpoint, is_startup=False):
    try:
        url = f"{BASE_URL}?{endpoint}"
        timeout_val = 0.5 if is_startup else 0.15
        requests.get(url, timeout=timeout_val)
    except requests.exceptions.RequestException:
        pass

def clamp_number(num, a, b):
    return max(min(num, max(a, b)), min(a, b))


def hex_to_hsv_bounds(hex_str, h_window=10, s_window=75, v_window=90):
    """
    Converts a hex color string into dynamic lower and upper HSV bound pairings.
    Returns a list of tuples containing (lower_bound, upper_bound).
    """
    hex_str = hex_str.lstrip('#')
    
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    
    rgb_pixel = np.uint8([[[b, g, r]]])
    hsv_pixel = cv2.cvtColor(rgb_pixel, cv2.COLOR_BGR2HSV)[0][0]
    
    target_h = int(hsv_pixel[0])
    target_s = int(hsv_pixel[1])
    target_v = int(hsv_pixel[2])
    
    h_low = target_h - h_window
    h_high = target_h + h_window
    
    s_low = max(target_s - s_window, 40)
    s_high = min(target_s + s_window, 255)
    
    v_low = max(target_v - v_window, 40)
    v_high = min(target_v + v_window, 255)
    
    bounds = []
    
    if h_low < 0:
        bounds.append((np.array([0, s_low, v_low]), np.array([h_high, s_high, v_high])))
        bounds.append((np.array([180 + h_low, s_low, v_low]), np.array([179, s_high, v_high])))
    elif h_high > 179:
        bounds.append((np.array([h_low, s_low, v_low]), np.array([179, s_high, v_high])))
        bounds.append((np.array([0, s_low, v_low]), np.array([h_high - 180, s_high, v_high])))
    else:
        bounds.append((np.array([h_low, s_low, v_low]), np.array([h_high, s_high, v_high])))
        
    return bounds


# THREAD-SAFE VIDEO PIPELINE
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


def main():
    # SET UP COMMAND LINE ARGUMENT HANDLING
    parser = argparse.ArgumentParser(description="Dynamic Color Tracking Car System")
    parser.add_argument(
        "color", 
        type=str, 
        nargs="?", 
        default=None, 
        help="Target tracking hue hex code string. (Example: FF0000 or #00FF00)"
    )
    args = parser.parse_args()

    dynamic_bounds = None
    if args.color:
        try:
            dynamic_bounds = hex_to_hsv_bounds(args.color)
            print(f"Custom Target Initialized: Calculated middle matrix ranges for Hex value: {args.color}")
        except Exception as e:
            print(f"Error parsing hex string context format: {e}. Falling back to default red configurations.")
            dynamic_bounds = None

    # WIFI CONNECT LOOP
    print("Checking WiFi...")
    start_time = time.time()
    connected = False

    while time.time() - start_time < 60:
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

    # START VIDEO STREAM VIA THREADED PIPELINE
    print(f"Spawning background thread engine for stream: {STREAM_URL}")
    stream_engine = ThreadedVideoGrabber(STREAM_URL)

    sleep(0.5)

    print("Turning on the camera LED...")
    send_cmd("cmd=CAM_LED&value=1", is_startup=True)
    sleep(0.3)

    current_speed = 3
    send_cmd(f"cmd=speed&value={current_speed}", is_startup=True)
    sleep(0.2)

    y_angle = 90
    send_cmd(f"cmd=servo&angle={y_angle}", is_startup=True)

    current_state = "stop"

    active_manual_key = None
    last_manual_key = None
    override_active = False
    override_pause_until = 0.0

    last_movement_cmd_time = 0.0
    MIN_CMD_COOLDOWN = 0.25

    print("\nTracking system initialized.")
    print("Use ARROW KEYS to drive manually. Press Q to quit.")

    while True:
        ret, frame = stream_engine.read()
        if not ret or frame is None:
            sleep(0.01)
            continue

        height, width, _ = frame.shape
        center_x = width // 2

        # MANUAL OVERRIDE LOGIC
        active_manual_key = get_manual_key()
        key_changed = (active_manual_key != last_manual_key)
        last_manual_key = active_manual_key
        current_time = time.time()

        if quit_pressed():
            send_cmd(get_movement_cmd("stop"))
            break

        skip_ai_logic = False

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

        # AI LOGIC (COLOR CHROMATIC TRACKING)
        if not skip_ai_logic:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            
            if dynamic_bounds is not None:
                mask = cv2.inRange(hsv, dynamic_bounds[0][0], dynamic_bounds[0][1])
                for additional_bound in dynamic_bounds[1:]:
                    mask += cv2.inRange(hsv, additional_bound[0], additional_bound[1])
            else:
                lower_red1, upper_red1 = np.array([0, 120, 70]), np.array([10, 255, 255])
                lower_red2, upper_red2 = np.array([170, 120, 70]), np.array([180, 255, 255])
                mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            detect_object = False
            coordinate_x = 0
            coordinate_y = 0
            object_area = 0

            if len(contours) > 0:
                largest = max(contours, key=cv2.contourArea)
                object_area = cv2.contourArea(largest)

                if object_area > 250:
                    detect_object = True
                    M = cv2.moments(largest)
                    if M["m00"] != 0:
                        coordinate_x = int(M["m10"] / M["m00"])
                        coordinate_y = int(M["m11"] / M["m00"])

                    x, y, w, h = cv2.boundingRect(largest)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.circle(frame, (coordinate_x, coordinate_y), 7, (0, 255, 0), -1)

            if detect_object:
                if current_speed != 3:
                    current_speed = 3
                    send_cmd(f"cmd=speed&value={current_speed}")

                if USE_AI_BRAKE and object_area > 40000:
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

                    cv2.imshow("HTTP Car Object Tracker", frame)
                    cv2.waitKey(1)
                    continue

                error_y = coordinate_y - (height // 2)
                if abs(error_y) > 30:
                    y_angle += 3 if error_y > 0 else -3
                    y_angle = clamp_number(y_angle, 0, 180)
                    send_cmd(f"cmd=servo&angle={y_angle}")

                deadzone = 60
                left = center_x - deadzone
                right = center_x + deadzone

                if coordinate_x < left:
                    target_state = "Anticlockwise"
                elif coordinate_x > right:
                    target_state = "Clockwise"
                else:
                    target_state = "Forward"

                if target_state != current_state:
                    current_state = target_state
                    send_cmd(get_movement_cmd(target_state))
            else:
                cv2.putText(frame, "SCANNING... SPINNING CLOCKWISE", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 0), 2)

                if y_angle != 90:
                    y_angle = 90
                    send_cmd(f"cmd=servo&angle={y_angle}")

                if current_speed != 1:
                    current_speed = 1
                    send_cmd(f"cmd=speed&value={current_speed}")

                if current_state != "Clockwise":
                    current_state = "Clockwise"
                    send_cmd(get_movement_cmd("Clockwise"))

        cv2.imshow("HTTP Car Object Tracker", frame)
        cv2.waitKey(1)

    # CLEAN SHUTDOWN + WIFI DISCONNECT
    print("\nShutting down...")
    send_cmd(get_movement_cmd("stop"))
    sleep(0.1)
    send_cmd("cmd=CAM_LED&value=0")

    stream_engine.release()

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