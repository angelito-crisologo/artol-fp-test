"""CP-SAT smoke test for Phase C.1.

Places three non-overlapping rectangles inside a 10x10 m region, each with a
required min area and min least-dimension, and prints the solution. This is
just a tooling sanity check before we build the real geometric model.
"""
from ortools.sat.python import cp_model

# 10 x 10 m region, modelled on a 5 cm grid -> 200 x 200 grid units
GRID_CM = 5
W, H = 10.0, 10.0
WU = int(W * 100 // GRID_CM)        # 200 units wide
HU = int(H * 100 // GRID_CM)        # 200 units high


def to_units(m: float) -> int:
    return int(round(m * 100 / GRID_CM))


def from_units(u: int) -> float:
    return round(u * GRID_CM / 100, 2)


def main():
    model = cp_model.CpModel()

    rooms = [
        # (label, min_w_m, min_h_m, min_area_sqm)
        ("A", 2.0, 2.0, 9.0),
        ("B", 1.5, 1.5, 6.0),
        ("C", 0.9, 0.9, 1.2),
    ]
    x, y, w, h = {}, {}, {}, {}
    xiv, yiv = {}, {}
    for label, mw, mh, ma in rooms:
        x[label] = model.NewIntVar(0, WU, f"x_{label}")
        y[label] = model.NewIntVar(0, HU, f"y_{label}")
        w[label] = model.NewIntVar(to_units(mw), WU, f"w_{label}")
        h[label] = model.NewIntVar(to_units(mh), HU, f"h_{label}")
        xend = model.NewIntVar(0, WU, f"xend_{label}")
        yend = model.NewIntVar(0, HU, f"yend_{label}")
        model.Add(xend == x[label] + w[label])
        model.Add(yend == y[label] + h[label])
        model.Add(xend <= WU)
        model.Add(yend <= HU)
        xiv[label] = model.NewIntervalVar(x[label], w[label], xend, f"xiv_{label}")
        yiv[label] = model.NewIntervalVar(y[label], h[label], yend, f"yiv_{label}")
        # min area (nonlinear) — auxiliary product variable, then >= min_area in u^2
        area = model.NewIntVar(0, WU * HU, f"area_{label}")
        model.AddMultiplicationEquality(area, [w[label], h[label]])
        model.Add(area >= int(round(ma * 10000 / (GRID_CM * GRID_CM))))

    model.AddNoOverlap2D(list(xiv.values()), list(yiv.values()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    print(f"status: {solver.StatusName(status)}  walltime: {solver.WallTime():.2f}s")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for label, *_ in rooms:
            print(f"  {label}: x={from_units(solver.Value(x[label])):.2f}  "
                  f"y={from_units(solver.Value(y[label])):.2f}  "
                  f"w={from_units(solver.Value(w[label])):.2f}  "
                  f"h={from_units(solver.Value(h[label])):.2f}")
    else:
        print("  no feasible solution")


if __name__ == "__main__":
    main()
