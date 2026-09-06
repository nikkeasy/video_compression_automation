import os
import subprocess
import argparse
import shutil
import time
import concurrent.futures
import threading
from dotenv import load_dotenv
from tqdm import tqdm

# --- CONFIGURATION: EDIT THESE SETTINGS IN .env ---
load_dotenv()
# Full path to the HandBrakeCLI.exe. Use forward slashes.
HANDBRAKE_CLI_PATH = os.getenv("HANDBRAKE_CLI_PATH")         # e.g. "C:/Program Files/HandBrake/HandBrakeCLI.exe"

# The PARENT folder where the script looks for videos.
INPUT_FOLDER = os.getenv("INPUT_FOLDER")                     # Root folder to scan for videos, e.g. "C:/Videos/Game Recordings"

# The FINAL destination for compressed files.
# LEAVE THIS BLANK ("") in .env to keep compressed files in the same folder as their originals.
TARGET_FOLDER = os.getenv("TARGET_FOLDER")                   # Final destination for compressed files, e.g. "C:/Videos/Compressed"

# The quality setting for the NVENC H.265 encoder. 18-22 is a good range.
QUALITY_RF = int(os.getenv("QUALITY_RF", "20"))              # e.g. 20-22 for near-lossless, higher = smaller files
POSTFIX = os.getenv("POSTFIX")                               # e.g. "_compressed"
VIDEO_EXTENSIONS = tuple(ext.strip().lower() for ext in os.getenv("VIDEO_EXTENSIONS", ".mp4,.mkv,.DVR").split(","))  # Generally mp4, mkv, DVR etc. Comma-separated in .env
MIN_FILE_SIZE_MB = int(os.getenv("MIN_FILE_SIZE_MB", "30"))  # Skip files smaller than this (MB), e.g. 30

# Encoding flags for the HandBrake command.
ENCODER = os.getenv("ENCODER")                               # e.g. "nvenc_h265" for NVIDIA GPU, "x265" for CPU
PRESET = os.getenv("PRESET")                                 # e.g. "fast", "medium", or "Hardware/H.265 NVENC 1080p"

# Parallel Processing: Number of files to process at the same time. Start with 2 or 3.
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))             # e.g. 3
# --- END OF CONFIGURATION ---

# A global lock for thread-safe printing to prevent garbled output
print_lock = threading.Lock()

def process_single_video(job_info):
    """
    This is the "worker" function. It processes one video file and includes a progress bar.
    This version reads character-by-character to handle carriage returns.
    """
    input_path, position = job_info
    try:
        # Build the output path and HandBrake command
        name_part, ext_part = os.path.splitext(os.path.basename(input_path))
        output_filename = f"{name_part}{POSTFIX}{ext_part}"
        root_folder = os.path.dirname(input_path)
        
        temp_output_path = os.path.join(root_folder, output_filename)

        command = [
            HANDBRAKE_CLI_PATH, "-i", input_path, "-o", temp_output_path,
            "--encoder", ENCODER, "--quality", str(QUALITY_RF)
        ]
        if PRESET:
            command.extend(["--preset", PRESET])

        # Use Popen to run the command in the background
        process = subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            encoding='utf-8', 
            errors='replace',
            bufsize=1 
        )
        
        # Create a tqdm progress bar for this specific file
        pbar_desc = os.path.basename(input_path)[:38]
        pbar = tqdm(total=100, desc=pbar_desc.ljust(40), position=position, leave=False)
        
        # --- NEW, ROBUST OUTPUT READING LOOP ---
        line_buffer = ''
        # iter(lambda: process.stdout.read(1), '') reads one character at a time
        for char in iter(lambda: process.stdout.read(1), ''):
            # When we hit a carriage return or newline, process the line we've built
            if char == '\r' or char == '\n':
                if "Encoding: task" in line_buffer and "%" in line_buffer:
                    try:
                        percent_str = line_buffer.split('%')[0].split(',')[-1].strip()
                        percent = float(percent_str)
                        pbar.update(percent - pbar.n)
                    except (ValueError, IndexError):
                        continue # Ignore malformed lines
                # Reset the buffer for the next line
                line_buffer = ''
            else:
                # If it's not a line ending, just add the character to our buffer
                line_buffer += char
        
        pbar.close()
        process.wait()

        # (The rest of the function remains the same)
        if process.returncode == 0:
            if TARGET_FOLDER:
                os.makedirs(TARGET_FOLDER, exist_ok=True)
                final_destination_path = os.path.join(TARGET_FOLDER, output_filename)
                shutil.move(temp_output_path, final_destination_path)
            os.remove(input_path)
            return True
        else:
            with print_lock:
                print(f"\n---!!! HANDBRAKE ERROR on {os.path.basename(input_path)} (Code: {process.returncode})!!!---")
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
            return False

    except Exception as e:
        with print_lock:
            print(f"\n---!!! SCRIPT ERROR on {os.path.basename(input_path)}: {e} !!!---")
        return False


def main_processor():
    # ... (This function is unchanged and correct)
    with print_lock:
        print(f"Scanning for videos in: {INPUT_FOLDER}")
    
    jobs = []
    for root, dirs, files in os.walk(INPUT_FOLDER):
        for filename in files:
            if filename.lower().endswith(VIDEO_EXTENSIONS) and POSTFIX not in filename:
                input_path = os.path.join(root, filename)
                try:
                    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
                    if file_size_mb >= MIN_FILE_SIZE_MB:
                        jobs.append(input_path)
                except FileNotFoundError:
                    continue
    
    if not jobs:
        with print_lock:
            print("No new videos to process.")
        return False

    with print_lock:
        print(f"Found {len(jobs)} videos to process. Starting {min(MAX_WORKERS, len(jobs))} workers...")
    
    job_info_list = [(job, i) for i, job in enumerate(jobs)]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(process_single_video, job_info_list))
    
    return any(results)

if __name__ == "__main__":
    # --- RE-ENABLED ARGUMENT PARSER ---
    parser = argparse.ArgumentParser(description="Compresses video files in parallel.")
    parser.add_argument('--shutdown', action='store_true', help="Shutdown the computer after successfully processing at least one video.")
    args = parser.parse_args()

    # Run the main processing function
    work_was_done = main_processor()

    # Move the cursor down below the progress bars before printing the final message
    print("\n" * (MAX_WORKERS + 2)) 
    print("All tasks complete.")

    # Check the shutdown flag AND if any work was actually done
#    if args.shutdown and work_was_done:
#        print("Initiating shutdown in 60 seconds...")
#        subprocess.run(["shutdown", "/s", "/t", "60"])
##    else:
#        input("Press Enter to exit.")