"""
TIA SCL Source File Generator - Creates IEC 61131-3 SCL files for TIA Portal.

Generates .scl text files that can be imported into TIA Portal via:
  File > External Sources > Add from file

Supports:
  - Function Blocks (FUNCTION_BLOCK)
  - Functions (FUNCTION)
  - Organization Blocks (ORGANIZATION_BLOCK)
  - Data Blocks (DATA_BLOCK)
  - Instance Data Blocks (DATA_BLOCK ... INSTANCE_DB OF)
  - User Defined Types (TYPE)

No TIA Portal installation required.

Usage:
    from tia_tools import SclGenerator, MemberDef, BOOL, REAL, TIME

    scl = SclGenerator()

    scl.function_block("FB_Motor", members=[
        MemberDef("Enable", BOOL, "Input", comment="Motor enable"),
        MemberDef("Running", BOOL, "Output"),
        MemberDef("Timer", TIME, "Static", "T#0s"),
    ], code='''
        IF #Enable THEN
            #Running := TRUE;
        ELSE
            #Running := FALSE;
        END_IF;
    ''')

    scl.save("FB_Motor.scl")
"""

from pathlib import Path
from textwrap import dedent
from typing import Optional

from .tia_block_generator import MemberDef


# Section name -> SCL keyword mapping
_SECTION_KW = {
    "Input": "VAR_INPUT",
    "Output": "VAR_OUTPUT",
    "InOut": "VAR_IN_OUT",
    "Static": "VAR",
    "Temp": "VAR_TEMP",
    "Constant": "VAR CONSTANT",
}

# Section ordering for FB/FC
_FB_SECTION_ORDER = ["Input", "Output", "InOut", "Static", "Temp", "Constant"]
_FC_SECTION_ORDER = ["Input", "Output", "InOut", "Temp", "Constant"]
_OB_SECTION_ORDER = ["Temp"]


class SclGenerator:
    """Generates IEC 61131-3 SCL source files for TIA Portal import."""

    def __init__(self, version: str = "0.1", optimized: bool = True):
        """
        Args:
            version: Block version string (e.g. "0.1")
            optimized: S7_Optimized_Access attribute (True for S7-1500)
        """
        self.version = version
        self.optimized = optimized
        self._blocks: list[tuple[str, str]] = []  # [(name, scl_text), ...]

    # ── Block Creation ────────────────────────────────────────────────────────

    def function_block(
        self,
        name: str,
        members: list[MemberDef] = None,
        code: str = "",
        comment: str = "",
    ) -> str:
        """
        Generate a FUNCTION_BLOCK.

        Args:
            name: Block name (e.g. "FB_MotorControl")
            members: List of MemberDef with sections Input/Output/InOut/Static/Temp/Constant
            code: SCL implementation code
            comment: Block comment
        Returns:
            Generated SCL text
        """
        lines = [f'FUNCTION_BLOCK "{name}"']
        lines.append(self._attributes())
        lines.append(f"VERSION : {self.version}")
        if comment:
            lines.append(f"// {comment}")

        lines.extend(self._var_sections(members or [], _FB_SECTION_ORDER))
        lines.append("")
        lines.append("BEGIN")
        lines.append(self._format_code(code))
        lines.append("END_FUNCTION_BLOCK")
        lines.append("")

        text = "\n".join(lines)
        self._blocks.append((name, text))
        return text

    def function(
        self,
        name: str,
        members: list[MemberDef] = None,
        code: str = "",
        return_type: str = "Void",
        comment: str = "",
    ) -> str:
        """
        Generate a FUNCTION.

        Args:
            name: Block name (e.g. "FC_Scale")
            members: List of MemberDef with sections Input/Output/InOut/Temp
            code: SCL implementation code
            return_type: Return data type ("Void", "Int", "Real", etc.)
            comment: Block comment
        Returns:
            Generated SCL text
        """
        header = f'FUNCTION "{name}" : {return_type}'
        lines = [header]
        lines.append(self._attributes())
        lines.append(f"VERSION : {self.version}")
        if comment:
            lines.append(f"// {comment}")

        lines.extend(self._var_sections(members or [], _FC_SECTION_ORDER))
        lines.append("")
        lines.append("BEGIN")
        lines.append(self._format_code(code))
        lines.append("END_FUNCTION")
        lines.append("")

        text = "\n".join(lines)
        self._blocks.append((name, text))
        return text

    def organization_block(
        self,
        name: str,
        members: list[MemberDef] = None,
        code: str = "",
        comment: str = "",
    ) -> str:
        """
        Generate an ORGANIZATION_BLOCK.

        Args:
            name: Block name (e.g. "OB1", "Main [OB1]")
            members: Optional VAR_TEMP members
            code: SCL implementation code
            comment: Block comment
        Returns:
            Generated SCL text
        """
        lines = [f'ORGANIZATION_BLOCK "{name}"']
        lines.append(self._attributes())
        lines.append(f"VERSION : {self.version}")
        if comment:
            lines.append(f"// {comment}")

        lines.extend(self._var_sections(members or [], _OB_SECTION_ORDER))
        lines.append("")
        lines.append("BEGIN")
        lines.append(self._format_code(code))
        lines.append("END_ORGANIZATION_BLOCK")
        lines.append("")

        text = "\n".join(lines)
        self._blocks.append((name, text))
        return text

    def data_block(
        self,
        name: str,
        members: list[MemberDef] = None,
        comment: str = "",
    ) -> str:
        """
        Generate a DATA_BLOCK (Global DB).

        Args:
            name: Block name (e.g. "DB_Outputs")
            members: List of MemberDef (all treated as VAR)
            comment: Block comment
        Returns:
            Generated SCL text
        """
        lines = [f'DATA_BLOCK "{name}"']
        lines.append(self._attributes())
        lines.append(f"VERSION : {self.version}")
        if comment:
            lines.append(f"// {comment}")
        lines.append("")

        # DB always uses VAR section
        if members:
            lines.append("VAR")
            for m in members:
                lines.append(self._member_line(m))
            lines.append("END_VAR")
        lines.append("")
        lines.append("BEGIN")
        lines.append("END_DATA_BLOCK")
        lines.append("")

        text = "\n".join(lines)
        self._blocks.append((name, text))
        return text

    def instance_db(
        self,
        name: str,
        fb_name: str,
        overrides: dict[str, str] = None,
    ) -> str:
        """
        Generate an Instance DATA_BLOCK for an FB.

        Args:
            name: Instance DB name (e.g. "DB_Motor1")
            fb_name: Associated Function Block name (e.g. "FB_MotorControl")
            overrides: Optional dict of {variable: value} to override initial values
        Returns:
            Generated SCL text
        """
        lines = [f'DATA_BLOCK "{name}"']
        lines.append(self._attributes())
        lines.append(f"VERSION : {self.version}")
        lines.append(f'"{fb_name}"')
        lines.append("")
        lines.append("BEGIN")
        if overrides:
            for var, val in overrides.items():
                lines.append(f"   {var} := {val};")
        lines.append("END_DATA_BLOCK")
        lines.append("")

        text = "\n".join(lines)
        self._blocks.append((name, text))
        return text

    def udt(
        self,
        name: str,
        members: list[MemberDef] = None,
        comment: str = "",
    ) -> str:
        """
        Generate a TYPE (User Defined Type / UDT).

        Args:
            name: Type name (e.g. "UDT_MotorData")
            members: List of MemberDef (sections ignored, all in STRUCT)
            comment: Block comment
        Returns:
            Generated SCL text
        """
        lines = [f'TYPE "{name}"']
        lines.append(f"VERSION : {self.version}")
        if comment:
            lines.append(f"// {comment}")
        lines.append("")
        lines.append("STRUCT")
        for m in (members or []):
            lines.append(self._member_line(m))
        lines.append("END_STRUCT;")
        lines.append("")
        lines.append("END_TYPE")
        lines.append("")

        text = "\n".join(lines)
        self._blocks.append((name, text))
        return text

    def function_block_with_idb(
        self,
        fb_name: str,
        idb_name: str,
        members: list[MemberDef] = None,
        code: str = "",
        comment: str = "",
        overrides: dict[str, str] = None,
    ) -> str:
        """
        Generate a Function Block + its Instance DB in one step.

        Args:
            fb_name: Function Block name
            idb_name: Instance Data Block name
            members: FB interface members
            code: SCL implementation code
            comment: Block comment
            overrides: Optional instance value overrides
        Returns:
            Combined SCL text (FB + IDB)
        """
        fb_text = self.function_block(fb_name, members, code, comment)
        idb_text = self.instance_db(idb_name, fb_name, overrides)
        return fb_text + "\n" + idb_text

    # ── Output ────────────────────────────────────────────────────────────────

    def to_string(self) -> str:
        """Get all generated blocks as a single SCL string."""
        return "\n".join(text for _, text in self._blocks)

    def save(self, filepath: str):
        """
        Save all generated blocks to a single .scl file.

        Args:
            filepath: Output file path (e.g. "program.scl")
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_string(), encoding="utf-8")
        print(f"Saved {len(self._blocks)} block(s) to {path}")

    def save_separate(self, directory: str):
        """
        Save each block as a separate .scl file.

        Args:
            directory: Output directory path
        """
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        for name, text in self._blocks:
            safe_name = name.replace('"', "").replace(" ", "_")
            filepath = dir_path / f"{safe_name}.scl"
            filepath.write_text(text, encoding="utf-8")
        print(f"Saved {len(self._blocks)} block(s) to {dir_path}/")

    def clear(self):
        """Clear all generated blocks."""
        self._blocks.clear()

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _attributes(self) -> str:
        """Generate the S7 attribute pragma."""
        if self.optimized:
            return "{ S7_Optimized_Access := 'TRUE' }"
        return "{ S7_Optimized_Access := 'FALSE' }"

    def _var_sections(self, members: list[MemberDef], order: list[str]) -> list[str]:
        """Group members by section and format as VAR blocks."""
        lines = []
        for section in order:
            section_members = [m for m in members if m.section == section]
            if not section_members:
                continue
            kw = _SECTION_KW.get(section, "VAR")
            lines.append("")
            lines.append(kw)
            for m in section_members:
                lines.append(self._member_line(m))
            lines.append("END_VAR")
        return lines

    def _member_line(self, m: MemberDef) -> str:
        """Format a single member as an SCL variable declaration line."""
        # Data type string
        if m.data_type == "Array" and m.array_type:
            lower = m.array_lower if m.array_lower is not None else 0
            upper = m.array_upper if m.array_upper is not None else 0
            dtype = f"Array[{lower}..{upper}] of {m.array_type}"
        else:
            dtype = m.data_type

        # Build line
        line = f"    {m.name} : {dtype}"
        if m.initial_value:
            line += f" := {m.initial_value}"
        line += ";"

        # Comment
        if m.comment:
            line += f"   // {m.comment}"

        return line

    def _format_code(self, code: str) -> str:
        """Clean up and indent user-provided SCL code."""
        if not code or not code.strip():
            return "    ;"
        # Dedent and re-indent with 4 spaces
        cleaned = dedent(code).strip()
        indented = "\n".join(f"    {line}" if line.strip() else "" for line in cleaned.splitlines())
        return indented


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _generate_examples():
    """Generate example SCL files to demonstrate all block types."""
    from .tia_block_generator import MemberDef, BOOL, INT, DINT, REAL, LREAL, WORD, TIME, STRING

    output_dir = Path(__file__).parent.parent / "generated_scl"
    output_dir.mkdir(exist_ok=True)

    scl = SclGenerator()

    # 1. Function Block - Motor Control
    scl.function_block("FB_MotorControl", members=[
        MemberDef("Enable", BOOL, "Input", comment="Motor enable signal"),
        MemberDef("Speed_SP", REAL, "Input", "0.0", "Speed setpoint 0-100%"),
        MemberDef("Running", BOOL, "Output", comment="Motor running feedback"),
        MemberDef("Speed_PV", REAL, "Output", "0.0", "Speed process value"),
        MemberDef("Error", BOOL, "Output", "false", "Error flag"),
        MemberDef("RunTimer", TIME, "Static", "T#0s", "Internal run timer"),
        MemberDef("StartupDelay", TIME, "Static", "T#5s", "Startup delay"),
    ], code="""
        IF #Enable AND NOT #Error THEN
            #Running := TRUE;
            #Speed_PV := #Speed_SP;
        ELSE
            #Running := FALSE;
            #Speed_PV := 0.0;
        END_IF;
    """, comment="Motor control function block")

    # 2. Instance DB for Motor Control
    scl.instance_db("DB_Motor1", "FB_MotorControl", overrides={
        "Speed_SP": "50.0",
        "StartupDelay": "T#10s",
    })

    # 3. Function - Analog Scaling
    scl.function("FC_Scale", members=[
        MemberDef("RawValue", INT, "Input", comment="Raw analog input (0-27648)"),
        MemberDef("ScaleMin", REAL, "Input", "0.0", "Engineering unit minimum"),
        MemberDef("ScaleMax", REAL, "Input", "100.0", "Engineering unit maximum"),
        MemberDef("TempCalc", REAL, "Temp"),
    ], return_type="Real", code="""
        #TempCalc := INT_TO_REAL(#RawValue);
        #FC_Scale := #ScaleMin + (#TempCalc * (#ScaleMax - #ScaleMin) / 27648.0);
    """, comment="Linear analog scaling")

    # 4. Organization Block - Main
    scl.organization_block("Main [OB1]", code="""
        // Call motor control
        "DB_Motor1"(Enable := "DI_Motor_Enable",
                    Speed_SP := "FC_Scale"(RawValue := "AI_Speed_SP",
                                           ScaleMin := 0.0,
                                           ScaleMax := 100.0));

        // Write outputs
        "DO_Motor_Run" := "DB_Motor1".Running;
    """, comment="Main scan cycle")

    # 5. Data Block - Process Data
    scl.data_block("DB_ProcessData", members=[
        MemberDef("Motor1_Run", BOOL, initial_value="false", comment="Motor 1 run command"),
        MemberDef("Motor2_Run", BOOL, initial_value="false", comment="Motor 2 run command"),
        MemberDef("Valve1_Open", BOOL, initial_value="false", comment="Valve 1 open command"),
        MemberDef("Speed_Setpoint", REAL, initial_value="0.0", comment="Speed SP in %"),
        MemberDef("ProcessTemp", REAL, initial_value="0.0", comment="Process temperature"),
        MemberDef("AlarmWord", WORD, initial_value="16#0000", comment="Alarm status word"),
    ], comment="Process data storage")

    # 6. UDT - Motor Status
    scl.udt("UDT_MotorStatus", members=[
        MemberDef("Enable", BOOL, comment="Enable command"),
        MemberDef("Running", BOOL, comment="Running feedback"),
        MemberDef("Error", BOOL, comment="Error active"),
        MemberDef("ErrorCode", INT, initial_value="0", comment="Error code"),
        MemberDef("Speed", REAL, initial_value="0.0", comment="Current speed %"),
        MemberDef("RunHours", DINT, initial_value="0", comment="Operating hours"),
    ], comment="Motor status data type")

    # 7. FB with UDT usage + Instance DB
    scl.function_block_with_idb(
        fb_name="FB_PlantControl",
        idb_name="DB_PlantControl",
        members=[
            MemberDef("Start", BOOL, "Input", comment="Plant start"),
            MemberDef("Stop", BOOL, "Input", comment="Plant stop"),
            MemberDef("Motor1", '"UDT_MotorStatus"', "Static", comment="Motor 1 status"),
            MemberDef("Motor2", '"UDT_MotorStatus"', "Static", comment="Motor 2 status"),
            MemberDef("PlantRunning", BOOL, "Output", comment="Plant is running"),
            MemberDef("ErrorActive", BOOL, "Output", "false", "Any error active"),
        ],
        code="""
            IF #Start AND NOT #Stop THEN
                #PlantRunning := TRUE;
                #Motor1.Enable := TRUE;
                #Motor2.Enable := TRUE;
            ELSIF #Stop THEN
                #PlantRunning := FALSE;
                #Motor1.Enable := FALSE;
                #Motor2.Enable := FALSE;
            END_IF;

            #ErrorActive := #Motor1.Error OR #Motor2.Error;
        """,
        comment="Plant control with two motors",
    )

    # Save all blocks in one file
    scl.save(str(output_dir / "example_program.scl"))

    # Also save separately
    scl.save_separate(str(output_dir / "separate"))

    print(f"\nGenerated {len(scl._blocks)} blocks:")
    for name, _ in scl._blocks:
        print(f"  - {name}")


if __name__ == "__main__":
    _generate_examples()
