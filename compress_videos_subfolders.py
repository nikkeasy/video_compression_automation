import os
import sys
import subprocess
import argparse
import shutil
import time
import threading
import concurrent.futures
from tqdm import tqdm
from dotenv import load_dotenv

# Force line-buffered stdout so prints show up instantly even when run through `uv run`
# (uv pipes output, which makes Python fully-buffer stdout and hide output for minutes).
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURATION: EDIT THESE SETTINGS IN .env ---
# LOAD ENV variables

load_dotenv()
INPUT_FOLDER = os.getenv("INPUT_FOLDER")                     # Root folder to scan for videos, e.g. "C:/Videos/Game Recordings"
TARGET_FOLDER = os.getenv("TARGET_FOLDER")                   # Final destination for compressed files, e.g. "C:/Users/you/OneDrive/Media"

# Full path to the HandBrakeCLI.exe. Use forward slashes.
HANDBRAKE_CLI_PATH = os.getenv("HANDBRAKE_CLI_PATH")         # e.g. "C:/Program Files/HandBrake/HandBrakeCLI.exe"

# The quality setting for the H.265 encoder. Lower = better quality/bigger file. 18-28 is a good range.
QUALITY_RF = int(os.getenv("QUALITY_RF", "20"))              # e.g. 20-22 for near-lossless, higher = smaller files

# The text to add to compressed files.
POSTFIX = os.getenv("POSTFIX")                               # e.g. "_compressed"

# File extensions to look for.
VIDEO_EXTENSIONS = tuple(ext.strip().lower() for ext in os.getenv("VIDEO_EXTENSIONS", ".mp4,.mkv").split(","))  # Generally mp4, mkv etc. Comma-separated in .env

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
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))             # e.g. 2-3 is the sweet spot for a single GPU

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
    output_filename = f"{name_part}{POSTFIX}{ext_part}"
    temp_output_path = os.path.join(os.path.dirname(input_path), output_filename)

    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    with print_lock:
        print("=" * 60)
        print(f"[Worker {slot}] Found large video: '{filename}' ({file_size_mb:.1f}MB) in '{os.path.dirname(input_path)}'")
        print(f"[Worker {slot}] Compressing to: {output_filename}...")

    command = [
        HANDBRAKE_CLI_PATH, "-i", input_path, "-o", temp_output_path,
        "--encoder", ENCODER, "--quality", str(QUALITY_RF)
    ]
    if PRESET:
        command.extend(["--preset", PRESET])
    if AENCODER:
        command.extend(["--aencoder", AENCODER])
    if HW_DECODE and HW_DECODE.strip().lower() == "true":
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
            print(f"[Worker {slot}] Moving compressed file to: {final_destination_path}")
            shutil.move(temp_output_path, final_destination_path)
            with print_lock:
                print(f"[Worker {slot}] Move successful!")

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

    # Phase 1: scan for eligible files
    for root, dirs, files in os.walk(INPUT_FOLDER):
        folders_scanned += 1
        if folders_scanned % 20 == 0:
            print(f"    ...scanned {folders_scanned} folders so far (found {len(job_info_list)} video(s))...")
        for filename in files:
            # Check if the file is a video we should consider
            if filename.lower().endswith(VIDEO_EXTENSIONS) and POSTFIX not in filename:
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

    # Phase 2: process in parallel, each worker gets its own progress bar slot
    successful_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_video, job, slot): job
                   for slot, job in enumerate(job_info_list)}
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
    parser = argparse.ArgumentParser(description="Compresses/moves videos in parallel (with progress bars). Use --onedrive to pause/resume OneDrive sync around the run.")
    parser.add_argument('--shutdown', action='store_true', help="Shutdown computer after the script completes.")
    parser.add_argument('--workers', type=int, default=None, help="Number of parallel compression workers. Overrides MAX_WORKERS from .env (e.g. --workers 2)")
    parser.add_argument('--onedrive', action='store_true', help="Stop OneDrive before compression and restart it after (prevents sync conflicts). By default OneDrive is left untouched.")
    args = parser.parse_args()

    workers = args.workers if args.workers is not None else MAX_WORKERS

    work_was_done = False
    if args.onedrive:
        try:
            stop_onedrive()
            work_was_done = compress_and_move_videos(max_workers=workers)
        finally:
            # This 'finally' block ensures OneDrive is ALWAYS restarted, even if the script crashes.
            start_onedrive()
    else:
        work_was_done = compress_and_move_videos(max_workers=workers)

    if args.shutdown and work_was_done:
        print("\nPipeline complete. Initiating shutdown in 60 seconds...")
        print("To cancel, open Command Prompt and type: shutdown /a")
        subprocess.run(["shutdown", "/s", "/t", "60", "/c", "Video processing finished."])
    else:
        input("\nPress Enter to exit.")