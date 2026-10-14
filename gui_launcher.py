import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

# Set working directory to app root
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_DIR)

# Import pebble_filler main entry point
import pebble_filler

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "9", "normal"), padx=5, pady=3)
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class TextRedirector:
    """Redirects stdout/stderr to the Tkinter scrolledtext widget."""
    def __init__(self, widget):
        self.widget = widget

    def write(self, str_val):
        self.widget.insert(tk.END, str_val)
        self.widget.see(tk.END)

    def flush(self):
        pass

class AppLauncherGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("P3A pebble_filler Launcher")
        self.root.geometry("620x450")

        title_label = ttk.Label(root, text="P3A Automation Companion", font=("Helvetica", 14, "bold"))
        title_label.pack(pady=10)

        btn_frame = ttk.Frame(root)
        btn_frame.pack(pady=5, fill=tk.X, padx=15)

        btn_test = ttk.Button(btn_frame, text="Run Dry-Run (--test)", command=lambda: self.run_pipeline_action(['--test']))
        btn_test.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        ToolTip(btn_test, "Runs validation and regex checks without opening the browser or modifying PebblePad.")

        btn_run = ttk.Button(btn_frame, text="Run Full Automation", command=lambda: self.run_pipeline_action([]))
        btn_run.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        ToolTip(btn_run, "Executes the full pipeline, launches Chromium, and injects validated records into PebblePad.")

        btn_remap = ttk.Button(btn_frame, text="Re-map Navigation (--remap)", command=lambda: self.run_pipeline_action(['--remap']))
        btn_remap.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        ToolTip(btn_remap, "Forces the app to clear URL caches and re-scan PebblePad menu locations before injecting.")

        output_label = ttk.Label(root, text="Terminal Output Log:")
        output_label.pack(anchor=tk.W, padx=15, pady=(10, 2))

        self.console = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=15, background="#1e1e1e", foreground="#00ff00", font=("Consolas", 10))
        self.console.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

    def run_pipeline_action(self, flags):
        self.console.delete("1.0", tk.END)
        
        def execute():
            # Redirect stdout and stderr to the Tkinter text box
            sys.stdout = TextRedirector(self.console)
            sys.stderr = TextRedirector(self.console)
            
            # Mock CLI arguments for argparse in pebble_filler.py
            sys.argv = ['pebble_filler.py'] + flags
            try:
                pebble_filler.main()
            except SystemExit as e:
                print(f"\n[Process Finished with Code {e.code}]")
            except Exception as e:
                print(f"\nFatal Execution Error: {str(e)}")
            finally:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__

        threading.Thread(target=execute, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = AppLauncherGUI(root)
    root.mainloop()