import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib import error, request


APP_NAME = "Highlightly Desktop"
BASE_DIR = Path(__file__).resolve().parent
CLIP_EDITOR = BASE_DIR / "clip_editor.py"
INPUT_DIR = BASE_DIR / "input_clips"
OUTPUT_DIR = BASE_DIR / "edited_clips"
MUSIC_DIR = BASE_DIR / "music"
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
        url,
        data=payload,
        method="POST",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
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


def normalize_plan(plan):
    plan_text = (plan or "Free").lower()
    if "founder" in plan_text or "pro" in plan_text or "trial" in plan_text:
        return "Pro Trial" if "trial" in plan_text else "Pro"
    return "Free"


class HighlightlyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        read_website_supabase_config()
        ensure_dirs()
        self.config_data = load_config()
        self.account = self.config_data.get("account")
        self.selected_files = []
        self.process = None
        self.log_queue = queue.Queue()

        self.title(APP_NAME)
        self.geometry("1120x740")
        self.minsize(980, 660)
        self.configure(bg="#070806")

        self.email_var = tk.StringVar(value=self.config_data.get("last_email", ""))
        self.password_var = tk.StringVar()
        self.groq_key_var = tk.StringVar(value=self.config_data.get("groq_api_key", ""))
        self.music_volume_var = tk.DoubleVar(value=float(self.config_data.get("music_volume", 0.08)))
        self.font_size_var = tk.IntVar(value=int(self.config_data.get("font_size", 85)))
        self.caption_margin_var = tk.IntVar(value=int(self.config_data.get("caption_margin", 180)))
        self.zoom_var = tk.DoubleVar(value=float(self.config_data.get("zoom", 1.04)))
        self.output_width_var = tk.IntVar(value=int(self.config_data.get("output_width", 1080)))
        self.output_height_var = tk.IntVar(value=int(self.config_data.get("output_height", 1920)))

        self.build_styles()
        self.build_ui()
        self.apply_account_state()
        self.after(120, self.drain_log_queue)

    def build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#070806")
        style.configure("Panel.TFrame", background="#11130f", relief="flat")
        style.configure("TLabel", background="#070806", foreground="#f5f5ee")
        style.configure("Muted.TLabel", background="#070806", foreground="#9a9b90")
        style.configure("Panel.TLabel", background="#11130f", foreground="#f5f5ee")
        style.configure("PanelMuted.TLabel", background="#11130f", foreground="#9a9b90")
        style.configure("Accent.TButton", background="#c7ff45", foreground="#050505", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#dfff82")])
        style.configure("Dark.TButton", background="#1f221b", foreground="#f5f5ee", font=("Segoe UI", 10, "bold"))
        style.map("Dark.TButton", background=[("active", "#2c3026")])
        style.configure("TEntry", fieldbackground="#171914", foreground="#f5f5ee", insertcolor="#f5f5ee")
        style.configure("Horizontal.TScale", background="#11130f", troughcolor="#25291f")

    def build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(24, 18), style="TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        title = ttk.Label(header, text="Highlightly Desktop", font=("Segoe UI", 22, "bold"))
        title.grid(row=0, column=0, sticky="w")
        self.account_label = ttk.Label(header, text="Signed out", style="Muted.TLabel", font=("Segoe UI", 10, "bold"))
        self.account_label.grid(row=0, column=1, sticky="e", padx=(16, 0))

        body = ttk.Frame(self, padding=(24, 0, 24, 24), style="TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(body, padding=18, style="Panel.TFrame")
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 18))
        sidebar.columnconfigure(0, weight=1)

        ttk.Label(sidebar, text="Account", style="Panel.TLabel", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(sidebar, text="Sign in to unlock rendering.", style="PanelMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 14))

        ttk.Label(sidebar, text="Email", style="PanelMuted.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(sidebar, textvariable=self.email_var, width=32).grid(row=3, column=0, sticky="ew", pady=(4, 10))
        ttk.Label(sidebar, text="Password", style="PanelMuted.TLabel").grid(row=4, column=0, sticky="w")
        ttk.Entry(sidebar, textvariable=self.password_var, show="*", width=32).grid(row=5, column=0, sticky="ew", pady=(4, 12))
        ttk.Button(sidebar, text="Sign in", style="Accent.TButton", command=self.sign_in).grid(row=6, column=0, sticky="ew")
        ttk.Button(sidebar, text="Sign out", style="Dark.TButton", command=self.sign_out).grid(row=7, column=0, sticky="ew", pady=(8, 18))

        ttk.Label(sidebar, text="Groq API key", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(row=8, column=0, sticky="w")
        ttk.Label(sidebar, text="Optional. Saved locally only.", style="PanelMuted.TLabel").grid(row=9, column=0, sticky="w", pady=(2, 8))
        ttk.Entry(sidebar, textvariable=self.groq_key_var, show="*", width=32).grid(row=10, column=0, sticky="ew")
        ttk.Button(sidebar, text="Save app settings", style="Dark.TButton", command=self.save_app_settings).grid(row=11, column=0, sticky="ew", pady=(10, 18))

        ttk.Label(sidebar, text="Plan rules", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(row=12, column=0, sticky="w")
        self.plan_rules = ttk.Label(sidebar, text="", style="PanelMuted.TLabel", wraplength=260, justify="left")
        self.plan_rules.grid(row=13, column=0, sticky="w")

        main = ttk.Frame(body, style="TFrame")
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)

        clips_panel = ttk.Frame(main, padding=18, style="Panel.TFrame")
        clips_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 18))
        clips_panel.columnconfigure(0, weight=1)

        ttk.Label(clips_panel, text="Clips", style="Panel.TLabel", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(clips_panel, text="Add MP4, MOV, or MKV files.", style="PanelMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 12))
        self.file_list = tk.Listbox(clips_panel, height=8, bg="#171914", fg="#f5f5ee", selectbackground="#c7ff45", selectforeground="#050505", relief="flat")
        self.file_list.grid(row=2, column=0, sticky="nsew")
        clips_panel.rowconfigure(2, weight=1)
        row = ttk.Frame(clips_panel, style="Panel.TFrame")
        row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(row, text="Add clips", style="Accent.TButton", command=self.add_clips).pack(side="left")
        ttk.Button(row, text="Clear", style="Dark.TButton", command=self.clear_clips).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Open outputs", style="Dark.TButton", command=self.open_outputs).pack(side="right")

        settings_panel = ttk.Frame(main, padding=18, style="Panel.TFrame")
        settings_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 18))
        settings_panel.columnconfigure(0, weight=1)
        ttk.Label(settings_panel, text="Render settings", style="Panel.TLabel", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.add_slider(settings_panel, 1, "Music volume", self.music_volume_var, 0.0, 0.35, pro_only=False)
        self.add_slider(settings_panel, 2, "Caption font size", self.font_size_var, 48, 130, pro_only=True)
        self.add_slider(settings_panel, 3, "Caption top margin", self.caption_margin_var, 80, 420, pro_only=True)
        self.add_slider(settings_panel, 4, "Zoom amount", self.zoom_var, 1.0, 1.14, pro_only=True)

        output_row = ttk.Frame(settings_panel, style="Panel.TFrame")
        output_row.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        output_row.columnconfigure(1, weight=1)
        output_row.columnconfigure(3, weight=1)
        ttk.Label(output_row, text="Output W", style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.output_w_entry = ttk.Entry(output_row, textvariable=self.output_width_var, width=8)
        self.output_w_entry.grid(row=0, column=1, sticky="w", padx=(8, 18))
        ttk.Label(output_row, text="Output H", style="PanelMuted.TLabel").grid(row=0, column=2, sticky="w")
        self.output_h_entry = ttk.Entry(output_row, textvariable=self.output_height_var, width=8)
        self.output_h_entry.grid(row=0, column=3, sticky="w", padx=(8, 0))

        action_panel = ttk.Frame(main, padding=18, style="Panel.TFrame")
        action_panel.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        action_panel.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(action_panel, text="Ready.", style="PanelMuted.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(action_panel, text="Render selected clips", style="Accent.TButton", command=self.start_render)
        self.run_button.grid(row=0, column=1, sticky="e")
        ttk.Button(action_panel, text="Stop", style="Dark.TButton", command=self.stop_render).grid(row=0, column=2, sticky="e", padx=(8, 0))

        log_panel = ttk.Frame(main, padding=18, style="Panel.TFrame")
        log_panel.grid(row=2, column=0, columnspan=2, sticky="nsew")
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        ttk.Label(log_panel, text="Pipeline log", style="Panel.TLabel", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.log_text = tk.Text(log_panel, height=12, bg="#080907", fg="#e8e8df", insertbackground="#e8e8df", relief="flat", wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")

    def add_slider(self, parent, row, label, variable, from_, to, pro_only):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        frame.columnconfigure(0, weight=1)
        text = label + ("  Pro" if pro_only else "")
        ttk.Label(frame, text=text, style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        value = ttk.Label(frame, text="", style="PanelMuted.TLabel")
        value.grid(row=0, column=1, sticky="e")
        scale = ttk.Scale(frame, from_=from_, to=to, variable=variable, orient="horizontal", command=lambda _=None: self.update_slider_value(value, variable))
        scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        value.pro_only = pro_only
        scale.pro_only = pro_only
        self.update_slider_value(value, variable)

    def update_slider_value(self, label, variable):
        value = variable.get()
        if isinstance(value, float):
            label.configure(text=f"{value:.2f}")
        else:
            label.configure(text=str(value))

    def plan(self):
        if not self.account:
            return None
        return normalize_plan(self.account.get("plan"))

    def is_pro(self):
        return self.plan() in {"Pro", "Pro Trial"}

    def apply_account_state(self):
        if self.account:
            self.account_label.configure(text=f"{self.account.get('email')} - {self.account.get('plan', 'Free')}")
        else:
            self.account_label.configure(text="Signed out")
        if self.is_pro():
            self.plan_rules.configure(text="Pro: batch clips, all sliders, custom resolution, Groq cloud key, music controls.")
            self.run_button.configure(text="Render selected clips")
        else:
            self.plan_rules.configure(text="Free: one clip at a time, standard 1080x1920 output, basic music volume. Pro unlocks batch rendering and advanced caption controls.")
            self.run_button.configure(text="Render one clip")

        state = "normal" if self.is_pro() else "disabled"
        self.output_w_entry.configure(state=state)
        self.output_h_entry.configure(state=state)

    def sign_in(self):
        email = self.email_var.get().strip().lower()
        password = self.password_var.get()
        if email == ADMIN_LOGIN["email"] and password == ADMIN_LOGIN["password"]:
            self.account = {"email": "admin", "plan": ADMIN_LOGIN["plan"]}
            self.save_app_settings()
            self.apply_account_state()
            self.log("Signed in as admin with Pro Trial.")
            return
        if not email or not password:
            messagebox.showerror(APP_NAME, "Enter your email and password.")
            return
        try:
            self.account = supabase_password_login(email, password)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.save_app_settings()
        self.apply_account_state()
        self.log(f"Signed in as {self.account['email']} with {self.account['plan']} access.")

    def sign_out(self):
        self.account = None
        self.config_data.pop("account", None)
        save_config(self.config_data)
        self.apply_account_state()
        self.log("Signed out.")

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
        })
        if self.account:
            self.config_data["account"] = self.account
        save_config(self.config_data)
        self.log("App settings saved locally.")

    def add_clips(self):
        files = filedialog.askopenfilenames(
            title="Choose gameplay clips",
            filetypes=[("Video clips", "*.mp4 *.mov *.mkv"), ("All files", "*.*")]
        )
        for file in files:
            if file and file not in self.selected_files:
                self.selected_files.append(file)
                self.file_list.insert("end", file)

    def clear_clips(self):
        self.selected_files.clear()
        self.file_list.delete(0, "end")

    def open_outputs(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        os.startfile(str(OUTPUT_DIR))

    def start_render(self):
        if not self.account:
            messagebox.showerror(APP_NAME, "Sign in before rendering.")
            return
        if self.process:
            messagebox.showinfo(APP_NAME, "A render is already running.")
            return
        if not CLIP_EDITOR.exists():
            messagebox.showerror(APP_NAME, f"Missing clip_editor.py at {CLIP_EDITOR}")
            return
        if not self.selected_files:
            messagebox.showerror(APP_NAME, "Add at least one clip first.")
            return

        files = list(self.selected_files)
        if not self.is_pro() and len(files) > 1:
            files = files[:1]
            self.log("Free plan: rendering only the first selected clip.")

        self.save_app_settings()
        self.run_button.configure(state="disabled")
        self.status_label.configure(text="Rendering...")
        worker = threading.Thread(target=self.render_worker, args=(files,), daemon=True)
        worker.start()

    def render_worker(self, files):
        try:
            for index, file in enumerate(files, start=1):
                self.log_queue.put(f"\n[{index}/{len(files)}] Rendering {Path(file).name}")
                env = os.environ.copy()
                if self.groq_key_var.get().strip():
                    env["GROQ_API_KEY"] = self.groq_key_var.get().strip()
                env["HIGHLIGHTLY_MUSIC_VOLUME"] = str(self.music_volume_var.get())
                if self.is_pro():
                    env["HIGHLIGHTLY_FONT_SIZE"] = str(self.font_size_var.get())
                    env["HIGHLIGHTLY_CAPTION_MARGIN_V"] = str(self.caption_margin_var.get())
                    env["HIGHLIGHTLY_ZOOM_AMOUNT"] = str(self.zoom_var.get())
                    env["HIGHLIGHTLY_OUTPUT_W"] = str(self.output_width_var.get())
                    env["HIGHLIGHTLY_OUTPUT_H"] = str(self.output_height_var.get())
                else:
                    env["HIGHLIGHTLY_FONT_SIZE"] = "85"
                    env["HIGHLIGHTLY_CAPTION_MARGIN_V"] = "180"
                    env["HIGHLIGHTLY_ZOOM_AMOUNT"] = "1.04"
                    env["HIGHLIGHTLY_OUTPUT_W"] = "1080"
                    env["HIGHLIGHTLY_OUTPUT_H"] = "1920"

                command = [sys.executable, str(CLIP_EDITOR), str(file)]
                self.process = subprocess.Popen(
                    command,
                    cwd=str(BASE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                for line in self.process.stdout:
                    self.log_queue.put(line.rstrip())
                code = self.process.wait()
                self.process = None
                self.log_queue.put("Finished." if code == 0 else f"Exited with code {code}.")
        finally:
            self.log_queue.put("__DONE__")

    def stop_render(self):
        if self.process:
            self.process.terminate()
            self.log("Stopping render...")

    def drain_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == "__DONE__":
                    self.run_button.configure(state="normal")
                    self.status_label.configure(text="Ready.")
                    self.process = None
                else:
                    self.log(item)
        except queue.Empty:
            pass
        self.after(120, self.drain_log_queue)

    def log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")


if __name__ == "__main__":
    app = HighlightlyApp()
    app.mainloop()
