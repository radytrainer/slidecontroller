"""
Small Windows helpers: find windows, bring one to the front, press keys.

Used by the PDF controller (viewers have no common automation API, so the
viewer window is focused and sent its navigation keys) and to put the
PowerPoint slide show in front.
"""

import time

import win32api
import win32con
import win32gui
import win32process

# Key names usable in config.py (combine with "+", e.g. "ctrl+l").
VIRTUAL_KEYS = {
    "right": win32con.VK_RIGHT,
    "left": win32con.VK_LEFT,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "page_down": win32con.VK_NEXT,
    "page_up": win32con.VK_PRIOR,
    "space": win32con.VK_SPACE,
    "escape": win32con.VK_ESCAPE,
    "enter": win32con.VK_RETURN,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "ctrl": win32con.VK_CONTROL,
    "shift": win32con.VK_SHIFT,
    "alt": win32con.VK_MENU,
    **{f"f{n}": getattr(win32con, f"VK_F{n}") for n in range(1, 13)},
}
EXTENDED_KEYS = {
    win32con.VK_RIGHT, win32con.VK_LEFT, win32con.VK_UP, win32con.VK_DOWN,
    win32con.VK_NEXT, win32con.VK_PRIOR, win32con.VK_HOME, win32con.VK_END,
}


def parse_key(spec: str) -> list[int]:
    """'ctrl+l' -> [VK_CONTROL, ord('L')]."""
    codes = []
    for part in spec.lower().split("+"):
        part = part.strip()
        if part in VIRTUAL_KEYS:
            codes.append(VIRTUAL_KEYS[part])
        elif len(part) == 1 and part.isalnum():
            codes.append(ord(part.upper()))
        else:
            raise ValueError(f"Unknown key '{part}' in '{spec}'")
    return codes


def _key_event(code: int, up: bool) -> None:
    flags = win32con.KEYEVENTF_EXTENDEDKEY if code in EXTENDED_KEYS else 0
    if up:
        flags |= win32con.KEYEVENTF_KEYUP
    win32api.keybd_event(code, 0, flags, 0)


def send_key(spec: str) -> None:
    """Press and release a key or combination in the foreground window."""
    codes = parse_key(spec)
    for code in codes:
        _key_event(code, up=False)
    for code in reversed(codes):
        _key_event(code, up=True)


def window_pid(hwnd: int) -> int:
    return win32process.GetWindowThreadProcessId(hwnd)[1]


def list_windows() -> list[tuple[int, str]]:
    """Visible top-level windows with a title: [(hwnd, title)]."""
    found = []

    def collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                found.append((hwnd, title))
        return True

    win32gui.EnumWindows(collect, None)
    return found


def wait_for_window(predicate, timeout: float, poll: float = 0.2) -> int | None:
    """Poll until a window matching ``predicate(hwnd, title)`` appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd, title in list_windows():
            if predicate(hwnd, title):
                return hwnd
        time.sleep(poll)
    return None


def is_window(hwnd: int | None) -> bool:
    return bool(hwnd) and bool(win32gui.IsWindow(hwnd))


def is_foreground(hwnd: int) -> bool:
    return win32gui.GetForegroundWindow() == hwnd


def bring_to_foreground(hwnd: int) -> bool:
    """Restore and focus a window. Returns True if it is now in front."""
    if not is_window(hwnd):
        return False
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except win32gui.error:
        # Windows only lets the app that received the last input steal focus.
        # Tapping ALT counts as input and lifts that restriction.
        _key_event(win32con.VK_MENU, up=False)
        _key_event(win32con.VK_MENU, up=True)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except win32gui.error:
            return False
    return is_foreground(hwnd)


def window_rect(hwnd: int | None) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) in screen pixels, or None if gone / minimised."""
    if not is_window(hwnd) or win32gui.IsIconic(hwnd):
        return None
    try:
        return tuple(win32gui.GetWindowRect(hwnd))
    except win32gui.error:
        return None


def class_name(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd)
    except win32gui.error:
        return ""


def find_windows(window_class: str) -> list[int]:
    """Visible top-level windows of this window class, biggest first."""
    found = []

    def collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and class_name(hwnd) == window_class:
            found.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)

    def area(hwnd):
        rect = window_rect(hwnd)
        return (rect[2] - rect[0]) * (rect[3] - rect[1]) if rect else 0

    return sorted(found, key=area, reverse=True)


def presentation_area() -> tuple[int, int, int, int]:
    """Where a slide show most likely is when its window is unknown: with several
    screens the biggest secondary one (the projector - the laptop screen shows
    Presenter View), otherwise the primary screen without the taskbar."""
    secondary = []
    for monitor, _, _ in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(monitor)
        if not info["Flags"] & win32con.MONITORINFOF_PRIMARY:
            secondary.append(tuple(info["Monitor"]))
    if secondary:
        return max(secondary, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    monitor = win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY)
    return tuple(win32api.GetMonitorInfo(monitor)["Work"])


def move_topmost(hwnd: int, x: int, y: int) -> None:
    """Move a window (screen pixels) and keep it above full-screen windows, without focusing it."""
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, 0, 0,
                          win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)


def post_close(hwnd: int) -> None:
    """Ask a window to close (like clicking X)."""
    if is_window(hwnd):
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
