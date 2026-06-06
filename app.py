from __future__ import annotations

import ctypes
import json
import math
import sys
import tkinter as tk
import traceback
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    BOTTOM,
    BOTH,
    LEFT,
    RIGHT,
    DoubleVar,
    Frame,
    IntVar,
    Label,
    StringVar,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
)

from gerbonara.rs274x import GerberFile
from gerbonara.utils import MM
from PIL import Image, ImageChops, ImageDraw, ImageTk

THEMES = {
    "light": {
        "app_bg": "#f3f3f3",
        "panel_bg": "#fbfbfb",
        "preview_bg": "#181818",
        "text": "#1f1f1f",
        "muted": "#555555",
        "about_bg": "#ffffff",
        "border": "#d8d8d8",
        "control_bg": "#ffffff",
        "hover_bg": "#e9e9e9",
        "pressed_bg": "#dddddd",
        "accent": "#0078d4",
    },
    "dark": {
        "app_bg": "#202020",
        "panel_bg": "#272727",
        "preview_bg": "#101010",
        "text": "#f2f2f2",
        "muted": "#b8b8b8",
        "about_bg": "#242424",
        "border": "#3a3a3a",
        "control_bg": "#303030",
        "hover_bg": "#3b3b3b",
        "pressed_bg": "#454545",
        "accent": "#60cdff",
    },
}

CHANNELS = {
    "soldermask": "Soldermask",
    "paste": "Paste",
    "legend": "Legend / Silkscreen",
    "signal": "Signal",
}
CHANNEL_LETTERS = "RGBA"
DEFAULT_CHANNEL_MAP = {
    "soldermask": 0,
    "paste": 1,
    "legend": 2,
    "signal": 3,
}
DEFAULT_PREVIEW_COLORS = {
    "soldermask": "#ff5b5b",
    "paste": "#55d66b",
    "legend": "#5b8cff",
    "signal": "#d9d9d9",
}
PREFERENCES_PATH = Path.home() / "PCBExtractor" / "preferences.json"

MAX_PIXELS = 150_000_000
MAX_SIDE = 20_000


def rgb_to_colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def windows_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return apps_use_light_theme == 0
    except Exception:
        return False


def load_preferences() -> dict[str, object]:
    prefs = {
        "dark_mode": windows_prefers_dark(),
        "channel_map": DEFAULT_CHANNEL_MAP.copy(),
    }
    if not PREFERENCES_PATH.exists():
        return prefs

    try:
        raw = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return prefs

    if isinstance(raw.get("dark_mode"), bool):
        prefs["dark_mode"] = raw["dark_mode"]

    raw_channel_map = raw.get("channel_map", {})
    if isinstance(raw_channel_map, dict):
        channel_map = prefs["channel_map"].copy()
        for key in CHANNELS:
            value = raw_channel_map.get(key)
            if isinstance(value, str) and value.upper() in CHANNEL_LETTERS:
                channel_map[key] = CHANNEL_LETTERS.index(value.upper())
            elif isinstance(value, int) and 0 <= value < len(CHANNEL_LETTERS):
                channel_map[key] = value
        prefs["channel_map"] = channel_map

    return prefs


def save_preferences(prefs: dict[str, object]):
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def apply_windows_11_mica(root: Tk, dark_mode: bool) -> bool:
    if sys.platform != "win32":
        return False

    try:
        if sys.getwindowsversion().build < 22000:
            return False

        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()

        dark = ctypes.c_int(1 if dark_mode else 0)
        caption_color = ctypes.c_int(rgb_to_colorref("#202020" if dark_mode else "#f3f3f3"))
        text_color = ctypes.c_int(rgb_to_colorref("#ffffff" if dark_mode else "#202020"))
        border_color = ctypes.c_int(rgb_to_colorref("#3a3a3a" if dark_mode else "#d0d0d0"))

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_BORDER_COLOR = 34
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMWCP_ROUND = 2
        DWMSBT_MAINWINDOW = 2

        for dark_attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                dark_attr,
                ctypes.byref(dark),
                ctypes.sizeof(ctypes.c_int),
            )
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
            ctypes.sizeof(ctypes.c_int),
        )
        for attr, color in (
            (DWMWA_BORDER_COLOR, border_color),
            (DWMWA_CAPTION_COLOR, caption_color),
            (DWMWA_TEXT_COLOR, text_color),
        ):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                attr,
                ctypes.byref(color),
                ctypes.sizeof(ctypes.c_int),
            )
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(ctypes.c_int(DWMSBT_MAINWINDOW)),
            ctypes.sizeof(ctypes.c_int),
        )
        return result == 0
    except Exception:
        return False


@dataclass
class LoadedLayer:
    path: Path
    gerber: GerberFile


class AppPopupMenu:
    def __init__(self, root: Tk, colors: dict[str, str]):
        self.root = root
        self.colors = colors
        self.items: list[dict[str, object]] = []
        self.window: Toplevel | None = None

    def add_command(self, label: str, command, accelerator: str | None = None):
        self.items.append(
            {
                "kind": "command",
                "label": label,
                "command": command,
                "accelerator": accelerator or "",
                "label_widget": None,
                "accelerator_widget": None,
            }
        )

    def add_separator(self):
        self.items.append({"kind": "separator"})

    def entryconfigure(self, index: int, label: str):
        item = self.items[index]
        item["label"] = label
        label_widget = item.get("label_widget")
        if label_widget is not None and label_widget.winfo_exists():
            label_widget.configure(text=label)

    def popup(self, x: int, y: int):
        self.close()
        window = Toplevel(self.root)
        self.window = window
        window.overrideredirect(True)
        window.configure(bg=self.colors["border"])
        window.attributes("-topmost", True)

        surface = Frame(window, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        surface.pack(fill=BOTH, expand=True, padx=1, pady=1)

        for item in self.items:
            if item["kind"] == "separator":
                separator = Frame(surface, bg=self.colors["border"], height=1, bd=0, highlightthickness=0)
                separator.pack(fill="x", padx=8, pady=4)
                continue

            row = Frame(surface, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
            row.pack(fill="x", padx=2, pady=1)
            row.columnconfigure(0, weight=1)

            label = Label(
                row,
                text=str(item["label"]),
                bg=self.colors["panel_bg"],
                fg=self.colors["text"],
                font=("Segoe UI", 9),
                anchor="w",
                padx=12,
                pady=5,
                bd=0,
                highlightthickness=0,
            )
            label.grid(row=0, column=0, sticky="ew")
            accelerator = Label(
                row,
                text=str(item["accelerator"]),
                bg=self.colors["panel_bg"],
                fg=self.colors["muted"],
                font=("Segoe UI", 9),
                anchor="e",
                padx=12,
                pady=5,
                bd=0,
                highlightthickness=0,
            )
            accelerator.grid(row=0, column=1, sticky="e")
            item["label_widget"] = label
            item["accelerator_widget"] = accelerator

            def set_row_bg(color: str, widgets=(row, label, accelerator)):
                for widget in widgets:
                    widget.configure(bg=color)

            def run_command(_event=None, command=item["command"]):
                self.close()
                command()

            for widget in (row, label, accelerator):
                widget.bind("<Enter>", lambda _event, setter=set_row_bg: setter(self.colors["hover_bg"]))
                widget.bind("<Leave>", lambda _event, setter=set_row_bg: setter(self.colors["panel_bg"]))
                widget.bind("<Button-1>", run_command)

        window.bind("<Escape>", lambda _event: self.close())
        window.bind("<FocusOut>", lambda _event: self.close())
        window.geometry(f"+{x}+{y}")
        window.update_idletasks()
        window.focus_force()

    def close(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        for item in self.items:
            if item.get("kind") == "command":
                item["label_widget"] = None
                item["accelerator_widget"] = None


def union_bounds(bounds: list[tuple[tuple[float, float], tuple[float, float]]]):
    min_x = min(box[0][0] for box in bounds)
    min_y = min(box[0][1] for box in bounds)
    max_x = max(box[1][0] for box in bounds)
    max_y = max(box[1][1] for box in bounds)
    return (min_x, min_y), (max_x, max_y)


def padded_bounds(bounds, margin_mm: float):
    (min_x, min_y), (max_x, max_y) = bounds
    return (min_x - margin_mm, min_y - margin_mm), (max_x + margin_mm, max_y + margin_mm)


def rasterize_layer(gerber: GerberFile, bounds, pixels_per_mm: float, invert: bool) -> Image.Image:
    (min_x, min_y), (max_x, max_y) = bounds
    width = max(1, math.ceil((max_x - min_x) * pixels_per_mm))
    height = max(1, math.ceil((max_y - min_y) * pixels_per_mm))
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    def tx(point):
        x, y = point
        return ((x - min_x) * pixels_per_mm, (max_y - y) * pixels_per_mm)

    max_error_mm = max(0.002, 0.35 / pixels_per_mm)

    for obj in gerber.objects:
        for primitive in obj.to_primitives(unit=MM):
            if primitive.is_zero_size():
                continue

            try:
                arc_poly = primitive.to_arc_poly().approximate_arcs(max_error=max_error_mm)
            except (ZeroDivisionError, ValueError):
                # Some exported Gerbers contain zero-radius arc fragments. They
                # have no drawable area as masks, so skipping is safer than
                # failing the whole layer import.
                continue

            points = [tx(point) for point in arc_poly.outline]
            if len(points) >= 3:
                fill = 255 if arc_poly.polarity_dark else 0
                draw.polygon(points, fill=fill)

    if invert:
        mask = ImageChops.invert(mask)
    return mask


def packed_image(
    layers: dict[str, LoadedLayer],
    visibility: dict[str, bool],
    inversion: dict[str, bool],
    channel_map: dict[str, int],
    pixels_per_mm: float,
    margin_mm: float,
    include_hidden: bool,
) -> tuple[Image.Image, dict[str, Image.Image], tuple[tuple[float, float], tuple[float, float]]]:
    active = [
        layer.gerber.bounding_box(unit=MM, default=None)
        for key, layer in layers.items()
        if include_hidden or visibility[key]
    ]
    active = [box for box in active if box is not None]
    if not active:
        if layers:
            raise ValueError("Show at least one layer, or enable export of hidden layers.")
        raise ValueError("Load at least one Gerber layer first.")

    bounds = padded_bounds(union_bounds(active), margin_mm)
    masks: dict[str, Image.Image] = {}

    (min_x, min_y), (max_x, max_y) = bounds
    width = max(1, math.ceil((max_x - min_x) * pixels_per_mm))
    height = max(1, math.ceil((max_y - min_y) * pixels_per_mm))
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        raise ValueError(
            f"Requested output is too large ({width} x {height}px). "
            "Lower Pixels / mm or reduce the margin."
        )
    blank = Image.new("L", (width, height), 0)

    for key in CHANNELS:
        if key in layers and (include_hidden or visibility[key]):
            masks[key] = rasterize_layer(layers[key].gerber, bounds, pixels_per_mm, inversion[key])
        else:
            masks[key] = blank.copy()

    output_masks = [blank.copy() for _letter in CHANNEL_LETTERS]
    for key, channel in channel_map.items():
        if key in masks and 0 <= channel < len(output_masks):
            output_masks[channel] = masks[key]

    rgba = Image.merge(
        "RGBA",
        tuple(output_masks),
    )
    return rgba, masks, bounds


def preview_image(
    masks: dict[str, Image.Image],
    visibility: dict[str, bool],
    preview_colors: dict[str, str],
) -> Image.Image:
    size = next(iter(masks.values())).size
    preview = Image.new("RGB", size, (24, 24, 24))

    for key in CHANNELS:
        if not visibility[key]:
            continue
        color = preview_colors[key]
        layer = Image.new("RGB", size, color)
        alpha = masks[key].point(lambda value: int(value * 0.72))
        preview = Image.composite(layer, preview, alpha)

    return preview


class PCBExtractorApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("PCB Layer Extractor")
        self.root.minsize(1000, 680)
        self.preferences = load_preferences()
        self.dark_mode = bool(self.preferences["dark_mode"])
        self.channel_map: dict[str, int] = dict(self.preferences["channel_map"])
        self.preview_colors: dict[str, str] = DEFAULT_PREVIEW_COLORS.copy()
        self.colors = THEMES["dark" if self.dark_mode else "light"]
        self.root.configure(bg=self.colors["app_bg"])

        self.layers: dict[str, LoadedLayer] = {}
        self.visible = {key: IntVar(value=1) for key in CHANNELS}
        self.inverted = {key: IntVar(value=0) for key in CHANNELS}
        self.path_text = {key: StringVar(value="No file loaded") for key in CHANNELS}
        self.pixels_per_mm = DoubleVar(value=40.0)
        self.margin_mm = DoubleVar(value=0.25)
        self.include_hidden_export = IntVar(value=1)
        self.status = StringVar(value="Import Gerber files to begin.")
        self.image_ref = None
        self.last_rgba: Image.Image | None = None
        self.last_masks: dict[str, Image.Image] | None = None
        self.edit_menu: AppPopupMenu | None = None
        self.layer_swatches: dict[str, Frame] = {}
        self.layer_titles: dict[str, Label] = {}

        self.build_ui()
        self.build_shortcuts()
        self.root.after(100, self.enable_mica)

    def enable_mica(self):
        apply_windows_11_mica(self.root, self.dark_mode)

    def build_command_bar(self, parent):
        bar = Frame(
            parent,
            bg=self.colors["app_bg"],
            bd=0,
            highlightthickness=0,
        )
        bar.pack(fill="x", padx=(0, 0), pady=(0, 10))

        file_menu = AppPopupMenu(self.root, self.colors)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Alt+F4", command=self.root.destroy)
        self.add_menu_button(bar, "File", file_menu)

        self.edit_menu = AppPopupMenu(self.root, self.colors)
        for key, label in CHANNELS.items():
            self.edit_menu.add_command(
                label=f"Hide {label}",
                command=lambda k=key: self.toggle_layer_visibility(k),
            )
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Preferences", command=self.show_preferences)
        self.add_menu_button(bar, "Edit", self.edit_menu)

        help_menu = AppPopupMenu(self.root, self.colors)
        help_menu.add_command(label="About", command=self.show_about)
        self.add_menu_button(bar, "Help", help_menu)

    def add_menu_button(self, parent, text: str, menu):
        button = Label(
            parent,
            text=text,
            bg=self.colors["app_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            padx=10,
            pady=5,
            bd=0,
            highlightthickness=0,
        )
        button.pack(side=LEFT)

        def show_menu(_event=None):
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            menu.popup(x, y)

        button.bind("<Button-1>", show_menu)
        button.bind("<Enter>", lambda _event: button.configure(bg=self.colors["hover_bg"]))
        button.bind("<Leave>", lambda _event: button.configure(bg=self.colors["app_bg"]))

    def build_shortcuts(self):
        self.root.bind_all("<Control-n>", lambda _event: self.new_project())

    def new_project(self):
        self.layers.clear()
        for key in CHANNELS:
            self.visible[key].set(1)
            self.inverted[key].set(0)
            self.path_text[key].set("No file loaded")
        self.last_rgba = None
        self.last_masks = None
        self.image_ref = None
        self.preview_label.configure(image="", text="No preview yet")
        self.status.set("New project ready. Import Gerber files to begin.")
        self.refresh_edit_menu()

    def toggle_layer_visibility(self, key: str):
        self.visible[key].set(0 if self.visible[key].get() else 1)
        self.refresh_edit_menu()
        self.schedule_render()

    def refresh_edit_menu(self):
        if self.edit_menu is None:
            return
        for index, (key, label) in enumerate(CHANNELS.items()):
            action = "Hide" if self.visible[key].get() else "Show"
            self.edit_menu.entryconfigure(index, label=f"{action} {label}")

    def show_about(self):
        about = Toplevel(self.root)
        about.title("About PCB Layer Extractor")
        about.transient(self.root)
        about.resizable(False, False)
        about.configure(bg=self.colors["about_bg"])
        about.grab_set()

        container = Frame(about, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
        container.pack(fill=BOTH, expand=True, padx=24, pady=22)

        Label(
            container,
            text="PCB Layer Extractor",
            font=("Segoe UI", 18, "bold"),
            bg=self.colors["about_bg"],
            fg=self.colors["text"],
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w")
        Label(
            container,
            text="Version 1.0.0 (Beta)",
            font=("Segoe UI", 10),
            bg=self.colors["about_bg"],
            fg=self.colors["muted"],
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(2, 14))

        Label(
            container,
            text="Made by Alexander Bugar",
            font=("Segoe UI", 10, "bold"),
            bg=self.colors["about_bg"],
            fg=self.colors["text"],
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(0, 14))

        body = (
            "MIT License\n\n"
            "Copyright (c) 2026 Alexander Bugar\n\n"
            "Permission is granted to use, copy, modify, merge, publish, distribute, sublicense, "
            "and/or sell copies of this software, subject to inclusion of the MIT license notice.\n\n"
            "This software is provided as-is, without warranty of any kind.\n\n"
            "Packages used: Python Tkinter, Gerbonara, Pillow."
        )
        Label(
            container,
            text=body,
            justify=LEFT,
            wraplength=460,
            bg=self.colors["about_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w")

        self.flat_button(container, "OK", about.destroy, width=80).pack(anchor="e", pady=(18, 0))

        about.update_idletasks()
        apply_windows_11_mica(about, self.dark_mode)
        x = self.root.winfo_x() + (self.root.winfo_width() - about.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - about.winfo_height()) // 2
        about.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def show_preferences(self):
        prefs_window = Toplevel(self.root)
        prefs_window.title("Preferences")
        prefs_window.transient(self.root)
        prefs_window.resizable(False, False)
        prefs_window.configure(bg=self.colors["about_bg"])
        prefs_window.grab_set()

        container = Frame(prefs_window, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
        container.pack(fill=BOTH, expand=True, padx=22, pady=20)

        Label(
            container,
            text="Preferences",
            font=("Segoe UI", 16, "bold"),
            bg=self.colors["about_bg"],
            fg=self.colors["text"],
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(0, 14))

        theme_panel = self.dialog_panel(container, "Appearance")
        dark_var = IntVar(value=1 if self.dark_mode else 0)
        self.flat_checkbutton(
            theme_panel,
            "Dark mode",
            dark_var,
            background=self.colors["about_bg"],
        ).pack(anchor="w")

        defaults_panel = self.dialog_panel(container, "Layer Defaults", pady=(14, 0))
        header = Frame(defaults_panel, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
        header.pack(fill="x", pady=(0, 6))
        for column, text in enumerate(("Layer", "Output channel")):
            header.columnconfigure(column, weight=1 if column != 1 else 0)
            Label(
                header,
                text=text,
                bg=self.colors["about_bg"],
                fg=self.colors["muted"],
                font=("Segoe UI", 9),
                bd=0,
                highlightthickness=0,
            ).grid(row=0, column=column, sticky="w", padx=(0, 12))

        channel_vars = {key: IntVar(value=self.channel_map[key]) for key in CHANNELS}

        for key, label in CHANNELS.items():
            row = Frame(defaults_panel, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
            row.pack(fill="x", pady=3)
            row.columnconfigure(0, minsize=165)

            Label(
                row,
                text=label,
                bg=self.colors["about_bg"],
                fg=self.colors["text"],
                font=("Segoe UI", 9),
                anchor="w",
                bd=0,
                highlightthickness=0,
            ).grid(row=0, column=0, sticky="w", padx=(0, 12))

            options = Frame(row, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
            options.grid(row=0, column=1, sticky="w")
            option_buttons: list[Label] = []

            def redraw_options(var=channel_vars[key], buttons=option_buttons):
                for index, button in enumerate(buttons):
                    selected = var.get() == index
                    button.configure(
                        bg=self.colors["accent"] if selected else self.colors["control_bg"],
                        fg="#111111" if selected else self.colors["text"],
                    )

            for index, letter in enumerate(CHANNEL_LETTERS):
                option = Label(
                    options,
                    text=letter,
                    bg=self.colors["control_bg"],
                    fg=self.colors["text"],
                    font=("Segoe UI", 9),
                    width=3,
                    padx=4,
                    pady=6,
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=self.colors["border"],
                    highlightcolor=self.colors["border"],
                )
                option.pack(side=LEFT, padx=(0, 6))
                option.bind(
                    "<Button-1>",
                    lambda _event, var=channel_vars[key], value=index: var.set(value),
                )
                option_buttons.append(option)

            channel_vars[key].trace_add("write", lambda *_args, redraw=redraw_options: redraw())
            redraw_options()

        actions = Frame(container, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
        actions.pack(fill="x", pady=(18, 0))

        def reset_defaults():
            dark_var.set(1 if windows_prefers_dark() else 0)
            for key in CHANNELS:
                channel_vars[key].set(DEFAULT_CHANNEL_MAP[key])

        def apply_and_close():
            channel_map = {key: var.get() for key, var in channel_vars.items()}
            if len(set(channel_map.values())) != len(CHANNELS):
                messagebox.showerror("Preferences", "Each layer must use a different RGBA channel.")
                return

            prefs_window.destroy()
            self.apply_preferences(bool(dark_var.get()), channel_map)

        self.flat_button(actions, "Reset Defaults", reset_defaults, width=110).pack(side=LEFT)
        self.flat_button(actions, "Cancel", prefs_window.destroy, width=82).pack(side=RIGHT)
        self.flat_button(actions, "Save", apply_and_close, width=82).pack(side=RIGHT, padx=(0, 8))

        prefs_window.update_idletasks()
        apply_windows_11_mica(prefs_window, self.dark_mode)
        x = self.root.winfo_x() + (self.root.winfo_width() - prefs_window.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - prefs_window.winfo_height()) // 2
        prefs_window.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def apply_preferences(
        self,
        dark_mode: bool,
        channel_map: dict[str, int],
    ):
        self.dark_mode = dark_mode
        self.channel_map = channel_map
        self.preferences = {
            "dark_mode": self.dark_mode,
            "channel_map": {key: CHANNEL_LETTERS[value] for key, value in self.channel_map.items()},
        }
        try:
            save_preferences(self.preferences)
        except OSError as exc:
            messagebox.showerror("Preferences", f"Could not save preferences:\n\n{exc}")
            return

        self.colors = THEMES["dark" if self.dark_mode else "light"]
        self.root.configure(bg=self.colors["app_bg"])
        for child in self.root.winfo_children():
            child.destroy()
        self.build_ui()
        self.refresh_edit_menu()
        apply_windows_11_mica(self.root, self.dark_mode)
        self.status.set(f"Preferences saved to {PREFERENCES_PATH}.")
        self.schedule_render()

    def dialog_panel(self, parent, title: str, pady=(0, 0)):
        outer = Frame(parent, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
        outer.pack(fill="x", pady=pady)
        Label(
            outer,
            text=title,
            bg=self.colors["about_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9, "bold"),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(0, 6))
        body = Frame(outer, bg=self.colors["about_bg"], bd=0, highlightthickness=0)
        body.pack(fill="x")
        return body

    def build_ui(self):
        preview_bg = self.colors["preview_bg"]

        shell = Frame(self.root, bg=self.colors["app_bg"], bd=0, highlightthickness=0)
        shell.pack(fill=BOTH, expand=True, padx=10, pady=(8, 10))

        self.build_command_bar(shell)

        main = Frame(shell, bg=self.colors["app_bg"], bd=0, highlightthickness=0)
        main.pack(fill=BOTH, expand=True)

        sidebar = Frame(main, width=360, bg=self.colors["app_bg"], bd=0, highlightthickness=0)
        sidebar.pack(side=LEFT, fill="y", padx=(0, 12))
        sidebar.pack_propagate(False)

        layers_box = self.panel(sidebar, "Layers")

        self.layer_swatches.clear()
        self.layer_titles.clear()
        for key, label in CHANNELS.items():
            self.add_layer_row(layers_box, key, label, self.preview_colors[key])

        settings = self.panel(sidebar, "Output", pady=(12, 0))

        self.add_number_row(settings, "Pixels / mm", self.pixels_per_mm)
        self.add_number_row(settings, "Margin mm", self.margin_mm)
        self.flat_checkbutton(
            settings,
            text="Export all loaded layers even when hidden",
            variable=self.include_hidden_export,
        ).pack(anchor="w", pady=(10, 8))

        buttons = Frame(settings, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        buttons.pack(fill="x", pady=(8, 0))
        self.flat_button(buttons, "Refresh Preview", self.schedule_render).pack(side=LEFT, fill="x", expand=True)
        self.flat_button(buttons, "Export PNG", self.export_png).pack(side=LEFT, fill="x", expand=True, padx=(8, 0))

        preview_box = Frame(main, bg=preview_bg, bd=0, highlightthickness=0)
        preview_box.pack(side=RIGHT, fill=BOTH, expand=True)
        self.preview_label = Label(
            preview_box,
            bg=preview_bg,
            fg="#dddddd",
            text="No preview yet",
            font=("Segoe UI", 10),
            bd=0,
            highlightthickness=0,
        )
        self.preview_label.pack(fill=BOTH, expand=True)

        status = Label(
            self.root,
            textvariable=self.status,
            anchor="w",
            bg=self.colors["app_bg"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            padx=12,
            pady=4,
            bd=0,
            highlightthickness=0,
        )
        status.pack(side=BOTTOM, fill="x")

    def add_layer_row(self, parent, key: str, label: str, color: str):
        row = Frame(parent, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        row.pack(fill="x", pady=(0, 8))
        row.columnconfigure(1, weight=1)

        swatch = Frame(row, bg=color, width=18, height=18, bd=0, highlightthickness=0)
        swatch.grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=(6, 0))
        swatch.grid_propagate(False)
        self.layer_swatches[key] = swatch

        title = Label(
            row,
            text=label,
            anchor="w",
            bg=self.colors["panel_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
        )
        title.grid(row=0, column=1, sticky="ew", pady=(3, 0))
        self.layer_titles[key] = title

        self.flat_button(row, "Import", lambda k=key: self.import_layer(k), width=86).grid(
            row=0,
            column=2,
            sticky="e",
            padx=(10, 0),
        )

        path_label = Label(
            row,
            textvariable=self.path_text[key],
            anchor="w",
            wraplength=245,
            bg=self.colors["panel_bg"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
        )
        path_label.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(0, 2))

        controls = Frame(row, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        controls.grid(row=2, column=1, columnspan=2, sticky="w")
        self.flat_checkbutton(
            controls,
            text="Show",
            variable=self.visible[key],
            command=self.visibility_changed,
        ).pack(side=LEFT)
        self.flat_checkbutton(
            controls,
            text="Invert mask",
            variable=self.inverted[key],
            command=self.schedule_render,
        ).pack(side=LEFT, padx=(16, 0))

    def panel(self, parent, title: str, pady=(0, 0)):
        outer = Frame(parent, bg=self.colors["app_bg"], bd=0, highlightthickness=0)
        outer.pack(fill="x", pady=pady)
        header = Label(
            outer,
            text=title,
            bg=self.colors["app_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        header.pack(anchor="w", padx=(8, 0), pady=(0, 2))

        body_border = Frame(outer, bg=self.colors["border"], bd=0, highlightthickness=0)
        body_border.pack(fill="x")
        body = Frame(body_border, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        body.pack(fill="x", padx=1, pady=1)
        content = Frame(body, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        content.pack(fill="x", padx=10, pady=10)
        return content

    def flat_button(self, parent, text: str, command, width: int | None = None):
        button = Label(
            parent,
            text=text,
            bg=self.colors["control_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            padx=12,
            pady=8,
            width=0,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["border"],
        )
        if width is not None:
            button.configure(width=max(1, width // 8))

        def press(_event=None):
            button.configure(bg=self.colors["pressed_bg"])

        def release(_event=None):
            button.configure(bg=self.colors["hover_bg"])
            command()

        button.bind("<Enter>", lambda _event: button.configure(bg=self.colors["hover_bg"]))
        button.bind("<Leave>", lambda _event: button.configure(bg=self.colors["control_bg"]))
        button.bind("<ButtonPress-1>", press)
        button.bind("<ButtonRelease-1>", release)
        return button

    def flat_checkbutton(self, parent, text: str, variable: IntVar, command=None, background: str | None = None):
        bg = background or self.colors["panel_bg"]
        control = Frame(parent, bg=bg, bd=0, highlightthickness=0)
        box = tk.Canvas(
            control,
            width=18,
            height=18,
            bg=bg,
            bd=0,
            highlightthickness=0,
        )
        box.pack(side=LEFT)
        label = Label(
            control,
            text=text,
            bg=bg,
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
        )
        label.pack(side=LEFT, padx=(6, 0))

        def draw():
            box.delete("all")
            checked = bool(variable.get())
            fill = self.colors["accent"] if checked else self.colors["control_bg"]
            outline = self.colors["accent"] if checked else "#8a8a8a"
            box.create_rectangle(2, 2, 16, 16, fill=fill, outline=outline, width=1)
            if checked:
                box.create_line(
                    5,
                    9,
                    8,
                    12,
                    14,
                    5,
                    fill="#111111",
                    width=2,
                    capstyle="round",
                    joinstyle="round",
                )

        def toggle(_event=None):
            variable.set(0 if variable.get() else 1)
            if command is not None:
                command()

        def set_hover(active: bool):
            color = self.colors["hover_bg"] if active else bg
            control.configure(bg=color)
            label.configure(bg=color)
            box.configure(bg=color)
            draw()

        variable.trace_add("write", lambda *_args: draw())
        draw()

        for widget in (control, box, label):
            widget.bind("<Button-1>", toggle)
            widget.bind("<Enter>", lambda _event: set_hover(True))
            widget.bind("<Leave>", lambda _event: set_hover(False))
        return control

    def add_number_row(self, parent, label: str, variable: DoubleVar):
        row = Frame(parent, bg=self.colors["panel_bg"], bd=0, highlightthickness=0)
        row.pack(fill="x", pady=4)
        row.columnconfigure(1, weight=1)
        Label(
            row,
            text=label,
            anchor="w",
            bg=self.colors["panel_bg"],
            fg=self.colors["text"],
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        entry = tk.Entry(
            row,
            textvariable=variable,
            bg=self.colors["control_bg"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            width=10,
        )
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<Return>", lambda _event: self.schedule_render())
        entry.bind("<FocusOut>", lambda _event: self.schedule_render())

    def visibility_changed(self):
        self.refresh_edit_menu()
        self.schedule_render()

    def import_layer(self, key: str):
        path = filedialog.askopenfilename(
            title=f"Import {CHANNELS[key]} Gerber",
            filetypes=[
                ("Gerber files", "*.gbr *.ger *.gtl *.gbl *.gts *.gbs *.gto *.gbo *.gko *.gm1 *.gml *.pho *.art"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            gerber = GerberFile.open(path)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not read this Gerber file:\n\n{exc}")
            return

        self.layers[key] = LoadedLayer(Path(path), gerber)
        self.path_text[key].set(Path(path).name)
        self.status.set(f"Loaded {CHANNELS[key]} from {Path(path).name}.")
        self.schedule_render()

    def render(self, include_hidden: bool):
        pixels_per_mm = float(self.pixels_per_mm.get())
        margin_mm = float(self.margin_mm.get())
        if pixels_per_mm <= 0:
            raise ValueError("Pixels / mm must be greater than zero.")
        if margin_mm < 0:
            raise ValueError("Margin cannot be negative.")

        visibility = {key: bool(var.get()) for key, var in self.visible.items()}
        inversion = {key: bool(var.get()) for key, var in self.inverted.items()}
        rgba, masks, bounds = packed_image(
            self.layers,
            visibility,
            inversion,
            self.channel_map,
            pixels_per_mm,
            margin_mm,
            include_hidden=include_hidden,
        )
        return rgba, masks, bounds, visibility

    def schedule_render(self):
        if not self.layers:
            return
        self.status.set("Rendering preview...")
        self.root.after(50, self.render_preview)

    def render_preview(self):
        try:
            rgba, masks, bounds, visibility = self.render(include_hidden=True)
            preview = preview_image(masks, visibility, self.preview_colors)
            self.last_rgba = rgba
            self.last_masks = masks
            self.show_preview(preview)
            size_mm = (bounds[1][0] - bounds[0][0], bounds[1][1] - bounds[0][1])
            self.status.set(
                f"Preview ready: {rgba.width} x {rgba.height}px, {size_mm[0]:.2f} x {size_mm[1]:.2f}mm."
            )
        except Exception as exc:
            self.status.set("Render failed.")
            messagebox.showerror("Render failed", f"{exc}\n\n{traceback.format_exc(limit=2)}")

    def show_preview(self, image: Image.Image):
        max_w = max(300, self.preview_label.winfo_width() - 24)
        max_h = max(300, self.preview_label.winfo_height() - 24)
        display = image.copy()
        display.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        self.image_ref = ImageTk.PhotoImage(display)
        self.preview_label.configure(image=self.image_ref, text="")

    def export_png(self):
        if not self.layers:
            messagebox.showinfo("Nothing to export", "Load at least one Gerber file first.")
            return

        try:
            include_hidden = bool(self.include_hidden_export.get())
            rgba, _masks, _bounds, _visibility = self.render(include_hidden=include_hidden)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        path = filedialog.asksaveasfilename(
            title="Export packed RGBA PNG",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            initialfile="pcb_layers_packed.png",
        )
        if not path:
            return

        try:
            rgba.save(path)
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not write PNG:\n\n{exc}")
            return

        self.status.set(f"Exported packed PNG to {path}.")
        messagebox.showinfo("Export complete", f"Packed RGBA PNG exported:\n\n{path}")


def main():
    root = Tk()
    app = PCBExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
