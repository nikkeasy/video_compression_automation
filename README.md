# video_compression_automation
Fast way to compress your videos and save an enormous amount of space on your drive using Python and HandBrake CLI.

---

## 📑 Table of Contents
- [⚡ Turbo Quick Start (EZ Mode)](#-turbo-quick-start-ez-mode)
  - [1. Desktop with NVIDIA GPU](#1-desktop-with-nvidia-gpu-rtx-3070--4070--4080--etc)
  - [2. Intel Laptop / QuickSync (Core i7 + Iris Xe)](#2-intel-laptop--quicksync-core-i7--iris-xe)
  - [3. Universal Laptop / CPU Mode](#3-universal-laptop--cpu-mode)
  - [Quick Command Cheat Sheet](#quick-command-cheat-sheet)
- [📦 The Scripts - What Each File Does](#-the-scripts---what-each-file-does)
- [🛠️ Setup & Prerequisites](#️-setup--prerequisites)
- [🔄 The Full Pipeline – End to End](#-the-full-pipeline--end-to-end)
- [⚙️ Performance Tuning & Best Practices](#️-performance-tuning--best-practices)
- [📂 Special Case: Video Compression File Migration with RoboCopy](#-special-case-video-compression-file-migration-with-robocopy-hdd-to-ssd-staging)
- [🎥 Other Use Cases (Action Cams: GoPro, DJI, Insta360)](#-other-use-cases-action-cams-gopro-dji-insta360)
- [📝 Dev Notes & Origin Story (Personal POV)](#-dev-notes--origin-story-personal-pov)

---

## ⚡ Turbo Quick Start (EZ Mode)

Whether you are on a beastly desktop gaming rig or a basic laptop, here are the exact commands to run:

### 1. Desktop with NVIDIA GPU (RTX 3070 / 4070 / 4080 / etc.)
To max out your NVIDIA graphics card and compress at lightning speed:

```bash
uv run compress_videos_subfolders.py --gpu
```

**Recommended production run (with recommended flags):**
```bash
uv run compress_videos_subfolders.py --gpu --workers 2 --onedrive
```

**Flag breakdown:**
- `--gpu`: Uses NVIDIA NVENC hardware encoder (`nvenc_h265`) and turns on GPU hardware decoding (`--hwdecode`). Compression finishes in seconds per file and CPU usage drops to ~10-15%.
- `--workers 2`: Runs 2 video encodings in parallel. This is the sweet spot for an RTX 4070 to fully saturate the NVENC chip and disk throughput.
- `--onedrive`: Automatically stops `OneDrive.exe` before compression so files don't get locked by sync conflicts, and restarts OneDrive once finished.
- `--shutdown` *(optional)*: Automatically turns off your PC when all videos finish (ideal for overnight batches).

---

### 2. Intel Laptop / QuickSync (Core i7 + Iris Xe)
If your laptop has an Intel CPU (such as an **Intel Core i7** with **Intel Iris Xe Graphics**), you have hardware acceleration built directly into your chip:

```bash
uv run compress_videos_subfolders.py --qsv --workers 1
```

**Why `--qsv` on an Intel laptop:**
- Uses **Intel Quick Sync Video (QSV)** hardware encoding.
- **4–6x faster** than software CPU encoding.
- Keeps laptop fans quiet, prevents thermal throttling, and saves battery.

---

### 3. Universal Laptop / CPU Mode
If you are on an AMD laptop, older CPU, or a machine without any hardware acceleration:

```bash
uv run compress_videos_subfolders.py --cpu --workers 1
```
*(Or simply run `uv run compress_videos_subfolders.py` — the script automatically detects that no NVIDIA GPU is available and safely falls back to CPU mode!)*

**Why these flags on a laptop?**
- `--cpu`: Forces the universal `x265` software encoder. It works reliably on **any** machine.
- `--workers 1`: **Crucial for laptops!** Encoding on CPU is heavy. Running 1 worker ensures your laptop doesn't overheat, thermal throttle, or freeze up.
- `--preset fast`: Automatically uses a fast CPU preset so encodes finish in a reasonable timeframe.

---

### Quick Command Cheat Sheet

| Situation | Command | What it does |
| :--- | :--- | :--- |
| **Desktop + NVIDIA GPU** | `uv run compress_videos_subfolders.py --gpu --workers 2` | Max speed with NVENC H.265 |
| **Overnight GPU Run** | `uv run compress_videos_subfolders.py --gpu --workers 2 --onedrive --shutdown` | Pauses OneDrive, encodes, shuts down PC |
| **Intel Laptop (i7 / Iris Xe)** | `uv run compress_videos_subfolders.py --qsv --workers 1` | Fast hardware encoding via Intel QuickSync |
| **Universal Laptop (CPU)** | `uv run compress_videos_subfolders.py --cpu --workers 1` | Safe CPU x265 encoding, won't freeze laptop |
| **Auto-Detect** | `uv run compress_videos_subfolders.py` | Automatically checks for GPU, otherwise uses CPU |

---

## 📦 The Scripts - What Each File Does

### `compress_videos_subfolders.py` – Recursive, .env Powered (THE MAIN WORKHORSE)
This is the workhorse. Uses `os.walk()` to recursively scan ALL subfolders under `INPUT_FOLDER`. 
- Reads input/output paths and presets from your `.env` file so you don't have to edit code.
- Accepts flags like `--gpu`, `--cpu`, `--qsv`, `--workers`, and `--onedrive`.
- Skips files smaller than `MIN_FILE_SIZE_MB` (default 30MB or 200MB) — no point compressing tiny clips.
- Multi-threaded worker queue with clean, multi-line `tqdm` progress bars.
- Verifies output integrity before deleting source files.

### `compress_videos.py` – Single Folder, Simple
The original script. Scans ONE folder (`INPUT_FOLDER`), finds all `.mp4` and `.mkv` files, compresses them, moves compressed files to the target folder, and deletes originals. Use this if all your videos are already collected in one flat folder.

### `compress_one_video.py` – Standalone Parallel Tester
Uses `concurrent.futures.ThreadPoolExecutor` to process videos in parallel with individual progress bars. Useful for testing HandBrake worker limits on your GPU.

### `stop_onedrive_function.py` – OneDrive Helper
A standalone version of the OneDrive stop/start routines, useful for testing sync locks independently.

---

## 🛠️ Setup & Prerequisites

### 1. What You Need Installed
- **HandBrakeCLI** – The command-line engine for HandBrake. Download from [handbrake.fr](https://handbrake.fr/downloads.php). Place it at `C:\Program Files\HandBrake\CLI\HandBrakeCLI.exe` (the script auto-detects standard paths).
- **FFmpeg (Optional)** – Useful if you want thumbnail embedding (`THUMBNAIL_EMBED=true`) or safety probe verification.
- **uv (Recommended)** or Python 3.10+ – Ultra-fast Python package and environment manager.

### 2. Why `uv`? (Simple, Fast & Efficient + Virtual Environments)
We strongly recommend running these scripts with [`uv`](https://docs.astral.sh/uv/) instead of bare `python`:
- **Blazing Fast**: Written in Rust, `uv` installs packages and boots environments virtually instantly (10–100x faster than traditional pip).
- **Zero-Fuss Virtual Environments (`.venv`)**: No manual `python -m venv .venv` creation and no tedious `activate.bat` scripts. `uv` creates and maintains your isolated `.venv` automatically.
- **Effortless Runs**: Simply typing `uv run compress_videos_subfolders.py` immediately executes the script inside the isolated environment, keeping your system Python completely clean.

**Install uv (Windows PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Install Project Dependencies:**
```bash
uv add python-dotenv tqdm
```
*(Or if you prefer standard pip: `pip install python-dotenv tqdm`)*

### 3. The `.env` File
Create a `.env` file in the project root:

```ini
INPUT_FOLDER = "C:/Videos/Recordings"
TARGET_FOLDER = "C:/Videos/Recordings"
HANDBRAKE_CLI_PATH = "C:/Program Files/HandBrake/CLI/HandBrakeCLI.exe"
QUALITY_RF = "20"
POSTFIX = "_compressed"
MIN_FILE_SIZE_MB = "30"

# Optional overrides (if omitted, use CLI flags --gpu, --cpu, or --qsv):
# ENCODER = "nvenc_h265"  # For desktop with NVIDIA GPU
# ENCODER = "qsv_h265"    # For Intel laptop (QuickSync)
# ENCODER = "x265"        # For CPU software encoding
# PRESET = "fast"
```

> [!TIP]
> Use **forward slashes** (`/`) in path strings inside `.env` to prevent Windows escape character issues.

---

## 🔄 The Full Pipeline – End to End

Here is how the automated workflow operates from raw recording to compressed destination:

1. **PAUSE ONEDRIVE (Optional / Automatic):** With `--onedrive`, the script halts `OneDrive.exe` so background cloud sync doesn't lock video files during processing.
2. **RECURSIVE SCAN:** `compress_videos_subfolders.py` scans all folders and subfolders under `INPUT_FOLDER`. Files below `MIN_FILE_SIZE_MB` and previously compressed files (containing `_compressed`) are skipped.
3. **BATCH COMPRESSION:** Videos are processed through HandBrakeCLI according to your hardware mode (`--gpu`, `--qsv`, or `--cpu`), displaying real-time percentage progress bars.
4. **SAFETY VERIFICATION:** The script confirms that the compressed output exists and is non-empty before touching any original footage.
5. **THUMBNAIL EMBEDDING (Optional):** If `THUMBNAIL_EMBED="true"` and FFmpeg is present, a high-res cover frame is embedded directly into the MP4 container.
6. **MOVE & CLEANUP:** Compressed files are moved to `TARGET_FOLDER` (or saved in-place), and original uncompressed files are deleted to free up storage.
7. **RESUME ONEDRIVE:** OneDrive restarts so syncing can resume with the newly compressed, smaller files.
8. **OPTIONAL SHUTDOWN:** If `--shutdown` was passed, Windows schedules a 60-second shutdown countdown (cancel anytime via `shutdown /a`).

---

## ⚙️ Performance Tuning & Best Practices

### Controlling Worker Count
Worker count is controlled by `MAX_WORKERS` in `.env` or overridden with `--workers <N>`:
- **1 Worker:** Essential for CPU encoding on laptops to avoid 100% CPU lockup and thermal throttling.
- **2 Workers:** The sweet spot for NVIDIA GPUs (e.g. RTX 4070) — one file encodes while another handles disk read/write.
- **3+ Workers:** Good for smaller 1080p clips; diminishing returns on 4K due to NVENC hardware chip limits.

### RF Quality vs Speed
`QUALITY_RF` in `.env` (or via `-q <N>` / `--rf <N>`) controls the compression level:
- **RF 18–20:** Near-lossless, pristine quality, ~60–70% size reduction. Ideal for high-action drone/GoPro footage.
- **RF 22–24:** The sweet spot for game recordings and casual videos (~75–80% size reduction, visually identical).
- **RF 26+:** Ultra-small files, but high-motion scenes may show slight compression artifacts.

### GPU Hardware Decoding (`--hwdecode`)
Enabled automatically with `--gpu`. Instructs the GPU's NVDEC decoder to unpack the source video, taking decoding pressure off the CPU and dropping CPU usage from 100% to ~10–15%.

---

## 📂 Special Case: Video Compression File Migration with RoboCopy (HDD to SSD Staging)

> [!NOTE]
> **This is a special-case staging step, NOT the default workflow.**
> You only need RoboCopy if your raw recordings initially reside on a slow mechanical hard drive (HDD) and you want to stage them onto a fast NVMe SSD before compression.
> 
> **RoboCopy's purpose is NOT to move completed files.** The Python script itself handles moving completed files to OneDrive/destination and deleting originals.

### Why use RoboCopy for HDD to SSD Staging?
Encoding videos directly off a slow mechanical hard drive (e.g., external `H:\`) creates a major bottleneck: HandBrake's encoder constantly waits for slow disk read heads.

To solve this, RoboCopy can rapidly move raw recordings from the slow HDD to a local SSD temp folder before starting compression:

```bat
robocopy "H:\Game Recordings" "C:\Projects\Video_Processing_Temp" /E /MOVE /MT:16 /R:2 /W:5
```

### Parameter Breakdown:
- `/E` — Copies all subfolders, including empty ones (preserves full folder hierarchy).
- `/MOVE` — Deletes files and directories from the source HDD once successfully copied to the SSD, freeing up HDD space.
- `/MT:16` — Enables multi-threaded copying with 16 parallel threads, maximizing transfer speeds over SATA/USB.
- `/R:2` — Retries only 2 times if a file is locked (default is 1,000,000 retries, which would hang the script indefinitely).
- `/W:5` — Waits 5 seconds between retries instead of the default 30 seconds.

Once this one-time migration finishes, you run the Python script on the fast SSD folder.

---

## 🎥 Other Use Cases (Action Cams: GoPro, DJI, Insta360)

Action cameras dump high-bitrate footage (60–100 Mbps) in H.264, easily consuming 80–100 GB in a single afternoon.

The script natively handles standard action camera folder structures:
```text
DCIM/
└── 100GOPRO/
    ├── GX010001.MP4    (4.2 GB -> compresses to ~900 MB)
    ├── GX010002.MP4    (3.8 GB -> compresses to ~800 MB)
    ├── GX010001.THM    (skipped automatically)
    └── GX010001.LRV    (skipped automatically)
```
- Non-video metadata (`.THM`, `.LRV`) and files smaller than `MIN_FILE_SIZE_MB` are ignored automatically.
- Tested extensively on DJI Osmo Action and GoPro 4K/60fps footage with ~75% reduction and imperceptible quality difference.

---

## 📝 Dev Notes & Origin Story (Personal POV)

*(For those curious about how this pipeline came to be and the troubleshooting lessons along the way)*

### The HandBrakeCLI Mystery
I initially set out to compress raw gameplay recordings manually in CMD on Windows using `HandBrakeCLI.exe`. My first test command looked like this:

```bat
"C:\Program Files\HandBrake\HandBrakeCLI.exe" -i "Fortnite_test.mp4" -o "MyTestVideo_compressed.mp4" --preset Web/Creator 1080p60
```

That failed because the preset parameter had spaces and needed quotation marks:

```bat
"C:\Program Files\HandBrake\HandBrakeCLI.exe" -i "Fortnite_test.mp4" -o "MyTestVideo_compressed.mp4" --preset "Web/Creator 1080p60"
```

The syntax was now technically valid, but HandBrakeCLI still threw errors and refused to process the file—even though the exact same file loaded fine in the HandBrake desktop GUI! 

I consulted Gemini, which suggested the container might need **remuxing** with FFmpeg due to malformed MP4 atoms or bad headers. I downloaded FFmpeg, opened CMD, and typed:

```bat
"C:\ffmpeg\bin\ffmpeg.exe" -i "Fortnite_test.mp4.mp4" -c copy "Fortnite_test_remuxed.mp4"
```
*(Notice the `.mp4.mp4` extension—turns out Windows had hidden known extensions, and the original filename had a double extension all along!)*

### Unleashing the RTX 4070
Once the container issue was sorted, I switched from CPU presets to NVIDIA hardware encoding (`nvenc_h265`). 

The test results were staggering:
- **Raw recording:** 1.68 GB
- **Compressed file:** Under 300 MB (~82% reduction)
- **Time taken:** ~40 seconds

That proved that hardware H.265 compression was not just viable—it was a total game-changer. Rather than manually encoding clips one by one in CMD, I built this automated Python project to recursively scan entire folder structures, handle parallel workers, prevent OneDrive sync collisions, verify file integrity, and tidy up afterwards.