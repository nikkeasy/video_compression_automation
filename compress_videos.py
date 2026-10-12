import os
import subprocess
import argparse
import shutil
import time
from dotenv import load_dotenv

load_dotenv()

def resolve_handbrake_path(path_str):
    if path_str:
        clean = path_str.strip().strip('"').strip("'")
        if os.path.isfile(clean):
            return clean
        if os.path.isdir(clean):
            for candidate in ("HandBrakeCLI.exe", "HandBrakeCLI"):
                full = os.path.join(clean, candidate)
                if os.path.isfile(full):
                    return full
    defaults = [
        r"C:\Program Files\HandBrake\CLI\HandBrakeCLI.exe",
        r"C:\Program Files\HandBrake\HandBrakeCLI.exe",
    ]
    for d in defaults:
        if os.path.isfile(d):
            return d
    which_hb = shutil.which("HandBrakeCLI") or shutil.which("HandBrakeCLI.exe")
    if which_hb:
        return which_hb
    return path_str.strip().strip('"').strip("'") if path_str else None

def has_nvidia_gpu():
    return shutil.which("nvidia-smi") is not None

# --- CONFIGURATION: EDIT THESE SETTINGS IN .env ---
# NOTE: This script scans ONE flat folder (no subfolders) and works in that same folder.
HANDBRAKE_CLI_PATH = resolve_handbrake_path(os.getenv("HANDBRAKE_CLI_PATH"))
INPUT_FOLDER = os.getenv("INPUT_FOLDER")                     # Folder to scan for videos, e.g. "C:/Downloads"
ONEDRIVE_FOLDER = os.getenv("ONEDRIVE_FOLDER")               # Final destination, e.g. "C:/Users/username/OneDrive/Media/Game Recordings". Leave empty to skip the move.
QUALITY_RF = int(os.getenv("QUALITY_RF", "22"))              # H.265 quality (lower = better), e.g. 20-22 for near-lossless
POSTFIX = os.getenv("POSTFIX", "_compressed") or "_compressed"
VIDEO_EXTENSIONS = tuple(ext.strip().lower() for ext in os.getenv("VIDEO_EXTENSIONS", ".mp4,.mkv").split(","))  # Generally mp4, mkv etc. Comma-separated in .env

# Encoding flags for the HandBrake command.
ENCODER = os.getenv("ENCODER") or ("nvenc_h265" if has_nvidia_gpu() else "x265")
PRESET = os.getenv("PRESET", "fast" if ENCODER == "x265" else None)
AENCODER = os.getenv("AENCODER")                             # e.g. "copy" for audio passthrough, leave empty to re-encode audio
# --- END OF CONFIGURATION ---

def stop_onedrive():
    """Stops the OneDrive process."""
    print("\n--- Attempting to stop OneDrive sync client... ---")
    try:
        # Use taskkill to force /im (image name) OneDrive.exe to terminate.
        subprocess.run(["taskkill", "/f", "/im", "OneDrive.exe"], capture_output=True, text=True, check=True)
        print("OneDrive process stopped successfully.")
        # Give Windows a moment to release file locks
        time.sleep(3) 
    except subprocess.CalledProcessError:
        # This error occurs if OneDrive wasn't running, which is fine.
        print("OneDrive was not running.")

def start_onedrive():
    """Starts the OneDrive process."""
    print("\n--- Attempting to restart OneDrive sync client... ---")
    # Construct the path to OneDrive.exe using environment variables for reliability
    onedrive_path = os.path.join(os.getenv('LOCALAPPDATA'), 'Microsoft\\OneDrive\\OneDrive.exe')
    
    if os.path.exists(onedrive_path):
        try:
            # Use Popen for a non-blocking call to start the process
            subprocess.Popen([onedrive_path])
            print("OneDrive process restarted successfully.")
        except Exception as e:
            print(f"---!!! ONEDRIVE START ERROR !!!---")
            print(f"Could not restart OneDrive. You may need to start it manually. Error: {e}")
    else:
        print(f"---!!! ONEDRIVE START ERROR !!!---")
        print(f"Could not find OneDrive.exe at: {onedrive_path}")

def compress_and_move_videos():
    # (The main function is identical to the previous version, no changes needed here)
    print(f"Scanning folder: {INPUT_FOLDER}")
    files_processed_count = 0
    for filename in os.listdir(INPUT_FOLDER):
        if filename.lower().endswith(VIDEO_EXTENSIONS) and POSTFIX not in filename:
            input_path = os.path.join(INPUT_FOLDER, filename)
            name_part, ext_part = os.path.splitext(filename)
            output_filename = f"{name_part}{POSTFIX}{ext_part}"
            temp_output_path = os.path.join(INPUT_FOLDER, output_filename)
            print("="*60)
            print(f"Found new video: {filename}")
            command = [
                HANDBRAKE_CLI_PATH, "-i", input_path, "-o", temp_output_path,
                "--encoder", ENCODER, "--quality", str(QUALITY_RF)
            ]
            if PRESET:
                command.extend(["--preset", PRESET])
            if AENCODER:
                command.extend(["--aencoder", AENCODER])
            try:
                print(f"Compressing to: {output_filename}...")
                subprocess.run(command, capture_output=True, text=True, check=True)
                compressed_size = os.path.getsize(temp_output_path)
                original_size = os.path.getsize(input_path)

                # SIZE SAFETY GATE: Never replace an original with a larger file!
                if compressed_size >= original_size:
                    print(f"⚠️ SIZE WARNING: Compressed output ({compressed_size / (1024 * 1024):.1f} MB) is LARGER than original ({original_size / (1024 * 1024):.1f} MB).")
                    print("Discarding bloated compressed file and keeping original.")
                    if os.path.exists(temp_output_path):
                        os.remove(temp_output_path)
                    print("="*60 + "\n")
                    continue

                savings_pct = ((original_size - compressed_size) / original_size) * 100
                print(f"Compression successful! ({compressed_size / (1024 * 1024):.1f} MB vs {original_size / (1024 * 1024):.1f} MB original | -{savings_pct:.1f}% space saved)")
                if ONEDRIVE_FOLDER:
                    os.makedirs(ONEDRIVE_FOLDER, exist_ok=True)
                    final_destination_path = os.path.join(ONEDRIVE_FOLDER, output_filename)
                    print(f"Moving compressed file to: {final_destination_path}")
                    shutil.move(temp_output_path, final_destination_path)
                    print("Move successful!")
                print(f"Deleting original file: {filename}")
                os.remove(input_path)
                files_processed_count += 1
            except Exception as e:
                print(f"---!!! PROCESSING ERROR !!!---")
                print(f"An error occurred with file {filename}. Details: {e}")
                print("The original file will be kept.")
            print("="*60 + "\n")
    if files_processed_count > 0:
        print(f"Script finished. Processed {files_processed_count} new video(s).")
        return True
    else:
        print("Script finished. No new videos to process.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compresses/moves videos in a single flat folder. Use --onedrive to pause/resume OneDrive sync around the run.")
    parser.add_argument('--shutdown', action='store_true', help="Shutdown computer after the script completes.")
    parser.add_argument('--onedrive', action='store_true', help="Stop OneDrive before compression and restart it after (prevents sync conflicts). By default OneDrive is left untouched.")
    args = parser.parse_args()

    if args.onedrive:
        try:
            stop_onedrive()
            work_was_done = compress_and_move_videos()
        finally:
            # This 'finally' block ensures OneDrive is ALWAYS restarted, even if the script crashes.
            start_onedrive()
    else:
        work_was_done = compress_and_move_videos()

    if args.shutdown and work_was_done:
        print("\nPipeline complete. Initiating shutdown in 60 seconds...")
        print("To cancel, open Command Prompt and type: shutdown /a")
    #   subprocess.run(["shutdown", "/s", "/t", "60", "/c", "Video processing finished."])
    else:
        input("\nPress Enter to exit.")