import sys

WDA_EXCLUDEFROMCAPTURE = 0x00000011


def hide_from_capture(win_id: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(win_id), WDA_EXCLUDEFROMCAPTURE))
    if sys.platform == "darwin":
        try:
            import objc
            from AppKit import NSWindowSharingNone
        except ImportError:
            return False
        view = objc.objc_object(c_void_p=win_id)
        window = view.window()
        if window is None:
            return False
        window.setSharingType_(NSWindowSharingNone)
        return True
    return False
