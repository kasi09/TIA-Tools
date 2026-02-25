"""
TIA Documentation Generator - Generates HTML documentation from SCL source files.

Creates a browsable HTML documentation site:
  - index.html: All blocks grouped by type (FB, FC, OB, DB, TYPE) with links
  - {BlockName}.html: Interface table, description, source code, dependencies
  - dependencies.html: Dependency overview

Only uses Python stdlib (no external templates or frameworks).

Usage:
    from tia_tools import DocGenerator

    doc = DocGenerator()
    doc.scan_directory("./scl_sources")
    doc.generate("./docs")
"""

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class VarInfo:
    """Variable declaration info."""
    name: str
    data_type: str
    section: str  # Input, Output, InOut, Static, Temp, Constant
    initial_value: str = ""
    comment: str = ""


@dataclass
class BlockDoc:
    """Documentation data for a single block."""
    name: str
    block_type: str  # FB, FC, OB, DB, TYPE
    file: str
    line: int
    version: str = ""
    comment: str = ""
    variables: list[VarInfo] = field(default_factory=list)
    source: str = ""
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    return_type: str = ""


# ─── Parser ──────────────────────────────────────────────────────────────────

_BLOCK_PATTERN = re.compile(
    r'^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\s+"([^"]+)"(?:\s*:\s*(\w+))?',
    re.IGNORECASE,
)
_BLOCK_END = re.compile(
    r'^\s*(END_FUNCTION_BLOCK|END_FUNCTION|END_ORGANIZATION_BLOCK|END_DATA_BLOCK|END_TYPE)\b',
    re.IGNORECASE,
)
_VERSION = re.compile(r'^\s*VERSION\s*:\s*(\S+)', re.IGNORECASE)
_VAR_SECTION_START = re.compile(
    r'^\s*(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR_GLOBAL|VAR\s+CONSTANT|VAR|STRUCT)\b',
    re.IGNORECASE,
)
_VAR_SECTION_END = re.compile(r'^\s*(END_VAR|END_STRUCT)\b', re.IGNORECASE)
_VAR_DECL = re.compile(
    r'^\s+(\w+)\s*:\s*(.+?)\s*(?::=\s*(.+?))?\s*;(.*)$'
)
_BLOCK_REF = re.compile(r'"([^"]+)"')
_BLOCK_CALL = re.compile(r'"([^"]+)"\s*\(')

_SECTION_MAP = {
    "VAR_INPUT": "Input",
    "VAR_OUTPUT": "Output",
    "VAR_IN_OUT": "InOut",
    "VAR_TEMP": "Temp",
    "VAR_GLOBAL": "Global",
    "VAR CONSTANT": "Constant",
    "VAR": "Static",
    "STRUCT": "Static",
}

_TYPE_MAP = {
    "FUNCTION_BLOCK": "FB",
    "FUNCTION": "FC",
    "ORGANIZATION_BLOCK": "OB",
    "DATA_BLOCK": "DB",
    "TYPE": "TYPE",
}


def _parse_scl_file(filepath: str) -> list[BlockDoc]:
    """Parse an SCL file and extract block documentation."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    blocks: list[BlockDoc] = []

    current_block: Optional[BlockDoc] = None
    in_var_section = False
    current_section = ""
    block_start_line = 0
    in_block_comment = False
    comment_buffer: list[str] = []

    for line_num, raw_line in enumerate(lines):
        line = raw_line.rstrip()

        # Block comment tracking
        if in_block_comment:
            if "*)" in line:
                in_block_comment = False
            continue
        if "(*" in line and "*)" not in line:
            in_block_comment = True
            continue

        # Block start
        m = _BLOCK_PATTERN.match(line)
        if m:
            block_kw = m.group(1).upper()
            block_name = m.group(2)
            return_type = m.group(3) or ""

            current_block = BlockDoc(
                name=block_name,
                block_type=_TYPE_MAP.get(block_kw, "?"),
                file=str(path),
                line=line_num,
                return_type=return_type,
            )
            block_start_line = line_num
            comment_buffer = []
            continue

        if current_block is None:
            continue

        # Version
        vm = _VERSION.match(line)
        if vm:
            current_block.version = vm.group(1)
            continue

        # Comment lines after block header (before VAR sections)
        if not in_var_section and line.strip().startswith("//"):
            comment_text = line.strip()[2:].strip()
            if comment_text:
                comment_buffer.append(comment_text)
            continue

        if comment_buffer and not current_block.comment:
            current_block.comment = " ".join(comment_buffer)
            comment_buffer = []

        # VAR section start
        vsm = _VAR_SECTION_START.match(line)
        if vsm:
            section_kw = vsm.group(1).upper()
            current_section = _SECTION_MAP.get(section_kw, "Static")
            in_var_section = True
            continue

        # VAR section end
        if _VAR_SECTION_END.match(line):
            in_var_section = False
            continue

        # Variable declaration
        if in_var_section:
            vdm = _VAR_DECL.match(line)
            if vdm:
                var_name = vdm.group(1)
                var_type = vdm.group(2).strip()
                var_init = (vdm.group(3) or "").strip()
                var_comment_text = vdm.group(4).strip()

                # Extract comment
                comment = ""
                if "//" in var_comment_text:
                    comment = var_comment_text.split("//", 1)[1].strip()

                current_block.variables.append(VarInfo(
                    name=var_name, data_type=var_type,
                    section=current_section,
                    initial_value=var_init, comment=comment,
                ))
            continue

        # Block calls
        for cm in _BLOCK_CALL.finditer(line):
            called = cm.group(1)
            if called != current_block.name and called not in current_block.calls:
                current_block.calls.append(called)

        # Block end
        if _BLOCK_END.match(line):
            # Capture source
            current_block.source = "\n".join(lines[block_start_line:line_num + 1])
            if comment_buffer and not current_block.comment:
                current_block.comment = " ".join(comment_buffer)
            blocks.append(current_block)
            current_block = None
            in_var_section = False

    return blocks


# ─── HTML Generation ─────────────────────────────────────────────────────────

_CSS = """\
:root {
    --bg: #1e1e2e;
    --bg-surface: #252536;
    --bg-card: #2a2a3c;
    --text: #cdd6f4;
    --text-dim: #a6adc8;
    --accent: #89b4fa;
    --accent2: #a6e3a1;
    --accent3: #f9e2af;
    --border: #45475a;
    --red: #f38ba8;
    --green: #a6e3a1;
    --yellow: #f9e2af;
    --blue: #89b4fa;
    --purple: #cba6f7;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { color: var(--accent); margin-bottom: 1rem; font-size: 1.8rem; }
h2 { color: var(--accent2); margin: 1.5rem 0 0.8rem; font-size: 1.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }
h3 { color: var(--accent3); margin: 1rem 0 0.5rem; font-size: 1.1rem; }
.badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-right: 0.5rem;
}
.badge-fb { background: #313244; color: var(--blue); border: 1px solid var(--blue); }
.badge-fc { background: #313244; color: var(--green); border: 1px solid var(--green); }
.badge-ob { background: #313244; color: var(--purple); border: 1px solid var(--purple); }
.badge-db { background: #313244; color: var(--yellow); border: 1px solid var(--yellow); }
.badge-type { background: #313244; color: var(--red); border: 1px solid var(--red); }
table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.5rem 0 1rem;
    background: var(--bg-card);
    border-radius: 8px;
    overflow: hidden;
}
th, td { padding: 0.5rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--bg-surface); color: var(--accent); font-weight: 600; font-size: 0.85rem; text-transform: uppercase; }
td { font-size: 0.9rem; }
td:nth-child(1) { font-weight: 600; color: var(--text); }
td:nth-child(2) { color: var(--accent3); font-family: monospace; }
.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
}
.card:hover { border-color: var(--accent); }
.card-title { font-size: 1.1rem; font-weight: 600; }
.card-desc { color: var(--text-dim); font-size: 0.9rem; margin-top: 0.3rem; }
pre {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    overflow-x: auto;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    font-size: 0.85rem;
    line-height: 1.5;
    margin: 0.5rem 0 1rem;
}
.nav {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.8rem 1.2rem;
    margin-bottom: 1.5rem;
    font-size: 0.9rem;
}
.nav a { margin-right: 1rem; }
.section-header { color: var(--text-dim); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.5rem; }
.dep-list { list-style: none; padding: 0; }
.dep-list li { padding: 0.2rem 0; }
.dep-list li::before { content: '→ '; color: var(--accent); }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0; }
.stat { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem 1.2rem; min-width: 120px; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 0.8rem; color: var(--text-dim); }
"""


def _badge(block_type: str) -> str:
    cls = f"badge-{block_type.lower()}"
    return f'<span class="badge {cls}">{html.escape(block_type)}</span>'


def _nav(current: str = "") -> str:
    links = [
        ("index.html", "Overview"),
        ("dependencies.html", "Dependencies"),
    ]
    parts = []
    for href, label in links:
        if label.lower() == current.lower():
            parts.append(f"<strong>{html.escape(label)}</strong>")
        else:
            parts.append(f'<a href="{href}">{html.escape(label)}</a>')
    return f'<div class="nav">{"  |  ".join(parts)}</div>'


def _html_page(title: str, body: str, nav_current: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
{_nav(nav_current)}
{body}
<footer style="margin-top:2rem;padding-top:1rem;border-top:1px solid var(--border);color:var(--text-dim);font-size:0.8rem;">
Generated by TIA-Tools DocGenerator
</footer>
</body>
</html>"""


def _safe_filename(name: str) -> str:
    return name.replace('"', "").replace(" ", "_").replace("/", "_").replace("\\", "_")


# ─── DocGenerator Class ─────────────────────────────────────────────────────

class DocGenerator:
    """Generate HTML documentation from SCL source files."""

    def __init__(self):
        self.blocks: list[BlockDoc] = []
        self._files_scanned: list[str] = []

    def scan_file(self, filepath: str) -> int:
        """
        Scan a single SCL file.

        Returns:
            Number of blocks found
        """
        parsed = _parse_scl_file(filepath)
        self.blocks.extend(parsed)
        self._files_scanned.append(filepath)
        return len(parsed)

    def scan_directory(self, directory: str, recursive: bool = True) -> int:
        """
        Scan all .scl files in a directory.

        Returns:
            Number of files scanned
        """
        path = Path(directory)
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        pattern = "**/*.scl" if recursive else "*.scl"
        count = 0
        for scl_file in sorted(path.glob(pattern)):
            self.scan_file(str(scl_file))
            count += 1
        return count

    def generate(self, output_dir: str) -> None:
        """
        Generate HTML documentation.

        Args:
            output_dir: Output directory for HTML files
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Resolve called_by
        block_names = {b.name for b in self.blocks}
        for block in self.blocks:
            for call in block.calls:
                for other in self.blocks:
                    if other.name == call and block.name not in other.called_by:
                        other.called_by.append(block.name)

        # Generate pages
        self._generate_index(out)
        self._generate_dependencies(out)
        for block in self.blocks:
            self._generate_block_page(out, block)

        print(f"Documentation generated: {out}")
        print(f"  {len(self.blocks)} blocks, {len(self._files_scanned)} files")
        print(f"  Open: {out / 'index.html'}")

    def _generate_index(self, out: Path) -> None:
        """Generate index.html with block overview."""
        # Group by type
        groups = {}
        for b in self.blocks:
            groups.setdefault(b.block_type, []).append(b)

        body = '<h1>SCL Documentation</h1>\n'

        # Stats
        body += '<div class="stats">\n'
        body += f'<div class="stat"><div class="stat-value">{len(self.blocks)}</div><div class="stat-label">Blocks</div></div>\n'
        body += f'<div class="stat"><div class="stat-value">{len(self._files_scanned)}</div><div class="stat-label">Files</div></div>\n'
        total_vars = sum(len(b.variables) for b in self.blocks)
        body += f'<div class="stat"><div class="stat-value">{total_vars}</div><div class="stat-label">Variables</div></div>\n'
        body += '</div>\n'

        type_order = ["FB", "FC", "OB", "DB", "TYPE"]
        type_labels = {
            "FB": "Function Blocks",
            "FC": "Functions",
            "OB": "Organization Blocks",
            "DB": "Data Blocks",
            "TYPE": "User Defined Types",
        }

        for bt in type_order:
            if bt not in groups:
                continue
            body += f'<h2>{html.escape(type_labels.get(bt, bt))}</h2>\n'
            for b in sorted(groups[bt], key=lambda x: x.name):
                safe = _safe_filename(b.name)
                desc = html.escape(b.comment) if b.comment else '<span style="color:var(--text-dim)">No description</span>'
                var_count = len(b.variables)
                body += f'<a href="{safe}.html" style="text-decoration:none">'
                body += f'<div class="card">'
                body += f'<div class="card-title">{_badge(bt)} {html.escape(b.name)}'
                if b.version:
                    body += f' <span style="color:var(--text-dim);font-size:0.8rem">v{html.escape(b.version)}</span>'
                if b.return_type:
                    body += f' <span style="color:var(--accent3);font-size:0.8rem">: {html.escape(b.return_type)}</span>'
                body += f'</div>'
                body += f'<div class="card-desc">{desc} &mdash; {var_count} variables</div>'
                body += f'</div></a>\n'

        (out / "index.html").write_text(_html_page("SCL Documentation", body, "Overview"), encoding="utf-8")

    def _generate_block_page(self, out: Path, block: BlockDoc) -> None:
        """Generate a detail page for a single block."""
        safe = _safe_filename(block.name)

        body = f'<h1>{_badge(block.block_type)} {html.escape(block.name)}</h1>\n'

        # Info
        if block.comment:
            body += f'<p style="color:var(--text-dim);font-size:1rem;margin-bottom:1rem">{html.escape(block.comment)}</p>\n'

        body += '<table>\n'
        body += f'<tr><td>Type</td><td>{html.escape(block.block_type)}</td></tr>\n'
        if block.version:
            body += f'<tr><td>Version</td><td>{html.escape(block.version)}</td></tr>\n'
        if block.return_type:
            body += f'<tr><td>Return Type</td><td>{html.escape(block.return_type)}</td></tr>\n'
        body += f'<tr><td>Source File</td><td>{html.escape(Path(block.file).name)}</td></tr>\n'
        body += '</table>\n'

        # Interface table grouped by section
        sections_order = ["Input", "Output", "InOut", "Static", "Temp", "Constant"]
        for section in sections_order:
            vars_in_section = [v for v in block.variables if v.section == section]
            if not vars_in_section:
                continue

            section_labels = {
                "Input": "VAR_INPUT", "Output": "VAR_OUTPUT", "InOut": "VAR_IN_OUT",
                "Static": "VAR", "Temp": "VAR_TEMP", "Constant": "VAR CONSTANT",
            }
            body += f'<h3>{html.escape(section_labels.get(section, section))}</h3>\n'
            body += '<table>\n'
            body += '<tr><th>Name</th><th>Type</th><th>Initial</th><th>Comment</th></tr>\n'
            for v in vars_in_section:
                body += f'<tr>'
                body += f'<td>{html.escape(v.name)}</td>'
                body += f'<td>{html.escape(v.data_type)}</td>'
                body += f'<td>{html.escape(v.initial_value)}</td>'
                body += f'<td style="color:var(--text-dim)">{html.escape(v.comment)}</td>'
                body += f'</tr>\n'
            body += '</table>\n'

        # Dependencies
        if block.calls or block.called_by:
            body += '<h2>Dependencies</h2>\n'
            if block.calls:
                body += '<h3>Calls</h3>\n<ul class="dep-list">\n'
                for c in block.calls:
                    safe_c = _safe_filename(c)
                    body += f'<li><a href="{safe_c}.html">{html.escape(c)}</a></li>\n'
                body += '</ul>\n'
            if block.called_by:
                body += '<h3>Called by</h3>\n<ul class="dep-list">\n'
                for c in block.called_by:
                    safe_c = _safe_filename(c)
                    body += f'<li><a href="{safe_c}.html">{html.escape(c)}</a></li>\n'
                body += '</ul>\n'

        # Source code
        if block.source:
            body += '<h2>Source Code</h2>\n'
            body += f'<pre>{html.escape(block.source)}</pre>\n'

        (out / f"{safe}.html").write_text(
            _html_page(f"{block.block_type} {block.name}", body),
            encoding="utf-8",
        )

    def _generate_dependencies(self, out: Path) -> None:
        """Generate dependencies overview page."""
        body = '<h1>Dependencies</h1>\n'

        # Build adjacency list
        has_deps = False
        for block in sorted(self.blocks, key=lambda b: b.name):
            if block.calls or block.called_by:
                has_deps = True

        if not has_deps:
            body += '<p style="color:var(--text-dim)">No inter-block dependencies found.</p>\n'
        else:
            body += '<table>\n'
            body += '<tr><th>Block</th><th>Type</th><th>Calls</th><th>Called By</th></tr>\n'
            for block in sorted(self.blocks, key=lambda b: (b.block_type, b.name)):
                safe = _safe_filename(block.name)
                calls_html = ", ".join(
                    f'<a href="{_safe_filename(c)}.html">{html.escape(c)}</a>' for c in block.calls
                ) or "-"
                called_by_html = ", ".join(
                    f'<a href="{_safe_filename(c)}.html">{html.escape(c)}</a>' for c in block.called_by
                ) or "-"
                body += f'<tr>'
                body += f'<td><a href="{safe}.html">{html.escape(block.name)}</a></td>'
                body += f'<td>{_badge(block.block_type)}</td>'
                body += f'<td>{calls_html}</td>'
                body += f'<td>{called_by_html}</td>'
                body += f'</tr>\n'
            body += '</table>\n'

            # ASCII dependency graph
            body += '<h2>Dependency Graph</h2>\n<pre>\n'
            for block in sorted(self.blocks, key=lambda b: b.name):
                if block.calls:
                    for call in block.calls:
                        body += f'{html.escape(block.name)} ──▶ {html.escape(call)}\n'
            body += '</pre>\n'

        (out / "dependencies.html").write_text(
            _html_page("Dependencies", body, "Dependencies"),
            encoding="utf-8",
        )


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    scan_dir = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent / "generated_scl")
    output_dir = sys.argv[2] if len(sys.argv) > 2 else str(Path(scan_dir) / "docs")

    doc = DocGenerator()
    count = doc.scan_directory(scan_dir)
    print(f"Scanned {count} files, found {len(doc.blocks)} blocks")
    doc.generate(output_dir)
