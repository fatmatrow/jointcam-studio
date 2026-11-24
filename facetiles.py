"""Geometry of the live eye/eye/lip patch shared by tracking and every renderer.

The patch holds three tiles side by side: left eye, right eye, lips. Version 1.0 used
96 x 64 tiles. 1.1 samples them at twice the resolution straight from the full-size camera
frame so 1080p output keeps real eyelash and lip detail instead of upscaled blur.
"""
SCALE = 2
TILE_W = 96 * SCALE
TILE_H = 64 * SCALE
PATCH_W = TILE_W * 3
PATCH_SHAPE = (TILE_H, PATCH_W, 4)


def tile(patch, index):
    return patch[:, TILE_W * index:TILE_W * (index + 1)]
