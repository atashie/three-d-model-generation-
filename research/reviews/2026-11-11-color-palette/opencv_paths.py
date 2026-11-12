"""Does cv2.GaussianBlur's result depend on OpenCV's optimisation switch, in float32 and float64?"""
import cv2
import numpy as np

from tdmg.smoothing import smooth_labels

rng = np.random.default_rng(0)
lab = np.zeros((17, 17), np.int32)
lab[np.triu_indices(17, 1)] = 1
np.fill_diagonal(lab, 2)
tests = {"diag": (lab, 2.5)}
for n in (40, 200):
    tests[f"rand{n}"] = (rng.integers(0, 4, (n, n)).astype(np.int32), 2.0)
blocks = np.kron(rng.integers(0, 5, (30, 30)), np.ones((9, 9), int)).astype(np.int32)
tests["blocks"] = (blocks, 2.0)

for name, (lab, sig) in tests.items():
    for dt in (np.float32, np.float64):
        outs = []
        for opt in (True, False):
            cv2.setUseOptimized(opt)
            f = [cv2.GaussianBlur((np.pad(lab, 1, mode="edge") == c).astype(dt), (0, 0), sig,
                                  sigmaY=sig, borderType=cv2.BORDER_REPLICATE)
                 for c in np.unique(lab)]
            outs.append(np.stack(f))
        cv2.setUseOptimized(True)
        print(name, dt.__name__, "bitwise equal:", np.array_equal(outs[0], outs[1]),
              "max diff:", float(np.abs(outs[0] - outs[1]).max()))
    fines = []
    for opt in (True, False):
        cv2.setUseOptimized(opt)
        fines.append(smooth_labels(lab, sig, 4).fine)
    cv2.setUseOptimized(True)
    print(name, "smooth_labels fine pixels differing:", int((fines[0] != fines[1]).sum()))
