"""Live 3D preview in VS Code (OCP CAD Viewer extension). Builds the three parts without writing STLs or previews.
Open this file in VS Code, start the viewer (Command Palette: "OCP CAD Viewer: Open viewer"), then run the file with the Python extension
using case/.venv as the interpreter."""
from pathlib import Path
from ocp_vscode import show
src = (Path(__file__).parent / "flightscope_case.py").read_text().split("\nparts = {")[0]   # model definitions only, stops before the exports
g = {"__file__": str(Path(__file__).parent / "flightscope_case.py"), "__name__": "flightscope_case"}
exec(compile(src, "flightscope_case.py", "exec"), g)
show(g["front_shell"](), g["mid_frame"](), g["rear_cover"](), names=["front_shell", "mid_frame", "rear_cover"])
