import AppKit as A
import unicodedata
from Foundation import NSAttributedString, NSMutableAttributedString
from markdown_it import MarkdownIt

from .native import bind


def label(parent, text, x, y, w=200, h=24):
    view = A.NSTextField.labelWithString_(text)
    view.setFrame_(A.NSMakeRect(x, y, w, h))
    parent.addSubview_(view)
    return view


def field(parent, x, y, w, value="", secure=False):
    cls = A.NSSecureTextField if secure else A.NSTextField
    view = cls.alloc().initWithFrame_(A.NSMakeRect(x, y, w, 26))
    view.setStringValue_(value)
    parent.addSubview_(view)
    return view


def button(parent, title, x, y, w, callback, targets):
    view = A.NSButton.alloc().initWithFrame_(A.NSMakeRect(x, y, w, 30))
    view.setTitle_(title)
    view.setBezelStyle_(A.NSBezelStyleRounded)
    bind(view, callback, targets)
    parent.addSubview_(view)
    return view


def check(parent, title, x, y, w, value=False, callback=None, targets=None):
    view = A.NSButton.alloc().initWithFrame_(A.NSMakeRect(x, y, w, 25))
    view.setButtonType_(A.NSButtonTypeSwitch)
    view.setTitle_(title)
    view.setState_(1 if value else 0)
    if callback:
        bind(view, callback, targets)
    parent.addSubview_(view)
    return view


def choice(parent, options, x, y, w, callback=None, targets=None):
    view = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(A.NSMakeRect(x, y, w, 28), False)
    view.addItemsWithTitles_(options)
    if callback:
        bind(view, callback, targets)
    parent.addSubview_(view)
    return view


def text_area(parent, x, y, w, h, editable=False):
    scroll = A.NSScrollView.alloc().initWithFrame_(A.NSMakeRect(x, y, w, h))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(A.NSBezelBorder)
    text = A.NSTextView.alloc().initWithFrame_(A.NSMakeRect(0, 0, w - 18, h))
    text.setEditable_(editable)
    text.setSelectable_(True)
    text.setRichText_(not editable)
    text.setFont_(A.NSFont.systemFontOfSize_(14))
    text.setTextContainerInset_(A.NSMakeSize(10, 10))
    text.setVerticallyResizable_(True)
    text.setHorizontallyResizable_(False)
    text.setAutoresizingMask_(A.NSViewWidthSizable)
    text.textContainer().setWidthTracksTextView_(True)
    text.textContainer().setContainerSize_(A.NSMakeSize(w - 18, 1e7))
    if editable:
        text.setAutomaticQuoteSubstitutionEnabled_(False)
        text.setAutomaticDashSubstitutionEnabled_(False)
    scroll.setDocumentView_(text)
    parent.addSubview_(scroll)
    return text, scroll


def window(title, width, height):
    style = A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable
    value = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        A.NSMakeRect(0, 0, width, height), style, A.NSBackingStoreBuffered, False)
    value.setReleasedWhenClosed_(False)
    value.setTitle_(title)
    value.center()
    return value


_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")


def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def attributed_markdown(source):
    """Native selectable attributed text; Markdown is never executed as HTML."""
    output = NSMutableAttributedString.alloc().init()
    base = {A.NSFontAttributeName: A.NSFont.systemFontOfSize_(14),
            A.NSForegroundColorAttributeName: A.NSColor.labelColor()}
    bold = dict(base, **{A.NSFontAttributeName: A.NSFont.boldSystemFontOfSize_(14)})
    mono = dict(base, **{A.NSFontAttributeName: A.NSFont.monospacedSystemFontOfSize_weight_(12, 0)})

    def append(text, attrs=None):
        output.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(text, attrs or base))

    table = None
    row = None
    heading = False
    list_depth = 0
    for token in _markdown.parse(source):
        kind = token.type
        if kind == "table_open":
            table = []
        elif kind == "tr_open":
            row = []
        elif kind == "tr_close" and table is not None:
            table.append(row)
        elif kind == "table_close":
            widths = [max(display_width(r[i]) if i < len(r) else 0 for r in table)
                      for i in range(max(map(len, table), default=0))]
            for i, r in enumerate(table):
                append(" | ".join(cell + " " * (widths[j] - display_width(cell)) for j, cell in enumerate(r)) + "\n", mono)
                if i == 0:
                    append("-+-".join("-" * width for width in widths) + "\n", mono)
            table = None
            append("\n")
        elif kind in ("fence", "code_block"):
            append(token.content + "\n", mono)
        elif kind == "heading_open":
            heading = True
        elif kind == "heading_close":
            heading = False
            append("\n")
        elif kind in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif kind in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
        elif kind == "list_item_open":
            append("  " * max(0, list_depth - 1) + "• ")
        elif kind == "paragraph_close" and table is None:
            append("\n" if list_depth else "\n\n")
        elif kind == "hr":
            append("────────────────────────\n")
        elif kind == "inline":
            if table is not None:
                row.append("".join(c.content if c.type not in ("softbreak", "hardbreak") else " "
                                   for c in token.children or [] if c.nesting == 0))
                continue
            strong, emphasis, link = 0, 0, None
            for child in token.children or []:
                if child.type == "strong_open":
                    strong += 1
                elif child.type == "strong_close":
                    strong -= 1
                elif child.type == "em_open":
                    emphasis += 1
                elif child.type == "em_close":
                    emphasis -= 1
                elif child.type == "link_open":
                    link = child.attrGet("href")
                elif child.type == "link_close":
                    link = None
                elif child.type in ("softbreak", "hardbreak"):
                    append("\n")
                elif child.type == "code_inline":
                    append(child.content, mono)
                elif child.nesting == 0:
                    attrs = dict(bold if strong or heading else base)
                    if emphasis:
                        attrs[A.NSFontAttributeName] = A.NSFontManager.sharedFontManager().convertFont_toHaveTrait_(
                            attrs[A.NSFontAttributeName], A.NSItalicFontMask)
                    if link and link.startswith(("https://", "http://")):
                        attrs[A.NSLinkAttributeName] = link
                    append(child.content, attrs)
    return output
