"""OCR fallback for windows whose controls are invisible to accessibility APIs (canvas, games,
custom-drawn UI). Text lines become click targets with screen rectangles.

Windows uses the built-in ``Windows.Media.Ocr`` engine through winrt; macOS uses the Vision
framework through pyobjc. Freshness is a hash of the pixels inside the target rectangle: the
click happens only if that region looks exactly as it did when the line was read.
Measured on Windows 11 (one run): a 1600x1000 window region, 117 ms capture + 145 ms OCR, 52 lines;
CJK text may come back with inserted spaces.
"""

import asyncio
import hashlib
import sys


class OCRUnavailable(RuntimeError):
    pass


def _grab(rect):
    try:
        import mss
    except ImportError:
        raise OCRUnavailable("OCR needs: pip install 'jev-filter[desktop]'") from None
    left, top, right, bottom = rect
    box = {
        "left": int(left),
        "top": int(top),
        "width": max(1, int(right - left)),
        "height": max(1, int(bottom - top)),
    }
    factory = getattr(mss, "MSS", None) or mss.mss
    with factory() as screen:
        shot = screen.grab(box)
        return shot.rgb, shot.size


def _grab_window(hwnd):
    """Windows: PrintWindow(PW_RENDERFULLCONTENT) captures the window itself even when another
    window covers it (a screen grab would OCR whatever is on top). Returns rgb, size, origin."""
    import ctypes
    from ctypes import wintypes

    # Private DLL instances with full prototypes: 64-bit handles must not be truncated, and
    # the shared ctypes.windll function objects used by uiautomation must not be mutated.
    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    handle = ctypes.c_void_p
    user32.GetWindowRect.argtypes = [handle, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowDC.argtypes, user32.GetWindowDC.restype = [handle], handle
    user32.ReleaseDC.argtypes = [handle, handle]
    user32.PrintWindow.argtypes = [handle, handle, wintypes.UINT]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [handle], handle
    gdi32.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = handle
    gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = [handle, handle], handle
    gdi32.GetDIBits.argtypes = [
        handle,
        handle,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteDC.argtypes = [handle]
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, 2):
            return None
        header = BITMAPINFOHEADER(40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0):
            return None
        bgra = buffer.raw
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
    if not any(bgra[i] for i in range(0, len(bgra), 4 * 97)):
        return None  # some GPU-composited windows render black through PrintWindow
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    rgb = bytes(rgb)
    scale = _dpi_scale(hwnd)
    if scale > 1.01:
        # A DPI-virtualized window is drawn at its logical size in the top-left of the bitmap
        # (measured: 520x360 logical content inside a 938x698 physical rect at 175%).
        logical = (max(1, int(width / scale)), max(1, int(height / scale)))
        rgb = _crop(rgb, (width, height), (0, 0, logical[0], logical[1]))
        width, height = logical
    return rgb, (width, height), (rect.left, rect.top), scale


def _dpi_scale(hwnd):
    """Physical pixels per window pixel: monitor DPI / the window's own DPI (1 when aware)."""
    try:
        import ctypes

        user32, shcore = ctypes.WinDLL("user32"), ctypes.WinDLL("shcore")
        user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        user32.MonitorFromWindow.argtypes, user32.MonitorFromWindow.restype = (
            [ctypes.c_void_p, ctypes.c_uint],
            ctypes.c_void_p,
        )
        window_dpi = user32.GetDpiForWindow(hwnd) or 96
        monitor = user32.MonitorFromWindow(hwnd, 2)
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        if (
            shcore.GetDpiForMonitor(
                ctypes.c_void_p(monitor), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
            )
            != 0
        ):
            return 1.0
        return dpi_x.value / window_dpi
    except Exception:
        return 1.0


def _crop(rgb, size, box):
    width, _ = size
    left, top, right, bottom = box
    rows = [rgb[(y * width + left) * 3 : (y * width + right) * 3] for y in range(top, bottom)]
    return b"".join(rows)


class BaseOCR:
    def capture(self, window):
        hwnd = window.get("hwnd")
        if sys.platform == "win32" and hwnd:
            grabbed = _grab_window(hwnd)
            if grabbed is not None:
                self.hwnd = hwnd
                return grabbed
        self.hwnd = None
        rect = window.get("rect")
        rgb, size = _grab(rect)
        return rgb, size, (rect[0], rect[1]), 1.0

    def lines(self, window):
        if not window.get("rect"):
            return []
        grabbed = self.capture(window)
        rgb, size, (ox, oy), scale = grabbed
        self.window = window
        found = self.recognize(rgb, size)
        result = []
        for text, (x, y, w, h) in found:
            screen = [ox + x * scale, oy + y * scale, ox + (x + w) * scale, oy + (y + h) * scale]
            result.append({"text": text[:200], "rect": [round(v) for v in screen]})
        self.hashes = {tuple(r["rect"]): self.region_hash(r["rect"], grabbed) for r in result}
        return result

    def region_hash(self, rect, grabbed=None):
        if grabbed is None and getattr(self, "window", None) is not None:
            grabbed = self.capture(self.window)
        if grabbed is None:
            rgb, _ = _grab(rect)
            return hashlib.sha1(rgb).hexdigest()
        rgb, size, (ox, oy), scale = grabbed
        box = (
            max(0, int((rect[0] - ox) / scale)),
            max(0, int((rect[1] - oy) / scale)),
            min(size[0], int((rect[2] - ox) / scale)),
            min(size[1], int((rect[3] - oy) / scale)),
        )
        return hashlib.sha1(_crop(rgb, size, box)).hexdigest()

    def unchanged(self, rect):
        before = getattr(self, "hashes", {}).get(tuple(rect))
        return before is not None and self.region_hash(rect) == before

    def click(self, rect, backend):
        if not self.unchanged(rect):
            from .browser import StalePage

            raise StalePage("text region changed")
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        backend.pointer_click_at(x, y)
        return {"via": "ocr_pointer"}


class WindowsOCR(BaseOCR):
    def __init__(self):
        try:
            from winrt.windows.graphics.imaging import (  # noqa: F401
                BitmapPixelFormat,
                SoftwareBitmap,
            )
            from winrt.windows.media.ocr import OcrEngine
        except ImportError:
            raise OCRUnavailable("Windows OCR needs: pip install 'jev-filter[desktop]'") from None
        self.engine = OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise OCRUnavailable("no OCR language installed")

    def recognize(self, rgb, size):
        import mss.tools
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        png = mss.tools.to_png(rgb, size)

        async def run():
            # The PNG decode path is the one verified on Windows 11; the raw-buffer
            # SoftwareBitmap overloads differ between winrt projections.
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream.get_output_stream_at(0))
            writer.write_bytes(png)
            await writer.store_async()
            await writer.flush_async()
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_converted_async(
                BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
            )
            return await self.engine.recognize_async(bitmap)

        result = asyncio.run(run())
        out = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            xs = [w.bounding_rect.x for w in words]
            ys = [w.bounding_rect.y for w in words]
            x2 = [w.bounding_rect.x + w.bounding_rect.width for w in words]
            y2 = [w.bounding_rect.y + w.bounding_rect.height for w in words]
            out.append(
                (join_words(words), (min(xs), min(ys), max(x2) - min(xs), max(y2) - min(ys)))
            )
        return out


def join_words(words):
    """Rebuild a line from word boxes: CJK engines split Latin words ("Setti ngs"), so a space
    is kept only where the horizontal gap looks like a real word gap."""
    text = ""
    previous = None
    for word in words:
        box = word.bounding_rect
        if previous is not None:
            gap = box.x - (previous.x + previous.width)
            height = max(1.0, (box.height + previous.height) / 2)
            text += " " if gap > 0.3 * height else ""
        text += word.text
        previous = box
    return text


class MacOCR(BaseOCR):
    def __init__(self):
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
        except ImportError:
            raise OCRUnavailable("macOS OCR needs: pip install 'jev-filter[desktop]'") from None

    def recognize(self, rgb, size):
        import Quartz
        import Vision

        width, height = size
        provider = Quartz.CGDataProviderCreateWithData(None, bytes(rgb), len(rgb), None)
        image = Quartz.CGImageCreate(
            width,
            height,
            8,
            24,
            width * 3,
            Quartz.CGColorSpaceCreateDeviceRGB(),
            Quartz.kCGBitmapByteOrderDefault,
            provider,
            None,
            False,
            Quartz.kCGRenderingIntentDefault,
        )
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        ok, _ = handler.performRequests_error_([request], None)
        out = []
        for observation in (request.results() or []) if ok else []:
            candidate = observation.topCandidates_(1)
            if not candidate:
                continue
            box = observation.boundingBox()  # normalized, origin bottom-left
            x = box.origin.x * width
            y = (1 - box.origin.y - box.size.height) * height
            out.append(
                (
                    str(candidate[0].string()),
                    (x, y, box.size.width * width, box.size.height * height),
                )
            )
        return out


def open_ocr(mode="auto"):
    if mode == "off":
        return None
    try:
        engine = (
            WindowsOCR()
            if sys.platform == "win32"
            else MacOCR()
            if sys.platform == "darwin"
            else None
        )
    except OCRUnavailable:
        if mode == "on":
            raise
        return None
    if engine is None and mode == "on":
        raise OCRUnavailable("OCR supports Windows and macOS")
    return engine
