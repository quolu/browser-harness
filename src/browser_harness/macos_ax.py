"""Press Chrome's Allow sheet through the Accessibility API of one process.

System Events addresses processes by name, so with several Google Chrome
instances running, AppleScript reaches only one of them. AXUIElementCreateApplication
takes the pid, which lets mac-approve answer the prompt of the exact instance
the daemon is waiting on.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import (
    POINTER,
    c_bool,
    c_char_p,
    c_float,
    c_int,
    c_int32,
    c_long,
    c_uint32,
    c_ulong,
    c_void_p,
)

_UTF8 = 0x08000100
_AX_SUCCESS = 0
_AX_API_DISABLED = -25211
_MAX_DEPTH = 16
_MESSAGING_TIMEOUT = 2.0
_WALK_BUDGET = 5.0


class AccessibilityDenied(Exception):
    pass


def _load():
    cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ax = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFStringGetLength.argtypes = [c_void_p]
    cf.CFStringGetLength.restype = c_long
    cf.CFStringGetMaximumSizeForEncoding.argtypes = [c_long, c_uint32]
    cf.CFStringGetMaximumSizeForEncoding.restype = c_long
    cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, c_uint32]
    cf.CFStringGetCString.restype = c_bool
    cf.CFGetTypeID.argtypes = [c_void_p]
    cf.CFGetTypeID.restype = c_ulong
    cf.CFStringGetTypeID.restype = c_ulong
    cf.CFArrayGetTypeID.restype = c_ulong
    cf.CFArrayGetCount.argtypes = [c_void_p]
    cf.CFArrayGetCount.restype = c_long
    cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
    cf.CFArrayGetValueAtIndex.restype = c_void_p
    cf.CFRelease.argtypes = [c_void_p]
    ax.AXIsProcessTrusted.restype = c_bool
    ax.AXUIElementCreateApplication.argtypes = [c_int]
    ax.AXUIElementCreateApplication.restype = c_void_p
    ax.AXUIElementCopyAttributeValue.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
    ax.AXUIElementCopyAttributeValue.restype = c_int32
    ax.AXUIElementPerformAction.argtypes = [c_void_p, c_void_p]
    ax.AXUIElementPerformAction.restype = c_int32
    ax.AXUIElementSetMessagingTimeout.argtypes = [c_void_p, c_float]
    ax.AXUIElementSetMessagingTimeout.restype = c_int32
    return cf, ax


class _Session:
    """Owns every CF object it copies and releases them on close."""

    def __init__(self):
        self.cf, self.ax = _load()
        self._owned = []
        self._keys = {}
        self._deadline = time.monotonic() + _WALK_BUDGET

    def close(self):
        for ref in reversed(self._owned):
            self.cf.CFRelease(ref)
        self._owned.clear()

    def _own(self, ref):
        if ref:
            self._owned.append(ref)
        return ref

    def _key(self, name):
        if name not in self._keys:
            self._keys[name] = self._own(self.cf.CFStringCreateWithCString(None, name.encode(), _UTF8))
        return self._keys[name]

    def application(self, pid):
        app = self._own(self.ax.AXUIElementCreateApplication(pid))
        self.ax.AXUIElementSetMessagingTimeout(app, _MESSAGING_TIMEOUT)
        return app

    def _copy(self, element, name):
        if time.monotonic() > self._deadline:
            raise TimeoutError(f"the Accessibility walk took longer than {_WALK_BUDGET:g}s")
        value = c_void_p()
        err = self.ax.AXUIElementCopyAttributeValue(element, self._key(name), ctypes.byref(value))
        if err == _AX_API_DISABLED:
            raise AccessibilityDenied
        if err != _AX_SUCCESS or not value.value:
            return None
        return self._own(value.value)

    def string(self, element, name):
        ref = self._copy(element, name)
        if ref is None or self.cf.CFGetTypeID(ref) != self.cf.CFStringGetTypeID():
            return ""
        size = self.cf.CFStringGetMaximumSizeForEncoding(self.cf.CFStringGetLength(ref), _UTF8) + 1
        buffer = ctypes.create_string_buffer(size)
        if not self.cf.CFStringGetCString(ref, buffer, size, _UTF8):
            return ""
        return buffer.value.decode("utf-8", errors="replace")

    def elements(self, element, name):
        ref = self._copy(element, name)
        if ref is None or self.cf.CFGetTypeID(ref) != self.cf.CFArrayGetTypeID():
            return []
        return [self.cf.CFArrayGetValueAtIndex(ref, i) for i in range(self.cf.CFArrayGetCount(ref))]

    def press(self, element):
        err = self.ax.AXUIElementPerformAction(element, self._key("AXPress"))
        if err == _AX_API_DISABLED:
            raise AccessibilityDenied
        return err == _AX_SUCCESS


def _has_allow_heading(session, element, titles, depth=0):
    if depth > _MAX_DEPTH:
        return False
    if session.string(element, "AXRole") == "AXHeading" and any(
        session.string(element, attr) in titles for attr in ("AXTitle", "AXDescription", "AXValue")
    ):
        return True
    return any(_has_allow_heading(session, child, titles, depth + 1) for child in session.elements(element, "AXChildren"))


def _is_allow_sheet(session, sheet, titles):
    return session.string(sheet, "AXTitle") in titles or _has_allow_heading(session, sheet, titles)


def _press_allow(session, element, labels, depth=0):
    if depth > _MAX_DEPTH:
        return False
    if session.string(element, "AXRole") == "AXButton":
        label = session.string(element, "AXDescription") or session.string(element, "AXTitle")
        return label in labels and session.press(element)
    return any(_press_allow(session, child, labels, depth + 1) for child in session.elements(element, "AXChildren"))


def press_allow_sheet(pid, titles, labels):
    """Press the exact Allow button on an exact Allow sheet of process `pid`.

    Returns "ready" after a press and "not-found" when that process shows no
    such sheet. Raises AccessibilityDenied when this process lacks
    Accessibility access.
    """
    session = _Session()
    try:
        if not session.ax.AXIsProcessTrusted():
            raise AccessibilityDenied
        app = session.application(pid)
        for window in session.elements(app, "AXWindows"):
            for child in session.elements(window, "AXChildren"):
                if session.string(child, "AXRole") != "AXSheet":
                    continue
                if _is_allow_sheet(session, child, titles) and _press_allow(session, child, labels):
                    return "ready"
        return "not-found"
    finally:
        session.close()
