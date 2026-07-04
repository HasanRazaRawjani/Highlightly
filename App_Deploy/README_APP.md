# Highlightly Desktop App

Run:

```bat
Launch Highlightly App.bat
```

The app runs the live `clip_editor.py` file from this same folder. If you edit `clip_editor.py`, the app uses the edited version the next time it renders.

## Login

- Real users can sign in with their Supabase email and password.
- Test admin login:

```txt
Email: admin
Password: admin
Plan: Pro Trial
```

## Free vs Pro

Free:

- One clip at a time
- Standard 1080x1920 output
- Basic music volume slider

Pro / Pro Trial:

- Batch clip rendering
- Caption font size slider
- Caption top margin slider
- Zoom slider
- Custom output width and height
- Optional Groq API key field

## Groq API key

Paste your Groq key into the app and click **Save app settings**. It is saved locally in:

```txt
_temp/highlightly_app_config.json
```

The app passes it into `clip_editor.py` as `GROQ_API_KEY` while rendering.

You can still use a terminal environment variable instead:

```bat
set GROQ_API_KEY=gsk_your_key_here
```

## Outputs

Rendered clips go to:

```txt
edited_clips/
```

## Requirements

Install the existing pipeline requirements:

```bat
pip install openai openai-whisper numpy scipy requests
```

FFmpeg and FFprobe must be installed and available on PATH.
