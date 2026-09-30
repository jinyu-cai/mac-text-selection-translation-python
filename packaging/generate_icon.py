"""Rebuild the English app icon using native vector drawing; no external assets."""
from pathlib import Path
import subprocess
import tempfile

import AppKit as A
from Foundation import NSString


def draw(size):
    image = A.NSImage.alloc().initWithSize_(A.NSMakeSize(size, size))
    image.lockFocus()
    transform = A.NSAffineTransform.transform()
    transform.scaleBy_(size / 1024)
    transform.concat()
    background = A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        A.NSMakeRect(80, 80, 864, 864), 194, 194)
    gradient = A.NSGradient.alloc().initWithStartingColor_endingColor_(
        A.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.24, 0.42, 1),
        A.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.04, 0.10, 0.20, 1))
    gradient.drawInBezierPath_angle_(background, -90)
    letter = NSString.stringWithString_("T")
    attrs = {A.NSFontAttributeName: A.NSFont.systemFontOfSize_weight_(570, A.NSFontWeightMedium),
             A.NSForegroundColorAttributeName: A.NSColor.whiteColor()}
    width = letter.sizeWithAttributes_(attrs).width
    letter.drawAtPoint_withAttributes_(A.NSMakePoint((1024 - width) / 2, 258), attrs)
    A.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.43, 0.77, 1, 1).setStroke()
    for points in (((310, 278), (714, 278), (665, 327)), ((714, 196), (310, 196), (359, 147))):
        line = A.NSBezierPath.bezierPath()
        line.moveToPoint_(A.NSMakePoint(*points[0]))
        line.lineToPoint_(A.NSMakePoint(*points[1]))
        line.lineToPoint_(A.NSMakePoint(*points[2]))
        line.setLineWidth_(23)
        line.setLineCapStyle_(A.NSRoundLineCapStyle)
        line.setLineJoinStyle_(A.NSRoundLineJoinStyle)
        line.stroke()
    image.unlockFocus()
    bitmap = A.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    return bitmap.representationUsingType_properties_(A.NSBitmapImageFileTypePNG, {})


if __name__ == "__main__":
    destination = Path(__file__).with_name("Translator.icns").resolve()
    with tempfile.TemporaryDirectory(prefix="translator-icon-") as temp:
        iconset = Path(temp) / "Translator.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                # NSImage drawing follows the current display scale; encode exact pixel sizes.
                data = draw(size * scale)
                target = iconset / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                data.writeToFile_atomically_(str(target), True)
                subprocess.run(["sips", "-z", str(size * scale), str(size * scale), str(target)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(destination)], check=True)
    print(destination)
