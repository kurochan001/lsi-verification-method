"""Frame-array oracle. It contains no streaming, window-buffer or bus implementation."""
import random


def sobel(pixels, width, height):
    if width < 3 or height < 3 or len(pixels) != width * height or any(type(p) is not int or not 0 <= p <= 255 for p in pixels):
        raise ValueError('requires W,H >= 3 and a complete eight-bit grayscale frame')
    kx = ((-1, 0, 1), (-2, 0, 2), (-1, 0, 1))
    ky = ((-1, -2, -1), (0, 0, 0), (1, 2, 1))
    result = []
    for y in range(height):
        for x in range(width):
            gx = gy = 0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    yy, xx = y + dy, x + dx
                    value = pixels[yy * width + xx] if 0 <= yy < height and 0 <= xx < width else 0
                    gx += value * kx[dy + 1][dx + 1]
                    gy += value * ky[dy + 1][dx + 1]
            result.append(min(255, abs(gx) + abs(gy)))
    return result


def directed(width, height):
    return [[12] * (width * height),
            [255 if x >= width // 2 else 0 for y in range(height) for x in range(width)],
            [3*x + 5*y for y in range(height) for x in range(width)],
            [255 if (x, y) == (width // 2, height // 2) else 0 for y in range(height) for x in range(width)],
            [(7*x + 11*y + 1) % 64 for y in range(height) for x in range(width)]]


def random_frames(width, height, seed, frames):
    rng = random.Random(seed)
    return [[rng.randrange(32 if frame % 2 == 0 else 256) for _ in range(width * height)] for frame in range(frames)]
