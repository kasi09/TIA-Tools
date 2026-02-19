"""
TIA Portal Block XML Generator - Creates TIA Openness-compatible XML files.

Generates XML for program blocks (OB, FB, FC, DB) that can be imported
into TIA Portal via the Openness API or manually through the TIA Portal GUI.

Supports:
  - Organization Blocks (OB) with LAD/FBD/SCL networks
  - Function Blocks (FB) with instance data
  - Functions (FC)
  - Data Blocks (DB) with typed members
  - Global tag tables

No TIA Portal installation required - generates standard XML files.

Usage:
    gen = TiaBlockGenerator()
    gen.create_ob1_main(networks=[
        gen.scl_network("Startup", "// Startup logic here"),
    ])
    gen.save("Main_OB1.xml")
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from datetime import datetime
from typing import Optional
import uuid


# ─── Constants ────────────────────────────────────────────────────────────────

TIA_OPENNESS_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v3"
NAMESPACE_MAP = {
    "": "http://www.siemens.com/automation/Openness/SW/Interface/v3",
}

# Standard data types
BOOL = "Bool"
INT = "Int"
DINT = "DInt"
REAL = "Real"
LREAL = "LReal"
WORD = "Word"
DWORD = "DWord"
STRING = "String"
WSTRING = "WString"
TIME = "Time"
DATE_AND_TIME = "Date_And_Time"
ARRAY = "Array"


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _indent_xml(elem: ET.Element) -> str:
    """Pretty-print an XML element."""
    rough = ET.tostring(elem, encoding="unicode", xml_declaration=False)
    parsed = minidom.parseString(rough)
    pretty = parsed.toprettyxml(indent="  ", encoding=None)
    # Remove the XML declaration that minidom adds
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines = lines[1:]
    return "\n".join(lines)


def _new_id() -> str:
    """Generate a unique ID for XML elements."""
    return str(uuid.uuid4().int % 0xFFFFFFFF)


# ─── Data Type Definitions ────────────────────────────────────────────────────

class MemberDef:
    """Definition of a block interface member (parameter or static variable)."""

    def __init__(
        self,
        name: str,
        data_type: str,
        section: str = "Static",
        initial_value: str = None,
        comment: str = None,
        array_lower: int = None,
        array_upper: int = None,
        array_type: str = None,
    ):
        self.name = name
        self.data_type = data_type
        self.section = section  # Input, Output, InOut, Static, Temp, Constant, Return
        self.initial_value = initial_value
        self.comment = comment
        self.array_lower = array_lower
        self.array_upper = array_upper
        self.array_type = array_type


class NetworkDef:
    """Definition of a program block network."""

    def __init__(self, title: str, language: str = "SCL", code: str = ""):
        self.title = title
        self.language = language  # SCL, LAD, FBD, STL
        self.code = code


# ─── Block Generator ──────────────────────────────────────────────────────────

class TiaBlockGenerator:
    """Generates TIA Portal Openness-compatible XML block files."""

    def __init__(self, author: str = "Python Generator", family: str = ""):
        self.author = author
        self.family = family
        self._document = None
        self._root = None

    # ── Organization Blocks ───────────────────────────────────────────────────

    def create_ob(
        self,
        number: int = 1,
        name: str = "Main",
        language: str = "SCL",
        networks: list = None,
        members: list = None,
        comment: str = "",
        event_class: str = "ProgramCycle",
        secondary_type: str = None,
    ) -> ET.Element:
        """
        Create an Organization Block (OB).

        Args:
            number: OB number (1=Main, 100=Startup, etc.)
            name: Block name
            language: Programming language (SCL, LAD, FBD, STL)
            networks: List of NetworkDef objects
            members: List of MemberDef objects for Temp section
            comment: Block comment
            event_class: OB event class (ProgramCycle, Startup, CyclicInterrupt, etc.)
        """
        doc = self._create_document()
        block = self._add_block(doc, "OB", number, name, language, comment)

        # Attribute list
        attr_list = self._add_element(block, "AttributeList")

        # Interface
        interface = self._add_element(attr_list, "Interface")
        sections = self._add_element(interface, "Sections",
                                     xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v3")

        # Input section (OBs typically have a standard Temp section)
        if members:
            for section_name in ["Input", "Output", "InOut", "Temp", "Constant"]:
                section_members = [m for m in members if m.section == section_name]
                if section_members:
                    section = self._add_element(sections, "Section", Name=section_name)
                    for m in section_members:
                        self._add_member(section, m)
        else:
            # Default Temp section for OB
            temp_section = self._add_element(sections, "Section", Name="Temp")
            self._add_member(temp_section, MemberDef("Temp_OB_info", "Word", "Temp"))

        # Networks
        if networks:
            self._add_networks(attr_list, networks, language)

        self._document = doc
        self._root = block
        return doc

    def create_ob1_main(self, networks: list = None, language: str = "SCL") -> ET.Element:
        """Convenience: Create OB1 (Main program cycle)."""
        return self.create_ob(
            number=1, name="Main", language=language,
            networks=networks or [NetworkDef("Main Logic", "SCL", "// Main program logic")],
            comment="Main Program Sweep (Cycle)",
        )

    def create_ob100_startup(self, networks: list = None, language: str = "SCL") -> ET.Element:
        """Convenience: Create OB100 (Startup)."""
        return self.create_ob(
            number=100, name="Startup", language=language,
            networks=networks or [NetworkDef("Initialization", "SCL", "// Startup initialization")],
            comment="Startup Organization Block",
            event_class="Startup",
        )

    # ── Function Blocks ───────────────────────────────────────────────────────

    def create_fb(
        self,
        number: int,
        name: str,
        language: str = "SCL",
        members: list = None,
        networks: list = None,
        comment: str = "",
        version: str = "0.1",
    ) -> ET.Element:
        """
        Create a Function Block (FB).

        Args:
            number: FB number
            name: Block name
            language: Programming language
            members: List of MemberDef for Input/Output/InOut/Static/Temp
            networks: List of NetworkDef
            comment: Block comment
            version: Block version string
        """
        doc = self._create_document()
        block = self._add_block(doc, "FB", number, name, language, comment, version)

        attr_list = self._add_element(block, "AttributeList")

        # Interface with all sections
        interface = self._add_element(attr_list, "Interface")
        sections = self._add_element(interface, "Sections",
                                     xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v3")

        if members:
            for section_name in ["Input", "Output", "InOut", "Static", "Temp", "Constant"]:
                section_members = [m for m in members if m.section == section_name]
                section = self._add_element(sections, "Section", Name=section_name)
                for m in section_members:
                    self._add_member(section, m)
        else:
            for section_name in ["Input", "Output", "InOut", "Static", "Temp"]:
                self._add_element(sections, "Section", Name=section_name)

        if networks:
            self._add_networks(attr_list, networks, language)

        self._document = doc
        return doc

    # ── Functions ─────────────────────────────────────────────────────────────

    def create_fc(
        self,
        number: int,
        name: str,
        language: str = "SCL",
        members: list = None,
        networks: list = None,
        comment: str = "",
        return_type: str = "Void",
        version: str = "0.1",
    ) -> ET.Element:
        """
        Create a Function (FC).

        Args:
            number: FC number
            name: Block name
            language: Programming language
            members: List of MemberDef for Input/Output/InOut/Temp/Return
            networks: List of NetworkDef
            comment: Block comment
            return_type: Return data type (Void, Bool, Int, etc.)
            version: Block version string
        """
        doc = self._create_document()
        block = self._add_block(doc, "FC", number, name, language, comment, version)

        attr_list = self._add_element(block, "AttributeList")

        interface = self._add_element(attr_list, "Interface")
        sections = self._add_element(interface, "Sections",
                                     xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v3")

        if members:
            for section_name in ["Input", "Output", "InOut", "Temp", "Return"]:
                section_members = [m for m in members if m.section == section_name]
                section = self._add_element(sections, "Section", Name=section_name)
                for m in section_members:
                    self._add_member(section, m)
        else:
            for section_name in ["Input", "Output", "InOut", "Temp", "Return"]:
                section = self._add_element(sections, "Section", Name=section_name)
                if section_name == "Return":
                    self._add_member(section, MemberDef("Ret_Val", return_type, "Return"))

        if networks:
            self._add_networks(attr_list, networks, language)

        self._document = doc
        return doc

    # ── Data Blocks ───────────────────────────────────────────────────────────

    def create_db(
        self,
        number: int,
        name: str,
        members: list = None,
        comment: str = "",
        optimized: bool = True,
        version: str = "0.1",
    ) -> ET.Element:
        """
        Create a Data Block (DB).

        Args:
            number: DB number
            name: Block name
            members: List of MemberDef (all go into Static section)
            comment: Block comment
            optimized: Use optimized block access (default True for S7-1500)
            version: Block version
        """
        doc = self._create_document()
        block = self._add_block(doc, "GlobalDB", number, name, "DB", comment, version)

        attr_list = self._add_element(block, "AttributeList")

        # Memory layout attribute
        if not optimized:
            mem_layout = self._add_element(attr_list, "MemoryLayout")
            mem_layout.text = "Standard"

        interface = self._add_element(attr_list, "Interface")
        sections = self._add_element(interface, "Sections",
                                     xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v3")

        static_section = self._add_element(sections, "Section", Name="Static")
        if members:
            for m in members:
                self._add_member(static_section, m)

        self._document = doc
        return doc

    # ── Tag Tables ────────────────────────────────────────────────────────────

    def create_tag_table(
        self,
        name: str,
        tags: list,
    ) -> ET.Element:
        """
        Create a PLC tag table XML.

        Args:
            name: Tag table name
            tags: List of dicts with keys: name, data_type, address, comment
        """
        doc = ET.Element("Document")
        doc.set("xmlns", "http://www.siemens.com/automation/Openness/SW/Interface/v3")

        engineering = self._add_element(doc, "Engineering", version="V14")
        tag_table = self._add_element(doc, "SW.Tags.PlcTagTable", ID="0")
        attr_list = self._add_element(tag_table, "AttributeList")
        name_elem = self._add_element(attr_list, "Name")
        name_elem.text = name

        object_list = self._add_element(tag_table, "ObjectList")

        for tag_def in tags:
            tag = self._add_element(object_list, "SW.Tags.PlcTag", ID=_new_id())
            tag_attrs = self._add_element(tag, "AttributeList")

            tag_name = self._add_element(tag_attrs, "Name")
            tag_name.text = tag_def["name"]

            tag_type = self._add_element(tag_attrs, "DataTypeName")
            tag_type.text = tag_def["data_type"]

            if tag_def.get("address"):
                tag_addr = self._add_element(tag_attrs, "LogicalAddress")
                tag_addr.text = tag_def["address"]

            if tag_def.get("comment"):
                comment_elem = self._add_element(tag_attrs, "Comment")
                ml_text = self._add_element(comment_elem, "MultiLanguageText", Lang="de-DE")
                ml_text.text = tag_def["comment"]

        self._document = doc
        return doc

    # ── Network Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def scl_network(title: str, code: str) -> NetworkDef:
        """Create an SCL network definition."""
        return NetworkDef(title=title, language="SCL", code=code)

    @staticmethod
    def lad_network(title: str) -> NetworkDef:
        """Create an empty LAD network definition."""
        return NetworkDef(title=title, language="LAD", code="")

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, filepath: str):
        """Save the current block to an XML file."""
        if self._document is None:
            raise RuntimeError("No block created yet.")

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        tree = ET.ElementTree(self._document)
        ET.indent(tree, space="  ")

        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            tree.write(f, encoding="unicode", xml_declaration=False)

        print(f"Block saved to: {path}")

    def to_xml_string(self) -> str:
        """Return the current block as an XML string."""
        if self._document is None:
            raise RuntimeError("No block created yet.")
        ET.indent(self._document, space="  ")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            self._document, encoding="unicode"
        )

    # ── Internal XML Helpers ──────────────────────────────────────────────────

    def _create_document(self) -> ET.Element:
        """Create the root Document element."""
        doc = ET.Element("Document")
        engineering = self._add_element(doc, "Engineering", version="V14")
        return doc

    def _add_block(
        self,
        parent: ET.Element,
        block_type: str,
        number: int,
        name: str,
        language: str,
        comment: str = "",
        version: str = "0.1",
    ) -> ET.Element:
        """Add a SW.Blocks.* element."""
        type_map = {
            "OB": "SW.Blocks.OB",
            "FB": "SW.Blocks.FB",
            "FC": "SW.Blocks.FC",
            "GlobalDB": "SW.Blocks.GlobalDB",
            "DB": "SW.Blocks.GlobalDB",
        }
        block = self._add_element(parent, type_map.get(block_type, f"SW.Blocks.{block_type}"),
                                  ID=str(number))

        attr_list = self._add_element(block, "AttributeList")

        # Standard attributes
        self._add_text_element(attr_list, "Name", name)
        self._add_text_element(attr_list, "Number", str(number))

        if language != "DB":
            self._add_text_element(attr_list, "ProgrammingLanguage", language)

        if self.author:
            self._add_text_element(attr_list, "AutoNumber", "true")

        if comment:
            comment_elem = self._add_element(attr_list, "Comment")
            ml_text = self._add_element(comment_elem, "MultiLanguageText", Lang="de-DE")
            ml_text.text = comment

        return block

    def _add_networks(self, parent: ET.Element, networks: list, default_language: str):
        """Add CompileUnit (network) elements."""
        object_list = self._add_element(parent.find("..") or parent, "ObjectList")

        for idx, net in enumerate(networks):
            compile_unit = self._add_element(object_list, "SW.Blocks.CompileUnit",
                                            ID=str(idx + 1))
            cu_attrs = self._add_element(compile_unit, "AttributeList")

            # Network title
            if net.title:
                title_elem = self._add_element(cu_attrs, "NetworkTitle")
                ml_text = self._add_element(title_elem, "MultiLanguageText", Lang="de-DE")
                ml_text.text = net.title

            lang = net.language or default_language
            self._add_text_element(cu_attrs, "ProgrammingLanguage", lang)

            # Network source
            if lang == "SCL" and net.code:
                source = self._add_element(cu_attrs, "NetworkSource")
                # SCL code goes into structured text element
                st_elem = self._add_element(source, "StructuredText")
                st_elem.text = net.code
            elif lang in ("LAD", "FBD"):
                # Empty FlgNet for LAD/FBD
                source = self._add_element(cu_attrs, "NetworkSource")
                flg_net = self._add_element(source, "FlgNet")
                parts = self._add_element(flg_net, "Parts")
                wires = self._add_element(flg_net, "Wires")

    def _add_member(self, section: ET.Element, member: MemberDef):
        """Add a Member element to a section."""
        m = self._add_element(section, "Member", Name=member.name, Datatype=member.data_type)

        if member.data_type == ARRAY and member.array_type:
            m.set("Datatype", f"Array[{member.array_lower}..{member.array_upper}] of {member.array_type}")

        if member.initial_value:
            start_val = self._add_element(m, "StartValue")
            start_val.text = member.initial_value

        if member.comment:
            comment_elem = self._add_element(m, "Comment")
            ml_text = self._add_element(comment_elem, "MultiLanguageText", Lang="de-DE")
            ml_text.text = member.comment

    @staticmethod
    def _add_element(parent: ET.Element, tag: str, **attribs) -> ET.Element:
        """Add a child element with attributes."""
        elem = ET.SubElement(parent, tag)
        for key, val in attribs.items():
            elem.set(key, val)
        return elem

    @staticmethod
    def _add_text_element(parent: ET.Element, tag: str, text: str) -> ET.Element:
        """Add a child element with text content."""
        elem = ET.SubElement(parent, tag)
        elem.text = text
        return elem


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Demo: Generate example blocks
    gen = TiaBlockGenerator(author="TIA Tools Demo")
    output_dir = Path("./generated_blocks")

    # 1. OB1 - Main
    gen.create_ob1_main(networks=[
        gen.scl_network("Call Motor Control", '"FC_MotorControl"();'),
        gen.scl_network("Call Data Processing", '"FC_DataProcess"();'),
    ])
    gen.save(str(output_dir / "Main_OB1.xml"))

    # 2. OB100 - Startup
    gen.create_ob100_startup(networks=[
        gen.scl_network("Initialize Outputs", """
            "DB_Outputs".Motor1_Run := FALSE;
            "DB_Outputs".Motor2_Run := FALSE;
            "DB_Outputs".Valve1_Open := FALSE;
        """),
    ])
    gen.save(str(output_dir / "Startup_OB100.xml"))

    # 3. FB - Motor Control
    gen.create_fb(
        number=1,
        name="FB_MotorControl",
        members=[
            MemberDef("Enable", BOOL, "Input", comment="Motor enable signal"),
            MemberDef("Speed_SP", REAL, "Input", "0.0", "Speed setpoint 0-100%"),
            MemberDef("Running", BOOL, "Output", comment="Motor running feedback"),
            MemberDef("Speed_PV", REAL, "Output", "0.0", "Speed process value"),
            MemberDef("Error", BOOL, "Output", "false", "Error flag"),
            MemberDef("RunTimer", TIME, "Static", "T#0s", "Internal run timer"),
            MemberDef("StartupDelay", TIME, "Static", "T#5s", "Startup delay"),
        ],
        networks=[
            gen.scl_network("Motor Start/Stop", """
                IF #Enable AND NOT #Error THEN
                    #Running := TRUE;
                    #Speed_PV := #Speed_SP;
                ELSE
                    #Running := FALSE;
                    #Speed_PV := 0.0;
                END_IF;
            """),
        ],
        comment="Motor control function block",
    )
    gen.save(str(output_dir / "FB_MotorControl.xml"))

    # 4. FC - Data Processing
    gen.create_fc(
        number=1,
        name="FC_DataProcess",
        members=[
            MemberDef("RawValue", INT, "Input", comment="Raw input value"),
            MemberDef("ScaledValue", REAL, "Output", comment="Scaled output"),
            MemberDef("TempCalc", REAL, "Temp"),
        ],
        networks=[
            gen.scl_network("Scale Input", """
                #TempCalc := INT_TO_REAL(#RawValue);
                #ScaledValue := #TempCalc * 100.0 / 27648.0;
            """),
        ],
        return_type="Int",
        comment="Data processing function",
    )
    gen.save(str(output_dir / "FC_DataProcess.xml"))

    # 5. DB - Global Data
    gen.create_db(
        number=1,
        name="DB_Outputs",
        members=[
            MemberDef("Motor1_Run", BOOL, initial_value="false", comment="Motor 1 run command"),
            MemberDef("Motor2_Run", BOOL, initial_value="false", comment="Motor 2 run command"),
            MemberDef("Valve1_Open", BOOL, initial_value="false", comment="Valve 1 open command"),
            MemberDef("Speed_Setpoint", REAL, initial_value="0.0", comment="Speed setpoint %"),
            MemberDef("ProcessTemp", REAL, initial_value="0.0", comment="Process temperature"),
            MemberDef("AlarmWord", WORD, initial_value="16#0000", comment="Alarm status word"),
        ],
        comment="Global output data block",
    )
    gen.save(str(output_dir / "DB_Outputs.xml"))

    # 6. Tag Table
    gen.create_tag_table("IO_Tags", [
        {"name": "DI_Motor1_Feedback", "data_type": "Bool", "address": "%I0.0",
         "comment": "Motor 1 running feedback"},
        {"name": "DI_Motor2_Feedback", "data_type": "Bool", "address": "%I0.1",
         "comment": "Motor 2 running feedback"},
        {"name": "DI_Emergency_Stop", "data_type": "Bool", "address": "%I0.2",
         "comment": "Emergency stop button"},
        {"name": "AI_Temperature", "data_type": "Int", "address": "%IW64",
         "comment": "Temperature sensor analog input"},
        {"name": "DO_Motor1_Run", "data_type": "Bool", "address": "%Q0.0",
         "comment": "Motor 1 run command"},
        {"name": "DO_Motor2_Run", "data_type": "Bool", "address": "%Q0.1",
         "comment": "Motor 2 run command"},
        {"name": "DO_Valve1", "data_type": "Bool", "address": "%Q0.2",
         "comment": "Valve 1 control"},
        {"name": "AO_Speed_Ref", "data_type": "Int", "address": "%QW64",
         "comment": "Speed reference analog output"},
    ])
    gen.save(str(output_dir / "IO_Tags.xml"))

    print(f"\nAll example blocks generated in: {output_dir.resolve()}")
