"""
TIA Portal Project Creator - Creates TIA Portal projects via the Openness API.

Requires:
  - TIA Portal V14+ (Professional) installed with "Openness" option
  - User must be member of "Siemens TIA Openness" Windows group
  - pip install pythonnet

Supports:
  - Creating new projects
  - Adding hardware (S7-1500, S7-1200, ET200 stations)
  - Importing program blocks (OB, FB, FC, DB) from XML
  - Importing SCL source files
  - Compiling and saving

Usage:
    creator = TiaProjectCreator(tia_version="14.0")
    creator.start_tia(with_gui=False)
    creator.create_project("MyProject", r"D:\\Projects")
    creator.add_plc("PLC_1", order_number="6ES7 515-2FM01-0AB0", firmware="V2.1")
    creator.import_block("D:\\blocks\\Main_OB1.xml")
    creator.compile()
    creator.save_and_close()
"""

import sys
import os
from pathlib import Path
from typing import Optional

# TIA version to Openness DLL mapping
TIA_VERSION_MAP = {
    "14.0": ("V14", r"C:\Program Files\Siemens\Automation\Portal V14\PublicAPI\V14"),
    "15.0": ("V15", r"C:\Program Files\Siemens\Automation\Portal V15\PublicAPI\V15"),
    "15.1": ("V15.1", r"C:\Program Files\Siemens\Automation\Portal V15.1\PublicAPI\V15.1"),
    "16.0": ("V16", r"C:\Program Files\Siemens\Automation\Portal V16\PublicAPI\V16"),
    "17.0": ("V17", r"C:\Program Files\Siemens\Automation\Portal V17\PublicAPI\V17"),
    "18.0": ("V18", r"C:\Program Files\Siemens\Automation\Portal V18\PublicAPI\V18"),
    "19.0": ("V19", r"C:\Program Files\Siemens\Automation\Portal V19\PublicAPI\V19"),
    "20.0": ("V20", r"C:\Program Files\Siemens\Automation\Portal V20\PublicAPI\V20"),
}

# Common CPU order numbers
CPU_CATALOG = {
    # S7-1500
    "CPU 1511-1 PN":     "6ES7 511-1AK02-0AB0",
    "CPU 1513-1 PN":     "6ES7 513-1AL02-0AB0",
    "CPU 1515-2 PN":     "6ES7 515-2AM02-0AB0",
    "CPU 1515F-2 PN":    "6ES7 515-2FM01-0AB0",
    "CPU 1516-3 PN/DP":  "6ES7 516-3AN02-0AB0",
    "CPU 1517-3 PN/DP":  "6ES7 517-3AP00-0AB0",
    "CPU 1518-4 PN/DP":  "6ES7 518-4AP00-0AB0",
    # S7-1200
    "CPU 1211C DC/DC/DC": "6ES7 211-1AE40-0XB0",
    "CPU 1212C DC/DC/DC": "6ES7 212-1AE40-0XB0",
    "CPU 1214C DC/DC/DC": "6ES7 214-1AG40-0XB0",
    "CPU 1215C DC/DC/DC": "6ES7 215-1AG40-0XB0",
}


def _detect_tia_version() -> Optional[str]:
    """Auto-detect installed TIA Portal version."""
    for ver, (_, path) in sorted(TIA_VERSION_MAP.items(), reverse=True):
        if os.path.exists(path):
            return ver
    return None


class TiaProjectCreator:
    """Creates and configures TIA Portal projects via the Openness API."""

    def __init__(self, tia_version: str = None):
        """
        Initialize the creator.

        Args:
            tia_version: TIA Portal version like "14.0", "17.0", etc.
                         Auto-detects if not specified.
        """
        self.tia_version = tia_version or _detect_tia_version()
        if not self.tia_version:
            raise RuntimeError(
                "No TIA Portal installation found. "
                "Install TIA Portal with the Openness option, or specify the version manually."
            )

        self._tia = None       # TIA Portal instance
        self._project = None   # Current project
        self._plc_device = None
        self._plc_software = None
        self._loaded = False

    def _load_openness(self):
        """Load the Siemens.Engineering DLL via pythonnet."""
        if self._loaded:
            return

        try:
            import clr
        except ImportError:
            raise ImportError(
                "pythonnet is required: pip install pythonnet\n"
                "For Python 3.11+: pip install pythonnet>=3.0"
            )

        ver_tag, api_path = TIA_VERSION_MAP[self.tia_version]

        # Add the Openness DLL directory
        dll_path = os.path.join(api_path, "Siemens.Engineering.dll")
        if not os.path.exists(dll_path):
            raise FileNotFoundError(
                f"Siemens.Engineering.dll not found at: {dll_path}\n"
                f"Make sure TIA Portal {ver_tag} is installed with Openness."
            )

        clr.AddReference(dll_path)

        # Optional: HMI support
        hmi_dll = os.path.join(api_path, "Siemens.Engineering.Hmi.dll")
        if os.path.exists(hmi_dll):
            clr.AddReference(hmi_dll)

        self._loaded = True

    def start_tia(self, with_gui: bool = False):
        """
        Start a TIA Portal instance.

        Args:
            with_gui: If True, start with the GUI visible (slower but allows interaction).
        """
        self._load_openness()
        from Siemens.Engineering import TiaPortal, TiaPortalMode

        mode = TiaPortalMode.WithUserInterface if with_gui else TiaPortalMode.WithoutUserInterface
        print(f"Starting TIA Portal {self.tia_version} ({'GUI' if with_gui else 'headless'})...")
        self._tia = TiaPortal(mode)
        print("TIA Portal started.")

    def attach_to_running(self):
        """Attach to an already running TIA Portal instance."""
        self._load_openness()
        from Siemens.Engineering import TiaPortal

        processes = TiaPortal.GetProcesses()
        if not processes or processes.Count == 0:
            raise RuntimeError("No running TIA Portal instance found.")
        self._tia = processes[0].Attach()
        if self._tia.Projects.Count > 0:
            self._project = self._tia.Projects[0]
        print(f"Attached to TIA Portal (PID: {processes[0].Id})")

    def create_project(self, name: str, directory: str):
        """
        Create a new empty TIA Portal project.

        Args:
            name: Project name (will be used as folder name)
            directory: Parent directory where the project folder will be created
        """
        if not self._tia:
            raise RuntimeError("TIA Portal not started. Call start_tia() first.")

        from Siemens.Engineering import ProjectComposition
        from System.IO import DirectoryInfo

        target_dir = DirectoryInfo(directory)
        print(f"Creating project '{name}' in {directory}...")
        self._project = self._tia.Projects.Create(target_dir, name)
        print(f"Project created: {self._project.Path}")

    def open_project(self, project_path: str):
        """
        Open an existing TIA Portal project.

        Args:
            project_path: Full path to the .ap14/.ap15/etc file
        """
        if not self._tia:
            raise RuntimeError("TIA Portal not started. Call start_tia() first.")

        from System.IO import FileInfo

        file_info = FileInfo(project_path)
        print(f"Opening project: {project_path}...")
        self._project = self._tia.Projects.Open(file_info)
        print("Project opened.")

    def add_plc(
        self,
        name: str = "PLC_1",
        order_number: str = "6ES7 515-2FM01-0AB0",
        firmware: str = "V2.1",
        station_name: str = None,
    ):
        """
        Add a PLC to the project.

        Args:
            name: PLC device name
            order_number: Siemens order number (MLFB)
            firmware: Firmware version string
            station_name: Optional station name (defaults to "{name}_Station")
        """
        if not self._project:
            raise RuntimeError("No project open. Call create_project() or open_project() first.")

        # Build the hardware identifier string
        # Format: "OrderNumber:6ES7 515-2FM01-0AB0/V2.1"
        hw_id = f"OrderNumber:{order_number}/{firmware}"

        print(f"Adding PLC: {name} ({order_number}, FW {firmware})...")

        # For TIA V14+, use the DeviceComposition
        device = self._project.Devices.CreateWithItem(hw_id, name, station_name or f"{name}")
        self._plc_device = device

        # Get PLC software container
        for device_item in device.DeviceItems:
            software_container = self._get_software_container(device_item)
            if software_container:
                self._plc_software = software_container
                print(f"PLC software container found for {name}")
                break

        print(f"PLC '{name}' added successfully.")

    def _get_software_container(self, device_item):
        """Recursively find the PlcSoftware container in device items."""
        from Siemens.Engineering import IEngineeringServiceProvider
        from Siemens.Engineering.SW import PlcSoftware

        try:
            software = device_item.GetService[PlcSoftware]()
            if software:
                return software
        except Exception:
            pass

        # Recurse into sub-items
        if hasattr(device_item, "DeviceItems"):
            for sub_item in device_item.DeviceItems:
                result = self._get_software_container(sub_item)
                if result:
                    return result
        return None

    def import_block(self, xml_path: str, block_group: str = None):
        """
        Import a program block from a TIA Openness XML file.

        Args:
            xml_path: Path to the XML file
            block_group: Optional subfolder name under "Program blocks"
        """
        if not self._plc_software:
            raise RuntimeError("No PLC added. Call add_plc() first.")

        from System.IO import FileInfo
        from Siemens.Engineering.SW.Blocks import PlcBlockComposition

        file_info = FileInfo(xml_path)
        block_group_obj = self._plc_software.BlockGroup

        if block_group:
            # Create or find subfolder
            try:
                block_group_obj = block_group_obj.Groups.Find(block_group)
                if not block_group_obj:
                    block_group_obj = self._plc_software.BlockGroup.Groups.Create(block_group)
            except Exception:
                block_group_obj = self._plc_software.BlockGroup.Groups.Create(block_group)

        print(f"Importing block from {xml_path}...")
        block_group_obj.Blocks.Import(file_info, ImportOptions.Override)
        print("Block imported.")

    def import_scl_source(self, scl_path: str):
        """
        Import an SCL source file into the PLC software.

        Args:
            scl_path: Path to the .scl file
        """
        if not self._plc_software:
            raise RuntimeError("No PLC added. Call add_plc() first.")

        from System.IO import FileInfo

        file_info = FileInfo(scl_path)
        external_sources = self._plc_software.ExternalSourceGroup.ExternalSources

        print(f"Importing SCL source: {scl_path}...")
        source = external_sources.CreateFromFile(Path(scl_path).name, file_info)

        # Generate blocks from source
        source.GenerateBlocksFromSource()
        print("SCL source imported and blocks generated.")

    def add_tag_table(self, name: str, tags: list):
        """
        Add a PLC tag table with tags.

        Args:
            name: Tag table name
            tags: List of dicts with keys: name, data_type, address, comment
                  e.g. [{"name": "Motor1", "data_type": "Bool", "address": "%Q0.0", "comment": "Motor 1 output"}]
        """
        if not self._plc_software:
            raise RuntimeError("No PLC added. Call add_plc() first.")

        tag_table_group = self._plc_software.TagTableGroup
        tag_table = tag_table_group.TagTables.Create(name)
        print(f"Creating tag table '{name}' with {len(tags)} tags...")

        for tag_def in tags:
            tag = tag_table.Tags.Create(
                tag_def["name"],
                tag_def["data_type"],
                tag_def.get("address", ""),
            )
            if tag_def.get("comment"):
                tag.Comment.Items[0].Text = tag_def["comment"]

        print(f"Tag table '{name}' created.")

    def compile(self, plc_name: str = None):
        """Compile the PLC software."""
        if not self._plc_software:
            raise RuntimeError("No PLC software available.")

        print("Compiling PLC software...")
        compiler = self._plc_software.GetService[
            type(self._plc_software).GetType().Assembly.GetType(
                "Siemens.Engineering.Compiler.ICompilable"
            )
        ]
        result = self._plc_software.GetService[
            self._plc_software.GetType().Assembly.GetType(
                "Siemens.Engineering.Compiler.ICompilable"
            )
        ].Compile()
        print(f"Compilation result: {'Success' if result.State == 0 else 'Failed'}")
        return result

    def save(self):
        """Save the current project."""
        if self._project:
            print("Saving project...")
            self._project.Save()
            print("Project saved.")

    def save_and_close(self):
        """Save and close the project and TIA Portal."""
        if self._project:
            self.save()
            self._project.Close()
            self._project = None
        if self._tia:
            self._tia.Dispose()
            self._tia = None
            print("TIA Portal closed.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save_and_close()


# ─── Convenience Functions ────────────────────────────────────────────────────

def create_simple_project(
    project_name: str,
    project_dir: str,
    cpu_order: str = "6ES7 515-2FM01-0AB0",
    cpu_firmware: str = "V2.1",
    tia_version: str = None,
    block_xmls: list = None,
    scl_files: list = None,
    tags: dict = None,
    with_gui: bool = False,
):
    """
    High-level function to create a complete TIA project in one call.

    Args:
        project_name: Name of the project
        project_dir: Directory to create the project in
        cpu_order: CPU order number
        cpu_firmware: CPU firmware version
        tia_version: TIA Portal version (auto-detect if None)
        block_xmls: List of XML file paths to import as blocks
        scl_files: List of SCL source file paths to import
        tags: Dict of {table_name: [tag_defs]} for PLC tag tables
        with_gui: Whether to show TIA Portal GUI

    Returns:
        Path to the created project file
    """
    with TiaProjectCreator(tia_version=tia_version) as creator:
        creator.start_tia(with_gui=with_gui)
        creator.create_project(project_name, project_dir)
        creator.add_plc("PLC_1", order_number=cpu_order, firmware=cpu_firmware)

        if block_xmls:
            for xml_path in block_xmls:
                creator.import_block(xml_path)

        if scl_files:
            for scl_path in scl_files:
                creator.import_scl_source(scl_path)

        if tags:
            for table_name, tag_list in tags.items():
                creator.add_tag_table(table_name, tag_list)

        creator.compile()
        return str(Path(project_dir) / project_name)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create TIA Portal projects from Python")
    parser.add_argument("name", help="Project name")
    parser.add_argument("directory", help="Target directory")
    parser.add_argument("--cpu", default="6ES7 515-2FM01-0AB0", help="CPU order number")
    parser.add_argument("--fw", default="V2.1", help="CPU firmware version")
    parser.add_argument("--tia-version", help="TIA Portal version (e.g., 14.0, 17.0)")
    parser.add_argument("--gui", action="store_true", help="Show TIA Portal GUI")
    parser.add_argument("--import-xml", nargs="+", help="XML block files to import")
    parser.add_argument("--import-scl", nargs="+", help="SCL source files to import")

    args = parser.parse_args()

    result = create_simple_project(
        project_name=args.name,
        project_dir=args.directory,
        cpu_order=args.cpu,
        cpu_firmware=args.fw,
        tia_version=args.tia_version,
        block_xmls=args.import_xml,
        scl_files=args.import_scl,
        with_gui=args.gui,
    )
    print(f"\nProject created at: {result}")
