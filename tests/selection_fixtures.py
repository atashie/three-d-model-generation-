"""Synthetic images that copy the measured structure of the owner's test images.

See research/verification/2026-11-10-subject-selection/README.md. All return HxWx4 uint8 RGBA.
"""

import cv2
import numpy as np

DISC = (57, 46, 40)           # Roadie's measured disc colour
RED = (230, 20, 20)
WHITE = (240, 240, 240)
DARK_LINE = (20, 10, 5)       # about 62 RGB units from DISC: kept at tolerance 30, cut at 80

DISC_SEED = (30, 100)         # x, y inside the disc, away from the bird
BIRD_SEED = (100, 80)         # x, y on the bird's body
GAP_BETWEEN_LEGS = (100, 130)
RING_POINT = (100, 5)         # on the thin ring outside the disc
STROKE_POINT = (60, 20)       # on soft_blob's thin stroke, away from its blurred tip


def roadie_like() -> np.ndarray:
    """Opaque disc on a transparent canvas, a thin separate ring outside it, and a red bird.

    The bird's shoes are joined to its legs only through a dark outline, so a high
    tolerance cuts the feet off, as measured on the real image at tolerance 60.
    """
    img = np.zeros((200, 200, 4), np.uint8)
    cv2.circle(img, (100, 100), 95, (*WHITE, 255), 1)
    cv2.circle(img, (100, 100), 90, (*DISC, 255), -1)
    cv2.ellipse(img, (100, 80), (35, 20), 0, 0, 360, (*RED, 255), -1)
    cv2.line(img, (85, 95), (70, 134), (*RED, 255), 3)
    cv2.line(img, (115, 95), (130, 134), (*RED, 255), 3)
    for cx in (70, 130):
        cv2.ellipse(img, (cx, 143), (10, 6), 0, 0, 360, (*WHITE, 255), -1)
        cv2.ellipse(img, (cx, 143), (11, 7), 0, 0, 360, (*DARK_LINE, 255), 2)
    return img


def soft_blob() -> np.ndarray:
    """One round body with a thin stroke on top and soft alpha edges, like Oddie."""
    alpha = np.zeros((120, 120), np.uint8)
    cv2.circle(alpha, (60, 75), 30, 255, -1)
    cv2.line(alpha, (60, 45), (60, 10), 255, 3)
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
    img = np.zeros((120, 120, 4), np.uint8)
    img[..., :3] = (80, 112, 144)
    img[..., 3] = alpha
    return img


def two_subjects() -> np.ndarray:
    img = np.zeros((60, 120, 4), np.uint8)
    cv2.circle(img, (30, 30), 20, (*RED, 255), -1)
    cv2.circle(img, (90, 30), 20, (*RED, 255), -1)
    return img


def empty() -> np.ndarray:
    return np.zeros((10, 10, 4), np.uint8)
