import os
import sys
import subprocess
import argparse
import shutil
import time
import queue
import threading
import concurrent.futures
from tqdm import tqdm
from dotenv import load_dotenv

# Force line-buffered stdout so prints show up instantly even when run through `uv run`
# (uv pipes output, which makes Python fully-buffer stdout and hide output for minutes).
sys.stdout.reconfigure(line_buffering=True)

def resolve_handbrake_path(path_str):
    """
    Locates the HandBrakeCLI executable.
    Handles direct file paths, directory paths, common install locations, and PATH.
    """
    if path_str:
        clean = path_str.strip().strip('"').strip("'")
        if os.path.isfile(clean):
            return clean
        if os.path.isdir(clean):
            for candidate in ("HandBrakeCLI.exe", "HandBrakeCLI"):
                full = os.path.join(clean, candidate)
                if os.path.isfile(full):
                    return full
    # Check common default paths on Windows
    defaults = [
        r"C:\Program Files\HandBrake\CLI\HandBrakeCLI.exe",
        r"C:\Program Files\HandBrake\HandBrakeCLI.exe",
    ]
    for d in defaults:
        if os.path.isfile(d):
            return d
    # Check system PATH
    which_hb = shutil.which("HandBrakeCLI") or shutil.which("HandBrakeCLI.exe")
    if which_hb:
        return which_hb
    return path_str.strip().strip('"').strip("'") if path_str else None

def has_nvidia_gpu():
    """Checks if an NVIDIA GPU is available via nvidia-smi."""
    return shutil.which("nvidia-smi") is not None

# --- CONFIGURATION: EDIT THESE SETTINGS IN .env ---
load_dotenv()
INPUT_FOLDER = os.getenv("INPUT_FOLDER")                     # Root folder to scan for videos, e.g. "C:/Videos/Game Recordings"
TARGET_FOLDER = os.getenv("TARGET_FOLDER")                   # Final destination for compressed files, e.g. "C:/Users/you/OneDrive/Media"

# Full path to HandBrakeCLI.exe or its parent folder.
HANDBRAKE_CLI_PATH = resolve_handbrake_path(os.getenv("HANDBRAKE_CLI_PATH"))

# The quality setting for the H.265 encoder. Lower = better quality/bigger file. 18-28 is a good range.
QUALITY_RF = int(os.getenv("QUALITY_RF", "20"))              # e.g. 20-22 for near-lossless, higher = smaller files

# The text to add to compressed files.
POSTFIX = os.getenv("POSTFIX", "_compressed") or "_compressed" # e.g. "_compressed"

# File extensions to look for.
VIDEO_EXTENSIONS = tuple(ext.strip().lower() for ext in os.getenv("VIDEO_EXTENSIONS", ".mp4,.mkv").split(","))  # Comma-separated in .env

# Files smaller than this (in MB) will be skipped entirely.
MIN_FILE_SIZE_MB = int(os.getenv("MIN_FILE_SIZE_MB", "30"))  # e.g. 30

# Encoding flags for the HandBrake command.
ENCODER = os.getenv("ENCODER")                               # e.g. "nvenc_h265" for NVIDIA GPU, "x265" for CPU
PRESET = os.getenv("PRESET")                                 # e.g. "fast", "medium", or "Hardware/H.265 NVENC 1080p"
AENCODER = os.getenv("AENCODER")                             # e.g. "copy" for audio passthrough, leave empty to re-encode audio

# Use GPU hardware decoding (NVDEC) to offload the CPU. Set to "false" to disable.
HW_DECODE = os.getenv("HW_DECODE", "false")                  # e.g. "true" — CPU drops from 100% to ~15%, way faster for 4K

# Embed a thumbnail frame into compressed MP4s (needs FFmpeg on PATH). "false" to disable.
THUMBNAIL_EMBED = os.getenv("THUMBNAIL_EMBED", "false")       # e.g. "true" — restores Windows Explorer preview images

# Locate FFmpeg once at startup (used for thumbnail embedding). None if not installed.
FFMPEG_PATH = shutil.which("ffmpeg")

# How many videos to compress in parallel. Can be overridden at runtime with --workers.
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))             # e.g. 2-3 for GPU, 1 for CPU

# Lock for thread-safe printing (parallel workers share the console).
print_lock = threading.Lock()

# --- END OF CONFIGURATION ---

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
    """Starts the OneDrive process. Tries both the classic OneDrive.exe and the
    newer OneDrive.App.exe (used by the current OneDrive client)."""
    print("\n--- Attempting to restart OneDrive sync client... ---")
    local_appdata = os.getenv('LOCALAPPDATA')
    candidates = [
        os.path.join(local_appdata, 'Microsoft', 'OneDrive', 'OneDrive.exe'),
        os.path.join(local_appdata, 'Microsoft', 'OneDrive', 'OneDrive.App.exe'),
    ]
    onedrive_path = next((p for p in candidates if os.path.exists(p)), None)

    if onedrive_path:
        try:
            subprocess.Popen([onedrive_path])
            print(f"OneDrive process restarted successfully (found: {os.path.basename(onedrive_path)}).")
        except Exception as e:
            print(f"---!!! ONEDRIVE START ERROR !!!---")
            print(f"Could not restart OneDrive. You may need to start it manually. Error: {e}")
    else:
        print(f"---!!! ONEDRIVE START ERROR !!!---")
        print(f"Could not find OneDrive.exe or OneDrive.App.exe in: {os.path.dirname(candidates[0])}")


def embed_thumbnail(original_path, video_path, slot):
    """
    Extracts a frame from the ORIGINAL video at the 5-second mark and attaches it
    as cover art to the COMPRESSED video, so Windows Explorer shows a preview image
    just like the original files did. Uses two quick FFmpeg remux passes.
    Returns True on success (or gracefully skips if FFmpeg is missing).
    """
    if not THUMBNAIL_EMBED or THUMBNAIL_EMBED.strip().lower() != "true":
        return True  # Feature disabled, nothing to do
    if not FFMPEG_PATH:
        print(f"[Worker {slot}] THUMBNAIL SKIPPED: FFmpeg not found on PATH. Install FFmpeg or set THUMBNAIL_EMBED=false.")
        return True  # Not fatal, video is still fine
    if not os.path.exists(original_path):
        print(f"[Worker {slot}] THUMBNAIL SKIPPED: original file no longer exists.")
        return True

    thumb_path = video_path + "_thumb.jpg"
    tagged_path = video_path + "_tagged.mp4"

    try:
        # Step 1: grab one frame from the original. Try 5s first; fall back to 1s / 0s
        # for short clips where seeking past the end would fail.
        thumb_ok = False
        for seek in ("5", "1", "0"):
            extract_cmd = [FFMPEG_PATH, "-ss", seek, "-i", original_path,
                           "-frames:v", "1", "-q:v", "3", "-y", thumb_path]
            result = subprocess.run(extract_cmd, capture_output=True, text=True)
            if result.returncode == 0 and os.path.exists(thumb_path):
                thumb_ok = True
                break
        if not thumb_ok:
            print(f"[Worker {slot}] THUMBNAIL WARNING: could not extract frame (FFmpeg code {result.returncode}). Video is still fine.")
            return True

        # Step 2: attach the JPEG as cover art into the MP4 container (fast remux, no re-encode)
        attach_cmd = [FFMPEG_PATH, "-i", video_path, "-i", thumb_path,
                      "-map", "0", "-map", "1", "-c", "copy",
                      "-disposition:v:1", "attached_pic",
                      "-metadata:s:t", "mimetype=image/jpeg",
                      "-y", tagged_path]
        result = subprocess.run(attach_cmd, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(tagged_path):
            print(f"[Worker {slot}] THUMBNAIL WARNING: could not embed cover art (FFmpeg code {result.returncode}). Video is still fine.")
            return True

        # Replace the original output with the tagged version
        os.replace(tagged_path, video_path)
        print(f"[Worker {slot}] Thumbnail embedded successfully.")
        return True

    finally:
        # Always clean up the temp thumbnail and any leftover tagged file
        for temp in (thumb_path, tagged_path):
            if os.path.exists(temp):
                try:
                    os.remove(temp)
                except OSError:
                    pass


def process_single_video(job_info, slot):
    """
    Compresses one video with a live tqdm progress bar, then moves it to the
    destination (if set) and deletes the original. job_info is (input_path, filename).
    Returns True on success.
    """
    input_path, filename = job_info
    name_part, ext_part = os.path.splitext(filename)
    postfix_str = POSTFIX if POSTFIX else "_compressed"
    output_filename = f"{name_part}{postfix_str}{ext_part}"
    temp_output_path = os.path.join(os.path.dirname(input_path), output_filename)

    # Clean up any leftover partial file from previous interrupted runs
    if os.path.exists(temp_output_path):
        try:
            os.remove(temp_output_path)
        except OSError:
            pass

    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    with print_lock:
        print("=" * 60)
        print(f"[Worker {slot}] Found large video: '{filename}' ({file_size_mb:.1f}MB) in '{os.path.dirname(input_path)}'")
        print(f"[Worker {slot}] Compressing to: {output_filename}...")

    # Build HandBrakeCLI command (guaranteed non-None arguments)
    command = [
        HANDBRAKE_CLI_PATH, "-i", input_path, "-o", temp_output_path,
        "--encoder", str(ENCODER), "--quality", str(QUALITY_RF)
    ]
    if PRESET:
        command.extend(["--preset", str(PRESET)])
    if AENCODER:
        command.extend(["--aencoder", str(AENCODER)])
    if HW_DECODE and str(HW_DECODE).strip().lower() == "true":
        command.append("--hwdecode")

    try:
        # Run HandBrake and stream its stdout char-by-char to build a real progress bar.
        # IMPORTANT: we must read raw characters with read(1) instead of iterating over
        # process.stdout, because HandBrake terminates its progress lines with a carriage
        # return (\r), and iterating the file object waits for \n — the bar would sit at 0%.
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        bar_format = f"[Worker {slot}]" + "{desc}: {percentage:3.0f}%|{bar}|"
        with tqdm(total=100, desc=filename[:38], position=slot, bar_format=bar_format, leave=True) as pbar:
            line_buffer = ""
            for char in iter(lambda: process.stdout.read(1), ""):
                if char == "\r" or char == "\n":
                    if "Encoding: task" in line_buffer and "%" in line_buffer:
                        try:
                            percent_str = line_buffer.split("%")[0].split(",")[-1].strip()
                            percent = float(percent_str)
                            if 0 <= percent <= 100:
                                pbar.update(percent - pbar.n)
                        except (ValueError, IndexError):
                            pass  # Ignore malformed progress lines
                    line_buffer = ""
                else:
                    line_buffer += char
        process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"HandBrake exited with code {process.returncode}")

        # SAFETY GATE: verify the compressed output is real before touching the original.
        # HandBrake can exit 0 yet produce a tiny broken stub file (seen with --hwdecode
        # failures), and we must NEVER delete the original in that case. Size checks alone
        # are not enough, so we probe the file with FFmpeg: it must decode with no errors
        # AND contain a video stream longer than 0.5 seconds.
        if not os.path.exists(temp_output_path):
            raise RuntimeError(f"Safety gate: compressed output '{temp_output_path}' does not exist! Keeping original.")
        if FFMPEG_PATH:
            probe = subprocess.run(
                [FFMPEG_PATH, "-v", "error", "-i", temp_output_path, "-map", "0:v:0",
                 "-f", "null", "-"],
                capture_output=True, text=True)
            if probe.returncode != 0 or probe.stderr.strip():
                raise RuntimeError(
                    f"Safety gate: compressed output FAILED FFmpeg validation "
                    f"(code {probe.returncode}): {probe.stderr.strip()[:300]} ... Keeping original.")
        else:
            # No FFmpeg available: fall back to a simple size sanity check
            if os.path.getsize(temp_output_path) < 1_000_000:
                raise RuntimeError("Safety gate: compressed output is suspiciously small (<1MB). Keeping original.")

        compressed_size = os.path.getsize(temp_output_path)

        with print_lock:
            print(f"[Worker {slot}] Compression successful! ({compressed_size / (1024 * 1024):.1f} MB vs {file_size_mb:.1f} MB original)")

        # Embed a thumbnail from the ORIGINAL into the compressed file (before original is deleted)
        embed_thumbnail(input_path, temp_output_path, slot)

        if TARGET_FOLDER:
            os.makedirs(TARGET_FOLDER, exist_ok=True)
            final_destination_path = os.path.join(TARGET_FOLDER, output_filename)
            if os.path.abspath(temp_output_path) != os.path.abspath(final_destination_path):
                print(f"[Worker {slot}] Moving compressed file to: {final_destination_path}")
                shutil.move(temp_output_path, final_destination_path)
                with print_lock:
                    print(f"[Worker {slot}] Move successful!")
            else:
                with print_lock:
                    print(f"[Worker {slot}] Compressed file saved in target folder: {temp_output_path}")

        with print_lock:
            print(f"[Worker {slot}] Deleting original file: {filename}")
        os.remove(input_path)
        print("=" * 60)
        return True

    except Exception as e:
        with print_lock:
            print(f"---!!! PROCESSING ERROR (Worker {slot}) !!!---")
            print(f"An error occurred with file {filename}. Details: {e}")
            print("The original file will be kept.")
        # Clean up partial output if HandBrake left something broken behind
        if os.path.exists(temp_output_path):
            try:
                os.remove(temp_output_path)
            except OSError:
                pass
        print("=" * 60)
        return False


def compress_and_move_videos(max_workers):
    """
    Phase 1: Recursively scans subfolders and collects all eligible videos.
    Phase 2: Compresses them in parallel with a ThreadPoolExecutor.
    Returns True if at least one video was processed.
    """
    print(f"Recursively scanning parent folder: {INPUT_FOLDER}")
    job_info_list = []
    total_size_mb = 0.0
    folders_scanned = 0

    postfix_check = POSTFIX if POSTFIX else "_compressed"

    # Phase 1: scan for eligible files
    for root, dirs, files in os.walk(INPUT_FOLDER):
        folders_scanned += 1
        if folders_scanned % 20 == 0:
            print(f"    ...scanned {folders_scanned} folders so far (found {len(job_info_list)} video(s))...")
        for filename in files:
            # Check if the file is a video we should consider (avoid re-compressing already processed files)
            if filename.lower().endswith(VIDEO_EXTENSIONS) and postfix_check not in filename and "_compressed" not in filename:
                input_path = os.path.join(root, filename)

                # Skip files that are too small to be worth compressing
                try:
                    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
                    if file_size_mb < MIN_FILE_SIZE_MB:
                        print(f"--- Skipping '{filename}' ({file_size_mb:.1f}MB) - Below {MIN_FILE_SIZE_MB}MB threshold.")
                        continue
                except FileNotFoundError:
                    print(f"--- Warning: Could not find file {input_path} to get its size. Skipping.")
                    continue

                job_info_list.append((input_path, filename))
                total_size_mb += file_size_mb

    if not job_info_list:
        print(f"Scan complete ({folders_scanned} folders). Script finished. No new videos to process.")
        return False

    print(f"\nScan complete ({folders_scanned} folders).")
    print(f"Found {len(job_info_list)} video(s) to process ({total_size_mb / 1024:.2f} GB total).")
    print(f"Compressing with {max_workers} parallel worker(s)...\n")

    start_time = time.time()

    # Slot queue so progress bar position stays within [0, max_workers - 1]
    slot_queue = queue.Queue()
    for s in range(max_workers):
        slot_queue.put(s)

    def worker_wrapper(job):
        slot = slot_queue.get()
        try:
            return process_single_video(job, slot)
        finally:
            slot_queue.put(slot)

    # Phase 2: process in parallel
    successful_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker_wrapper, job): job for job in job_info_list}
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                successful_count += 1

    elapsed = time.time() - start_time
    hours, rem = divmod(elapsed, 3600)
    minutes, seconds = divmod(rem, 60)
    duration_str = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

    if successful_count > 0:
        print(f"\nScript finished. Processed {successful_count}/{len(job_info_list)} new video(s).")
        print(f"Total task duration: {duration_str}")
        return True
    else:
        print("\nScript finished. All videos failed to process. Check the errors above.")
        print(f"Total task duration: {duration_str}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compresses/moves videos in parallel with live progress bars. "
                    "Use --gpu for NVIDIA GPUs, --cpu for basic laptops, or --qsv for Intel QuickSync."
    )
    parser.add_argument('--gpu', action='store_true', help="Use NVIDIA GPU hardware encoder (nvenc_h265) and HW decoding.")
    parser.add_argument('--cpu', action='store_true', help="Use CPU encoder (x265) with safe single-worker default, ideal for basic laptops.")
    parser.add_argument('--qsv', action='store_true', help="Use Intel QuickSync hardware encoder (qsv_h265), great for Intel laptops.")
    parser.add_argument('--encoder', type=str, default=None, help="Specify HandBrake encoder (e.g. nvenc_h265, x265, qsv_h265). Overrides .env")
    parser.add_argument('--preset', type=str, default=None, help="Specify HandBrake preset (e.g. fast, medium). Overrides .env")
    parser.add_argument('-q', '--quality', '--rf', dest='quality_rf', type=int, default=None, help="RF Quality value (lower = better quality/bigger file, e.g. 20-24). Overrides .env")
    parser.add_argument('--workers', type=int, default=None, help="Number of parallel compression workers. Overrides MAX_WORKERS from .env")
    parser.add_argument('--onedrive', action='store_true', help="Stop OneDrive before compression and restart it after (prevents sync conflicts).")
    parser.add_argument('--shutdown', action='store_true', help="Shutdown computer after the script completes.")
    args = parser.parse_args()

    # 1. Resolve Encoder & HW Decoding
    if args.gpu:
        ENCODER = "nvenc_h265"
        HW_DECODE = "true"
    elif args.cpu:
        ENCODER = "x265"
        HW_DECODE = "false"
        if not args.preset and not PRESET:
            PRESET = "fast"
    elif args.qsv:
        ENCODER = "qsv_h265"
        HW_DECODE = "false"
    elif args.encoder:
        ENCODER = args.encoder
    elif not ENCODER:
        # Auto-detect encoder if not provided in .env
        if has_nvidia_gpu():
            ENCODER = "nvenc_h265"
            HW_DECODE = "true"
            print("[Auto-detect] NVIDIA GPU detected -> default encoder set to nvenc_h265")
        else:
            ENCODER = "x265"
            HW_DECODE = "false"
            if not PRESET:
                PRESET = "fast"
            print("[Auto-detect] No NVIDIA GPU detected -> falling back to universal CPU encoder: x265")

    # 2. Resolve Preset
    if args.preset:
        PRESET = args.preset

    # 3. Resolve Quality RF
    if args.quality_rf is not None:
        QUALITY_RF = args.quality_rf

    # 4. Resolve Workers
    if args.workers is not None:
        workers = args.workers
    elif args.cpu or ENCODER == "x265":
        workers = 1  # Safe laptop/CPU default: 1 worker avoids pegging all cores to 100%
    else:
        workers = MAX_WORKERS

    # 5. Sanity Checks on HandBrake and Input Folder
    if not HANDBRAKE_CLI_PATH or not os.path.isfile(HANDBRAKE_CLI_PATH):
        print("=" * 60)
        print("ERROR: HandBrakeCLI executable not found!")
        print(f"Current resolved path: {HANDBRAKE_CLI_PATH}")
        print("Please verify HANDBRAKE_CLI_PATH in .env or ensure HandBrakeCLI is installed.")
        print('Example: HANDBRAKE_CLI_PATH = "C:/Program Files/HandBrake/CLI/HandBrakeCLI.exe"')
        print("=" * 60)
        sys.exit(1)

    if not INPUT_FOLDER or not os.path.exists(INPUT_FOLDER):
        print("=" * 60)
        print("ERROR: INPUT_FOLDER does not exist or is not set in .env:")
        print(f"INPUT_FOLDER: {INPUT_FOLDER}")
        print("Please check your .env configuration.")
        print("=" * 60)
        sys.exit(1)

    # 6. Display Configuration Banner
    print("=" * 60)
    print("Video Compression Automation (Subfolders)")
    print("=" * 60)
    print(f"HandBrakeCLI : {HANDBRAKE_CLI_PATH}")
    print(f"Input Folder : {INPUT_FOLDER}")
    print(f"Target Folder: {TARGET_FOLDER if TARGET_FOLDER else '(Same as input)'}")
    print(f"Encoder      : {ENCODER}")
    print(f"Preset       : {PRESET if PRESET else '(default)'}")
    print(f"Quality (RF) : {QUALITY_RF}")
    print(f"Workers      : {workers}")
    print(f"HW Decode    : {HW_DECODE}")
    print("=" * 60 + "\n")

    work_was_done = False
    if args.onedrive:
        try:
            stop_onedrive()
            work_was_done = compress_and_move_videos(max_workers=workers)
        finally:
            start_onedrive()
    else:
        work_was_done = compress_and_move_videos(max_workers=workers)

    if args.shutdown and work_was_done:
        print("\nPipeline complete. Initiating shutdown in 60 seconds...")
        print("To cancel, open Command Prompt and type: shutdown /a")
        subprocess.run(["shutdown", "/s", "/t", "60", "/c", "Video processing finished."])
    else:
        input("\nPress Enter to exit.")