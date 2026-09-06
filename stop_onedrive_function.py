import os
import subprocess
import time


def stop_onedrive():
    """Stops the OneDrive process to prevent sync conflicts."""
    print("\n--- Attempting to stop OneDrive sync client... ---")
    try:
        subprocess.run(["taskkill", "/f", "/im", "OneDrive.exe"], capture_output=True, text=True, check=True)
        print("OneDrive process stopped successfully.")
        time.sleep(3) # Give Windows a moment to release file locks
    except subprocess.CalledProcessError:
        print("OneDrive was not running, which is okay.")

def start_onedrive():
    """Starts the OneDrive process."""
    print("\n--- Attempting to restart OneDrive sync client... ---")
    onedrive_path = os.path.join(os.getenv('LOCALAPPDATA'), 'Microsoft\\OneDrive\\OneDrive.exe')
    
    if os.path.exists(onedrive_path):
        try:
            subprocess.Popen([onedrive_path])
            print("OneDrive process restarted successfully.")
        except Exception as e:
            print(f"---!!! ONEDRIVE START ERROR !!!---")
            print(f"Could not restart OneDrive. You may need to start it manually. Error: {e}")
    else:
        print(f"---!!! ONEDRIVE START ERROR !!!---")
        print(f"Could not find OneDrive.exe at: {onedrive_path}")
