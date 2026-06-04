import subprocess
import time

PRIMARY_SSID = "ESP32-Car"
PRIMARY_PASSWORD = "12345678"

FALLBACK_SSID = "ESP32-Car002"
FALLBACK_PASSWORD = "12345678"


def run_cmd(cmd):
    # Run a Windows command and return output
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return ""


def scan_for_ssid(target_ssid):
    # Refresh Windows network cache list.
    run_cmd("netsh wlan scan")
    time.sleep(1.5)
    output = run_cmd("netsh wlan show networks")
    return target_ssid in output


def connect_wifi(ssid, password):
    # Connect to a WiFi network using netsh.
    # Overwrites old cached XML profiles to prevent authentication state mismatches.
    profile_xml = f"""<?xml version="1.0"?>
    <WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
        <name>{ssid}</name>
        <SSIDConfig>
            <SSID>
                <name>{ssid}</name>
            </SSID>
        </SSIDConfig>
        <connectionType>ESS</connectionType>
        <connectionMode>manual</connectionMode>
        <MSM>
            <security>
                <authEncryption>
                    <authentication>WPA2PSK</authentication>
                    <encryption>AES</encryption>
                    <useOneX>false</useOneX>
                </authEncryption>
                <sharedKey>
                    <keyType>passPhrase</keyType>
                    <protected>false</protected>
                    <keyMaterial>{password}</keyMaterial>
                </sharedKey>
            </security>
        </MSM>
    </WLANProfile>
    """

    profile_path = f"{ssid}.xml"
    with open(profile_path, "w") as f:
        f.write(profile_xml)

    # Clean up any existing legacy configurations matching this SSID name
    run_cmd(f'netsh wlan delete profile name="{ssid}"')

    # Add the freshly built XML file
    run_cmd(f'netsh wlan add profile filename="{profile_path}"')

    # Issue an explicit connection command
    run_cmd(f'netsh wlan connect name="{ssid}"')


def connect_to_primary():
    connect_wifi(PRIMARY_SSID, PRIMARY_PASSWORD)


def connect_to_fallback():
    connect_wifi(FALLBACK_SSID, FALLBACK_PASSWORD)


def disconnect_wifi():
    # Disconnect WiFi on Windows
    run_cmd("netsh wlan disconnect")
