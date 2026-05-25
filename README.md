# Virtual Flight Engineer - Flight Plan Automation for MSFS

VFE_civa_ins is a Python-based utility for **MSFS 2024** 
that automates the entry of flight plan waypoints into the **CIVA INS** navigation unit,
specifically for the **DC Designs Concorde**. The aircraft will fly under FMC control 
if a full flight plan is loaded, and INS selected, but this loses the realism of 1960's inertial navigation. This is a new application based on a previous version that used "Macro Commander" to push the buttons . This version has many new features including handling the automation natively.
 
VFE_civa_ins parses standard `.pln` files, splits them into up to 9 waypoint phases, and generates mouse-macro sequences. It manages the flight plan load, monitors progress and warns of approaching phase load.

There are 5 collapsible UI groups:
- Load Flight Plan: Allows Simbrief generated flight plan to be loaded and processed into a macro form for hotkey triggered import.
- Capture Hotkey Controls: Allows input of a wait time between mouse moves. Captures a `phase` hotkey for INS import and a `Waypoint` hotkey for display of a list of INS id, name and plan altitude.
- Calibration: Captures INS device selector and button locations and saves for subsequent use. Expects use of an **MSFS** saved custom cockpit view or **Chase Plane** equivalent for repeatable results. 
- **SimConnect** Telemetry: Uses SimConnect to monitor aircraft location, speed and altitude in relation to the flight plan. Uses location to synchronise with phases and legs to warn of approaching new phase.
- System Status: Checks and displays MSFS and SimConnect status.

The utility emulates a pilot, co-pilot 
or flight engineer keying the required waypoints manually. Entry of a single waypoint is 17 keystrokes
on the CIVA unit, thus requiring the use of automation, but through the standard INS interface. **VFE civa ins** loads a flight plan in about 90 secs.


## ⚠️ Notes and Warnings

1.  Emergency Stop: A 9-waypoint phase will contain over 1,000 lines of commands. If the macro runs out of sequence or is triggered by mistake, press `Shift + Esc` to stop the import.
`Ctrl + Alt + Del` remains your last resort for a system override.
    
2.  Target Focus: Output is targeted specifically at the MSFS process. If MSFS is not running the `system status` will change and automation operations suspended  You should ensure MSFS is running full screen and maximised.
    
3.  Macro timing: Calibrate reads the `Global Wait Time` and outputs the delay between mouse clicks. This serves several purposes: 
    - ensures the macro runs at optimal speed; 
    - ensures it is not so fast as to fail with inherent responsiveness in the UI to contend with. 100ms is recommended and is the minimum wait time.
    
5.  It is understood that during the CIVA load, no mouse or keyboard activity is possible. 

6. An optional OCR engine is built in to allow data not available through SimConnect to be acquired from the MSFS cockpit UI. In particular the `waypoint selector` is used to capture the ID . If **Python Tesseract** (https://builtin.com/articles/python-tesseract) is not installed, this facility will be disabled.

6. The project is released in source and executable format.

## Development

This project was developed through a collaborative process between the author and Google Gemini. 
- Role: Gemini assisted in advising on specific architectures for IPC, system tray app methods, developing specific functions, and optimizing logic.
- Oversight: All AI-generated code was manually reviewed, refactored, and tested to ensure it meets project needs.


## Terminology
    
- INS:      Inertial Navigation System
- Flight plan:
- Waypoint:
- NoProc:    An export form from **Simbrief Downloader** omitting SID and STAR details. (`FS2020 No SID/STAR`)
          Noproc or `MFS` version is required for CIVA_flightplan as all waypoints have a `<WorldPosition>` tag
- Phase:     Each set of up to 9 waypoints for input to the CIVA unit
- Leg: The path between consecutive waypoints.


## ✈️ Features

- **User Interface**: The VFE_civa_ins application is minimisable, UI group collapsible, MSFS state aware.
- **Parsing**: Extracts Waypoint name, Latitude, Longitude, and Elevation from MSFS XML flight plans. Parses flightplan.PDF OFP file to extract Dispatcher Remarks containing accel and decel waypoints for highlighting on waypoint message list.
- **CIVA Logic**: Coordinate formatting (CDDMMS / CDDDMMS) and specific required import sequences encoded.
- **On-Screen Feedback**: Includes audio beeps, message box with information and warnings, communication status labels.
- **Custom Calibration**: Captures control locations for saved custom views for reliable and rapid automation steps.
- **Portability**: This application could be used in other MSFS aircraft and converted to run in other simulators. The architecture changes to a more generic approach to the **flight engineer** role, allowing specialised areas such as specific cockpit checklist phases to be automated in future versions.
- **Minimal Footprint**: SimConnect telemetry refresh requires only a 10 sec cycle. Other threads trigger on user request. May be minimised between phase loads,
- **System tray**: A small program **VFEtray** is started by **VFE_civa_ins** in the system tray to action the automation. It uses IPC to pass status changes to **VFE_civa_ins** for dialogue displays in MSFS as required.
- **Settings preserved** between runs. The previous imported flight plan, calibration, hotkeys and other settings restored

## 🛠️ Requirements

- **Fplans folder** where you normally direct generated flight plans from **Simbrief**, or similar. A sub-folder, `\phases` will be created by the application for the generated plans.
- **MSFS** 
  The `Cockpit Interaction System` Flight Interface setting must be set to `Lock`. Single scroll on
  the waypoint selector fails if `Legacy` is used.
- **Simbrief Downloader**: Ensure the MSFS 2020 versions are selected for output as these include the `<WorldPosition>` tag.
  
>   [!NOTE]
>  If the `FMC` display is visible next to the pilot INS, 
>  the `Auto-Man` switch must be set to `Man` to operate under `INS`. This should be   
>  done every flight as the default is auto. On the `INS` unit, the `Auto-Man` switch should 
>  be set to `Auto` to automatically transition to the next waypoint.

## 🚀 Installation & Setup

1. **Download** this release to a project folder of your choice.

2. **Install Dependencies** If the optional OCR detection of INS state is required, install **Python Tesseract** from https://builtin.com/articles/python-tesseract The VFE application will detect and use.
   
3. Start **VFE_civa_ins** as 'Administrator', Right-click on the vfe_civa_ins.exe file > Properties > Compatibility > **Run as administrator**. The application will run **on top** of MSFS. Collapse UI sections not required.

4. In MSFS, zoom to the CIVA unit with your saved view. 

4. **Capture Hotkey Controls** 

    i. Set the mouse move and click wait time. 100 msecs is recommended. 

    ii. Click `Capture Phase Hotkey` and enter a key combination ending in "1" eg "ctrl+shift+1" for the first phase. 

    iii. Click `Capture Waypoint Hotkey` and enter a key combination ending in "F1" eg "ctrl+shift+F1" for the first phase. This is used to display a small dialogue summary of the waypoints in the corresponding phase. eg F3 for phase 3. 

    iv. The hotkeys are armed when Group 1 > `Process Flight Plan` is selected. 

    v. This once-only step has been completed and`Group 2` can be unchecked.
    
5. **Calibrate**: 

	i. Create a view in MSFS (Chase Plane is a good option here) that shows the pilot CIVA INS 
	   filling the screen height. Ensure the view is repeatable.

    ii. Click `Run Calibration` and follow the prompts to `left mouse click` on each named button or selector in turn. The 2,4,6,8 buttons provide the cardinal directions N, W, S, E and only need recording once.
    
    iii. When complete, click on `Confirm Save`.
    
    iv. This once-only step has been completed and the `Group 3: Calibration` group can be unchecked. Rerun if view changes. Display scale or screen resolution changes should not affect the calibration.
    
    
> [!NOTE] 
>   The effective use of the rotary waypoint selector requires
>      a `{move to selector}{mouse click}{mouse wheel forward}{mouse click}`
>      sequence to prevent a stray mouse wheel movement changing the screen view.
>      This control template is implemented by the calibrate script.
>      

6.  **Simbrief Downloader**: Modify the `Formats to Download` list to include:

- PDF Document: for oceanic segment highlight
- FS2020: to include departure and arrival waypoints in the INS load
- FS2020 (No SID/STAR): (more realistically) to exclude SID and STAR waypoints from the INS 
- FS2024: for conventional EFB flight plan import in MSFS (for ATC, BeyondATC... etc)

## 📖 How to setup each flight plan

1. Simbrief flight plan: Concorde flight plan needs to reflect acceleration and deceleration restrictions to ensure subsonic flight over land. In Simbrief this can be achieved with **Dispatcher Remarks**. Edit this section before the generate. The inflight waypoint list dialogue will highlight the oceanic flight segment between the accel and decel waypoints. The following format will be read and decoded from a PDF downloader output file:
```
    ACCEL: PACSE
    DECEL: 4027N07230W
```


2. Start MSFS. There is no need to load the flight plan via the EFB unless native ATC is required.A Simbrief generated plan will be available to external ATC apps. 

2. `Import FLight Plan` Select your MSFS .pln flight plan when prompted. (eg EGLLKJFK_MFS_25Apr26.pln or EGLLKJFK_MFS_NoProc_25Apr26.pln).

3. `Process Flight Plan` loads calibration data, splits each flight plan into 9 waypoint phases and saves to the `/phases`. Each split plan can be loaded using MSFS EFB, but this is not required for CIVA INS use. Finally, it arms the hotkeys for each plan phase.

   
## 📖 How to load each flight plan phase in MSFS

> [!TIP]
>       A useful upgrade to the 
>       INS unit including the Alert light and other significant improvements 
>       to the aircraft can be found in the addon:
>   "https://flightsim.to/addon/94824/dc-designs-concorde-systems-enhancement"

1.  Prerequisites for waypoint entry are:

	  i. Cold and dark checklist including rightmost Engineers Panel, power and hydrauics, Mode Selector Unit (MSU) to NAV.

      ii. The CIVA INS (C/DU) on .

      iii. Eight position `data selector` set to `WAY PT`. This is handled by **VFE**

      iv. `Waypoint/DME` selector set to zero. **This must be set manually.**, but a warning will be displayed on VFE if it is not 0.

2. Set the CIVA view.
	    
    i. **Prepare Device**: Set `Auto-Man` INS selector to `Auto` for automatic leg transition. If `FCU` on the right of the INS is visible set same switch to `Man` to cede flight plan control to the INS.
    > This is an important step as if the full flight plan is loaded via the EFB, the FCU will control the plan if FCU-AUTO is selected.
    
    ii. **Import**: Hit the hotkey `Ctrl + Shift + 1` for phase 1 and watch  the points load for the first phase.
    When complete, use `Ctrl + Shift + F1` at any time to display a message box with each waypoint number, name and elevation.

	iii. **Arm Direct-To**: Manually click `Wy Pt Chg` button and select 0 to 1 (or the desired waypoint id for a `direct to` INS navigation direction, and `Insert`. The `From-To` display will change. The CIVA convention `current location:0` to `waypoint number` should be used to initiate the device for the first phase from the end of the SID, for example. The INS will also select an intercept with a leg, with a non-zero `from`.

	iv. **Switch AP to INS nav**: Clear `Hdg Hld`, select `INS Navigation` and hit `INS` on the AP panel.

3.  For subsequent phases, 
	follow steps 2.ii and 2.iii for subsequent phases with `Ctrl + Shift + 2,3...`.

## 📁 Using Radio Navigation In Conjunction with INS

The switch between radio nav and INS with an INS flight plan loaded should require:

    To VOR NAV
    1.  Set AFCS panel `HDG HLD` to maintain current heading.
    2.  Switch `Radio/INS` nav selector to `Rad`.
    3.  Switch `Nav1/Stand-by` selector to the VOR frequency of the beacon.
    4.  Set AFCS panel, `INS` off, `TRK HDG` to desired mode.
    5.  Use AFCS, `course` knob to adjust required radial.
    6.  If multiple VORs to be tuned, use the co-pilot nav selector and the pilot's Nav 1/2 switch.
    
    There seem to be some issues in VOR beacon frequency setup in current version 1.1.2 of Concorde.
    The DME1 indicator appears to be connected to the stand-by frequency.
    The VOR/DME distance display is the best indicator as to correct tuning.
    
    To INS
    
    1.  Switch `Radio/INS` nav selector to `INS`.
    2.  Set AFCS panel, `INS` on.
    3.  Select the `From-To` selector on the INS to `0-required waypoint` using the method in 2.ii above.
    
	
## 📁 Project Structure

1.  VFE_civa_ins.exe and VFEtray.exe

2.  `Videos` folder for setup and use assistance.
    i.  CalibrationStep.mkv
    ii.  FlightPlanProcess.mkv
    iii.  FlightPlanLoad.mkv
    iv.  CIVAInFlightUse.mkv

8.  `tests\EGLLKJFK_MFS_NoProc_18Apr26.pln` and PDF: 

    A sample classic **Simbrief** flight plan used for testing.
    Modified as some original waypoints no longer exist. 
    This departure was used by Concorde as it allowed acceleration to supersonic flight phase over 
    the Bristol Channel. The CPT3F departure has been expanded in the "Selected Route" section 
    of the Simbrief edit page, although the VOR navigation departure is more interesting and typical. 

```
EGLL D255G D259K WOD D100H CPT/F060 KENET UNZIB/F150 D149T/F280 BHD57 LESLU/F500 
5041N01500W 5050N02000W 5030N03000W 4916N04000W 4703N05000W 4610N05300W 4414N06000W 
4246N06500W 4200N06700W 4044N06955W 4027N07230W CAMRN KJFK
```
This could be placed in the flight plans Simbrief export folder as an example.

> [!NOTE] 
>   Simbrief does not recognise Concorde performance data and produces erroneous altitude predictions.
>   A workaround is to use the wypt/Fnnn syntax to advise departure restriction, supersonic acceleration points
>   and expected cruise altitude waypoint altitudes. To calculate a TOD with these minimal inputs. Simbrief will not accept flight level constraints on descent.
>   To assist vertical profile planning, these altitudes will be displayed alongside the waypoint name
>   in the onscreen dialogue attached to each phase.
    
## 🚀 Roadmap
- [ ] Add usage videos
- [ ] Test in FSS B727
- [X] Add a popup message or a kneepad note to name waypoints as the `from-to` selector progresses.
- [ ] An option to push a set of named waypoints on the fly for a diversion would be appealing, with a lookup to find the coordinates. This could involve some interaction with the EFB.
- [ ] Extend to handle generic checklist named panel automation.

## ⚖️ License

This project is licensed under the MIT License.

## System Architecture Summary Block

Use this summary to initialise chat thread with Gemini or similar with follow on enhancements (note: this was generated by Gemini and is heavy in random details and light in conceptual summary but probably worthwhile as a starting point):

Act as a Senior Win32 C and PyQt5 Python Software Engineer. We are developing "VFE" (Virtual Flight Engineer), a high-speed cockpit automation platform for Microsoft Flight Simulator. Do not explain basics. Maintain the following architectural context:

1. VFEui (Python / PyQt5): Handles UI configuration, settings JSON, flight plan parsing, and global keyboard hotkey capturing. It remains Per-Monitor DPI Aware. It manages window loops and layout updates natively.
2. VFEtray (Native x64 C): A headless, elevated background utility living in the system tray, compiled via MSVC (cl.exe) with /subsystem:windows. It utilizes a native Win32 window loop (WndProc) to intercept custom IPC window messages from VFEui.
3. Thread-Safe IPC Bridge: 
   - VFEui triggers macro or UI tasks by dispatching direct PostMessage strings to VFEtray's HWND.
   - VFEui uses a QTimer polling loop (100ms) watching for "vfe_msg.trigger" or "vfe_dialogue.trigger" token files written by VFEtray to %APPDATA%\VFE\.
   - All internal Python UI logging (logProgressBox) and QDialog generation routines are strictly decoupled from background threads using class-level pyqtSignals (request_log_update, request_inline_msg_ui) to guarantee complete thread safety.
4. Input Engine: VFEtray processes macro text instructions line-by-line using custom absolute hardware mouse array parsing loops (SendInput with MOUSEEVENTF_VIRTUALDESK) to support 4K layouts, multi-monitor spans, and custom high-DPI scaling steps smoothly.
5. Macro Language Specs: Supports {mouse move} [smooth travel pathing], {wait} (ms) [interruptible sleep slices], {mousedown}, {mouseup} [coordinate-locked persistent mouse states via MOUSEEVENTF_MOVE], {mouse wheel forward}, {mouse wheel back}, and inline {message} commands. Left-Escape + Left-Shift interrupt instantly signals g_abortExecution to wipe the hardware queue.
6. Target Window Locking: GetHwndByPartialTitle performs a substring search for "Microsoft Flight Simulator".

Acknowledge this architecture simply as "VFE Context Initialised." and wait for my next coding requirement.
