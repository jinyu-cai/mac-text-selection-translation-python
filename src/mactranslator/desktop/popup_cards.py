"""Native output cards matching the original popup's source/result controls."""
import math

import AppKit as A
from Foundation import NSAttributedString

from . import widgets as W
from .native import copy_text


class TopDownView(A.NSView):
    def isFlipped(self):
        return True


class CardView(TopDownView):
    def drawRect_(self, dirty):
        A.NSColor.labelColor().colorWithAlphaComponent_(0.04).setFill()
        A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 8, 8).fill()


def icon_button(parent, symbol, title, callback, targets):
    button = W.symbol_button(parent, symbol, title, 0, 0, callback, targets)
    button.setBordered_(False)
    button.setFrameSize_(A.NSMakeSize(24, 24))
    button.setContentTintColor_(A.NSColor.secondaryLabelColor())
    return button


def spinner(parent):
    view = A.NSProgressIndicator.alloc().initWithFrame_(A.NSMakeRect(0, 0, 16, 16))
    view.setStyle_(A.NSProgressIndicatorStyleSpinning)
    view.setControlSize_(A.NSControlSizeSmall)
    view.setDisplayedWhenStopped_(False)
    parent.addSubview_(view)
    return view


def body_view(parent):
    text = A.NSTextView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 100, 24))
    text.setEditable_(False)
    text.setSelectable_(True)
    text.setDrawsBackground_(False)
    text.setTextContainerInset_(A.NSMakeSize(0, 0))
    text.setVerticallyResizable_(False)
    text.setHorizontallyResizable_(False)
    text.textContainer().setLineFragmentPadding_(0)
    text.textContainer().setWidthTracksTextView_(True)
    parent.addSubview_(text)
    return text


class OutputCard:
    def __init__(self, app, source=False):
        self.app, self.source = app, source
        self.targets = []
        self.view = (TopDownView if source else CardView).alloc().initWithFrame_(A.NSMakeRect(0, 0, 100, 40))
        self.output = ""
        self.cached_content = None
        self.title = W.label(self.view, "", 8, 8, 200, 20)
        self.title.setFont_(A.NSFont.systemFontOfSize_weight_(12, A.NSFontWeightSemibold))
        self.title.setTextColor_(A.NSColor.secondaryLabelColor())
        self.title.setLineBreakMode_(A.NSLineBreakByTruncatingTail)
        self.title.setHidden_(source)
        self.progress = spinner(self.view)
        self.speak = icon_button(self.view, "speaker.wave.2", "Speak Source" if source else "Speak Translation",
                                 lambda _: self.app.speak(self.output), self.targets)
        self.speech_progress = spinner(self.view)
        self.copy = None if source else icon_button(self.view, "doc.on.doc", "Copy Translation",
                                                    lambda _: copy_text(self.output), self.targets)
        self.text = body_view(self.view)

    def update(self, title, output, loading=False, error=None):
        self.output = output
        self.title.setStringValue_(title)
        self.title.setToolTip_(title)
        self.loading = loading
        (self.progress.startAnimation_ if loading else self.progress.stopAnimation_)(None)
        self.refresh_speech()
        if self.copy:
            self.copy.setEnabled_(bool(output.strip()))
        value = error or output or ("Translating…" if loading else "")
        content = (value, bool(error), bool(output))
        if self.cached_content != content:
            if self.source or error or not output:
                color = (A.NSColor.systemRedColor() if error else
                         A.NSColor.labelColor() if self.source else A.NSColor.secondaryLabelColor())
                attributed = NSAttributedString.alloc().initWithString_attributes_(value, {
                    A.NSFontAttributeName: A.NSFont.systemFontOfSize_(13), A.NSForegroundColorAttributeName: color})
            else:
                attributed = W.attributed_markdown(value)
                while attributed.length() and str(attributed.string()).endswith("\n"):
                    attributed.deleteCharactersInRange_((attributed.length() - 1, 1))
            self.text.textStorage().setAttributedString_(attributed)
            self.cached_content = content

    def refresh_speech(self):
        cloud = any(p.enabled and p.kind in ("openai_tts", "dashscope_tts") for p in self.app.settings.providers)
        busy = cloud and getattr(self.app, "speech_preparing", False)
        image = W.symbol("waveform" if cloud else "speaker.wave.2", "Speak")
        if image:
            self.speak.setImage_(image)
        self.speak.setEnabled_(bool(self.output.strip()))
        self.speak.setHidden_(busy)
        (self.speech_progress.startAnimation_ if busy else self.speech_progress.stopAnimation_)(None)

    def layout(self, width):
        padding = 0 if self.source else 8
        text_width = max(1, width - (32 if self.source else 2 * padding))
        text_y = 0 if self.source else 34
        self.text.setFrame_(A.NSMakeRect(padding, text_y, text_width, 24))
        container = self.text.textContainer()
        container.setContainerSize_(A.NSMakeSize(text_width, 1e7))
        self.text.layoutManager().ensureLayoutForTextContainer_(container)
        manager = self.text.layoutManager()
        used = manager.usedRectForTextContainer_(container)
        glyphs = manager.boundingRectForGlyphRange_inTextContainer_(
            manager.glyphRangeForTextContainer_(container), container)
        # Fallback-font subscripts can extend below the nominal line fragment.
        # Include their ink bounds and a small rounding margin in the text view.
        height = max(20, math.ceil(max(A.NSMaxY(used), A.NSMaxY(glyphs))) + 3)
        self.text.setFrameSize_(A.NSMakeSize(text_width, height))
        total = max(24, text_y + height + padding)
        self.view.setFrameSize_(A.NSMakeSize(width, total))
        speak_x = width - (24 if self.source else 60)
        control_y = 0 if self.source else 5
        self.speak.setFrameOrigin_(A.NSMakePoint(speak_x, control_y))
        self.speech_progress.setFrameOrigin_(A.NSMakePoint(speak_x + 4, control_y + 4))
        if not self.source:
            self.copy.setFrameOrigin_(A.NSMakePoint(width - 32, control_y))
            self.title.setFrame_(A.NSMakeRect(8, 8, max(1, width - 96), 20))
            title_width = min(self.title.attributedStringValue().size().width, width - 96)
            self.progress.setFrameOrigin_(A.NSMakePoint(12 + title_width, 10))
        return total
