from asyncio import Event
from threading import Event
import os
import winsound
import time
import ctypes
from typing import Callable, Optional, Tuple
from pynput import mouse
# from pynput.mouse import Button, Controller
from VFE_local_storage import LocalStorage, CalibrationData, UserPreferences

storage = LocalStorage()
#trap waypoint selector location
WPS_X = 0
WPS_Y = 0

# --- CHECK FOR ADMIN RIGHTS ---
def is_admin():
    try: 
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception: 
        return False

#if not  is_admin():           
#     print("ERROR: You MUST run this script as ADMINISTRATOR for MSFS control")
#     input("Press Enter to exit...")
#     exit()

# --- MACRO TEMPLATES ---
TEMPLATES = {
    "header": "<#> {name}",
    "move": "<mm>({x},{y},{wait})<#> {name}",
    "click_down": "<mlbd><#>",
    "click_up": "<mlbu><#>",
    "scroll_f": "<mwheel_f><#>",
    "scroll_b": "<mwheel_b><#>",
    "wait": "<wx>({wait},0)<#>"
}

BUTTONS = [
    {"name": "clear", "prompt": "Click on CLEAR"},
    {"name": "automan", "prompt": "Click on AUTO-MAN selector"},
    {"name": "wy pt chg", "prompt": "Click on WY PT CHG"},
    {"name": "hold", "prompt": "Click on HOLD"},
    # not used, upsets device state...
    #{"name": "remote", "prompt": "Click on REMOTE"},
    {"name": "insert", "prompt": "Click on INSERT"},
    {"name": "waypoint selector", "prompt": "Click on WAYPOINT SELECTOR"},
    {"name": "data selector", "prompt": "Click on DATA SELECTOR"},
    {"name": "0", "prompt": "Click on 0"}, {"name": "1", "prompt": "Click on 1"},
    {"name": "2", "prompt": "Click on 2"}, {"name": "3", "prompt": "Click on 3"},
    {"name": "4", "prompt": "Click on 4"}, {"name": "5", "prompt": "Click on 5"},
    {"name": "6", "prompt": "Click on 6"}, {"name": "7", "prompt": "Click on 7"},
    {"name": "8", "prompt": "Click on 8"}, {"name": "9", "prompt": "Click on 9"}
]

DIAL_POSITIONS = ["TK/GS", "HDG DA", "XTK TKE", "POS", "WAY PT", "DIS/TIME", "WIND", "DSRTK/STS", "TEST"]

APPDATA_DIR = os.path.join(os.getenv("APPDATA"), "msfsVFE")

class CalibrationWizard:
    def __init__(self, 
                 prompt_callback: Optional[Callable[[str], str]] = None,
                 status_callback: Optional[Callable[[str], None]] = None,
                 wait_for_click: Optional[Event] = None,
                 beep_callback: Optional[Callable[[int, int], None]] = None,
                 global_wait: Optional[str] = None):
        self.recorded_lines = []
        self.last_pos = (0, 0)
        self.event_captured = False
        self.global_wait = global_wait or "200"
        #Keep at 300
        self.global_slow_wait = "300"
        self.data_selector_coords = None
        self.prompt_callback = prompt_callback
        self.status_callback = status_callback
        self.beep_callback = beep_callback
        self.wait_for_click = wait_for_click
        if self.wait_for_click is not None:
            self.wait_for_click.action = None

    def beep(self, freq=1000, dur=100):
        if self.beep_callback:
            self.beep_callback(freq, dur)
        else:
            winsound.Beep(freq, dur)

    def prompt(self, message: str) -> str:
        if self.prompt_callback:
            return self.prompt_callback(message)
        return input(message)

    def update_status(self, message: str):
        if self.status_callback:
            self.status_callback(message)
        else:
            print(message)

    def on_click(self, x, y, button, pressed):
        if pressed and button == mouse.Button.left:
            self.last_pos = (int(x), int(y))
            self.event_captured = True
            return False

    def add_standard_action(self, action_key):
        self.recorded_lines.append(TEMPLATES[action_key])
        self.recorded_lines.append(TEMPLATES["wait"].format(wait=self.global_wait))

    def add_delayed_action(self, action_key):
        self.recorded_lines.append(TEMPLATES[action_key])
        self.recorded_lines.append(TEMPLATES["wait"].format(wait=self.global_slow_wait))

    def run(self):
        self.update_status("--- CIVA Calibration Assistant ---")
        if int(self.global_wait) < 100:
            self.global_wait = "100"
            self.update_status("Too small, set to '100'")
        
        for btn in BUTTONS:
            self.update_status(f"Next: {btn['prompt']}")
            self.event_captured = False
            with mouse.Listener(on_click=self.on_click) as _:
                while not self.event_captured:
                    time.sleep(0.1)
            
            x, y = self.last_pos
            if btn['name'] == "data selector": 
                self.data_selector_coords = (x, y)
                self.update_status(f"Captured data selector at: {x}, {y}")
            elif btn['name'] == "waypoint selector": 
                WPS_X = x
                WPS_Y = y
            self.beep()
            self.recorded_lines.append(TEMPLATES["header"].format(name=btn['name']))

            
            if "selector" in btn['name'] or \
                btn['name'] == "automan":
                self.update_status(f"  Setting template for: {btn['name']}")
                self.recorded_lines.append(TEMPLATES["move"].format(x=x, y=y, wait=self.global_slow_wait, name=btn['name']))
                self.add_standard_action("click_down")
                self.add_standard_action("click_up")
                #self.add_delayed_action("scroll_f")
                self.add_standard_action("scroll_f")
                self.add_standard_action("click_down")
                self.add_standard_action("click_up")
                self.recorded_lines.append("")
                #---- Add a back version of the selector! ----
                hdr_name = TEMPLATES["header"] + " back"
                self.recorded_lines.append(hdr_name.format(name=btn['name']))
                self.recorded_lines.append(TEMPLATES["move"].format(x=x, y=y, wait=self.global_slow_wait, name=btn['name']))
                self.add_standard_action("click_down")
                self.add_standard_action("click_up")
                #self.add_delayed_action("scroll_f")
                self.add_standard_action("scroll_b")
                self.add_standard_action("click_down")
                self.add_standard_action("click_up")                
            else:
                self.recorded_lines.append(TEMPLATES["move"].format(x=x, y=y, wait=self.global_wait, name=btn['name']))
                self.add_standard_action("click_down")
                self.add_standard_action("click_up")
            self.recorded_lines.append("")

        doDataSelector = False
        if not doDataSelector:
            if self.wait_for_click:
                self.update_status("\nWaiting for Confirm Save or Stop/Reset...")
                self.wait_for_click.action = None
                self.wait_for_click.clear()
                self.wait_for_click.wait()
                action = getattr(self.wait_for_click, 'action', None)
                if action == 'save':
                    self.save_file()
                else:
                    self.update_status('Calibration save cancelled.')
                self.wait_for_click.clear()
            else:
                self.save_file()
        else:
            self.verify_data_selector()

        return WPS_X, WPS_Y
    
    def verify_data_selector(self):
        if not self.data_selector_coords:
            self.update_status("\n[ERROR] Coordinates missing.")
            return
        
        self.prompt("\nPress Enter to begin (Tab to MSFS and DONT TOUCH MOUSE)...")
        for i in range(5, 0, -1):
            self.update_status(f"  {i}...")
            time.sleep(1)

        # DIRECT WINDOWS API CALL FOR ABSOLUTE POSITION
        x, y = self.data_selector_coords
        ctypes.windll.user32.SetCursorPos(x, y)
        self.update_status(f"  Sent cursor to Absolute: {x}, {y}")
        time.sleep(2.0) 

        # Re-verify position with pynput to see if it stayed there
        m = mouse.Controller()
        actual_x, actual_y = m.position
        self.update_status(f"  Sim reported cursor at: {actual_x}, {actual_y}")

        # FOCUS CLICK
        m.press(mouse.Button.left)
        time.sleep(0.2)
        m.release(mouse.Button.left)
        time.sleep(0.5)

        # DATA SELECTOR LOGIC (8 LEFT, 4 RIGHT)
        self.update_status("  Resetting to TK/GS...")
        for _ in range(8):
            m.scroll(0, -1)
            time.sleep(0.4)
        
        for pos in DIAL_POSITIONS:
            self.update_status(f"  Pos: {pos}")
            self.beep(800, 100)
            time.sleep(0.8)
            if pos != "TEST": 
                m.scroll(0, 1)

        self.update_status("  Returning to WAY PT...")
        for _ in range(4):
            m.scroll(0, -1)
            time.sleep(0.4)

        ans = self.prompt("\nVerified? (y/n): ")
        if ans.lower() == 'y': 
            self.save_file()


    def save_file(self):
        #script_dir = os.path.dirname(os.path.abspath(__file__))
        
        output_path = os.path.join(APPDATA_DIR, "CIVAinsCalibration.txt")
        with open(output_path, "w") as f:
            f.write("\n".join(self.recorded_lines))
        self.update_status(f"SUCCESS! Saved calibration to: {output_path}")


def run_calibration(
    prompt_callback: Optional[Callable[[str], str]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    wait_for_click: Optional[Event] = None,
    beep_callback: Optional[Callable[[int, int], None]] = None,
    global_wait: Optional[str] = None,
) -> Tuple[bool, int, int]:
    """Run the calibration wizard interactively and return True if the file was saved."""
    wizard = CalibrationWizard(
        prompt_callback=prompt_callback,
        status_callback=status_callback,
        wait_for_click=wait_for_click,
        beep_callback=beep_callback,
        global_wait=global_wait,
    ) 
    result = wizard.run()
    calibration_path = os.path.join(APPDATA_DIR, "CIVAinsCalibration.txt")
    # return wypt sel x,y
    return os.path.exists(calibration_path), result[0], result[1]


if __name__ == "__main__":
    run_calibration()
