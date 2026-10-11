"""Register the interpreter's NVIDIA DLLs for this Windows process only."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

import ctypes
import logging
import os
import sys
from pathlib import Path


# AddDllDirectory registrations must outlive all model loads and native calls.
# Keep native libraries too, including the cuDNN core matching its companion DLLs.
_directory_handles: dict[Path, object] = {}
_libraries: dict[Path, object] = {}
_search_configured = False


def configure_cuda_dlls() -> tuple[Path, ...]:
    """Called lazily in the worker, before importing Faster Whisper/CTranslate2."""
    global _search_configured
    if sys.platform != "win32":
        return ()
    nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    directories = tuple((nvidia / package / "bin").resolve()
                        for package in ("cublas", "cudnn", "cuda_nvrtc")
                        if (nvidia / package / "bin").is_dir())
    if not directories:
        return ()  # A system runtime may still be available; retain CPU fallback.
    if not _search_configured:
        # Native libraries also use unqualified LoadLibrary calls. Enable the
        # registered directories for those calls, without changing any PATH.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        set_directories = kernel32.SetDefaultDllDirectories
        set_directories.argtypes = [ctypes.c_uint32]
        set_directories.restype = ctypes.c_int
        if not set_directories(0x00001000):  # LOAD_LIBRARY_SEARCH_DEFAULT_DIRS
            raise ctypes.WinError(ctypes.get_last_error())
        _search_configured = True
    for directory in directories:
        if directory not in _directory_handles:
            _directory_handles[directory] = os.add_dll_directory(str(directory))
            logging.getLogger(__name__).info("Registered NVIDIA DLL directory: %s", directory)
    for package, name in (("cublas", "cublas64_12.dll"), ("cudnn", "cudnn64_9.dll")):
        library = (nvidia / package / "bin" / name).resolve()
        if library.is_file() and library not in _libraries:
            # Prefer the installed NVIDIA cuDNN core before CTranslate2 imports
            # its bundled core, which may be older than the companion libraries.
            _libraries[library] = ctypes.WinDLL(str(library))
    return directories
