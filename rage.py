import tkinter as tk
import ctypes
from ctypes import wintypes
import random
import time
import threading
import winsound
import math

# --- Windows API Definitions ---
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT)
    ]

def get_caret_position():
    """Get absolute screen coordinates of the text cursor."""
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    
    # Get foreground window thread
    hwnd = user32.GetForegroundWindow()
    if not hwnd: return None
    
    thread_id = user32.GetWindowThreadProcessId(hwnd, None)
    
    # Attach input processing mechanism to that thread
    # Note: AttachThreadInput is tricky, but often needed for GetGUIThreadInfo across processes.
    # We'll try without first, as AttachThreadInput can cause lag/issues.
    # Actually, GetGUIThreadInfo works better if we pass the thread ID of the foreground window.
    
    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(gti)):
        if gti.hwndCaret:
            point = wintypes.POINT(gti.rcCaret.left, gti.rcCaret.top)
            user32.ClientToScreen(gti.hwndCaret, ctypes.byref(point))
            return (point.x, point.y + (gti.rcCaret.bottom - gti.rcCaret.top)//2) # Center Y
    return None

# --- Application ---

class RageApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Rage Mode")
        
        # Fullscreen Transparent Overlay
        self.width = self.root.winfo_screenwidth()
        self.height = self.root.winfo_screenheight()
        self.root.geometry(f"{self.width}x{self.height}+0+0")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-transparentcolor', 'black')
        self.root.config(bg='black')
        
        # Click-through
        self.make_click_through()
        
        self.canvas = tk.Canvas(self.root, width=self.width, height=self.height, bg='black', highlightthickness=0)
        self.canvas.pack()
        
        # State
        self.particles = []
        self.rage_meter = 0.0
        self.last_key_time = time.time()
        self.shake_offset = (0, 0)
        
        # Keys to monitor (Simple polling for A-Z, Space, Enter)
        self.keys_to_poll = [i for i in range(0x41, 0x5A + 1)] # A-Z
        self.keys_to_poll.extend([0x20, 0x0D, 0x08]) # Space, Enter, Backspace
        self.key_states = {k: False for k in self.keys_to_poll}
        
        self.root.bind('<Escape>', self.quit)
        
        # Start Threads
        self.running = True
        threading.Thread(target=self.input_loop, daemon=True).start()
        
        self.animate()
        self.root.mainloop()

    def make_click_through(self):
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def quit(self, event):
        self.running = False
        self.root.destroy()

    def play_sound(self, filename):
        def sound_worker():
            alias = f"sound_{random.randint(0, 1000000)}"
            # Use absolute path or relative? Relative to CWD is safer if run from there.
            # But mci often needs full paths or standard paths.
            # Let's try relative first, if fails we get full path.
            import os
            filepath = os.path.abspath(filename)
            
            # Open
            cmd_open = f'open "{filepath}" type mpegvideo alias {alias}'
            user32 = ctypes.windll.user32
            winmm = ctypes.windll.winmm
            
            # Send string signature: LPCWSTR, LPWSTR, UINT, HWND
            winmm.mciSendStringW(cmd_open, None, 0, 0)
            
            # Play
            winmm.mciSendStringW(f'play {alias}', None, 0, 0)
            
            # Wait for approx duration then close? 
            # Or just wait a safe amount (2 sec) then cleanup
            time.sleep(1.0) 
            winmm.mciSendStringW(f'close {alias}', None, 0, 0)

        threading.Thread(target=sound_worker, daemon=True).start()

    def input_loop(self):
        """Polls for key presses."""
        backspace_repeat_time = 0
        while self.running:
            active = False
            current_time = time.time()
            
            for k in self.keys_to_poll:
                # check most significant bit for key down
                state = user32.GetAsyncKeyState(k) & 0x8000
                if state:
                    # Special case: Backspace repeats while held
                    if k == 0x08: # Backspace
                        if current_time - backspace_repeat_time > 0.08: # ~12 repeats/sec
                            self.on_key_press(k)
                            backspace_repeat_time = current_time
                            active = True
                    elif not self.key_states[k]:
                        self.key_states[k] = True
                        self.on_key_press(k)
                        active = True
                else:
                    self.key_states[k] = False
            
            # Rage decay
            if not active:
                self.rage_meter = max(0, self.rage_meter - 0.5)
                
            time.sleep(0.01)

    def on_key_press(self, key_code):
        # Check Caps Lock (low order bit 1 = toggled)
        caps_on = user32.GetKeyState(0x14) & 0x0001
        # Check Shift (high order bit 1 = down)
        shift_down = user32.GetAsyncKeyState(0x10) & 0x8000
        
        is_uppercase = caps_on or shift_down
        
        if not is_uppercase:
            # User requested NO sound and NO shake for small letters.
            # We just return early, or maybe decrease rage?
            # Let's effectively ignore lowercase for "Rage" purposes.
            return

        # Boost rage faster if uppercase
        boost = 20 if is_uppercase else 10
        self.rage_meter = min(100, self.rage_meter + boost)
        
        # Specific sounds
        if key_code == 0x0D: # Enter
            self.play_sound("enter.mp3")
            self.spawn_explosion(None, None, intensity_mult=3.0) 
        elif key_code == 0x20: # Space
            self.play_sound("space.mp3") 
            self.spawn_explosion(None, None, intensity_mult=0.5)
        elif key_code == 0x08: # Backspace
            self.play_sound("backspace.mp3")
            self.spawn_explosion(None, None, intensity_mult=1.5)
        else:
            self.play_sound("key.mp3")
            # Bigger fire for uppercase
            mult = 2.0 if is_uppercase else 1.0
            self.spawn_explosion(None, None, intensity_mult=mult)
        
        self.trigger_shake(force=is_uppercase)

    def trigger_shake(self, force=False):
        # Screen shake intensity based on rage
        intensity = min(30, 8 + self.rage_meter / 4)
        
        # 1. Shake the overlay particles (visual)
        self.shake_offset = (
            random.randint(-int(intensity), int(intensity)),
            random.randint(-int(intensity), int(intensity))
        )
        self.root.after(50, lambda: setattr(self, 'shake_offset', (0,0)))
        
        # 2. Shake the ACTUAL ACTIVE WINDOW (physical)
        # Verify drift is fixed logic is present below...
        # Force shake if uppercase, even if rage is low
        if force or self.rage_meter > 20:
             self.shake_active_window(intensity)

    def shake_active_window(self, intensity):
        hwnd = user32.GetForegroundWindow()
        if not hwnd or hwnd == self.root.winfo_id(): 
            return # Don't shake self or nothing
        
        # Initialize active_shakes dict if not present
        if not hasattr(self, 'active_shakes'):
            self.active_shakes = {}

        # If we are already shaking this window, use its KNOWN ORIGINAL position.
        # Otherwise, capture current position as original.
        if hwnd in self.active_shakes:
            original_rect = self.active_shakes[hwnd]['rect']
            # Cancel pending restore because we are about to shake again
            timer = self.active_shakes[hwnd].get('timer')
            if timer:
                try:
                    self.root.after_cancel(timer)
                except:
                    pass
        else:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            original_rect = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            self.active_shakes[hwnd] = {'rect': original_rect, 'timer': None}

        origin_x, origin_y, width, height = original_rect
        
        # Random offset from ORIGINAL
        dx = random.randint(-int(intensity), int(intensity))
        dy = random.randint(-int(intensity), int(intensity))
        
        flags = 0x0001 | 0x0004 | 0x0010 # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        
        # 1. Apply Shake
        user32.SetWindowPos(hwnd, 0, origin_x + dx, origin_y + dy, width, height, flags)
        
        # 2. Schedule Restore
        def restore():
            user32.SetWindowPos(hwnd, 0, origin_x, origin_y, width, height, flags)
            if hwnd in self.active_shakes:
                del self.active_shakes[hwnd]
            
        timer_id = self.root.after(50, restore)
        if hwnd in self.active_shakes:
            self.active_shakes[hwnd]['timer'] = timer_id

    def spawn_explosion(self, x, y, intensity_mult=1.0):
        if x is None:
            caret = get_caret_position()
            if caret:
                x, y = caret
            else:
                return

        # Less particles = faster
        count = int(8 * intensity_mult)
        
        for _ in range(count):
            max_life = random.randint(15, 30)
            self.particles.append({
                'x': x + random.uniform(-8, 8),
                'y': y,
                'vx': random.uniform(-2, 2),
                'vy': random.uniform(-8, -3),
                'life': max_life,
                'max_life': max_life,
                'size': random.uniform(4, 10) * intensity_mult
            })

    def animate(self):
        if not self.running: return
        
        self.canvas.delete("all")
        shake_x, shake_y = self.shake_offset
        
        for p in self.particles[:]:
            # Organic movement - slight wobble
            p['x'] += p['vx'] + random.uniform(-0.5, 0.5)
            p['y'] += p['vy']
            p['vy'] -= 0.15  # Float up
            p['life'] -= 1
            
            if p['life'] <= 0:
                self.particles.remove(p)
                continue
            
            ratio = p['life'] / p['max_life']
            x = p['x'] + shake_x
            y = p['y'] + shake_y
            size = p['size'] * ratio
            
            # Simple color: white/yellow when new, red/dark when old
            if ratio > 0.7:
                color = '#ffcc00'  # Bright yellow
            elif ratio > 0.4:
                color = '#ff6600'  # Orange
            else:
                color = '#cc2200'  # Dark red
            
            self.canvas.create_oval(
                x - size, y - size,
                x + size, y + size,
                fill=color, outline=''
            )
            
        self.root.after(16, self.animate)

if __name__ == "__main__":
    RageApp()
