# Optional ACEBOTT Smart Car V1 - Firmware (Modified) - Car Body ESP32 Board

A modified version of the stock **ACEBOTT Smart Car V1 ESP32-CAM firmware**. This update extends the default configuration web server by adding new command set with auto-braking mechanics.

---

## 🛠️ Hardware Profile

* **Base Platform**: ACEBOTT Smart Car V1 (ESP32-CAM Core Module)

---

### New Command Set with Auto-Stop

| Target URI Target | Movement Vector | Execution Profile |
| --- | --- | --- |
| `http://192.168.4.1:81/control?control?cmd=car-auto-stop&direction=Forward` | Longitudinal Forward | Translates to forward drive with timeout/auto-braking safety. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=Backward` | Longitudinal Reverse | Translates to reverse drive with timeout/auto-braking safety. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=Left` | Lateral Strafe Left | Lateral side-stepping vector using mecanum orientation. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=Right` | Lateral Strafe Right | Lateral side-stepping vector using mecanum orientation. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=Clockwise` | Axial Rotation CW | Rotates the chassis on its central axis clockwise. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=Anticlockwise` | Axial Rotation CCW | Rotates the chassis on its central axis counter-clockwise. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=LeftUp` | Diagonal Forward-Left | $45^\circ$ forward-left diagonal vector. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=RightUp` | Diagonal Forward-Right | $45^\circ$ forward-right diagonal vector. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=LeftDown` | Diagonal Backward-Left | $45^\circ$ rearward-left diagonal vector. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=RightDown` | Diagonal Backward-Right | $45^\circ$ rearward-right diagonal vector. |
| `http://192.168.4.1:81/control?/control?cmd=car-auto-stop&direction=stop` | Hard Stop | Instantly clears all motor PWM/direction lines. |

---


## 🚀 Flashing & Validation

1. Open your modified project root inside the **Arduino IDE**.
2. Install version 2 of the Arduino core for the ESP32, and all ACEBOTT libraries.
3. Select your target board configuration profile (**ESP32-WROOM-DA Module**).
4. Flash the binary to Car Body ESP32 Board
5. Connect your development computer or automation client to the local `ESP32-Car` Wi-Fi access network, and use `curl` or any HTTP module to dispatch instructions cleanly:

```bash
curl "http://192.168.4.1:81/control?cmd=car-auto-stop&direction=Forward"

```
