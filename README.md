# Highlightly

**Turn Valorant gameplay clips into phone-ready YouTube Shorts and TikToks — automatically.**

Highlightly is a Windows desktop app that takes your 16:9 gameplay footage (Medal, OBS, in-game recordings, etc.), crops it to vertical 9:16, generates synced karaoke-style captions, detects kills with a custom YOLO model, and exports a finished short ready to upload.

**Live site (demo + download):** https://highlightly.xyz/

---

## What it does

1. **Drop a clip** — `.mp4`, `.mov`, or `.mkv` from any clipping software.
2. **Highlightly edits locally** — rendering runs on your PC, not in the cloud.
3. **Get a vertical short** — captions, optional background music, kill effects, and a file in `edited_clips/` ready to post.

No manual timeline scrubbing. No CapCut-style hand-editing for every clip.

---

## Try it

| Link | Purpose |
|------|---------|
| [highlightly.xyz](https://highlightly.xyz/) | Live website — sign up and download the Windows installer |
| [GitHub repo](https://github.com/HasanRazaRawjani/Highlightly) | Source code |

**Quick start for end users:**

1. Open https://highlightly.xyz/
2. Create a free account and sign in
3. Click **Download the app** and run `highlightly-setup.exe`
4. Launch Highlightly, drop a Valorant clip into the queue, and click render

> **Note:** The app is Windows-only. FFmpeg is bundled in the installer build. A Groq API key (optional) speeds up caption generation; local Whisper works as a fallback.

---

## Features

### Video pipeline

- **9:16 vertical export** with cinematic blur background (4:3 gameplay window over a blurred mirror layer)
- **Auto captions** — Groq Whisper Large V3 (cloud) with local Whisper fallback
- **Word-level sync** — karaoke-style ASS subtitles with spring-scale entrance and yellow word pop
- **Dual-speaker lanes** — separate caption tracks when mic + Discord/game audio overlap
- **Background music** — optional `.mp3`/`.wav` with sidechain ducking under voice
- **Batch rendering** (Pro)

### Valorant-specific

- **Custom YOLO kill detection** — trained on Roboflow (~91% mAP on kill banners)
- **Kill FX (Pro)** — red flash, screen shake, zoom punch, on-screen kill counter at detected timestamps

### App & distribution

- **Desktop GUI** — Tkinter app with clip queue, preview, and settings
- **Windows installer** — Inno Setup wizard with Terms, Privacy, Start menu entry, uninstaller
- **Account system** — Supabase auth; Free and Pro tiers via Stripe on the website

---

## Tech stack

| Layer | Tools |
|-------|-------|
| Desktop app | Python 3, Tkinter, Pygame (preview) |
| Render engine | FFmpeg, ASS subtitles |
| Captions | Groq API (Whisper Large V3), OpenAI Whisper (local fallback) |
| Kill detection | Ultralytics YOLOv8, OpenCV |
| Auth & billing | Supabase, Stripe |
| Website | Static HTML/CSS/JS on Netlify |
| Packaging | PyInstaller, Inno Setup |

---

## Project structure

```
Highlightly/
├── App_Deploy/                  # Main application (desktop + render engine)
│   ├── highlightly_desktop_app.py   # GUI
│   ├── clip_editor.py               # FFmpeg render pipeline
│   ├── valorant_kill_detector_yolo.py
│   ├── youtube_upload.py
│   ├── lib/                         # Runtime paths, bundled FFmpeg
│   ├── packaging/                   # PyInstaller + Inno Setup build scripts
│   ├── models/valorant_kill/        # YOLO weights (best.pt)
│   ├── input_clips/                 # Drop raw clips here (dev)
│   └── edited_clips/                # Rendered output (dev)
├── Website/                     # highlightly.xyz frontend
├── training/                    # YOLO dataset (Roboflow export)
└── README.md                    # You are here
```

See also:

- [App_Deploy/README_APP.md](App_Deploy/README_APP.md) — dev layout, Free vs Pro, Groq key setup
- [App_Deploy/packaging/README.md](App_Deploy/packaging/README.md) — building the `.exe` and installer
- [App_Deploy/models/valorant_kill/README.md](App_Deploy/models/valorant_kill/README.md) — kill detection model details

---

## Development setup

**Requirements:** Windows 10+, Python 3.10+, FFmpeg on PATH

```powershell
git clone https://github.com/HasanRazaRawjani/Highlightly.git
cd Highlightly/App_Deploy

pip install openai openai-whisper numpy scipy requests groq opencv-python pillow ultralytics pygame

# Optional: faster captions
set GROQ_API_KEY=gsk_your_key_here

# Run the desktop app
Launch Highlightly App.bat
```

Drop test clips in `App_Deploy/input_clips/`. Rendered files appear in `App_Deploy/edited_clips/`.

### Build a release

```powershell
# Single portable exe
Build Highlightly.bat
# → App_Deploy/release/Highlightly.exe

# Windows installer (what the website ships)
Build Highlightly Setup.bat
# → App_Deploy/release/highlightly-setup.exe
```

Full build docs: [App_Deploy/packaging/README.md](App_Deploy/packaging/README.md)

---

## Free vs Pro

| Feature | Free | Pro |
|---------|------|-----|
| Download & render | Yes | Yes |
| One clip at a time | Yes | — |
| Batch rendering | — | Yes |
| Caption font size / margin / zoom sliders | — | Yes |
| Custom output resolution | — | Yes |
| Kill FX (flash, shake, zoom, counter) | — | Yes |
| Watermark | Yes | No |

---

## AI usage

This project uses AI in these specific ways:

- **Groq Whisper API** — cloud speech-to-text for auto captions (optional; local Whisper fallback exists)
- **Custom YOLO model** — trained on labeled Valorant screenshots (Roboflow); not a generic pre-trained model
- **Development assistance** — AI was used during development for debugging and brainstorming; all core design, pipeline architecture, and most code were written by the author

Highlightly is **not** a one-prompt generated app. The render pipeline, GUI, installer, website, and YOLO training workflow were built and iterated manually over ~70 logged hours.

---

## Screenshots

_Add screenshots here — e.g. `docs/screenshots/app-queue.png`, `docs/screenshots/output-short.png`._

Suggested captures:

- Desktop app with a clip in the queue
- Before/after: 16:9 raw clip vs 9:16 exported short
- Kill FX enabled on a multi-kill clip

---

## Author

**Hasan**

- Website: https://highlightly.xyz/
- GitHub: https://github.com/HasanRazaRawjani/Highlightly
