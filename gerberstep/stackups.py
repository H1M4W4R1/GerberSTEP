"""Offline mechanical presets; dimensions in mm, gaps ordered bottom to top.

Source: https://jlcpcb.com/impedance (checked 2026-10-14).
Published dimensions are preserved, not rescaled to the nominal board thickness.
Two-layer presets are nominal estimates, not published impedance stackups.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Stackup:
    name: str
    gaps: tuple[float, ...]
    outer: float = 0.035
    inner: float = 0.0152

    def matches(self, board):
        sides = [layer.side for layer in board.layers if layer.kind == "copper"]
        expected = {"top", "bottom"} | {f"inner{i}" for i in range(1, len(self.gaps))}
        return len(sides) == len(expected) and set(sides) == expected

    def thicknesses(self, board):
        if not self.matches(board):
            raise ValueError("Stackup requires matching top, bottom and internal copper layers.")
        values = {f"Dielectric_{i}": gap for i, gap in enumerate(self.gaps, 1)}
        for layer in board.layers:
            if layer.kind == "copper":
                values[layer.name] = self.inner if layer.side.startswith("inner") else self.outer
        return values


STACKUPS = tuple(Stackup(f"JLCPCB 2L · {size:g} mm (nominal)", (round(size - 0.07, 4),))
                 for size in (0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0)) + tuple(
    Stackup(f"JLC04161H-{name} · 4L / 1.6 mm", (gap, core, gap))
    for name, gap, core in (("7628", 0.2104, 1.065), ("3313", 0.0994, 1.265),
                            ("1080", 0.0764, 1.265), ("2116", 0.1164, 1.265)))
