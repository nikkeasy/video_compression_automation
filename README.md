# video_compression_automation
Fast way to compress your videos and save enormous amount of space on hard drive using python script and HandBrake CLI commands


## Documentation

### HandBrakeCLI manual test.

Had some problems with the HandBrakeCLI commands working so had to test it manually. I opened up CMD on windows and tried different commands. 

> C:\Downloads>"C:\Program Files\HandBrake\HandBrakeCLI.exe" -i "Fortnite_test.mp4" -o "MyTestVideo_compressed.mp4" --preset Web/Creator 1080p60

Note: The command above did not work because it did not enclose the preset option **Web/Creator 1080p60** in Quotes

> C:\Downloads>"C:\Program Files\HandBrake\HandBrakeCLI.exe" -i "Fortnite_test.mp4" -o "MyTestVideo_compressed.mp4" --preset "Web/Creator 1080p60"

This command's syntax was correct but it could NOT process the file??? I am baffled because the same exact file works in HandBrake GUI. I googled and eventually asked Gemini about it and it said that it could be because the file is somehow not in a correct format and needs 'Remuxing' and FFMPEG library could do the trick. Aarghh, more hassle and steps along the way. Downloaded FFMPEG and begun to start the *Remux* process for the file and then, by accident I noticed as I pressed Tab to get the filename autocompleted on cmd it showed me this: 

> C:\Downloads>"C:\ffmpeg\bin\ffmpeg.exe" -i "Fortnite_test.mp4.mp4" -c copy "Fortnite_test_remuxed.mp4"  

As I have a powerful RTX 4070 GPU, I wanted to take advantage of it and use Hardware NVIDIA encoding (H.265 NVENC). For a test case I compressed a 1,68 Gb game recording down to just under 300 Mb in around 40 seconds. I will take one more test and after I can conclude that it works I will create a script that finds all game recordings in a folder and its subfolders with certain criteria and compresses them to be around 70% smaller in size than the original counterparts.


#### Advanced configs to optimize compression

- Parallel processing
    - NVIDIA Engine paired with RTX 4070 potentially could to 2-4 files at once, which really speeds up the compression operations significantly and I really see no reason NOT to use it.


Robocopy for copying files from HDD 

robocopy "H:\Game Recordings" "C:\Projects\Video_Processing_Temp" /E /MOVE /MT:16 /R:2 /W:5
Which means: 
    
    /E       – Copy ALL subfolders, even empty ones. We want the whole folder structure, not just the files.
    /MOVE    – Move files from source to destination (delete originals after successful copy). This frees up the HDD space!
    /MT:16   – Multi-threaded copying with 16 threads. Way faster than the default single-threaded copy, especially over a network or between drives.
    /R:2     – Only retry 2 times on failure. The default is ONE MILLION retries, which would hang the script forever if a file is locked. Don't be that guy.
    /W:5     – Wait 5 seconds between retries. Default is 30 seconds, which is way too long.

This is the very first step in the pipeline: raw game recordings sit on my HDD (H:). Robocopy moves them over to the processing temp folder where the Python compression scripts can do their thing. After compression, the compressed files go to their final destination (NordLocker/OneDrive), and the originals in the temp folder get deleted automatically by the scripts.


### The Scripts - What Each File Does

#### compress_videos.py – Single Folder, Simple
The original script. Scans ONE folder (TARGET_FOLDER), finds all .mp4 and .mkv files, compresses them with NVENC H.265, moves compressed files to OneDrive, and deletes the originals. Has OneDrive stop/start built in. Use this if all your videos are in one flat folder.

Supports the --shutdown flag to turn off your PC after processing.

#### compress_videos_subfolders.py – Recursive, .env Powered (THE MAIN ONE)
This is the workhorse. Uses os.walk() to recursively scan ALL subfolders under INPUT_FOLDER. Reads its input/output paths from a .env file so you don't have to edit the script itself. Skips files smaller than 30 MB (MIN_FILE_SIZE_MB) — no point compressing tiny clips. Uses the "fast" preset with audio passthrough (--aencoder copy).

This is the script you actually use for batch processing your entire game recordings library.

#### compress_one_video.py – Parallel Processing with Progress Bars
The fancy version. Uses Python's concurrent.futures.ThreadPoolExecutor to compress up to MAX_WORKERS (default 3) videos at the same time. Each worker gets its own tqdm progress bar showing real-time encoding percentage. Takes advantage of the RTX 4070's multiple NVENC chips.

Good for when you have a TON of videos and want to max out your GPU.

#### stop_onedrive_function.py – OneDrive Helper
A standalone version of the OneDrive stop/start functions. Extracted here for testing separately.

#### testfile.py – .env Loader Tester
Quick sanity check to make sure python-dotenv is loading your INPUT_FOLDER and TARGET_FOLDER correctly from the .env file.


## Setup & Prerequisites

### What You Need Installed
- **HandBrakeCLI** – The command-line version of HandBrake. Download from handbrake.fr. Must be at "C:\Program Files\HandBrake\HandBrakeCLI.exe" (or change HANDBRAKE_CLI_PATH in the scripts).
- **FFmpeg** – Only needed IF HandBrakeCLI refuses to process a file (had this happen once, file needed "remuxing" first). Download from ffmpeg.org. Put it wherever, you just run it manually from CMD.
- **NVIDIA GPU with NVENC** – The scripts use nvenc_h265 hardware encoding. Without an NVIDIA GPU you'd need to change the --encoder flag to something CPU-based (x265), which will be MUCH slower.

### Python Packages

    pip install python-dotenv tqdm

(python-dotenv is for the .env file, tqdm is for the progress bars in compress_one_video.py)

### The .env File
Create a .env file in the project root with:

    INPUT_FOLDER = "C:/path/to/your/videos"
    TARGET_FOLDER = "C:/path/to/final/destination"

Use FORWARD SLASHES even on Windows. The scripts won't work with backslashes in the .env values. This is used by compress_videos_subfolders.py.


## The Full Pipeline – End to End

Here's the complete workflow, from raw recording to compressed final file:

    1. ROBOCOPY – Move raw game recordings from HDD to processing temp folder:

       robocopy "H:\Game Recordings" "C:\Projects\Video_Processing_Temp" /E /MOVE /MT:16 /R:2 /W:5

    2. STOP ONEDRIVE – Kill OneDrive.exe so it doesn't lock the files we're about to process. The script does this automatically, but it's worth knowing WHY — OneDrive loves to start syncing the moment a file changes, which can cause "file in use" errors during compression.

    3. COMPRESS – Run compress_videos_subfolders.py. It scans all subfolders, skips anything under 30MB, and compresses with NVENC H.265 at RF 20 using the "fast" preset.

    4. MOVE TO DESTINATION – Compressed files get moved to TARGET_FOLDER (NordLocker in my case). Original uncompressed files get deleted from the temp folder.

    5. START ONEDRIVE – OneDrive restarts automatically after processing, so it can start syncing the new compressed files.

    6. OPTIONAL SHUTDOWN – Add --shutdown when running the script and your PC will turn itself off 60 seconds after everything finishes:

       python compress_videos_subfolders.py --shutdown

It's basically: Copy → Stop Sync → Smash with GPU → Move → Start Sync → Go touch grass.


## Performance Tuning

### Controlling Worker Count

The parallel processing in compress_videos_subfolders.py (and compress_one_video.py) is controlled by MAX_WORKERS in the .env file, but you can also override it at runtime with the --workers flag:

    uv run compress_videos_subfolders.py --workers 2

### What's actually effective?

Here's the thing I learned the hard way: more workers does NOT mean linearly faster. On a single RTX 4070:

    - 1 worker  = one file at a time. GPU idles between encodes. Slowest overall.
    - 2 workers = the sweet spot. One file encodes while the other does file I/O (reading from HDD, writing output). Near 2x throughput.
    - 3 workers = default. Still good, slightly diminishing returns as the NVENC chip gets contended.
    - 5+ workers = don't bother. NVENC is a fixed hardware encoder, it can only chew through so many pixels per second. Extra workers just fight each other and inflate RAM usage.

For big 4K GoPro files, 2 workers is honestly plenty. For a pile of smaller 1080p clips, 3-4 can squeeze a bit more out of the GPU.

### RF Quality vs Speed

QUALITY_RF in .env is the single biggest lever for BOTH file size and speed:

    - RF 18 = slower, bigger files, near-lossless. For footage you really care about.
    - RF 22 = the sweet spot. ~70% smaller, imperceptible quality loss. This is what I use.
    - RF 26+ = fast and tiny, but you start seeing artifacts in high-motion footage.

### GPU Hardware Decoding (NVDEC)

Set `HW_DECODE = "true"` in `.env` and the script adds `--hwdecode` to the HandBrake command. This makes the GPU's NVDEC chip decode the source video instead of the CPU — CPU usage drops from 100% to ~10-15% and 4K encodes get significantly faster, since NVDEC decodes H.264 at many times real-time speed. Works with any NVIDIA GPU from the GTX 900 series onwards. Set to `"false"` to disable.

### Embedded Thumbnails (Windows Explorer previews)

HandBrake strips container-level cover art during re-encoding, so compressed files lose the preview thumbnails Windows Explorer shows for the originals. Set `THUMBNAIL_EMBED = "true"` in `.env` to restore them: after each successful compression, the script extracts one frame from the ORIGINAL video (5-second mark) with FFmpeg and attaches it as cover art into the compressed MP4. Fast remux, ~2-4 seconds per video, ~100-300 KB per thumbnail. Requires FFmpeg on PATH — if it's missing the script just skips thumbnails with a warning, the video itself is unaffected. Set to `"false"` to disable.

### Example Commands

The classic "I'm going to bed, compress my ENTIRE GoPro archive at max power and turn off the PC when done":

    uv run compress_videos_subfolders.py --shutdown

Same but with explicit worker count (ignores MAX_WORKERS in .env):

    uv run compress_videos_subfolders.py --workers 2 --shutdown

Normal run (waits for Enter at the end, PC stays on):

    uv run compress_videos_subfolders.py

Careful mode - one file at a time, for when you're watching the first run of a new batch and want to eyeball the quality:

    uv run compress_videos_subfolders.py --workers 1

Bonus: if you started the shutdown countdown but remembered you needed the PC, you have 60 seconds to cancel:

    shutdown /a


## Other Use Cases

### Action Camera Footage (GoPro, DJI, Insta360)

This script works just as well for action camera recordings as it does for game recordings.

The problem is the same: action cameras record at insanely high bitrates (60-100 Mbps) to keep up with fast motion, and H.264 is not exactly a space-efficient codec. A single afternoon of snowboarding can easily eat 80-100 GB of disk space. Not ideal.

The fix is the same too: NVENC H.265 encoding. The H.265 codec is specifically designed for high-resolution, high-motion content — exactly what action cameras produce. I've tested this with some 4K/60fps GoPro footage and got around 75% size reduction with zero visible quality loss (RF 20 is very conservative).

#### How it works with action cam folder structures

Action cameras dump files in a standard DCIM folder structure, something like:

    DCIM/
    └── 100GOPRO/
        ├── GX010001.MP4    (4.2 GB)
        ├── GX010002.MP4    (3.8 GB)
        ├── GX010001.THM    (thumbnail - skipped)
        └── GX010001.LRV    (low-res proxy - skipped)

The script's recursive scanning (os.walk) handles this natively. Just point INPUT_FOLDER to the root of the SD card or wherever you've dumped the footage, and it'll find everything. The .THM and .LRV files get ignored automatically because they're not in the VIDEO_EXTENSIONS tuple, and even if they were, they'd be well under the 30 MB threshold.

#### What to change

Literally nothing. Same .env file, same script. If you're doing a LOT of 4K footage, you COULD bump MAX_WORKERS down to 2 in compress_one_video.py — 4K encoding is heavier on the GPU's NVENC chips. But on an RTX 4070 with 3 workers I haven't run into issues.

If you really want to optimize for action cam specifically, you could:

    - Set QUALITY_RF to 22 instead of 20 (slightly more compression, still looks great)
    - Lower MIN_FILE_SIZE_MB to 10 if you want to catch shorter clips
    - Add '.MP4' (uppercase) to VIDEO_EXTENSIONS if your camera uses uppercase extensions

But again, the defaults Just Work™ for this use case.