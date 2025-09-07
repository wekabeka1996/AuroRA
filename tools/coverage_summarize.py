import sys, json, xml.etree.ElementTree as ET
from collections import defaultdict
xml_path, json_path, out_md = sys.argv[1], sys.argv[2], sys.argv[3]

root = ET.parse(xml_path).getroot()
# coverage.py XML schema: packages/package[@name][@line-rate][@branch-rate]
mods = []
for pkg in root.findall(".//packages/package"):
    name = pkg.get("name", "")
    line_rate = float(pkg.get("line-rate", "0")) * 100
    branch_rate = float(pkg.get("branch-rate", "0")) * 100
    file_count = len(pkg.findall(".//classes/class"))
    mods.append((name, line_rate, branch_rate, file_count))

mods.sort(key=lambda x: x[1])  # by lines%

# Heatmap candidates <70% (files)
with open(json_path, "r") as f:
    cj = json.load(f)
files = []
for fn, fobj in cj["files"].items():
    s = fobj["summary"]
    lines = s.get("percent_covered", 0.0)
    branches = s.get("percent_covered_branches", None)
    if lines < 70.0:
        files.append((fn, lines, branches))
files.sort(key=lambda x: x[1])

# Build MD
lines = []
lines.append("# Coverage Report (snapshot)\n")
lines.append("## Module summary (by lines%)\n")
lines.append("| module | lines% | branches% | #files |")
lines.append("|---|---:|---:|---:|")
for m, lr, br, fc in mods:
    lines.append(f"| `{m}` | {lr:.1f} | {br:.1f} | {fc} |")

lines.append("\n## Files <70% (heatmap list)\n")
lines.append("| file | lines% | branches% |")
lines.append("|---|---:|---:|")
for fn, lr, br in files:
    brs = f"{br:.1f}" if br is not None else "—"
    lines.append(f"| `{fn}` | {lr:.1f} | {brs} |")

with open(out_md, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Written {out_md}")