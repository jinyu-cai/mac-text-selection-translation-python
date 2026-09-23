import asyncio
import ctypes as C
import math

import AppKit as A
import ApplicationServices as AX
import Quartz as Q
from Foundation import NSObject
from PyObjCTools import AppHelper

from mactranslator.policies import capture_clipboard, likely_selection, should_restore


async def on_main(function):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def invoke():
        if future.cancelled():
            return
        try:
            result = function()
        except Exception as exc:
            loop.call_soon_threadsafe(finish, None, exc)
        else:
            loop.call_soon_threadsafe(finish, result, None)

    def finish(value, error):
        if not future.done():
            future.set_exception(error) if error else future.set_result(value)

    AppHelper.callAfter(invoke)
    return await future


def alert(message, title="划词翻译"):
    panel = A.NSAlert.alloc().init()
    panel.setMessageText_(title)
    panel.setInformativeText_(str(message))
    panel.addButtonWithTitle_("好")
    panel.runModal()


def copy_text(text):
    pb = A.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, A.NSPasteboardTypeString)


def accessibility_allowed(prompt=False):
    return AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: prompt})


def selected_text():
    status, focused = AX.AXUIElementCopyAttributeValue(
        AX.AXUIElementCreateSystemWide(), AX.kAXFocusedUIElementAttribute, None)
    if status or focused is None:
        return None
    status, selected = AX.AXUIElementCopyAttributeValue(focused, AX.kAXSelectedTextAttribute, None)
    if status or selected is None:
        return None
    if hasattr(selected, "string"):
        selected = selected.string()
    return str(selected).strip() or None


def simulate_copy():
    source = Q.CGEventSourceCreate(Q.kCGEventSourceStateCombinedSessionState)
    Q.CGEventSourceSetLocalEventsSuppressionInterval(source, 0)
    for state in (Q.kCGEventSuppressionStateSuppressionInterval, Q.kCGEventSuppressionStateRemoteMouseDrag):
        Q.CGEventSourceSetLocalEventsFilterDuringSuppressionState(source, Q.kCGEventFilterMaskPermitAllEvents, state)
    for down in (True, False):
        event = Q.CGEventCreateKeyboardEvent(source, 8, down)
        Q.CGEventSetFlags(event, Q.kCGEventFlagMaskCommand)
        Q.CGEventPost(Q.kCGHIDEventTap, event)


def snapshot_clipboard():
    items = []
    for item in A.NSPasteboard.generalPasteboard().pasteboardItems() or []:
        clone = A.NSPasteboardItem.alloc().init()
        for kind in item.types():
            data = item.dataForType_(kind)
            if data is not None:
                clone.setData_forType_(data, kind)
        if clone.types():
            items.append(clone)
    return items


async def capture_selection(restore=True):
    for _ in range(40):
        if not await on_main(A.NSEvent.pressedMouseButtons):
            break
        await asyncio.sleep(0.025)
    await asyncio.sleep(0.08)
    text = await on_main(selected_text)
    if text:
        return text
    saved = await on_main(snapshot_clipboard) if restore else None
    # All pasteboard operations execute on the main thread. Poll data into a snapshot
    # consumed by the pure async policy, preserving its cancellation/restore behavior.
    state = {}

    def sample():
        pb = A.NSPasteboard.generalPasteboard()
        return {"count": pb.changeCount(), "text": pb.stringForType_(A.NSPasteboardTypeString)}

    state.update(await on_main(sample))

    async def pause():
        if state.pop("copy", False):
            await on_main(simulate_copy)
        await asyncio.sleep(0.015)
        state.update(await on_main(sample))

    result = await capture_clipboard(lambda: state["count"], lambda: state["text"],
                                     lambda: state.update(copy=True), pause)
    if saved is not None and result:
        def restore_if_unchanged():
            pb = A.NSPasteboard.generalPasteboard()
            if should_restore(result[1], pb.changeCount()):
                pb.clearContents()
                if saved:
                    pb.writeObjects_(saved)
        await on_main(restore_if_unchanged)
    return result[0] if result else None


class Action(NSObject):
    def invoke_(self, sender):
        try:
            self.callback(sender)
        except Exception as exc:
            alert(str(exc))


def bind(control, callback, targets):
    target = Action.alloc().init()
    target.callback = callback
    targets.append(target)
    control.setTarget_(target)
    control.setAction_("invoke:")
    return control


class Hotkeys:
    """Carbon hotkeys retain the Swift app's permission-free registration behavior."""
    class Spec(C.Structure):
        _fields_ = [("eventClass", C.c_uint32), ("eventKind", C.c_uint32)]

    class ID(C.Structure):
        _fields_ = [("signature", C.c_uint32), ("id", C.c_uint32)]

    def __init__(self):
        self.lib = C.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        self.refs = []
        self.callbacks = {}
        self.handler = C.c_void_p()
        self.callback_type = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.c_void_p, C.c_void_p)
        self.callback = self.callback_type(self._fire)
        signatures = {
            "GetEventDispatcherTarget": (C.c_void_p, []),
            "InstallEventHandler": (C.c_int32, [C.c_void_p, self.callback_type, C.c_uint32,
                                                 C.POINTER(self.Spec), C.c_void_p, C.POINTER(C.c_void_p)]),
            "RegisterEventHotKey": (C.c_int32, [C.c_uint32, C.c_uint32, self.ID, C.c_void_p,
                                                 C.c_uint32, C.POINTER(C.c_void_p)]),
            "UnregisterEventHotKey": (C.c_int32, [C.c_void_p]),
            "RemoveEventHandler": (C.c_int32, [C.c_void_p]),
            "GetEventParameter": (C.c_int32, [C.c_void_p, C.c_uint32, C.c_uint32, C.c_void_p,
                                               C.c_uint32, C.c_void_p, C.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            func = getattr(self.lib, name)
            func.restype, func.argtypes = result, args

    def _fire(self, call, event, userdata):
        key = self.ID()
        status = self.lib.GetEventParameter(event, int.from_bytes(b"----"), int.from_bytes(b"hkid"),
                                            None, C.sizeof(key), None, C.byref(key))
        if not status and key.id in self.callbacks:
            AppHelper.callAfter(self.callbacks[key.id])
        return 0

    def configure(self, bindings):
        self.stop()
        if not bindings:
            return
        spec = self.Spec(int.from_bytes(b"keyb"), 6)
        target = self.lib.GetEventDispatcherTarget()
        status = self.lib.InstallEventHandler(target, self.callback, 1, C.byref(spec), None, C.byref(self.handler))
        if status:
            raise RuntimeError(f"无法注册快捷键处理器（{status}）")
        for index, (hotkey, callback) in enumerate(bindings, 1):
            modifiers = sum(carbon for native, carbon in ((1 << 20, 256), (1 << 17, 512),
                                                           (1 << 19, 2048), (1 << 18, 4096))
                            if hotkey.modifiers & native)
            ref = C.c_void_p()
            status = self.lib.RegisterEventHotKey(hotkey.key_code, modifiers,
                                                  self.ID(0x4D545250, index), target, 0, C.byref(ref))
            if status:
                self.stop()
                raise RuntimeError(f"快捷键已被占用或无法注册（{status}）。请更换快捷键。")
            self.refs.append(ref)
            self.callbacks[index] = callback

    def stop(self):
        for ref in self.refs:
            self.lib.UnregisterEventHotKey(ref)
        self.refs.clear()
        self.callbacks.clear()
        if self.handler.value:
            self.lib.RemoveEventHandler(self.handler)
            self.handler = C.c_void_p()


class SelectionWatcher:
    def __init__(self, selection, dismiss):
        self.selection, self.dismiss = selection, dismiss
        self.monitors = []
        self.start_point = (0, 0)
        self.dragged = False
        self.generation = 0

    def start(self):
        self.stop()
        mask = A.NSEventMaskLeftMouseDown | A.NSEventMaskLeftMouseDragged | A.NSEventMaskLeftMouseUp
        monitor = A.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self.event)
        if monitor is not None:
            self.monitors.append(monitor)

    def event(self, event):
        point = A.NSEvent.mouseLocation()
        if event.type() == A.NSEventTypeLeftMouseDown:
            self.generation += 1
            self.start_point, self.dragged = tuple(point), False
            self.dismiss()
        elif event.type() == A.NSEventTypeLeftMouseDragged:
            self.dragged = True
        else:
            distance = math.hypot(point.x - self.start_point[0], point.y - self.start_point[1])
            if likely_selection(self.dragged, distance, event.clickCount()):
                generation = self.generation
                AppHelper.callLater(0.05, lambda: self.selection(point) if generation == self.generation else None)

    def stop(self):
        self.generation += 1
        for monitor in self.monitors:
            A.NSEvent.removeMonitor_(monitor)
        self.monitors.clear()


def login_status():
    from ServiceManagement import SMAppService
    return SMAppService.mainAppService().status()


def set_login(enabled):
    from ServiceManagement import SMAppService, SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval
    service = SMAppService.mainAppService()
    registered = service.status() in (SMAppServiceStatusEnabled, SMAppServiceStatusRequiresApproval)
    if enabled != registered:
        ok, error = service.registerAndReturnError_(None) if enabled else service.unregisterAndReturnError_(None)
        if not ok:
            raise RuntimeError(str(error.localizedDescription()) if error else "无法更新登录项。请使用打包后的应用。")
    if service.status() == SMAppServiceStatusRequiresApproval:
        SMAppService.openSystemSettingsLoginItems()
