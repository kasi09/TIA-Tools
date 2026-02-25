"""
TIA Tools - Python toolkit for Siemens TIA Portal projects.

Modules:
    tia_project_reader  - Read TIA projects without TIA Portal (parses PLF binary)
    tia_project_creator - Create TIA projects via Openness API (requires TIA Portal)
    tia_block_generator - Generate TIA Openness XML blocks (no TIA Portal needed)
    tia_tag_export      - CSV/Excel tag import/export (no TIA Portal needed)
    tia_scl_generator   - Generate SCL source files (no TIA Portal needed)
    tia_block_library   - Standard block templates (Motor, Valve, PID, Alarm, Scale)
    tia_cross_reference - Cross-reference analysis for SCL files
    tia_doc_generator   - HTML documentation generator for SCL projects
"""

from .tia_project_reader import TiaProjectReader, ProjectInfo
from .tia_block_generator import TiaBlockGenerator, MemberDef, NetworkDef
from .tia_block_generator import BOOL, INT, DINT, REAL, LREAL, WORD, DWORD, STRING, TIME
from .tia_tag_export import TiaTagExporter, TiaTagImporter, export_project_tags, csv_to_tag_table, csv_to_db
from .tia_scl_generator import SclGenerator
from .tia_block_library import BlockLibrary
from .tia_cross_reference import CrossReference
from .tia_doc_generator import DocGenerator

__all__ = [
    "TiaProjectReader",
    "ProjectInfo",
    "TiaBlockGenerator",
    "MemberDef",
    "NetworkDef",
    "SclGenerator",
    "BlockLibrary",
    "CrossReference",
    "DocGenerator",
    "TiaTagExporter",
    "TiaTagImporter",
    "export_project_tags",
    "csv_to_tag_table",
    "csv_to_db",
    "BOOL", "INT", "DINT", "REAL", "LREAL", "WORD", "DWORD", "STRING", "TIME",
]
