"""
TIA Cross-Reference Tool - Scans SCL files and builds a reference database.

Analyzes SCL source files to find:
  - Variable references (#Variable)
  - Block references ("BlockName")
  - Hardware addresses (%I, %Q, %M)
  - Declarations vs. usage (read/write/call)

Provides:
  - find_usages(name) - All references to a variable/block
  - find_unused() - Declared but never referenced variables
  - find_dependencies(block) - What a block uses
  - find_dependents(block) - What uses a block
  - export_csv() / export_json() - Export reference data

Usage:
    from tia_tools import CrossReference

    xref = CrossReference()
    xref.scan_directory("./scl_sources")

    for ref in xref.find_usages("Motor1_Run"):
        print(f"  {ref.file}:{ref.line} [{ref.kind}] {ref.context}")
"""

import csv
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ─── Data Types ──────────────────────────────────────────────────────────────

@dataclass
class Reference:
    """A single reference to a symbol."""
    name: str
    file: str
    line: int
    col: int
    kind: str  # "declaration", "read", "write", "call"
    ref_type: str  # "variable", "block", "address", "type"
    context: str  # The source line (trimmed)
    block: str = ""  # Enclosing block name


@dataclass
class BlockInfo:
    """Information about a parsed block."""
    name: str
    block_type: str  # FB, FC, OB, DB, TYPE
    file: str
    line: int
    variables: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)


# ─── Parser Patterns ────────────────────────────────────────────────────────

_BLOCK_START = re.compile(
    r'^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\s+"([^"]+)"',
    re.IGNORECASE,
)
_BLOCK_END = re.compile(
    r'^\s*(END_FUNCTION_BLOCK|END_FUNCTION|END_ORGANIZATION_BLOCK|END_DATA_BLOCK|END_TYPE)\b',
    re.IGNORECASE,
)
_VAR_SECTION = re.compile(
    r'^\s*(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR_GLOBAL|VAR\b(?:\s+CONSTANT)?)',
    re.IGNORECASE,
)
_END_VAR = re.compile(r'^\s*END_VAR\b', re.IGNORECASE)
_VAR_DECL = re.compile(r'^\s+(\w+)\s*:', re.IGNORECASE)
_HASH_VAR = re.compile(r'#(\w+)')
_BLOCK_REF = re.compile(r'"([^"]+)"')
_ADDRESS = re.compile(r'%[IQM][BWD]?\d+(?:\.\d+)?')
_ASSIGNMENT_LHS = re.compile(r'#(\w+)\s*:=')
_ASSIGNMENT_LHS_DB = re.compile(r'"([^"]+)"\.\w+\s*:=')

_BLOCK_TYPE_MAP = {
    "FUNCTION_BLOCK": "FB",
    "FUNCTION": "FC",
    "ORGANIZATION_BLOCK": "OB",
    "DATA_BLOCK": "DB",
    "TYPE": "TYPE",
}


# ─── CrossReference Class ───────────────────────────────────────────────────

class CrossReference:
    """Cross-reference analyzer for SCL source files."""

    def __init__(self):
        self.references: list[Reference] = []
        self.blocks: dict[str, BlockInfo] = {}
        self._files_scanned: list[str] = []

    def scan_file(self, filepath: str) -> None:
        """
        Scan a single SCL file for references.

        Args:
            filepath: Path to .scl file
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        rel_path = str(path)
        self._files_scanned.append(rel_path)

        current_block = ""
        current_block_type = ""
        in_var_section = False
        in_block_comment = False

        for line_num, raw_line in enumerate(lines):
            line = raw_line.rstrip()

            # Skip block comments
            if in_block_comment:
                if "*)" in line:
                    in_block_comment = False
                continue
            if "(*" in line and "*)" not in line:
                in_block_comment = True
                continue

            # Remove line comments for analysis
            code_line = line
            comment_idx = self._find_comment(line)
            if comment_idx >= 0:
                code_line = line[:comment_idx]

            trimmed = code_line.strip()
            if not trimmed:
                continue

            # Block start
            m = _BLOCK_START.match(trimmed)
            if m:
                block_kw = m.group(1).upper()
                block_name = m.group(2)
                bt = _BLOCK_TYPE_MAP.get(block_kw, "?")
                current_block = block_name
                current_block_type = bt

                self.blocks[block_name] = BlockInfo(
                    name=block_name, block_type=bt,
                    file=rel_path, line=line_num,
                )
                self.references.append(Reference(
                    name=block_name, file=rel_path, line=line_num,
                    col=trimmed.index('"'), kind="declaration",
                    ref_type="block", context=trimmed, block=block_name,
                ))
                continue

            # Block end
            if _BLOCK_END.match(trimmed):
                current_block = ""
                current_block_type = ""
                continue

            # VAR section tracking
            if _VAR_SECTION.match(trimmed):
                in_var_section = True
                continue
            if _END_VAR.match(trimmed):
                in_var_section = False
                continue

            # Variable declarations
            if in_var_section:
                vm = _VAR_DECL.match(code_line)
                if vm:
                    var_name = vm.group(1)
                    self.references.append(Reference(
                        name=var_name, file=rel_path, line=line_num,
                        col=code_line.index(var_name), kind="declaration",
                        ref_type="variable", context=trimmed,
                        block=current_block,
                    ))
                    if current_block and current_block in self.blocks:
                        self.blocks[current_block].variables.append(var_name)

                # Also check for UDT type references in declarations
                for bm in _BLOCK_REF.finditer(code_line):
                    ref_name = bm.group(1)
                    # Skip if it's the block declaration itself
                    if ref_name == current_block:
                        continue
                    self.references.append(Reference(
                        name=ref_name, file=rel_path, line=line_num,
                        col=bm.start(), kind="read",
                        ref_type="type", context=trimmed,
                        block=current_block,
                    ))
                continue

            # Skip pragma lines
            if trimmed.startswith("{"):
                continue

            # ── Code analysis (not in VAR sections) ──

            # Find assignments (writes)
            for am in _ASSIGNMENT_LHS.finditer(code_line):
                var_name = am.group(1)
                self.references.append(Reference(
                    name=var_name, file=rel_path, line=line_num,
                    col=am.start(), kind="write",
                    ref_type="variable", context=trimmed,
                    block=current_block,
                ))

            # Find hash variable reads (excluding LHS of assignments)
            assignment_vars = {m.group(1) for m in _ASSIGNMENT_LHS.finditer(code_line)}
            for hm in _HASH_VAR.finditer(code_line):
                var_name = hm.group(1)
                if var_name in assignment_vars:
                    # Check if this specific occurrence is the LHS
                    before = code_line[:hm.start()]
                    after = code_line[hm.end():]
                    if ":=" in after[:5]:
                        continue  # This is the write, already recorded
                self.references.append(Reference(
                    name=var_name, file=rel_path, line=line_num,
                    col=hm.start(), kind="read",
                    ref_type="variable", context=trimmed,
                    block=current_block,
                ))

            # Find block references ("BlockName")
            for bm in _BLOCK_REF.finditer(code_line):
                ref_name = bm.group(1)
                if ref_name == current_block:
                    continue  # Skip self-reference in header

                # Determine if call or read
                after = code_line[bm.end():].lstrip()
                if after.startswith("("):
                    kind = "call"
                elif after.startswith("."):
                    kind = "read"
                else:
                    kind = "read"

                self.references.append(Reference(
                    name=ref_name, file=rel_path, line=line_num,
                    col=bm.start(), kind=kind,
                    ref_type="block", context=trimmed,
                    block=current_block,
                ))

                if current_block and current_block in self.blocks:
                    if kind == "call" and ref_name not in self.blocks[current_block].calls:
                        self.blocks[current_block].calls.append(ref_name)

            # Find hardware addresses
            for am in _ADDRESS.finditer(code_line):
                addr = am.group(0)
                # Determine read/write based on assignment
                before = code_line[:am.start()]
                after = code_line[am.end():].lstrip()
                if ":=" in after[:5]:
                    kind = "write"  # address on LHS
                else:
                    kind = "read"

                self.references.append(Reference(
                    name=addr, file=rel_path, line=line_num,
                    col=am.start(), kind=kind,
                    ref_type="address", context=trimmed,
                    block=current_block,
                ))

                if current_block and current_block in self.blocks:
                    if addr not in self.blocks[current_block].addresses:
                        self.blocks[current_block].addresses.append(addr)

    def scan_directory(self, directory: str, recursive: bool = True) -> int:
        """
        Scan all .scl files in a directory.

        Args:
            directory: Directory path
            recursive: Search subdirectories

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

    # ── Query Methods ────────────────────────────────────────────────────────

    def find_usages(self, name: str) -> list[Reference]:
        """Find all references to a symbol (variable, block, or address)."""
        return [r for r in self.references if r.name == name]

    def find_usages_like(self, pattern: str) -> list[Reference]:
        """Find references matching a regex pattern."""
        regex = re.compile(pattern, re.IGNORECASE)
        return [r for r in self.references if regex.search(r.name)]

    def find_unused(self) -> list[Reference]:
        """Find variables that are declared but never read or written."""
        # Collect all declarations
        declarations = {}
        for r in self.references:
            if r.kind == "declaration" and r.ref_type == "variable":
                key = (r.block, r.name)
                declarations[key] = r

        # Remove those that have usage
        for r in self.references:
            if r.kind != "declaration" and r.ref_type == "variable":
                key = (r.block, r.name)
                declarations.pop(key, None)

        return list(declarations.values())

    def find_dependencies(self, block_name: str) -> dict:
        """
        Find what a block depends on (calls, variables, addresses).

        Returns:
            Dict with keys: calls, variables, addresses, types
        """
        refs = [r for r in self.references if r.block == block_name and r.kind != "declaration"]

        calls = sorted(set(r.name for r in refs if r.ref_type == "block" and r.kind == "call"))
        blocks_read = sorted(set(r.name for r in refs if r.ref_type == "block" and r.kind == "read"))
        addresses = sorted(set(r.name for r in refs if r.ref_type == "address"))
        types = sorted(set(r.name for r in refs if r.ref_type == "type"))

        return {
            "calls": calls,
            "block_reads": blocks_read,
            "addresses": addresses,
            "types": types,
        }

    def find_dependents(self, block_name: str) -> list[str]:
        """Find which blocks reference the given block."""
        dependents = set()
        for r in self.references:
            if r.name == block_name and r.block and r.block != block_name:
                dependents.add(r.block)
        return sorted(dependents)

    def get_block_summary(self) -> list[dict]:
        """Get a summary of all blocks with their dependencies."""
        result = []
        for name, info in self.blocks.items():
            deps = self.find_dependencies(name)
            result.append({
                "name": name,
                "type": info.block_type,
                "file": info.file,
                "line": info.line,
                "variables": len(info.variables),
                "calls": deps["calls"],
                "addresses": deps["addresses"],
                "types": deps["types"],
            })
        return result

    # ── Export Methods ────────────────────────────────────────────────────────

    def export_csv(self, filepath: str) -> None:
        """Export all references to CSV."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Name", "File", "Line", "Col", "Kind", "Type", "Block", "Context"])
            for r in self.references:
                writer.writerow([r.name, r.file, r.line + 1, r.col, r.kind, r.ref_type, r.block, r.context])

        print(f"Exported {len(self.references)} references to {path}")

    def export_json(self, filepath: str) -> None:
        """Export all references and blocks to JSON."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "files_scanned": self._files_scanned,
            "blocks": {name: asdict(info) for name, info in self.blocks.items()},
            "references": [asdict(r) for r in self.references],
            "summary": {
                "total_references": len(self.references),
                "total_blocks": len(self.blocks),
                "total_files": len(self._files_scanned),
                "unused_variables": len(self.find_unused()),
            },
        }

        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Exported to {path}")

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _find_comment(line: str) -> int:
        """Find start of // comment (outside strings)."""
        in_string = False
        string_char = ""
        for i in range(len(line) - 1):
            ch = line[i]
            if in_string:
                if ch == string_char:
                    in_string = False
            else:
                if ch in ("'", '"'):
                    in_string = True
                    string_char = ch
                elif ch == "/" and line[i + 1] == "/":
                    return i
        return -1


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    xref = CrossReference()

    # Default: scan generated_scl directory
    scan_dir = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent / "generated_scl")

    print(f"Scanning: {scan_dir}")
    count = xref.scan_directory(scan_dir)
    print(f"Scanned {count} file(s)")
    print()

    # Block summary
    print("Blocks found:")
    print("-" * 70)
    for info in xref.get_block_summary():
        calls_str = ", ".join(info["calls"]) if info["calls"] else "-"
        print(f"  {info['type']:5s} {info['name']:25s} vars={info['variables']:2d}  calls=[{calls_str}]")
    print()

    # Unused variables
    unused = xref.find_unused()
    if unused:
        print(f"Unused variables ({len(unused)}):")
        for r in unused:
            print(f"  {r.block}#{r.name}  ({r.file}:{r.line + 1})")
    print()

    # Export
    output_dir = Path(scan_dir) / "xref"
    output_dir.mkdir(exist_ok=True)
    xref.export_csv(str(output_dir / "cross_reference.csv"))
    xref.export_json(str(output_dir / "cross_reference.json"))
