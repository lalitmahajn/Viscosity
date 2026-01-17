# viscologic/ui/theme.py
# Global Industrial HMI Theme Configuration
# Professional, modern look with consistent colors and styles

from tkinter import ttk
from typing import Any


def apply_theme(root: Any) -> None:
    """
    Apply professional Industrial HMI theme to the Tkinter application.
    Sets up ttk.Style with consistent colors and styles across all screens.
    
    Args:
        root: The tk.Tk() root window instance
    """
    style = ttk.Style()
    style.theme_use('clam')
    
    # ========== Color Palette ==========
    BG_MAIN = "#ECF0F1"      # Light Gray - Main background
    BG_HEADER = "#2C3E50"    # Dark Slate Blue - Headers
    BG_CARD = "#FFFFFF"      # White - Cards
    TEXT_PRIMARY = "#2C3E50" # Dark Charcoal - Primary text
    ACCENT_GREEN = "#27AE60" # Green - Start/Action buttons
    ACCENT_RED = "#C0392B"   # Red - Stop/Danger buttons
    TEXT_WHITE = "#FFFFFF"   # White - Text on dark backgrounds
    TEXT_SECONDARY = "#7F8C8D" # Gray - Secondary text
    
    # ========== Base Widget Styles ==========
    
    # Main frame - light gray background
    style.configure("TFrame", background=BG_MAIN)
    style.configure("TLabel", background=BG_MAIN, foreground=TEXT_PRIMARY)
    style.configure("TButton", background="#D5DBDB", foreground=TEXT_PRIMARY)
    style.map("TButton", 
              background=[("active", "#BDC3C7"), ("pressed", "#A6ACAF")])
    
    # Entry and Combobox - white backgrounds
    style.configure("TEntry", background=BG_CARD, fieldbackground=BG_CARD, 
                   foreground=TEXT_PRIMARY, borderwidth=1)
    style.configure("TCombobox", background=BG_CARD, fieldbackground=BG_CARD,
                   foreground=TEXT_PRIMARY)
    style.map("TCombobox", 
              fieldbackground=[("readonly", BG_CARD)],
              background=[("readonly", BG_CARD)])
    
    # Notebook (tabs)
    style.configure("TNotebook", background=BG_MAIN)
    style.configure("TNotebook.Tab", background="#BDC3C7", padding=[12, 6],
                  foreground=TEXT_PRIMARY)
    style.map("TNotebook.Tab",
              background=[("selected", BG_MAIN)],
              expand=[("selected", [1, 1, 1, 0])])
    
    # Progressbar
    style.configure("TProgressbar", background=ACCENT_GREEN, 
                   troughcolor=BG_MAIN, borderwidth=0, lightcolor=ACCENT_GREEN,
                   darkcolor=ACCENT_GREEN)
    
    # ========== Card Styles ==========
    
    # Card frame - white background, no border
    style.configure("Card.TFrame", 
                   background=BG_CARD, 
                   relief="flat", 
                   borderwidth=0)
    
    # Labels inside cards - white background, dark text
    style.configure("Card.TLabel",
                   background=BG_CARD,
                   foreground=TEXT_PRIMARY,
                   font=("Segoe UI", 10))
    
    # Large value labels (for sensor readings)
    style.configure("Value.TLabel",
                   background=BG_CARD,
                   foreground=TEXT_PRIMARY,
                   font=("Segoe UI", 24, "bold"))
    
    # Medium value labels
    style.configure("ValueMedium.TLabel",
                   background=BG_CARD,
                   foreground=TEXT_PRIMARY,
                   font=("Segoe UI", 18, "bold"))
    
    # Small value labels
    style.configure("ValueSmall.TLabel",
                   background=BG_CARD,
                   foreground=TEXT_PRIMARY,
                   font=("Segoe UI", 14, "bold"))
    
    # Secondary text in cards
    style.configure("CardSecondary.TLabel",
                   background=BG_CARD,
                   foreground=TEXT_SECONDARY,
                   font=("Segoe UI", 9))
    
    # ========== Header Styles ==========
    
    # Header frame - dark blue background
    style.configure("Header.TFrame",
                   background=BG_HEADER,
                   relief="flat",
                   borderwidth=0)
    
    # Header labels - white text on dark blue
    style.configure("Header.TLabel",
                   background=BG_HEADER,
                   foreground=TEXT_WHITE,
                   font=("Segoe UI", 12, "bold"))
    
    # Header title (larger)
    style.configure("HeaderTitle.TLabel",
                   background=BG_HEADER,
                   foreground=TEXT_WHITE,
                   font=("Segoe UI", 14, "bold"))
    
    # ========== Button Styles ==========
    
    # Green action buttons (Start, Enable, Save, etc.)
    style.configure("Green.TButton",
                   background=ACCENT_GREEN,
                   foreground=TEXT_WHITE,
                   borderwidth=0,
                   padding=[10, 5],
                   font=("Segoe UI", 10, "bold"))
    style.map("Green.TButton",
              background=[("active", "#229954"), ("pressed", "#1E8449")])
    
    # Red danger buttons (Stop, Abort, Cancel, etc.)
    style.configure("Red.TButton",
                   background=ACCENT_RED,
                   foreground=TEXT_WHITE,
                   borderwidth=0,
                   padding=[10, 5],
                   font=("Segoe UI", 10, "bold"))
    style.map("Red.TButton",
              background=[("active", "#A93226"), ("pressed", "#922B21")])
    
    # Blue info buttons
    style.configure("Blue.TButton",
                   background="#3498DB",
                   foreground=TEXT_WHITE,
                   borderwidth=0,
                   padding=[10, 5],
                   font=("Segoe UI", 10))
    style.map("Blue.TButton",
              background=[("active", "#2980B9"), ("pressed", "#21618C")])
    
    # ========== Status Bar Styles ==========
    
    style.configure("StatusBar.TFrame",
                   background="#D5DBDB",
                   relief="flat",
                   borderwidth=0)
    style.configure("StatusBar.TLabel",
                   background="#D5DBDB",
                   foreground=TEXT_PRIMARY)
    
    # ========== Special Widget Styles ==========
    
    # Health progressbar (dynamic color)
    style.configure("Health.TProgressbar",
                   troughcolor=BG_CARD,
                   borderwidth=0,
                   lightcolor=ACCENT_GREEN,
                   darkcolor=ACCENT_GREEN)
    
    # Listbox (for alarms, etc.)
    try:
        root.option_add("*Listbox.background", BG_CARD)
        root.option_add("*Listbox.foreground", TEXT_PRIMARY)
        root.option_add("*Listbox.selectBackground", ACCENT_GREEN)
        root.option_add("*Listbox.selectForeground", TEXT_WHITE)
    except Exception:
        pass
    
    # Treeview (for tables)
    style.configure("Treeview",
                   background=BG_CARD,
                   foreground=TEXT_PRIMARY,
                   fieldbackground=BG_CARD,
                   borderwidth=1)
    style.configure("Treeview.Heading",
                   background="#BDC3C7",
                   foreground=TEXT_PRIMARY,
                   font=("Segoe UI", 10, "bold"),
                   relief="flat")
    style.map("Treeview",
              background=[("selected", ACCENT_GREEN)],
              foreground=[("selected", TEXT_WHITE)])
    
    # Set root window background
    root.configure(bg=BG_MAIN)

