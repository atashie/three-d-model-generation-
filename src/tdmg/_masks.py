"""Binary mask validation shared by tdmg.flat and tdmg.smoothing.

It lives here, not in either module, so that tdmg.flat can import tdmg.smoothing without
an import cycle.
"""

from __future__ import annotations

import numpy as np

MASK_ON = 255  # Integer masks hold 0 and 255, as mask.png does (selection.load_mask).


def binary_cells(mask: np.ndarray, error: type[Exception]) -> np.ndarray:
    """mask as a 2-D bool array; raise error for any other shape, dtype or values.

    The mask is bool, or integer with only 0 and MASK_ON (MASK_ON is foreground).
    """
    mask = np.asarray(mask)
    if mask.ndim != 2:
        raise error(f"mask must be two-dimensional, got shape {mask.shape}")
    if mask.dtype == np.bool_:
        return mask
    if np.issubdtype(mask.dtype, np.integer):
        if not np.isin(mask, (0, MASK_ON)).all():
            raise error(f"an integer mask must hold only 0 and {MASK_ON}")
        return mask == MASK_ON
    raise error(f"mask must be bool or integer (0 and {MASK_ON}), got {mask.dtype}")
