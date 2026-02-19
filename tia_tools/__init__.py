"""
TIA Tools - Python toolkit for Siemens TIA Portal projects.

Modules:
    tia_project_reader  - Read TIA projects without TIA Portal (parses PLF binary)
    tia_project_creator - Create TIA projects via Openness API (requires TIA Portal)
    tia_block_generator - Generate TIA Openness XML blocks (no TIA Portal needed)
    tia_tag_export      - CSV/Excel tag import/export (no TIA Portal needed)
"""

from .tia_project_reader import TiaProjectReader, ProjectInfo
from .tia_block_generator import TiaBlockGenerator, MemberDef, NetworkDef
from .tia_block_generator import BOOL, INT, DINT, REAL, LREAL, WORD, DWORD, STRING, TIME
from .tia_tag_export import TiaTagExporter, TiaTagImporter, export_project_tags, csv_to_tag_table, csv_to_db

__all__ = [
    "TiaProjectReader",
    "ProjectInfo",
    "TiaBlockGenerator",
    "MemberDef",
    "NetworkDef",
    "TiaTagExporter",
    "TiaTagImporter",
    "export_project_tags",
    "csv_to_tag_table",
    "csv_to_db",
    "BOOL", "INT", "DINT", "REAL", "LREAL", "WORD", "DWORD", "STRING", "TIME",
]
