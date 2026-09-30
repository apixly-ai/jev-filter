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


class BaseOCR:
    def lines(self, window):
        rect = window.get("rect")
        if not rect:
            return []
        rgb, size = _grab(rect)
        found = self.recognize(rgb, size)
        result = []
        for text, (x, y, w, h) in found:
            screen = [rect[0] + x, rect[1] + y, rect[0] + x + w, rect[1] + y + h]
            result.append({"text": text[:200], "rect": [round(v) for v in screen]})
        self.hashes = {tuple(r["rect"]): self.region_hash(r["rect"]) for r in result}
        return result

    def region_hash(self, rect):
        rgb, _ = _grab(rect)
        return hashlib.sha1(rgb).hexdigest()

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
