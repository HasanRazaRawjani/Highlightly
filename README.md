# 🔒 Highlightly v3.1 — Private Valorant Clip Pipeline
> **PROPRIETARY & CONFIDENTIAL** > *This repository, source code, and assets are private intellectual property. Unauthorized copying, distribution, or execution of this software via any medium is strictly prohibited.*

Highlightly is an automated, high-performance private script built to transform standard 16:9 widescreen desktop gameplay clips into edited, vertical (9:16) shorts for personal use. It automates high-end video layout designs, multi-track gaming audio engineering, and dynamic kinetic subtitles using advanced AI.

---

## 🛠️ Internal Operational Stack

* **Cinematic Blur Canvas Layering:** Drops a `4:3` cropped gameplay container over a heavily box-blurred, scaled background mirror layer. Captures all high-action screen elements without sacrificing vertical frame compliance.
* **Groq Cloud API Core (Whisper Large V3):** Routes optimized audio tracks through Groq's high-speed cloud architecture. Completes 60-second video transcriptions in less than 1 second.
* **Strict Word-Level Timing Synchronization:** Forces microscopic word-level token lookups (`timestamp_granularities=["word"]`) directly on the API layer. Zero text delay or caption running ahead of your voice.
* **Fast-Talk Clustered Phrasing:** Automatically bundles split word timestamps into 6-word sentences. Prevents the text from blinking or flashing too quickly when speaking fast.
* **CapCut Styled Kinetic Subtitles:** Uses internal ASS tagging rules to build a spring-scale entrance animation combined with an automated, mid-sentence **Bright Yellow Text Pop**.
* **Lossless Multi-Track Downmixing:** Automatically sweeps, extracts, and mixes individual multi-track audio pipelines (Game Audio, Discord Comms, Microphone) into a single master track.
* **Upload Stream Pre-Encoding:** Extracts downmixed audio into a highly compressed, light `64kbps` mono MP3 file before processing via cloud API, removing connection resets entirely.

---

## 📂 Project Structure

Maintain the local directory tree exactly as follows:

```text
Highlightly/
│
├── clip_editor.py        # Master pipeline source script
├── input_clips/          # Drop raw 16:9 gameplay footage files here
├── edited_clips/         # Compiled vertical vertical shorts render out here
├── music/                # (Optional) Drop background tracks here (.mp3, .wav)
└── _temp/                # Auto-generated internal folder for transient execution steps
