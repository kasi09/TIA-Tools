"""
TIA Portal Project Reader - Reads TIA Portal v14+ project files without TIA Portal installed.

Parses the binary PEData.plf file to extract:
- Project metadata (name, version, creation date)
- Hardware configuration (stations, CPUs, modules)
- Program block definitions (OB, FB, FC, DB types and interfaces)
- Library versions and dependencies
- MetaInfo schema definitions

Usage:
    reader = TiaProjectReader("path/to/project/folder")
    info = reader.read()
    print(info.summary())
"""

import struct
import zlib
import sqlite3
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class DeviceInfo:
    name: str
    role: str
    template: str
    object_id: str
    order_number: str = ""
    manufacturer: str = ""
    description: str = ""


@dataclass
class CpuInfo:
    name: str
    order_number: str
    firmware_version: str
    subtype: str
    description: str
    memory_code_kb: int = 0
    memory_data_kb: int = 0
    max_blocks: int = 0
    supported_languages: str = ""


@dataclass
class LibraryRef:
    guid: str
    display_version: str
    switch_minor: bool = False


@dataclass
class BlockInterface:
    """A member/parameter of a program block interface."""
    member_id: int
    name: str
    rid: str
    lid: int = 0
    offset: int = -1
    flags: int = 0


@dataclass
class ProgramBlock:
    """Represents a Safety / System function block found in the project."""
    name: str
    block_type: str = ""  # FB, FC, OB, DB
    members: list = field(default_factory=list)


@dataclass
class ProjectInfo:
    name: str = ""
    tia_version: str = ""
    station_name: str = ""
    cpu: Optional[CpuInfo] = None
    devices: list = field(default_factory=list)
    libraries: list = field(default_factory=list)
    meta_packages: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    timestamps: list = field(default_factory=list)
    xref_tables: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"  TIA Project: {self.name}",
            f"  TIA Portal Version: {self.tia_version}",
            f"{'='*60}",
            "",
        ]
        if self.station_name:
            lines.append(f"  Station: {self.station_name}")
        if self.cpu:
            lines += [
                f"  CPU: {self.cpu.name}",
                f"    Order Number: {self.cpu.order_number}",
                f"    Firmware: {self.cpu.firmware_version}",
                f"    Subtype: {self.cpu.subtype}",
                f"    Max Blocks: {self.cpu.max_blocks}",
                f"    Languages: {self.cpu.supported_languages}",
            ]
        if self.devices:
            lines.append(f"\n  Hardware Components ({len(self.devices)}):")
            for d in self.devices:
                extra = f" [{d.order_number}]" if d.order_number else ""
                lines.append(f"    - {d.name} (Role: {d.role}){extra}")
        if self.libraries:
            lines.append(f"\n  Libraries ({len(self.libraries)}):")
            for lib in self.libraries:
                lines.append(f"    - {lib.guid}  {lib.display_version}")
        if self.meta_packages:
            lines.append(f"\n  MetaInfo Packages ({len(self.meta_packages)}):")
            for pkg in self.meta_packages:
                lines.append(f"    - {pkg}")
        if self.blocks:
            lines.append(f"\n  Program Blocks ({len(self.blocks)}):")
            for blk in self.blocks:
                lines.append(f"    - {blk.name} ({blk.block_type}, {len(blk.members)} members)")
        if self.timestamps:
            lines.append(f"\n  Timestamps: {self.timestamps[0]} ... {self.timestamps[-1]}")
        if self.xref_tables:
            lines.append(f"\n  XRef Database:")
            for table, count in self.xref_tables.items():
                lines.append(f"    - {table}: {count} rows")
        lines.append("")
        return "\n".join(lines)


# ─── PLF Header ───────────────────────────────────────────────────────────────

@dataclass
class PlfHeader:
    header_size: int
    version: int
    guid: bytes
    data_size: int
    entry_count: int
    block_count: int


# ─── Reader ───────────────────────────────────────────────────────────────────

class TiaProjectReader:
    """Reads a TIA Portal project directory and extracts all available information."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        # Support pointing to either the .ap14 parent or the inner folder
        if self.project_path.suffix in (".ap14", ".ap15", ".ap16", ".ap17", ".ap18", ".ap19", ".ap20"):
            self.project_path = self.project_path.parent
        self._plf_data: bytes = b""
        self._idx_data: bytes = b""
        self._zlib_blocks: list = []

    def read(self) -> ProjectInfo:
        """Read the full project and return a ProjectInfo object."""
        info = ProjectInfo()

        # 1. Read .ap file (XML wrapper)
        self._read_ap_file(info)

        # 2. Read PEData.plf (binary database)
        plf_path = self.project_path / "System" / "PEData.plf"
        if plf_path.exists():
            self._plf_data = plf_path.read_bytes()
            self._extract_zlib_blocks()
            self._parse_meta_packages(info)
            self._parse_devices(info)
            self._parse_cpu_attributes(info)
            self._parse_library_versions(info)
            self._parse_block_interfaces(info)
            self._parse_timestamps(info)

        # 3. Read XRef database
        xref_path = self.project_path / "XRef" / "XRef.db"
        if xref_path.exists():
            self._read_xref(xref_path, info)

        return info

    # ── AP File ───────────────────────────────────────────────────────────────

    def _read_ap_file(self, info: ProjectInfo):
        """Parse the .ap14/.ap15/etc XML project file."""
        ap_files = list(self.project_path.glob("*.ap*"))
        ap_files = [f for f in ap_files if re.match(r"\.ap\d+$", f.suffix)]
        if not ap_files:
            return
        ap_file = ap_files[0]
        try:
            tree = ET.parse(str(ap_file))
            root = tree.getroot()
            ns = re.match(r"\{(.+?)\}", root.tag)
            if ns:
                info.name = root.get("Name", "")
                info.tia_version = root.get("ProjectCompatibilityVersion", "")
            else:
                info.name = root.get("Name", "")
                info.tia_version = root.get("ProjectCompatibilityVersion", "")
        except ET.ParseError:
            info.name = ap_file.stem

    # ── PLF Binary Parsing ────────────────────────────────────────────────────

    def _parse_plf_header(self) -> PlfHeader:
        """Parse the 64-byte PLF header."""
        if len(self._plf_data) < 64:
            return PlfHeader(0, 0, b"", 0, 0, 0)
        h = PlfHeader(
            header_size=struct.unpack_from("<I", self._plf_data, 0)[0],
            version=struct.unpack_from("<I", self._plf_data, 4)[0],
            guid=self._plf_data[8:24],
            data_size=struct.unpack_from("<I", self._plf_data, 24)[0],
            entry_count=struct.unpack_from("<I", self._plf_data, 28)[0],
            block_count=struct.unpack_from("<I", self._plf_data, 32)[0],
        )
        return h

    def _extract_zlib_blocks(self):
        """Find and decompress all zlib-compressed blocks in PLF."""
        data = self._plf_data
        self._zlib_blocks = []
        i = 0
        while i < len(data) - 2:
            if data[i] == 0x78 and data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
                try:
                    obj = zlib.decompressobj()
                    decompressed = obj.decompress(data[i:])
                    comp_size = len(data[i:]) - len(obj.unused_data)
                    if len(decompressed) >= 10:
                        self._zlib_blocks.append({
                            "offset": i,
                            "comp_size": comp_size,
                            "data": decompressed,
                            "size": len(decompressed),
                        })
                        i += comp_size
                        continue
                except Exception:
                    pass
            i += 1

    def _find_blocks_containing(self, *patterns: bytes) -> list:
        """Return decompressed blocks that contain all given byte patterns."""
        results = []
        for block in self._zlib_blocks:
            if all(p in block["data"] for p in patterns):
                results.append(block)
        return results

    # ── MetaInfo Packages ─────────────────────────────────────────────────────

    def _parse_meta_packages(self, info: ProjectInfo):
        """Extract Package names from MetaInfo XML blocks."""
        for block in self._zlib_blocks:
            if block["size"] > 10000 and b"<MetaInfo" in block["data"][:200]:
                text = block["data"].decode("utf-8", errors="replace")
                packages = re.findall(r'Package name="([^"]+)"', text)
                info.meta_packages.extend(packages)

    # ── Device Configuration ──────────────────────────────────────────────────

    def _parse_devices(self, info: ProjectInfo):
        """Parse device/hardware info from data pages."""
        for block in self._zlib_blocks:
            if block["size"] != 4096:
                continue
            data = block["data"]
            # Look for the device page pattern: length-prefixed strings with
            # Role/Template/ObjectId markers
            if b"S7PCentralStation" not in data:
                continue

            strings = self._extract_length_prefixed_strings(data)
            if not strings:
                continue

            # Parse station name
            for s in strings:
                if "Station" in s and "/" in s:
                    info.station_name = s
                    break

            # Parse device entries: they come in groups of
            # (Role, <role>, Template, <template>, ObjectId, <id>)
            i = 0
            while i < len(strings) - 1:
                if strings[i] == "Role" and i + 5 < len(strings):
                    role = strings[i + 1] if i + 1 < len(strings) else ""
                    template = ""
                    obj_id = ""
                    # Look ahead for Template and ObjectId
                    for j in range(i + 2, min(i + 8, len(strings))):
                        if strings[j] == "Template" and j + 1 < len(strings):
                            template = strings[j + 1]
                        if strings[j] == "ObjectId" and j + 1 < len(strings):
                            obj_id = strings[j + 1]

                    if role and template:
                        info.devices.append(DeviceInfo(
                            name="",  # filled below
                            role=role,
                            template=template,
                            object_id=obj_id,
                        ))
                    i += 6
                else:
                    i += 1

            # Parse hardware catalog entries (name, order number, manufacturer)
            # Pattern: Manufacturer Name, Component Name, Order Number
            catalog_entries = []
            for s in strings:
                if re.match(r"6ES7\s", s) or re.match(r"6ES\d", s):
                    catalog_entries.append(s)

            # Match device names from the initial string list
            device_names = []
            for s in strings:
                if s.endswith("_1") or s.endswith("_2"):
                    device_names.append(s)

            # Assign names to devices where possible
            for idx, dev in enumerate(info.devices):
                if idx < len(device_names):
                    # Try to find a matching name
                    pass

            # Also extract from the catalog section
            self._parse_hardware_catalog(data, strings, info)

    def _parse_hardware_catalog(self, data: bytes, strings: list, info: ProjectInfo):
        """Extract hardware order numbers and descriptions."""
        # Find patterns like "Siemens\x0eCPU 1515F-2 PN\x136ES7 515-2FM01-0AB0"
        i = 0
        while i < len(data) - 10:
            # Look for "Siemens" followed by component description
            if data[i:i + 7] == b"Siemens":
                # Go backwards to find the name
                # Go forwards to find order number
                j = i + 7
                if j < len(data):
                    name_len = data[j]
                    if 2 < name_len < 100 and j + 1 + name_len <= len(data):
                        name = data[j + 1:j + 1 + name_len].decode("utf-8", errors="replace")
                        k = j + 1 + name_len
                        if k < len(data):
                            order_len = data[k]
                            if 5 < order_len < 50 and k + 1 + order_len <= len(data):
                                order_num = data[k + 1:k + 1 + order_len].decode("utf-8", errors="replace")
                                if re.match(r"6ES\d", order_num):
                                    # Found a valid catalog entry
                                    for dev in info.devices:
                                        if not dev.order_number and dev.name == "":
                                            dev.name = name
                                            dev.order_number = order_num
                                            dev.manufacturer = "Siemens"
                                            break
                i += 1
            else:
                i += 1

    def _extract_length_prefixed_strings(self, data: bytes) -> list:
        """Extract length-prefixed strings (1-byte length prefix) from binary data."""
        strings = []
        i = 0
        while i < len(data) - 1:
            length = data[i]
            if 2 <= length <= 200 and i + 1 + length <= len(data):
                try:
                    s = data[i + 1:i + 1 + length].decode("utf-8")
                    if s.isprintable() and len(s) >= 2:
                        strings.append(s)
                        i += 1 + length
                        continue
                except (UnicodeDecodeError, ValueError):
                    pass
            i += 1
        return strings

    # ── CPU Attributes ────────────────────────────────────────────────────────

    def _parse_cpu_attributes(self, info: ProjectInfo):
        """Extract CPU configuration attributes from MetaAttributes XML pages."""
        for block in self._zlib_blocks:
            if block["size"] != 4096:
                continue
            data = block["data"]
            if b'Attribute Name="FwVersion"' not in data and b'Name="Subtype"' not in data:
                continue
            text = data.decode("utf-8", errors="replace")

            fw_ver = self._extract_attr(text, "FwVersion")
            subtype = self._extract_attr(text, "Subtype")
            desc = self._extract_attr(text, "Description")
            max_blocks = self._extract_attr(text, "IecplMaxNumberOfBlocks")
            languages = self._extract_attr(text, "IecplSupportedLanguages")
            max_mem = self._extract_attr(text, "IecplMaxMemory")

            if fw_ver or subtype:
                # Try to find CPU name from device catalog pages
                cpu_name = ""
                cpu_order = ""

                # Search hardware catalog pages for CPU name + order number
                for block2 in self._zlib_blocks:
                    if block2["size"] != 4096:
                        continue
                    d2 = block2["data"]
                    if b"Siemens" not in d2 or b"6ES7" not in d2:
                        continue
                    strs = self._extract_length_prefixed_strings(d2)
                    for s in strs:
                        # CPU name pattern: "CPU 1515F-2 PN", "CPU 1516-3 PN/DP" etc.
                        if re.match(r"CPU \d{4}", s) and not cpu_name:
                            cpu_name = s
                        if re.match(r"6ES7 \d{3}", s) and not cpu_order:
                            cpu_order = s
                    if cpu_name and cpu_order:
                        break

                # Fallback: check device list
                if not cpu_name:
                    for dev in info.devices:
                        if dev.order_number and "CPU" in dev.name:
                            cpu_name = dev.name
                            cpu_order = dev.order_number
                            break

                info.cpu = CpuInfo(
                    name=cpu_name or "Unknown CPU",
                    order_number=cpu_order,
                    firmware_version=fw_ver or "",
                    subtype=subtype or "",
                    description=desc[:200] if desc else "",
                    max_blocks=int(max_blocks) if max_blocks else 0,
                    supported_languages=self._decode_languages(languages),
                )
                break

    @staticmethod
    def _extract_attr(text: str, attr_name: str) -> str:
        """Extract Value from: <Attribute Name="X" Type="T" Value="V" />"""
        # Use a precise pattern that matches the exact attribute name
        pattern = rf'<Attribute Name="{re.escape(attr_name)}" Type="[^"]*" Value="([^"]*)"'
        m = re.search(pattern, text)
        return m.group(1) if m else ""

    @staticmethod
    def _decode_languages(lang_str: str) -> str:
        """Decode TIA language codes: 1=LAD, 2=FBD, 3=STL, 4=SCL, 6=GRAPH"""
        lang_map = {"1": "LAD", "2": "FBD", "3": "STL", "4": "SCL", "5": "CFC", "6": "GRAPH"}
        if not lang_str:
            return ""
        codes = lang_str.split(";")
        return ", ".join(lang_map.get(c.strip(), f"?{c}") for c in codes if c.strip())

    # ── Library Versions ──────────────────────────────────────────────────────

    def _parse_library_versions(self, info: ProjectInfo):
        """Extract library version references from LibraryVersions XML."""
        for block in self._zlib_blocks:
            if b"<LibraryVersions" in block["data"][:100]:
                text = block["data"].decode("utf-8", errors="replace")
                for m in re.finditer(
                    r'Library LibGuid="([^"]+)" DisplayVersion="([^"]+)"'
                    r'(?:\s+SwitchMinor="([^"]*)")?',
                    text,
                ):
                    info.libraries.append(LibraryRef(
                        guid=m.group(1),
                        display_version=m.group(2),
                        switch_minor=m.group(3) == "true" if m.group(3) else False,
                    ))

    # ── Block Interfaces ──────────────────────────────────────────────────────

    def _parse_block_interfaces(self, info: ProjectInfo):
        """Extract program block interface definitions from data pages."""
        for block in self._zlib_blocks:
            if block["size"] != 4096:
                continue
            data = block["data"]
            if b"<Root RIdSlots" not in data:
                continue
            text = data.decode("utf-8", errors="replace")

            # Extract members
            members = []
            for m in re.finditer(
                r'<Member ID="(\d+)" Name="([^"]+)" RID="([^"]+)"'
                r'(?:\s+StdO="(\d+)")?'
                r'(?:\s+[^/]*)?\s*LID="(\d+)"',
                text,
            ):
                members.append(BlockInterface(
                    member_id=int(m.group(1)),
                    name=m.group(2),
                    rid=m.group(3),
                    offset=int(m.group(4)) if m.group(4) else -1,
                    lid=int(m.group(5)),
                ))

            if members:
                # Try to determine block name from context
                block_name = "Unknown"
                if b"F_PROG_DAT" in data or b"F_RTG_DAT" in data:
                    block_name = "SafeSys (F-System DB)"
                elif b"ChannelInfo" in data:
                    block_name = "DiagnosticAlarm (OB82)"
                elif b"_dnVKE_" in data or b"_lnCACHE" in data:
                    block_name = "F_CTRL (Safety FB)"
                elif b"IdentXmlPart" in data:
                    block_name = "Main (OB1)"

                info.blocks.append(ProgramBlock(
                    name=block_name,
                    block_type="FB" if "FB" in block_name or "F_" in block_name else "OB",
                    members=members,
                ))

    # ── Timestamps ────────────────────────────────────────────────────────────

    def _parse_timestamps(self, info: ProjectInfo):
        """Extract timestamps from device pages."""
        for block in self._zlib_blocks:
            if block["size"] != 4096:
                continue
            data = block["data"]
            # Pattern: "2/19/2026 11:20:55 AM"
            for m in re.finditer(rb'\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M', data):
                ts = m.group().decode("ascii")
                if ts not in info.timestamps:
                    info.timestamps.append(ts)

    # ── XRef Database ─────────────────────────────────────────────────────────

    def _read_xref(self, xref_path: Path, info: ProjectInfo):
        """Read the XRef SQLite database."""
        try:
            conn = sqlite3.connect(str(xref_path))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            for (table_name,) in tables:
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                count = cursor.fetchone()[0]
                info.xref_tables[table_name] = count
            conn.close()
        except Exception:
            pass


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python tia_project_reader.py <project_folder>")
        print("  e.g.: python tia_project_reader.py D:/Projects/MyProject/MyProject")
        sys.exit(1)

    reader = TiaProjectReader(sys.argv[1])
    project_info = reader.read()
    print(project_info.summary())
