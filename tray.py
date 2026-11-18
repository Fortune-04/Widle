"""Windows notification-area (system tray) icon for Widle, implemented with ctypes only."""

import ctypes
import struct
from ctypes import wintypes as w

CLASS_NAME = "WidleTrayWindow"
WM_NULL, WM_LBUTTONUP, WM_RBUTTONUP = 0x0000, 0x0202, 0x0205
WM_TRAY, WM_SHOW = 0x8001, 0x8002
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
SM_CXSMICON = 49
MENU_ACTIONS = {1: ("Show widget", "show"), 2: ("Hide widget", "hide"), 3: ("Exit", "exit")}

BG_RGB, BAR_RGB = (0x1E, 0x1F, 0x26), (0x3E, 0xCF, 0x8E)
BARS = ((0.20, 0.30), (0.415, 0.47), (0.63, 0.62))
BAR_WIDTH, BASELINE = 0.17, 0.80

LRESULT = w.LPARAM
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                ("lpszClassName", w.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                ("guidItem", w.DWORD * 4), ("hBalloonIcon", w.HICON)]


def icon_pixels(size):
    pad, radius = max(1, size // 16), max(2, size // 5)
    lo, hi, base = pad, size - pad, BASELINE * size
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            cx, cy = x + 0.5, y + 0.5
            dx = max(lo + radius - cx, 0, cx - (hi - radius))
            dy = max(lo + radius - cy, 0, cy - (hi - radius))
            if not (lo <= cx <= hi and lo <= cy <= hi) or dx * dx + dy * dy > radius * radius:
                row.append((0, 0, 0, 0))
                continue
            on_bar = any(start * size <= cx < (start + BAR_WIDTH) * size and base - height * size <= cy < base
                         for start, height in BARS)
            row.append((BAR_RGB if on_bar else BG_RGB) + (255,))
        rows.append(row)
    return rows


def icon_dib(size):
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytes(c for row in reversed(icon_pixels(size)) for (r, g, b, a) in row for c in (b, g, r, a))
    mask = bytes((size + 31) // 32 * 4 * size)
    return header + pixels + mask


def ico_file(sizes=(16, 20, 24, 32, 48, 64, 128)):
    images = [icon_dib(s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, image in zip(sizes, images):
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return out + b"".join(images)


def _api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for fn, args, res in [
        (user32.RegisterClassW, [ctypes.POINTER(WNDCLASSW)], w.ATOM),
        (user32.UnregisterClassW, [w.LPCWSTR, w.HINSTANCE], w.BOOL),
        (user32.CreateWindowExW, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID], w.HWND),
        (user32.DestroyWindow, [w.HWND], w.BOOL),
        (user32.DefWindowProcW, [w.HWND, w.UINT, w.WPARAM, w.LPARAM], LRESULT),
        (user32.RegisterWindowMessageW, [w.LPCWSTR], w.UINT),
        (user32.CreatePopupMenu, [], w.HMENU),
        (user32.AppendMenuW, [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR], w.BOOL),
        (user32.TrackPopupMenu, [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.LPVOID],
         w.BOOL),
        (user32.DestroyMenu, [w.HMENU], w.BOOL),
        (user32.SetForegroundWindow, [w.HWND], w.BOOL),
        (user32.PostMessageW, [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
        (user32.GetCursorPos, [ctypes.POINTER(w.POINT)], w.BOOL),
        (user32.GetSystemMetrics, [ctypes.c_int], ctypes.c_int),
        (user32.CreateIconFromResourceEx, [ctypes.c_void_p, w.DWORD, w.BOOL, w.DWORD, ctypes.c_int,
                                           ctypes.c_int, w.UINT], w.HICON),
        (user32.DestroyIcon, [w.HICON], w.BOOL),
        (user32.FindWindowW, [w.LPCWSTR, w.LPCWSTR], w.HWND),
        (shell32.Shell_NotifyIconW, [w.DWORD, ctypes.POINTER(NOTIFYICONDATAW)], w.BOOL),
        (kernel32.GetModuleHandleW, [w.LPCWSTR], w.HMODULE),
    ]:
        fn.argtypes, fn.restype = args, res
    return user32, shell32, kernel32


def show_existing():
    user32, _, _ = _api()
    hwnd = user32.FindWindowW(CLASS_NAME, None)
    if hwnd:
        user32.PostMessageW(hwnd, WM_SHOW, 0, 0)


class Tray:
    def __init__(self, on_event, tooltip="Widle"):
        self.on_event = on_event
        self.user32, self.shell32, kernel32 = _api()
        self.hinst = kernel32.GetModuleHandleW(None)
        self.taskbar_created = self.user32.RegisterWindowMessageW("TaskbarCreated")
        self._proc = WNDPROC(self._wndproc)
        wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=self.hinst, lpszClassName=CLASS_NAME)
        if not self.user32.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = self.user32.CreateWindowExW(0, CLASS_NAME, "Widle", 0, 0, 0, 0, 0,
                                                None, None, self.hinst, None)
        if not self.hwnd:
            self.user32.UnregisterClassW(CLASS_NAME, self.hinst)
            raise ctypes.WinError(ctypes.get_last_error())
        size = self.user32.GetSystemMetrics(SM_CXSMICON) or 16
        dib = icon_dib(size)
        self.hicon = self.user32.CreateIconFromResourceEx(dib, len(dib), True, 0x00030000, size, size, 0)
        self.nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1,
                                   uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY,
                                   hIcon=self.hicon, szTip=tooltip[:127])
        if not self._notify(NIM_ADD):
            self.remove()
            raise OSError("Could not add the tray icon")

    def _notify(self, action):
        return bool(self.shell32.Shell_NotifyIconW(action, ctypes.byref(self.nid)))

    def set_tooltip(self, text):
        if self.hwnd and text[:127] != self.nid.szTip:
            self.nid.szTip = text[:127]
            self._notify(NIM_MODIFY)

    def remove(self):
        if not self.hwnd:
            return
        self._notify(NIM_DELETE)
        self.user32.DestroyWindow(self.hwnd)
        self.user32.DestroyIcon(self.hicon)
        self.user32.UnregisterClassW(CLASS_NAME, self.hinst)
        self.hwnd = None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONUP:
                self.on_event("show")
            elif event == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_SHOW:
            self.on_event("show")
            return 0
        if msg == self.taskbar_created:
            self._notify(NIM_ADD)
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        menu = self.user32.CreatePopupMenu()
        for cmd, (label, _action) in MENU_ACTIONS.items():
            if cmd == 3:
                self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            self.user32.AppendMenuW(menu, MF_STRING, cmd, label)
        pt = w.POINT()
        self.user32.GetCursorPos(ctypes.byref(pt))
        self.user32.SetForegroundWindow(self.hwnd)
        cmd = self.user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        self.user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        self.user32.DestroyMenu(menu)
        if cmd in MENU_ACTIONS:
            self.on_event(MENU_ACTIONS[cmd][1])
