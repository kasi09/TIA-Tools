"""
TIA Block Library - Standard block templates for industrial automation.

Provides ready-to-use SCL/XML templates for common automation patterns:
  - FB_Motor:       Motor control with state machine, feedback monitoring
  - FB_Valve:       Valve control with open/close feedback, timeout
  - FB_PID:         PID controller with manual/auto mode
  - FB_Alarm:       Alarm handling with acknowledge, auto-reset
  - FC_AnalogScale: Analog value scaling with clamping

Usage:
    from tia_tools import BlockLibrary

    lib = BlockLibrary()
    templates = lib.list_templates()

    scl = lib.generate_scl("FB_Motor", name="FB_Pump1", startup_time="T#5s")
    xml = lib.generate_xml("FB_Motor", name="FB_Pump1", number=10)
"""

from typing import Optional
from .tia_block_generator import TiaBlockGenerator, MemberDef, NetworkDef
from .tia_block_generator import BOOL, INT, DINT, REAL, WORD, TIME
from .tia_scl_generator import SclGenerator


# ─── Template Definitions ────────────────────────────────────────────────────

_TEMPLATES = {
    "FB_Motor": {
        "description": "Motor control with Start/Stop/Reset, feedback monitoring, state machine (Idle/Starting/Running/Stopping/Faulted), error codes",
        "block_type": "FB",
        "defaults": {
            "startup_time": "T#3s",
            "feedback_time": "T#5s",
        },
    },
    "FB_Valve": {
        "description": "Valve control with Open/Close commands, open/closed feedback, travel time monitoring, timeout error",
        "block_type": "FB",
        "defaults": {
            "travel_time": "T#10s",
        },
    },
    "FB_PID": {
        "description": "PID controller with SP/PV/Kp/Ti/Td, Euler discretization, output clamping 0-100%, manual/auto mode",
        "block_type": "FB",
        "defaults": {
            "cycle_time": "T#100ms",
            "kp": "1.0",
            "ti": "T#10s",
            "td": "T#0s",
            "out_min": "0.0",
            "out_max": "100.0",
        },
    },
    "FB_Alarm": {
        "description": "Alarm handling with condition input, acknowledge, auto-reset option, active/unacknowledged status",
        "block_type": "FB",
        "defaults": {
            "auto_reset": "FALSE",
        },
    },
    "FC_AnalogScale": {
        "description": "Analog scaling: raw input (0-27648) to engineering units with clamping",
        "block_type": "FC",
        "defaults": {
            "raw_min": "0",
            "raw_max": "27648",
            "eng_min": "0.0",
            "eng_max": "100.0",
        },
    },
}


# ─── SCL Code Templates ─────────────────────────────────────────────────────

def _motor_members(params: dict) -> list[MemberDef]:
    return [
        # Inputs
        MemberDef("Start", BOOL, "Input", comment="Start command (pulse)"),
        MemberDef("Stop", BOOL, "Input", comment="Stop command (pulse)"),
        MemberDef("Reset", BOOL, "Input", comment="Reset fault"),
        MemberDef("Feedback", BOOL, "Input", comment="Motor running feedback from field"),
        MemberDef("StartupTime", TIME, "Input", params.get("startup_time", "T#3s"), "Startup delay time"),
        MemberDef("FeedbackTime", TIME, "Input", params.get("feedback_time", "T#5s"), "Feedback monitoring timeout"),
        # Outputs
        MemberDef("RunCommand", BOOL, "Output", "FALSE", "Output to motor contactor"),
        MemberDef("Running", BOOL, "Output", "FALSE", "Motor is running (confirmed)"),
        MemberDef("Error", BOOL, "Output", "FALSE", "Error active"),
        MemberDef("ErrorCode", INT, "Output", "0", "0=OK, 1=FeedbackTimeout, 2=FeedbackLost"),
        MemberDef("State", INT, "Output", "0", "State: 0=Idle, 10=Starting, 20=Running, 30=Stopping, 99=Faulted"),
        # Static
        MemberDef("StartupTimer", "TON", "Static", comment="Startup delay timer"),
        MemberDef("FeedbackTimer", "TON", "Static", comment="Feedback monitoring timer"),
        MemberDef("EdgeStart", "R_TRIG", "Static", comment="Start edge detection"),
        MemberDef("EdgeReset", "R_TRIG", "Static", comment="Reset edge detection"),
    ]


def _motor_code(params: dict) -> str:
    return """\
// Edge detection
#EdgeStart(CLK := #Start);
#EdgeReset(CLK := #Reset);

// Fault reset
IF #EdgeReset.Q AND #State = 99 THEN
    #State := 0;
    #Error := FALSE;
    #ErrorCode := 0;
END_IF;

// State machine
CASE #State OF
    0: // IDLE
        #RunCommand := FALSE;
        #Running := FALSE;
        IF #EdgeStart.Q AND NOT #Error THEN
            #State := 10;
        END_IF;

    10: // STARTING
        #RunCommand := TRUE;
        #StartupTimer(IN := TRUE, PT := #StartupTime);
        IF #StartupTimer.Q THEN
            #StartupTimer(IN := FALSE);
            // Check feedback
            IF #Feedback THEN
                #State := 20;
            ELSE
                #ErrorCode := 1; // Feedback timeout
                #Error := TRUE;
                #State := 99;
            END_IF;
        END_IF;
        IF #Stop THEN
            #State := 30;
            #StartupTimer(IN := FALSE);
        END_IF;

    20: // RUNNING
        #RunCommand := TRUE;
        #Running := TRUE;
        // Monitor feedback loss
        #FeedbackTimer(IN := NOT #Feedback, PT := #FeedbackTime);
        IF #FeedbackTimer.Q THEN
            #FeedbackTimer(IN := FALSE);
            #ErrorCode := 2; // Feedback lost
            #Error := TRUE;
            #State := 99;
        END_IF;
        IF #Stop THEN
            #State := 30;
        END_IF;

    30: // STOPPING
        #RunCommand := FALSE;
        #Running := FALSE;
        #FeedbackTimer(IN := FALSE);
        #State := 0;

    99: // FAULTED
        #RunCommand := FALSE;
        #Running := FALSE;

    ELSE
        #State := 0;
END_CASE;"""


def _valve_members(params: dict) -> list[MemberDef]:
    return [
        # Inputs
        MemberDef("Open", BOOL, "Input", comment="Open command"),
        MemberDef("Close", BOOL, "Input", comment="Close command"),
        MemberDef("FbkOpen", BOOL, "Input", comment="Valve open feedback"),
        MemberDef("FbkClosed", BOOL, "Input", comment="Valve closed feedback"),
        MemberDef("TravelTime", TIME, "Input", params.get("travel_time", "T#10s"), "Maximum travel time"),
        # Outputs
        MemberDef("CmdOpen", BOOL, "Output", "FALSE", "Open solenoid output"),
        MemberDef("CmdClose", BOOL, "Output", "FALSE", "Close solenoid output"),
        MemberDef("IsOpen", BOOL, "Output", "FALSE", "Valve is fully open"),
        MemberDef("IsClosed", BOOL, "Output", "FALSE", "Valve is fully closed"),
        MemberDef("Error", BOOL, "Output", "FALSE", "Travel timeout error"),
        MemberDef("State", INT, "Output", "0", "0=Closed, 10=Opening, 20=Open, 30=Closing, 99=Fault"),
        # Static
        MemberDef("TravelTimer", "TON", "Static", comment="Travel time monitoring"),
    ]


def _valve_code(params: dict) -> str:
    return """\
// Update feedback status
#IsOpen := #FbkOpen AND NOT #FbkClosed;
#IsClosed := #FbkClosed AND NOT #FbkOpen;

// State machine
CASE #State OF
    0: // CLOSED
        #CmdOpen := FALSE;
        #CmdClose := FALSE;
        #TravelTimer(IN := FALSE);
        IF #Open AND NOT #Close THEN
            #State := 10;
        END_IF;

    10: // OPENING
        #CmdOpen := TRUE;
        #CmdClose := FALSE;
        #TravelTimer(IN := NOT #FbkOpen, PT := #TravelTime);
        IF #FbkOpen THEN
            #State := 20;
            #TravelTimer(IN := FALSE);
        ELSIF #TravelTimer.Q THEN
            #Error := TRUE;
            #State := 99;
            #TravelTimer(IN := FALSE);
        END_IF;
        IF #Close THEN
            #State := 30;
            #TravelTimer(IN := FALSE);
        END_IF;

    20: // OPEN
        #CmdOpen := TRUE;
        #CmdClose := FALSE;
        #TravelTimer(IN := FALSE);
        IF #Close AND NOT #Open THEN
            #State := 30;
        END_IF;

    30: // CLOSING
        #CmdOpen := FALSE;
        #CmdClose := TRUE;
        #TravelTimer(IN := NOT #FbkClosed, PT := #TravelTime);
        IF #FbkClosed THEN
            #State := 0;
            #TravelTimer(IN := FALSE);
        ELSIF #TravelTimer.Q THEN
            #Error := TRUE;
            #State := 99;
            #TravelTimer(IN := FALSE);
        END_IF;
        IF #Open THEN
            #State := 10;
            #TravelTimer(IN := FALSE);
        END_IF;

    99: // FAULT
        #CmdOpen := FALSE;
        #CmdClose := FALSE;
        // Reset on any new command
        IF #Open OR #Close THEN
            #Error := FALSE;
            #State := 0;
        END_IF;

    ELSE
        #State := 0;
END_CASE;"""


def _pid_members(params: dict) -> list[MemberDef]:
    return [
        # Inputs
        MemberDef("Enable", BOOL, "Input", comment="PID enable"),
        MemberDef("ManualMode", BOOL, "Input", "FALSE", "TRUE = manual output"),
        MemberDef("ManualValue", REAL, "Input", "0.0", "Manual output value"),
        MemberDef("SP", REAL, "Input", "0.0", "Setpoint"),
        MemberDef("PV", REAL, "Input", "0.0", "Process value"),
        MemberDef("Kp", REAL, "Input", params.get("kp", "1.0"), "Proportional gain"),
        MemberDef("Ti", TIME, "Input", params.get("ti", "T#10s"), "Integral time"),
        MemberDef("Td", TIME, "Input", params.get("td", "T#0s"), "Derivative time"),
        MemberDef("CycleTime", TIME, "Input", params.get("cycle_time", "T#100ms"), "Controller cycle time"),
        MemberDef("OutMin", REAL, "Input", params.get("out_min", "0.0"), "Output minimum"),
        MemberDef("OutMax", REAL, "Input", params.get("out_max", "100.0"), "Output maximum"),
        # Outputs
        MemberDef("Output", REAL, "Output", "0.0", "Controller output"),
        MemberDef("Error_P", REAL, "Output", "0.0", "Current error (SP - PV)"),
        MemberDef("Active", BOOL, "Output", "FALSE", "Controller is active"),
        # Static
        MemberDef("IntegralSum", REAL, "Static", "0.0", "Integral accumulator"),
        MemberDef("LastError", REAL, "Static", "0.0", "Previous error for derivative"),
        # Temp
        MemberDef("dt", REAL, "Temp", comment="Cycle time in seconds"),
        MemberDef("tiSec", REAL, "Temp", comment="Ti in seconds"),
        MemberDef("tdSec", REAL, "Temp", comment="Td in seconds"),
        MemberDef("pTerm", REAL, "Temp", comment="Proportional term"),
        MemberDef("iTerm", REAL, "Temp", comment="Integral term"),
        MemberDef("dTerm", REAL, "Temp", comment="Derivative term"),
        MemberDef("rawOutput", REAL, "Temp", comment="Output before clamping"),
    ]


def _pid_code(params: dict) -> str:
    return """\
IF NOT #Enable THEN
    #Output := 0.0;
    #IntegralSum := 0.0;
    #LastError := 0.0;
    #Active := FALSE;
    RETURN;
END_IF;

#Active := TRUE;

// Manual mode
IF #ManualMode THEN
    #Output := #ManualValue;
    IF #Output < #OutMin THEN #Output := #OutMin; END_IF;
    IF #Output > #OutMax THEN #Output := #OutMax; END_IF;
    #IntegralSum := #Output; // Bumpless transfer
    #Error_P := #SP - #PV;
    #LastError := #Error_P;
    RETURN;
END_IF;

// Calculate error
#Error_P := #SP - #PV;

// Time conversions (TIME to REAL seconds)
#dt := TIME_TO_REAL(#CycleTime) / 1000.0;
#tiSec := TIME_TO_REAL(#Ti) / 1000.0;
#tdSec := TIME_TO_REAL(#Td) / 1000.0;

// P term
#pTerm := #Kp * #Error_P;

// I term (Euler forward)
IF #tiSec > 0.0 THEN
    #IntegralSum := #IntegralSum + (#Kp / #tiSec) * #Error_P * #dt;
END_IF;
#iTerm := #IntegralSum;

// D term
IF #dt > 0.0 THEN
    #dTerm := #Kp * #tdSec * (#Error_P - #LastError) / #dt;
ELSE
    #dTerm := 0.0;
END_IF;

// Sum
#rawOutput := #pTerm + #iTerm + #dTerm;

// Clamp output
IF #rawOutput > #OutMax THEN
    #Output := #OutMax;
    // Anti-windup: limit integral
    #IntegralSum := #IntegralSum - (#rawOutput - #OutMax);
ELSIF #rawOutput < #OutMin THEN
    #Output := #OutMin;
    #IntegralSum := #IntegralSum - (#rawOutput - #OutMin);
ELSE
    #Output := #rawOutput;
END_IF;

#LastError := #Error_P;"""


def _alarm_members(params: dict) -> list[MemberDef]:
    return [
        # Inputs
        MemberDef("Condition", BOOL, "Input", comment="Alarm condition (TRUE = alarm)"),
        MemberDef("Acknowledge", BOOL, "Input", comment="Acknowledge command (pulse)"),
        MemberDef("AutoReset", BOOL, "Input", params.get("auto_reset", "FALSE"), "Auto-reset when condition clears"),
        # Outputs
        MemberDef("Active", BOOL, "Output", "FALSE", "Alarm is active (condition present)"),
        MemberDef("Unacknowledged", BOOL, "Output", "FALSE", "Alarm not yet acknowledged"),
        MemberDef("Latched", BOOL, "Output", "FALSE", "Alarm latched (was active, not yet reset)"),
        # Static
        MemberDef("EdgeAck", "R_TRIG", "Static", comment="Acknowledge edge detection"),
        MemberDef("PrevCondition", BOOL, "Static", "FALSE", "Previous condition for edge"),
    ]


def _alarm_code(params: dict) -> str:
    return """\
// Edge detection
#EdgeAck(CLK := #Acknowledge);

// Rising edge of condition -> latch alarm
IF #Condition AND NOT #PrevCondition THEN
    #Latched := TRUE;
    #Unacknowledged := TRUE;
END_IF;

// Active = condition present
#Active := #Condition;

// Acknowledge
IF #EdgeAck.Q THEN
    #Unacknowledged := FALSE;
END_IF;

// Reset latched alarm
IF #AutoReset THEN
    // Auto-reset: clear when condition gone AND acknowledged
    IF NOT #Condition AND NOT #Unacknowledged THEN
        #Latched := FALSE;
    END_IF;
ELSE
    // Manual reset: clear when acknowledged AND condition gone
    IF NOT #Condition AND NOT #Unacknowledged THEN
        #Latched := FALSE;
    END_IF;
END_IF;

#PrevCondition := #Condition;"""


def _analog_scale_members(params: dict) -> list[MemberDef]:
    return [
        MemberDef("RawValue", INT, "Input", comment="Raw analog input"),
        MemberDef("RawMin", INT, "Input", params.get("raw_min", "0"), "Raw range minimum"),
        MemberDef("RawMax", INT, "Input", params.get("raw_max", "27648"), "Raw range maximum"),
        MemberDef("EngMin", REAL, "Input", params.get("eng_min", "0.0"), "Engineering unit minimum"),
        MemberDef("EngMax", REAL, "Input", params.get("eng_max", "100.0"), "Engineering unit maximum"),
        MemberDef("Normalized", REAL, "Temp"),
    ]


def _analog_scale_code(params: dict) -> str:
    return """\
// Normalize to 0.0 .. 1.0
IF (#RawMax - #RawMin) <> 0 THEN
    #Normalized := INT_TO_REAL(#RawValue - #RawMin) / INT_TO_REAL(#RawMax - #RawMin);
ELSE
    #Normalized := 0.0;
END_IF;

// Scale to engineering range
#FC_AnalogScale := #EngMin + (#Normalized * (#EngMax - #EngMin));

// Clamp output
IF #FC_AnalogScale > #EngMax THEN
    #FC_AnalogScale := #EngMax;
ELSIF #FC_AnalogScale < #EngMin THEN
    #FC_AnalogScale := #EngMin;
END_IF;"""


# Map template name -> (members_fn, code_fn)
_TEMPLATE_BUILDERS = {
    "FB_Motor": (_motor_members, _motor_code),
    "FB_Valve": (_valve_members, _valve_code),
    "FB_PID": (_pid_members, _pid_code),
    "FB_Alarm": (_alarm_members, _alarm_code),
    "FC_AnalogScale": (_analog_scale_members, _analog_scale_code),
}


# ─── BlockLibrary Class ─────────────────────────────────────────────────────

class BlockLibrary:
    """Standard block template library for TIA Portal automation projects."""

    def list_templates(self) -> list[dict]:
        """
        List all available templates.

        Returns:
            List of dicts with keys: name, block_type, description, defaults
        """
        result = []
        for name, info in _TEMPLATES.items():
            result.append({
                "name": name,
                "block_type": info["block_type"],
                "description": info["description"],
                "defaults": dict(info["defaults"]),
            })
        return result

    def get_template_info(self, template: str) -> Optional[dict]:
        """Get info for a specific template."""
        info = _TEMPLATES.get(template)
        if not info:
            return None
        return {
            "name": template,
            "block_type": info["block_type"],
            "description": info["description"],
            "defaults": dict(info["defaults"]),
        }

    def generate_scl(
        self,
        template: str,
        name: Optional[str] = None,
        version: str = "0.1",
        optimized: bool = True,
        comment: str = "",
        **params,
    ) -> str:
        """
        Generate SCL source code from a template.

        Args:
            template: Template name (e.g. "FB_Motor")
            name: Block name (default = template name)
            version: Block version string
            optimized: S7_Optimized_Access
            comment: Block comment
            **params: Template parameters (override defaults)

        Returns:
            SCL source code string

        Raises:
            ValueError: Unknown template name
        """
        if template not in _TEMPLATES:
            available = ", ".join(_TEMPLATES.keys())
            raise ValueError(f"Unknown template '{template}'. Available: {available}")

        info = _TEMPLATES[template]
        block_name = name or template

        # Merge defaults with user params
        merged = dict(info["defaults"])
        merged.update(params)

        # Get members and code
        members_fn, code_fn = _TEMPLATE_BUILDERS[template]
        members = members_fn(merged)
        code = code_fn(merged)

        if not comment:
            comment = info["description"]

        scl = SclGenerator(version=version, optimized=optimized)

        if info["block_type"] == "FB":
            return scl.function_block(block_name, members=members, code=code, comment=comment)
        elif info["block_type"] == "FC":
            # FC_AnalogScale returns Real
            return_type = "Real" if "Scale" in template else "Void"
            # Replace template name in code with actual block name
            actual_code = code.replace(f"#{template}", f"#{block_name}")
            return scl.function(block_name, members=members, code=actual_code,
                                return_type=return_type, comment=comment)
        else:
            raise ValueError(f"Unsupported block type: {info['block_type']}")

    def generate_xml(
        self,
        template: str,
        name: Optional[str] = None,
        number: int = 1,
        version: str = "0.1",
        comment: str = "",
        **params,
    ):
        """
        Generate TIA Openness XML from a template.

        Args:
            template: Template name (e.g. "FB_Motor")
            name: Block name (default = template name)
            number: Block number
            version: Block version string
            comment: Block comment
            **params: Template parameters

        Returns:
            xml.etree.ElementTree.Element (Document root)
        """
        if template not in _TEMPLATES:
            available = ", ".join(_TEMPLATES.keys())
            raise ValueError(f"Unknown template '{template}'. Available: {available}")

        info = _TEMPLATES[template]
        block_name = name or template

        merged = dict(info["defaults"])
        merged.update(params)

        members_fn, code_fn = _TEMPLATE_BUILDERS[template]
        members = members_fn(merged)
        code = code_fn(merged)

        if not comment:
            comment = info["description"]

        gen = TiaBlockGenerator()

        if info["block_type"] == "FB":
            return gen.create_fb(
                number=number, name=block_name, language="SCL",
                members=members,
                networks=[gen.scl_network("Main Logic", code)],
                comment=comment, version=version,
            )
        elif info["block_type"] == "FC":
            return_type = "Real" if "Scale" in template else "Void"
            actual_code = code.replace(f"#{template}", f"#{block_name}")
            return gen.create_fc(
                number=number, name=block_name, language="SCL",
                members=members,
                networks=[gen.scl_network("Main Logic", actual_code)],
                comment=comment, return_type=return_type, version=version,
            )
        else:
            raise ValueError(f"Unsupported block type: {info['block_type']}")

    def generate_all_scl(
        self,
        prefix: str = "",
        version: str = "0.1",
        optimized: bool = True,
    ) -> str:
        """
        Generate SCL for all templates.

        Args:
            prefix: Optional prefix for block names (e.g. "Plant1_")
            version: Block version
            optimized: S7_Optimized_Access

        Returns:
            Combined SCL string with all templates
        """
        parts = []
        for template_name in _TEMPLATES:
            name = prefix + template_name if prefix else None
            parts.append(self.generate_scl(template_name, name=name,
                                           version=version, optimized=optimized))
        return "\n\n".join(parts)


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pathlib import Path

    lib = BlockLibrary()

    print("Available templates:")
    print("-" * 60)
    for t in lib.list_templates():
        print(f"  {t['name']:20s} [{t['block_type']}] {t['description']}")
    print()

    # Generate all as SCL
    output_dir = Path(__file__).parent.parent / "generated_scl" / "library"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_scl = lib.generate_all_scl()
    (output_dir / "all_templates.scl").write_text(all_scl, encoding="utf-8")
    print(f"All templates saved to: {output_dir / 'all_templates.scl'}")

    # Generate individual files
    for t in lib.list_templates():
        scl = lib.generate_scl(t["name"])
        (output_dir / f"{t['name']}.scl").write_text(scl, encoding="utf-8")
        print(f"  {t['name']}.scl")

    # Generate customized motor
    custom = lib.generate_scl("FB_Motor", name="FB_Pump1",
                              startup_time="T#5s", feedback_time="T#10s",
                              comment="Pump 1 motor control")
    (output_dir / "FB_Pump1.scl").write_text(custom, encoding="utf-8")
    print(f"\nCustomized: FB_Pump1.scl")
