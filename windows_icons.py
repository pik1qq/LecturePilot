"""Native window icons at the window's DPI; no global icon-cache changes."""
import sys
from pathlib import Path

def enable_dpi_awareness():
    """Call before creating any windows. Preserve an existing process policy."""
    if sys.platform != 'win32': return False
    import ctypes
    try:
        user32=ctypes.WinDLL('user32',use_last_error=True)
        f=user32.SetProcessDpiAwarenessContext
        f.argtypes=[ctypes.c_void_p]; f.restype=ctypes.c_bool
        if f(ctypes.c_void_p(-4)): return True  # Per-monitor V2 (Windows 10+)
    except (AttributeError,OSError): pass
    try:
        user32=ctypes.WinDLL('user32',use_last_error=True)
        return bool(user32.SetProcessDPIAware())
    except (AttributeError,OSError): return False

class WindowIcons:
    def __init__(self,root):
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes; self.root=root; self.handles=[]; self.key=None
        u=ctypes.WinDLL('user32',use_last_error=True); self.u=u
        u.GetParent.argtypes=[wintypes.HWND]; u.GetParent.restype=wintypes.HWND
        u.LoadImageW.argtypes=[wintypes.HINSTANCE,wintypes.LPCWSTR,wintypes.UINT,ctypes.c_int,ctypes.c_int,wintypes.UINT];u.LoadImageW.restype=wintypes.HANDLE
        u.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];u.SendMessageW.restype=ctypes.c_ssize_t
        u.DestroyIcon.argtypes=[wintypes.HANDLE];u.DestroyIcon.restype=wintypes.BOOL
        u.GetSystemMetrics.argtypes=[ctypes.c_int];u.GetSystemMetrics.restype=ctypes.c_int
        try:
            u.GetDpiForWindow.argtypes=[wintypes.HWND];u.GetDpiForWindow.restype=wintypes.UINT
            u.GetSystemMetricsForDpi.argtypes=[ctypes.c_int,wintypes.UINT];u.GetSystemMetricsForDpi.restype=ctypes.c_int
        except AttributeError: pass
    def apply(self,path):
        self.root.update_idletasks()
        hwnd=self.u.GetParent(int(self.root.winfo_id()))
        if not hwnd: raise OSError('Native window not ready')
        try: dpi=self.u.GetDpiForWindow(hwnd) or 96
        except AttributeError: dpi=96
        def metric(index):
            try:return self.u.GetSystemMetricsForDpi(index,dpi)
            except AttributeError:return self.u.GetSystemMetrics(index)
        small=(metric(49),metric(50));big=(metric(11),metric(12))
        if min(*small,*big)<=0:raise OSError('Invalid system icon dimensions')
        key=(hwnd,str(Path(path)),dpi,small,big)
        if key==self.key:return
        loaded=[]
        try:
            for width,height in (small,big):
                handle=self.u.LoadImageW(None,str(path),1,width,height,0x10) # IMAGE_ICON, LR_LOADFROMFILE
                if not handle:raise OSError('Windows could not load icon')
                loaded.append(handle)
        except Exception:
            for h in loaded:self.u.DestroyIcon(h)
            raise
        self.u.SendMessageW(hwnd,0x80,0,loaded[0]) # WM_SETICON, ICON_SMALL
        self.u.SendMessageW(hwnd,0x80,1,loaded[1]) # WM_SETICON, ICON_BIG
        # Only destroy icons created by this object, never Tk's or a shared icon.
        if self.key and self.key[0]==hwnd:
            for h in self.handles:self.u.DestroyIcon(h)
            self.handles=[]
        self.handles.extend(loaded);self.key=key
    def close(self):
        for h in self.handles:self.u.DestroyIcon(h)
        self.handles=[];self.key=None
