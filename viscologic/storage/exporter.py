"""
viscologic/storage/exporter.py
------------------------------
Handles exporting logs and data to external storage (USB or Desktop).
"""
import os
import shutil
import time
import zipfile
import platform
from typing import Optional

def get_export_path() -> str:
    """
    Determine where to save the export.
    On Windows: User's Desktop.
    On Linux: Look for /media/usb or similar, else fallback to home dir.
    """
    sys_plat = platform.system().lower()
    
    if "windows" in sys_plat:
        # Desktop
        return os.path.join(os.path.expanduser("~"), "Desktop")
    elif "linux" in sys_plat:
        # Try common mount points
        candidates = ["/media/usb", "/mnt/usb", "/media/pi"]
        for c in candidates:
            if os.path.exists(c) and os.path.isdir(c):
                # check if writable
                if os.access(c, os.W_OK):
                    return c
        # Fallback to home
        return os.path.expanduser("~")
    
    return os.getcwd()

def perform_export(source_dir: str, prefix: str = "viscologic_logs") -> str:
    """
    Zips the source_dir and places it in the export path.
    Returns the full path of the created file.
    """
    if not os.path.exists(source_dir):
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.zip"
    dest_dir = get_export_path()
    dest_path = os.path.join(dest_dir, filename)

    # Create zip
    with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                # preserve relative path inside zip
                arcname = os.path.relpath(file_path, start=os.path.dirname(source_dir))
                zipf.write(file_path, arcname)
    
    return dest_path
