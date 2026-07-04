import sys
import subprocess
import shutil  # Added for moving user background music files
import filecmp

# ─── COMMERCIAL CLIENT-SIDE DEPENDENCY HOOK ───
def install_client_dependencies():
    required_packages = {
        "cv2": "opencv-pytho