import argparse
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional, Dict, Any

# IMPORTANT: Use responsibly. Only download content you have the right to download.
# Requires: pip install yt-dlp
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

APP_TITLE = "Simple YouTube Downloader (yt-dlp)"
DEFAULT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"

# Prefer single-file progressive MP4 when possible; fall back to merged A/V
QUALITY_MAP = {
    # First try a progressive MP4 (already video+audio in one file),
    # then fall back to MP4 video + M4A audio, and finally to best available.
    "Best (video+audio)": (
        "b[ext=mp4]/"
        "bv*[ext=mp4]+ba[ext=m4a]/"
        "bv*+ba/best"
    ),
    "1080p (if available)": (
        # Prefer a progressive MP4 up to 1080p if any exist (rare),
        # then fallback to separate tracks with merge, else best up to 1080p.
        "b[height<=1080][ext=mp4]/"
        "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
        "bv*[height<=1080]+ba/best[height<=1080]"
    ),
    "720p (if available)": (
        "b[height<=720][ext=mp4]/"
        "bv*[height<=720][ext=mp4]+ba[ext=m4a]/"
        "bv*[height<=720]+ba/best[height<=720]"
    ),
    "Audio only (m4a/mp3)": "bestaudio/best",
}

def build_ydl_opts(save_dir: Path, quality_key: str, audio_only_prefer_mp3: bool, progress_hook=None) -> Dict[str, Any]:
    fmt = QUALITY_MAP.get(quality_key, QUALITY_MAP["Best (video+audio)"])
    postprocessors = []
    if "Audio only" in quality_key:
        # Extract audio; prefer m4a; optionally transcode to mp3
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3" if audio_only_prefer_mp3 else "m4a",
            "preferredquality": "192",
        })
    else:
        # Remux to mp4 when feasible (yt-dlp will merge if fmt is video+audio)
        postprocessors.append({
            "key": "FFmpegVideoRemuxer",
            # Note: yt-dlp uses "preferedformat" (historical spelling)
            "preferedformat": "mp4",
        })

    ydl_opts: Dict[str, Any] = {
        "outtmpl": str(save_dir / DEFAULT_TEMPLATE),
        "format": fmt,
        "noprogress": True,
        "nopart": False,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "ignoreerrors": "only_download",
        "postprocessors": postprocessors,
        "progress_hooks": [progress_hook] if progress_hook else None,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        # Do not keep intermediate files; avoid extra outputs
        "keepvideo": False,
        "writethumbnail": False,
        "writeinfojson": False,
        # Prefer AVC/AAC when choices exist (more compatible, helps produce a single MP4)
        "format_sort": ["vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
        # Respectful defaults
        "ratelimit": None,    # set to an int (bytes/sec) if you want to throttle
        "throttledratelimit": None,
    }
    return ydl_opts

def run_download(url: str, save_dir: Path, quality_key: str, prefer_mp3: bool, hook, log) -> None:
    ydl_opts = build_ydl_opts(save_dir, quality_key, "Audio only" in quality_key and prefer_mp3, progress_hook=hook)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            log(f"Starting download to: {save_dir}")
            ydl.download([url])
            log("✅ Done.")
    except DownloadError as e:
        log(f"❌ Download failed: {e}")
    except Exception as e:
        log(f"❌ Unexpected error: {e}")

# ----------------- GUI -----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("680x420")
        self.minsize(640, 380)

        self.url_var = tk.StringVar()
        self.dir_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.quality_var = tk.StringVar(value="Best (video+audio)")
        self.prefer_mp3_var = tk.BooleanVar(value=False)

        # Initialize control variables BEFORE building UI that references them
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()

        self.downloading = False
        self.thread: Optional[threading.Thread] = None

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        # URL
        ttk.Label(frm, text="YouTube URL (video or playlist):").grid(row=0, column=0, sticky="w", **pad)
        url_entry = ttk.Entry(frm, textvariable=self.url_var)
        url_entry.grid(row=1, column=0, columnspan=3, sticky="ew", **pad)
        url_entry.focus()

        # Save dir
        ttk.Label(frm, text="Save to folder:").grid(row=2, column=0, sticky="w", **pad)
        dir_entry = ttk.Entry(frm, textvariable=self.dir_var)
        dir_entry.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…", command=self.choose_dir).grid(row=3, column=2, sticky="ew", **pad)

        # Quality
        ttk.Label(frm, text="Quality:").grid(row=4, column=0, sticky="w", **pad)
        quality_combo = ttk.Combobox(frm, values=list(QUALITY_MAP.keys()), textvariable=self.quality_var, state="readonly")
        quality_combo.grid(row=5, column=0, sticky="ew", **pad)

        mp3_chk = ttk.Checkbutton(frm, text="Prefer MP3 for audio-only", variable=self.prefer_mp3_var)
        mp3_chk.grid(row=5, column=1, sticky="w", **pad)

        # Buttons
        self.btn_download = ttk.Button(frm, text="Download", command=self.on_download)
        self.btn_download.grid(row=6, column=0, sticky="ew", **pad)

        self.btn_cancel = ttk.Button(frm, text="Cancel", command=self.on_cancel, state="disabled")
        self.btn_cancel.grid(row=6, column=1, sticky="ew", **pad)

        # Progress
        ttk.Label(frm, text="Progress:").grid(row=7, column=0, sticky="w", **pad)
        self.progress_bar = ttk.Progressbar(frm, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)

        # Status log
        ttk.Label(frm, text="Status:").grid(row=9, column=0, sticky="w", **pad)
        self.log_txt = tk.Text(frm, height=8, wrap="word")
        self.log_txt.grid(row=10, column=0, columnspan=3, sticky="nsew", **pad)

        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=0)
        frm.columnconfigure(2, weight=0)
        frm.rowconfigure(10, weight=1)

        # Footer
        disclaimer = "Use only where you have rights. Respect YouTube’s Terms of Service."
        ttk.Label(self, text=disclaimer, foreground="#666").pack(pady=(0,8))

    def choose_dir(self):
        path = filedialog.askdirectory(initialdir=self.dir_var.get() or str(Path.home()))
        if path:
            self.dir_var.set(path)

    def log(self, msg: str):
        self.log_txt.insert("end", msg + "\n")
        self.log_txt.see("end")
        self.status_var.set(msg)
        self.update_idletasks()

    def on_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a YouTube video or playlist URL.")
            return
        save_dir = Path(self.dir_var.get()).expanduser()
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Folder error", f"Cannot use folder:\n{e}")
            return

        self.downloading = True
        self.btn_download.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress_var.set(0)
        self.log("Queued…")

        def hook(d):
            # progress hook from yt-dlp
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                pct = (downloaded / total * 100) if total else 0
                self.progress_var.set(pct)
                spd = d.get("speed")
                eta = d.get("eta")
                msg = f"Downloading: {pct:5.1f}%"
                if spd:
                    msg += f" | {spd/1024/1024:.2f} MB/s"
                if eta:
                    msg += f" | ETA {int(eta)}s"
                self.status_var.set(msg)
            elif d.get("status") == "finished":
                self.progress_var.set(100)
                self.log("Post-processing… (merging, remuxing, etc.)")

        def worker():
            try:
                run_download(
                    url=url,
                    save_dir=save_dir,
                    quality_key=self.quality_var.get(),
                    prefer_mp3=self.prefer_mp3_var.get(),
                    hook=hook,
                    log=self.log
                )
            finally:
                self.downloading = False
                self.btn_download.config(state="normal")
                self.btn_cancel.config(state="disabled")

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def on_cancel(self):
        if self.downloading:
            messagebox.showinfo("Cancel", "Stopping after current fragment…")
        # yt-dlp doesn't expose a simple cancel; easiest is to exit app.
        # For a softer cancel, you'd need to integrate custom downloader or run ydl in a subprocess.
        self.destroy()

# ----------------- CLI -----------------
def run_cli():
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--url", required=True, help="YouTube video or playlist URL")
    parser.add_argument("--out", default=str(Path.home() / "Downloads"), help="Output directory")
    parser.add_argument("--quality", choices=list(QUALITY_MAP.keys()) + ["best", "1080p", "720p", "audio"], default="Best (video+audio)")

    parser.add_argument("--prefer-mp3", action="store_true", help="If audio-only, prefer MP3 (otherwise m4a)")
    args = parser.parse_args()

    quality = args.quality
    if args.quality == "best":
        quality = "Best (video+audio)"
    elif args.quality == "1080p":
        quality = "1080p (if available)"
    elif args.quality == "720p":
        quality = "720p (if available)"
    elif args.quality == "audio":
        quality = "Audio only (m4a/mp3)"

    outdir = Path(args.out).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    def log(msg: str):
        print(msg, flush=True)

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100) if total else 0
            spd = d.get("speed")
            eta = d.get("eta")
            line = f"\r{pct:5.1f}%"
            if spd: line += f" | {spd/1024/1024:.2f} MB/s"
            if eta: line += f" | ETA {int(eta)}s"
            print(line, end="", flush=True)
        elif d.get("status") == "finished":
            print("\nPost-processing…", flush=True)

    run_download(args.url, outdir, quality, args.prefer_mp3, hook, log)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # If CLI args provided, run CLI mode
        if any(s.startswith("--") for s in sys.argv[1:]):
            run_cli()
        else:
            # fall back to GUI if no proper flags passed
            app = App()
            app.mainloop()
    else:
        app = App()

        app.mainloop()
