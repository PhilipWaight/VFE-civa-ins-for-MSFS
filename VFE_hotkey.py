#    [User Presses Combination while MSFS has Focus]
#                           │
#                           ▼
#        ┌──────────────────────────────────────┐
#        │ pynput low-level win32_event_filter  │
#        └──────────────────────────────────────┘
#                           │
#         Is it a registered hotkey for MY APP?
#         ├──► YES: Return False (Swallow key from MSFS).
#         │         Fire the execution thread.
#         │
#         └──► NO:  Return True (Pass key smoothly to MSFS or other app).

import win32con
import ctypes
import threading
import win32con
import win32gui
import win32api
from pynput import keyboard

import logging

# Configure logging
logger = logging.getLogger(__name__)

# Explicit dictionary mapping for modifier and special named keys
SPECIAL_KEYS_MAP = {
    "ctrl": win32con.VK_CONTROL,
    "control": win32con.VK_CONTROL,
    "shift": win32con.VK_SHIFT,
    "alt": win32con.VK_MENU,
    "menu": win32con.VK_MENU,
    "win": win32con.VK_LWIN,
    "space": win32con.VK_SPACE,
    "tab": win32con.VK_TAB,
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "backspace": win32con.VK_BACK,
    "escape": win32con.VK_ESCAPE,
    "esc": win32con.VK_ESCAPE,
    # --- DEDICATED NUMPAD MAPPING ENTRY BLOCKS ---
    "numpad0": win32con.VK_NUMPAD0,
    "numpad1": win32con.VK_NUMPAD1,
    "numpad2": win32con.VK_NUMPAD2,
    "numpad3": win32con.VK_NUMPAD3,
    "numpad4": win32con.VK_NUMPAD4,
    "numpad5": win32con.VK_NUMPAD5,
    "numpad6": win32con.VK_NUMPAD6,
    "numpad7": win32con.VK_NUMPAD7,
    "numpad8": win32con.VK_NUMPAD8,
    "numpad9": win32con.VK_NUMPAD9,
    "numpad*": win32con.VK_MULTIPLY,
    "numpadmultiply": win32con.VK_MULTIPLY,
    "numpad+": win32con.VK_ADD,
    "numpadadd": win32con.VK_ADD,
    "numpad-": win32con.VK_SUBTRACT,
    "numpadsubtract": win32con.VK_SUBTRACT,
    "numpad.": win32con.VK_DECIMAL,
    "numpaddecimal": win32con.VK_DECIMAL,
    "numpad/": win32con.VK_DIVIDE,
    "numpaddivide": win32con.VK_DIVIDE,
}

# user_config = {
#     "Ctrl + Numpad5": "re_center_view",       # Resolves to VK_NUMPAD5 (0x65)
#     "Alt + numpad-": "zoom_out_mfd",          # Resolves to VK_SUBTRACT (0x6D)
#     "Shift + NumpadAdd": "increase_throttle"  # Resolves to VK_ADD (0x6B)
# }
# The dictionary layout consumed directly by your background win32_event_filter hook
# MY_APP_HOTKEYS = {}

# for string_combo, action_name in user_config.items():
#     try:
#         vk_signature = string_to_vk_combo(string_combo)
#         MY_APP_HOTKEYS[vk_signature] = action_name
#     except ValueError as e:
#         logger.info(f"Skipping corrupt configuration item: {e}")

# logger.info("Successfully loaded hotkey signature map into memory:")
# logger.info(MY_APP_HOTKEYS)

# Add Function keys (F1 - F24) dynamically to the mapping table
for i in range(1, 25):
    SPECIAL_KEYS_MAP[f"f{i}"] = getattr(win32con, f"VK_F{i}")

class HotkeyWrapper:
    """
    Wrapper class for hotkey handling.
    """
   
    def __init__(self, ui_instance):
        self._is_armed = False
        self._hook_thread = None
        self._listener = None
        self.VK_hotkeys = {}
        self.ui = ui_instance
        
        # Start the persistent background hook immediately
        self._start_persistent_hook()

    def _start_persistent_hook(self):
        """Starts the low-level listener once during initialization."""
        # Note: we pass a lambda or bound method to access instance variables
        self._listener = keyboard.Listener(win32_event_filter=self._win32_event_filter)
        self._listener.start()
        #self._hook_thread = threading.Thread(target=self._listener.start, daemon=True)
        #self._hook_thread.start()
    def stop_persistent_hook(self):
        """Safely unregisters the low-level hook and shuts down the background loop."""
        if hasattr(self, '_listener') and self._listener is not None:
            if self._listener.running:
                logger.info("[Hotkey System] Cleaning up low-level Windows hook...")
                self._listener.stop()  # Signals pynput loop to break
                self._listener.join()  # Waits for the thread to completely die
            self._listener = None        

    def arm(self):
        """Arms your app's custom hotkey overrides."""
        logger.info("[Hotkey System] Overrides Armed.")
        self._is_armed = True

    def disarm(self):
        """Unarms hotkeys. Everything passes straight to MSFS instantly."""
        logger.info("[Hotkey System] Overrides Unarmed. Passing all keys natively.")
        self._is_armed = False

    def add_hotkey(self, user_keys_config, islast):

        # Raw user strings loaded from an .ini, .json, or user input text box
        # user_config = {
        #     "Ctrl + Shift + M": "toggle_map_overlay",
        #     "alt-k": "mark_waypoint"
        # }

        for string_combo, action_name  in user_keys_config.items():
            try:
                vk_signature = self.string_to_vk_combo(string_combo)
                self.VK_hotkeys[vk_signature] = action_name
            except ValueError as e:
                logger.info(f"Skipping corrupt configuration item: {e}")

            #logger.info("Successfully loaded hotkey signature map into memory:")
            #if islast: logger.info(self.VK_hotkeys)

    def string_to_vk_combo(self, hotkey_str):
        """
        Parses strings like 'ctrl+shift+k', 'alt-space', or 'Ctrl + K'
        Returns: (frozenset([modifier_vks]), primary_vk)
        """
        # 1. Clean formatting and normalize delimiters
        normalized = hotkey_str.lower().replace("-", "+").replace(" ", "")
        parts = normalized.split("+")
        
        modifiers = set()
        primary_vk = None

        for part in parts:
            if not part:
                continue
                
            # 2. Check if the element is a known special or modifier key
            if part in SPECIAL_KEYS_MAP:
                vk = SPECIAL_KEYS_MAP[part]
                # Separate modifiers from the final executable hotkey stroke
                if vk in (win32con.VK_CONTROL, win32con.VK_SHIFT, win32con.VK_MENU, win32con.VK_LWIN):
                    modifiers.add(vk)
                else:
                    primary_vk = vk
            
            # 3. Handle standard alphanumeric keys (a-z, 0-9)
            elif len(part) == 1:
                # Query the OS layout engine to get the exact virtual key mapping code
                res = ctypes.windll.user32.VkKeyScanW(part)
                if res == -1:
                    raise ValueError(f"Unsupported character in hotkey configuration: '{part}'")
                primary_vk = res & 0xFF  # Extract low-order byte for true VK code
                
            else:
                raise ValueError(f"Unrecognized key designation entry: '{part}'")

        if primary_vk is None:
            raise ValueError(f"Invalid combo string '{hotkey_str}'. Missing primary action key.")

        return frozenset(modifiers), primary_vk
    
    # Define your custom app hotkeys using Virtual Key (VK) codes
    # Example: Ctrl + Shift + M (VK codes: Ctrl=17, Shift=16, M=77)
    # MY_APP_HOTKEYS = {
    #     (frozenset([win32con.VK_CONTROL, win32con.VK_SHIFT]), 77): "toggle_map_overlay",
    #     # Example: Alt + K (VK codes: Alt=18, K=75)
    #     (frozenset([win32con.VK_MENU]), 75): "mark_waypoint"
    # }

    def execute_app_action(self, action_name):
        """Executes your app logic asynchronously so it doesn't block the OS hook thread."""
        logger.info(f"\n[hotkey] Executing: {action_name}")
        # Insert map toggle, overlay update, or telemetry capture logic here
        #self.ui
        indx = int(action_name[-1])
        if indx in range(1,10):
            if "phase" in action_name: self.ui.trigger_phase_macro(indx)
            elif "wplist" in action_name: self.ui.trigger_waypoint_info(indx)

    def get_live_modifiers(self):
        """Reads the instantaneous physical state of the modifier keys."""
        mods = []
        if win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000:
            mods.append(win32con.VK_CONTROL)
        if win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000:
            mods.append(win32con.VK_SHIFT)
        if win32api.GetAsyncKeyState(win32con.VK_MENU) & 0x8000: # Alt key
            mods.append(win32con.VK_MENU)
        return frozenset(mods), mods

    def _win32_event_filter(self, msg, data):

        """
        Windows-native low-level keyboard intercept hook callback.
        
        Parameters:
        - msg (int): The Windows Message ID (e.g., WM_KEYDOWN, WM_SYSKEYDOWN)
        - data (struct): A pointer to the Windows KBDLLHOOKSTRUCT containing .vkCode
        """
        # 1. Immediate exit bypass if your state machine is unarmed
        if not self._is_armed:
            #logger.info(f"Hotkeys not armed")          
            return True # Pass key straight through to MSFS immediately

        # Only evaluate on Key Down messages (WM_KEYDOWN or WM_SYSKEYDOWN for Alt combos)
        # 256, 260
        try:
            vkints = None
            if msg in (win32con.WM_KEYDOWN, win32con.WM_SYSKEYDOWN):
                vkints = []
                vk_code = data.vkCode
                current_mods, vkints = self.get_live_modifiers()
                current_combo = (current_mods, vk_code)
                vkints.append(vk_code)

                # 1. Match against your app's global keys
                if current_combo in self.VK_hotkeys:
                    action_to_fire  = self.VK_hotkeys[current_combo]
                    logger.info(f"Hotkey triggered: {action_to_fire }")
                    # Fire the action code inside a separate thread to keep the hook light
                    #threading.Thread(target=self.execute_app_action, args=(action,), daemon=True).start()
                    self.execute_app_action(action_to_fire)
                    # Swallows the key completely. MSFS will never see it.
                    return False 

            # 2. Unknown keys pass naturally straight through to the active window (MSFS)
            # if vkints:
            #     kchars = vk_to_string(vkints)
            #     logger.info(f"Hotkey passed on: {kchars}")
            # if self.ui.msfs_hwnd != 0:
            #     logger.info(f"msfs focus")
            #     if win32gui.IsIconic(self.ui.msfs_hwnd): # If minimised
            #         win32gui.ShowWindow(self.ui.msfs_hwnd, win32con.SW_RESTORE)
            #     win32gui.SetForegroundWindow(self.ui.msfs_hwnd)
            return True 
        except Exception as e:
            logger.error(f"_win32_event_filter: {e}")
            return True

    # def start_global_hook(self):
    #     """Initializes the Windows background listener loop."""
    #     # Using win32_event_filter allows micro-targeted key suppression
    #     with keyboard.Listener(win32_event_filter=self.win32_event_filter) as listener:
    #         listener.join()
def vk_to_string(vkints):
    """
    Translates a Windows Virtual Key (VK) code into its human-readable name.
    Handles alphanumeric characters, system keys, and localized layouts.
    """
    chrs = ""
    for vk_code in vkints:
        # 1. Map the VK code to a hardware Scan Code (required by GetKeyNameTextW)
        # MapType 0: VK to Scan Code
        scan_code = ctypes.windll.user32.MapVirtualKeyW(vk_code, 0)
        
        # 2. Build the lParam bitmask that GetKeyNameTextW expects
        # Bit 16-23 must contain the hardware scan code
        l_param = scan_code << 16
        
        # Check for extended keys (e.g., Arrow keys, Right Ctrl/Alt)
        # Bit 24 marks the key as extended
        if vk_code in [33, 34, 35, 36, 37, 38, 39, 40, 45, 46]: # PageUp, PageDown, End, Home, Arrows, Insert, Delete
            l_param |= (1 << 24)

        # 3. Call GetKeyNameTextW using a string buffer to receive the name
        buffer = ctypes.create_unicode_buffer(32)
        result = ctypes.windll.user32.GetKeyNameTextW(l_param, buffer, len(buffer))
        
        if result > 0:
            chrs += buffer.value.lower()
            
        # 4. Fallback behavior for standard single ASCII characters if the API returns empty
        if 48 <= vk_code <= 57 or 65 <= vk_code <= 90: # 0-9 or A-Z
            chrs += chr(vk_code).lower()
        
    return f"vk: {chrs}"

