"""Generate a small, reproducible fabrication set (no external assets)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples" / "demo"


def coordinate(x, y):
    return f"X{round(x*1e6):d}Y{round(y*1e6):d}"


def write(name, apertures, body):
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / name).write_text("G04 GerberSTEP demonstration board*\n%FSLAX46Y46*%\n%MOMM*%\n"
                             + apertures + "\n%LPD*%\nG01*\n" + body + "\nM02*\n", encoding="ascii")


def line(points):
    return "\n".join(coordinate(x, y) + ("D02*" if i == 0 else "D01*") for i, (x, y) in enumerate(points)) + "\n"


def main():
    write("demo.gko", "%ADD10C,0.050*%", "D10*\n" + line([(0, 0), (60, 0), (60, 40), (0, 40), (0, 0)]))
    pads = [(6, y) for y in range(8, 34, 5)] + [(54, y) for y in range(8, 34, 5)]
    chip = [(x, y) for x in (25, 35) for y in range(13, 29, 3)]
    top = "D10*\n" + "\n".join(coordinate(x, y)+"D03*" for x, y in pads)
    top += "\nD11*\n" + "\n".join(coordinate(x, y)+"D03*" for x, y in chip)
    top += "\nD12*\n"
    for index, y in enumerate(range(8, 34, 5)):
        dest = 13+index*3
        top += line([(6, y), (14, y), (20, dest), (25, dest)])
        top += line([(35, dest), (40, dest), (46, y), (54, y)])
    write("demo.gtl", "%ADD10C,2.800*%\n%ADD11R,2.500X1.500*%\n%ADD12C,0.650*%", top)
    bottom = "D10*\n" + "\n".join(coordinate(x, y)+"D03*" for x, y in pads)
    bottom += "\nD12*\n" + line([(6, 8), (6, 4), (54, 4), (54, 8)])
    write("demo.gbl", "%ADD10C,2.800*%\n%ADD12C,0.800*%", bottom)
    openings = "D10*\n" + "\n".join(coordinate(x, y)+"D03*" for x, y in pads)
    write("demo.gbs", "%ADD10C,3.100*%", openings)
    openings += "\nD11*\n" + "\n".join(coordinate(x, y)+"D03*" for x, y in chip)
    write("demo.gts", "%ADD10C,3.100*%\n%ADD11R,2.800X1.800*%", openings)
    silk = "D10*\n" + line([(22, 10), (38, 10), (38, 31), (22, 31), (22, 10)])
    silk += line([(24, 34), (24, 37), (27, 37), (27, 35.5), (25.5, 35.5)])
    silk += line([(30, 34), (30, 37), (33, 37)])
    silk += line([(30, 35.5), (32, 35.5)])
    write("demo.gto", "%ADD10C,0.250*%", silk)
    write("demo.gbo", "%ADD10C,0.250*%", "D10*\n" + line([(20, 15), (40, 15), (40, 25), (20, 25), (20, 15)]))
    drill = "M48\nMETRIC,TZ\nT01C1.200\nT02C3.000\n%\nG90\nT01\n"
    drill += "\n".join(f"X{x:.3f}Y{y:.3f}" for x, y in pads)
    drill += "\nT02\n" + "\n".join(f"X{x:.3f}Y{y:.3f}" for x, y in [(3, 3), (57, 3), (3, 37), (57, 37)])
    (ROOT / "demo.drl").write_text(drill + "\nM30\n", encoding="ascii")


if __name__ == "__main__":
    main()
