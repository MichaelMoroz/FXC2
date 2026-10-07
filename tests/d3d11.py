"""Minimal ctypes D3D11 (WARP) wrapper used to validate DXBC blobs.

Only what the tests need: create shaders of every stage, and render a
fullscreen triangle with a given pixel shader + constant buffer into a
float RGBA target and read it back.
"""
import ctypes
import struct
from ctypes import POINTER, byref, c_float, c_int, c_size_t, c_uint, c_void_p, c_uint64

HRESULT = ctypes.c_long
D3D_DRIVER_TYPE_HARDWARE = 1
D3D_DRIVER_TYPE_WARP = 5
D3D11_SDK_VERSION = 7
DXGI_FORMAT_R32G32B32A32_FLOAT = 2

# vtable slots
DEV_CREATE_BUFFER, DEV_CREATE_TEX2D, DEV_CREATE_UAV, DEV_CREATE_RTV = 3, 5, 8, 9
DEV_CREATE = {"vs": 12, "gs": 13, "ps": 15, "hs": 16, "ds": 17, "cs": 18}
CTX_PS_SET_SHADER, CTX_VS_SET_SHADER, CTX_DRAW, CTX_MAP, CTX_UNMAP = 9, 11, 13, 14, 15
CTX_PS_SET_CB, CTX_IA_TOPOLOGY, CTX_OM_SET_RT, CTX_DISPATCH, CTX_RS_VIEWPORTS, CTX_COPY_RESOURCE = 16, 24, 33, 41, 44, 47
CTX_CS_SET_UAVS, CTX_CS_SET_SHADER = 68, 69


def _call(obj, slot, restype, *args):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    # Anything that is not a plain integer is some flavour of pointer.
    argtypes = [c_void_p] + [type(a) if isinstance(a, (c_uint, c_size_t)) else c_void_p for a in args]
    return ctypes.WINFUNCTYPE(restype, *argtypes)(vtbl[slot])(obj, *args)


def _release(obj):
    if obj:
        _call(obj, 2, c_uint)


class Device:
    def __init__(self, hardware=False):
        """WARP (software) by default; hardware=True uses the default GPU."""
        self.dev, self.ctx = c_void_p(), c_void_p()
        d3d11 = ctypes.WinDLL("d3d11")
        driver = D3D_DRIVER_TYPE_HARDWARE if hardware else D3D_DRIVER_TYPE_WARP
        hr = d3d11.D3D11CreateDevice(None, driver, None, 0, None, 0, D3D11_SDK_VERSION,
                                     byref(self.dev), None, byref(self.ctx))
        if hr < 0:
            raise OSError("D3D11CreateDevice failed: 0x%08x" % (hr & 0xffffffff))

    def create_shader(self, stage, blob):
        """Returns (shader pointer or None, hresult). The runtime validates
        the container checksum, signatures and bytecode here."""
        out = c_void_p()
        buf = ctypes.create_string_buffer(blob, len(blob))
        hr = _call(self.dev, DEV_CREATE[stage], HRESULT, ctypes.cast(buf, c_void_p), c_size_t(len(blob)),
                   c_void_p(None), byref(out))
        return (out if hr >= 0 else None), hr & 0xffffffff

    def check(self, stage, blob):
        shader, hr = self.create_shader(stage, blob)
        _release(shader)
        return hr

    def render(self, vs_blob, ps_blob, cb_data, width=128, height=128, readback=True):
        """Draws a fullscreen triangle; returns a list of width*height*4 floats.
        With readback=False only the first row is returned: mapping still
        waits for the GPU to finish, which is all a timing run needs."""
        vs, hr = self.create_shader("vs", vs_blob)
        ps, hr2 = self.create_shader("ps", ps_blob)
        if not vs or not ps:
            raise OSError("shader creation failed: vs=0x%08x ps=0x%08x" % (hr, hr2))

        def tex(usage, bind, cpu):
            # D3D11_TEXTURE2D_DESC
            desc = struct.pack("IIIIIIIIIII", width, height, 1, 1, DXGI_FORMAT_R32G32B32A32_FLOAT, 1, 0,
                               usage, bind, cpu, 0)
            t = c_void_p()
            hr = _call(self.dev, DEV_CREATE_TEX2D, HRESULT, ctypes.c_char_p(desc), c_void_p(None), byref(t))
            assert hr >= 0, hex(hr & 0xffffffff)
            return t

        rt = tex(0, 0x20, 0)             # DEFAULT, RENDER_TARGET
        staging = tex(3, 0, 0x20000)     # STAGING, CPU_ACCESS_READ
        rtv = c_void_p()
        assert _call(self.dev, DEV_CREATE_RTV, HRESULT, rt, c_void_p(None), byref(rtv)) >= 0

        cb = c_void_p()
        if cb_data:
            cb_data = cb_data + b"\0" * (-len(cb_data) % 16)
            desc = struct.pack("IIIIII", len(cb_data), 0, 0x4, 0, 0, 0)   # DEFAULT, CONSTANT_BUFFER
            init = (c_void_p * 3)(ctypes.cast(ctypes.c_char_p(cb_data), c_void_p), None, None)
            assert _call(self.dev, DEV_CREATE_BUFFER, HRESULT, ctypes.c_char_p(desc), init, byref(cb)) >= 0
            _call(self.ctx, CTX_PS_SET_CB, None, c_uint(0), c_uint(1), byref(cb))

        vp = (c_float * 6)(0, 0, width, height, 0, 1)
        _call(self.ctx, CTX_RS_VIEWPORTS, None, c_uint(1), vp)
        _call(self.ctx, CTX_OM_SET_RT, None, c_uint(1), byref(rtv), c_void_p(None))
        _call(self.ctx, CTX_IA_TOPOLOGY, None, c_uint(4))   # TRIANGLELIST
        _call(self.ctx, CTX_VS_SET_SHADER, None, vs, c_void_p(None), c_uint(0))
        _call(self.ctx, CTX_PS_SET_SHADER, None, ps, c_void_p(None), c_uint(0))
        _call(self.ctx, CTX_DRAW, None, c_uint(3), c_uint(0))
        _call(self.ctx, CTX_COPY_RESOURCE, None, staging, rt)

        class Mapped(ctypes.Structure):
            _fields_ = [("data", c_void_p), ("row_pitch", c_uint), ("depth_pitch", c_uint)]
        m = Mapped()
        assert _call(self.ctx, CTX_MAP, HRESULT, staging, c_uint(0), c_uint(1), c_uint(0), byref(m)) >= 0
        pixels = []
        for y in range(height if readback else 1):
            row = ctypes.string_at(m.data + y * m.row_pitch, width * 16)
            pixels.extend(struct.unpack("%df" % (width * 4), row))
        _call(self.ctx, CTX_UNMAP, None, staging, c_uint(0))
        for o in (cb, rtv, staging, rt, ps, vs):
            _release(o)
        return pixels

    def _buffer(self, data, usage, bind, cpu, misc, stride):
        desc = struct.pack("IIIIII", len(data), usage, bind, cpu, misc, stride)   # D3D11_BUFFER_DESC
        init = (c_void_p * 3)(ctypes.cast(ctypes.c_char_p(data), c_void_p), None, None)
        buf = c_void_p()
        hr = _call(self.dev, DEV_CREATE_BUFFER, HRESULT, ctypes.c_char_p(desc), init, byref(buf))
        assert hr >= 0, hex(hr & 0xffffffff)
        return buf

    def _readback(self, buf, size, misc, stride):
        staging = self._buffer(bytes(1) * size, 3, 0, 0x20000, misc & 0x40, stride)
        _call(self.ctx, CTX_COPY_RESOURCE, None, staging, buf)

        class Mapped(ctypes.Structure):
            _fields_ = [("data", c_void_p), ("row_pitch", c_uint), ("depth_pitch", c_uint)]
        m = Mapped()
        assert _call(self.ctx, CTX_MAP, HRESULT, staging, c_uint(0), c_uint(1), c_uint(0), byref(m)) >= 0
        data = ctypes.string_at(m.data, size)
        _call(self.ctx, CTX_UNMAP, None, staging, c_uint(0))
        _release(staging)
        return data

    def run_compute(self, cs_blob, raw_data, struct_data, stride, groups):
        """Dispatches (groups, 1, 1) with u0 = raw buffer and u1 = structured
        buffer; returns the final contents of both."""
        cs, hr = self.create_shader("cs", cs_blob)
        if not cs:
            raise OSError("compute shader creation failed: 0x%08x" % hr)
        raw = self._buffer(raw_data, 0, 0x80, 0, 0x20, 0)             # UNORDERED_ACCESS, ALLOW_RAW_VIEWS
        sbuf = self._buffer(struct_data, 0, 0x80, 0, 0x40, stride)   # UNORDERED_ACCESS, BUFFER_STRUCTURED
        uavs = (c_void_p * 2)()
        # D3D11_UNORDERED_ACCESS_VIEW_DESC: R32_TYPELESS, BUFFER, {first, count, RAW}
        raw_desc = struct.pack("IIIII", 39, 1, 0, len(raw_data) // 4, 1)
        raw_uav, struct_uav = c_void_p(), c_void_p()
        assert _call(self.dev, DEV_CREATE_UAV, HRESULT, raw, ctypes.c_char_p(raw_desc), byref(raw_uav)) >= 0
        assert _call(self.dev, DEV_CREATE_UAV, HRESULT, sbuf, c_void_p(None), byref(struct_uav)) >= 0
        uavs[0], uavs[1] = raw_uav.value, struct_uav.value
        _call(self.ctx, CTX_CS_SET_SHADER, None, cs, c_void_p(None), c_uint(0))
        _call(self.ctx, CTX_CS_SET_UAVS, None, c_uint(0), c_uint(2), uavs, c_void_p(None))
        _call(self.ctx, CTX_DISPATCH, None, c_uint(groups), c_uint(1), c_uint(1))
        out = (self._readback(raw, len(raw_data), 0x20, 0), self._readback(sbuf, len(struct_data), 0x40, stride))
        uavs[0] = uavs[1] = None
        _call(self.ctx, CTX_CS_SET_UAVS, None, c_uint(0), c_uint(2), uavs, c_void_p(None))
        for o in (raw_uav, struct_uav, raw, sbuf, cs):
            _release(o)
        return out
