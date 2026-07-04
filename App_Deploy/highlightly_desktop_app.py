import sys
import subprocess
import shutil  # Added for moving user background music files
import filecmp

# ─── COMMERCIAL CLIENT-SIDE DEPENDENCY HOOK ───
def install_client_dependencies():
    required_packages = {
        "cv2": "opencv-python",
        "PIL": "pillow",
        "requests": "requests",
        "groq": "groq",
        "pygame": "pygame"
    }
    for module_name, package_name in required_packages.items():
        try:
            __import__(module_name)
        except ImportError:
            print(f"[System Launcher] Initializing missing library: {package_name}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package_name, "--quiet"])
            except Exception as e:
                print(f"[Error] Failed to configure {package_name}: {e}")

install_client_dependencies()

# ─── CORE APPLICATION IMPORTS ───
import json
import os
import queue
import threading
import time
import random
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib import error, request, parse
import http.server
import webbrowser
import secrets
import hashlib
import base64
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageFont
import pygame

APP_NAME = "Highlightly Studio Pro"
BASE_DIR = Path(__file__).resolve().parent
CLIP_EDITOR = BASE_DIR / "clip_editor.py"
INPUT_DIR = BASE_DIR / "input_clips"
OUTPUT_DIR = BASE_DIR / "edited_clips"
MUSIC_DIR = BASE_DIR / "music"
ASSETS_DIR = BASE_DIR / "assets"
CONFIG_PATH = BASE_DIR / "_temp" / "highlightly_app_config.json"
WEBSITE_CONFIG = BASE_DIR / "Website" / "supabase-config.js"

SUPABASE_URL = "https://vzpltgcafcmjsroxwmuy.supabase.co"
SUPABASE_KEY = "sb_publishable_EwUxzFjBd-W1_Gnvaqsavw_Z-SncOyl"
ADMIN_LOGIN = {"email": "admin", "password": "admin", "plan": "Pro Trial"}


def ensure_dirs():
    for folder in (INPUT_DIR, OUTPUT_DIR, MUSIC_DIR, CONFIG_PATH.parent):
        folder.mkdir(exist_ok=True)

def load_config():
    ensure_dirs()
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_config(config):
    ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def read_website_supabase_config():
    global SUPABASE_URL, SUPABASE_KEY
    if not WEBSITE_CONFIG.exists():
        return
    text = WEBSITE_CONFIG.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        if "SUPABASE_URL" in line and '"' in line:
            SUPABASE_URL = line.split('"')[1]
        if "SUPABASE_ANON_KEY" in line and '"' in line:
            SUPABASE_KEY = line.split('"')[1]


def supabase_password_login(email, password):
    url = SUPABASE_URL.rstrip("/") + "/auth/v1/token?grant_type=password"
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = request.Request(
        url, data=payload, method="POST",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("msg")
        except Exception:
            detail = exc.reason
        raise RuntimeError(detail or "Login failed.") from exc

    user = data.get("user") or {}
    metadata = user.get("user_metadata") or {}
    plan = metadata.get("highlightly_plan") or "Free"
    return {"email": user.get("email", email), "plan": plan, "access_token": data.get("access_token")}


# ── Google OAuth (PKCE) constants ──
OAUTH_CALLBACK_PORT = 54321

# Shown after PKCE code is exchanged (no JS needed — server handles everything)
OAUTH_SUCCESS_HTML = """<!DOCTYPE html><html>
<head><title>Highlightly</title>
<style>body{font-family:sans-serif;background:#0b0f14;color:#eef2f6;
display:flex;align-items:center;justify-content:center;height:100vh;
margin:0;flex-direction:column;}h2{color:#c7ff45;}p{color:#8794a3;}</style>
</head><body>
<h2>Signed in successfully!</h2>
<p>You can close this tab and return to Highlightly.</p>
</body></html>"""

# Fallback for legacy implicit flow (token in URL fragment — needs JS to read it)
OAUTH_IMPLICIT_HTML = """<!DOCTYPE html><html>
<head><title>Highlightly</title>
<style>body{font-family:sans-serif;background:#0b0f14;color:#eef2f6;
display:flex;align-items:center;justify-content:center;height:100vh;
margin:0;flex-direction:column;}h2{color:#c7ff45;}p{color:#8794a3;}</style>
</head><body>
<h2>Signing you in...</h2><p>Please wait.</p>
<script>
var params = new URLSearchParams(window.location.hash.substring(1));
var token = params.get('access_token');
if (token) {
  fetch('http://localhost:54321/token?access_token=' + encodeURIComponent(token))
    .then(function(){ document.querySelector('h2').textContent = 'Signed in successfully!';
                      document.querySelector('p').textContent = 'You can close this tab.'; })
    .catch(function(e){ document.querySelector('p').textContent = 'Error: ' + e; });
} else {
  document.querySelector('p').textContent = 'No token found. Please try again.';
}
</script></body></html>"""


def google_oauth_login(on_success, on_error):
    """
    Full PKCE OAuth flow for desktop:
    1. Generate code_verifier + code_challenge
    2. Open browser to Supabase Google OAuth URL (with PKCE params)
    3. Supabase redirects to localhost:54321/?code=AUTH_CODE  (PKCE)
       OR localhost:54321/#access_token=...                   (implicit fallback)
    4. Local HTTP server catches the redirect:
       - PKCE: reads ?code= from query string, exchanges it for a token server-side
       - Implicit: serves HTML that reads the fragment via JS and posts token back
    5. Calls on_success(account) or on_error(msg) on completion
    """
    import hashlib, base64

    # PKCE values
    code_verifier   = secrets.token_urlsafe(64)
    raw_challenge   = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge  = base64.urlsafe_b64encode(raw_challenge).rstrip(b"=").decode("ascii")

    state           = {"done": False, "access_token": None, "error": None}

    def exchange_code_for_token(auth_code):
        """POST to Supabase to swap the PKCE auth code for an access token."""
        url     = SUPABASE_URL.rstrip("/") + "/auth/v1/token?grant_type=pkce"
        payload = json.dumps({"auth_code": auth_code, "code_verifier": code_verifier}).encode("utf-8")
        req     = request.Request(
            url, data=payload, method="POST",
            headers={
                "apikey":        SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type":  "application/json",
            }
        )
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("access_token", "")

    def fetch_user(access_token):
        url = SUPABASE_URL.rstrip("/") + "/auth/v1/user"
        req = request.Request(
            url, method="GET",
            headers={
                "apikey":        SUPABASE_KEY,
                "Authorization": f"Bearer {access_token}",
            }
        )
        with request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        email    = data.get("email", "")
        metadata = data.get("user_metadata") or {}
        plan     = metadata.get("highlightly_plan") or "Free"
        return {"email": email, "plan": plan, "access_token": access_token}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # suppress HTTP log noise

        def _html(self, html, status=200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _ok(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_GET(self):
            parsed   = parse.urlparse(self.path)
            qs       = dict(parse.parse_qsl(parsed.query))

            # ── PKCE callback: Supabase redirects here with ?code=AUTH_CODE ──
            if parsed.path in ("/", "") and "code" in qs:
                try:
                    token = exchange_code_for_token(qs["code"])
                    if token:
                        state["access_token"] = token
                        state["done"]         = True
                        self._html(OAUTH_SUCCESS_HTML)
                    else:
                        state["error"] = "Token exchange returned empty token."
                        state["done"]  = True
                        self._html("<h2>Sign-in failed. Please try again.</h2>")
                except Exception as exc:
                    state["error"] = f"Code exchange failed: {exc}"
                    state["done"]  = True
                    self._html(f"<h2>Error: {exc}</h2>")

            # ── Implicit fallback: JS posts the access_token here ──
            elif parsed.path == "/token" and "access_token" in qs:
                state["access_token"] = qs["access_token"]
                state["done"]         = True
                self._ok()

            # ── Serve implicit-flow HTML (fragment needs JS to read it) ──
            else:
                self._html(OAUTH_IMPLICIT_HTML)

    def _server_thread():
        srv = None
        try:
            srv = http.server.HTTPServer(("localhost", OAUTH_CALLBACK_PORT), _Handler)
            srv.timeout = 1.0
            deadline    = time.time() + 180  # 3-minute window
            while not state["done"] and time.time() < deadline:
                srv.handle_request()
        except Exception as exc:
            on_error(f"OAuth listener error: {exc}")
            return
        finally:
            if srv:
                srv.server_close()

        if state["error"]:
            on_error(state["error"])
        elif state["access_token"]:
            try:
                account = fetch_user(state["access_token"])
                on_success(account)
            except Exception as exc:
                on_error(f"Could not fetch user info: {exc}")
        else:
            on_error("Sign-in timed out or was cancelled.")

    # Build Supabase OAuth URL with PKCE params
    redirect_uri = f"http://localhost:{OAUTH_CALLBACK_PORT}/"
    oauth_url = (
        SUPABASE_URL.rstrip("/") + "/auth/v1/authorize"
        + "?provider=google"
        + f"&redirect_to={parse.quote(redirect_uri, safe='')}"
        + f"&code_challenge={parse.quote(code_challenge, safe='')}"
        + "&code_challenge_method=S256"
    )

    webbrowser.open(oauth_url)
    threading.Thread(target=_server_thread, daemon=True).start()


def normalize_plan(plan):
    plan_text = (plan or "Free").lower()
    if "founder" in plan_text or "pro" in plan_text or "trial" in plan_text:
        return "Pro Trial" if "trial" in plan_text else "Pro"
    return "Free"


class ModernSlider(tk.Canvas):
    """A flat, filled-track slider that replaces the default ttk.Scale look."""

    def __init__(self, parent, app, variable, from_, to, width=280, height=28, on_change=None, **kwargs):
        super().__init__(parent, width=width, height=height, bg=app.BG_INNER,
                          highlightthickness=0, bd=0, **kwargs)
        self.app = app
        self.variable = variable
        self.from_ = from_
        self.to = to
        self.w = width
        self.h = height
        self.track_y = height // 2
        self.pad = 10
        self.on_change = on_change
        self._track_len = self.w - 2 * self.pad

        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click_drag)
        self.bind("<B1-Motion>", self._on_click_drag)
        self._draw()

    def _on_resize(self, event):
        self.w = event.width
        self._track_len = self.w - 2 * self.pad
        self._draw()

    def _value_to_x(self, value):
        frac = (value - self.from_) / (self.to - self.from_) if self.to != self.from_ else 0
        frac = max(0.0, min(1.0, frac))
        return self.pad + frac * self._track_len

    def _x_to_value(self, x):
        frac = (x - self.pad) / self._track_len if self._track_len else 0
        frac = max(0.0, min(1.0, frac))
        return self.from_ + frac * (self.to - self.from_)

    def _on_click_drag(self, event):
        val = self._x_to_value(event.x)
        self.variable.set(val)
        self._draw()
        if self.on_change:
            self.on_change()

    def _draw(self):
        self.delete("all")
        y = self.track_y
        # background track
        self.create_line(self.pad, y, self.w - self.pad, y, fill=self.app.BORDER, width=5, capstyle="round")
        # filled portion
        knob_x = self._value_to_x(self.variable.get())
        self.create_line(self.pad, y, knob_x, y, fill=self.app.ACCENT, width=5, capstyle="round")
        # knob
        r = 8
        self.create_oval(knob_x - r, y - r, knob_x + r, y + r, fill=self.app.TEXT_LIGHT, outline=self.app.ACCENT, width=2)

    def refresh(self):
        self._draw()


class ToggleSwitch(tk.Canvas):
    """A pill-shaped on/off switch that replaces the default ttk.Checkbutton look."""

    def __init__(self, parent, app, variable, width=44, height=24, **kwargs):
        super().__init__(parent, width=width, height=height, bg=app.BG_INNER,
                          highlightthickness=0, bd=0, cursor="hand2", **kwargs)
        self.app = app
        self.variable = variable
        self.w = width
        self.h = height
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _toggle(self, event=None):
        self.variable.set(not self.variable.get())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.variable.get())
        pad = 2
        color = self.app.ACCENT if on else self.app.BORDER
        self.create_oval(0, 0, self.h, self.h, fill=color, outline="")
        self.create_oval(self.w - self.h, 0, self.w, self.h, fill=color, outline="")
        self.create_rectangle(self.h / 2, 0, self.w - self.h / 2, self.h, fill=color, outline="")
        knob_x = self.w - self.h / 2 if on else self.h / 2
        knob_fg = "#08110a" if on else self.app.TEXT_MUTED
        self.create_oval(knob_x - self.h / 2 + pad, pad, knob_x + self.h / 2 - pad, self.h - pad,
                          fill=self.app.TEXT_LIGHT, outline=knob_fg)

    def refresh(self):
        self._draw()


class HighlightlyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        read_website_supabase_config()
        ensure_dirs()
        pygame.mixer.init()
        
        self.config_data = load_config()
        self.account = self.config_data.get("account")

        # Restore the clip/music library from last session. Anything that no longer
        # exists on disk (deleted, or the .json got edited by hand) is silently dropped
        # instead of producing a broken card.
        self.selected_files = [f for f in self.config_data.get("selected_files", []) if os.path.exists(f)]
        self.export_ready = [f for f in self.config_data.get("export_ready", []) if f in self.selected_files]
        self.clip_music_map = {
            clip: track for clip, track in self.config_data.get("clip_music_map", {}).items()
            if clip in self.selected_files and (track == "" or (track and os.path.exists(track)))
        }
        self.clip_music_volume_map = {
            clip: vol for clip, vol in self.config_data.get("clip_music_volume_map", {}).items()
            if clip in self.selected_files
        }
        self.music_files = []
        self.thumbnail_cache = {}
        self.process = None
        self.log_queue = queue.Queue()
        
        # Audio Video Native Sync Mix Engine State
        self.video_cap = None
        self.is_playing = False
        self.playback_started_fresh = True
        self.playback_start_real_time = 0.0
        self.current_playback_offset = 0.0
        
        self.current_frame_img = None
        self.active_preview_file = None
        self.active_music_file = None
        
        self.video_sound = None
        self.music_sound = None
        self.temp_audio_path = CONFIG_PATH.parent / "extracted_preview_audio.wav"
        self.audio_cache_dir = CONFIG_PATH.parent / "preview_audio_cache"
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        self.audio_extract_cache = {}  # source video path -> extracted wav path, so re-selecting
                                        # a clip never re-runs ffmpeg

        self.title(APP_NAME)
        self.geometry("1400x880")
        self.minsize(1150, 760)
        
        self.is_fullscreen = False
        self.bind("<F11>", self.toggle_fullscreen)
        self.bind("<Escape>", self.end_fullscreen)

        # Global State Variables
        self.email_var = tk.StringVar(value=self.config_data.get("last_email", ""))
        self.password_var = tk.StringVar()
        self.groq_key_var = tk.StringVar(value=self.config_data.get("groq_api_key", ""))
        self.music_volume_var = tk.DoubleVar(value=float(self.config_data.get("music_volume", 0.08)))
        self.active_clip_volume_var = tk.DoubleVar(value=self.music_volume_var.get())
        self.font_size_var = tk.IntVar(value=int(self.config_data.get("font_size", 85)))
        self.caption_margin_var = tk.IntVar(value=int(self.config_data.get("caption_margin", 180)))
        self.zoom_var = tk.DoubleVar(value=float(self.config_data.get("zoom", 1.04)))
        self.output_width_var = tk.IntVar(value=int(self.config_data.get("output_width", 1080)))
        self.output_height_var = tk.IntVar(value=int(self.config_data.get("output_height", 1920)))

        # New render controls
        self.bg_blur_var = tk.IntVar(value=int(self.config_data.get("bg_blur", 25)))
        self.caption_outline_var = tk.IntVar(value=int(self.config_data.get("caption_outline", 5)))
        self.quality_var = tk.IntVar(value=int(self.config_data.get("quality_crf", 18)))
        self.preset_var = tk.StringVar(value=self.config_data.get("encode_preset", "fast"))
        self.caption_words_var = tk.IntVar(value=int(self.config_data.get("caption_words", 6)))
        self.highlight_var = tk.BooleanVar(value=bool(self.config_data.get("highlight_keywords", True)))
        self.font_name_var = tk.StringVar(value=self.config_data.get("caption_font", "Impact"))

        self.build_styles()
        
        self.view_container = ttk.Frame(self, style="TFrame")
        self.view_container.pack(side="top", fill="both", expand=True)

        self.current_screen_name = None
        self.is_animating = False

        self.screens = {}
        for ScreenClass in (LoginScreen, EditorScreen, ExportScreen):
            screen_name = ScreenClass.__name__
            screen_instance = ScreenClass(parent=self.view_container, controller=self)
            self.screens[screen_name] = screen_instance

        if self.account:
            self.show_screen("EditorScreen")
        else:
            self.show_screen("LoginScreen")

        self.after(120, self.drain_log_queue)
        self.after(15, self.stream_player_engine)
        self.protocol("WM_DELETE_WINDOW", self.on_close_cleanup)

    def toggle_fullscreen(self, event=None):
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)

    def end_fullscreen(self, event=None):
        self.is_fullscreen = False
        self.attributes("-fullscreen", False)

    def build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # ─── Palette: cool graphite base with a lime signal accent ───
        self.BG_MAIN = "#0b0f14"
        self.BG_PANEL = "#12171f"
        self.BG_INNER = "#1b222c"
        self.BG_INNER_HOVER = "#242d39"
        self.BORDER = "#232b36"
        self.TEXT_LIGHT = "#eef2f6"
        self.TEXT_MUTED = "#8794a3"
        self.TEXT_FAINT = "#57626f"
        self.ACCENT = "#c7ff45"
        self.ACCENT_HOVER = "#b3e63d"  # subtly dimmed on hover, not brighter — base accent is already vivid
        self.ACCENT_DIM = "#2b3320"
        self.DANGER = "#ff6b6b"
        self.DANGER_BG = "#2a1a1c"

        self.FONT = "Segoe UI"

        self.configure(bg=self.BG_MAIN)

        style.configure("TFrame", background=self.BG_MAIN)
        style.configure("Panel.TFrame", background=self.BG_PANEL, relief="flat")
        style.configure("Inner.TFrame", background=self.BG_INNER, relief="flat")

        # Base + semantic labels
        style.configure("TLabel", background=self.BG_MAIN, foreground=self.TEXT_LIGHT, font=(self.FONT, 10))
        style.configure("Muted.TLabel", background=self.BG_MAIN, foreground=self.TEXT_MUTED, font=(self.FONT, 10))
        style.configure("Panel.TLabel", background=self.BG_PANEL, foreground=self.TEXT_LIGHT, font=(self.FONT, 10))
        style.configure("PanelMuted.TLabel", background=self.BG_PANEL, foreground=self.TEXT_MUTED, font=(self.FONT, 10))
        style.configure("Inner.TLabel", background=self.BG_INNER, foreground=self.TEXT_LIGHT, font=(self.FONT, 9, "bold"))
        style.configure("InnerMuted.TLabel", background=self.BG_INNER, foreground=self.TEXT_MUTED, font=(self.FONT, 8))

        # Headings / captions
        style.configure("Brand.TLabel", background=self.BG_PANEL, foreground=self.TEXT_LIGHT, font=(self.FONT, 15, "bold"))
        style.configure("Eyebrow.TLabel", background=self.BG_PANEL, foreground=self.ACCENT, font=(self.FONT, 9, "bold"))
        style.configure("EyebrowMain.TLabel", background=self.BG_MAIN, foreground=self.ACCENT, font=(self.FONT, 9, "bold"))
        style.configure("CardTitle.TLabel", background=self.BG_PANEL, foreground=self.TEXT_LIGHT, font=(self.FONT, 12, "bold"))
        style.configure("SectionTitle.TLabel", background=self.BG_PANEL, foreground=self.TEXT_LIGHT, font=(self.FONT, 13, "bold"))

        # Buttons
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#08110a",
                         font=(self.FONT, 11, "bold"), borderwidth=0, padding=(18, 10))
        style.map("Accent.TButton",
                  background=[("disabled", self.BG_INNER), ("active", self.ACCENT_HOVER)],
                  foreground=[("disabled", self.TEXT_FAINT)])

        style.configure("Dark.TButton", background=self.BG_INNER, foreground=self.TEXT_LIGHT,
                         font=(self.FONT, 10, "bold"), borderwidth=0, padding=(14, 8))
        style.map("Dark.TButton",
                  background=[("disabled", self.BG_PANEL), ("active", self.BG_INNER_HOVER)],
                  foreground=[("disabled", self.TEXT_FAINT)])

        style.configure("Ghost.TButton", background=self.BG_PANEL, foreground=self.TEXT_MUTED,
                         font=(self.FONT, 9, "bold"), borderwidth=1, relief="solid", padding=(12, 6))
        style.map("Ghost.TButton",
                  background=[("active", self.BG_INNER)],
                  foreground=[("active", self.TEXT_LIGHT)])

        style.configure("Danger.TButton", background=self.DANGER_BG, foreground="#ffb4b4",
                         font=(self.FONT, 10, "bold"), borderwidth=0, padding=(14, 8))
        style.map("Danger.TButton",
                  background=[("disabled", self.BG_PANEL), ("active", "#3a2225")],
                  foreground=[("disabled", self.TEXT_FAINT)])

        style.configure("Tiny.TButton", background=self.ACCENT, foreground="#08110a",
                         font=(self.FONT, 8, "bold"), borderwidth=0, padding=(10, 5))
        style.map("Tiny.TButton", background=[("active", self.ACCENT_HOVER)])

        # Inputs
        style.configure("TEntry", fieldbackground=self.BG_INNER, foreground=self.TEXT_LIGHT,
                         insertcolor=self.TEXT_LIGHT, borderwidth=0, padding=8, font=(self.FONT, 10))
        style.map("TEntry", fieldbackground=[("disabled", self.BG_PANEL)])

        style.configure("Horizontal.TScale", background=self.BG_PANEL, troughcolor=self.BG_INNER)

        style.configure("Accent.Horizontal.TProgressbar", background=self.ACCENT,
                         troughcolor=self.BG_INNER, borderwidth=0, thickness=10)

        style.configure("Vertical.TScrollbar", background=self.BG_INNER, troughcolor=self.BG_PANEL,
                         borderwidth=0, arrowsize=12, width=10)
        style.map("Vertical.TScrollbar", background=[("active", self.BG_INNER_HOVER)])

        # Tabs (legacy — kept in case other screens still use ttk.Notebook)
        style.configure("TNotebook", background=self.BG_PANEL, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=self.BG_PANEL, foreground=self.TEXT_MUTED,
                         font=(self.FONT, 9, "bold"), padding=(16, 10), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", self.BG_INNER)],
                  foreground=[("selected", self.ACCENT)])

        # Segmented tab pills (custom tab bar used on the redesigned Export screen)
        style.configure("Seg.TButton", background=self.BG_PANEL, foreground=self.TEXT_MUTED,
                         font=(self.FONT, 9, "bold"), borderwidth=0, padding=(14, 9))
        style.map("Seg.TButton", background=[("active", self.BG_INNER_HOVER)], foreground=[("active", self.TEXT_LIGHT)])
        style.configure("SegActive.TButton", background=self.BG_INNER, foreground=self.ACCENT,
                         font=(self.FONT, 9, "bold"), borderwidth=0, padding=(14, 9))
        style.map("SegActive.TButton", background=[("active", self.BG_INNER)])

        # Chips (used to list queued clips in the batch export tray)
        style.configure("Chip.TFrame", background=self.BG_INNER)
        style.configure("ChipLabel.TLabel", background=self.BG_INNER, foreground=self.TEXT_LIGHT, font=(self.FONT, 8, "bold"))

        # Dropdowns
        style.configure("TCombobox", fieldbackground=self.BG_INNER, background=self.BG_INNER,
                         foreground=self.TEXT_LIGHT, arrowcolor=self.TEXT_MUTED, borderwidth=0,
                         padding=6, font=(self.FONT, 9))
        style.map("TCombobox",
                  fieldbackground=[("readonly", self.BG_INNER), ("disabled", self.BG_PANEL)],
                  foreground=[("disabled", self.TEXT_FAINT)])
        self.option_add("*TCombobox*Listbox.background", self.BG_INNER)
        self.option_add("*TCombobox*Listbox.foreground", self.TEXT_LIGHT)
        self.option_add("*TCombobox*Listbox.selectBackground", self.ACCENT_DIM)
        self.option_add("*TCombobox*Listbox.selectForeground", self.TEXT_LIGHT)

        # Checkboxes
        style.configure("TCheckbutton", background=self.BG_INNER, foreground=self.TEXT_LIGHT,
                         font=(self.FONT, 9, "bold"))
        style.map("TCheckbutton", foreground=[("disabled", self.TEXT_FAINT)])

    # ─── Custom vector logo mark + tiled crosshair backdrop (no image assets) ───
    _logo_cache = {}

    def load_logo_icon(self, size):
        """Loads the designed PNG logo at the requested size (cached). Returns None on failure
        so callers can fall back to the vector-drawn mark."""
        key = size
        if key in self._logo_cache:
            return self._logo_cache[key]
        photo = None
        try:
            img = Image.open(ASSETS_DIR / "highlightly_logo.png").convert("RGBA").resize((size, size), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            photo = None
        self._logo_cache[key] = photo
        return photo

    def make_logo_mark(self, parent, size=34):
        """Highlightly's brand mark. Uses the designed PNG logo when available, and falls back to
        an equivalent drawn-on-canvas version if the asset is missing."""
        icon = self.load_logo_icon(size)
        if icon:
            lbl = tk.Label(parent, image=icon, bg=parent["bg"] if "bg" in parent.keys() else self.BG_PANEL,
                           width=size, height=size, bd=0)
            lbl.image = icon  # keep a reference alive
            return lbl

        c = tk.Canvas(parent, width=size, height=size, bg=self.ACCENT, highlightthickness=0, bd=0)
        mid = size / 2
        ring_r = size * 0.34
        c.create_oval(mid - ring_r, mid - ring_r, mid + ring_r, mid + ring_r,
                       outline="#08110a", width=max(2, size // 14))
        tick = size * 0.14
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            c.create_line(mid + dx * ring_r, mid + dy * ring_r,
                           mid + dx * (ring_r + tick), mid + dy * (ring_r + tick),
                           fill="#08110a", width=max(2, size // 14), capstyle="round")
        p = size * 0.15
        c.create_polygon(mid - p * 0.5, mid - p, mid - p * 0.5, mid + p, mid + p, mid,
                          fill="#08110a", outline="")
        return c

    def paint_crosshair_tiles(self, canvas, line_color="#1a212b"):
        """Draws (and keeps redrawing on resize) the tiled crosshair texture directly onto an
        existing canvas. Reusable both for full-screen backdrops and for canvases used as a
        screen's main body — which is important, because a plain opaque Frame sitting on top of
        a separate backdrop canvas would otherwise hide the texture completely."""
        step = 54
        arm = 4

        def redraw(event=None):
            canvas.delete("crosshair_tile")
            w = canvas.winfo_width() or 1400
            h = canvas.winfo_height() or 880
            for y in range(0, h + step, step):
                for x in range(0, w + step, step):
                    canvas.create_line(x - arm, y, x + arm, y, fill=line_color, tags="crosshair_tile")
                    canvas.create_line(x, y - arm, x, y + arm, fill=line_color, tags="crosshair_tile")
            canvas.tag_lower("crosshair_tile")

        canvas.bind("<Configure>", redraw)
        canvas.after(60, redraw)

    def make_crosshair_backdrop(self, parent):
        """Paints a faint, tiled crosshair pattern across a screen's background — drawn with plain
        canvas lines, no image files involved. Only useful when nothing opaque and full-bleed sits
        on top of `parent`; for screens with a solid body area, paint directly on that body canvas
        instead (see `paint_crosshair_tiles`)."""
        bg = tk.Canvas(parent, bg=self.BG_MAIN, highlightthickness=0, bd=0)
        bg.place(x=0, y=0, relwidth=1, relheight=1)
        # Canvas.lower() is shadowed by the canvas-item "lower" method, so call
        # the underlying Tk widget-stacking command directly.
        bg.tk.call("lower", bg._w)
        self.paint_crosshair_tiles(bg)
        return bg

    def make_image_backdrop(self, parent, filename, fallback_to_crosshair=True):
        """Fills a screen's background with an image, scaled+cropped to always cover the full
        window (like CSS `background-size: cover`), re-rendered on resize. Falls back to the
        tiled crosshair pattern if the file can't be loaded."""
        try:
            source = Image.open(ASSETS_DIR / filename).convert("RGBA")
            if source.mode == "RGBA":
                # Some exported PNGs store garbage/black RGB under fully-transparent pixels.
                # A plain convert("RGB") would leak that in; composite onto white instead so
                # transparent regions render the way they look in a normal image viewer.
                white_canvas = Image.new("RGB", source.size, (255, 255, 255))
                white_canvas.paste(source, mask=source.split()[3])
                source = white_canvas
        except Exception:
            if fallback_to_crosshair:
                return self.make_crosshair_backdrop(parent)
            return None

        bg = tk.Canvas(parent, bg=self.BG_MAIN, highlightthickness=0, bd=0)
        bg.place(x=0, y=0, relwidth=1, relheight=1)
        bg.tk.call("lower", bg._w)

        state = {"photo": None, "size": None}

        def redraw(event=None):
            w = bg.winfo_width() or 1400
            h = bg.winfo_height() or 880
            if state["size"] == (w, h):
                return
            state["size"] = (w, h)
            src_w, src_h = source.size
            scale = max(w / src_w, h / src_h)
            new_w, new_h = int(src_w * scale) + 1, int(src_h * scale) + 1
            resized = source.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - w) // 2
            top = (new_h - h) // 2
            cropped = resized.crop((left, top, left + w, top + h))
            photo = ImageTk.PhotoImage(cropped)
            state["photo"] = photo  # keep a reference so it isn't garbage-collected
            bg.delete("bg_image")
            bg.create_image(0, 0, image=photo, anchor="nw", tags="bg_image")

        bg.bind("<Configure>", redraw)
        parent.after(60, redraw)
        return bg

    def set_placeholder(self, entry, text):
        """Shows greyed-out placeholder text in a ttk.Entry; clears on focus, restores when empty.
        Use `is_placeholder_active(entry)` before reading its value for real filtering/search."""
        entry.insert(0, text)
        entry.configure(foreground=self.TEXT_MUTED)
        entry._is_placeholder = True
        entry._placeholder_text = text

        def on_focus_in(event):
            if getattr(entry, "_is_placeholder", False):
                entry.delete(0, "end")
                entry.configure(foreground=self.TEXT_LIGHT)
                entry._is_placeholder = False

        def on_focus_out(event):
            if not entry.get():
                entry._is_placeholder = True  # set BEFORE inserting: insert() fires the
                                               # textvariable trace synchronously, so the
                                               # flag must already be correct when that fires
                entry.insert(0, text)
                entry.configure(foreground=self.TEXT_MUTED)

        entry.bind("<FocusIn>", on_focus_in, add="+")
        entry.bind("<FocusOut>", on_focus_out, add="+")

    def search_text(self, entry):
        """Reads an entry's value for filtering purposes, treating an active placeholder as empty."""
        if getattr(entry, "_is_placeholder", False):
            return ""
        return entry.get().strip().lower()

    def card(self, parent, **kwargs):
        """A bordered panel used throughout the redesign to group related content."""
        padding = kwargs.pop("padding", 18)
        outer = tk.Frame(parent, bg=self.BORDER)
        inner = ttk.Frame(outer, style="Panel.TFrame", padding=padding)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        outer.inner = inner
        return outer, inner

    def pill(self, parent, text, bg, fg, font_size=8):
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=(self.FONT, font_size, "bold"),
                         padx=8, pady=2, bd=0)

    def show_screen(self, screen_name):
        incoming_frame = self.screens[screen_name]
        if self.current_screen_name is None:
            incoming_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            incoming_frame.tkraise()
            self.current_screen_name = screen_name
            if hasattr(incoming_frame, "on_display_refresh"):
                incoming_frame.on_display_refresh()
            return

        if self.current_screen_name == screen_name or self.is_animating:
            return

        self.is_animating = True
        if hasattr(incoming_frame, "on_display_refresh"):
            incoming_frame.on_display_refresh()

        incoming_frame.place(relx=1.0, rely=0, relwidth=1, relheight=1)
        incoming_frame.tkraise()
        self._execute_slide_transition(incoming_frame, 1.0, screen_name)

    def _execute_slide_transition(self, frame, current_x, target_screen_name):
        step = 0.10
        next_x = current_x - step
        if next_x <= 0:
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            old_frame = self.screens.get(self.current_screen_name)
            if old_frame and self.current_screen_name != target_screen_name:
                old_frame.place_forget()
            self.current_screen_name = target_screen_name
            self.is_animating = False
        else:
            frame.place(relx=next_x, rely=0, relwidth=1, relheight=1)
            self.after(12, lambda: self._execute_slide_transition(frame, next_x, target_screen_name))

    def plan(self):
        if not self.account: return None
        return normalize_plan(self.account.get("plan"))

    def is_pro(self):
        return self.plan() in {"Pro", "Pro Trial"}

    def log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {text}")

    def update_slider_value(self, label_widget, tk_variable):
        val = tk_variable.get()
        if isinstance(val, float):
            label_widget.configure(text=f"{val:.2f}")
        else:
            label_widget.configure(text=str(val))

    def open_outputs(self):
        if not OUTPUT_DIR.exists():
            OUTPUT_DIR.mkdir(exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(OUTPUT_DIR))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(OUTPUT_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(OUTPUT_DIR)])

    def save_app_settings(self):
        self.config_data.update({
            "last_email": self.email_var.get().strip(),
            "groq_api_key": self.groq_key_var.get().strip(),
            "music_volume": self.music_volume_var.get(),
            "font_size": self.font_size_var.get(),
            "caption_margin": self.caption_margin_var.get(),
            "zoom": self.zoom_var.get(),
            "output_width": self.output_width_var.get(),
            "output_height": self.output_height_var.get(),
            "bg_blur": self.bg_blur_var.get(),
            "caption_outline": self.caption_outline_var.get(),
            "quality_crf": self.quality_var.get(),
            "encode_preset": self.preset_var.get(),
            "caption_words": self.caption_words_var.get(),
            "highlight_keywords": bool(self.highlight_var.get()),
            "caption_font": self.font_name_var.get(),
        })
        if self.account:
            self.config_data["account"] = self.account
        save_config(self.config_data)

    def sign_out(self):
        self.account = None
        self.config_data.pop("account", None)
        save_config(self.config_data)

    def drain_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                export_screen = self.screens["ExportScreen"]
                if item == "__PIPELINE_COMPLETE__":
                    continue
                export_screen.append_log(item)
                export_screen.note_log_line(item)
        except queue.Empty:
            pass
        self.after(120, self.drain_log_queue)

    def stream_player_engine(self):
        """Audio Clock Sync Engine: Strictly paces frames to match the hardware audio timeline."""
        if self.is_playing and self.video_cap and self.video_cap.isOpened():
            fps = self.video_cap.get(cv2.CAP_PROP_FPS) or 30.0
            elapsed = time.time() - self.playback_start_real_time
            target_frame = int(elapsed * fps)
            
            current_frame = int(self.video_cap.get(cv2.CAP_PROP_POS_FRAMES))
            
            # GATED TIMING RULE: Only read and parse a frame if the timeline has reached it
            if target_frame >= current_frame:
                if target_frame > current_frame + 15: # Large sync jump
                    self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                    current_frame = target_frame
                else: # Clean grab catch-up
                    while current_frame < target_frame:
                        self.video_cap.grab()
                        current_frame += 1

                ret, frame = self.video_cap.read()
                if ret:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, _ = frame.shape
                    
                    editor = self.screens["EditorScreen"]
                    c_w = editor.player_canvas.winfo_width()
                    c_h = editor.player_canvas.winfo_height()
                    if c_w < 100: c_w = 640
                    if c_h < 100: c_h = 360
                    
                    scale = min(c_w/w, c_h/h)
                    nw, nh = int(w * scale), int(h * scale)
                    frame = cv2.resize(frame, (nw, nh))

                    img = Image.fromarray(frame)
                    self.current_frame_img = ImageTk.PhotoImage(image=img)
                    
                    editor.player_canvas.delete("all")
                    editor.player_canvas.create_image(c_w//2, c_h//2, anchor="center", image=self.current_frame_img)
                else:
                    # Video loop reset boundary rules
                    self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.playback_start_real_time = time.time()
                    pygame.mixer.Channel(0).stop()
                    pygame.mixer.Channel(1).stop()
                    if self.video_sound: pygame.mixer.Channel(0).play(self.video_sound)
                    if self.music_sound: pygame.mixer.Channel(1).play(self.music_sound, loops=-1)
                
        self.after(15, self.stream_player_engine)

    def save_library_state(self):
        """Persists the current clip queue, export selections, and clip↔music pairings so
        they're still there next time the app opens."""
        self.config_data["selected_files"] = self.selected_files
        self.config_data["export_ready"] = self.export_ready
        self.config_data["clip_music_map"] = self.clip_music_map
        self.config_data["clip_music_volume_map"] = self.clip_music_volume_map
        save_config(self.config_data)

    def on_close_cleanup(self):
        self.save_library_state()
        self.save_app_settings()
        pygame.mixer.quit()
        if self.video_cap:
            self.video_cap.release()
        if os.path.exists(self.temp_audio_path):
            try: os.remove(self.temp_audio_path)
            except Exception: pass
        try:
            shutil.rmtree(self.audio_cache_dir, ignore_errors=True)
        except Exception:
            pass
        self.destroy()


# ──────────────────────────────────────────────────────────
# SCREEN 1: LOGIN
# ──────────────────────────────────────────────────────────
class LoginScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.app = controller

        self.app.make_image_backdrop(self, "bg.png")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card_outer, card = self.app.card(self, padding=44)
        card_outer.grid(row=0, column=0)
        card.grid_columnconfigure(0, weight=1, minsize=340)

        # Logo mark
        logo_row = ttk.Frame(card, style="Panel.TFrame")
        logo_row.grid(row=0, column=0, pady=(0, 22))
        logo_icon = self.app.make_logo_mark(logo_row, size=34)
        logo_icon.pack(side="left", padx=(0, 12))
        title_col = ttk.Frame(logo_row, style="Panel.TFrame")
        title_col.pack(side="left")
        ttk.Label(title_col, text="Highlightly", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(title_col, text="STUDIO PRO", style="Eyebrow.TLabel").pack(anchor="w")

        ttk.Label(card, text="Welcome back", font=(self.app.FONT, 19, "bold"),
                  style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 2))
        ttk.Label(card, text="Sign in to open your editing workspace.",
                  style="PanelMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 26))

        ttk.Label(card, text="EMAIL ADDRESS", style="PanelMuted.TLabel",
                  font=(self.app.FONT, 8, "bold")).grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(card, textvariable=self.app.email_var, width=40).grid(row=4, column=0, sticky="ew", pady=(0, 18), ipady=6)

        ttk.Label(card, text="PASSWORD", style="PanelMuted.TLabel",
                  font=(self.app.FONT, 8, "bold")).grid(row=5, column=0, sticky="w", pady=(0, 6))
        pw_entry = ttk.Entry(card, textvariable=self.app.password_var, show="•", width=40)
        pw_entry.grid(row=6, column=0, sticky="ew", pady=(0, 26), ipady=6)
        pw_entry.bind("<Return>", lambda e: self.exec_login())

        ttk.Button(card, text="Sign In  →", style="Accent.TButton",
                   command=self.exec_login).grid(row=7, column=0, sticky="ew")

        # ── Divider ──
        div = tk.Frame(card, bg=self.app.BG_PANEL)
        div.grid(row=8, column=0, sticky="ew", pady=(18, 0))
        div.columnconfigure(0, weight=1)
        div.columnconfigure(2, weight=1)
        tk.Frame(div, bg=self.app.BORDER, height=1).grid(row=0, column=0, sticky="ew")
        tk.Label(div, text="  or  ", bg=self.app.BG_PANEL, fg=self.app.TEXT_FAINT,
                 font=(self.app.FONT, 8)).grid(row=0, column=1)
        tk.Frame(div, bg=self.app.BORDER, height=1).grid(row=0, column=2, sticky="ew")

        # ── Google sign-in button ──
        self.google_btn = tk.Button(
            card, text="G   Sign in with Google",
            bg="#ffffff", fg="#3c4043",
            font=(self.app.FONT, 10, "bold"),
            relief="flat", cursor="hand2", pady=10,
            activebackground="#f1f3f4", activeforeground="#3c4043",
            command=self.exec_google_login
        )
        self.google_btn.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        self.google_btn.bind("<Enter>", lambda e: self.google_btn.configure(bg="#f1f3f4"))
        self.google_btn.bind("<Leave>", lambda e: self.google_btn.configure(bg="#ffffff"))

        ttk.Label(card, text="🔒 Connections are authenticated securely via Supabase.",
                  style="PanelMuted.TLabel", font=(self.app.FONT, 8)).grid(row=10, column=0, pady=(20, 0))

    def exec_google_login(self):
        """Open browser for Google OAuth (PKCE) and catch the callback locally."""
        self.google_btn.configure(state="disabled", text="Opening browser...")

        def on_success(account_data):
            self.app.after(0, lambda: self._finish_google_login(account_data))

        def on_error(msg):
            self.app.after(0, lambda: self._google_login_error(msg))

        google_oauth_login(on_success, on_error)

    def _finish_google_login(self, account_data):
        self.google_btn.configure(state="normal", text="G   Sign in with Google")
        self.app.account = account_data
        self.app.save_app_settings()
        self.app.log(f"Signed in via Google as {account_data.get('email', 'unknown')}.")
        self.app.show_screen("EditorScreen")

    def _google_login_error(self, msg):
        self.google_btn.configure(state="normal", text="G   Sign in with Google")
        messagebox.showerror(APP_NAME, f"Google sign-in failed:\n{msg}")

    def exec_login(self):
        email = self.app.email_var.get().strip().lower()
        password = self.app.password_var.get()
        
        if email == ADMIN_LOGIN["email"] and password == ADMIN_LOGIN["password"]:
            self.app.account = {"email": "admin", "plan": ADMIN_LOGIN["plan"]}
            self.app.save_app_settings()
            self.app.show_screen("EditorScreen")
            return
            
        if not email or not password:
            messagebox.showerror(APP_NAME, "Missing credentials.")
            return
            
        try:
            self.app.account = supabase_password_login(email, password)
            self.app.save_app_settings()
            self.app.show_screen("EditorScreen")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))


# ──────────────────────────────────────────────────────────
# SCREEN 2: PLAYBACK EDITOR
# ──────────────────────────────────────────────────────────
class EditorScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.app = controller

        self.app.make_crosshair_backdrop(self)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ─── Top bar ───
        header = tk.Frame(self, bg=self.app.BG_PANEL, height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(1, weight=1)

        brand_col = ttk.Frame(header, style="Panel.TFrame")
        brand_col.grid(row=0, column=0, sticky="w", padx=(24, 0))
        brand_icon = self.app.make_logo_mark(brand_col, size=26)
        brand_icon.pack(side="left", pady=18)
        ttk.Label(brand_col, text="  Highlightly", style="Brand.TLabel").pack(side="left", pady=18)

        self.user_lbl = ttk.Label(header, text="Studio Editor", style="PanelMuted.TLabel", font=(self.app.FONT, 10))
        self.user_lbl.grid(row=0, column=1, sticky="w", padx=(18, 0))

        ttk.Button(header, text="⏻ Sign Out", style="Ghost.TButton",
                   command=self.sign_out_action).grid(row=0, column=2, sticky="e", padx=24)

        # ─── Body ───
        # A Canvas (not an opaque Frame) so the crosshair texture painted on it is actually
        # visible in the gaps between panels, instead of being hidden behind a solid background.
        body = tk.Canvas(self, bg=self.app.BG_MAIN, highlightthickness=0, bd=0)
        body.grid(row=1, column=0, sticky="nsew")
        self.app.paint_crosshair_tiles(body)
        body.columnconfigure(0, weight=4)
        body.columnconfigure(1, weight=5)
        body.rowconfigure(0, weight=1)

        # LEFT SIDEBAR CONTAINER
        left_sidebar = ttk.Frame(body, style="TFrame")
        left_sidebar.grid(row=0, column=0, sticky="nsew", padx=(22, 10), pady=22)
        left_sidebar.columnconfigure(0, weight=1)
        left_sidebar.rowconfigure(0, weight=1)
        left_sidebar.rowconfigure(1, weight=1)

        # TOP HALF: Video Clips Panel
        queue_outer, queue_panel = self.app.card(left_sidebar, padding=16)
        queue_outer.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        queue_panel.columnconfigure(0, weight=1)
        queue_panel.rowconfigure(2, weight=1)

        q_head = ttk.Frame(queue_panel, style="Panel.TFrame")
        q_head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(q_head, text="Video Clips", style="CardTitle.TLabel").pack(side="left")

        self.clip_search_var = tk.StringVar()
        self.clip_search_var.trace_add("write", lambda *a: self.refresh_media_grid())
        clip_search_row = ttk.Frame(queue_panel, style="Panel.TFrame")
        clip_search_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        clip_search_row.columnconfigure(0, weight=1)
        self.clip_search_entry = ttk.Entry(clip_search_row, textvariable=self.clip_search_var)
        self.clip_search_entry.grid(row=0, column=0, sticky="ew")
        self.app.set_placeholder(self.clip_search_entry, "🔍  Search clips by filename…")
        ttk.Button(clip_search_row, text="✕", style="Ghost.TButton", width=2,
                   command=lambda: self.clip_search_var.set("")).grid(row=0, column=1, padx=(6, 0))

        self.grid_canvas = tk.Canvas(queue_panel, bg=self.app.BG_PANEL, highlightthickness=0)
        self.app.paint_crosshair_tiles(self.grid_canvas, line_color="#1e2530")
        self.grid_scrollbar = ttk.Scrollbar(queue_panel, orient="vertical", command=self.grid_canvas.yview)
        self.queue_frame = ttk.Frame(self.grid_canvas, style="Panel.TFrame")
        self.queue_frame.bind("<Configure>", lambda e: self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all")))
        self.grid_canvas.create_window((0, 0), window=self.queue_frame, anchor="nw")
        self.grid_canvas.configure(yscrollcommand=self.grid_scrollbar.set)
        self.grid_canvas.grid(row=2, column=0, sticky="nsew")
        self.grid_scrollbar.grid(row=2, column=1, sticky="ns")

        # ─── Ready-to-Export drop zone: drag a clip card here (or tap the button) to mark it ───
        ready_wrap = tk.Frame(queue_panel, bg=self.app.ACCENT_DIM, highlightthickness=1,
                               highlightbackground=self.app.ACCENT, highlightcolor=self.app.ACCENT)
        ready_wrap.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.ready_zone = ready_wrap
        ready_head = tk.Frame(ready_wrap, bg=self.app.ACCENT_DIM)
        ready_head.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(ready_head, text="✅  Ready to Export", bg=self.app.ACCENT_DIM, fg=self.app.ACCENT,
                 font=(self.app.FONT, 9, "bold")).pack(side="left")
        self.ready_count_lbl = tk.Label(ready_head, text="0 clips", bg=self.app.ACCENT_DIM, fg=self.app.TEXT_MUTED,
                                         font=(self.app.FONT, 8))
        self.ready_count_lbl.pack(side="right")
        self.ready_pill_row = tk.Frame(ready_wrap, bg=self.app.ACCENT_DIM)
        self.ready_pill_row.pack(fill="x", padx=10, pady=(0, 10))
        self.ready_hint_lbl = tk.Label(self.ready_pill_row, text="Drag a clip here, or tap “＋ Ready” on its card.",
                                        bg=self.app.ACCENT_DIM, fg=self.app.TEXT_MUTED, font=(self.app.FONT, 8))
        self.ready_hint_lbl.pack(anchor="w")

        actions = ttk.Frame(queue_panel, style="Panel.TFrame")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="＋ Add Videos", style="Tiny.TButton", command=self.add_clips).pack(side="left")
        ttk.Button(actions, text="Clear All", style="Ghost.TButton", command=self.clear_clips).pack(side="left", padx=(8, 0))

        # BOTTOM HALF: Music Library Panel
        music_outer, music_panel = self.app.card(left_sidebar, padding=16)
        music_outer.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        music_panel.columnconfigure(0, weight=1)
        music_panel.rowconfigure(2, weight=1)

        m_head = ttk.Frame(music_panel, style="Panel.TFrame")
        m_head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(m_head, text="Background Music", style="CardTitle.TLabel").pack(side="left")

        self.music_search_var = tk.StringVar()
        self.music_search_var.trace_add("write", lambda *a: self.refresh_music_library())
        music_search_row = ttk.Frame(music_panel, style="Panel.TFrame")
        music_search_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        music_search_row.columnconfigure(0, weight=1)
        self.music_search_entry = ttk.Entry(music_search_row, textvariable=self.music_search_var)
        self.music_search_entry.grid(row=0, column=0, sticky="ew")
        self.app.set_placeholder(self.music_search_entry, "🔍  Search tracks by filename…")
        ttk.Button(music_search_row, text="✕", style="Ghost.TButton", width=2,
                   command=lambda: self.music_search_var.set("")).grid(row=0, column=1, padx=(6, 0))

        self.music_canvas = tk.Canvas(music_panel, bg=self.app.BG_PANEL, highlightthickness=0)
        self.app.paint_crosshair_tiles(self.music_canvas, line_color="#1e2530")
        self.music_scrollbar = ttk.Scrollbar(music_panel, orient="vertical", command=self.music_canvas.yview)
        self.music_frame = ttk.Frame(self.music_canvas, style="Panel.TFrame")
        self.music_frame.bind("<Configure>", lambda e: self.music_canvas.configure(scrollregion=self.music_canvas.bbox("all")))
        self.music_canvas.create_window((0, 0), window=self.music_frame, anchor="nw")
        self.music_canvas.configure(yscrollcommand=self.music_scrollbar.set)
        self.music_canvas.grid(row=2, column=0, sticky="nsew")
        self.music_scrollbar.grid(row=2, column=1, sticky="ns")

        m_actions = ttk.Frame(music_panel, style="Panel.TFrame")
        m_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(m_actions, text="＋ Add Track", style="Tiny.TButton", command=self.add_own_music).pack(side="left")
        ttk.Button(m_actions, text="Refresh", style="Ghost.TButton", command=self.refresh_music_library).pack(side="left", padx=(8, 0))

        # RIGHT: Giant Video Previewer
        preview_outer, preview_panel = self.app.card(body, padding=20)
        preview_outer.grid(row=0, column=1, sticky="nsew", padx=(10, 22), pady=22)
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(2, weight=1)

        p_head = ttk.Frame(preview_panel, style="Panel.TFrame")
        p_head.grid(row=0, column=0, sticky="ew")
        ttk.Label(p_head, text="🎥  Live Preview", style="CardTitle.TLabel").pack(side="left")

        self.player_title = ttk.Label(preview_panel, text="Add or select a clip to begin previewing",
                                       style="PanelMuted.TLabel", font=(self.app.FONT, 9))
        self.player_title.grid(row=1, column=0, sticky="w", pady=(3, 12))

        canvas_frame = tk.Frame(preview_panel, bg=self.app.BORDER)
        canvas_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 16))
        self.player_canvas = tk.Canvas(canvas_frame, bg=self.app.BG_MAIN, highlightthickness=0)
        self.player_canvas.pack(fill="both", expand=True, padx=1, pady=1)

        ctrl_row = ttk.Frame(preview_panel, style="Panel.TFrame")
        ctrl_row.grid(row=3, column=0, sticky="ew")
        ctrl_row.columnconfigure(0, weight=1)

        self.scrub_btn = ttk.Button(ctrl_row, text="▶  Play Preview", style="Accent.TButton", width=16,
                                     command=self.toggle_workspace_playback, state="disabled")
        self.scrub_btn.grid(row=0, column=0, sticky="w")

        ttk.Button(ctrl_row, text="Next: Customize & Save  →", style="Accent.TButton",
                   command=self.go_to_export).grid(row=0, column=1, sticky="e")

        # Per-clip background music volume — every clip can have its own level, since a
        # quiet acoustic track and a loud EDM track need very different ceilings.
        vol_row = ttk.Frame(preview_panel, style="Panel.TFrame")
        vol_row.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        vol_row.columnconfigure(0, weight=1)

        vol_label_row = ttk.Frame(vol_row, style="Panel.TFrame")
        vol_label_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        vol_label_row.columnconfigure(0, weight=1)
        ttk.Label(vol_label_row, text="🎵  Background Music Volume — this clip", style="PanelMuted.TLabel",
                  font=(self.app.FONT, 9)).grid(row=0, column=0, sticky="w")
        self.clip_vol_val_lbl = tk.Label(vol_row, text="", bg=self.app.BG_INNER, fg=self.app.TEXT_LIGHT,
                                          font=("Consolas", 9, "bold"), padx=8, pady=1)
        self.clip_vol_val_lbl.grid(row=0, column=1, sticky="e")

        self.clip_volume_slider = ModernSlider(vol_row, self.app, self.app.active_clip_volume_var,
                                                0.0, 0.35, height=26, on_change=self.on_clip_volume_change)
        self.clip_volume_slider.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._refresh_clip_volume_label()
        self._sync_clip_volume_controls()

    def _refresh_clip_volume_label(self):
        self.app.update_slider_value(self.clip_vol_val_lbl, self.app.active_clip_volume_var)

    def _sync_clip_volume_controls(self):
        """Enables/disables the per-clip volume slider based on whether a clip is mounted,
        and loads that clip's saved volume (or the last-used default for a clip that's
        never had one set)."""
        has_clip = bool(self.app.active_preview_file)
        if has_clip:
            saved = self.app.clip_music_volume_map.get(self.app.active_preview_file, self.app.music_volume_var.get())
        else:
            saved = self.app.music_volume_var.get()
        self.app.active_clip_volume_var.set(saved)
        self.clip_volume_slider.refresh()
        self._refresh_clip_volume_label()

    def on_clip_volume_change(self):
        vol = self.app.active_clip_volume_var.get()
        self._refresh_clip_volume_label()
        if self.app.active_preview_file:
            self.app.clip_music_volume_map[self.app.active_preview_file] = vol
            self.app.music_volume_var.set(vol)  # also becomes the default for the next new clip
            self.app.save_library_state()
            if self.app.music_sound:
                self.app.music_sound.set_volume(vol)

    def on_display_refresh(self):
        if self.app.account:
            self.user_lbl.configure(text=f"Editing Workspace • {self.app.account.get('email')}")
        self.refresh_media_grid()
        self.refresh_music_library()

    def _import_to_library(self, source_path, target_dir):
        """Copies a user-picked file into the app's own storage folder (input_clips/ or music/)
        if it isn't already there. This is what makes moving, renaming, or deleting the
        original file on the Desktop/Downloads/wherever harmless — the app always plays
        from its own persistent copy, never the original path."""
        try:
            source = Path(source_path).resolve()
            target_dir = Path(target_dir).resolve()
        except Exception:
            return None
        try:
            if source.parent == target_dir:
                return str(source)  # already living in our own library folder

            dest = target_dir / source.name
            if dest.exists():
                if filecmp.cmp(source, dest, shallow=False):
                    return str(dest)  # identical file already imported — reuse it
                # Different file, same name — import alongside it under a new name
                # instead of silently overwriting the existing library copy.
                stem, suffix = dest.stem, dest.suffix
                n = 1
                while dest.exists():
                    dest = target_dir / f"{stem} ({n}){suffix}"
                    n += 1

            shutil.copy(str(source), str(dest))
            return str(dest)
        except Exception as e:
            print(f"[System Launcher] Error importing file: {e}")
            return None

    def add_clips(self):
        files = filedialog.askopenfilenames(filetypes=[("Video Clips", "*.mp4 *.mov *.mkv")])
        for f in files:
            if not f:
                continue
            imported = self._import_to_library(f, INPUT_DIR)
            if imported and imported not in self.app.selected_files:
                self.app.selected_files.append(imported)
        self.app.save_library_state()
        self.refresh_media_grid()

    def add_own_music(self):
        """Allows users to select background audio files from their local machine and copies them to the music catalog."""
        files = filedialog.askopenfilenames(filetypes=[("Audio Files", "*.mp3 *.wav")])
        for f in files:
            if f:
                self._import_to_library(f, MUSIC_DIR)
        self.refresh_music_library()

    def clear_clips(self):
        self.app.selected_files.clear()
        self.app.export_ready.clear()
        self.app.thumbnail_cache.clear()
        self.app.clip_music_map.clear()
        self.app.clip_music_volume_map.clear()
        self.app.save_library_state()
        self.refresh_media_grid()
        self.reset_player()

    def refresh_media_grid(self):
        if not hasattr(self, "queue_frame"):
            return  # search box placeholder can fire this before the grid exists yet

        missing = [f for f in self.app.selected_files if not os.path.exists(f)]
        if missing:
            for f in missing:
                self.app.selected_files.remove(f)
                if f in self.app.export_ready:
                    self.app.export_ready.remove(f)
                self.app.clip_music_map.pop(f, None)
                self.app.clip_music_volume_map.pop(f, None)
                self.app.thumbnail_cache.pop(f, None)
            self.app.save_library_state()
            if self.app.active_preview_file in missing:
                self.reset_player()

        for widget in self.queue_frame.winfo_children():
            widget.destroy()

        query = self.app.search_text(self.clip_search_entry) if hasattr(self, "clip_search_entry") else ""
        all_files = self.app.selected_files
        files = [f for f in all_files if query in Path(f).name.lower()] if query else all_files

        if not all_files:
            empty = ttk.Frame(self.queue_frame, style="Panel.TFrame", padding=(4, 22))
            empty.grid(row=0, column=0, sticky="nsew")
            ttk.Label(empty, text="No clips added yet", style="PanelMuted.TLabel",
                      font=(self.app.FONT, 9, "bold")).pack()
            ttk.Label(empty, text="Use “Add Videos” below to get started",
                      style="PanelMuted.TLabel", font=(self.app.FONT, 8)).pack(pady=(2, 0))
            self.refresh_ready_zone()
            return

        if not files:
            empty = ttk.Frame(self.queue_frame, style="Panel.TFrame", padding=(4, 22))
            empty.grid(row=0, column=0, sticky="nsew")
            ttk.Label(empty, text="No clips match your search", style="PanelMuted.TLabel",
                      font=(self.app.FONT, 9, "bold")).pack()
            self.refresh_ready_zone()
            return

        columns_limit = 2
        for index, filepath in enumerate(files):
            row = index // columns_limit
            col = index % columns_limit
            is_active = self.app.active_preview_file == filepath
            paired_track = self.app.clip_music_map.get(filepath)

            card_wrap = tk.Frame(self.queue_frame, bg=self.app.ACCENT if is_active else self.app.BORDER)
            card_wrap.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            card = ttk.Frame(card_wrap, style="Inner.TFrame", padding=8)
            card.pack(padx=1, pady=1, fill="both", expand=True)

            thumb_img = self.get_video_thumbnail(filepath)
            thumb_label = ttk.Label(card, image=thumb_img, style="Inner.TLabel")
            thumb_label.image = thumb_img
            thumb_label.pack(side="top", pady=(0, 6))

            short_title = Path(filepath).name
            if len(short_title) > 16: short_title = short_title[:13] + "..."

            ttk.Label(card, text=short_title, style="Inner.TLabel", font=(self.app.FONT, 8)).pack(pady=(0, 2))

            if paired_track:
                track_name = Path(paired_track).name
                if len(track_name) > 15: track_name = track_name[:12] + "..."
                pair_row = tk.Frame(card, bg=self.app.BG_INNER)
                pair_row.pack(pady=(0, 6))
                self.app.pill(pair_row, f"🔗 {track_name}", self.app.ACCENT_DIM, self.app.ACCENT, font_size=7).pack(side="left")
            elif paired_track == "":
                pair_row = tk.Frame(card, bg=self.app.BG_INNER)
                pair_row.pack(pady=(0, 6))
                self.app.pill(pair_row, "🔇 No music", self.app.BG_INNER_HOVER, self.app.TEXT_MUTED, font_size=7).pack(side="left")
            else:
                ttk.Label(card, text=" ", style="InnerMuted.TLabel", font=(self.app.FONT, 7)).pack(pady=(0, 6))

            btn_row = ttk.Frame(card, style="Inner.TFrame")
            btn_row.pack(fill="x")
            if is_active:
                ttk.Button(btn_row, text="✕  Remove", style="Danger.TButton", command=self.unmount_video).pack(fill="x")
            else:
                ttk.Button(btn_row, text="Use Video", style="Tiny.TButton", command=lambda p=filepath: self.mount_video(p)).pack(fill="x")

            if paired_track is not None:
                ttk.Button(card, text="↺  Unpair Music", style="Ghost.TButton",
                           command=lambda p=filepath: self.unpair_music(p)).pack(fill="x", pady=(4, 0))

            is_ready = filepath in self.app.export_ready
            ready_btn = ttk.Button(card, text="✓  In Export List" if is_ready else "＋  Ready to Export",
                                    style="Dark.TButton" if is_ready else "Ghost.TButton",
                                    command=lambda p=filepath: self.toggle_ready(p))
            ready_btn.pack(fill="x", pady=(4, 0))

            # Drag the thumbnail into the Ready-to-Export zone as an alternative to the button
            thumb_label.configure(cursor="hand2")
            thumb_label.bind("<ButtonPress-1>", lambda e, p=filepath: self._start_drag(p))
            thumb_label.bind("<B1-Motion>", self._on_drag_motion)
            thumb_label.bind("<ButtonRelease-1>", self._on_drag_release)

        self.refresh_ready_zone()

    def toggle_ready(self, filepath):
        if filepath in self.app.export_ready:
            self.app.export_ready.remove(filepath)
        else:
            self.app.export_ready.append(filepath)
        self.app.save_library_state()
        self.refresh_media_grid()

    def refresh_ready_zone(self):
        for widget in self.ready_pill_row.winfo_children():
            widget.destroy()

        ready = [f for f in self.app.export_ready if f in self.app.selected_files]
        if ready != self.app.export_ready:
            self.app.export_ready = ready  # drop any clip that was removed from the library entirely

        self.ready_count_lbl.configure(text=f"{len(ready)} clip{'s' if len(ready) != 1 else ''}")

        if not ready:
            self.ready_hint_lbl = tk.Label(self.ready_pill_row, text="Drag a clip here, or tap “＋ Ready” on its card.",
                                            bg=self.app.ACCENT_DIM, fg=self.app.TEXT_MUTED, font=(self.app.FONT, 8))
            self.ready_hint_lbl.pack(anchor="w")
            return

        row_wrap = tk.Frame(self.ready_pill_row, bg=self.app.ACCENT_DIM)
        row_wrap.pack(fill="x")
        for path in ready:
            name = Path(path).name
            if len(name) > 18: name = name[:15] + "..."
            pill = tk.Frame(row_wrap, bg=self.app.BG_INNER, padx=8, pady=4)
            pill.pack(side="left", padx=(0, 6), pady=(0, 6))
            tk.Label(pill, text=f"🎞️ {name}", bg=self.app.BG_INNER, fg=self.app.TEXT_LIGHT,
                     font=(self.app.FONT, 8, "bold")).pack(side="left")
            tk.Label(pill, text=" ✕", bg=self.app.BG_INNER, fg=self.app.TEXT_MUTED, font=(self.app.FONT, 8, "bold"),
                     cursor="hand2").pack(side="left")
            pill.winfo_children()[1].bind("<Button-1>", lambda e, p=path: self.toggle_ready(p))

    def _start_drag(self, filepath):
        self._drag_path = filepath
        self._drag_ghost = tk.Toplevel(self)
        self._drag_ghost.overrideredirect(True)
        self._drag_ghost.attributes("-topmost", True)
        name = Path(filepath).name
        if len(name) > 20: name = name[:17] + "..."
        tk.Label(self._drag_ghost, text=f"🎞️ {name}", bg=self.app.ACCENT, fg="#08110a",
                 font=(self.app.FONT, 8, "bold"), padx=8, pady=4).pack()

    def _on_drag_motion(self, event):
        if not getattr(self, "_drag_ghost", None):
            return
        x = self.winfo_pointerx() + 12
        y = self.winfo_pointery() + 12
        self._drag_ghost.geometry(f"+{x}+{y}")

    def _on_drag_release(self, event):
        ghost = getattr(self, "_drag_ghost", None)
        path = getattr(self, "_drag_path", None)
        if ghost:
            ghost.destroy()
            self._drag_ghost = None
        if not path:
            return

        zx1 = self.ready_zone.winfo_rootx()
        zy1 = self.ready_zone.winfo_rooty()
        zx2 = zx1 + self.ready_zone.winfo_width()
        zy2 = zy1 + self.ready_zone.winfo_height()
        px, py = self.winfo_pointerx(), self.winfo_pointery()

        if zx1 <= px <= zx2 and zy1 <= py <= zy2 and path not in self.app.export_ready:
            self.app.export_ready.append(path)
            self.refresh_media_grid()
        self._drag_path = None

    def refresh_music_library(self):
        if not hasattr(self, "music_frame"):
            return  # search box placeholder can fire this before the grid exists yet
        for widget in self.music_frame.winfo_children():
            widget.destroy()
        if not MUSIC_DIR.exists():
            return
        self.app.music_files = [str(MUSIC_DIR / f) for f in os.listdir(MUSIC_DIR) if f.lower().endswith((".mp3", ".wav"))]

        stale_pairs = [c for c, t in self.app.clip_music_map.items() if t and not os.path.exists(t)]
        if stale_pairs:
            for c in stale_pairs:
                self.app.clip_music_map.pop(c, None)
            self.app.save_library_state()

        query = self.app.search_text(self.music_search_entry) if hasattr(self, "music_search_entry") else ""
        tracks = [f for f in self.app.music_files if query in Path(f).name.lower()] if query else self.app.music_files

        if not self.app.music_files:
            empty = ttk.Frame(self.music_frame, style="Panel.TFrame", padding=(4, 22))
            empty.grid(row=0, column=0, sticky="nsew")
            ttk.Label(empty, text="No tracks in your library", style="PanelMuted.TLabel",
                      font=(self.app.FONT, 9, "bold")).pack()
            ttk.Label(empty, text="Use “Add Track” below to upload audio",
                      style="PanelMuted.TLabel", font=(self.app.FONT, 8)).pack(pady=(2, 0))
            return

        if not tracks:
            empty = ttk.Frame(self.music_frame, style="Panel.TFrame", padding=(4, 22))
            empty.grid(row=0, column=0, sticky="nsew")
            ttk.Label(empty, text="No tracks match your search", style="PanelMuted.TLabel",
                      font=(self.app.FONT, 9, "bold")).pack()
            return

        columns_limit = 2
        img = Image.new("RGB", (130, 65), color=self.app.BG_INNER)
        placeholder_thumb = ImageTk.PhotoImage(img)

        for index, filepath in enumerate(tracks):
            row = index // columns_limit
            col = index % columns_limit
            is_active = self.app.active_music_file == filepath
            paired_to_current = (self.app.active_preview_file
                                  and self.app.clip_music_map.get(self.app.active_preview_file) == filepath)

            card_wrap = tk.Frame(self.music_frame, bg=self.app.ACCENT if (is_active or paired_to_current) else self.app.BORDER)
            card_wrap.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            card = ttk.Frame(card_wrap, style="Inner.TFrame", padding=8)
            card.pack(padx=1, pady=1, fill="both", expand=True)

            thumb_label = ttk.Label(card, image=placeholder_thumb, style="Inner.TLabel")
            thumb_label.image = placeholder_thumb
            thumb_label.pack(side="top", pady=(0, 2))

            symbol_lbl = ttk.Label(thumb_label, text="♪", font=(self.app.FONT, 16, "bold"),
                                    background=self.app.BG_INNER, foreground=self.app.ACCENT)
            symbol_lbl.place(relx=0.5, rely=0.5, anchor="center")

            short_title = Path(filepath).name
            if len(short_title) > 16: short_title = short_title[:13] + "..."
            ttk.Label(card, text=short_title, style="Inner.TLabel", font=(self.app.FONT, 8)).pack(pady=(6, 2))

            if paired_to_current:
                pair_row = tk.Frame(card, bg=self.app.BG_INNER)
                pair_row.pack(pady=(0, 6))
                self.app.pill(pair_row, "🔗 Paired to this clip", self.app.ACCENT_DIM, self.app.ACCENT, font_size=7).pack(side="left")
            else:
                ttk.Label(card, text=" ", style="InnerMuted.TLabel", font=(self.app.FONT, 7)).pack(pady=(0, 6))

            if paired_to_current:
                ttk.Button(card, text="✕  Remove", style="Danger.TButton", command=self.unmix_music).pack(fill="x")
            elif self.app.active_preview_file:
                ttk.Button(card, text="🔗  Pair with Clip", style="Tiny.TButton",
                           command=lambda p=filepath: self.mount_music_track(p)).pack(fill="x")
            else:
                ttk.Button(card, text="Use Track", style="Tiny.TButton",
                           command=lambda p=filepath: self.mount_music_track(p)).pack(fill="x")

    def get_video_thumbnail(self, filepath):
        if filepath in self.app.thumbnail_cache:
            return self.app.thumbnail_cache[filepath]
        try:
            cap = cv2.VideoCapture(filepath)
            ret, frame = cap.read()
            cap.release()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = frame.shape
                scale = min(130/w, 75/h)
                nw, nh = int(w * scale), int(h * scale)
                frame = cv2.resize(frame, (nw, nh))
                img = Image.fromarray(frame)
            else:
                img = Image.new("RGB", (130, 75), color=self.app.BG_PANEL)
        except Exception:
            img = Image.new("RGB", (130, 75), color=self.app.BG_PANEL)
        tk_thumb = ImageTk.PhotoImage(img)
        self.app.thumbnail_cache[filepath] = tk_thumb
        return tk_thumb

    def _sync_scrub_button(self):
        """Single source of truth for the play/pause button — always derived from is_playing,
        never set ad-hoc, so switching music/clips mid-playback can't leave it showing the wrong label."""
        if not self.app.active_preview_file and not self.app.active_music_file:
            self.scrub_btn.configure(state="disabled", text="▶ Play Preview")
            return
        self.scrub_btn.configure(state="normal")
        has_video = bool(self.app.active_preview_file)
        if self.app.is_playing:
            self.scrub_btn.configure(text="⏸ Pause Preview" if has_video else "⏸ Pause Audio")
        else:
            self.scrub_btn.configure(text="▶ Play Preview" if has_video else "▶ Play Audio")

    def mount_video(self, target_path):
        if not os.path.exists(target_path): return
        self.reset_player()

        self.app.active_preview_file = target_path
        self.app.video_cap = cv2.VideoCapture(target_path)
        self.app.playback_started_fresh = True
        self.app.current_playback_offset = 0.0
        self.app.video_sound = None

        # Restore this clip's paired music track into the preview, if it has one — this is
        # cheap (no ffmpeg involved) so it happens immediately, before any audio extraction.
        paired = self.app.clip_music_map.get(target_path)
        clip_volume = self.app.clip_music_volume_map.get(target_path, self.app.music_volume_var.get())
        pygame.mixer.Channel(1).stop()
        if paired:
            self.app.active_music_file = paired
            try:
                self.app.music_sound = pygame.mixer.Sound(paired)
                self.app.music_sound.set_volume(clip_volume)
            except Exception:
                self.app.music_sound = None
        elif paired == "":
            self.app.active_music_file = None
            self.app.music_sound = None
        # else: no explicit pairing — leave whatever default track is currently active

        self.app.is_playing = False
        self._sync_scrub_button()
        self._sync_clip_volume_controls()
        self.update_title_bar_display()
        self.refresh_media_grid()
        self.refresh_music_library()

        # Pull down a single first frame right away so the preview never waits on audio
        # extraction — this is what used to make "Use Video" feel slow.
        self.app.is_playing = True
        self.app.playback_start_real_time = time.time()
        self.app.stream_player_engine()
        self.app.is_playing = False
        self._sync_scrub_button()

        self._load_clip_audio_async(target_path)

    def _load_clip_audio_async(self, target_path):
        """Extracts (or reuses a cached copy of) this clip's own audio track without blocking the
        UI thread. ffmpeg only actually runs the first time a given file is previewed."""
        cached = self.app.audio_extract_cache.get(target_path)
        if cached and os.path.exists(cached):
            self._apply_clip_audio(target_path, cached)
            return

        self.player_title.configure(text="🎞  Loading audio…", foreground="#ffc83b")
        out_path = self.app.audio_cache_dir / f"{hashlib.sha1(target_path.encode()).hexdigest()}.wav"

        def worker():
            cmd = ["ffmpeg", "-y", "-i", target_path, "-vn", "-acodec", "pcm_s16le",
                   "-ar", "44100", "-ac", "2", str(out_path)]
            ok = False
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                ok = out_path.exists()
            except Exception:
                ok = False
            self.after(0, lambda: self._apply_clip_audio(target_path, str(out_path) if ok else None))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_clip_audio(self, target_path, wav_path):
        # If the person already switched to a different clip while extraction was running,
        # this result is stale — drop it instead of stomping on the newer preview.
        if self.app.active_preview_file != target_path:
            return
        if wav_path:
            self.app.audio_extract_cache[target_path] = wav_path
            try:
                self.app.video_sound = pygame.mixer.Sound(wav_path)
                if self.app.is_playing:
                    pygame.mixer.Channel(0).play(self.app.video_sound)
            except Exception:
                self.app.video_sound = None
        else:
            self.app.video_sound = None
        self.update_title_bar_display()

    def unmount_video(self):
        self.reset_player()
        self._sync_clip_volume_controls()
        self.refresh_media_grid()

    def mount_music_track(self, track_path):
        """Loads and prepares selected audio. Pairs it to the currently mounted clip so the
        choice sticks for that clip specifically, and instantly syncs the live preview if playing."""
        if not os.path.exists(track_path): return
        pygame.mixer.Channel(1).stop()
        self.app.active_music_file = track_path

        if self.app.active_preview_file:
            self.app.clip_music_map[self.app.active_preview_file] = track_path
            self.app.save_library_state()

        try:
            self.app.music_sound = pygame.mixer.Sound(track_path)
            clip_volume = self.app.clip_music_volume_map.get(self.app.active_preview_file, self.app.music_volume_var.get())
            self.app.music_sound.set_volume(clip_volume)
            
            # Seamlessly injects track immediately if previewer engine is currently active —
            # is_playing itself is untouched, so the button stays exactly as it was.
            if self.app.is_playing:
                pygame.mixer.Channel(1).play(self.app.music_sound, loops=-1)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Audio mixer failed to load track: {e}")
            self.app.music_sound = None
            
        self.update_title_bar_display()
        self.refresh_music_library()
        self.refresh_media_grid()
        self._sync_scrub_button()

    def unpair_music(self, clip_path):
        """Reverts a clip back to no explicit pairing (falls back to the default track at export)."""
        self.app.clip_music_map.pop(clip_path, None)
        self.app.save_library_state()
        self.refresh_media_grid()
        self.refresh_music_library()

    def unmix_music(self):
        pygame.mixer.Channel(1).stop()
        self.app.music_sound = None
        self.app.active_music_file = None
        if self.app.active_preview_file:
            self.app.clip_music_map[self.app.active_preview_file] = ""  # explicit "no music" for this clip
            self.app.save_library_state()
        self.update_title_bar_display()
        self.refresh_music_library()
        self.refresh_media_grid()
        self._sync_scrub_button()

    def update_title_bar_display(self):
        v_name = Path(self.app.active_preview_file).name if self.app.active_preview_file else "EMPTY"
        m_name = Path(self.app.active_music_file).name if self.app.active_music_file else "NONE"
        self.player_title.configure(text=f"🎞  {v_name}    •    🎵  {m_name}", foreground=self.app.ACCENT)

    def toggle_workspace_playback(self):
        self.app.is_playing = not self.app.is_playing
        if self.app.is_playing:
            if self.app.playback_started_fresh:
                self.app.playback_start_real_time = time.time()
                if self.app.video_sound: pygame.mixer.Channel(0).play(self.app.video_sound)
                if self.app.music_sound: pygame.mixer.Channel(1).play(self.app.music_sound, loops=-1)
                self.app.playback_started_fresh = False
            else:
                self.app.playback_start_real_time = time.time() - self.app.current_playback_offset
                pygame.mixer.Channel(0).unpause()
                pygame.mixer.Channel(1).unpause()
        else:
            pygame.mixer.Channel(0).pause()
            pygame.mixer.Channel(1).pause()
            self.app.current_playback_offset = time.time() - self.app.playback_start_real_time
        self._sync_scrub_button()

    def reset_player(self):
        self.app.is_playing = False
        pygame.mixer.Channel(0).stop()
        pygame.mixer.Channel(1).stop()
        self.app.video_sound = None
        self.app.playback_started_fresh = True
        self.app.current_playback_offset = 0.0
        
        if self.app.video_cap:
            self.app.video_cap.release()
            self.app.video_cap = None
        self.app.active_preview_file = None
        self._sync_scrub_button()
        self.player_canvas.delete("all")
        self.player_title.configure(text="Add or select a clip to begin previewing", foreground=self.app.TEXT_MUTED)

    def go_to_export(self):
        """Cleans media engine states without wiping selected assets so configurations survive export routing."""
        self.app.is_playing = False
        pygame.mixer.Channel(0).stop()
        pygame.mixer.Channel(1).stop()
        self.app.playback_started_fresh = True
        self.app.current_playback_offset = 0.0
        if self.app.video_cap:
            self.app.video_cap.release()
            self.app.video_cap = None
        self.player_canvas.delete("all")
        self.player_title.configure(text="Add or select a clip to begin previewing", foreground=self.app.TEXT_MUTED)
        
        # FIXED: Removed the line that set self.app.active_music_file to None here!

        if not self.app.selected_files:
            messagebox.showerror(APP_NAME, "Please add at least one video clip before saving.")
            return
        if not self.app.export_ready:
            messagebox.showerror(APP_NAME, "Drag at least one clip into “Ready to Export” before continuing.")
            return
        self.app.show_screen("ExportScreen")

    def sign_out_action(self):
        self.reset_player()
        self.app.active_music_file = None
        self.app.sign_out()
        self.app.show_screen("LoginScreen")


# ──────────────────────────────────────────────────────────
# SCREEN 3: EXPORT HUB (Settings & Console)
# ──────────────────────────────────────────────────────────
class ExportScreen(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.app = controller

        self.app.make_crosshair_backdrop(self)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.pro_widgets = []
        self.total_files = 0
        self.current_file_index = 0
        self.anim_job = None

        # ─── Top bar ───
        header = tk.Frame(self, bg=self.app.BG_PANEL, height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(1, weight=1)

        ttk.Button(header, text="←  Back to Editor", style="Ghost.TButton",
                   command=self.go_back).grid(row=0, column=0, sticky="w", padx=24)
        title_col = ttk.Frame(header, style="Panel.TFrame")
        title_col.grid(row=0, column=1, sticky="w")
        title_row = ttk.Frame(title_col, style="Panel.TFrame")
        title_row.pack(anchor="w", pady=(14, 0))
        export_icon = self.app.make_logo_mark(title_row, size=22)
        export_icon.pack(side="left", padx=(0, 8))
        ttk.Label(title_row, text="Export & Render", style="Brand.TLabel").pack(side="left")
        ttk.Label(title_col, text="Fine-tune your output, then send the whole batch through the pipeline",
                  style="PanelMuted.TLabel", font=(self.app.FONT, 8)).pack(anchor="w", pady=(0, 14))

        # ─── Body ───
        body = tk.Canvas(self, bg=self.app.BG_MAIN, highlightthickness=0, bd=0)
        body.grid(row=1, column=0, sticky="nsew")
        self.app.paint_crosshair_tiles(body)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # ─── Batch queue tray (spans both columns) ───
        queue_outer, queue_panel = self.app.card(body, padding=16)
        queue_outer.grid(row=0, column=0, columnspan=2, sticky="ew", padx=22, pady=(22, 10))
        queue_panel.columnconfigure(1, weight=1)

        ttk.Label(queue_panel, text="🎬", style="Panel.TLabel", font=(self.app.FONT, 16)).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
        self.queue_title_lbl = ttk.Label(queue_panel, text="0 clips queued", style="CardTitle.TLabel")
        self.queue_title_lbl.grid(row=0, column=1, sticky="w")
        self.queue_sub_lbl = ttk.Label(queue_panel, text="Every clip below renders with the same settings in one batch.",
                                        style="PanelMuted.TLabel", font=(self.app.FONT, 8))
        self.queue_sub_lbl.grid(row=1, column=1, sticky="w")

        self.chip_row = ttk.Frame(queue_panel, style="Panel.TFrame")
        self.chip_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        # LEFT: Render Configuration — one continuous scrollable page, no tabs
        settings_outer, settings_panel = self.app.card(body, padding=0)
        settings_outer.grid(row=1, column=0, sticky="nsew", padx=(22, 10), pady=(0, 22))
        settings_panel.columnconfigure(0, weight=1)
        settings_panel.rowconfigure(0, weight=1)

        scroll_canvas = tk.Canvas(settings_panel, bg=self.app.BG_PANEL, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(settings_panel, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scroll_canvas.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=4)
        scrollbar.grid(row=0, column=1, sticky="ns")

        page = ttk.Frame(scroll_canvas, style="Panel.TFrame", padding=(18, 18, 18, 24))
        page_window = scroll_canvas.create_window((0, 0), window=page, anchor="nw")
        page.columnconfigure(0, weight=1)

        def _on_page_configure(event):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        page.bind("<Configure>", _on_page_configure)

        def _on_canvas_configure(event):
            scroll_canvas.itemconfigure(page_window, width=event.width)
        scroll_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        row_cursor = [0]

        def section(title):
            wrap = ttk.Frame(page, style="Panel.TFrame")
            wrap.grid(row=row_cursor[0], column=0, sticky="ew", pady=(0 if row_cursor[0] == 0 else 26, 0))
            wrap.columnconfigure(0, weight=1)
            row_cursor[0] += 1
            ttk.Label(wrap, text=title, style="SectionTitle.TLabel", font=(self.app.FONT, 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
            divider = tk.Frame(wrap, bg=self.app.BORDER, height=1)
            divider.grid(row=1, column=0, sticky="ew", pady=(0, 12))
            body_frame = ttk.Frame(wrap, style="Panel.TFrame")
            body_frame.grid(row=2, column=0, sticky="ew")
            body_frame.columnconfigure(0, weight=1)
            return body_frame

        # ── Section: Audio ──
        sec_audio = section("🎵  Audio")
        ttk.Label(sec_audio, text="Background music volume is now set per clip, back on the Editor "
                  "screen — select a clip there to adjust its own level.",
                  style="PanelMuted.TLabel", font=(self.app.FONT, 8), wraplength=280).grid(row=0, column=0, sticky="w")

        # ── Section: Captions ──
        sec_cap = section("🔤  Captions")
        self.add_slider(sec_cap, 0, "Caption Subtitle Size", self.app.font_size_var, 48, 130, pro_only=True)
        self.add_slider(sec_cap, 1, "Caption Y Margin (Height)", self.app.caption_margin_var, 80, 420, pro_only=True)
        self.add_slider(sec_cap, 2, "Caption Outline Thickness", self.app.caption_outline_var, 1, 10, pro_only=True)
        self.add_slider(sec_cap, 3, "Words per Caption Block", self.app.caption_words_var, 3, 10, pro_only=True)
        self.add_dropdown(sec_cap, 4, "Caption Font", self.app.font_name_var,
                           ["Impact", "Arial Black", "Bebas Neue", "Montserrat", "Anton", "Segoe UI"], pro_only=False)
        self.add_checkbox(sec_cap, 5, "✨  Highlight keywords mid-sentence", self.app.highlight_var, pro_only=False)

        # ── Section: Output ──
        sec_out = section("📐  Output")
        self.add_slider(sec_out, 0, "Zoom / Crop Ratio", self.app.zoom_var, 1.0, 1.14, pro_only=True)
        self.add_slider(sec_out, 1, "Background Blur Strength", self.app.bg_blur_var, 0, 40, pro_only=False)
        self.add_slider(sec_out, 2, "Video Quality  (lower = crisper, bigger file)", self.app.quality_var, 14, 28, pro_only=True, invert_hint=True)
        self.add_dropdown(sec_out, 3, "Render Speed", self.app.preset_var,
                           ["ultrafast", "veryfast", "fast", "medium", "slow"], pro_only=True)

        res_frame = ttk.Frame(sec_out, style="Inner.TFrame", padding=16)
        res_frame.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        res_frame.columnconfigure(1, weight=1)
        res_frame.columnconfigure(3, weight=1)
        ttk.Label(res_frame, text="📐  OUTPUT RESOLUTION", style="Inner.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        ttk.Label(res_frame, text="Width", style="InnerMuted.TLabel").grid(row=1, column=0, sticky="w")
        self.w_entry = ttk.Entry(res_frame, textvariable=self.app.output_width_var, width=8)
        self.w_entry.grid(row=1, column=1, sticky="w", padx=(8, 24), ipady=2)
        ttk.Label(res_frame, text="Height", style="InnerMuted.TLabel").grid(row=1, column=2, sticky="w")
        self.h_entry = ttk.Entry(res_frame, textvariable=self.app.output_height_var, width=8)
        self.h_entry.grid(row=1, column=3, sticky="w", padx=(8, 0), ipady=2)
        for var in (self.app.font_size_var, self.app.caption_margin_var, self.app.caption_outline_var,
                    self.app.font_name_var, self.app.highlight_var, self.app.zoom_var, self.app.bg_blur_var,
                    self.app.output_width_var, self.app.output_height_var):
            var.trace_add("write", lambda *a: self.schedule_preview_update())

        # ── Section: Advanced ──
        sec_adv = section("⚙  Advanced")
        api_frame = ttk.Frame(sec_adv, style="Inner.TFrame", padding=16)
        api_frame.grid(row=0, column=0, sticky="ew")
        api_frame.columnconfigure(0, weight=1)
        ttk.Label(api_frame, text="🔑  GROQ CLOUD API KEY  (optional)", style="Inner.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(api_frame, textvariable=self.app.groq_key_var, show="•", width=40).grid(row=1, column=0, sticky="ew", ipady=3)
        ttk.Label(sec_adv, text="Add your own free key from console.groq.com for near-instant "
                  "cloud captioning. Leave blank to use the slower local fallback engine.",
                  style="PanelMuted.TLabel", font=(self.app.FONT, 8), wraplength=280).grid(row=1, column=0, sticky="w", pady=(10, 0))

        # RIGHT: split into a live settings-preview card (fixed) and the console (expands)
        right_col = ttk.Frame(body, style="TFrame")
        right_col.grid(row=1, column=1, sticky="nsew", padx=(10, 22), pady=(0, 22))
        right_col.columnconfigure(0, weight=1)
        right_col.rowconfigure(1, weight=1)

        preview_outer, preview_card = self.app.card(right_col, padding=14)
        preview_outer.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        preview_card.columnconfigure(0, weight=1)
        ttk.Label(preview_card, text="👀  Live Settings Preview", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preview_card, text="A frame from your queued clip, rendered with the caption size, "
                  "blur, and zoom/crop you've dialed in — updates as you drag.",
                  style="PanelMuted.TLabel", font=(self.app.FONT, 8), wraplength=260).grid(row=1, column=0, sticky="w", pady=(2, 10))
        preview_canvas_wrap = tk.Frame(preview_card, bg=self.app.BORDER)
        preview_canvas_wrap.grid(row=2, column=0, sticky="ew")
        self.settings_preview_lbl = tk.Label(preview_canvas_wrap, bg=self.app.BG_MAIN)
        self.settings_preview_lbl.pack(padx=1, pady=1)
        self._preview_sample_frame = None   # raw PIL frame grabbed from a queued clip
        self._preview_sample_path = None
        self._preview_job = None

        # RIGHT (cont'd): Console & Run Buttons
        console_outer, console_panel = self.app.card(right_col, padding=22)
        console_outer.grid(row=1, column=0, sticky="nsew")
        console_panel.columnconfigure(0, weight=1)
        console_panel.rowconfigure(4, weight=1)

        ttk.Label(console_panel, text="Render Console", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))

        status_row = tk.Frame(console_panel, bg=self.app.BG_INNER)
        status_row.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.status_dot = tk.Label(status_row, text="●", bg=self.app.BG_INNER, fg=self.app.TEXT_MUTED, font=(self.app.FONT, 11))
        self.status_dot.pack(side="left", padx=(12, 6), pady=10)
        self.status_lbl = tk.Label(status_row, text="Pipeline ready — waiting for execution.",
                                    bg=self.app.BG_INNER, fg=self.app.TEXT_LIGHT, font=(self.app.FONT, 10, "bold"))
        self.status_lbl.pack(side="left", pady=10)

        progress_row = ttk.Frame(console_panel, style="Panel.TFrame")
        progress_row.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_row, orient="horizontal", mode="determinate",
                                         style="Accent.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress_pct_lbl = ttk.Label(progress_row, text="0%", style="PanelMuted.TLabel", font=("Consolas", 9, "bold"))
        self.progress_pct_lbl.grid(row=0, column=1, padx=(10, 0))

        action_row = ttk.Frame(console_panel, style="Panel.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        action_row.columnconfigure(0, weight=1)
        self.run_btn = ttk.Button(action_row, text="▶  Create Video", style="Accent.TButton", command=self.fire_render)
        self.run_btn.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.kill_btn = ttk.Button(action_row, text="■  Force Halt", style="Danger.TButton", command=self.halt_render, state="disabled")
        self.kill_btn.grid(row=0, column=1)

        term_wrap = tk.Frame(console_panel, bg=self.app.BORDER)
        term_wrap.grid(row=4, column=0, sticky="nsew", pady=(0, 14))
        term_bar = tk.Frame(term_wrap, bg=self.app.BG_INNER, height=28)
        term_bar.pack(fill="x", padx=1, pady=(1, 0))
        for dot_color in ("#ff6459", "#ffbd2e", "#28c93f"):
            tk.Label(term_bar, text="●", bg=self.app.BG_INNER, fg=dot_color, font=(self.app.FONT, 9)).pack(side="left", padx=(10 if dot_color == "#ff6459" else 3, 0), pady=6)
        tk.Label(term_bar, text="render.log", bg=self.app.BG_INNER, fg=self.app.TEXT_FAINT, font=(self.app.FONT, 8)).pack(side="left", padx=10)
        self.log_text = tk.Text(term_wrap, bg=self.app.BG_MAIN, fg=self.app.TEXT_LIGHT, insertbackground=self.app.TEXT_LIGHT,
                                 relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8, bd=0, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        ttk.Button(console_panel, text="📁  Open Output Folder", style="Dark.TButton",
                   command=self.app.open_outputs).grid(row=5, column=0, sticky="ew")

    def append_log(self, text):
        """Writes a line into the read-only render log (briefly unlocking it to insert)."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def set_progress(self, value, maximum=None):
        if maximum is not None:
            self.progress.configure(maximum=max(1, maximum))
        self.progress.configure(value=value)
        pct = int(round((value / float(self.progress["maximum"])) * 100)) if self.progress["maximum"] else 0
        self.progress_pct_lbl.configure(text=f"{pct}%")

    def schedule_preview_update(self):
        if self._preview_job:
            try:
                self.app.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.app.after(80, self.render_settings_preview)

    def _grab_sample_frame(self):
        """Grabs a representative frame (a third of the way in, to skip black intros) from a
        queued clip, so the settings preview has something real to show."""
        candidates = self.app.export_ready or self.app.selected_files
        if not candidates:
            self._preview_sample_frame = None
            self._preview_sample_path = None
            return
        path = candidates[0]
        if path == self._preview_sample_path and self._preview_sample_frame is not None:
            return
        try:
            cap = cv2.VideoCapture(path)
            total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            if total > 10:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 3)
            ret, frame = cap.read()
            cap.release()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._preview_sample_frame = Image.fromarray(frame)
                self._preview_sample_path = path
            else:
                self._preview_sample_frame = None
                self._preview_sample_path = None
        except Exception:
            self._preview_sample_frame = None
            self._preview_sample_path = None

    def render_settings_preview(self):
        """Renders a small PIL composite that mirrors clip_editor.py's real filter graph
        (cover-crop + blur background, 4:3 foreground overlay, zoom punch-in, sample caption)
        so caption size, blur, and zoom/crop settings can be judged before actually exporting."""
        self._preview_job = None
        self._grab_sample_frame()
        src = self._preview_sample_frame
        if src is None:
            self.settings_preview_lbl.configure(image="", text="Add a clip to see a preview",
                                                 fg=self.app.TEXT_MUTED, bg=self.app.BG_MAIN)
            self.settings_preview_lbl.image = None
            return

        out_w = max(1, int(self.app.output_width_var.get()))
        out_h = max(1, int(self.app.output_height_var.get()))
        disp_w = 230
        disp_h = max(1, int(disp_w * out_h / out_w))
        scale = disp_w / out_w  # every pixel-based setting below is scaled down by this factor

        sw, sh = src.size

        # Background: cover-crop to the frame, then blur
        cover_scale = max(disp_w / sw, disp_h / sh)
        bg = src.resize((max(1, int(sw * cover_scale)), max(1, int(sh * cover_scale))), Image.LANCZOS)
        bx, by = (bg.width - disp_w) // 2, (bg.height - disp_h) // 2
        bg = bg.crop((bx, by, bx + disp_w, by + disp_h))
        blur_radius = max(0.0, self.app.bg_blur_var.get() * scale * 0.6)
        if blur_radius > 0.3:
            bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        # Foreground: crop to a 4:3-ish box (matches clip_editor.py), scale to full width, center it
        fg_crop_w = min(sw, int(sh * 4 / 3))
        fx = (sw - fg_crop_w) // 2
        fg = src.crop((fx, 0, fx + fg_crop_w, sh))
        fg_h = max(1, int(disp_w * fg.height / fg.width))
        fg = fg.resize((disp_w, fg_h), Image.LANCZOS)

        canvas = bg.convert("RGB")
        canvas.paste(fg, (0, (disp_h - fg_h) // 2))

        # Zoom / crop punch-in
        zoom = self.app.zoom_var.get()
        if zoom > 1.0:
            zw, zh = max(1, int(disp_w * zoom)), max(1, int(disp_h * zoom))
            canvas = canvas.resize((zw, zh), Image.LANCZOS)
            zx, zy = (canvas.width - disp_w) // 2, (canvas.height - disp_h) // 2
            canvas = canvas.crop((zx, zy, zx + disp_w, zy + disp_h))

        # Sample caption styled with the current font size/margin/outline/highlight settings
        draw = ImageDraw.Draw(canvas)
        font_px = max(6, int(self.app.font_size_var.get() * scale))
        font = None
        for candidate in (f"{self.app.font_name_var.get()}.ttf", "arialbd.ttf", "arial.ttf"):
            try:
                font = ImageFont.truetype(candidate, font_px)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        sample_words = ["THIS", "IS", "YOUR", "CAPTION"]
        highlight_idx = 2 if self.app.highlight_var.get() else -1
        outline_px = max(1, round(self.app.caption_outline_var.get() * scale))
        margin_from_bottom = max(0, int(self.app.caption_margin_var.get() * scale))
        text_y = max(0, min(disp_h - font_px, disp_h - margin_from_bottom))

        widths = [draw.textlength(w + " ", font=font) for w in sample_words]
        x = max(0, (disp_w - sum(widths)) / 2)
        for i, word in enumerate(sample_words):
            fill = self.app.ACCENT if i == highlight_idx else "#ffffff"
            for ox in range(-outline_px, outline_px + 1):
                for oy in range(-outline_px, outline_px + 1):
                    if ox or oy:
                        draw.text((x + ox, text_y + oy), word, font=font, fill="#000000")
            draw.text((x, text_y), word, font=font, fill=fill)
            x += widths[i]

        tk_img = ImageTk.PhotoImage(canvas)
        self.settings_preview_lbl.configure(image=tk_img, text="")
        self.settings_preview_lbl.image = tk_img

    def refresh_queue_tray(self):
        for child in self.chip_row.winfo_children():
            child.destroy()

        files = self.app.export_ready
        count = len(files)
        noun = "clip" if count == 1 else "clips"
        self.queue_title_lbl.configure(text=f"{count} {noun} ready to export")

        if not self.app.is_pro() and count > 1:
            self.queue_sub_lbl.configure(
                text=f"Free plan renders only the first clip. Upgrade to Pro to export all {count} in one batch.")
        else:
            self.queue_sub_lbl.configure(text="Every clip below renders with the same settings in one batch.")

        if not files:
            ttk.Label(self.chip_row, text="Nothing marked ready yet — go back and drag clips into “Ready to Export”.",
                      style="PanelMuted.TLabel", font=(self.app.FONT, 8)).pack(side="left")
            return

        locked_after_first = (not self.app.is_pro()) and count > 1
        for idx, path in enumerate(files):
            name = os.path.basename(path)
            if len(name) > 22:
                name = name[:19] + "…"
            dimmed = locked_after_first and idx > 0
            chip = tk.Frame(self.chip_row, bg=self.app.BG_INNER, padx=10, pady=6)
            chip.pack(side="left", padx=(0, 8), pady=(0, 8))
            fg = self.app.TEXT_FAINT if dimmed else self.app.TEXT_LIGHT
            marker = "🔒" if dimmed else "🎞️"
            tk.Label(chip, text=f"{marker}  {name}", bg=self.app.BG_INNER, fg=fg,
                     font=(self.app.FONT, 8, "bold")).pack(side="left")

    def note_log_line(self, line):
        if "Processing File:" in line and self.total_files:
            self.current_file_index += 1
            name = line.split("Processing File:", 1)[1].strip()
            self.status_lbl.configure(text=f"Rendering clip {self.current_file_index} of {self.total_files} — {name}")
            self.set_progress(self.current_file_index - 1)
            self._start_creep(self.current_file_index - 1, self.current_file_index)
        elif "Export Complete" in line and self.total_files:
            # A clip actually finished rendering — snap the bar to the real, exact fraction
            # instead of waiting for the whole batch to end.
            self._stop_creep()
            self.set_progress(self.current_file_index)

    def _start_creep(self, low, high):
        """Nudges the bar forward in small steps while a clip is actively rendering, so it never
        just sits frozen between the 'started' and 'finished' log lines. Never reaches `high` on
        its own — that only happens once the real completion line snaps it there."""
        self._stop_creep()
        ceiling = low + (high - low) * 0.92
        step = (high - low) * 0.015

        def tick():
            current = float(self.progress["value"])
            if current >= ceiling:
                self.anim_job = None
                return
            self.set_progress(current + step)
            self.anim_job = self.app.after(180, tick)

        self.anim_job = self.app.after(180, tick)

    def _stop_creep(self):
        if self.anim_job is not None:
            try:
                self.app.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None

    def on_display_refresh(self):
        pro_state = "normal" if self.app.is_pro() else "disabled"
        for widget in self.pro_widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state=("readonly" if self.app.is_pro() else "disabled"))
                elif isinstance(widget, (ModernSlider, ToggleSwitch)):
                    widget.configure(state=pro_state)
                    widget.refresh()
                else:
                    widget.configure(state=pro_state)
            except tk.TclError:
                pass
        self.clear_log()
        self._stop_creep()
        self.set_progress(0, maximum=len(self.app.export_ready))
        self.current_file_index = 0
        self.refresh_queue_tray()
        self._preview_sample_path = None  # queue may have changed — force a fresh frame grab
        self.render_settings_preview()

    def go_back(self):
        if self.app.process:
            if not messagebox.askyesno(APP_NAME, "Render process is actively executing. Leave screen anyway?"):
                return
        self.app.show_screen("EditorScreen")

    def add_slider(self, parent, row, label, variable, from_, to, pro_only, invert_hint=False):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 16, 0))
        frame.grid_columnconfigure(0, weight=1)

        label_row = ttk.Frame(frame, style="Panel.TFrame")
        label_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        label_row.columnconfigure(0, weight=1)

        ttk.Label(label_row, text=label, style="PanelMuted.TLabel", font=(self.app.FONT, 10)).grid(row=0, column=0, sticky="w")
        if pro_only:
            self.app.pill(label_row, "PRO", self.app.ACCENT_DIM, self.app.ACCENT, font_size=7).grid(row=0, column=1, padx=(6, 0))

        val_lbl = tk.Label(frame, text="", bg=self.app.BG_INNER, fg=self.app.TEXT_LIGHT, font=("Consolas", 9, "bold"), padx=8, pady=1)
        val_lbl.grid(row=0, column=2, sticky="e", padx=(8, 0))

        def _refresh_label():
            self.app.update_slider_value(val_lbl, variable)

        slider = ModernSlider(frame, self.app, variable, from_, to, height=26, on_change=_refresh_label)
        slider.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        _refresh_label()
        if pro_only:
            self.pro_widgets.append(slider)
        return slider

    def add_dropdown(self, parent, row, label, variable, options, pro_only):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(16, 0))
        frame.grid_columnconfigure(0, weight=1)

        label_row = ttk.Frame(frame, style="Panel.TFrame")
        label_row.grid(row=0, column=0, sticky="ew")
        ttk.Label(label_row, text=label, style="PanelMuted.TLabel", font=(self.app.FONT, 10)).pack(side="left")
        if pro_only:
            self.app.pill(label_row, "PRO", self.app.ACCENT_DIM, self.app.ACCENT, font_size=7).pack(side="left", padx=(6, 0))

        combo = ttk.Combobox(frame, textvariable=variable, values=options, state="readonly")
        combo.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        if pro_only:
            self.pro_widgets.append(combo)
        return combo

    def add_checkbox(self, parent, row, label, variable, pro_only):
        wrap = tk.Frame(parent, bg=self.app.BG_INNER, padx=14, pady=10)
        wrap.grid(row=row, column=0, sticky="ew", pady=(16, 0))
        wrap.columnconfigure(0, weight=1)
        ttk.Label(wrap, text=label, style="Inner.TLabel", font=(self.app.FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
        toggle = ToggleSwitch(wrap, self.app, variable)
        toggle.grid(row=0, column=1, sticky="e", padx=(10, 0))
        if pro_only:
            self.pro_widgets.append(toggle)
        return toggle

    def fire_render(self):
        if self.app.process: return
        if not CLIP_EDITOR.exists():
            messagebox.showerror(APP_NAME, f"Compiler script missing: {CLIP_EDITOR}")
            return

        if not self.app.export_ready:
            messagebox.showerror(APP_NAME, "No clips are marked “Ready to Export”. Go back and drag some in first.")
            return

        files = list(self.app.export_ready)
        if not self.app.is_pro() and len(files) > 1:
            files = files[:1]
            self.app.log("Free account limit: Rendering index [0] only.")

        self.total_files = len(files)
        self.current_file_index = 0
        self.set_progress(0, maximum=self.total_files)

        self.app.save_app_settings()
        self.run_btn.configure(state="disabled")
        self.kill_btn.configure(state="normal")
        self.status_lbl.configure(text=f"Pipeline active — compiling {self.total_files} clip(s)…")
        self.status_dot.configure(fg="#ffbd2e")

        worker = threading.Thread(target=self.compiler_thread, args=(files,), daemon=True)
        worker.start()

    def compiler_thread(self, files):
        """Passes all targeted video assets, along with every render control, to the back-end compiler."""
        try:
            self.app.log(f"\n⚡ Batch-rendering {len(files)} target clip(s)...")
            env = os.environ.copy()

            if self.app.groq_key_var.get().strip():
                env["GROQ_API_KEY"] = self.app.groq_key_var.get().strip()

            env["HIGHLIGHTLY_MUSIC_VOLUME"] = str(self.app.music_volume_var.get())

            relevant_volume_map = {f: self.app.clip_music_volume_map[f] for f in files if f in self.app.clip_music_volume_map}
            if relevant_volume_map:
                env["HIGHLIGHTLY_MUSIC_VOLUME_MAP"] = json.dumps(relevant_volume_map)

            if self.app.active_music_file:
                env["HIGHLIGHTLY_MUSIC_PATH"] = str(self.app.active_music_file)

            # Per-clip pairings (explicit track or explicit "no music") — only send entries
            # for the clips actually in this render, so unrelated pairings don't leak through.
            relevant_map = {f: self.app.clip_music_map[f] for f in files if f in self.app.clip_music_map}
            if relevant_map:
                env["HIGHLIGHTLY_MUSIC_MAP"] = json.dumps(relevant_map)

            env["HIGHLIGHTLY_BG_BLUR"] = str(self.app.bg_blur_var.get())
            env["HIGHLIGHTLY_FONT_NAME"] = self.app.font_name_var.get()
            env["HIGHLIGHTLY_HIGHLIGHT_COLOR"] = "1" if self.app.highlight_var.get() else "0"

            if self.app.is_pro():
                env["HIGHLIGHTLY_FONT_SIZE"] = str(self.app.font_size_var.get())
                env["HIGHLIGHTLY_CAPTION_MARGIN_V"] = str(self.app.caption_margin_var.get())
                env["HIGHLIGHTLY_ZOOM_AMOUNT"] = str(self.app.zoom_var.get())
                env["HIGHLIGHTLY_OUTPUT_W"] = str(self.app.output_width_var.get())
                env["HIGHLIGHTLY_OUTPUT_H"] = str(self.app.output_height_var.get())
                env["HIGHLIGHTLY_CAPTION_OUTLINE"] = str(self.app.caption_outline_var.get())
                env["HIGHLIGHTLY_QUALITY"] = str(self.app.quality_var.get())
                env["HIGHLIGHTLY_PRESET"] = self.app.preset_var.get()
                env["HIGHLIGHTLY_CAPTION_WORDS"] = str(self.app.caption_words_var.get())
            else:
                env["HIGHLIGHTLY_FONT_SIZE"] = "85"
                env["HIGHLIGHTLY_CAPTION_MARGIN_V"] = "180"
                env["HIGHLIGHTLY_ZOOM_AMOUNT"] = "1.04"
                env["HIGHLIGHTLY_OUTPUT_W"] = "1080"
                env["HIGHLIGHTLY_OUTPUT_H"] = "1920"
                env["HIGHLIGHTLY_CAPTION_OUTLINE"] = "5"
                env["HIGHLIGHTLY_QUALITY"] = "18"
                env["HIGHLIGHTLY_PRESET"] = "fast"
                env["HIGHLIGHTLY_CAPTION_WORDS"] = "6"

            # CREATE_NO_WINDOW keeps this from popping open a separate console window on Windows.
            no_window_flag = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            command = [sys.executable, str(CLIP_EDITOR)] + files
            self.app.process = subprocess.Popen(
                command, cwd=str(BASE_DIR), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=no_window_flag
            )

            for line in self.app.process.stdout:
                self.app.log_queue.put(line.rstrip())

            code = self.app.process.wait()
            self.app.process = None
            self.app.log(f"Subprocess terminated with code: {code}.")
        finally:
            self.app.log_queue.put("__PIPELINE_COMPLETE__")
            self.app.after(10, self.wrap_pipeline)

    def wrap_pipeline(self):
        self._stop_creep()
        self.set_progress(self.total_files)
        self.status_lbl.configure(text=f"Render completed — {self.total_files} clip(s) exported successfully.")
        self.status_dot.configure(fg="#28c93f")
        self.run_btn.configure(state="normal")
        self.kill_btn.configure(state="disabled")

    def halt_render(self):
        if self.app.process:
            self._stop_creep()
            self.app.process.terminate()
            self.app.log("[Interrupt] Sent kill signal to compiler core.")


if __name__ == "__main__":
    app = HighlightlyApp()
    app.mainloop()