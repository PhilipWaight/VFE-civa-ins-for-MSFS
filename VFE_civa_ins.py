#!/usr/bin/env python3
from ast import Try
import math
import sys 
import os
import ctypes
from types import SimpleNamespace
import json
import threading
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field

import re
# read optional OFP pdf file for dispatch remarks
from click import group
from pypdf import PdfReader
# glob for targeted cleanup of previous plan macros from 
# flightplan\PHASES folder
import glob
# for Phases macro files...
import keyboard as global_kb
import pyperclip
import time
# facilitate clipboard actions with beep prompt
import winsound
# fail safe for python exit by mouse move to top left
import pyautogui
import logging
#running process checks
import psutil
#MSFS focus
import win32gui
import win32con
import win32process
import win32con
# No changes needed to the focus function logic!
import subprocess

# SimConnect
from VFE_simconnect_wrapper import SimConnectWrapper

# Mouse/Keyboard automation
from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

# Support threading event in called script
from threading import Event

# Local storage
from VFE_local_storage import LocalStorage, CalibrationData, UserPreferences

# PyQt5 imports for new UI framework
from PyQt5.QtWidgets import (
    QApplication, QDialog, QMainWindow, QProgressBar, QSizePolicy, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QGroupBox, QMessageBox,
    QTextEdit, QComboBox, QShortcut, QPlainTextEdit, QTextBrowser
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QPalette, QColor, QIcon, QTextCursor, QTextBlock

#import cv2 # Optional, but excellent for cleaning up flight sim text textures
#Capture waypoint selector digit by image capture
from datetime import datetime
import mss
from PIL import Image, ImageOps, ImageFilter
from PIL import ImageMorph     # Native morphology engine
# Download, install and updated windows env path to include tesseract install folder
# https://builtin.com/articles/python-tesseract
import pytesseract

# FORCE REGISTRATION: Explicitly binds the layout types to PyQt's cross-thread engine
# try:
#     qRegisterMetaType(QTextBlock, "QTextBlock")
#     qRegisterMetaType(QTextCursor, "QTextCursor")
# except Exception:
#     pass

__author__  = "Philip Waight"
__ai__      =  "Gemini"
__version__ = "1.0.0"
__status__  = "Beta"  #  "Production", "Dev", "Beta"

# Explicitly tell Windows this is a unique application, not generic Python
myappid = f'PJsim.VFE.{__version__}'  # Arbitrary string unique to your application
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

# --- CHECK FOR ADMIN RIGHTS ---
def is_admin():
    try: 
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception: 
        return False

#if not  is_admin():           
#     print("ERROR: You MUST run this program as ADMINISTRATOR\n       for MSFS phase hotkeys to be actioned")
#     input("Press Enter to exit...")
#     exit()

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Waypoint:
    """Represents a flight plan waypoint."""
    id: str
    name: str
    latitude: float
    longitude: float
    altitude: int
    oceanic: bool = False
    loaded: bool = False

@dataclass
class Phase:
    """Represents a CIVA phase (up to 9 waypoints)."""
    number: int
    waypoints: List[Waypoint] = field(default_factory=list)
    from_icao: str = ""
    to_icao: str = ""


@dataclass
class FlightPlan:
    """Complete flight plan data."""
    departure: str = ""
    destination: str = ""
    phases: List[Phase] = field(default_factory=list)
    accel_waypoint: str = ""
    decel_waypoint: str = ""


@dataclass
class AircraftState:
    """Current aircraft state from SimConnect."""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    heading: float = 0.0
    ground_speed: float = 0.0
    active_waypoint: str = ""

# Default inline message Dict
DEFAULT_INLINE_MSG = {
    "title"     : "Next INS phase pending",
    "w_pct"     : 20,            # dialog width as % of screen wid
    "h_pct"     : 10,            # dialog height as % of screen ht
    "x"         : 200, 
    "y"         : 200,
    "ontop"     : 1, 
    "buttons"   : 1,            #Ok button
    "timeout"   : 10,           #secs
    "style"     : "font-size: 12pt;",
    "html"      : ""
}

# Configure logging while degugging the new UI framework and CIVA button automation
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
gLogging = False


"""
CIVA INS Flight Plan Processor - PyQt5 Windows UI Version

This script emulates co-pilot manual entry of waypoint coordinates to the civa ins
using a native Windows UI interface without Macro Commander dependency.

See README.md for detailed setup instructions

"""

# =============================================================================
# Flight Plan Processor
# =============================================================================

class FlightPlanProcessor:
    """Handles flight plan parsing and phase generation."""
    
    def __init__(self, ui_instance):
        # calibration_path: str):
        self.ui = ui_instance
        self.current_plan: Optional[FlightPlan] = None
        self.calibration_data = {}
        # Use a Lock to prevent multiple macros from firing at once
        self.ui.macro_lock = threading.Lock()

    def bind_all_sequences(self):
        # Clear previous bindings and interrupts to prevent overlap
        try:
            self.ui.worker = FlightPlanWorker(self.ui)  # Re-instantiate to reset state
            global_kb.unhook_all()
            self.ui.worker.is_cancelled = False

        except Exception:
            pass # Safety catch for uninitialized listeners
        # 0. bind interrupt hotkey (Shift + Esc)
        # interrupt trapped in VFEtray
        # global_kb.add_hotkey('shift+esc', self.ui.worker.cancel, suppress=True)

        # 1. Bind Phase Load Sequence (e.g., Ctrl+Shift+1, +2, +3...)
        self.setup_sequence(
            start_key=self.ui.phase_hotkey, 
            count=self.ui.total_phases, 
            callback=self.ui.trigger_phase_macro,
            is_f_key=False
        )

        # 2. Bind Waypoint Info Sequence (e.g., Ctrl+Shift+F1, +F2, +F3...)
        self.setup_sequence(
            start_key=self.ui.waypoint_hotkey, 
            count=self.ui.total_phases, 
            callback=self.ui.trigger_waypoint_info,
            is_f_key=True
        )

    def setup_sequence(self, start_key, count, callback, is_f_key):
        # Split 'ctrl+shift+1' -> base='ctrl+shift', key='1'
        parts = start_key.split('+')
        base_modifiers = "+".join(parts[:-1])
        start_val = parts[-1]

        for i in range(count):
            if is_f_key:
                # Handle F-keys: 'f' + (initial_num + offset)
                initial_num = int(start_val.lower().replace('f', ''))
                current_key = f"f{initial_num + i}"
            else:
                # Handle Numeric keys: 1 + offset
                current_key = str(int(start_val) + i)

            full_hotkey = f"{base_modifiers}+{current_key}"
            
            # Bind with 'n=i+1' to freeze the ID in the lambda
            global_kb.add_hotkey(full_hotkey, lambda n=i+1: callback(n))

            # Phase Load Hotkeys Callback Connection:
            #global_kb.add_hotkey(full_hotkey, lambda n=i+1: self.ui.trigger_phase_macro(n))

            # Waypoint Dialogue Hotkeys Callback Connection:
            #global_kb.add_hotkey(full_hotkey, lambda n=i+1: self.ui.trigger_waypoint_info(n))



    def load_calibration(self):
        """Load calibration data."""
        if os.path.exists(self.ui.calibration_path):
            try:
                with open(self.ui.calibration_path, 'r') as f:
                    current_button = None
                    for line in f:
                        clean_line = line.strip()
                        if clean_line.startswith("<#>"):
                            current_button = clean_line[3:].strip().lower()
                            self.calibration_data[current_button] = []
                        elif current_button:
                            self.calibration_data[current_button].append(clean_line)
            except Exception as e:
                logger.error(f"Failed to load calibration: {e}")
    
    def load_flight_plan(self, file_path: str) -> FlightPlan:
        """Load and parse a flight plan file."""
        tree = ET.parse(file_path)
        root = tree.getroot()
        fp_container = root.find(".//FlightPlan.FlightPlan")
        
        plan = FlightPlan()
        
        # Extract departure/destination
        plan.departure = self._get_global_icao(root, "DepartureID") or "DEP"
        plan.destination = self._get_global_icao(root, "DestinationID") or "ARR"
        
        # Extract waypoints
        waypoints = []
        for child in fp_container:
            tag = child.tag.split('}')[-1].lower()
            if "atcwaypoint" in tag:
                wp = self._parse_waypoint(child)
                if wp:
                    waypoints.append(wp)
        
        # Read PDF for accel/decel
        pdf_path = file_path.replace(".pln", ".pdf").replace("_NoProc", "")
        if os.path.exists(pdf_path):
            plan.accel_waypoint, plan.decel_waypoint = self._read_ofp_pdf(pdf_path)
        
        # Split into phases (9 waypoints each)
        chunk_size = 9
        for i in range(0, len(waypoints), chunk_size):
            chunk = waypoints[i:i + chunk_size]
            phase = Phase(
                number=i // chunk_size + 1,
                waypoints=chunk,
                from_icao=plan.departure if i == 0 else chunk[0].name,
                to_icao=plan.destination if i + chunk_size >= len(waypoints) else chunk[-1].name
            )
            plan.phases.append(phase)
        
        self.current_plan = plan
        return plan
    
    def _get_global_icao(self, container, tag_name: str) -> Optional[str]:
        """Extract ICAO from flight plan."""
        node = container.find(f".//{tag_name}")
        if node is not None:
            icao_child = node.find(".//ICAOIdent")
            if icao_child is not None:
                return icao_child.text
            return node.text
        return None
    
    def _parse_waypoint(self, node) -> Optional[Waypoint]:
        """Parse a waypoint from XML node."""
        world_pos = node.findtext("WorldPosition")
        if not world_pos:
            return None
        
        # Parse coordinates
        coord_pattern = r"([NS])(\d+)°\s*(\d+)'\s*(\d+\.?\d*)\",([EW])(\d+)°\s*(\d+)'\s*(\d+\.?\d*)\",[-+]?0*(\d+)\.?\d*"
        match = re.search(coord_pattern, world_pos)
        if not match:
            return None
        
        lat_card, lat_d, lat_m, lat_s, lon_card, lon_d, lon_m, lon_s, elev = match.groups()
        
        # Convert to decimal
        lat = float(lat_d) + float(lat_m)/60 + float(lat_s)/3600
        if lat_card == "S": lat = -lat
        
        lon = float(lon_d) + float(lon_m)/60 + float(lon_s)/3600
        if lon_card == "W": lon = -lon
        
        waypoint_id = node.get("id") or "UNK"
        icao = node.findtext("ICAO/ICAOIdent")
        if icao:
            waypoint_id = icao
        
        return Waypoint(
            id=waypoint_id,
            name=waypoint_id,
            latitude=lat,
            longitude=lon,
            altitude=int(elev)
        )
    
    def _read_ofp_pdf(self, pdf_path) -> tuple:
        """Read OFP PDF for accel/decel waypoints."""
        accel_name = ""
        decel_name = ""
        
        try:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                text = page.extract_text()
                lines = text.splitlines()
                
                for line in lines:
                    accel_match = re.search(r"ACCEL:\s*(\S+)", line)
                    if accel_match:
                        accel_name = accel_match.group(1)
                    
                    decel_match = re.search(r"DECEL:\s*(\S+)", line)
                    if decel_match:
                        decel_name = decel_match.group(1)
        except Exception as e:
            logger.debug(f"PDF read error (normal if no PDF): {e}")
        
        return accel_name, decel_name


# ============================================================================
# PYQT5 THREADED INTERRUPT HANDLER for pushing the flight plan
# ============================================================================

class FlightPlanWorker(QThread):
    # Signals to communicate back to the UI
    progress_changed = pyqtSignal(int)
    status_changed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, uiInstance):
        super().__init__()
        self.ui = uiInstance  # Store the reference correctly
        self.ui.is_cancelled = False
        self.ui.is_loading = False
        self.ui.isRunning = False        
    
    def run(self, phase_num):
        self.status_changed.emit(f"VFE: Starting Phase {phase_num} Load...")
        # Trigger mouse movement logic here
        result = load_phase_to_civa(self, phase_num)  #self.current_phase
        if result.get('success'):
            self.status_changed.emit(result.get('message'))
            self.status_changed.emit(f"✅ Armed hotkeys for MSFS load")
        else:  
            self.status_changed.emit(f"❌ {result.get('message')}")
            QApplication.processEvents()  # Alert the user with a beep on failure
            self.cancel()  # Ensure we stop any ongoing processing if there's an error
        
    def test(self):
        steps = ["Initializing...", "Parsing Data...", "Moving Mouse...", "Finalizing..."]
        
        for i, step_name in enumerate(steps):
            if self.is_cancelled:
                break
            
            # Update UI
            self.status_changed.emit(step_name)
            self.progress_changed.emit(int((i / len(steps)) * 100))
            
            # Simulate your logic (mouse moves/clicks)
            time.sleep(1) 
            
        self.finished.emit()

    def cancel(self):
        self.is_cancelled = True
        self.ui.is_loading = False
        self.ui.worker.isRunning = False
        pyautogui.mouseUp()  # Ensure any held mouse buttons are released
        self.ui.worker.wait()  # stop any further processing
        logger.info("Flight plan worker cancelled by user.")


class CalibrationWorker(QThread):
    statusChanged = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, ui, global_wait: str = "200"):
        super().__init__()
        self.global_wait = global_wait
        self.ui = ui
 
    def run(self):
        try:
            # Create a 'gate' that can be opened/closed
            self.user_clicked_event = Event() 
            
            from VFE_civa_calibrate import run_calibration
            result = run_calibration(
                status_callback=self.statusChanged.emit,
                wait_for_click=self.user_clicked_event, # Pass the event
                beep_callback=lambda freq, dur: winsound.Beep(freq, dur),
                global_wait=self.global_wait,
            )
            success, wps_x, wps_y = result
            self.ui.waypoint_sel_x = wps_x
            self.ui.waypoint_sel_y = wps_y

        except Exception as e:
            logger.error(f"Calibration worker failed: {e}")
            self.statusChanged.emit(f"Calibration error: {e}")
            success = False

        self.finished.emit(success)

# ============================================================================
# PYQT5 UNIVERSAL WORKER - processing functions
# ============================================================================

#class UniversalWorker(QThread):
#    progress_changed = pyqtSignal(int)
#    status_changed = pyqtSignal(str)
#    finished = pyqtSignal()

#    def __init__(self, task_function):
#        super().__init__()
#        self.task_function = task_function  # Pass your logic function here
#        self.is_cancelled = False

#    def run(self):
        # Execute the specific function passed during init
#        self.task_function(self) 
#        self.finished.emit()

#    def cancel(self):
#        self.is_cancelled = True

# ============================================================================
# PYQT5 UNIVERSAL WORKER - generic processing functions
# ============================================================================

#def process_alpha(worker):
#    for i in range(10):
#        if worker.is_cancelled: return
#        worker.status_changed.emit(f"Step {i} of Alpha")
#        time.sleep(1)

#def process_beta(worker):
    # Different logic here
#    worker.status_changed.emit("Running Beta...")
#    time.sleep(5)

# Triggering from the UI:
#def start_alpha(self):
#    self.worker = UniversalWorker(process_alpha)
#    self.worker.status_changed.connect(self.statusLabel.setText)
#    self.worker.start()

class wplistDialog(QDialog):
    def __init__(self, title, html_content, w_pct, h_pct):
        super().__init__()
        # Title and styling
        if gLogging: logger.info("Initializing waypoint dialogue with title: " + title)
        self.setWindowTitle(title)

        # Access the Windows DWM API using ctypes
        DWMWA_CAPTION_COLOR = 35     # Attribute for title bar background
        DWMWA_TEXT_COLOR = 36        # Attribute for title bar text
        
        hwnd = int(self.winId())     # Get the native window handle
        
        # Set background color to dark blue (Hex: #0000FF -> BGR: 0xFF0000)
        bg_color = 0xDCDCDC 
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(ctypes.c_int(bg_color)), 4
        )
        
        # Set text color to white (Hex: #FFFFFF -> BGR: 0xFFFFFF)
        text_color = 0x0
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_TEXT_COLOR, ctypes.byref(ctypes.c_int(text_color)), 4
        )


        # Calculate dynamic pixel size based on user's current display width percentage
        screen_geo = QApplication.desktop().screenGeometry(self)
        width = int(screen_geo.width() * (w_pct / 100.0))
        height = int(screen_geo.height() * (h_pct / 100.0))
        #self.setMinimumSize(width, height)  
        # Forces window on top of MSFS without pulling desktop system input focus
        self.setWindowFlags(self.windowFlags() | 
                                Qt.WindowStaysOnTopHint | 
                                Qt.Tool ) 
                                #Qt.WindowTransparentForInput)

        # 1. Main vertical layout
        main_layout = QVBoxLayout()
        
        # 2. Add HTML table (safe for sizes smaller than content)
        self.browser = QTextBrowser()
        self.browser.setHtml(html_content)
        main_layout.addWidget(self.browser)
        
        # 3. Create OK Button layout at the bottom
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("OK", self)
        #ok_button.setFixedWidth(80)
        ok_button.clicked.connect(self.accept) # Closes dialog with accepted status
        
        # Right-align the button (standard UI practice)
        button_layout.addStretch()
        button_layout.addWidget(ok_button, alignment=Qt.AlignLeft)
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
        # 4. Set a small minimum size (Safe because QTextBrowser will show scrollbars)
        #self.setMinimumSize(100, 150) 
        # Force the dialog layout to strictly respect the size hints of its contents
        self.layout().setSizeConstraint(main_layout.SetMinimumSize)

# ============================================================================
# PYQT5 UI FRAMEWORK - CIVA INS Flight Plan Window
# ============================================================================

class CIVAFlightPlanUI(QMainWindow):
    """
    Main PyQt5 window for CIVA INS Flight Plan processing.
    
    UI Structure (5 Control Groups):
    - Group 1: Load Flight Plan (button + file picker + filename display)
    - Group 2: Capture/Hotkey Controls (button + hotkey display)
    - Group 3: Calibration (button + status indicator)
    - Group 4: Simconnect Telemetry (status fields for INS data)
    - Group 5: Connection & Exit (Simconnect check, MSFS status, Exit button)
    """
    # 1. CRITICAL: defined  at the CLASS level
    # This registers the signal with PyQt's meta-object framework
    request_waypoint_ui = pyqtSignal(int)
    # Dedicated thread-safe channel passing the JSON payload dictionary
    request_inline_msg_ui = pyqtSignal(dict) 
    # NEW: Dedicated thread-safe channel passing string log messages
    request_log_update = pyqtSignal(str)     

    def __init__(self):
        super().__init__()
        self.loaded_flight_plan = None
        self.flight_plan_path = None
        self.calibration_status = False
        self.calibration_path = False
        self.simconnect_connected = False
        self.msfs_running = False
        self.current_phase = 0
        self.total_phases = 0
        self.generated_phases = []
        self.generated_waypoints = []
        self.msg_html_waypoints = [] # Caches dynamic HTML strings for waypoint summary table
        self.is_loading = False
        #ensure no library UI timing conflict
        pyautogui.PAUSE = 0
        pyautogui.MINIMUM_DURATION = 0
        pyautogui.MINIMUM_SLEEP = 0.        
        self.appdata_dir = os.path.join(os.getenv("APPDATA"), "msfsVFE")
        os.makedirs(self.appdata_dir, exist_ok=True) 
        # Check if calibration file exists at startup
        #script_dir = os.path.dirname(os.path.abspath(__file__))
        self.calibration_path = os.path.join( self.appdata_dir, "CIVAinsCalibration.txt")
        if os.path.exists(self.calibration_path):
            self.calibration_status = True

        # Load existing settings or use defaults
        self.settings = self.load_settings("settings.json")
        self.global_wait = self.settings.get("global_wait", 200) 
        self.lastwpinfo_dist = self.settings.get("lastwpinfo_dist", 50)
        self.lastwpwarn_dist = self.settings.get("lastwpwarn_dist", 5)
        self.lastwpwarn_clear = False           #True - when next phase loaded  
        self.txt_global_wait = str(self.global_wait)
        self.txt_phase_hotkey = self.settings.get("phase_hotkey", "ctrl+shift+1")
        self.txt_waypoint_hotkey = self.settings.get("waypoint_hotkey", "ctrl+shift+F1")
        self.loaded_flight_plan = self.settings.get("flight_plan", None)
        self.phase_hotkey = self.txt_phase_hotkey
        self.waypoint_hotkey = self.txt_waypoint_hotkey

        # Components
        self.simconnect = SimConnectWrapper("CIVA INS simconnect")
        self.flight_plan = FlightPlanProcessor(self)
        self.automation = CivaButtonPusher(self)
        self.storage = LocalStorage()   
        # initialise wp tracker and check OCR status
        self.wp_tracker = CIVA_INS_WP_Tracker(self) 
        waypoint_sel_loc =self.settings.get("waypoint_sel_loc")
        if waypoint_sel_loc:
            self.waypoint_sel_x =waypoint_sel_loc["scn_x"]
            self.waypoint_sel_y =waypoint_sel_loc["scn_y"]
        else:
            self.waypoint_sel_x = 0
            self.waypoint_sel_y = 0          
       
        # Setup the Worker
        self.worker = FlightPlanWorker(self)
        self.calibration_worker = None

        self.initUI()
        self.setup_telemetry_timer()

        self.update_hotkey_status()
        self.update_calibration_status()

        # Track runtime environment configurations
        self.waypoint_html_data = {} # Caches your dynamic HTML strings
        self.trigger_file = "vfe_dialogue.trigger"

        # Asynchronous trigger watcher for crisp HTML dialogue rendering
        self.dialogue_watcher = QTimer(self)
        self.dialogue_watcher.timeout.connect(self.check_dialogue_requests)
        self.dialogue_watcher.start(100) # Fast 100ms processing poll rate 
        # Connect the new cross-thread bridge channel
        self.request_inline_msg_ui.connect(self.render_inline_macro_msg) 

        # 2. Connect the thread-safe bridge signal to your dialogue renderer
        self.request_waypoint_ui.connect(self.show_html_waypoint_dialogue)

        # 3. Connect the thread-safe signal to your actual UI update function
        self.request_log_update.connect(self._safe_append_log)

        # Safe launch configuration for the C Companion
       
        self.launch_vfe_tray()
        
# ============================================================================

    def launch_vfe_tray(self):
        """Ensures a single clean copy of the C tray application is running."""
        # Clean out lingering background tasks before bootstrapping
        try:
            subprocess.run(["taskkill", "/F", "/IM", "VFEtray.exe"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        # Wipe old stale trigger files from previous runs
        if os.path.exists(self.trigger_file):
            try: os.remove(self.trigger_file)
            except Exception: pass

        if os.path.exists("VFEtray.exe"):
            # Launch detached from python's console handler
            subprocess.Popen(["VFEtray.exe"], creationflags=subprocess.CREATE_NO_WINDOW)

    def closeEvent(self, event):

        # Automatically save when the user closes the app
        self.settings["global_wait"]  = self.global_wait
        self.settings["phase_hotkey"] = self.phase_hotkey
        self.settings["waypoint_hotkey"] = self.waypoint_hotkey
        self.settings["flight_plan"]  = self.loaded_flight_plan
        self.save_settings(self.settings)

        # Add this alongside your tray exit code
        if hasattr(self, 'current_inline_dialogue') and self.current_inline_dialogue:
            try: self.current_inline_dialogue.close()
            except Exception: pass

        """Cleanly terminates the C tray companion when the pilot quits VFEui."""
        tray_hwnd = win32gui.FindWindow("VFEEngineTrayClass", "VFE Tray Engine")
        if tray_hwnd:
            # Post direct Exit Command Token to the C WndProc handler loop
            win32gui.PostMessage(tray_hwnd, win32con.WM_COMMAND, 1001, 0) # 1001 = ID_TRAY_EXIT
        
        # Housekeeping: Purge active runtime files
        for i in range(1, 10):
            try: os.remove(f"macro_p{i}.txt")
            except Exception: pass
        if os.path.exists(self.trigger_file):
            try: os.remove(self.trigger_file)
            except Exception: pass

        event.accept()

    def export_vfe_macros(self, processed_flight_plan):
        """
        Call after flightPlanProcessor completes parsing.
        Expects processed_flight_plan to be a dictionary structure containing the legs.
        """
        #appdata_dir = os.path.join(os.getenv("APPDATA"), "msfsVFE")
        os.makedirs(self.appdata_dir, exist_ok=True)
                
        # Reset current text data cache structures
        self.waypoint_html_data.clear()
        
        phases = processed_flight_plan.get("phases", [])
        self.total_phases = len(phases) # Auto-sets count bounds for loop mapping

        for idx, phase in enumerate(phases):
            phase_id = idx + 1
            
            # A. Build the macro command script line arrays
            # Write files directly into the shared Appdata repository
            filename = os.path.join(self.appdata_dir, f"macro_p{phase_id:01d}.txt")
            with open(filename, "w") as f:
                # Loop the macro string objects built inside your calibration module
                for cmd in phase.get("macro_commands", []):
                    f.write(f"{cmd}\n")

            # B. Store HTML formatting text block dynamically for this leg's display summary
            # Adjust string interpolation markers to map your real layout coordinates
            # self.waypoint_html_data[phase_id] = f"""
            # <html>
            #     <body style='background-color: #121212; color: #00FF00; font-family: Consolas; padding: 10px;'>
            #         <h2 style='color: #ffaa00; margin-bottom: 0px;'>[WAYPOINT {phase_id:02d} MANIFEST]</h2>
            #         <h4 style='color: #888888; margin-top: 5px;'>ROUTE: {phase.get("from_icao", "???")} &rarr; {phase.get("to_icao", "???")}</h4>
            #         <hr border='1' color='#ffaa00'/>
            #         <table border='0' style='font-size: 14px; color: #ffffff;'>
            #             <tr><td><b>TRACK:</b></td><td style='color:#ffaa00;'>{phase.get("heading", "000")}&deg; True</td></tr>
            #             <tr><td><b>CIVA POSITION:</b></td><td>WP POSITION {phase_id}</td></tr>
            #             <tr><td><b>COORDINATES:</b></td><td style='color:cyan;'>{phase.get("lat_lon_str", "N 00 00.0 / E 00 00.0")}</td></tr>
            #             <tr><td><b>STATUS:</b></td><td style='color:lime;'>TELEMETRY LINK SECURED</td></tr>
            #         </table>
            #         <br/>
            #         <p style='color: #555555; font-size: 11px;'>Press Shift+Esc instantly to abort hardware pointer tracking lines.</p>
            #     </body>
            # </html>
            # """

    def trigger_phase_macro(self, phase_number: int):
        """Target execution logic for your captured Phase Hotkeys"""
        tray_hwnd = win32gui.FindWindow("VFEEngineTrayClass", "VFE Tray Engine")
        if tray_hwnd:
            # Check correct waypoint selector - 0
            if self.ocr_available == True:
                detected_digit = self.wp_tracker.capture_and_ocr_digit(self.ui_instance)
                if detected_digit in range(10) and detected_digit == 0:
                    self.update_progress_log(f"✅ Waypoint selector set to 0")
                elif detected_digit != 0:
                    self.update_progress_log(f"⚠️ Waypoint selector digit set to {detected_digit}")
                else: 
                    self.update_progress_log(f"⚠️ Waypoint selector digit not OCR readable")

            # Signal WM_VFE_EXECUTE_PHASE (WM_USER + 10)
            win32gui.PostMessage(tray_hwnd, win32con.WM_USER + 10, phase_number, 0)
            self.update_progress_log(f"VFE: Phase {phase_number} macro stream dispatched to background core.")

    def trigger_waypoint_info(self, phase_number: int):
        """Target execution logic for your captured Waypoint Dialogue Hotkeys"""
        # This safely broadcasts the request to the main thread's event loop
        self.request_waypoint_ui.emit(phase_number)

        # tray_hwnd = win32gui.FindWindow("VFEEngineTrayClass", "VFE Tray Engine")
        # if tray_hwnd:
        #     # Signal WM_VFE_DISPLAY_INFO (WM_USER + 11)
        #     win32gui.PostMessage(tray_hwnd, win32con.WM_USER + 11, wp_number, 0)

# This handles rendering crisp HTML dialog windows synchronously 
# on top of the sim frame without stealing input focus windows 
# away from the game loop.

    def check_dialogue_requests(self):
        """Watches for file notification requests emitted from the C tray engine thread."""
        if os.path.exists(self.trigger_file):
            try:
                with open(self.trigger_file, "r") as f:
                    wp_num = int(f.read().strip())
                os.remove(self.trigger_file) # Consume token file instantly
                
                # self.show_html_waypoint_dialogue(wp_num)
            except Exception:
                pass
        # 2. Handle Inline <msg> Command Intercepts
        # New: Check for inline <msg> triggers emitted out of macro run executions
        msg_trigger = "vfe_msg.trigger"
        if os.path.exists(msg_trigger):
            try:
                os.remove(msg_trigger) # Consume token instantly
                
                # Fetch JSON parameters from AppData
                    # fprintf(msgFile, "{\n");
                    # fprintf(msgFile, "  \"x\": %d, \"y\": %d,\n", mx, my);
                    # fprintf(msgFile, "  \"html\": \"%s\",\n", textBuf);
                    # fprintf(msgFile, "  \"title\": \"%s\",\n", titleBuf);
                    # fprintf(msgFile, "  \"buttons\": %d, \"timeout\": %d,\n", buttons, timeout);
                    # fprintf(msgFile, "  \"type\": %d, \"ontop\": %d,\n", mtype, ontop);
                    # fprintf(msgFile, "  \"w_pct\": %d, \"h_pct\": %d\n", w_pct, h_pct);
                    # fprintf(msgFile, "}");
                
                msg_json_path = os.path.join(self.appdata_dir, "current_msg.json")
                if os.path.exists(msg_json_path):
                    import json
                    with open(msg_json_path, "r", encoding="cp1252") as f:
                        data = json.load(f)
                    os.remove(msg_json_path)

                    msgData = data.copy()       #DEFAULT_INLINE_MSG.copy()
                    msgData["html"]     = f"<p> style='font-size: 12pt;'> {msgData["html"]} </p>"

                    #self.render_inline_macro_msg(data)
                    # FIX: Broadcast via signal instead of running the layout function directly
                    self.request_inline_msg_ui.emit(msgData)
                    
            except Exception as e:
                self.update_progress_log(f"⚠️ Error displaying message window: {e}") 

    def render_inline_macro_msg(self, data):
        """Runs safely on the Main UI Thread via the queued signal channel."""
        try:  
            if gLogging: logger.info(f"Create inline WP progress dialog: {data['title']}")
            # 1. THE OVERLAP FIX: If a dialogue exists, close it immediately 
            # to clear the text-block formatting queues
            if hasattr(self, 'current_inline_dialogue') and self.current_inline_dialogue:
                try:
                    self.current_inline_dialogue.close()
                    #self.current_inline_dialogue.deleteLater() # Force memory cleanup
                except Exception:
                    pass
            if gLogging: logger.info(f"Previous dialog cleanup: {data['title']}")
            # 2. Attach the NEW instance directly to the main UI class variable
            # Passing 'None' ensures it behaves as a clean independent window layer
            self.current_inline_dialogue = QDialog(None) 
            self.current_inline_dialogue.setWindowTitle(data["title"])
            
            # Calculate dynamic size variables based on display metrics
            screen_geo = QApplication.desktop().screenGeometry(self)
            width = int(screen_geo.width() * (data["w_pct"] / 100.0))
            height = int(screen_geo.height() * (data["h_pct"] / 100.0))
            self.current_inline_dialogue.setFixedSize(width, height)
            self.current_inline_dialogue.move(data["x"], data["y"])
            if gLogging: logger.info(f"Inline dialogue size: {data["x"]}, {data["y"]}")            

            # Apply top-level overlay window flags
            if gLogging: logger.info(f"Inline dialogue ontop: {data["ontop"]}")            
            flags = Qt.Tool
            if data["ontop"] == 1 or True:
                flags |= Qt.WindowStaysOnTopHint
            self.current_inline_dialogue.setWindowFlags(
                self.current_inline_dialogue.windowFlags() | flags)

            layout = QVBoxLayout(self.current_inline_dialogue)
            browser = QTextBrowser(self.current_inline_dialogue)
            
            # Inject the HTML formatting safely
            html_payload = data["html"].replace("%_vQuoteChar%", '"')
            # wrap text in size element
            #<p style="font-size: 1rem;">  This is simple body text. </p>
            if data["style"] != "":
                html_payload = f"<p style='{data["style"]}'> {html_payload} </p> "
            else:             
                html_payload = f"<p style='font-size: 1rem;'> {html_payload} </p> "
            if gLogging: logger.info(html_payload)   

            browser.setHtml(html_payload)
            layout.addWidget(browser)

            # Handle OK button logic (buttons=1)
            if data["buttons"] == 1:
                btn_ok = QPushButton("OK", self.current_inline_dialogue)
                btn_ok.setFixedWidth(80)
                btn_ok.clicked.connect(self.current_inline_dialogue.accept)
                layout.addWidget(btn_ok, alignment=Qt.AlignLeft)

            # Handle message display timeout (timeout_sec > 0)
            if data["timeout"] > 0:
                QTimer.singleShot(data["timeout"] * 1000, self.current_inline_dialogue.accept)

            # Render the fresh window overlay cleanly
            self.current_inline_dialogue.show() 
            if gLogging: logger.info(f"inline WP progress dialog complete")
        except Exception as e:
            self.update_progress_log(f"⚠️ Error, inline msg: {e}") 

    def show_html_waypoint_dialogue(self, phase_number):
        #return f'<msg>({x},{y},"{safe_html}","{title}",1,{timeout},0,1,25%,45%)'

        w_pct = 20
        h_pct = 40  
        title = f"VFE Waypoint Summary - Phase {phase_number}"

        """Launches a non-blocking overlay framework containing raw layout streams."""
        
        dialogue = wplistDialog(title, self.msg_html_waypoints[phase_number - 1],
                                w_pct, h_pct
                                )
    
        #dialogue.setFixedSize(480, 320)
        # Set orientation position
        dialogue.move(200, 200)

        # USE EXEC_ FOR PERSISTENCE: 
        # .exec_() halts execution on this thread and keeps the window open 
        # explicitly until the user clicks 'OK' or presses Esc. 
        # (Unlike .show(), it won't vanish or timeout automatically)

        dialogue.exec_() # Launches safe dialog loop execution tree

    
    def show_html_waypoint_dialogueOrig(self, phase_number):
        #return f'<msg>({x},{y},"{safe_html}","{title}",1,{timeout},0,1,25%,45%)'

        #self.wpD = wplistDialog(self.msg_html_waypoints[phase_number - 1])
        w_pct = 20
        h_pct = 40
        """Launches a non-blocking overlay framework containing raw layout streams."""
        dialogue = QDialog(self)
        self.wpD.setWindowTitle(f"VFE Waypoint Summary - Phase {phase_number}")

        # Calculate dynamic pixel size based on user's current display width percentage
        screen_geo = QApplication.desktop().screenGeometry(self)
        width = int(screen_geo.width() * (w_pct / 100.0))
        height = int(screen_geo.height() * (h_pct / 100.0))
        dialogue.setMinimumSize(width, height)        
        #dialogue.setFixedSize(480, 320)
        # Set orientation position
        dialogue.move(200, 200)
        
        # Forces window on top of MSFS without pulling desktop system input focus
        dialogue.setWindowFlags(dialogue.windowFlags() | 
                                Qt.WindowStaysOnTopHint | 
                                Qt.Tool ) 
                                #Qt.WindowTransparentForInput)
        
        layout = QVBoxLayout(dialogue)
        browser = QTextBrowser(dialogue)
        
        # Load string stream directly or use a default baseline fallback framework
        html_content = self.msg_html_waypoints[phase_number - 1]
        # html_content = self.waypoint_html_data.get(
        #     wp_number, 
        #     f"<html><body style='background:#121212;color:white;'><h3>Leg {wp_number}</h3>No active telemetry logged.</body></html>"
        # )
        
        browser.setHtml(html_content)
        layout.addWidget(browser)
        # NATIVE BUTTON ASSEMBLY: HTML string does not need an 'OK' link
        btn_ok = QPushButton("OK", dialogue)
        btn_ok.setFixedWidth(80)
        
        # dialogue.accept closes the dialogue box and ends the loop cleanly
        btn_ok.clicked.connect(dialogue.accept) 
        
        # Place button at the bottom left as specified
        layout.addWidget(btn_ok, alignment=Qt.AlignLeft)

        # USE EXEC_ FOR PERSISTENCE: 
        # .exec_() halts execution on this thread and keeps the window open 
        # explicitly until the user clicks 'OK' or presses Esc. 
        # (Unlike .show(), it won't vanish or timeout automatically)

        dialogue.exec_() # Launches safe dialog loop execution tree

# ============================================================================

    def load_settings(self, filename="settings.json"):
        try:
            settingsfile = os.path.join(self.appdata_dir,filename)
            with open(settingsfile, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}  # Return empty dict if file doesn't exist yet

    def save_settings(self, data, filename="settings.json"):
        settingsfile = os.path.join(self.appdata_dir,filename)
        with open(settingsfile, "w") as f:
            json.dump(data, f, indent=4)  # indent=4 makes it easy for humans to read

    def start_processing(self):
        self.worker.is_cancelled = False
        self.worker.start()
    def stop_processing(self):
        if self.worker.isRunning():
            self.worker.cancel()
            self.update_progress_log("Interrupted: Cancelled by User")

    def capture_hotkey(self):
        # --- NEW: PURGE BUFFER ---
        # 1. Clear any stuck keys or ghosting events in the library
        global_kb.stash_state() 
        
        # 2. Force wait for all physical keys to be UP
        # This prevents 'leaking' from the previous button click
        while any(global_kb._pressed_events.values()):
            time.sleep(0.05)
        # -------------------------        
        # Capture the full hotkey string
        # suppress=True prevents the key from 'typing' into Windows
        hotkey = global_kb.read_hotkey(suppress=True)
        return hotkey

    def initUI(self):
        """Initialize and layout all UI components."""
        self.ui_instance = self
        self.setWindowTitle(f"Virtual Flight Engineer v{__version__}")
        self.setGeometry(100, 100, 700, 800)
        # Resolve absolute path to ensure the icon loads reliably
        icon_path = os.path.join(os.path.dirname(__file__), "vfe.ico")
        
        # Apply the icon to the title bar
        self.setWindowIcon(QIcon(icon_path))        

        # Replace QShortcut with a Global Hotkey
        # 'suppress=False' allows the game to still see the keys if needed
        # VFEtray traps interrupt
        #global_kb.add_hotkey('shift+esc', self.stop_processing, suppress=True)

        # Main widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout()
        
        # === GROUP 1: LOAD FLIGHT PLAN ===
        group1_widget = self.create_group1_load_flightplan()
        self.main_layout.addWidget(group1_widget)
        
        # === GROUP 2: CAPTURE / HOTKEY CONTROLS ===
        group2_widget = self.create_group2_capture_hotkey()
        self.main_layout.addWidget(group2_widget)
        
        # === GROUP 3: CALIBRATION ===
        group3_widget = self.create_group3_calibration()
        self.main_layout.addWidget(group3_widget)
        
        # === GROUP 4: SIMCONNECT TELEMETRY ===
        group4_widget = self.create_group4_simconnect_telemetry()
        self.main_layout.addWidget(group4_widget)
        
        # === GROUP 5: CONNECTION & EXIT ===
        group5_widget = self.create_group5_connection_exit()
        self.main_layout.addWidget(group5_widget)
        
        central_widget.setLayout(self.main_layout)
        

        # shrink ui to control size
        self.adjustSize()

        # worker signals listener..
        self.worker.status_changed.connect(self.update_progress_log) 

        # Restore groups collapsed state from settings
        groups = [self.group2, self.group3, self.group4, self.group5]
        saved_states = self.settings.get("collapsed_states", {})

        for group in groups:
            name = group.objectName()
            # Default to True (Expanded) if not found in settings
            is_expanded = saved_states.get(name, True)
            
            # Block signals briefly so the window doesn't flicker/resize 5 times
            group.blockSignals(True)
            group.setChecked(is_expanded)
            
            # Manually apply the visibility logic once
            layout = group.layout()
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w: w.setVisible(is_expanded)
            group.setMaximumHeight(16777215) if is_expanded else group.setMaximumHeight(30)
            
            group.blockSignals(False)

        # One final resize to fit the restored states
                # 3. FORCE WINDOW SHRINK (The Magic Sequence)
        self.setMinimumHeight(0)    # Allow the window to be small
        self.main_layout.activate() # Recalculate layout logic
        self.adjustSize()           # Snap window to new content height
        #force on top to allow calibration
        flags = self.windowFlags()
        flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        # Start background check for MSFS
        # Create the background timer
        self.sim_check_timer = QTimer(self)
        self.sim_check_timer.timeout.connect(self.check_sim_status)
        # Start checking every 5 seconds (5000 ms)
        self.sim_check_timer.start(5000)
        # Track status to avoid spamming the log
        self.sim_was_running = False
        self.simconnect_was_running = False

        
        # Import existing defined flight plan file on start...
        self.load_flight_plan_import(self.loaded_flight_plan)
        
    def create_group1_load_flightplan(self):
        """
        Group 1: Load Flight Plan
        - Load Flight Plan button
        - Filename display field
        """
         # group1 title
        group = QGroupBox("Group 1: Load Flight Plan")
        group.setStyleSheet("QGroupBox::title { color: orange; font:}")
        # dont expand group on win resize
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # Load plan line
        main_layout = QVBoxLayout()
        layoutL1 = QHBoxLayout()
        btn_load = QPushButton("Import Flight Plan")
        btn_load.clicked.connect(self.on_load_flight_plan)
        self.txt_filename = QLineEdit()
        self.txt_filename.setReadOnly(True)
        if self.loaded_flight_plan:
            self.txt_filename.setText(os.path.basename(self.loaded_flight_plan))
        else:
            self.txt_filename.setPlaceholderText("No flight plan loaded")
        layoutL1.addWidget(btn_load)
        layoutL1.addWidget(QLabel("File:"))
        layoutL1.addWidget(self.txt_filename, stretch=1)
        main_layout.addLayout(layoutL1)

        # Proess plan line and progress box
        layoutL2 = QHBoxLayout()
        btn_load = QPushButton("Process\n Flight Plan\n(arm hotkeys)")
        btn_load.clicked.connect(self.on_process_flight_plan)
        self.logProgressBox = QPlainTextEdit()
        self.logProgressBox.setReadOnly(True)
        self.logProgressBox.setFixedHeight(70) 
        self.logProgressBox.setPlaceholderText("pending...")
        layoutL2.addWidget(btn_load)
        layoutL2.addWidget(self.logProgressBox, stretch=1)
        main_layout.addLayout(layoutL2)

        group.setLayout(main_layout)
        return group
    
    def create_group2_capture_hotkey(self):
        """
        Group 2: Capture/Hotkey Controls
        - Global wait time configuration
        - Capture button
        - Display fields for hotkeys:
          - Load flight phase hotkey
          - Show waypoints hotkey
        """
        self.group2 = QGroupBox("Group 2: Capture & Hotkey Controls")
        self.group2.setObjectName("group2")
        # ... do this for all groups        
        self.group2.setCheckable(True)
        self.group2.setChecked(True)
        self.group2.setStyleSheet("QGroupBox::title { color: orange; }")
        # dont expand group on win resize
        self.group2.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # 2. Connect the toggle to a function
        self.group2.toggled.connect(self.on_group_toggle)
        layout = QVBoxLayout()
        
        # Global wait time (from civa_calibrate.py lines 79-82)
        wait_time_layout = QHBoxLayout()
        wait_time_layout.addWidget(QLabel("Global Wait Time (ms):"))
        self.txt_global_wait = QLineEdit()
        self.txt_global_wait.setText(str(self.global_wait))  # Default value
        self.txt_global_wait.setMaximumWidth(100)
        self.txt_global_wait.editingFinished.connect(self.on_wait_time_changed)
        wait_time_layout.addWidget(self.txt_global_wait)
        wait_time_layout.addWidget(QLabel("(minimum: 100ms)"))
        wait_time_layout.addStretch()
        layout.addLayout(wait_time_layout)
        
        # Capture phase button and status
        phase_layout = QHBoxLayout()

        self.btn_record_phase = QPushButton("Capture Phase Hotkey")
        self.btn_record_phase.clicked.connect(self.on_capture_phase_hotkey)
        self.lbl_phase_capture_status = QLabel("Ready to capture phase 1 hotkey")
        
        phase_layout.addWidget(self.btn_record_phase)
        phase_layout.addWidget(self.lbl_phase_capture_status, stretch=1)
        
        # Capture display wp button and status
        waypoint_layout = QHBoxLayout()

        self.btn_record_waypoint = QPushButton("Capture Waypoint Hotkey")
        self.btn_record_waypoint.clicked.connect(self.on_capture_waypoint_hotkey)
        self.lbl_waypoint_capture_status = QLabel("Ready to capture waypoint hotkey")
        
        waypoint_layout.addWidget(self.btn_record_waypoint)
        waypoint_layout.addWidget(self.lbl_waypoint_capture_status, stretch=1)

        layout.addLayout(phase_layout)
        layout.addLayout(waypoint_layout)
        
        self.group2.setLayout(layout)
        return self.group2
    
    def create_group3_calibration(self):
        """
        Group 3: Calibration
        - Calibrate button
        - Status indicator (red/green)
        - Prompt text for calibration steps
        """
        self.group3 = QGroupBox("Group 3: Calibration")
        self.group3.setObjectName("group3")
        self.group3.setCheckable(True)
        self.group3.setChecked(True)        
        self.group3.setStyleSheet("QGroupBox::title { color: orange; }")
        # dont expand group on win resize
        self.group3.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # 2. Connect the toggle to a function
        self.group3.toggled.connect(self.on_group_toggle)
        layout = QVBoxLayout()
        
        button_layout = QHBoxLayout()
        self.btn_calibrate = QPushButton("Run Calibration")
        self.btn_calibrate.clicked.connect(self.on_confirm_save)
        
        self.lbl_calibration_status = QLabel("Status: Uncalibrated")
        self.lbl_calibration_status.setStyleSheet("background-color: red; padding: 5px; border-radius: 3px; color: white; font-weight: bold;")
        
        button_layout.addWidget(self.btn_calibrate)
        button_layout.addWidget(QLabel("Calibration:"))
        button_layout.addWidget(self.lbl_calibration_status, stretch=1)
        
        self.lbl_calibration_prompt = QLabel("Ready for calibration")
        self.lbl_calibration_prompt.setStyleSheet("font-weight: bold; margin-top: 4px;")
        self.btn_stop_reset = QPushButton("Stop/reset")
        self.btn_stop_reset.clicked.connect(self.on_stop_reset)
        
        prompt_layout = QHBoxLayout()
        prompt_layout.addWidget(self.lbl_calibration_prompt, stretch=1)
        prompt_layout.addWidget(self.btn_stop_reset)
        
        layout.addLayout(button_layout)
        layout.addLayout(prompt_layout)
        
        self.group3.setLayout(layout)
        return self.group3
    
    def create_group4_simconnect_telemetry(self):
        """
        Group 4: Simconnect Telemetry
        - Display fields for:
          - INS next waypoint
          - Current heading
          - Current altitude
          - Ground speed
          - Other relevant telemetry
        """
        self.group4 = QGroupBox("Group 4: Simconnect Telemetry (INS Monitoring)")
        self.group4.setObjectName("group4")

        self.group4.setCheckable(True)
        self.group4.setChecked(True)            
        self.group4.setStyleSheet("QGroupBox::title { color: orange; }")
        # dont expand group on win resize
        self.group4.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # 2. Connect the toggle to a function
        self.group4.toggled.connect(self.on_group_toggle)
        layout = QVBoxLayout()
        
        # Create telemetry display fields
        telemetry_grid = QVBoxLayout()
        
        self.lbl_ins_waypoint = QLabel("INS Next Waypoint: --")
        #self.lbl_current_heading = QLabel("Current Heading: -- °")
        self.lbl_current_altitude = QLabel("Current Altitude: -- ft")
        self.lbl_ground_speed = QLabel("Ground Speed: -- kts")
        self.lbl_latlng = QLabel("Latitude:   Longitude:")
        
          
        #self.lbl_simconnect_info = QLabel("Simconnect Status: Disconnected")
        # threaded progress..
        self.progressBar = QProgressBar(self)
        #self.lbl_statusLabel = QLabel("Ready", self)

        telemetry_grid.addWidget(self.lbl_ins_waypoint)
        #telemetry_grid.addWidget(self.lbl_current_heading)
        telemetry_grid.addWidget(self.lbl_current_altitude)
        telemetry_grid.addWidget(self.lbl_ground_speed)
        telemetry_grid.addWidget(self.lbl_latlng)
        #telemetry_grid.addWidget(self.lbl_simconnect_info)
        telemetry_grid.addWidget(self.progressBar)
        #telemetry_grid.addWidget(self.lbl_statusLabel)
        layout.addLayout(telemetry_grid)
        
        self.group4.setLayout(layout)
        return self.group4
    
    def create_group5_connection_exit(self):
        """
        Group 5: Connection & Exit Controls
        - Check Simconnect connection button
        - MSFS running status indicator
        - Simconnect connected status indicator
        - Exit application button
        """
        self.group5 = QGroupBox("Group 5: System Status & Exit")
        self.group5.setObjectName("group5")

        self.group5.setCheckable(True)
        self.group5.setChecked(True)            

        self.group5.setStyleSheet("QGroupBox::title { color: orange; }")
        # dont expand group on win resize
        self.group5.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # 2. Connect the toggle to a function
        self.group5.toggled.connect(self.on_group_toggle)

        layout = QVBoxLayout()
        
        # Connection check button
        check_layout = QHBoxLayout()
        btn_check_conn = QPushButton("Check Simconnect Connection")
        btn_check_conn.clicked.connect(self.on_check_simconnect)
        check_layout.addWidget(btn_check_conn)
        
        # Status indicators
        status_layout = QHBoxLayout()
        
        self.lbl_msfs_status = QLabel("MSFS: Not Running")
        self.lbl_msfs_status.setStyleSheet("background-color: red; padding: 5px; border-radius: 3px; color: white;")
        
        self.lbl_simconnect_status = QLabel("Simconnect: Disconnected")
        self.lbl_simconnect_status.setStyleSheet("background-color: red; padding: 5px; border-radius: 3px; color: white;")
        
        status_layout.addWidget(self.lbl_msfs_status)
        status_layout.addWidget(self.lbl_simconnect_status)
        
        # Exit button
        btn_exit = QPushButton("Exit Application")
        btn_exit.clicked.connect(self.on_exit_app)
        btn_exit.setStyleSheet("background-color: #ff6b6b; color: white; padding: 8px;")
        
        layout.addLayout(check_layout)
        layout.addLayout(status_layout)
        layout.addWidget(btn_exit)
        
        self.group5.setLayout(layout)
        return self.group5
    
    def on_group_toggle(self, is_checked):

        # 1. Hide/Show all widgets inside the layout
        # This prevents the GroupBox from leaving a "ghost" empty space
        group = self.sender()
        name = group.objectName()
        # 1. Update the local settings dictionary
        # Assuming self.settings is your JSON-loaded dict
        if "collapsed_states" not in self.settings:
            self.settings["collapsed_states"] = {}
        self.settings["collapsed_states"][name] = is_checked

        layout = group.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i).widget()
            if item:
                item.setVisible(is_checked)
        
        #self.main_layout.activate()

        # 2. Update the GroupBox height
        # If hidden, set a small fixed height to 'collapse' the border
        if not is_checked:
            group.setMaximumHeight(30) # Height of the title bar
        else:
            group.setMaximumHeight(16777215) # Standard QWidget limit

        # 3. FORCE WINDOW SHRINK (The Magic Sequence)
        self.setMinimumHeight(0)    # Allow the window to be small
        self.main_layout.activate() # Recalculate layout logic
        self.adjustSize()           # Snap window to new content height
        # 4. Optional: Save to file immediately
        self.save_settings(self.settings) 

    # 2. Define the update function
    def on_wait_time_changed(self):
        new_text = self.txt_global_wait.text()
        try:
            # Update your variable
            self.global_wait = int(new_text)
            self.update_progress_log(f"VFE: Global wait updated to {self.global_wait}s")

            # Save to settings immediately
            self.settings["global_wait"] = self.global_wait
            self.save_settings(self.settings)
        except ValueError:
            # Reset to last known good value if input is invalid
            self.txt_global_wait.setText(str(self.global_wait))
            self.statusLabel.setText("⚠️ Invalid number format")

    def check_sim_status(self):
        target_exe = "FlightSimulator2024.exe"
        is_running = is_process_running(target_exe) # Using the psutil function

        if is_running and not self.sim_was_running:
            self.update_progress_log(f"🎮 {target_exe} detected. Ready to Arm.")
            self.lbl_msfs_status.setText("MSFS status: Running")
            self.lbl_msfs_status.setStyleSheet("color: lime;")
            self.sim_was_running = True
            
        elif not is_running and self.sim_was_running:
            self.update_progress_log(f"❌ {target_exe} closed. Hotkeys disarmed.")
            self.lbl_msfs_status.setText("SIM STATUS: NOT FOUND")
            self.lbl_msfs_status.setStyleSheet("color: red;")
            self.sim_was_running = False
            # Safety: Disarm keys if sim closes
            global_kb.unhook_all() 

    # ========================================================================
    # CALLBACK FUNCTIONS
    # ========================================================================
    def on_phase_triggered(self, phase_num):
        if not self.macro_lock.acquire(blocking=False):
            self.worker.status_changed.emit(f"VFE: Macro already running.")
            return
        
        if gLogging: logger.info(f"Phase hotkey triggered: Phase {phase_num}")
        self.worker.status_changed.emit(f"VFE: Starting Phase {phase_num} Load...")
        try:
            self.worker.run(phase_num)
        finally:
            # 2. Always release in a 'finally' block
            self.macro_lock.release()
        return

    def on_waypoint_info_triggered(self, wp_num):
        # Lookup name from your data structure
        name = self.get_waypoint_name(wp_num) 
        self.statusLabel.setText(f"WP {wp_num}: {name}")
        
    def on_load_flight_plan(self):
        """Handle Load Flight Plan button click."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Flight Plan File",
            "",
            "Flight Plans (*.pln);;XML Files (*.xml);;All Files (*)"
        )
        
        if file_path:
            self.load_flight_plan_import(file_path)
            
    def load_flight_plan_import(self, file_path):
        if file_path:
            if os.path.exists(file_path):
                self.flight_plan_path = file_path
                self.loaded_flight_plan = file_path
                filename = os.path.basename(file_path)
                self.txt_filename.setText(filename)
                # QMessageBox.information(self, "Flight Plan Loaded", f"Loaded: {filename}")
                # TODO: Parse and process flight plan here
                self.flight_plan.current_plan = load_flight_plan_file(self, file_path)
                fp = self.flight_plan.current_plan
                if fp:
                    self.update_progress_log("")
                    self.update_progress_log(f"✅ Imported flight plan: {filename}\nDeparture: {fp.departure} → Destination: {fp.destination}\n Total Waypoints: {len(fp.phases)*9}, Ready to process...")
            else:        
                self.update_progress_log(f"❌ Existing file not found: {file_path}")
                
    def on_process_flight_plan(self):
        """Handle process Flight Plan button click."""
        # TODO: Parse and process flight plan here
        if process_flight_plan(self):
            # arm hotkey listeners
            # (macros already written)
            #self.export_vfe_macros(self.flight_plan.current_plan) # Pass parsed data object
            #hotkey arm            
            self.flight_plan.bind_all_sequences()
            self.update_progress_log(f"✅ Armed hotkeys for MSFS load")  # Clear log"")
            self.update_progress_log(f"⚠️ Ensure waypoint selector on 0 before phase load.")  # Clear log"")

    def on_capture_phase_hotkey(self):
        """Handle Capture Phase Hotkey button click"""
        # Validate global wait time as well
        try:
            wait_value = int(self.txt_global_wait.text())
            if wait_value < 100:
                wait_value = 100
                self.txt_global_wait.setText("100")
                QMessageBox.warning(self, "Wait Time Too Small", "Global wait time set to minimum: 100ms")
        except ValueError:
                self.txt_global_wait.setText("200")
                QMessageBox.warning(self, "Invalid Input", "Invalid wait time. Reset to 200ms")
                return        

        # Disable button and update status
        self.btn_record_phase.setEnabled(False)
        self.lbl_phase_capture_status.setText("Recording... (e.g. Ctrl+Shift+1)")
        QApplication.processEvents() # Ensure the label updates
        
        raw = self.capture_hotkey()
        self.phase_hotkey = self.normalize_hotkey(raw)
        self.lbl_phase_capture_status.setText(f"✅ Phase: {self.phase_hotkey}")
        
        self.btn_record_phase.setEnabled(True)
        # Saved on exit from self.phase_hotkey
        self.settings["global_wait"]  = self.global_wait
        self.settings["phase_hotkey"] = self.phase_hotkey


    def on_capture_waypoint_hotkey(self):
        self.btn_record_waypoint.setEnabled(False)
        self.lbl_waypoint_capture_status.setText("Recording... (e.g. Ctrl+Shift+F1)")
        QApplication.processEvents()
        
        raw = self.capture_hotkey()
        self.waypoint_hotkey = self.normalize_hotkey(raw)
        self.lbl_waypoint_capture_status.setText(f"✅ Waypoint: {self.waypoint_hotkey}")
        self.settings["waypoint_hotkey"] = self.waypoint_hotkey
        self.btn_record_waypoint.setEnabled(True)

    def on_confirm_save(self):
        """Handle Confirm Save button click."""
        # If calibration is already running, this acts as the save confirmation trigger.
        if self.calibration_worker and self.calibration_worker.isRunning():
            if hasattr(self.calibration_worker, 'user_clicked_event') and self.calibration_worker.user_clicked_event:
                self.calibration_worker.user_clicked_event.action = 'save'
                self.calibration_worker.user_clicked_event.set()
                self.lbl_calibration_prompt.setText('Save confirmed. Finalizing calibration...')
                self.btn_calibrate.setEnabled(False)
            else:
                QMessageBox.warning(self, 'Calibration Error', 'Calibration event is not available.')
            return

        response = QMessageBox.question(
            self,
            'Start Calibration',
            'This will launch the calibration script.\nEnsure MSFS is running and zoomed to CIVA unit.\nContinue?'
        )
        if response != QMessageBox.Yes:
            return

        if self.calibration_worker and self.calibration_worker.isRunning():
            QMessageBox.warning(self, 'Calibration Busy', 'Calibration is already running.')
            return

        self.lbl_calibration_prompt.setText('Calibration started. Follow the terminal prompts.')
        winsound.Beep(1000, 150)
        self.btn_calibrate.setText('Confirm Save')
        self.btn_calibrate.setEnabled(True)

        global_wait = self.txt_global_wait.text()

        self.calibration_worker = CalibrationWorker(self, global_wait)
        self.calibration_worker.statusChanged.connect(self.lbl_calibration_prompt.setText)
        self.calibration_worker.finished.connect(self.on_calibration_finished)
        self.calibration_worker.start()

    def on_stop_reset(self):
        """Handle Stop/reset button click."""
        self.calibration_status = False
        self.update_calibration_status()
        self.lbl_calibration_prompt.setText("Calibration stopped. Status reset to uncalibrated.")
        if self.calibration_worker and self.calibration_worker.isRunning():
            if hasattr(self.calibration_worker, 'user_clicked_event') and self.calibration_worker.user_clicked_event:
                self.calibration_worker.user_clicked_event.action = 'stop'
                self.calibration_worker.user_clicked_event.set()
        self.btn_calibrate.setEnabled(True)
        self.btn_calibrate.setText('Run Calibration')

    def on_calibration_finished(self, saved: bool):
        self.btn_calibrate.setEnabled(True)
        self.btn_calibrate.setText('Run Calibration')
        self.calibration_path = os.path.join(self.appdata_dir, "CIVAinsCalibration.txt")
        if saved and os.path.exists(self.calibration_path):
            self.calibration_status = True
            self.update_calibration_status()
            self.lbl_calibration_prompt.setText("Calibration complete. File saved.")
            self.update_progress_log("Calibration completed successfully!")
            if gLogging: logger.info("Calibration completed and file saved.")
        
            # Define the exact window coordinates of INS display box
            # save waypoint selector scrn loc in settings..
            self.settings["waypoint_sel_loc"] = {}
            self.settings["waypoint_sel_loc"]["scn_x"] = self.waypoint_sel_x
            self.settings["waypoint_sel_loc"]["scn_y"] = self.waypoint_sel_y

            detected_digit = self.wp_tracker.capture_and_ocr_digit(self.ui_instance)
            if detected_digit in range(10):
                self.update_progress_log(f"✅ Waypoint selector digit check: {detected_digit}")
            else: 
                self.update_progress_log(f"⚠️ Waypoint selector digit not OCR readable")

        else:
            self.calibration_status = False
            self.update_calibration_status()
            self.lbl_calibration_prompt.setText("Calibration failed: file not created.")
            QMessageBox.warning(self, "Calibration Failed", "Calibration file was not created.")
            logger.warning("Calibration script ran but no calibration file was created.")
    
    def on_check_simconnect(self):
        """Handle Check Simconnect Connection button click."""
        # TODO: Implement Simconnect connection check
        try:
            is_running = self.simconnect.connect() # Using the psutil function

            if is_running and not self.simconnect_was_running:
                self.update_progress_log(f"🎮 SimConnect available.")
                self.lbl_simconnect_status.setText("SimConnect: Running")
                self.lbl_simconnect_status.setStyleSheet("color: lime;")
                self.simconnect_was_running = True
            elif not is_running and self.simconnect_was_running:
                self.update_progress_log(f"❌ SimConnect lost.")
                self.lbl_simconnect_status.setText("SimConnect: Disconnected")
                self.lbl_simconnect_status.setStyleSheet("color: red;")
                self.simconnect_was_running = False
            if is_running:
                scData = self.simconnect.get_aircraft_data()
                if scData:
                    if gLogging: logger.info(f"Simconnect Check: alt:{scData["alt"]}; gspd:{scData["spd"]}; lat:{scData["lat"]}; lng:{scData["lng"]} ")
                    self.update_telemetry("","",scData["alt"],scData["spd"], scData["lat"], scData["lng"] )

                    if gLogging: logger.info(scData.keys())                                
            else:
                logger.info("Simconnect connection failed")
        except Exception as e:
            logger.error(f"Failed to SimConnect: {e}")
    
    def on_exit_app(self):
        """Handle Exit Application button click."""
        response = QMessageBox.Yes
        #QMessageBox.question(
        #    self,
        #    "Exit Application",
        #    "Are you sure you want to exit?",
        #    QMessageBox.Yes | QMessageBox.No
        #)
        if response == QMessageBox.Yes:
            try:
                keyboard.unhook_all()
            except:
                pass
            try:
                global_kb.unhook_all()
            except:
                pass
            self.close()

    # ========================================================================
    # UI UPDATE FUNCTIONS
    # ========================================================================
    # region UI update functions for status indicators, telemetry fields, and progress log
    def update_progress_log(self, message):
        """Thread-safe entry point. Safe to call from ANY thread or worker loop."""
        # Broadcast the text safely across thread boundaries
        self.request_log_update.emit(message)

    def _safe_append_log(self, message):
        """Executes strictly on the Main UI Thread via the signal queue."""
        if message == "":
            self.logProgressBox.clear()
        else:
            self.logProgressBox.blockSignals(True)
            self.logProgressBox.appendPlainText(message)
            
            # Auto-scroll safely now that we are guaranteed to be on the Main Thread
            # Use ensureCursorVisible() as a cleaner, native alternative to manual scroll math
            self.logProgressBox.ensureCursorVisible()
            
            self.logProgressBox.blockSignals(False)


    def update_calibration_status(self):
        """Update calibration status indicator."""
        if self.calibration_status:
            self.lbl_calibration_status.setText("Status: Calibrated")
            self.lbl_calibration_status.setStyleSheet("background-color: green; padding: 5px; border-radius: 3px; color: white; font-weight: bold;")
        else:
            self.lbl_calibration_status.setText("Status: Uncalibrated")
            self.lbl_calibration_status.setStyleSheet("background-color: red; padding: 5px; border-radius: 3px; color: white; font-weight: bold;")
    
    def update_hotkey_status(self):
        """Update hotkey capture status indicators."""
        if self.phase_hotkey:
            self.lbl_phase_capture_status.setText(f"✅ Phase: {self.phase_hotkey}")
        else:
            self.lbl_phase_capture_status.setText("Ready to capture phase hotkey")
        
        if self.waypoint_hotkey:
            self.lbl_waypoint_capture_status.setText(f"✅ Waypoint: {self.waypoint_hotkey}")
        else:
            self.lbl_waypoint_capture_status.setText("Ready to capture waypoint hotkey")

    def update_msfs_status(self, running: bool):
        """Update MSFS running status indicator."""
        self.msfs_running = running
        if running:
            self.lbl_msfs_status.setText("MSFS: Running")
            self.lbl_msfs_status.setStyleSheet("background-color: green; padding: 5px; border-radius: 3px; color: white;")
        else:
            self.lbl_msfs_status.setText("MSFS: Not Running")
            self.lbl_msfs_status.setStyleSheet("background-color: red; padding: 5px; border-radius: 3px; color: white;")
    
    def update_simconnect_status(self, connected: bool):
        """Update Simconnect connection status indicator."""
        self.simconnect_connected = connected
        if connected:
            self.lbl_simconnect_status.setText("Simconnect: Connected")
            self.lbl_simconnect_status.setStyleSheet("background-color: green; padding: 5px; border-radius: 3px; color: white;")
        else:
            self.lbl_simconnect_status.setText("Simconnect: Disconnected")
            self.lbl_simconnect_status.setStyleSheet("background-color: red; padding: 5px; border-radius: 3px; color: white;")
    
    def update_telemetry(self, ins_waypoint="--", heading="--", altitude="--", groundspeed="--", lat="--", lng="--"):
        """Update telemetry display fields."""
        if self.teleticker == True: 
            tick = f"🟢"
            self.teleticker = False
        else: 
            tick = ""
            self.teleticker = True
        self.lbl_ins_waypoint.setText(f"{tick} INS Next Waypoint: {ins_waypoint}")
        #self.lbl_current_heading.setText(f"Current Heading: {heading} °")
        self.lbl_current_altitude.setText(f"Current Altitude: {altitude} ft")
        self.lbl_ground_speed.setText(f"Ground Speed: {groundspeed} kts")
        self.lbl_latlng.setText(f"Latitude: {lat} Longitude: {lng}")    

    def setup_telemetry_timer(self):
        """Setup periodic telemetry update timer (framework placeholder)."""
        # TODO: Implement actual Simconnect polling
        # For now, this is a placeholder for periodic updates
        self.teleticker = False
        self.telemetry_timer = QTimer()
        self.telemetry_timer.timeout.connect(self.poll_simconnect_data)
        # Start polling every 10sec when needed
        self.telemetry_timer.start(10000)
    
    def poll_simconnect_data(self):
        """Poll Simconnect for telemetry data (framework placeholder)."""
        # TODO: Implement actual Simconnect data retrieval
        if self.simconnect.connected:
            scData = self.simconnect.get_aircraft_data()
            if scData:
                # logger.info(f"Simconnect Check: alt:{scData["alt"]}; gspd:{scData["spd"]}; lat:{scData["lat"]}; lng:{scData["lng"]} ")
                self.update_telemetry("","",scData["alt"],scData["spd"], scData["lat"], scData["lng"] )
                #logger.info(scData.keys())
                #timer cycle 10 secs: Check progress against next phase and waypoint..
                if scData["spd"] > 50 or True:
                    # check current phase wps
                    self.checkPhaseProgress(scData["lat"], scData["lng"] )
        else:
            pass
    def checkPhaseProgress(self,curLat, curLng ):
        fp = self.flight_plan.current_plan  
                #....phases[0].waypoints[0].altitude
        navstatus = []
        phx = 1
        for phase in fp.phases:
            # no assumption on what phase is loaded to device
            # just use current location to determine phase:wpfrom-wpto
            wps = phase.waypoints
            nwp = len(phase.waypoints)
            # each phase has destination as last waypoint (wrong: dest has already been dropped).
            # for this check, only the last phase should include the last point
            #if (phx < len(fp.phases)):
            #    wps = wps[:-1]

            curloc = [curLat,curLng]
            coords = []
            for wp in wps:
                coords.append(SimpleNamespace(latitude=wp.latitude, longitude=wp.longitude))

            # Returns:
            # dict: {
            #     'flag': -1, 0, or 1,
            #     'from_idx': int:0-nwp-1 or None,
            #     'to_idx': int or None,
            #     'dist_to_to_pt_nm': float,
            #     'leg_length_nm': float
            # }
            navstatus.append (track_current_phase(coords, curloc))
            i = len(navstatus)
            nvs = navstatus[i-1]
            if gLogging: logger.info (f"for phase {i}: {nvs}")
            # Check for next phase load based on current location
            # 1. flag = 0 for this phase being active
            # 2. from_idx-to_idx is the last leg
            # 3. dist_to_to_pt_nm is less than 50nm
            # 4. dist_to_to_pt_nm is less than 1nm
            # 5. next phase hasnt been loaded

            ##TESTING
            #nvs["to_idx"] = nwp - 1
            #nvs["dist_to_to_pt_nm"] = 2

            if nvs["flag"] == 0 and nvs["to_idx"] + 1 == nwp and \
                nvs["dist_to_to_pt_nm"] < self.lastwpinfo_dist and \
                    self.lastwpwarn_clear == False:
                msgData = DEFAULT_INLINE_MSG.copy()
                msgData["html"]     = "⚠️: Approaching last waypoint"
                msgData["timeout"]  = 60
                if nvs["dist_to_to_pt_nm"] < self.lastwpwarn_dist:
                    msgData["html"] = "❗: At last waypoint. Load next phase"
                    self.lastwpwarn_clear = True

                # FIX: Broadcast via signal instead of running the layout function directly
                self.request_inline_msg_ui.emit(msgData)
                #self.render_inline_macro_msg(msgData)
            # next phase...
            phx += 1


    def normalize_hotkey(self, hotkey_str):
        # 1. Map shift-symbols to their base digits
        shift_map = {
            '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
            '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'
        }
        
        # 2. Split into individual keys
        parts = hotkey_str.split('+')
        new_parts = []
        
        for p in parts:
            # Remove 'left ' or 'right ' prefixes from modifiers
            clean_p = p.lower().replace('left ', '').replace('right ', '').strip()
            
            # Translate symbols (! -> 1)
            final_p = shift_map.get(clean_p, clean_p)
            
            # Add to list (F1 and num 1 remain as-is)
            new_parts.append(final_p)
            
        # 3. Join back together
        return "+".join(new_parts)
 
    #endregion

# ========================================================================
# Action phase listener and processor (hotkey triggered)
# ========================================================================
# def start_phase_listener(ui_instance):
#     # current phase
#     phaseix = 0
#     state = {"index": 0}
#     stateMsg = {"index": 0}
#     total = len(ui_instance.generated_phases)
#     key_stub = re.sub(r'\+[1-9]', '', ui_instance.chosen_key)
#     # Renamed to be generic
#     def on_hotkey_pressed(event):
#         if state["index"] < total:
#             try:
#                 file_path = ui_instance.generated_phases[state["index"]]
#                 with open(file_path, 'r') as f:
#                     pyperclip.copy(f.read())
                
#                 state["index"] += 1
#                 logger.info(f"-> [{state['index']}/{total}] COPIED: {os.path.basename(file_path)}")
#                 winsound.Beep(1000, 100)
#             except Exception as e:
#                 logger.error(f"Error: {e}")
#         else:
#             # change color on CMD window:
#             if stateMsg["index"] == 0:
#                 #os.system('color 0A')
#                 #logger.info("\n" + "="*50)            
#                 #logger.info(" Starting waypoint details Message set (ESC to exit)")
#                 #logger.info(" Tab to Macro Commander macro edit window for 'Waypoints 1' \n and hit F9 to copy first file")             
#                 pass         

#             if stateMsg["index"] < total:
#                 try:
#                     file_path = ui_instance.generated_WPmsg[stateMsg["index"]]
                    
#                     #ui_instance.select_phase(state["index"] + 1) #data.get("phase"))
#                     ui_instance.load_phase_to_civa(ui_instance, ui_instance.current_phase)

#                     stateMsg["index"] += 1
#                     logger.info(f"-> [{stateMsg['index']}/{total}] COPIED: {os.path.basename(file_path)}")
#                     winsound.Beep(1000, 100)
#                 except Exception as e:
#                     logger.error(f"Error: {e}")
#             else:
#                 logger.info("All phases completed! Press ESC to exit.")
#                 winsound.Beep(600, 150)
#                 #os.system('color 07')

#     # listen to each phase hotkey
#     for phaseix in ui_instance.generated_phases:
#         activ_key = key_stub + "+" + str(phaseix + 1)
#         global_kb.on_press_key(activ_key, on_hotkey_pressed)

#     # The "Keep-Alive" loop
#     try:
#         while True:
#             if global_kb.is_pressed('esc'):
#                 logger.info("ESC detected. Exiting phase listener.")
#                 break
#             time.sleep(1.0) # A longer sleep is fine and saves Windows resources
#     finally:
#         #global_kb.unhook_all()
#         #os.system('color 07')
#         logger.info("\n[ESC] detected. Hotkeys retained.")

def load_flight_plan_file(self, file_path: str) -> Dict[str, Any]:
    """Load a flight plan file."""
    try:
        plan = self.flight_plan.load_flight_plan(file_path)
        plan.summary =  {
            "success": True,
            "departure": plan.departure,
            "destination": plan.destination,
            "phases": [
                {
                    "number": p.number,
                    "from": p.from_icao,
                    "to": p.to_icao,
                    "waypoint_count": len(p.waypoints)
                }
                for p in plan.phases
            ],
            "total_waypoints": sum(len(p.waypoints) for p in plan.phases)
        }
        return plan
    except Exception as e:
        logger.error(f"Failed to load flight plan: {e}")
        return {"success": False, "error": str(e)}

def select_phase(self, phase_num: int) -> Dict[str, Any]:
    """Select a phase to display."""
    if not self.flight_plan.current_plan:
        return {"success": False, "error": "No flight plan loaded"}
    
    if phase_num < 1 or phase_num > len(self.flight_plan.current_plan.phases):
        return {"success": False, "error": "Invalid phase number"}
    
    self.current_phase = phase_num
    phase = self.flight_plan.current_plan.phases[phase_num - 1]
    
    # Mark oceanic waypoints
    accel = self.flight_plan.current_plan.accel_waypoint
    decel = self.flight_plan.current_plan.decel_waypoint
    is_oceanic = False
    
    waypoints = []
    for wp in phase.waypoints:
        if wp.name == accel:
            is_oceanic = True
        if wp.name == decel:
            is_oceanic = False
        
        waypoints.append({
            "id": wp.id,
            "name": wp.name,
            "altitude": wp.altitude,
            "oceanic": is_oceanic,
            "status": "loaded" if wp.loaded else "pending"
        })
    
    return {
        "success": True,
        "phase": phase_num,
        "waypoints": waypoints
    }

def load_phase_to_civa(self, phase_num: int) -> Dict[str, Any]:
    """
    Load a phase to CIVA INS using automation.
    This replaces the Macro Commander macro execution.
    """
    #if not self.flight_plan.waypoints:
    #    return {"success": False, "error": "No flight plan loaded"}
    try:
        if self.ui.is_loading:
            return {"success": False, "error": "Loading already in progress"}
        
        phase = self.ui.flight_plan.current_plan.phases[phase_num - 1]
        self.ui.is_loading = True
        self.ui.worker.isRunning = True
        set_focus_by_exe("FlightSimulator2024.exe", self.ui)

        # Set data selector to WAY PT
        self.ui.automation.set_data_selector("WAY PT")
        #Set auto-man selector to AUTO
        self.push_button("automan")

        if gLogging: 
            if gLogging: logger.info("Set data selector to WAY PT")
            self.status_changed.emit(f"Set data selector to WAY PT")
        set_focus_instant(self.ui)      # Enter each waypoint
        for wp in phase.waypoints:
            #self.status_changed.emit(f"Waypoint loading {wp.name}.")
            if not self.ui.automation.enter_waypoint(wp):
                # interrupted
                return {
                    "success": False,
                    "message": f"Interrupted at {wp.name} "
                }
            wp.loaded = True

        self.status_changed.emit(f"Completed waypoint loading for Phase {phase_num}.")
        self.lastwpwarn_clear = False       # arm next warning
       
        return {
            "success": True,
            "message": f"Phase {phase_num} loaded ({len(phase.waypoints)} waypoints)"
        }
    except Exception as e:
        logger.error(f"Phase load error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        self.ui.is_loading = False

def get_state(self) -> Dict[str, Any]:
    """Get current application state for UI."""
    return {"currentPhase": self.current_phase}

    #plan = self.flight_plan.current_plan
    
    #return {
        #"simConnected": self.simconnect.is_connected(),
        #"msfsRunning": self.msfs_running,
        #"departure": plan.departure if plan else "",
        #"destination": plan.destination if plan else "",
        #"position": f"{self.aircraft_state.latitude:.4f}, {self.aircraft_state.longitude:.4f}",
        #"groundSpeed": int(self.aircraft_state.ground_speed),
        #"heading": int(self.aircraft_state.heading),
        #"activeWaypoint": self.aircraft_state.active_waypoint,
        #"isLoading": self.is_loading
    #}
    
def clear(self):
    """Clear current flight plan."""
    self.flight_plan.current_plan = None
    self.current_phase = 0
    

# =============================================================================
# CIVA Button Automation (replaces Macro Commander)
# =============================================================================

class CivaButtonPusher:
    """
    Handles mouse and keyboard automation for CIVA INS button presses.
    Replaces Macro Commander macro files with direct Python automation.
    """
    
    def __init__(self, ui_instance, worker=None):
        #calibration_path: str, worker=None):
        self.worker = worker  # Reference to background thread
        self.ui = ui_instance  # Reference to main UI for status updates
        self.fp = self.ui.flight_plan
        self.fp.calibration_data = {}
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.click_delay = 0.1  # seconds between clicks
        self.load_calibration()
    
    def load_calibration(self):
        """Load calibration data from file."""
        if os.path.exists(self.ui.calibration_path):        
            try:
                with open(self.ui.calibration_path, 'r') as f:
                    current_button = None
                    for line in f:
                        clean_line = line.strip()
                        if clean_line.startswith("<#>"):
                            current_button = clean_line[3:].strip().lower()
                            self.fp.calibration_data[current_button] = []
                        elif current_button:
                            self.fp.calibration_data[current_button].append(clean_line)
                self.ui.update_progress_log(f"Loaded calibration: {len(self.fp.calibration_data)} buttons")
            except Exception as e:
                logger.error(f"Failed to load calibration: {e}")
    
    def push_button(self, name: str):
        """
        Push a CIVA button by name.
        Reads calibration data and performs mouse clicks at recorded positions.
        """
        button_name = str(name).lower()
        
        # 1. IMMEDIATE INTERRUPT CHECK
        if self.ui.worker and self.ui.worker.is_cancelled:
            #print(f"Stopping: {label} push aborted.")
            return False

        # 2. UPDATE UI VIA WORKER SIGNAL
        #if self.worker:
        #    self.worker.status_changed.emit(f"Pushing {button_name}...")
     
        commands = self.fp.calibration_data.get(button_name, [])
        
        if not commands:
            logger.warning(f"Button '{name}' not found in calibration")
            return

        if gLogging: logger.info(f"-> {name}: {commands}")        
        #set_focus_instant(self.ui)      # Enter each waypoint
        for cmd in commands:
            #if name == "waypoint selector": 
            #    logger.info(f"-> {name}: {cmd}")
            set_focus_instant(self.ui)      # Enter each waypoint
            self._execute_command(cmd)
            time.sleep(self.click_delay)       #..all delays coded

        #debug 
        #if name == "waypoint selector":
        #    self.ui.worker.is_cancelled = True
        return True
    
    def _execute_command(self, command: str):
        """Execute a single calibration command."""
        #set_focus_instant(self.ui)      # logger focus intercept!        
        command = command.strip()
        
        if command.startswith("<mm>"):
            # Mouse move
            self._parse_and_move(command)
        elif command.startswith("<mlbd>"):
            # Mouse left button down
            #self.mouse.press(Button.left)
            pyautogui.mouseDown(button='left')
            time.sleep(0.05)            
        elif command.startswith("<mlbu>"):
            # Mouse left button up
            pyautogui.mouseUp(button='left')
            time.sleep(0.05) 
        elif command.startswith("<mwheel_f>"):
            # Mouse wheel forward
            time.sleep(0.05)
            pyautogui.scroll(1)
            time.sleep(0.05)
        elif command.startswith("<mwheel_b>"):
            # Mouse wheel backward
            pyautogui.scroll(-1)
            time.sleep(0.05)    
        elif command.startswith("<wx>"):
            # Wait command
            wait_time = self._parse_wait(command) / 1000.0
            #logger.info(f"Waiting for {wait_time:.3f} seconds")
            if wait_time:
                time.sleep(wait_time)  # Convert ms to seconds
        elif command.startswith("<msg>"):
            # Message display - skip for automation
            pass
    
    def _parse_and_move(self, command: str):
        """Parse move command and move mouse."""
        # Format: <mm>(x,y,wait)<#>
        match = re.search(r'<mm>\((\d+),(\d+),(\d+)\)', command)
        # Check for interrupt before moving
        if self.worker and self.worker.is_cancelled:
            return
        if match:
            x = int(match.group(1))
            y = int(match.group(2))
            duration = int(match.group(3))
            #self.mouse.position = (x, y)
            # 1. Move the mouse (with duration so you can see it)
            pyautogui.moveTo(x, y, duration=duration/1000.0)  # duration in seconds
            #if wait_time:
            #    time.sleep(wait_time / 1000)  # Convert ms to seconds
    
    def _parse_wait(self, command: str) -> Optional[float]:
        """Parse wait time from command."""
        import re
        match = re.search(r'<wx>\((\d+),', command)
        return float(match.group(1)) if match else None
    
    def set_data_selector(self, position: str = "WAY PT"):
        """Set the data selector to specified position."""
        # This would implement the selector rotation logic
        # from the original reset_data_selector function
        pass
    
    def enter_waypoint(self, waypoint: Waypoint):
        """
        Enter a single waypoint into CIVA INS.
        Format: {waypoint selector}{insert}{longitude}{insert}{latitude}{insert}
        """
        # Convert to CIVA coordinate format
        lat_seq = self._format_coordinate(waypoint.latitude, True)
        lon_seq = self._format_coordinate(waypoint.longitude, False)
        
        # 1. Increment Waypoint Selector
        if not self.push_button("waypoint selector"): return False
      
        # 2. Enter Latitude
        if not self.push_button("insert"): return False
        for digit in lat_seq:
            if not self.push_button(digit): return False
        
        # 3. Enter Longitude
        if not self.push_button("insert"): return False
        for digit in lon_seq:
            if not self.push_button(digit): return False
        
        # 4. Final confirmation
        if not self.push_button("insert"): return False
        
        logger.info(f"Entered waypoint: {waypoint.name}")
        #set_focus_instant(self.ui)      # Enter each waypoint
        return True
    
    def _format_coordinate(self, coord: float, is_latitude: bool) -> str:
        """
        Format coordinate for CIVA INS entry.
        Latitude: CDDMMS (e.g., N38°44'55" -> 238455)
        Longitude: CDDDMMS (e.g., W90°22'12" -> 4090221)
        """
        if is_latitude:
            direction = "N" if coord >= 0 else "S"
            coord = abs(coord)
        else:
            direction = "E" if coord >= 0 else "W"
            coord = abs(coord)
        
        degrees = int(coord)
        minutes_float = (coord - degrees) * 60
        minutes = int(minutes_float)
        seconds = (minutes_float - minutes) * 60
        seconds_digit = int(seconds) // 10
        
        # Cardinal mapping
        card_map = {"N": "2", "S": "8", "E": "6", "W": "4"}
        cardinal = card_map[direction]
        
        if is_latitude:
            return cardinal + str(degrees).zfill(2) + str(minutes).zfill(2) + str(seconds_digit)
        else:
            return cardinal + str(degrees).zfill(3) + str(minutes).zfill(2) + str(seconds_digit)

# ============================================================================
# UTILITY FUNCTIONS - Original CIVA Processing
# ============================================================================
def is_process_running(exe_name):
    """Check if there is any running process that contains the given name."""
    for proc in psutil.process_iter(['name']):
        try:
            # Check if process name matches; .lower() handles case sensitivity
            if proc.info['name'] and proc.info['name'].lower() == exe_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def set_focus_instant(ui_instance):
    # 1. Bring window to front (Ignore ShowWindow if already visible)
    try:
        win32gui.SetForegroundWindow(ui_instance.msfs_hwnd)
    except Exception:
        # Sometimes Windows blocks SetForeground; this is a common bypass
        win32gui.BringWindowToTop(ui_instance.msfs_hwnd)

    # 2. THE "JIGGLE": Wake up the MSFS software cursor
    # We move 1 pixel and back. This is invisible to the user 
    # but forces the simulator to re-draw the cursor.
    pyautogui.moveRel(1, 0)
    pyautogui.moveRel(-1, 0)

def set_focus_by_exe(exe_name="FlightSimulator2024.exe", ui_instance=None):
    # 1. Find the PID of the exe
    pid = None
    for proc in psutil.process_iter(['name', 'pid']):
        if proc.info['name'].lower() == exe_name.lower():
            pid = proc.info['pid']
            break
    
    if not pid: return False

    # 2. Find the window handle (HWND) belonging to that PID
    def callback(hwnd, target_pid):
        if win32gui.IsWindowVisible(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == target_pid:
                # Found the main window!
                ui_instance.msfs_hwnd = hwnd
                if win32gui.IsIconic(hwnd): # If minimised
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return False # Stop iterating
        return True

    try:
        win32gui.EnumWindows(callback, pid)
        return True
    except Exception:
        return True # Callback returns False to stop, which throws an internal error

def clean_filename(name):
    """Removes characters not allowed in Windows filenames."""
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def get_write_handle(path):
    return open(path, 'w')

def get_icao(wp_node):
    """Extracts the ICAOIdent text from a waypoint node."""
    icao_node = wp_node.find(".//ICAOIdent")
    return icao_node.text if icao_node is not None else "UNK"

def get_global_icao(container, tag_name):
    """Finds ICAO in global nodes like DepartureID or DestinationID."""
    # First search for direct child, then deep search
    node = container.find(f".//{tag_name}")
    if node is not None:
        # If it has children (like DepartureDetails), look for ICAOIdent
        icao_child = node.find(".//ICAOIdent")
        if icao_child is not None: 
            return icao_child.text
        # Otherwise return the text of the node itself (like DepartureID)
        return node.text
    return None

# WPtablehdr = 
def getMsgHeader ():
#  return (' <msg>(100,100, \"<html>\n'
    return (' <html>\n'
              '<table style=%_vQuoteChar%width: 100%; height: 100%;'
              'background-color: Gainsboro; max-width: 700px; font-family: Verdana, sans-serif;  \n'
              'border-collapse: collapse; border: 1px solid #ccc; border-radius: 8px; \n'
              'table-layout: fixed; overflow: hidden; display: table;%_vQuoteChar%> \n'
              '<thead>\n'
              '<tr style=%_vQuoteChar%font-size: 14px;background-color: #2d3436; color: #ffffff;%_vQuoteChar%>\n'
              '<th style=%_vQuoteChar%padding: 14px; text-align: left; width: 40%; font-weight: bold;%_vQuoteChar%>Id</th>\n'
              '<th style=%_vQuoteChar%padding: 14px; text-align: left; width: 60%; font-weight: bold;%_vQuoteChar%>Name</th>\n'
              '<th style=%_vQuoteChar%padding: 14px; text-align: left; width: 40%; font-weight: bold;%_vQuoteChar%>Altitude</th>\n'
              '</tr>\n'
              '</thead>\n'
              '<tbody>\n')

# WPtablerow = 
def getMsgRow(ID, Name, Elev_ft, accel_name, decel_name, isOceanic):

    # If name matches accel_name
    # highlight the oceanic segment by colour and '*' on name for all segments
    # up to decel name
    text_clr = "#333"
    bkgnd = " style=%_vQuoteChar%font-size: 12px;background-color: Gainsboro;%_vQuoteChar%"
    if Name == accel_name:
        firstOceanic = " (Accel)"
    elif Name == decel_name:
        firstOceanic = " (Decel)"
    else: 
        firstOceanic = ""
    
    if isOceanic and Name == decel_name:
        isOceanic = False
    elif Name == accel_name or isOceanic:
        bkgnd = " style=%_vQuoteChar%font-size: 12px;background-color: #D6EEEE;%_vQuoteChar%"
        isOceanic = True


    return isOceanic, f"""
    <tr{bkgnd}>
      <td style=%_vQuoteChar%padding: 8px 14px; border-bottom: 1px solid #eee; color: #333;%_vQuoteChar%>{ID}{firstOceanic}</td>
      <td style=%_vQuoteChar%padding: 8px 14px; border-bottom: 1px solid #eee; color: {text_clr};%_vQuoteChar%>{Name}</td>
      <td style=%_vQuoteChar%padding: 8px 14px; border-bottom: 1px solid #eee; color: #333;%_vQuoteChar%>{Elev_ft}</td>
    </tr>
    """


# WPtableFooter = 
def getMsgFooter ():
  return ('</tbody>\n'
          '</table></html>\n')
#          '</table></html>\",\"CIVA Waypoints\",1,0,0,1, 25%,45%)\n')

# Read the phase macro files and setup handler to push on request
# to the MSFS cockpit UI
def process_flight_plan(ui_instance):
    global target_exe

    root = tk.Tk()
    root.withdraw()
    #This is a Macro Commander macro captured from a record session and annotated
    # It should be saved with, for example, a CTRL-SHIFT-0 hotkey
    # to allow for a quick check of saved CIVA INS MSFS view or after other changes
    # it also needs to be a txt file on disk for access from this script
    #script_dir = os.path.dirname(os.path.abspath(ui_instance.loaded_flight_plan))
    #calibration_path = os.path.join(script_dir, "CIVAinsCalibration.txt")

    # capture target exe to ensure directed macro output enabled
    #if messagebox.askyesno("Microsoft Flight Simulator Edition", 
    #    "Is the target application Microsoft Flight Simulator 2024? (Otherwise 2020 is assumed)"):
    target_exe = "flightsimulator2024.exe"
    #else:
    #    target_exe = "flightsimulator.exe"

    # eg EGLLKJFK_MFS_NoProc_23Apr26.pln
    source_path = ui_instance.loaded_flight_plan
    prg = lambda msg: ui_instance.update_progress_log(msg)
    if source_path == "":
        prg ("❌ Import Flight Plan first")
        return False    
    # macro output path
    target_macro_dir = ui_instance.appdata_dir
        
    include_icao = True 
        # messagebox.askyesno("Flightplan Filename Option", 
        # "Include Departure/Arrival ICAOs in the filename?\n\nFormat: root_FROM_TO_plnXX.pln")

    try:
        # Use a parser that preserves some structure but we will re-indent
        tree = ET.parse(source_path)
        xml_root = tree.getroot()
        fp_container = xml_root.find(".//FlightPlan.FlightPlan")

        # Extract Global ICAO info for naming
        dep_id = get_global_icao(xml_root, "DepartureID") or "DEP"
        dest_id = get_global_icao(xml_root, "DestinationID") or "ARR"

        header_nodes, waypoint_nodes, footer_nodes = [], [], []
        found_first_wp = found_footer_start = False

        for child in fp_container:
            tag = child.tag.split('}')[-1].lower()
            if "arrivaldetails" in tag or "approachdetails" in tag:
                found_footer_start = True
            
            if "atcwaypoint" in tag:
                waypoint_nodes.append(child)
                found_first_wp = True
            elif found_footer_start:
                footer_nodes.append(child)
            elif not found_first_wp:
                header_nodes.append(child)
            else:
                footer_nodes.append(child)

        source_dir = os.path.dirname(source_path)
        # eg EGLLKJFK_MFS_NoProc_22Apr26
        base_name, ext = os.path.splitext(os.path.basename(source_path))
        target_dir = os.path.join(source_dir, "PHASES")
        prg(f"Output to {target_dir} ")
        # OPTIONAL: get any PDF OFP output...
        # EGLLKJFK_PDF_23Apr26.pdf
        components = base_name.split("_")
        pdf_name = "_".join([components[0], "PDF"] + components[2:]) + ".pdf" 
        pdf_name = pdf_name.replace("_NoProc", "")
        
        pdf_path = os.path.join(source_dir, pdf_name)
        # Get any OFP remarks to mark acceleration and deceleration points which may differ to TOD
        accel_name, decel_name = Read_OFP_PDF (pdf_path)    
        # oceanic state preserved between phases  
        isOceanic = False        
         
        os.makedirs(target_dir, exist_ok=True)
        # Clean up only the specific CIVA Phase files from previous runs
        # This looks for any file matching "CIVA_Phase_###.txt"
        old_civa_files = glob.glob(os.path.join(target_macro_dir, "macro_p[0-9].txt"))
        for f_path in old_civa_files:
            try:
                os.remove(f_path)
            except OSError:
                pass # Ignore if file is locked or already gone

        # 2. Load calibration data once at the start
        # (Assumes parse_civa_calibration function is defined above)
        calibration_data = parse_civa_calibration(ui_instance.calibration_path)
        prg ("Loaded calibration data")
        chunk_size = 9
        total_chunks = (len(waypoint_nodes) + chunk_size - 1) // chunk_size
        
        # Process each civa_set
        for i in range(0, len(waypoint_nodes), chunk_size):
            phase_num = (i // chunk_size) + 1
            current_chunk = waypoint_nodes[i : i + chunk_size]
            
            # Name logic 
            from_name = dep_id if phase_num == 1 else get_icao(current_chunk[0])
            to_name = dest_id if phase_num == total_chunks else get_icao(current_chunk[-1])
            
            from_clean, to_clean = clean_filename(from_name), clean_filename(to_name)
            
            num_waypoints_in_this_phase = len(current_chunk)
        
            if include_icao:
                new_filename = f"{base_name}_{from_clean}_{to_clean}_pln{phase_num:03d}{ext}"
            else:
                new_filename = f"{base_name}_pln{phase_num:03d}{ext}"
            
            #split plan file...
            output_path = os.path.join(target_dir, new_filename)
            
            # Rebuild XML
            new_root = ET.Element(xml_root.tag, xml_root.attrib)
            for child in xml_root:
                if "FlightPlan.FlightPlan" not in child.tag:
                    new_root.append(ET.fromstring(ET.tostring(child)))

            new_fp = ET.SubElement(new_root, "FlightPlan.FlightPlan")
            for node in header_nodes: 
                new_fp.append(ET.fromstring(ET.tostring(node)))
            for wp in current_chunk: 
                new_fp.append(ET.fromstring(ET.tostring(wp)))
            for node in footer_nodes: 
                new_fp.append(ET.fromstring(ET.tostring(node)))

            # Write current_chunk <WorldPosition> tags
            isOceanic = save_phase_macro(ui_instance, new_filename, phase_num, current_chunk, 
                        calibration_data, target_macro_dir, accel_name, decel_name, isOceanic)
            
            # Apply clean indentation (standardized human readable)
            if hasattr(ET, 'indent'):
                ET.indent(new_root, space="    ", level=0)

            # Write to file
            with open(output_path, "wb") as f:
                f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
                ET.ElementTree(new_root).write(f, encoding="utf-8", xml_declaration=False)
            
            prg(f"Phase {phase_num:03d}: WyPt Count {num_waypoints_in_this_phase}, {from_name} -> {to_name}")

        prg(f"Split into {total_chunks} phases.")
 
        # Collect all generated Phase file paths for clipboard output
        ui_instance.generated_phases = []
        for j in range(1, total_chunks + 1):
            # Matches your naming logic
            pattern = f"macro_p{j:01d}.txt"
            ui_instance.generated_phases.append(os.path.join(target_macro_dir, pattern))
        
        # Collect all Waypoint MSG file paths for clipboard output
        prg("Collecting waypoint messages for hotkey display...")
        generated_WPmsg = []
        for j in range(1, total_chunks + 1):
            # Matches your naming logic
            pattern = f"CIVA_Msg_{j:03d}.txt"
            generated_WPmsg.append(os.path.join(target_dir, pattern))            

        ui_instance.total_phases = chunk_size    
        # ok to arm hotkeys
        return True
 
    except Exception as e:
        messagebox.showerror("Error", f"Processing failed: {e}")

def parse_civa_calibration(file_path):
    """
    Parses a CIVA INS calibration file into a dictionary.
    Keys: Button names (e.g., 'hold', '1', 'insert')
    Values: List of macro command strings
    """
    calibration_map = {}
    current_button = None

    try:
        with open(file_path, 'r') as file:
            for line in file:
                clean_line = line.strip()
                
                # Skip empty lines
                if not clean_line:
                    continue

                # Check for the button header <#>
                if clean_line.startswith("<#>"):
                    # Extract the name after <#> and normalize to lowercase
                    current_button = clean_line[3:].strip().lower()
                    calibration_map[current_button] = []
                
                # If we are within a button block, add the command to its list
                elif current_button is not None:
                    calibration_map[current_button].append(clean_line)

        return calibration_map

    except FileNotFoundError:
        logger.error(f"Error: The file at {file_path} was not found.")
        return {}
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {}


def save_phase_macro (ui_instance, new_filename, phase_num, current_chunk, calibration_data, target_dir, accel_name, decel_name, isOceanic):
    """
    current_chunk: A list of ElementTree nodes (<ATCWaypoint>)
    phase_num: The sequential number of the phase (1, 2, 3...)
    """
    filename = f"macro_p{phase_num:01d}.txt"
    file_path = os.path.join(target_dir, filename)
    
    with open(file_path, 'w') as f:
        # record equivalent flight plan file
        f.write(f"<#> For {new_filename}\n")        
        f.write(f"<#> CIVA AUTO-LOADER PHASE {phase_num:03d}\n")
        # Ensure macro output is directed to the target MSFS app        
        # f.write(f'<if_win>("Executable:{target_exe}","OPEN")\n')
        # f.write(f'  <win_activate>("Executable:{target_exe}")\n')
        
        #Output a <msg> display file of waypoint, wp_num for each Phase
        # WPmsg_filename = f"macro_msg_p{phase_num:01d}.txt"
        # WPmsg_path = os.path.join(target_dir, WPmsg_filename)  
        # WPh = get_write_handle(WPmsg_path)
        #msg_html_waypoints[phase_num]
        WPhtml = getMsgHeader()
  
        # Set data selector to WAY PT
        reset_data_selector(calibration_data, f)

        for wpix, wp_node in enumerate(current_chunk):
            # Find the text inside the <WorldPosition> tag for this node
            # This handles the namespace if present or simple tags if not
            world_pos_string = wp_node.findtext("WorldPosition")
            waypoint_id      = wp_node.get("id") or "UNK"
            ICAOident        = wp_node.findtext("ICAO/ICAOIdent")
            if ICAOident and waypoint_id == "UNK":
                    waypoint_id = ICAOident
            if world_pos_string:
                # Passes the string "N20° 42' 38.02",W68° 7' 31.01",+039000.00"
                elev_ft = write_waypoint_macro(waypoint_id, world_pos_string, calibration_data, f, wpix + 1)
                if elev_ft:
                    isOceanic, html_row = getMsgRow(wpix + 1,waypoint_id, elev_ft, accel_name, decel_name, isOceanic) 
                    WPhtml += html_row
            else:
                logger.info(f"WARNING: No WorldPosition for '{waypoint_id}' in Phase {phase_num}. Select 'FS2020 No SID/STAR' in Downloader") 
                f.write(f"<#> WARNING: No WorldPosition found for '{waypoint_id}' in Phase {phase_num}\n")

        WPhtml += getMsgFooter()
        # Safely swap embedded styling quotes into your custom token macro
        safe_html = WPhtml.replace("%_vQuoteChar%", '"')
        safe_html = safe_html.replace("\n", "")
        ui_instance.msg_html_waypoints.append(safe_html )  # Store for hotkey display
        # Set from to selector to 0-1
        #push_button("wy pt chg")
        #push_button("0")
        #push_button("1")        
        #push_button("insert")
        
        if phase_num == 1:
            f.write('<msg>(500,500,"REMINDER: Set FCR Auto-Man switch to Man\n Set INS Auto-Man switch to Auto","Enable INS Mode!",1,60,0,1,20%,20%)\n')
        
        f.write(f"<#> End of Phase {phase_num:03d}\n")
        # Close Directed macro output check        
        # f.write("<else>\n")
        # f.write(f'  <msg>(500,500,"Error:Cant find {target_exe} window","%_vRunningMacroName%",1,0,0,1,33%,33%)\n')
        # f.write("<endif>\n")  
    return isOceanic

def write_waypoint_macro(waypoint_id, world_pos_tag, calibration_data, out_file, phase):
    """
    Parses a MSFS WorldPosition string and writes the macro command sequence.
    Sequence: {waypoint selector}{insert}{longitude}{insert}{latitude}{insert}
    """
    # Regex for N38° 44' 55.31",W90° 22' 12.09",+000617.00
    # Added elev extract: ,[-+]?0*(\d+\.?\d*)
    coord_pattern = r"([NS])(\d+)°\s*(\d+)'\s*(\d+\.?\d*)\",([EW])(\d+)°\s*(\d+)'\s*(\d+\.?\d*)\",[-+]?0*(\d+)\.?\d*"
    
    # add to coord pattern to retrieve elevation... ,\+?(-?\d+\.?\d*)
    match = re.search(coord_pattern, world_pos_tag)
    
    if not match:
        out_file.write(f"<#> ERROR: Invalid coordinate format: {world_pos_tag}\n")
        return

    lat_card, lat_d, lat_m, lat_s, lon_card, lon_d, lon_m, lon_s, elev_ft = match.groups()

    # Cardinal Mapping: N=2, S=8, E=6, W=4
    card_map = {'N': '2', 'S': '8', 'E': '6', 'W': '4'}

    # 1. Format Longitude: CDDDMMS (e.g. W90° 22' 12" -> 4 090 22 1)
    lon_s_digit = str(int(float(lon_s)) // 10)
    lon_sequence = card_map[lon_card] + lon_d.zfill(3) + lon_m.zfill(2) + lon_s_digit

    # 2. Format Latitude: CDDMMS (e.g. N38° 44' 55" -> 2 38 44 5)
    lat_s_digit = str(int(float(lat_s)) // 10)
    lat_sequence = card_map[lat_card] + lat_d.zfill(2) + lat_m.zfill(2) + lat_s_digit

    def cal_push_button(name):
        """Writes the lines from the calibration array for a specific button."""
        lines = calibration_data.get(str(name).lower(), [])
        if not lines:
            out_file.write(f"<#> WARNING: Button '{name}' not found in calibration!\n")
        for line in lines:
            out_file.write(f"{line}\n")

    # --- START MACRO OUTPUT ---
    # <msg>(-100,-100,"<HTML><BODY><h1>This is an EXAMPLE</h1>    
 
    out_file.write(f"<#> World pos tag: {world_pos_tag}\n")
    out_file.write(f"<#> Waypoint Entry: {lat_card}{lat_d}{lat_m}{lat_s} / {lon_card}{lon_d}{lon_m}{lon_s} / Elevation: {elev_ft}'\n")
    out_file.write(f"<#> Encoded: '{lat_sequence}' / '{lon_sequence}'\n")
    # Write onscreen message indicating WP name and pos
    # World pos tag: N42° 0' 0.00",W67° 0' 0.00",+036000.00
    # <msg>(100,100,"WP: EGLL Pos: N51° 28' 39.00 W0° 27' 41.00","World pos tag",0,10,0,0,20%,10%)
    # clean tag.
    out_tag = world_pos_tag.replace('"', '').rpartition(',')[0]

    out_file.write(f'<msg>(100,100, "WP: {waypoint_id} Pos: {out_tag}", "World pos tag", 0, 10, 0, 0, 20%, 10%)\n')
 
    # 1. Increment Waypoint Selector
    cal_push_button("waypoint selector")
    
    # 2. Enter Latitude
    cal_push_button("insert")
    for digit in lat_sequence:
        cal_push_button(digit)
    
    # 3. Enter Longitude
    cal_push_button("insert")
    for digit in lon_sequence:
        cal_push_button(digit)
        
    # 4. Final confirmation
    cal_push_button("insert")

    out_file.write('<msgoff>\n')
    out_file.write("<#> End Waypoint Entry\n")
    
    return elev_ft
         
def reset_data_selector(calibration_data, out_file):
    """
    Forces the Data Selector to the WAY PT position.
    Assumes dial starts somewhere near TEST or far right.
    """
    global_wait = "400"
    coords = calibration_data.get("data selector")
    if not coords:
        return

    out_file.write("<#> --- AUTOMATIC DATA SELECTOR RESET ---\n")
    
    # 1. Move to the dial
    # (Extracting move line from your calibration array)
    for line in coords:
        if "<mm>" in line:
            out_file.write(line)                            # remove extra  + "\n")
    # force focus on wheel
    out_file.write("<mlbd><#>\n")
    out_file.write("<wx>(200,0)<#>\n")
    out_file.write("<mlbu><#>\n")
    out_file.write("<wx>(200,0)<#>\n")

    # 2. Force to far left (TK/GS) - 8 scrolls
    for _ in range(8):
        out_file.write("<mwheel_b><#>\n")
        out_file.write(f"<wx>({global_wait},0)<#>\n")

    # 3. Move 4 positions right to 'WAY PT'
    for _ in range(4):
        out_file.write("<mwheel_f><#>\n")
        out_file.write(f"<wx>({global_wait},0)<#>\n")
    # move away from selector    
    out_file.write("<mm>(300,300)<#>\n")
    
    out_file.write("<#> --- SELECTOR SET TO WAY PT ---\n\n")
    
def Read_OFP_PDF (pdf_path):
    
    #from pypdf import PdfReader
    #import re
    # Define regex patterns to find the tokens
    # \s* matches any whitespace, \S+ matches the non-whitespace value
    
    accel_pattern = r".*ACCEL:\s*(\S+)"
    decel_pattern = r".*DECEL:\s*(\S+)"
    # if manual acceleration point is not included, it can be inferred from
    # a step above 020
    # FL STEPS EGLL/0030/WOD/0040/CPT/0060/PACSE/0280/LESLU/0500
    steps_pattern = r".*FL STEPS.*"
    accel_match = None
    decel_match = None
    steps_name  = None
        
    # 1. Load the PDF
    reader = PdfReader(pdf_path)
    if reader:
        for page in reader.pages:         # Get the first page
            text = page.extract_text()
            lines = text.splitlines()
            for line in lines:            

                # 3. Extract the data
                if not accel_match: 
                    accel_match = re.search(accel_pattern, line)
                    accel_name = accel_match.group(1) if accel_match else ""
                if not decel_match:
                    decel_match = re.search(decel_pattern, line)
                    decel_name = decel_match.group(1) if decel_match else ""
                if not steps_name and re.search(steps_pattern, line):
                    steps_name,steps_level = Parse_FL_steps (line)
    else:
        return

    if not accel_name and steps_name:
        accel_name = steps_name
    return accel_name, decel_name

def Parse_FL_steps (fl_steps_line):

    # Split OFP fl steps string into components
    # FL STEPS EGLL/0030/WOD/0040/CPT/0060/PACSE/0280/LESLU/0500
    comp = fl_steps_line.split('/')

    name = None
    level = None

    # Iterate through the list starting from the second element
    for i in range(1, len(comp)):
        item = comp[i]
        
        # Check if the item is numeric
        if item.isdigit():
            num = int(item)
            
            # Find the first number greater than 200
            if num > 200:
                level = item
                name = comp[i-1] # The name is the item right before the number
                break # Stop at the first occurrence

    return name, level
 

# spec:
# i have an array of signed geographic coordinates (float) in decimal degrees 
#    representing a series of linear legs and a current location.
# I need a python function that will:
# 1. find the leg based on smallest perpendicular distance to each leg 
#    and within the length of the leg (i.e. rotate leg and point to horiz or vert axis and test)
# 2. find the from point as the smaller array index and the to point as the from+1
# 3. if not within any leg, return -1 if close to first point, 
# 4. return a flag of 0 if a valid leg has been found
# 5. return a flag of 1 if not within any leg, and closer to 2nd point
# 6. for each flag case, return a distance in approx nm, nautical miles to the to 
#    point and the length of the leg or 0 if flag is 1 or -1.. 
#    If flag =1 return distance from the last point


def track_current_phase(coords, current_loc):
    """
    Tracks the active flight plan leg for a CIVA INS unit.
    Uses an MBR check to handle airport overlaps and prevent false 0 flags.
    
    Parameters:
    coords (list of lists/tuples): [[lat0, lon0], [lat1, lon1], ...] in decimal degrees.
    current_loc (list/tuple): [current_lat, current_lon]
    
    Returns:
    dict: {
        'flag': -1 (before/near start), 0 (on leg), 1 (beyond/near end),
        'from_idx': int,
        'to_idx': int,
        'dist_to_to_pt_nm': float,
        'leg_length_nm': float
    }
    """
    n = len(coords)
    if n < 2:
        raise ValueError("Flight plan must contain at least two waypoints.")

    cur_lat, cur_lon = current_loc

    # =========================================================================
    # 1. MINIMUM BOUNDING RECTANGLE (MBR) CHECK
    # =========================================================================
    # Extract coordinate boundaries for the entire phase
    lats = [c.latitude for c in coords]
    lons = [c.longitude for c in coords]
    
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    
    # Check if the aircraft is strictly outside the phase footprint
    # A small buffer can be added if needed, but strict boundary enforces your spec
    is_outside_mbr = not (min_lat <= cur_lat <= max_lat and min_lon <= cur_lon <= max_lon)

    # =========================================================================
    # 2. LOCAL COORDINATE PROJECTION (NM)
    # =========================================================================
    lat_to_nm = 60.0
    lon_to_nm = 60.0 * math.cos(math.radians(cur_lat))

    cx, cy = 0.0, 0.0
    pts = []
    for crd in coords:
        x = (crd.longitude - cur_lon) * lon_to_nm
        y = (crd.latitude - cur_lat) * lat_to_nm
        pts.append((x, y))

    valid_leg_found = False
    best_leg_idx = None
    min_perp_dist = float('inf')

    # =========================================================================
    # 3. LEG EVALUATION (Skipped if outside MBR)
    # =========================================================================
    if not is_outside_mbr:
        for i in range(n - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i+1]
            
            dx = x2 - x1
            dy = y2 - y1
            leg_len_sq = dx*dx + dy*dy
            
            if leg_len_sq == 0:
                continue
                
            # Vector projection factor t (0.0 = From, 1.0 = To)
            t = ((cx - x1) * dx + (cy - y1) * dy) / leg_len_sq
            
            # Check if current position sits squarely within the leg bounds
            if 0.0 <= t <= 1.0:
                valid_leg_found = True
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy
                perp_dist = math.sqrt((cx - proj_x)**2 + (cy - proj_y)**2)
                
                if perp_dist < min_perp_dist:
                    min_perp_dist = perp_dist
                    best_leg_idx = i

    # =========================================================================
    # 4. FLAG & METRIC GENERATION
    # =========================================================================
    if valid_leg_found:
        # Flag 0: Active tracking inside the MBR on a valid segment
        from_pt = pts[best_leg_idx]
        to_pt = pts[best_leg_idx + 1]
        leg_length = math.sqrt((to_pt[0] - from_pt[0])**2 + (to_pt[1] - from_pt[1])**2)
        dist_to_to_pt = math.sqrt((to_pt[0] - cx)**2 + (to_pt[1] - cy)**2)
        
        return {
            'flag': 0,
            'from_idx': best_leg_idx,
            'to_idx': best_leg_idx + 1,
            'dist_to_to_pt_nm': dist_to_to_pt,
            'leg_length_nm': leg_length
        }
    else:
        # Flag -1 or 1: Outside MBR or not matched inside any vector bounds
        x_first, y_first = pts[0]
        x_last, y_last = pts[-1]
        
        dist_to_first = math.sqrt((x_first - cx)**2 + (y_first - cy)**2)
        dist_to_last = math.sqrt((x_last - cx)**2 + (y_last - cy)**2)
        
        if dist_to_first <= dist_to_last:
            # Flag -1: Closer to origin waypoint
            return {
                'flag': -1,
                'from_idx': 0,
                'to_idx': 1,
                'dist_to_to_pt_nm': dist_to_first,
                'leg_length_nm': 0.0
            }
        else:
            # Flag 1: Closer to final waypoint
            return {
                'flag': 1,
                'from_idx': n - 2,
                'to_idx': n - 1,
                'dist_to_to_pt_nm': dist_to_last,
                'leg_length_nm': 0.0
            }




def set_dark_mode(app):
    app.setStyle("Fusion") # Required for custom palettes to work
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.black)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

class CIVA_INS_WP_Tracker:
    def __init__(self, uiInstance):
        # Configure path to Tesseract if it is not in your system environment variables
        # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
       # Set up a flag to track if OCR capability is active
        self.ui = uiInstance
        self.ui.ocr_available = True
        
        # Optional: Set explicit path if needed before checking
        # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        
        # Check if Tesseract is installed and available immediately upon startup
        self._verify_tesseract_presence()

    def _verify_tesseract_presence(self):
        """Checks if Tesseract is accessible on the system."""
        try:
            # Running tesseract_version() forces a quick check against the system binary
            version = pytesseract.get_tesseract_version()
            self.ui.update_progress_log(f" [OCR SUCCESS] Tesseract Engine found (v{version}).")
        except pytesseract.TesseractNotFoundError:
            # Catch the specific error and gracefully downgrade features
            self.ui.ocr_available = False
            self.ui.update_progress_log(" [OCR WARNING] Tesseract not installed or not in PATH.")
            self.ui.update_progress_log(" Disabling rotary waypoint selector scan .")

    def _get_primary_monitor(self, sct):
        """
        Internal helper: Locates the true Primary Monitor in the multi-monitor system.
        The primary display always acts as the origin coordinates (0,0) in Windows.
        """
        for monitor in sct.monitors[1:]:  # Skip monitors[0] which is the unified canvas
            if monitor["left"] == 0 and monitor["top"] == 0:
                return monitor
        return sct.monitors[1]  # Safely fall back to the first physical display if index matches fail

    def capture_and_ocr_digit(self, ui_Instance):
        """
        Captures a screen rect from the primary display and extracts a single digit.
        
        Parameters:
        screen_rect (dict): Bounding box format {'top': y, 'left': x, 'width': w, 'height': h}
        """
        # If the backend engine isn't installed, fail early and return None
        if not self.ui.ocr_available:
            return None  
                # Wrap your main execution in an extra layer of protection just in case
        try: 
            # convert wpt sel loc to rectangle
            wd = 100
            ht = 100
            top = int(ui_Instance.waypoint_sel_y - ht / 2)
            left = int(ui_Instance.waypoint_sel_x - wd / 2)
            screen_rect = {'top': top, 
                            'left': left, 
                            'width': wd, 'height': ht}     
            with mss.MSS() as sct:
                # 1. Resolve multi-monitor screen offsets dynamically
                primary = self._get_primary_monitor(sct)
                
                # 2. Lock relative target offsets explicitly onto the Primary Display geometry
                capture_box = {
                    "top": primary["top"] + screen_rect["top"],
                    "left": primary["left"] + screen_rect["left"],
                    "width": screen_rect["width"],
                    "height": screen_rect["height"]
                }
                
                # 3. Capture the calculated primary coordinates bounding box
                sct_img = sct.grab(capture_box)
                
                # 4. Convert raw screen buffer directly to a PIL Image object
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                # 5. Preprocess texture image (upscale and convert to grayscale)
                #img_gray = img.convert('L')
                #img_large = img_gray.resize((img_gray.width * 2, img_gray.height * 2), Image.Resampling.LANCZOS)

                # =========================================================================
                # STABILIZED MECHANICAL SELECTOR MORPHOLOGY PIPELINE
                # =========================================================================
                # 1. Standardise to 180x180 Grayscale
                img_gray = img.convert('L')
                img_normalized = img_gray.resize((180, 180), Image.Resampling.LANCZOS)
                
                # 2. Invert (White text on dark dial -> Black text on White canvas)
                img_inverted = ImageOps.invert(img_normalized)
                
                # 3. Create a strict binary image (only pure black 0 and pure white 255)
                threshold_value = 140 
                img_binary = img_inverted.point(lambda p: 255 if p > threshold_value else 0)
                
                # 4. Convert to 1-bit mode (strictly required by Pillow's Morph engine)
                img_1bit = img_binary.convert('1')
                
                # 5. LOAD BUILT-IN EROSION OPERATOR
                # "erosion4" shaves the outer edges of black elements. This re-opens 
                # the choked interior holes of 5, 6, and 9 beautifully.
                op = ImageMorph.MorphOp(op_name="erosion4")
                
                # Run the thinning pass twice to pull structural weight off the thick digits
                count, img_thinned = op.apply(img_1bit)
                count, img_thinned = op.apply(img_thinned)
                
                # 6. Smooth the edges to clean up pixel steps/aliasing
                img_final = img_thinned.convert('L')
                img_final = img_final.filter(ImageFilter.SMOOTH_MORE)
                
                # 7. Final clean snap to black/white and pad the borders
                img_final = img_final.point(lambda p: 255 if p > 128 else 0)
                img_final = ImageOps.expand(img_final, border=20, fill=255)
                # =========================================================================

                # --- DEBUG IMAGE EXPORT ---
                debug = True
                if debug:
                    debug_dir = os.path.join(os.path.dirname(__file__), "ocr_debug")
                    os.makedirs(debug_dir, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    img_final.save(os.path.join(debug_dir, f"civa_morph_{timestamp}.png"))
                
                # 6. Apply Tesseract configuration targeting single integers (0-9) exclusively
                # =========================================================================
                # CONFIGURATION OVERHAUL: Added --oem 0 (Legacy Engine Mode)
                # =========================================================================
                # --psm 10: Treat image as a single character
                # --oem 0: Forces Legacy Engine, which excels at isolated mechanical fonts
                # --psm 13 treats the text line as a raw sequence, bypassing single-glyph distortion bugs
                custom_config = r'--psm 13 --oem 3 -c tessedit_char_whitelist=0123456789'

                ocr_result = pytesseract.image_to_string(img_final, config=custom_config)
                digit_str = ocr_result.strip()
                # Handle the specific '41' / '11' multi-character glitch gracefully
                if len(digit_str) > 1:
                    if '1' in digit_str and '4' in digit_str:
                        # If Tesseract returned '41', '11', or '71', the true dial index is 1
                        return 1
                    else:
                        # General fallback: grab the first character if another number acts up
                        digit_str = digit_str[0]
                return int(digit_str) if digit_str.isdigit() else None
        except pytesseract.TesseractNotFoundError:
            # If it somehow breaks dynamically during flight, catch it here
            self.ui.ocr_available = False
            return None
            # except pytesseract.TesseractError:
            #     # Fallback: Some Tesseract installations don't include the legacy engine data assets.
            #     # If your system errors out on --oem 0, we fall back cleanly to default OEM 3.
            #     custom_config_fallback = r'--psm 10 --oem 3 -c tessedit_char_whitelist=0123456789'
            #     ocr_result = pytesseract.image_to_string(img_final, config=custom_config_fallback)
            #     digit = ocr_result.strip()
            #     return int(digit) if digit.isdigit() else None


if __name__ == "__main__":
    # Enable high DPI support for automatic font scaling with display scale
#    app = QApplication([])
#    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
#    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
#    window = CIVAFlightPlanUI()
#    window.show()
#    app.exec_()

# 1. Windows System Level Scaling
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        ctypes.windll.user32.SetProcessDPIAware()

    # 2. Qt Level Scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # Custom dark palette for better aesthetics
    set_dark_mode(app)


    window = CIVAFlightPlanUI()
    window.show()
    sys.exit(app.exec_())   

    # fail safe
    pyautogui.FAILSAFE = True 


