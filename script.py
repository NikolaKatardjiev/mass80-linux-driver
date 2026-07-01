import serial
import json
import os
import subprocess
from datetime import datetime

# Adjust this to your actual serial port if it differs
SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200

def handle_media_key(key_name):
    """Executes Linux track skipping and play/pause commands."""
    print(f"Triggering Button: {key_name}")
    env = os.environ.copy()
    
    try:
        if key_name == "Next":
            subprocess.run(["playerctl", "next"], env=env)
        elif key_name == "Pervious":  # Match firmware typo
            subprocess.run(["playerctl", "previous"], env=env)
        elif key_name == "Play" or key_name == "Pause":
            subprocess.run(["playerctl", "--all-players", "play-pause"], env=env)
        elif key_name in ["Vol +", "Vol -"]:
            # Query the current volume percentage from pactl
            res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], 
                                 capture_output=True, text=True, env=env)
            
            # Extract the percentage integer from pactl's output string (e.g., "Volume: front-left: 65536 / 100% / 0.00 dB")
            try:
                current_vol = int(res.stdout.split('%')[0].split()[-1])
            except (IndexError, ValueError):
                current_vol = 50  # Fallback safety default if parsing fails
            
            if key_name == "Vol +":
                # Add 5%, but freeze it if it hits or goes over 100%
                new_vol = min(current_vol + 5, 100)
            else:
                # Subtract 5%, floor it at 0%
                new_vol = max(current_vol - 5, 0)

            print(f"Incremental Volume Adjustment: {current_vol}% -> {new_vol}%")
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{new_vol}%"], env=env)
    except Exception as e:
        print(f"Failed to execute button command for {key_name}: {e}")

def handle_slider_change(action, value):
    """Handles percentage-based sliders for Volume and Monitor Brightness."""
    print(f"Slider Update -> {action}: {value}%")
    env = os.environ.copy()
    
    try:
        if action == "volume":
            # Set absolute audio volume directly to the slider value (e.g., 70%)
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"], env=env)
            
    except Exception as e:
        print(f"Failed to execute slider adjustment for {action}: {e}")

def send_time_heartbeat(ser):
    """Sends the current system time to the keyboard to prevent screen sleep."""
    now = datetime.now()
    time_payload = {
        "action": "set_time",
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second
    }
    json_string = json.dumps(time_payload) + "\n"
    ser.write(json_string.encode('utf-8'))
    ser.flush()

def main():
    print(f"Connecting to Mass80 on {SERIAL_PORT}...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    except Exception as e:
        print(f"Error opening port: {e}")
        return

    print("System active. Audio, Brightness, Buttons, and Sliders operational.")
    print("Press Ctrl+C to stop.")
    
    try:
        while True:
            raw_line = ser.readline()
            print(raw_line)
            if not raw_line:
                continue
                
            try:
                decoded_line = raw_line.decode('utf-8', errors='ignore').strip()
                
                # Filter out serial logging noise
                if decoded_line.startswith('[CDC-TX]') or not decoded_line:
                    continue
                
                if decoded_line.startswith('{') and decoded_line.endswith('}'):
                    data = json.loads(decoded_line)
                    action_type = data.get("action")
                    
                    # 1. Process Button Clicks
                    if action_type == "send_key":
                        handle_media_key(data.get("key"))
                        
                    # 2. Process Volume and Brightness Sliders
                    elif action_type in ["volume", "light_computer"]:
                        slider_val = data.get("value")
                        if slider_val is not None:
                            handle_slider_change(action_type, int(slider_val))
                        
                    # 3. Maintain Screen Handshake Awake Timer
                    elif action_type == "get_time":
                        send_time_heartbeat(ser)
                        
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"Error processing line: {e}")

    except KeyboardInterrupt:
        print("\nExiting cleanly...")
    finally:
        ser.close()
        print("Serial port closed.")

if __name__ == "__main__":
    main()
