"""Shared original-pixel renderer preserved from the first frog tool."""
import numpy as np
from PIL import Image
from scipy.spatial import Delaunay
from scipy.ndimage import map_coordinates


class Animator:
    def __init__(self, rig, size=512, *, source):
        self.rig = rig
        self.size = size
        self.original = Image.open(source).convert('RGBA')
        self.alpha = np.asarray(self.original)[:, :, 3].astype(float)
        w, h = self.original.size
        xx, yy = np.meshgrid(np.linspace(0, w-1, 66), np.linspace(0, h-1, 64))
        self.vertices = np.column_stack((xx.ravel(), yy.ravel()))
        self.triangles = Delaunay(self.vertices).simplices
        self.scale = size * 0.79 / max(w, h)
        self.center = np.array(rig['body_center'], float)

    def pose(self, t, params):
        raise NotImplementedError('Provide pose vertices in a subclass.')

    def frame(self, t, params=None):
        # Same shared-triangle inverse lookup and supersampling as the original tool.
        ss = 2
        n = self.size * ss
        dst = self.pose(t, params or {}) * ss
        out = np.zeros((n, n), np.float32)
        for ids in self.triangles:
            tri = dst[ids]
            original = self.vertices[ids]
            matrix = np.column_stack((tri[1]-tri[0], tri[2]-tri[0]))
            source_matrix = np.column_stack((original[1]-original[0], original[2]-original[0]))
            if np.linalg.det(matrix) * np.linalg.det(source_matrix) <= 0:
                raise ValueError('Mesh fold: reduce amplitudes or correct control points.')
            lo = np.maximum(np.floor(tri.min(axis=0)).astype(int), 0)
            hi = np.minimum(np.ceil(tri.max(axis=0)).astype(int), n-1)
            if (hi < lo).any():
                continue
            x, y = np.meshgrid(np.arange(lo[0], hi[0]+1), np.arange(lo[1], hi[1]+1))
            uv = np.linalg.solve(matrix, np.stack((x-tri[0, 0], y-tri[0, 1])).reshape(2, -1))
            inside = (uv[0] >= -1e-7) & (uv[1] >= -1e-7) & (uv.sum(axis=0) <= 1+1e-7)
            xy = original[0, :, None] + source_matrix @ uv[:, inside]
            values = map_coordinates(self.alpha, [xy[1], xy[0]], order=1, mode='constant', cval=0)
            out[y.ravel()[inside], x.ravel()[inside]] = values
        alpha = Image.fromarray(np.uint8(np.clip(out, 0, 255))).resize((self.size, self.size), Image.Resampling.LANCZOS)
        rgba = Image.new('RGBA', (self.size, self.size), (0, 0, 0, 0))
        rgba.putalpha(alpha)
        return rgba
