"""py2app entry point; package metadata/dependencies live in pyproject.toml."""
from setuptools import setup
from py2app.build_app import py2app
import zlib


class PortablePythonBundle(py2app):
    """py2app 0.28 assumes zlib is a .so; uv's Python links it into libpython.

    The bundled shared libpython already supplies the builtin. Skip only that
    nonexistent extension copy; standard python.org installations use py2app unchanged.
    """
    def build_executable(self, *args, **kwargs):
        builtin = not hasattr(zlib, "__file__")
        if builtin:
            zlib.__file__ = "<builtin-zlib>"
        try:
            return super().build_executable(*args, **kwargs)
        finally:
            if builtin:
                del zlib.__file__

    def copy_file(self, source, destination, *args, **kwargs):
        if source == "<builtin-zlib>":
            return destination, False
        return super().copy_file(source, destination, *args, **kwargs)

setup(
    cmdclass={"py2app": PortablePythonBundle},
    name="Text Selection Translation Python",
    version="0.1.0",
    app=["../launcher.py"],
    options={"py2app": {
        "argv_emulation": False,
        "strip": False,
        "packages": ["mactranslator", "uvicorn", "fastapi", "starlette", "pydantic", "httpx",
                     "httpcore", "anyio", "markdown_it", "mdurl", "certifi"],
        "includes": ["uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
                     "uvicorn.lifespan.on", "anyio._backends._asyncio", "sqlite3"],
        "excludes": ["pytest", "ruff", "tkinter"],
        "plist": {
            "CFBundleName": "Text Selection Translation Python",
            "CFBundleDisplayName": "Text Selection Translation Python",
            "CFBundleIdentifier": "com.example.mactranslator.python",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "14.0",
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "NSScreenCaptureUsageDescription": "框选屏幕文字，使用本机 OCR 识别后翻译。",
        },
    }},
)
