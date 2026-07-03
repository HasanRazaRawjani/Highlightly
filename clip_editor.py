"""
Highlightly v3.1 — Ultra-Fast Valorant Clip Editor (Cinematic Blur Restored)
---------------------------------------------------------------------------
Drop source clips into input_clips/, get back edited vertical shorts in edited_clips/.

Requirements:
    pip install groq openai openai-whisper numpy scipy requests
    ffmpeg on PATH

Features:
  - High-Visibility Layout: 4:3 centered foreground on top of a 16:9 heavily blurred background
  - Powered by Groq Cloud (Whisper Large V3) for near-instant cloud transcriptions
  - Strict Word-Level Timing explicitly forced to eliminate out-of-sync caption ahead-runs
  - Fast-Talk Phrase Optimizer: Clusters word metrics into fluid 6-word sentence structures
  - Native ASS Subtitle Pipeline: Multi-color CapCut styled middle yellow text pops
  - Multi-Track Source Audio Downmixing: Combines mic + discord + game sounds flawlessly
  - Low-Payload MP3 Pre-encoding: Cuts down upload payloads to prevent connection resets
  - Automatic Local Engine Fallback if offline or no cloud key is configured
"""

import os
import sys
import json
import subprocess
import random

# ─────────── CONFIGURATION ───────────
# Get a free API key from https://console.groq.com/
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "your_groq_key_here")  # Replace with your gsk_xxxx key
MUSIC_VOLUME       = float(os.environ.get("HIGHLIGHTLY_MUSIC_VOLUME", "0.08"))       # Background music ceiling scaling
FONT_NAME          = os.environ.get("HIGHLIGHTLY_FONT_NAME", "Impact")   # Modern heavy gaming caption standard
FONT_SIZE          = int(os.environ.get("HIGHLIGHTLY_FONT_SIZE", "85"))         # Balanced size for sentence-based phrases
CAPTION_MARGIN_V   = int(os.environ.get("HIGHLIGHTLY_CAPTION_MARGIN_V", "180"))        # Vertical alignment clearance from the TOP edge
OUTPUT_W           = int(os.environ.get("HIGHLIGHTLY_OUTPUT_W", "1080"))       # Target output resolution width
OUTPUT_H           = int(os.environ.get("HIGHLIGHTLY_OUTPUT_H", "1920"))       # Target output resolution height
ZOOM_AMOUNT        = float(os.environ.get("HIGHLIGHTLY_ZOOM_AMOUNT", "1.04"))       # Constant foreground zoom (1.0 = none, 1.04 = subtle dynamic punch)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR  = os.path.join(BASE_DIR, "input_clips")
OUTPUT_DIR = os.path.join(BASE_DIR, "edited_clips")
MUSIC_DIR  = os.path.join(BASE_DIR, "music")
TEMP_DIR   = os.path.join(BASE_DIR, "_temp")
# ──────────────────────────────────────


def ffrun(cmd):
    """Executes an FFmpeg pipeline subprocess cleanly."""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )


def get_info(path):
    """Probes video and audio assets using ffprobe to gather exact track structures."""
    r = ffrun(["ffprobe", "-v", "error",
                "-show_entries", "stream=codec_type,width,height",
                "-show_entries", "format=duration",
                "-of", "json", path])
    try:
        d = json.loads(r.stdout)
    except Exception:
        return 1920, 1080, 0.0, 0

    streams = d.get("streams", [])
    w, h = 1920, 1080
    audio_stream_count = 0
    
    for s in streams:
        if s.get("codec_type") == "video":
            w = int(s.get("width", 1920))
            h = int(s.get("height", 1080))
        elif s.get("codec_type") == "audio":
            audio_stream_count += 1

    dur = float(d.get("format", {}).get("duration", 0))
    return w, h, dur, audio_stream_count


def extract_whisper_audio(video_path, audio_stream_count, out_path):
    """Extracts and downmixes all hidden audio streams into a web-optimized tiny MP3 file."""
    cmd = ["ffmpeg", "-y", "-i", video_path]
    if audio_stream_count > 1:
        mix_inputs = "".join(f"[0:a:{i}]" for i in range(audio_stream_count))
        filter_str = f"{mix_inputs}amix=inputs={audio_stream_count}:duration=longest[aout]"
        cmd += ["-filter_complex", filter_str, "-map", "[aout]"]
    elif audio_stream_count == 1:
        cmd += ["-map", "0:a:0"]
    else:
        return False
        
    cmd += ["-c:a", "libmp3lame", "-b:a", "64k", "-ar", "16000", "-ac", "1", out_path]
    res = ffrun(cmd)
    return res.returncode == 0 and os.path.exists(out_path)


def transcribe(audio_path):
    """Transcribes audio using Groq Cloud (Whisper Large V3) with local offline fallback."""
    api_key = GROQ_API_KEY if GROQ_API_KEY != "your_groq_key_here" else os.environ.get("GROQ_API_KEY")
    
    if api_key:
        from openai import OpenAI
        print("  Sending audio track to Groq Cloud (Whisper Large V3)...")
        try:
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
            response = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=open(audio_path, "rb"),
                response_format="verbose_json",
                language="en",
                temperature=0.0,
                # CRITICAL: Forces Groq to pass back exact microsecond word bounds instead of wide chunks
                timestamp_granularities=["word"], 
                prompt="Valorant player microphone commentary, live callouts, gaming tactical comms."
            )
            result = response.model_dump() if hasattr(response, "model_dump") else response
            return parse_word_timestamps(result)
        except Exception as e:
            print(f"  Groq cloud transcription failed: {e}. Falling back to local engine...")

    # Offline local fallback using open-source whisper engine
    print("  No active cloud API key found. Initializing local Whisper engine...")
    try:
        import whisper
    except ImportError:
        print("\n[Dependency Error]: Local fallback requires whisper. Please run: pip install openai-whisper")
        sys.exit(1)

    model = whisper.load_model("base")
    print("  Transcribing locally (this may take a few moments)...")
    result = model.transcribe(
        audio_path, 
        language="en", 
        temperature=0.0,
        word_timestamps=True,
        initial_prompt="Valorant player microphone commentary, live callouts, gaming tactical comms."
    )
    return parse_word_timestamps(result)


def parse_word_timestamps(result):
    """Safely extracts segment or precise word-level metadata layers from the transcription results."""
    words = []
    
    # 1. Inspect if top-level word object is provided natively
    if "words" in result and result["words"]:
        for w in result["words"]:
            words.append({
                "word": w.get("word", "").strip(),
                "start": w.get("start", 0),
                "end": w.get("end", 0)
            })
        return words

    # 2. Inspect inner timeline segment containers
    segments = result.get("segments", [])
    for seg in segments:
        if seg.get("no_speech_prob", 0) > 0.45:
            continue
            
        if "words" in seg and seg["words"]:
            for w in seg["words"]:
                words.append({
                    "word": w.get("word", "").strip(),
                    "start": w.get("start", seg.get("start", 0)),
                    "end": w.get("end", seg.get("end", 0))
                })
        else:
            # Fallback segment splitter if precision layer metrics failed
            seg_text = seg.get("text", "").strip()
            if not seg_text:
                continue
            seg_words = seg_text.split()
            start_time = seg.get("start", 0)
            end_time = seg.get("end", 0)
            duration = max(0.05, end_time - start_time)
            word_dur = duration / max(1, len(seg_words))
            
            for i, w_str in enumerate(seg_words):
                words.append({
                    "word": w_str,
                    "start": start_time + (i * word_dur),
                    "end": start_time + ((i + 1) * word_dur)
                })
    return words


def group_captions(words, max_words=6, max_chars=32, max_gap=0.45):
    """
    Groups individual elements into natural sentences or short phrases.
    Ensures text blocks stay on screen long enough for fast-talk streams.
    """
    if not words:
        return []
    
    groups, cur, cur_len = [], [], 0
    for w in words:
        word_cleaned = w["word"].strip().upper()
        if not word_cleaned:
            continue
        w["word"] = word_cleaned
        
        is_break = False
        if cur:
            if len(cur) >= max_words:
                is_break = True
            elif cur_len + len(w["word"]) + 1 > max_chars:
                is_break = True
            elif w["start"] - cur[-1]["end"] > max_gap:
                is_break = True
            elif cur[-1]["word"].endswith((".", "!", "?")):
                is_break = True

        if is_break and cur:
            groups.append(cur)
            cur, cur_len = [], 0
            
        cur.append(w)
        cur_len += len(w["word"]) + 1
        
    if cur:
        groups.append(cur)
        
    return [
        {"text": " ".join(w["word"] for w in g),
         "start": g[0]["start"],
         "end":   g[-1]["end"]}
        for g in groups
    ]


def _ass_time(s):
    """Seconds → ASS timestamp H:MM:SS.cc"""
    h  = int(s // 3600)
    m  = int((s % 3600) // 60)
    sc = s % 60
    cs = int(round((sc % 1) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{int(sc):02d}.{cs:02d}"


def write_ass(captions, path, play_w, play_h):
    """Writes styled subtitles to disk using advanced ASS formatting with popping highlights."""
    # Alignment 8 = Top Center (Ideal layout visibility standard)
    style = (
        f"Style: Default,{FONT_NAME},{FONT_SIZE},"
        f"&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"  # White text, Black outline, Black shadow
        f"-1,0,0,0,100,100,0,0,1,5,1,8,"                 # Thick Outline=5, Alignment=8
        f"10,10,{CAPTION_MARGIN_V},1"
    )
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_w}",
        f"PlayResY: {play_h}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    
    for cap in captions:
        start = _ass_time(cap["start"])
        end   = _ass_time(max(cap["end"], cap["start"] + 0.05))
        text  = cap["text"].replace("{", r"\{").replace("}", r"\}")
        
        # CapCut Phrase Highlights: Dynamic mid-sentence yellow highlighting (\c&H00FFFF&)
        tokens = text.split()
        if len(tokens) > 2:
            mid = len(tokens) // 2
            tokens[mid] = f"{{\\c&H00FFFF&}}{tokens[mid]}"
            if mid + 1 < len(tokens):
                tokens[mid+1] = f"{tokens[mid+1]}{{\\c&H00FFFFFF&}}"
            else:
                tokens[mid] = f"{tokens[mid]}{{\\c&H00FFFFFF&}}"
            text = " ".join(tokens)
        elif len(tokens) == 2:
            tokens[1] = f"{{\\c&H00FFFF&}}{tokens[1]}{{\\c&H00FFFFFF&}}"
            text = " ".join(tokens)
            
        # Add a smooth scaling pop animation to emphasize speech timing
        animated_text = f"{{\\fscx85\\fscy85\\t(0,80,\\fscx100\\fscy100)}}{text}"
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{animated_text}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def pick_music():
    """Scans the music directory to select a random audio track."""
    if not os.path.isdir(MUSIC_DIR):
        return None
    files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith((".mp3", ".wav", ".aac", ".m4a"))]
    return os.path.join(MUSIC_DIR, random.choice(files)) if files else None


def edit_clip(input_path, output_path):
    """Processes a clip: crops, centers, downmixes audio, transcribes, and burns animated subtitles."""
    name = os.path.basename(input_path)
    print(f"\n{'='*60}\nProcessing File: {name}\n{'='*60}")

    os.makedirs(TEMP_DIR, exist_ok=True)
    ass_path = os.path.join(TEMP_DIR, "captions.ass")
    mp3_path = os.path.join(TEMP_DIR, "whisper_input.mp3")

    try:
        src_w, src_h, dur, audio_stream_count = get_info(input_path)
        print(f"  Metadata → Dimension: {src_w}x{src_h} | Time: {dur:.1f}s | Audio Tracks Located: {audio_stream_count}")

        # ── Optimized Downmixed Audio Stream Extraction ──
        if audio_stream_count > 0:
            success = extract_whisper_audio(input_path, audio_stream_count, mp3_path)
            words = transcribe(mp3_path if success else input_path)
        else:
            words = []
            
        captions = group_captions(words)
        print(f"  Generated {len(captions)} multi-word phrase structural text blocks.")

        write_ass(captions, ass_path, OUTPUT_W, OUTPUT_H)

        # Format subtitle string layout safely for Windows/Unix directory processing chains
        ass_ffmpeg = ass_path.replace("\\", "/").replace(":", "\\:")

        # ── High-Visibility Cinematic Layout Filter Graph Construction ──
        # 1. Background layer (bg): Scales to fill vertical bounds, crops to 1080x1920, applies strong blur
        # 2. Foreground layer (fg): Cuts source into clean 4:3 gaming frame aspect standard, scales width, scales to target
        # 3. Blending stage: Overlays foreground directly center on top of the blurred background frame
        # 4. Optional Push Zoom: Applies an extra resizing layer sequence over the composition if configured
        vf_pipeline = (
            f"split=2[bg_src][fg_src];"
            f"[bg_src]scale={OUTPUT_W}:{OUTPUT_H}:force_original_aspect_ratio=increase,crop={OUTPUT_W}:{OUTPUT_H},boxblur=luma_radius=25:luma_power=4[bg];"
            f"[fg_src]crop='min(iw,ih*4/3)':ih,scale={OUTPUT_W}:-2:flags=lanczos[fg_scaled];"
            f"[bg][fg_scaled]overlay=(W-w)/2:(H-h)/2"
        )

        if ZOOM_AMOUNT > 1.0:
            zoomed_w = int(OUTPUT_W * ZOOM_AMOUNT)
            zoomed_h = int(OUTPUT_H * ZOOM_AMOUNT)
            zoomed_w += zoomed_w % 2
            zoomed_h += zoomed_h % 2
            vf_pipeline += f",scale={zoomed_w}:{zoomed_h}:flags=lanczos,crop={OUTPUT_W}:{OUTPUT_H}"
            
        vf_pipeline += f",ass='{ass_ffmpeg}'"

        # ── Audio Mixing & Subprocess Pipeline Building ──
        music_path = pick_music()
        cmd = ["ffmpeg", "-y", "-i", input_path]
        if music_path:
            cmd += ["-stream_loop", "-1", "-i", music_path]

        # Mixed Track Complex Structure Matrix
        filter_complex_blocks = [f"[0:v]{vf_pipeline}[vout]"]
        
        if audio_stream_count > 1:
            mix_inputs = "".join(f"[0:a:{i}]" for i in range(audio_stream_count))
            filter_complex_blocks.append(f"{mix_inputs}amix=inputs={audio_stream_count}:duration=longest,volume=1.0[source_audio]")
        elif audio_stream_count == 1:
            filter_complex_blocks.append("[0:a:0]volume=1.0[source_audio]")

        if audio_stream_count > 0 and music_path:
            filter_complex_blocks.append(f"[1:a]volume={MUSIC_VOLUME}[music_scaled]")
            filter_complex_blocks.append("[music_scaled][source_audio]sidechaincompress=threshold=0.15:ratio=4:attack=50:release=300[music_ducked]")
            filter_complex_blocks.append("[source_audio][music_ducked]amix=inputs=2:duration=first[aout]")
            cmd += ["-filter_complex", ";".join(filter_complex_blocks), "-map", "[vout]", "-map", "[aout]"]
        elif audio_stream_count > 0 and not music_path:
            if filter_complex_blocks:
                cmd += ["-filter_complex", ";".join(filter_complex_blocks), "-map", "[vout]", "-map", "[source_audio]"]
            else:
                cmd += ["-vf", vf_pipeline, "-map", "0:v", "-map", "0:a:0"]
        elif audio_stream_count == 0 and music_path:
            filter_complex_blocks.append(f"[1:a]volume={MUSIC_VOLUME}[aout]")
            cmd += ["-filter_complex", ";".join(filter_complex_blocks), "-map", "[vout]", "-map", "[aout]"]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            cmd += ["-filter_complex", ";".join(filter_complex_blocks), "-map", "[vout]", "-map", "1:a"]

        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(dur),
            output_path,
        ]

        print("  Rendering composition output...")
        result = ffrun(cmd)
        
        if result.returncode != 0:
            print("  [FFmpeg Error Encountered Log Trace]:")
            print(" ", (result.stderr or "")[-1200:])
            return False

        file_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"  Export Complete → {os.path.basename(output_path)} ({file_mb:.2f} MB)")
        return True

    except Exception as e:
        import traceback
        print(f"  Pipeline Engine Crash: {e}")
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup temporary audio files safely
        if os.path.exists(ass_path):
            try:
                os.remove(ass_path)
            except Exception:
                pass
        if os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except Exception:
                pass


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(MUSIC_DIR,  exist_ok=True)

    if len(sys.argv) > 1:
        inp = sys.argv[1]
        if not os.path.exists(inp):
            print(f"Error: Target clip path does not exist: {inp}")
            sys.exit(1)
        stem = os.path.splitext(os.path.basename(inp))[0]
        edit_clip(inp, os.path.join(OUTPUT_DIR, f"{stem}_edited.mp4"))
        return

    os.makedirs(INPUT_DIR, exist_ok=True)
    clips = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith((".mp4", ".mov", ".mkv"))]
    if not clips:
        print(f"Directory empty: drop clips into '{INPUT_DIR}/' to begin.")
        return

    print(f"Discovered {len(clips)} matching clip assets.")
    success_count = failure_count = 0
    
    for fname in clips:
        inp  = os.path.join(INPUT_DIR, fname)
        stem = os.path.splitext(fname)[0]
        out  = os.path.join(OUTPUT_DIR, f"{stem}_edited.mp4")
        if edit_clip(inp, out):
            success_count += 1
        else:
            failure_count += 1

    print(f"\n{'='*60}\nProcessing metrics: {success_count} exported cleanly, {failure_count} errors encountered.\nOutputs available inside: '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()
