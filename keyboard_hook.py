"""Global low-level keyboard hook for Windows exam lockdown.

Uses WH_KEYBOARD_LL to suppress dangerous shortcuts (Alt+Tab, Win key,
Alt+F4, Ctrl+Esc, devtools, refresh, etc.) system-wide while the exam
browser is running.

The hook runs inside a dedicated thread that pumps its own Win32 message
loop, so it does not interfere with the Qt event loop.
"""

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012

# Virtual-key codes we care about
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C

LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    LowLevelKeyboardProc,
    ctypes.c_void_p,
    wintypes.DWORD,
]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
    wintypes.UINT,
]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def build_vk_map():
    """Human readable key names -> virtual-key codes."""
    m = {
        "ctrl": VK_CONTROL,
        "control": VK_CONTROL,
        "alt": VK_MENU,
        "menu": VK_MENU,
        "shift": VK_SHIFT,
        "win": VK_LWIN,
        "esc": 0x1B,
        "escape": 0x1B,
        "tab": 0x09,
        "space": 0x20,
        "enter": 0x0D,
        "return": 0x0D,
    }
    for ch in "abcdefghijklmnopqrstuvwxyz":
        m[ch] = ord(ch.upper())
    for d in "0123456789":
        m[d] = ord(d)
    for i in range(1, 13):
        m["f%d" % i] = 0x6F + i
    return m


VK_MAP = build_vk_map()


def is_key_down(vk):
    """True when the given virtual key is currently held down."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class KeyboardBlocker:
    """Install/remove a system-wide keyboard suppression hook."""

    def __init__(self, block_cfg=None):
        self.cfg = block_cfg or {}
        self._hook = None
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._running = False
        # keep a strong reference so the callback is not garbage collected
        self._callback = LowLevelKeyboardProc(self._proc)

    # -- public API ------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="kbd-hook", daemon=True
        )
        self._thread.start()
        self._ready.wait(2.0)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._running = False

    # -- internals -------------------------------------------------------
    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        hmod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._callback, hmod, 0
        )
        self._ready.set()
        if not self._hook:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def _proc(self, nCode, wParam, lParam):
        if nCode == 0:
            try:
                kb = ctypes.cast(
                    lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)
                ).contents
                vk = kb.vkCode
            except Exception:
                vk = None
            if vk is not None and self._should_block(vk):
                return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _should_block(self, vk):
        c = self.cfg

        # Windows / Super key (also blocks Win+<anything>)
        if c.get("windows_key", True):
            if vk in (VK_LWIN, VK_RWIN):
                return True
            if is_key_down(VK_LWIN) or is_key_down(VK_RWIN):
                return True

        alt = is_key_down(VK_MENU)
        ctrl = is_key_down(VK_CONTROL)
        shift = is_key_down(VK_SHIFT)

        if c.get("alt_tab", True) and alt and vk == 0x09:      # Alt+Tab
            return True
        if c.get("alt_f4", True) and alt and vk == 0x73:       # Alt+F4
            return True
        if c.get("alt_esc", True) and alt and vk == 0x1B:      # Alt+Esc
            return True
        if c.get("ctrl_esc", True) and ctrl and vk == 0x1B:    # Ctrl+Esc
            return True
        if c.get("ctrl_shift_esc", True) and ctrl and shift and vk == 0x1B:
            return True                                        # Task Manager
        if vk == 0x7A:                                         # F11 fullscreen
            return True
        if c.get("refresh", True) and ctrl and vk == 0x52:    # Ctrl+R
            return True
        if c.get("devtools", True):
            if vk == 0x7B:                                     # F12
                return True
            if ctrl and shift and vk in (0x49, 0x4A, 0x43):    # I / J / C
                return True
        if c.get("new_window", True) and ctrl and vk in (0x4E, 0x54, 0x57):
            return True                                        # Ctrl+N/T/W
        if c.get("print", True) and ctrl and vk == 0x50:       # Ctrl+P
            return True
        if c.get("view_source", True) and ctrl and vk == 0x55:  # Ctrl+U
            return True
        return False
