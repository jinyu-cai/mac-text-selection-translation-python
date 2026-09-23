import asyncio
import concurrent.futures

import AppKit as A
import Quartz as Q
import ScreenCaptureKit as SC
import Vision
from Foundation import NSDictionary, NSProcessInfo

from mactranslator.policies import ocr_rect
from .native import on_main


class SelectionView(A.NSView):
    def acceptsFirstResponder(self):
        return True

    def drawRect_(self, dirty):
        A.NSColor.colorWithCalibratedWhite_alpha_(0, 0.25).setFill()
        A.NSRectFill(self.bounds())
        if getattr(self, "selection", None):
            A.NSColor.systemBlueColor().setStroke()
            path = A.NSBezierPath.bezierPathWithRect_(self.selection)
            path.setLineWidth_(2)
            path.stroke()

    def mouseDown_(self, event):
        self.anchor = self.convertPoint_fromView_(event.locationInWindow(), None)

    def mouseDragged_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        x, y = min(self.anchor.x, point.x), min(self.anchor.y, point.y)
        self.selection = A.NSMakeRect(x, y, abs(point.x - self.anchor.x), abs(point.y - self.anchor.y))
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        self.mouseDragged_(event)
        if self.selection.size.width >= 2 and self.selection.size.height >= 2:
            self.owner.finish((self.display_id, self.selection))
        else:
            self.owner.cancel()

    def keyDown_(self, event):
        if event.keyCode() == 53:
            self.owner.cancel()


class SelectionWindow(A.NSWindow):
    def canBecomeKeyWindow(self):
        return True


class OCRCapture:
    def __init__(self):
        self.windows = []
        self.selection_future = None
        self.busy = False

    def choose(self):
        if not Q.CGPreflightScreenCaptureAccess() and not Q.CGRequestScreenCaptureAccess():
            raise RuntimeError("请在系统设置 → 隐私与安全性 → 屏幕录制中允许此应用，然后重启。")
        self.selection_future = concurrent.futures.Future()
        for screen in A.NSScreen.screens():
            window = SelectionWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                screen.frame(), A.NSWindowStyleMaskBorderless, A.NSBackingStoreBuffered, False)
            window.setReleasedWhenClosed_(False)
            window.setLevel_(A.NSScreenSaverWindowLevel)
            window.setOpaque_(False)
            window.setBackgroundColor_(A.NSColor.clearColor())
            window.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                           A.NSWindowCollectionBehaviorFullScreenAuxiliary)
            view = SelectionView.alloc().initWithFrame_(A.NSMakeRect(0, 0, screen.frame().size.width,
                                                                   screen.frame().size.height))
            view.owner, view.display_id = self, screen.deviceDescription()["NSScreenNumber"]
            window.setContentView_(view)
            window.makeKeyAndOrderFront_(None)
            window.makeFirstResponder_(view)
            self.windows.append(window)
        A.NSCursor.crosshairCursor().push()
        return self.selection_future

    def close(self):
        for window in self.windows:
            window.orderOut_(None)
            window.close()
        if self.windows:
            A.NSCursor.pop()
        self.windows.clear()

    def finish(self, result):
        self.close()
        if self.selection_future and not self.selection_future.done():
            self.selection_future.set_result(result)

    def cancel(self):
        self.close()
        if self.selection_future and not self.selection_future.done():
            self.selection_future.cancel()

    async def capture(self):
        if self.busy:
            raise RuntimeError("已有一次截图 OCR 正在进行。")
        self.busy = True
        try:
            selection = await on_main(self.choose)
            display_id, rect = await asyncio.wrap_future(selection)
            await asyncio.sleep(0.08)
            image = await self.image(display_id, rect)
            return await asyncio.to_thread(self.recognize, image)
        finally:
            self.busy = False
            await on_main(self.close)

    async def image(self, display_id, rect):
        loop = asyncio.get_running_loop()

        async def callback_result(register):
            future = loop.create_future()

            def callback(value, error):
                def finish():
                    if future.done():
                        return
                    if error:
                        future.set_exception(RuntimeError(str(error.localizedDescription())))
                    elif value is None:
                        future.set_exception(RuntimeError("没有截取到屏幕图像。"))
                    else:
                        future.set_result(value)
                loop.call_soon_threadsafe(finish)

            register(callback)
            return await future

        content = await callback_result(lambda cb: SC.SCShareableContent.
                                        getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                                            False, True, cb))
        display = next((d for d in content.displays() if d.displayID() == display_id), None)
        if display is None:
            raise RuntimeError("所选显示器已断开。")
        own = [w for w in content.windows() if w.owningApplication() and
               w.owningApplication().processID() == NSProcessInfo.processInfo().processIdentifier()]
        content_filter = SC.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, own)
        source, pixels = ocr_rect((rect.origin.x, rect.origin.y, rect.size.width, rect.size.height),
                                  display.height(), content_filter.pointPixelScale())
        config = SC.SCStreamConfiguration.alloc().init()
        config.setSourceRect_(A.NSMakeRect(*source))
        config.setWidth_(max(1, pixels[0]))
        config.setHeight_(max(1, pixels[1]))
        config.setShowsCursor_(False)
        config.setCapturesAudio_(False)
        return await callback_result(lambda cb: SC.SCScreenshotManager.
                                     captureImageWithFilter_configuration_completionHandler_(content_filter, config, cb))

    @staticmethod
    def recognize(image):
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        request.setAutomaticallyDetectsLanguage_(True)
        request.setMinimumTextHeight_(0)
        supported, _ = request.supportedRecognitionLanguagesAndReturnError_(None)
        preferred = ["zh-Hans", "zh-Hant", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES", "it-IT", "pt-BR"]
        languages = [code for code in preferred if code in (supported or [])]
        if languages:
            request.setRecognitionLanguages_(languages)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, NSDictionary.dictionary())
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(str(error.localizedDescription()) if error else "OCR 识别失败。")
        observations = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                box = observation.boundingBox()
                observations.append((box.origin.y + box.size.height / 2, box.origin.x, str(candidates[0].string())))
        # Group into rows before horizontal sorting; avoids a nontransitive fuzzy comparator.
        observations.sort(key=lambda item: -item[0])
        rows = []
        for observation in observations:
            if rows and abs(rows[-1][0][0] - observation[0]) < 0.018:
                rows[-1].append(observation)
            else:
                rows.append([observation])
        text = "\n".join(item[2] for row in rows for item in sorted(row, key=lambda item: item[1])).strip()
        if not text:
            raise RuntimeError("没有识别到文字。")
        return text
