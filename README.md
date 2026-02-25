# TIA-Tools

Python toolkit for Siemens TIA Portal projects.

<a href="https://www.buymeacoffee.com/kasi09" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

## Modules

| Module | Purpose | TIA Portal required? |
|---|---|---|
| `tia_project_reader.py` | Read TIA projects without TIA Portal (parses PLF binary) | **No** |
| `tia_project_creator.py` | Create TIA projects via Openness API | **Yes** |
| `tia_block_generator.py` | Generate TIA Openness XML for OB/FB/FC/DB/Tags | **No** |
| `tia_tag_export.py` | CSV/Excel tag import/export from PLF projects | **No** |
| `tia_scl_generator.py` | Generate SCL source files (.scl) for direct TIA import | **No** |
| `tia_block_library.py` | Standard block templates (Motor, Valve, PID, Alarm, Scale) | **No** |
| `tia_cross_reference.py` | Cross-reference analysis for SCL source files | **No** |
| `tia_doc_generator.py` | HTML documentation generator for SCL projects | **No** |

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

### Export/Import tags and variables (no TIA Portal needed)

```python
from tia_tools import TiaTagExporter, TiaTagImporter

# Export all tags from a TIA project to CSV
exporter = TiaTagExporter("D:/Projects/MyProject/MyProject")
exporter.export_csv("variables.csv")        # semicolon-delimited for German Excel
exporter.export_excel("variables.xlsx")     # colored Excel with overview sheet (requires openpyxl)

# Import tags from CSV and generate TIA XML
importer = TiaTagImporter()
importer.import_csv("my_tags.csv")
importer.generate_tag_table_xml("IO_Tags.xml")              # PLC tag table
importer.generate_db_xml("DB_Process.xml", db_number=10)     # Global data block
importer.generate_fb_xml("FB_Control.xml", fb_number=5)      # Function block with sections
```

### Generate SCL source files (no TIA Portal needed)

```python
from tia_tools import SclGenerator, MemberDef, BOOL, REAL, INT, TIME

scl = SclGenerator()

# Function Block with instance DB
scl.function_block_with_idb("FB_Motor", "DB_Motor1", members=[
    MemberDef("Enable", BOOL, "Input", comment="Motor enable"),
    MemberDef("Speed_SP", REAL, "Input", "0.0", "Speed setpoint %"),
    MemberDef("Running", BOOL, "Output", comment="Running feedback"),
    MemberDef("Timer", TIME, "Static", "T#0s"),
], code="""
    IF #Enable THEN
        #Running := TRUE;
    ELSE
        #Running := FALSE;
    END_IF;
""")

# Function with return value
scl.function("FC_Scale", members=[
    MemberDef("RawValue", INT, "Input"),
    MemberDef("ScaleMax", REAL, "Input", "100.0"),
], return_type="Real", code="""
    #FC_Scale := INT_TO_REAL(#RawValue) * #ScaleMax / 27648.0;
""")

# Data Block + UDT
scl.data_block("DB_Data", members=[
    MemberDef("Speed", REAL, initial_value="0.0"),
    MemberDef("Alarm", BOOL, initial_value="false"),
])

scl.save("program.scl")          # All blocks in one file
scl.save_separate("scl_output/") # Each block as separate .scl file
```

Import in TIA Portal: *External Sources > Add from file > Generate blocks*

### Standard block library

```python
from tia_tools import BlockLibrary

lib = BlockLibrary()

# List available templates
for t in lib.list_templates():
    print(f"{t['name']:20s} [{t['block_type']}] {t['description']}")
# FB_Motor, FB_Valve, FB_PID, FB_Alarm, FC_AnalogScale

# Generate SCL from template (with custom parameters)
scl = lib.generate_scl("FB_Motor", name="FB_Pump1",
                        startup_time="T#5s", feedback_time="T#10s")

# Generate TIA XML from template
xml = lib.generate_xml("FB_Motor", name="FB_Pump1", number=10)

# Generate all templates at once
all_scl = lib.generate_all_scl(prefix="Plant1_")
```

Available templates:

| Template | Type | Description |
|---|---|---|
| `FB_Motor` | FB | Start/Stop/Reset, feedback monitoring, state machine, error codes |
| `FB_Valve` | FB | Open/Close, feedback, travel time monitoring, timeout error |
| `FB_PID` | FB | SP/PV/Kp/Ti/Td, Euler discretization, output clamping, manual/auto |
| `FB_Alarm` | FB | Condition/Acknowledge, auto-reset, active/unacknowledged status |
| `FC_AnalogScale` | FC | Raw (0-27648) to engineering units, clamping |

### Cross-reference analysis

```python
from tia_tools import CrossReference

xref = CrossReference()
xref.scan_directory("./scl_sources")

# Find all usages of a variable or block
for ref in xref.find_usages("Motor1_Run"):
    print(f"  {ref.file}:{ref.line} [{ref.kind}] {ref.context}")

# Find unused variables
unused = xref.find_unused()

# Block dependency analysis
deps = xref.find_dependencies("Main [OB1]")  # calls, addresses, types
dependents = xref.find_dependents("FB_MotorControl")  # who calls this block

# Export
xref.export_csv("cross_reference.csv")
xref.export_json("cross_reference.json")
```

### HTML documentation generator

```python
from tia_tools import DocGenerator

doc = DocGenerator()
doc.scan_directory("./scl_sources")
doc.generate("./docs")
# Creates index.html, {BlockName}.html, dependencies.html
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

# Export tags to CSV/Excel
python tia_tools/tia_tag_export.py export "D:/Projects/MyProject" tags.csv
python tia_tools/tia_tag_export.py export "D:/Projects/MyProject" tags.xlsx

# Import tags from CSV to TIA XML
python tia_tools/tia_tag_export.py import tags.csv IO_Tags.xml tag_table
python tia_tools/tia_tag_export.py import vars.csv DB_Process.xml db

# Generate SCL source files
python -m tia_tools.tia_scl_generator

# Block library - generate all templates
python -m tia_tools.tia_block_library

# Cross-reference analysis
python -m tia_tools.tia_cross_reference ./scl_sources

# Generate HTML documentation
python -m tia_tools.tia_doc_generator ./scl_sources ./docs

# Create a project
python -m tia_tools.tia_project_creator MyProject D:/Projects --cpu "6ES7 515-2FM01-0AB0"
```

## Requirements

- **Reader + Block Generator + Tag Export (CSV) + SCL Generator + Block Library + Cross-Reference + Doc Generator:** Python 3.8+ (no external dependencies)
- **Tag Export (Excel):** Python 3.8+ with `openpyxl`
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
