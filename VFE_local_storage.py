#!/usr/bin/env python3
"""
CIVA INS Local Storage Manager

Manages persistent storage for CIVA INS toolbar app.
Uses MSFS-appropriate local storage paths.
"""

import os
import json
import platform
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field


# =============================================================================
# Storage Paths
# =============================================================================

def get_app_data_dir() -> Path:
    """
    Get the appropriate app data directory based on platform.
    MSFS toolbar apps should use user-local storage.
    """
    if platform.system() == "Windows":
        # Windows: Use LocalAppData (not Roaming)
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        # macOS/Linux fallback
        base = Path.home() / ".local" / "share"
    
    app_dir = base / "CIVA_INS"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_calibration_path() -> Path:
    """Get path for calibration data."""
    return get_app_data_dir() / "calibration.json"


def get_preferences_path() -> Path:
    """Get path for user preferences."""
    return get_app_data_dir() / "preferences.json"


def get_flight_plan_cache_path() -> Path:
    """Get path for cached flight plans."""
    cache_dir = get_app_data_dir() / "flight_plans"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ButtonCalibration:
    """Calibration data for a single button."""
    name: str
    x: int
    y: int
    wait_ms: int = 200
    button_type: str = "left"  # "left", "right", "wheel_up", "wheel_down"


@dataclass
class CalibrationData:
    """Complete calibration data for CIVA INS."""
    version: str = "1.0"
    msfs_version: str = "2020"  # "2020" or "2024"
    screen_resolution: str = ""
    buttons: Dict[str, Any] = field(default_factory=list)
    data_selector_positions: Dict[str, int] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class UserPreferences:
    """User preferences for the toolbar app."""
    auto_connect_simconnect: bool = True
    click_delay_ms: int = 200
    show_oceanic_highlighting: bool = True
    audio_feedback: bool = True
    default_msfs_version: str = "2020"


# =============================================================================
# Storage Manager
# =============================================================================

class LocalStorage:
    """
    Manages local storage for CIVA INS toolbar.
    Provides JSON-based storage with disk file fallback.
    """
    
    def __init__(self):
        self.app_dir = get_app_data_dir()
    
    # -------------------------------------------------------------------------
    # Calibration
    # -------------------------------------------------------------------------
    
    def save_calibration(self, calibration: CalibrationData) -> bool:
        """Save calibration data to local storage."""
        try:
            path = get_calibration_path()
            with open(path, 'w') as f:
                json.dump(asdict(calibration), f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving calibration: {e}")
            return False
    
    def load_calibration(self) -> Optional[CalibrationData]:
        """Load calibration data from local storage."""
        try:
            path = get_calibration_path()
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                return CalibrationData(**data)
        except Exception as e:
            print(f"Error loading calibration: {e}")
        return None
    
    def export_macro_format(self, calibration: CalibrationData, output_path: str):
        """
        Export calibration to Macro Commander format (legacy compatibility).
        This maintains compatibility with existing workflow.
        """
        with open(output_path, 'w') as f:
            for button_name, button_data in calibration.buttons.items():
                f.write(f"<#> {button_name}\n")
                if isinstance(button_data, list):
                    for line in button_data:
                        f.write(f"{line}\n")
                else:
                    # New JSON format - convert to macro format
                    f.write(f"<mm>({button_data.get('x', 0)},{button_data.get('y', 0)})\n")
                    f.write(f"<wx>({button_data.get('wait_ms', 200)},0)\n")
                f.write("\n")
    
    # -------------------------------------------------------------------------
    # Preferences
    # -------------------------------------------------------------------------
    
    def save_preferences(self, preferences: UserPreferences) -> bool:
        """Save user preferences."""
        try:
            path = get_preferences_path()
            with open(path, 'w') as f:
                json.dump(asdict(preferences), f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving preferences: {e}")
            return False
    
    def load_preferences(self) -> UserPreferences:
        """Load user preferences."""
        try:
            path = get_preferences_path()
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
                return UserPreferences(**data)
        except Exception as e:
            print(f"Error loading preferences: {e}")
        return UserPreferences()
    
    # -------------------------------------------------------------------------
    # Flight Plan Cache
    # -------------------------------------------------------------------------
    
    def cache_flight_plan(self, plan_name: str, data: Dict) -> bool:
        """Cache a flight plan for quick loading."""
        try:
            path = get_flight_plan_cache_path() / f"{plan_name}.json"
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error caching flight plan: {e}")
            return False
    
    def load_cached_flight_plan(self, plan_name: str) -> Optional[Dict]:
        """Load a cached flight plan."""
        try:
            path = get_flight_plan_cache_path() / f"{plan_name}.json"
            if path.exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading cached flight plan: {e}")
        return None
    
    def list_cached_flight_plans(self) -> list:
        """List all cached flight plans."""
        cache_dir = get_flight_plan_cache_path()
        return [p.stem for p in cache_dir.glob("*.json")]
    
    def clear_cache(self) -> bool:
        """Clear all cached flight plans."""
        try:
            for path in get_flight_plan_cache_path().glob("*.json"):
                path.unlink()
            return True
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return False


# =============================================================================
# Example Usage
# =============================================================================

if __name__ == "__main__":
    storage = LocalStorage()
    
    print(f"Storage location: {storage.app_dir}")
    print(f"  Calibration: {get_calibration_path()}")
    print(f"  Preferences: {get_preferences_path()}")
    print(f"  Flight Plans: {get_flight_plan_cache_path()}")
    
    # Test preferences
    prefs = storage.load_preferences()
    print(f"\nCurrent preferences: {prefs}")
    
    # Save test calibration
    test_cal = CalibrationData(
        version="1.0",
        msfs_version="2024",
        buttons={
            "clear": [{"x": 100, "y": 200, "wait_ms": 200}],
            "1": [{"x": 150, "y": 200, "wait_ms": 200}]
        }
    )
    storage.save_calibration(test_cal)
    print("\nTest calibration saved")