"""Native icon loading and DPI transitions; Windows also exercises real HWNDs."""
import ctypes,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from windows_icons import WindowIcons

class IconsTests(unittest.TestCase):
    def test_native_size_theme_dpi_and_own_handle_cleanup(self):
        u=MagicMock();u.GetParent.return_value=100;u.GetDpiForWindow.return_value=144
        u.GetSystemMetricsForDpi.side_effect=lambda metric,dpi: (24 if metric in (49,50) else 48) if dpi==144 else (16 if metric in (49,50) else 32)
        u.LoadImageW.side_effect=[10,11,12,13,14,15]
        root=MagicMock();root.winfo_id.return_value=20
        with patch.object(ctypes,'WinDLL',return_value=u,create=True):
            icons=WindowIcons(root)
            icons.apply('light.ico')
            self.assertEqual([c.args[3:5] for c in u.LoadImageW.call_args_list],[(24,24),(48,48)])
            self.assertEqual([c.args[1:] for c in u.SendMessageW.call_args_list],[(0x80,0,10),(0x80,1,11)])
            icons.apply('light.ico');self.assertEqual(u.LoadImageW.call_count,2)
            icons.apply('dark.ico');self.assertEqual([c.args[0] for c in u.DestroyIcon.call_args_list],[10,11])
            u.GetDpiForWindow.return_value=96;icons.apply('dark.ico')
            self.assertEqual([c.args[3:5] for c in u.LoadImageW.call_args_list[-2:]],[(16,16),(32,32)])
            icons.close()
            self.assertEqual([c.args[0] for c in u.DestroyIcon.call_args_list],[10,11,12,13,14,15])
    def test_failed_load_does_not_replace_existing_icons(self):
        u=MagicMock();u.GetParent.return_value=100;u.GetDpiForWindow.return_value=96
        u.GetSystemMetricsForDpi.return_value=16;u.LoadImageW.side_effect=[1,2,3,0]
        root=MagicMock();root.winfo_id.return_value=20
        with patch.object(ctypes,'WinDLL',return_value=u,create=True):
            icons=WindowIcons(root);icons.apply('light.ico')
            with self.assertRaises(OSError):icons.apply('dark.ico')
            self.assertEqual(u.SendMessageW.call_count,2)
            u.DestroyIcon.assert_called_once_with(3)
            icons.close()

@unittest.skipUnless(sys.platform=='win32','requires Windows native HWND')
class RealWindowsIconsTests(unittest.TestCase):
    def test_real_window_receives_valid_icon_handles(self):
        import tkinter as tk
        import make_icon  # generate ICO even on a clean source checkout
        try:root=tk.Tk()
        except tk.TclError as e:self.skipTest('No GUI session available: '+str(e))
        icons=None
        try:
            root.update();icons=WindowIcons(root)
            light=Path(make_icon.__file__).parent/'app-icon.ico'
            dark=Path(make_icon.__file__).parent/'app-icon-dark.ico'
            icons.apply(light)
            hwnd=icons.u.GetParent(root.winfo_id())
            small=icons.u.SendMessageW(hwnd,0x7f,0,0);big=icons.u.SendMessageW(hwnd,0x7f,1,0)
            self.assertTrue(small);self.assertTrue(big)
            self.assertEqual([small,big],icons.handles)
            icons.apply(dark)
            self.assertEqual(icons.u.SendMessageW(hwnd,0x7f,1,0),icons.handles[-1])
        finally:
            root.destroy()
            if icons:icons.close()

if __name__=='__main__':unittest.main()
