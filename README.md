# TIA-Tools

Python toolkit for Siemens TIA Portal projects.

## Modules

| Module | Purpose | TIA Portal required? |
|---|---|---|
| `tia_project_reader.py` | Read TIA projects without TIA Portal (parses PLF binary) | **No** |
| `tia_project_creator.py` | Create TIA projects via Openness API | **Yes** |
| `tia_block_generator.py` | Generate TIA Openness XML for OB/FB/FC/DB/Tags | **No** |

## Quick Start

### Read an existing TIA project (no TIA Portal needed)

```python
from tia_tools import TiaProjectReader

reader = TiaProjectReader("D:/Projects/MyProject/MyProject")
info = reader.read()
print(info.summary())
```

Output:
```
============================================================
  TIA Project: MyProject
  TIA Portal Version: 14.0.0.0
============================================================
  Station: S71500/ET200MP-Station_1
  CPU: CPU 1515F-2 PN
    Order Number: 6ES7 515-2FM01-0AB0
    Firmware: V2.1
    Subtype: S71500.CPU
    Max Blocks: 6000
    Languages: LAD, STL, FBD, SCL, GRAPH
  ...
```

### Generate program blocks (no TIA Portal needed)

```python
from tia_tools import TiaBlockGenerator, MemberDef, BOOL, REAL, TIME

gen = TiaBlockGenerator(author="My Company")

# Create a Function Block
gen.create_fb(1, "FB_MotorControl", members=[
    MemberDef("Enable", BOOL, "Input", comment="Motor enable"),
    MemberDef("Speed_SP", REAL, "Input", "0.0", "Speed setpoint %"),
    MemberDef("Running", BOOL, "Output", comment="Running feedback"),
    MemberDef("Speed_PV", REAL, "Output", "0.0", "Actual speed"),
    MemberDef("RunTimer", TIME, "Static", "T#0s"),
], networks=[
    gen.scl_network("Motor Logic", """
        IF #Enable THEN
            #Running := TRUE;
            #Speed_PV := #Speed_SP;
        ELSE
            #Running := FALSE;
            #Speed_PV := 0.0;
        END_IF;
    """),
])
gen.save("FB_MotorControl.xml")

# Create a Data Block
gen.create_db(1, "DB_Outputs", members=[
    MemberDef("Motor1_Run", BOOL, initial_value="false"),
    MemberDef("Motor2_Run", BOOL, initial_value="false"),
    MemberDef("Speed_Setpoint", REAL, initial_value="0.0"),
])
gen.save("DB_Outputs.xml")

# Create a Tag Table
gen.create_tag_table("IO_Tags", [
    {"name": "DI_Motor_FB", "data_type": "Bool", "address": "%I0.0", "comment": "Motor feedback"},
    {"name": "DO_Motor_Run", "data_type": "Bool", "address": "%Q0.0", "comment": "Motor run cmd"},
    {"name": "AI_Temperature", "data_type": "Int", "address": "%IW64", "comment": "Temp sensor"},
])
gen.save("IO_Tags.xml")
```

### Create a TIA project (requires TIA Portal + Openness)

```python
from tia_tools.tia_project_creator import create_simple_project

create_simple_project(
    project_name="MyProject",
    project_dir="D:/Projects",
    cpu_order="6ES7 515-2FM01-0AB0",
    cpu_firmware="V2.1",
    block_xmls=["FB_MotorControl.xml", "DB_Outputs.xml"],
    with_gui=False,
)
```

## CLI Usage

```bash
# Read a project
python -m tia_tools.tia_project_reader "D:/Projects/MyProject/MyProject"

# Generate example blocks
python -m tia_tools.tia_block_generator

# Create a project
python -m tia_tools.tia_project_creator MyProject D:/Projects --cpu "6ES7 515-2FM01-0AB0"
```

## Requirements

- **Reader + Block Generator:** Python 3.8+ (no external dependencies)
- **Project Creator:** Python 3.8+ with `pythonnet`, TIA Portal V14+ Professional with Openness

## PLF File Format (Reverse Engineered)

The `PEData.plf` binary database uses:
- 64-byte header (size, version, GUID)
- Zlib-compressed blocks containing XML metadata schemas and 4KB data pages
- Append-only structure with `##CLOSE##` and `$$COMMIT$` markers
- RSA signatures for integrity
- Length-prefixed string encoding for device names and attributes

## Supported TIA Portal Versions

| Version | Reader | Creator |
|---|---|---|
| V14 | ✓ | ✓ |
| V15 / V15.1 | ✓ | ✓ |
| V16 | ✓ | ✓ |
| V17 | ✓ | ✓ |
| V18 | ✓ | ✓ |
| V19 | ✓ | ✓ |
| V20 | ✓ | ✓ |

## License

MIT
