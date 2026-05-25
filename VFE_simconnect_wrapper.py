#!/usr/bin/env python3
"""
SimConnect Wrapper for CIVA INS Flight Plan Processor

This module provides a wrapper around the SimConnect API to monitor aircraft
state and INS progress during flight.

Requirements:
- py-simconnect package (pip install py-simconnect)
- Or can use comtypes for native SimConnect access

"""

import logging
import time
from typing import Optional, Dict, Any

# Configure logging
logger = logging.getLogger(__name__)


class SimConnectWrapper:
    """
    Wrapper class for SimConnect communication with MSFS.
    Provides methods to connect, subscribe to events, and read aircraft data.
    """
    
    def __init__(self, app_name: str = "CIVA INS Flight Plan Processor"):
        self.app_name = app_name
        self.connected = False
        self.flightLoaded = False
        self.flightActive = False
        self.sm = None
        self._data_callback = None
        
    def connect(self, timeout: int = 10) -> bool:
        """
        Establish connection to SimConnect.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            bool: True if connection successful
        """
        try:

            import os
            import sys

            # Check if running as a PyInstaller bundle
            if getattr(sys, 'frozen', False):
                bundle_dir = sys._MEIPASS
                os.add_dll_directory(bundle_dir)
            else:
                # Fallback for your local "py vfe_civa_ins.py" testing
                os.add_dll_directory(r"C:\MSFS 2024 SDK\SimConnect SDK\lib")

            # Try to import py-simconnect
            from SimConnect import SimConnect, AircraftRequests
            
            self.sm = SimConnect(True)  #, self.app_name)
            # 2. Create a SystemEvents request helper
            #self.sys_events = SystemEvents(self.sm)

            self.aq = AircraftRequests(self.sm)
            self.connected = True
            #logger.info("Connected to SimConnect")
            return True
            
        # except ImportError:
        #     # Fall back to comtypes approach
        #     try:
        #         return self._connect_comtypes(timeout)
        #     except Exception as e:
        #         logger.warning(f"SimConnect not available: {e}")
        #         self.connected = False
        #         return False
        except Exception as e:
            logger.error(f"Failed to connect to SimConnect: {e}")
            self.connected = False
            return False
    
    def _connect_comtypes(self, timeout: int) -> bool:
        """
        Alternative connection using comtypes for native SimConnect access.
        """
        try:
            from comtypes.client import CreateObject
            from comtypes import GUID
            
            # Create SimConnect instance
            self.sm = CreateObject(
                "SimConnect.SimConnect.1",
                interface=None,
                clsctx=None
            )
            self.connected = True
            logger.info("Connected to SimConnect via comtypes")
            return True
            
        except ImportError:
            logger.debug("comtypes not available")
            return False
        except Exception as e:
            logger.debug(f"comtypes connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from SimConnect."""
        if self.sm and self.connected:
            try:
                self.sm.exit()
                logger.info("Disconnected from SimConnect")
            except Exception as e:
                logger.debug(f"Error disconnecting: {e}")
            finally:
                self.connected = False
                self.sm = None
    
    def is_connected(self) -> bool:
        """Check if currently connected to SimConnect."""
        return self.connected
    
    def get_aircraft_data(self) -> Optional[Dict[str, Any]]:
        """
        Get current aircraft data from SimConnect.
        
        Returns:
            dict: Aircraft data including position, heading, altitude, etc.
                  None if not connected or error
        """
        if not self.connected:
            return None
        try:
            # simstate = self.SimConnect_RequestSystemState("Sim")
            # # user in UI menus
            # if simstate == 0:
            #     self.flightLoaded = False 
            #     data = {
            #         "flight_loaded": False}
            #     return data
            # elif simstate == 1:

                # Request aircraft data
                # This is a simplified version - full implementation would
                # define custom data definitions and request specific fields

            # 3. Listen for specific MSFS system state changes
            # For example: checking if the simulation is active ("Sim")
            #logger.info(f"get aircraft data - AQ")
            data = {
                "flight_loaded":    True,
                # "ui_active": True,  
                "in_active_pause":  self.aq.get("IS IN ACTIVE PAUSE"),              
                "in_ctr_area":      self.aq.get("IS IN CTR AREA"), 
                "lights_on":        self.aq.get("IS ANY INTERIOR LIGHT ON"), 
                "sim_on_ground":    self.aq.get("SIM ON GROUND"), 
                "timestamp":        time.time(),
                "connected":        self.connected,
                #"category": self.aq.get("AIRCRAFT CATEGORY"),   
                "alt": round(self.aq.get("PLANE_ALTITUDE")),
                "spd": round(self.aq.get("GROUND_VELOCITY")),                
                "lat": round(self.aq.get("PLANE_LATITUDE"), 6),
                "lng": round(self.aq.get("PLANE_LONGITUDE"), 6)                                
            }
            # 1. Fetch the raw bytes from the AircraftRequests object for string items
            data["title"] = self.get_sm_string("TITLE", "Unknown Aircraft")
            #logger.info(f"scw: {data}")
            # conditions for being active in cockpit
            self.flightLoaded = True 
            # change state if end flight - no specifc var
            self.flightActive = (data["spd"] > 0 or \
                                #data["title"] != "" or \
                                #data["lights_on"] == 1 or \
                                data["sim_on_ground"] == 1 or \
                                data["in_ctr_area"] == 1)
            return data
            
        except Exception as e:
            self.flightLoaded = False
            logger.debug(f"Error getting aircraft data: {e}")
            return None

    def get_sm_string (self, dataref, defstr):
        raw_title_bytes = self.aq.get(dataref)
        locstr = ""
        if raw_title_bytes:
            # 2. Split at the first null character to truncate the padding
            # 3. Decode the valid data slice safely into a python string
            locstr = raw_title_bytes.split(b'\x00')[0].decode('utf-8', errors='ignore').strip()
        else:
            locStr = defstr
        return locstr
        


    def get_position(self) -> Optional[Dict[str, float]]:
        """
        Get current aircraft position.
        
        Returns:
            dict: Position data (lat, lon, alt) or None if not connected
        """
        if not self.connected:
            return None
            
        try:
            # Placeholder for actual SimConnect data request
            # In full implementation, this would request:
            # PLANE LATITUDE, PLANE LONGITUDE, PLANE ALTITUDE
            return {
                "latitude": 0.0,
                "longitude": 0.0,
                "altitude": 0.0
            }
        except Exception as e:
            logger.debug(f"Error getting position: {e}")
            return None
    
    def get_heading(self) -> Optional[float]:
        """
        Get current aircraft heading (true heading).
        
        Returns:
            float: Heading in degrees, or None if not connected
        """
        if not self.connected:
            return None
            
        try:
            # Request heading from SimConnect
            return 0.0
        except Exception as e:
            logger.debug(f"Error getting heading: {e}")
            return None
    
    def get_ground_speed(self) -> Optional[float]:
        """
        Get current ground speed in knots.
        
        Returns:
            float: Ground speed in knots, or None if not connected
        """
        if not self.connected:
            return None
            
        try:
            # Request ground speed from SimConnect
            return 0.0
        except Exception as e:
            logger.debug(f"Error getting ground speed: {e}")
            return None
    
    def subscribe_to_event(self, event_id: str, callback):
        """
        Subscribe to a SimConnect event.
        
        Args:
            event_id: The event ID to subscribe to
            callback: Callback function to call when event occurs
        """
        if not self.connected:
            logger.warning("Cannot subscribe: not connected to SimConnect")
            return
            
        self._data_callback = callback
        # In full implementation, this would use SimConnect's
        # MapClientEventToSimObject and AddEventToGroup methods
        
    def request_data(self, definition_id: int = 0):
        """
        Request data from SimConnect.
        
        Args:
            definition_id: Data definition ID to request
        """
        if not self.connected:
            return
            
        # In full implementation, this would use
        # RequestDataSet and handle the response in a callback
        
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def create_simconnect_wrapper() -> SimConnectWrapper:
    """
    Factory function to create a SimConnectWrapper instance.
    
    Returns:
        SimConnectWrapper: New wrapper instance (not automatically connected)
    """
    return SimConnectWrapper()


# Example usage
if __name__ == "__main__":
    # Configure basic logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Test the wrapper
    # wrapper = create_simconnect_wrapper()
    
    # print("Testing SimConnect Wrapper...")
    # print(f"Attempting connection...")
    
    # if wrapper.connect(timeout=5):
    #     print("✓ Connected to SimConnect")
    #     print(f"  Position: {wrapper.get_position()}")
    #     print(f"  Heading: {wrapper.get_heading()}")
    #     print(f"  Ground Speed: {wrapper.get_ground_speed()}")
    #     wrapper.disconnect()
    #     print("✓ Disconnected from SimConnect")
    # else:
    #     print("✗ Could not connect to SimConnect (this is normal if MSFS is not running)")