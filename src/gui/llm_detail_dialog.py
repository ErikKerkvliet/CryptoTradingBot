import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json

class LLMDetailDialog(tk.Toplevel):
    """Dialog to show the full message and constructed prompt for an LLM response."""

    def __init__(self, parent, db, llm_id):
        super().__init__(parent)
        self.db = db
        self.llm_id = llm_id

        self.title(f"Details for LLM Response #{self.llm_id}")
        self.geometry("700x650") # Increased height slightly
        self.transient(parent)
        self.grab_set()

        # Fetch data using the updated DB method
        self.data = self.db.get_llm_response_and_prompt(self.llm_id)
        if not self.data:
            messagebox.showerror("Error", f"Could not find data for LLM Response ID {self.llm_id}", parent=self)
            self.destroy()
            return

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Model Information Frame ---
        model_frame = ttk.LabelFrame(main_frame, text="Model Information", padding=10)
        model_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(model_frame, text="Model Used:", font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky="w")
        model_name = self.data.get('model', 'N/A')
        ttk.Label(model_frame, text=model_name, foreground="blue").grid(row=0, column=1, sticky="w", padx=5)


        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=5)

        # --- Message Tab ---
        message_frame = ttk.Frame(notebook)
        notebook.add(message_frame, text="Message")

        ttk.Label(message_frame, text="Original Telegram message sent for analysis:", wraplength=650).pack(anchor="w", pady=(0, 5))
        message_text = scrolledtext.ScrolledText(message_frame, wrap=tk.WORD, height=10)
        message_text.pack(fill=tk.BOTH, expand=True)
        message_text.insert(tk.END, self.data.get('message', 'Message not found.'))
        message_text.config(state=tk.DISABLED) # Read-only

        # --- Prompt Tab ---
        prompt_frame = ttk.Frame(notebook)
        notebook.add(prompt_frame, text="Prompt")

        ttk.Label(prompt_frame, text="Full prompt sent to the language model (System Prompt + Message):", wraplength=650).pack(anchor="w", pady=(0, 5))
        prompt_text = scrolledtext.ScrolledText(prompt_frame, wrap=tk.WORD, height=10)
        prompt_text.pack(fill=tk.BOTH, expand=True)

        system_prompt = self.data.get('system_prompt', '')
        user_message = self.data.get('message', '')
        full_prompt = f"--- SYSTEM PROMPT ---\n{system_prompt}\n\n--- USER MESSAGE ---\n{user_message}"
        prompt_text.insert(tk.END, full_prompt)
        prompt_text.config(state=tk.DISABLED) # Read-only

        # --- NEW: Raw Response Tab ---
        response_frame = ttk.Frame(notebook)
        notebook.add(response_frame, text="Response")

        ttk.Label(response_frame, text="Raw JSON response received from the model:", wraplength=650).pack(anchor="w", pady=(0, 5))
        response_text_widget = scrolledtext.ScrolledText(response_frame, wrap=tk.WORD, height=10)
        response_text_widget.pack(fill=tk.BOTH, expand=True)

        raw_response_str = self.data.get('raw_response')
        if raw_response_str:
            try:
                # Try to parse and pretty-print the JSON
                parsed_json = json.loads(raw_response_str)
                pretty_json = json.dumps(parsed_json, indent=4)
                response_text_widget.insert(tk.END, pretty_json)
            except (json.JSONDecodeError, TypeError):
                # If it's not valid JSON, just show the raw text
                response_text_widget.insert(tk.END, raw_response_str)
        else:
            response_text_widget.insert(tk.END, "No raw response was saved.")

        response_text_widget.config(state=tk.DISABLED) # Read-only


        # --- Close Button ---
        ttk.Button(main_frame, text="Close", command=self.destroy).pack(pady=10)