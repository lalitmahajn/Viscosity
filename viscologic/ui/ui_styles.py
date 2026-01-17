# viscologic/ui/ui_styles.py
# Shared UI styling constants and helpers for consistent look across all screens

from typing import Dict, Any, Tuple

# Color scheme
COLORS = {
    "primary": "#2c3e50",      # Dark blue-gray
    "secondary": "#34495e",     # Medium gray
    "accent": "#3498db",        # Blue
    "success": "#27ae60",       # Green
    "warning": "#f39c12",       # Orange
    "danger": "#e74c3c",        # Red
    "info": "#3498db",          # Blue
    "bg_light": "#ecf0f1",      # Light gray background
    "bg_card": "#ffffff",       # White card background
    "text_primary": "#2c3e50",  # Dark text
    "text_secondary": "#7f8c8d", # Gray text
    "border": "#bdc3c7",        # Light border
}

# Font sizes
FONTS = {
    "title": ("Segoe UI", 16, "bold"),
    "subtitle": ("Segoe UI", 14, "bold"),
    "heading": ("Segoe UI", 12, "bold"),
    "body": ("Segoe UI", 10),
    "body_bold": ("Segoe UI", 10, "bold"),
    "large": ("Segoe UI", 32, "bold"),
    "medium": ("Segoe UI", 22, "bold"),
    "small": ("Segoe UI", 9),
}

# Padding constants
PADDING = {
    "small": 4,
    "medium": 8,
    "large": 12,
    "xlarge": 16,
}

# Card style helper
def create_card_style() -> Dict[str, Any]:
    """Returns style dict for card frames"""
    return {
        "padding": PADDING["large"],
        "relief": "flat",
    }

# Status color helper
def get_status_color(status: str) -> str:
    """Returns color based on status string"""
    status_lower = str(status).lower()
    if "locked" in status_lower or "running" in status_lower or "ok" in status_lower:
        return COLORS["success"]
    elif "searching" in status_lower or "sweeping" in status_lower:
        return COLORS["warning"]
    elif "fault" in status_lower or "error" in status_lower or "alarm" in status_lower:
        return COLORS["danger"]
    elif "idle" in status_lower or "paused" in status_lower:
        return COLORS["text_secondary"]
    return COLORS["text_primary"]

# Health score color helper
def get_health_color(health: float) -> str:
    """Returns color based on health score (0-100)"""
    if health >= 80:
        return COLORS["success"]
    elif health >= 60:
        return COLORS["warning"]
    else:
        return COLORS["danger"]

