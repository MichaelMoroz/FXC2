"""Exercises bin/d3dcompiler_47.dll (the vkd3d based drop-in) through the
same entry points an engine or tool would call."""
import ctypes
import os
import sys
from ctypes import POINTER, byref, c_char_p, c_size_t, c_uint, c_void_p, c_wchar_p

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import d3d11  # noqa: E402

SOURCE = b"""
#include "common.hlsli"
float4 main(float4 pos : SV_Position) : SV_Target { return tint * SCALE; }
"""


def blob_bytes(blob):
    ptr = d3d11._call(blob, 3, c_void_p)
    size = d3d11._call(blob, 4, c_size_t)
    return ctypes.string_at(ptr, size)


def main():
    dll = ctypes.WinDLL(os.path.join(ROOT, "bin", "d3dcompiler_47.dll"))
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    src = os.path.join(ROOT, "out", "_dll_test.hlsl")
    with open(os.path.join(ROOT, "out", "common.hlsli"), "w") as f:
        f.write("cbuffer C { float4 tint; };\n")
    with open(src, "wb") as f:
        f.write(SOURCE)

    class Macro(ctypes.Structure):
        _fields_ = [("name", c_char_p), ("definition", c_char_p)]
    macros = (Macro * 2)(Macro(b"SCALE", b"2.0"), Macro(None, None))

    code, errors = c_void_p(), c_void_p()
    dll.D3DCompileFromFile.argtypes = [c_wchar_p, c_void_p, c_void_p, c_char_p, c_char_p, c_uint, c_uint,
                                       POINTER(c_void_p), POINTER(c_void_p)]
    # (ID3DInclude *)1 is D3D_COMPILE_STANDARD_FILE_INCLUDE.
    hr = dll.D3DCompileFromFile(src, macros, c_void_p(1), b"main", b"ps_5_0", 0, 0, byref(code), byref(errors))
    if errors:
        print(blob_bytes(errors).decode(errors="replace"))
    assert hr == 0, "D3DCompileFromFile failed: 0x%08x" % (hr & 0xffffffff)
    dxbc = blob_bytes(code)
    assert dxbc[:4] == b"DXBC"

    hr = d3d11.Device().check("ps", dxbc)
    assert hr == 0, "D3D11 rejected the shader: 0x%08x" % hr

    text = c_void_p()
    dll.D3DDisassemble.argtypes = [c_char_p, c_size_t, c_uint, c_char_p, POINTER(c_void_p)]
    assert dll.D3DDisassemble(dxbc, len(dxbc), 0, None, byref(text)) == 0
    assert b"ps_5_0" in blob_bytes(text)

    # ID3D11ShaderReflection
    iid = (ctypes.c_ubyte * 16).from_buffer_copy(
        (0x8d536ca1).to_bytes(4, "little") + (0x0cca).to_bytes(2, "little") + (0x4956).to_bytes(2, "little")
        + bytes([0xa8, 0x37, 0x78, 0x69, 0x63, 0x75, 0x55, 0x84]))
    refl = c_void_p()
    dll.D3DReflect.argtypes = [c_char_p, c_size_t, c_void_p, POINTER(c_void_p)]
    hr = dll.D3DReflect(dxbc, len(dxbc), iid, byref(refl))
    assert hr == 0 and refl, "D3DReflect failed: 0x%08x" % (hr & 0xffffffff)

    print("d3dcompiler_47.dll drop-in: compile (file include + macros), D3D11 load, disassemble, reflect OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
