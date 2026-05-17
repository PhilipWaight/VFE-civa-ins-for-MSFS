//cl VFEtray.c /O2 /Fe:VFEtray.exe user32.lib shell32.lib gdi32.lib /link /subsystem:windows /entry:WinMainCRTStartup

#define PSAPI_VERSION 1  // Forces MSVC to link standard GetModuleBaseName layout
#define _WIN32_WINNT 0x0600
#define _CRT_SECURE_NO_WARNINGS

#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>
#include <psapi.h>      // Explicitly includes process memory structures
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


// Struct to hold lookup criteria and the resulting window handle
typedef struct {
    const char* targetExe;
    HWND foundHwnd;
} FindWindowData;

#define WM_TRAYICON (WM_USER + 1)
#define ID_TRAY_EXIT 1001
#define ID_TRAY_RUN  1002

// Custom Inter-Process Communication Messages from Python UI
#define WM_VFE_EXECUTE_PHASE (WM_USER + 10) // wParam = Phase Number (1-9)
#define WM_VFE_DISPLAY_INFO  (WM_USER + 11) // wParam = Waypoint Number (1-9)

NOTIFYICONDATAA nid;
HWND g_hWnd = NULL;
int g_virtualLeft = 0;
int g_virtualTop = 0;
int g_virtualWidth = 0;
int g_virtualHeight = 0;
volatile BOOL g_abortExecution = FALSE;
char appdataBuffer[MAX_PATH] = {0};
char outstr[MAX_PATH];
int g_firstRun = 1;


// Dynamically expands environment variables like %appdata% to full folder strings
void GetVFEAppdataPath(const char* filename, char* outPath) {
    
    // Natively fetches the target Roaming directory path string
    GetEnvironmentVariableA("APPDATA", appdataBuffer, MAX_PATH);

    // Constructs the absolute location target string safely
    sprintf(outPath, "%s\\msfsVFE\\%s", appdataBuffer, filename);
}

void writeLog(const char* format, ...) {
    char messageBuffer[1024];
    char timeBuffer[64];
    SYSTEMTIME st;
    char outPath[MAX_PATH];

    sprintf(outPath, "%s\\msfsVFE\\%s", appdataBuffer, "engine_debug.log");

    // 1. Fetch the precise Windows system local time matrix
    GetLocalTime(&st);

    // 2. Format the timestamp: [YYYY-MM-DD HH:MM:SS.ms]
    sprintf(timeBuffer, "[%04d-%02d-%02d %02d:%02d:%02d.%03d] ",
            st.wYear, st.wMonth, st.wDay, 
            st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);

    // 3. Parse your incoming printf style custom string messages
    va_list args;
    va_start(args, format);
    vsprintf(messageBuffer, format, args);
    va_end(args);

    // 4. Open and append cleanly to your debug text repository
    FILE* logFile = fopen(outPath, "a");
    if (logFile) {
        // Print the timestamp block followed instantly by your log message
        fprintf(logFile, "%s%s", timeBuffer, messageBuffer);
        fclose(logFile);
    }
}


// High-precision mouse packet injector mapping virtual space
void SendHardwareMouse(int x, int y, DWORD flags, DWORD data) {
    INPUT input = {0};
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)((double)(x - g_virtualLeft) * (65536.0 / (double)g_virtualWidth));
    input.mi.dy = (LONG)((double)(y - g_virtualTop) * (65536.0 / (double)g_virtualHeight));
    input.mi.dwFlags = flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
    input.mi.mouseData = data;

    // --- LOW LEVEL PACKET TRACKER ---
    // Logs exactly what actions are reaching the Windows Input Queue
    if (flags & MOUSEEVENTF_LEFTDOWN) {
        writeLog("INPUT_QUEUE: Left DOWN dispatched to Pixel (%d, %d) | Mickeys (%ld, %ld)\n", x, y, input.mi.dx, input.mi.dy);
    }
    if (flags & MOUSEEVENTF_LEFTUP) {
        writeLog("INPUT_QUEUE: Left UP dispatched to Pixel (%d, %d) | Mickeys (%ld, %ld)\n", x, y, input.mi.dx, input.mi.dy);
    }
    
    SendInput(1, &input, sizeof(INPUT));
}

// Linear path interpolation tool to force cursor render streams 
void SmoothMouseMove(int targetX, int targetY, int durationMs) {
    POINT curPos;
    GetCursorPos(&curPos);
    int startX = curPos.x;
    int startY = curPos.y;

    int steps = (durationMs > 16) ? (int)(durationMs / 10) : 1; 
    int stepDelay = durationMs / steps;

    for (int i = 1; i <= steps; i++) {
        // High-frequency Shift-Esc interrupt trap
        if ((GetAsyncKeyState(VK_ESCAPE) & 0x8000) && (GetAsyncKeyState(VK_SHIFT) & 0x8000)) {
             g_abortExecution = TRUE;
             return;
        }
        double t = (double)i / (double)steps;
        int currentX = (int)(startX + (targetX - startX) * t);
        int currentY = (int)(startY + (targetY - startY) * t);
        SendHardwareMouse(currentX, currentY, MOUSEEVENTF_MOVE, 0);
        Sleep(stepDelay);
    }
    SendHardwareMouse(targetX + 1, targetY + 1, MOUSEEVENTF_MOVE, 0);
    SendHardwareMouse(targetX, targetY, MOUSEEVENTF_MOVE, 0);
}

// Macro file handler with sequential termination traps
void ExecuteMacroFile(const char* filepath) {
    FILE* file = fopen(filepath, "r");
    if (!file) {
        writeLog("ERROR: Cannot open macro file path: %s\n", filepath);
        return;
    }

    g_abortExecution = FALSE;
    char line[256];
    int commandCount = 0;
    
    while (fgets(line, sizeof(line), file) && g_abortExecution == FALSE) {
        commandCount++;
        
        // 1. Structural cleanup: Strip newlines
        line[strcspn(line, "\r\n")] = 0;
        
        // --- NEW: STRIP TRAILING IN-LINE COMMENTS ---
        // Find the first instance of a comment tag anywhere on the line
        char* comment_ptr = strstr(line, "<#>");
        if (comment_ptr != NULL) {
            *comment_ptr = '\0'; // Truncate the string at the comment start
        }
        // --------------------------------------------

        // Trim trailing spaces left over after stripping the comment
        int len = (int)strlen(line);
        while(len > 0 && (line[len-1] == ' ' || line[len-1] == '\t')) {
            line[len-1] = 0;
            len--;
        }

        // Skip the line if it is now completely empty
        if (line[0] == '\0') continue;

        writeLog("PARSER: Processing Command Line %d: '%s'\n", commandCount, line);

        // 2. Mouse Move Command: <mm>(x,y,msecs)
        int mx, my, msecs;
        if (sscanf(line, "<mm>(%d,%d,%d)", &mx, &my, &msecs) == 3) {
            SmoothMouseMove(mx, my, msecs);
            continue;
        }

        // 3. Wait Window Command: <wx>(msecs,0)
        int wx_ms, dummy;
        if (sscanf(line, "<wx>(%d,%d)", &wx_ms, &dummy) == 2) {
            int slices = wx_ms / 10;
            for(int s=0; s<slices; s++) {
                if ((GetAsyncKeyState(VK_ESCAPE) & 0x8000) && (GetAsyncKeyState(VK_SHIFT) & 0x8000)) { g_abortExecution = TRUE; break; }
                Sleep(10);
            }
            continue;
        }

        // 4. Left Button Down Command: <mlbd> (Now works flawlessly with trailing comments!)
        if (_stricmp(line, "<mlbd>") == 0) {
            POINT p; GetCursorPos(&p);
            SendHardwareMouse(p.x, p.y, MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN, 0);
            continue;
        }

        // 5. Left Button Up Command: <mlbu>
        if (_stricmp(line, "<mlbu>") == 0) {
            POINT p; GetCursorPos(&p);
            SendHardwareMouse(p.x, p.y, MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP, 0);
            continue;
        }

        // 6. Scroll Forward: <mwheel_f>
        if (_stricmp(line, "<mwheel_f>") == 0) {
            POINT p; GetCursorPos(&p);
            SendHardwareMouse(p.x, p.y, MOUSEEVENTF_WHEEL, WHEEL_DELTA);
            continue;
        }

        // 7. Scroll Backward: <mwheel_b>
        if (_stricmp(line, "<mwheel_b>") == 0) {
            POINT p; GetCursorPos(&p);
            SendHardwareMouse(p.x, p.y, MOUSEEVENTF_WHEEL, (DWORD)(-WHEEL_DELTA));
            continue;
        }
        // Streamlined Target: <msg>(x, y, "text", "title", buttons, timeout, type, ontop, w_pct, h_pct)
        // eg <msg>(100,100, "WP: EGLL Pos: N51° 28' 39.00,W0° 27' 41.00", "World pos tag", 0, 10, 0, 0, 20%, 10%)
        if (strncmp(line, "<msg>", 5) == 0) {
            int mx = 100, my = 100, buttons = 1, timeout = 0, mtype = 0, ontop = 1, w_pct = 25, h_pct = 20;
            char textBuf[2048] = {0};
            char titleBuf[256] = {0};
            writeLog("In msg\n");
            char* first_quote = strchr(line, '"');
            char* last_quote = strrchr(line, '"');

            if (first_quote && last_quote && last_quote > first_quote) {
                // Find inner structural quote groups using basic boundary checks
                char* title_end = last_quote;
                char* title_start = title_end - 1;
                while (title_start > first_quote && *title_start != '"') title_start--;
                
                char* text_end = title_start - 1;
                while (text_end > first_quote && *text_end != '"') text_end--;
                char* text_start = first_quote;

                if (text_start && text_end && title_start && title_end && text_end > text_start && title_end > title_start) {
                    // Pull raw inline strings safely
                    size_t text_len = text_end - text_start - 1;
                    if (text_len > 2047) text_len = 2047;
                    strncpy(textBuf, text_start + 1, text_len);
                    textBuf[text_len] = '\0';

                    size_t title_len = title_end - title_start - 1;
                    if (title_len > 255) title_len = 255;
                    strncpy(titleBuf, title_start + 1, title_len);
                    titleBuf[title_len] = '\0';

                    // Scan the remaining integer properties
                    sscanf(title_end + 1, " , %d , %d , %d , %d , %d%% , %d%%)", 
                           &buttons, &timeout, &mtype, &ontop, &w_pct, &h_pct);

                    // Drop the parsed parameters into the shared state file
                    char msgPath[MAX_PATH];
                    GetVFEAppdataPath("current_msg.json", msgPath);
                    
                    FILE* msgFile = fopen(msgPath, "w");
                    if (msgFile) {
                        fprintf(msgFile, "{\n");
                        fprintf(msgFile, "  \"x\": %d, \"y\": %d,\n", mx, my);
                        fprintf(msgFile, "  \"html\": \"%s\",\n", textBuf);
                        fprintf(msgFile, "  \"title\": \"%s\",\n", titleBuf);
                        fprintf(msgFile, "  \"buttons\": %d, \"timeout\": %d,\n", buttons, timeout);
                        fprintf(msgFile, "  \"type\": %d, \"ontop\": %d,\n", mtype, ontop);
                        fprintf(msgFile, "  \"w_pct\": %d, \"h_pct\": %d\n", w_pct, h_pct);
                        fprintf(msgFile, "}");
                        fclose(msgFile);
                        writeLog("Send vfe_msg trigger\n");
                        // Fire the Python UI alert trigger
                        FILE* tFile = fopen("vfe_msg.trigger", "w");
                        if (tFile) {
                            fprintf(tFile, "1");
                            fclose(tFile);
                        }
                    }
                }
            } else {
                writeLog("PARSER_WARNING: Inline <msg> block quoting error.\n");
            }
            continue;
        }
        
        writeLog("PARSER_WARNING: Command unparsed or unknown format line %d: '%s'\n", commandCount, line);
    }
    if (g_abortExecution == TRUE) {
        writeLog("Interrupted by shift+esc\n");
    }
        
    fclose(file);
}


// Callback to find the window by partial title match
BOOL CALLBACK EnumWindowsTitleCallback(HWND hwnd, LPARAM lParam) {
    FindWindowData* data = (FindWindowData*)lParam;
    
    // 1. Only look at visible, top-level main windows
    if (!IsWindowVisible(hwnd)) return TRUE;

    char titleBuffer[256] = {0};
    GetWindowTextA(hwnd, titleBuffer, sizeof(titleBuffer));

    // 2. Perform a partial case-insensitive string match
    // Checks if the window title starts with "Microsoft Flight Simulator"
    if (_strnicmp(titleBuffer, data->targetExe, strlen(data->targetExe)) == 0) {
        // Double check it's a real interactive window frame, not a background ghost
        RECT rect;
        GetWindowRect(hwnd, &rect);
        int width = rect.right - rect.left;
        int height = rect.bottom - rect.top;

        // Ensure the window actually has size (filters out hidden telemetry windows)
        if (width > 100 && height > 100) {
            data->foundHwnd = hwnd;
            return FALSE; // Found the true 3D window frame! Stop enumerating.
        }
    }
    return TRUE; // Keep looking
}

// Bypasses dynamic version trailing strings by scanning the UI title roots
HWND GetHwndByPartialTitle(const char* partialTitle) {
    FindWindowData data;
    data.targetExe = partialTitle;
    data.foundHwnd = NULL;

    EnumWindows(EnumWindowsTitleCallback, (LPARAM)&data);
    return data.foundHwnd;
}

void ActivateSimulatorWindow() {
    // Look for the base parent window title root (ignores the trailing version suffix)
    HWND msfsHwnd = GetHwndByPartialTitle("Microsoft Flight Simulator");

    if (msfsHwnd) {
        if (IsIconic(msfsHwnd)) {
            ShowWindow(msfsHwnd, SW_RESTORE);
        }
        
        // Bring the true 3D viewport canvas to the active foreground
        SetForegroundWindow(msfsHwnd);
        BringWindowToTop(msfsHwnd);
        
        // Reassert the click-focus tokens required by the cockpit overlay layout
        SendMessage(msfsHwnd, WM_ACTIVATE, WA_CLICKACTIVE, 0);
        Sleep(300); 
    } else {
        // Output cleanly to your debug log if the simulation layout isn't loaded
        writeLog("ERROR: Microsoft Flight Simulator target interface window not found.\n");
    }
}


// 2. Corrected Window Procedure
LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {

    if (msg == WM_TRAYICON) {
     
        if (lParam == WM_RBUTTONUP) {
            POINT curPoint; GetCursorPos(&curPoint);
            HMENU hMenu = CreatePopupMenu();
            AppendMenuA(hMenu, MF_STRING, ID_TRAY_RUN, "Execute debug macro.txt");
            AppendMenuA(hMenu, MF_STRING, ID_TRAY_EXIT, "Exit VFE Engine");
            SetForegroundWindow(hWnd);
            TrackPopupMenu(hMenu, TPM_BOTTOMALIGN | TPM_LEFTALIGN, curPoint.x, curPoint.y, 0, hWnd, NULL);
            DestroyMenu(hMenu);
        }
        return 0;
    }
    
    if (msg == WM_COMMAND) {
        if (LOWORD(wParam) == ID_TRAY_RUN) {
            char absolutePath[MAX_PATH];
            if (g_firstRun == 1) {writeLog("VFEtray v1.0.0\n");g_firstRun--;} 

            GetVFEAppdataPath("macro.txt", absolutePath); 
            //writeLog("VFEtray v1.0.0\n");
            writeLog("Running debug macro: %s\n", absolutePath);
            
            ActivateSimulatorWindow();
            ExecuteMacroFile(absolutePath);
        }
        else if (LOWORD(wParam) == ID_TRAY_EXIT) {
//            if (g_firstRun == 1) {writeLog("VFEtray v1.0.0\n");g_firstRun--;}             
            Shell_NotifyIconA(NIM_DELETE, &nid);
            PostQuitMessage(0);
        }
        return 0;
    }

    // Phase Execution Target Command Handler Update
    if (msg == WM_VFE_EXECUTE_PHASE) {
        int phase_num = (int)wParam;
        char macroFilename[64];
        char absolutePath[MAX_PATH];
        if (g_firstRun == 1) {writeLog("VFEtray v1.0.0\n");g_firstRun--;}             
        // Build filename string
        sprintf(macroFilename, "macro_p%d.txt", phase_num);
        
        // Resolve absolute %APPDATA%\msfsVFE\macro_pX.txt location
        GetVFEAppdataPath(macroFilename, absolutePath);
        
        ActivateSimulatorWindow();
        ExecuteMacroFile(absolutePath); // Parses macro from Appdata folder
        return 0;
    }


    if (msg == WM_VFE_DISPLAY_INFO) {
        int wp_num = (int)wParam;
        FILE* triggerFile = fopen("vfe_dialogue.trigger", "w");
        if (triggerFile) {
            fprintf(triggerFile, "%d", wp_num);
            fclose(triggerFile);
        }
        return 0;
    }

    return DefWindowProc(hWnd, msg, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    SetProcessDPIAware();
    g_virtualLeft = GetSystemMetrics(SM_XVIRTUALSCREEN);
    g_virtualTop = GetSystemMetrics(SM_YVIRTUALSCREEN);
    g_virtualWidth = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    g_virtualHeight = GetSystemMetrics(SM_CYVIRTUALSCREEN);

    WNDCLASSEXA wc = {0};
    wc.cbSize = sizeof(WNDCLASSEXA);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = "VFEEngineTrayClass";
    wc.hIcon = LoadIconA(hInstance, MAKEINTRESOURCEA(101));
    RegisterClassExA(&wc);

    g_hWnd = CreateWindowExA(0, "VFEEngineTrayClass", "VFE Tray Engine", 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, hInstance, NULL);

    memset(&nid, 0, sizeof(NOTIFYICONDATAA));
    nid.cbSize = sizeof(NOTIFYICONDATAA);
    nid.hWnd = g_hWnd;
    nid.uID = 1;
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    nid.uCallbackMessage = WM_TRAYICON;
    //nid.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    nid.hIcon = LoadIconA(hInstance, MAKEINTRESOURCEA(101));
    strcpy(nid.szTip, "Virtual Flight Engineer");
    Shell_NotifyIconA(NIM_ADD, &nid);
    
  // 5. THE FIX: Clear the log file and print the header here
    // This ensures paths are ready and we don't overwrite our own data
    char logPath[MAX_PATH];
    GetVFEAppdataPath("engine_debug.log", logPath);
    FILE* fClear = fopen(logPath, "w"); // Explicitly wipe previous run logs
    if (fClear) fclose(fClear);

    // Now write the startup header securely
    writeLog("=========================================\n");
    writeLog(" VFEtray Subsystem v1.0.0 Online\n");
    writeLog(" Screen Canvas: %dx%d (Offset: %d,%d)\n", g_virtualWidth, g_virtualHeight, g_virtualLeft, g_virtualTop);
    writeLog("=========================================\n");    
    
    
    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
    
    return (int)msg.wParam;
}
