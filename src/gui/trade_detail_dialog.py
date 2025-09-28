import tkinter as tk
from tkinter import ttk, messagebox
import json


class TradeDetailDialog(tk.Toplevel):
    """Dialog to show detailed info about a single trade and its LLM response."""

    def __init__(self, parent, db, trade_id):
        super().__init__(parent)
        self.db = db
        self.trade_id = trade_id

        self.title(f"Details for Trade #{self.trade_id}")
        self.geometry("550x600")
        self.transient(parent)
        self.grab_set()

        self.data = self.db.get_trade_and_llm_response(self.trade_id)
        if not self.data:
            messagebox.showerror("Error", f"Could not find data for Trade ID {self.trade_id}", parent=self)
            self.destroy()
            return

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # --- Trade Details (Packed to the LEFT inside top_frame) ---
        trade_frame = ttk.LabelFrame(top_frame, text="Trade Details", padding=10)
        trade_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        details = {
            "Pair": f"{self.data.get('base_currency', '')}/{self.data.get('quote_currency', '')}",
            "Side": self.data.get('side', ''),
            "Status": self.data.get('status', ''),
            "Timestamp": self.data.get('trade_timestamp', ''),
            "Channel": self.data.get('telegram_channel', ''),
            "Volume": f"{self.data.get('volume', 0):.8f}",
            "Price": f"{self.data.get('price', 0):.8f}",
            "Leverage": self.data.get('leverage', 'N/A'),
            "Stop Loss": self.data.get('trade_stop_loss', 'N/A'),
        }
        for i, (label, value) in enumerate(details.items()):
            ttk.Label(trade_frame, text=f"{label}:", font=('Arial', 9, 'bold')).grid(row=i, column=0, sticky="w",
                                                                                     padx=5, pady=2)
            ttk.Label(trade_frame, text=str(value)).grid(row=i, column=1, sticky="w", padx=5)

        # --- Targets Overview (Packed to the LEFT inside top_frame) ---
        targets_frame = ttk.LabelFrame(top_frame, text="Take-Profit Targets", padding=10)
        targets_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        targets_tree = ttk.Treeview(targets_frame, show='tree')
        targets_tree.pack(fill=tk.BOTH, expand=True)

        targets_json = self.data.get('trade_targets')
        if targets_json:
            try:
                targets_list = json.loads(targets_json)
                if isinstance(targets_list, list) and targets_list:
                    for index, target in enumerate(targets_list):
                        targets_tree.insert('', tk.END, text=f"{(index + 1)}: {target}")
                else:
                    # Handle cases where data is invalid or list is empty
                    targets_tree.insert('', tk.END, text="No valid targets found")
            except (json.JSONDecodeError, TypeError):
                targets_tree.insert('', tk.END, text="Invalid target format")
        else:
            # Handle case where no targets are specified at all
            targets_tree.insert('', tk.END, text="No targets specified")

        # --- LLM Analysis (Packed BELOW the top_frame) ---
        llm_frame = ttk.LabelFrame(main_frame, text="AI Response", padding=10)
        llm_frame.pack(fill=tk.X, pady=10)

        if self.data.get('llm_id'):
            llm_details = {
                "": f"{self.data.get('raw_response', '')}%",
            }
            for i, (label, value) in enumerate(llm_details.items()):
                ttk.Label(llm_frame, text=f"{label}", font=('Arial', 9, 'bold')).grid(row=i, column=0, sticky="w",
                                                                                       padx=5, pady=2)
                ttk.Label(llm_frame, text=str(value)).grid(row=i, column=1, sticky="w", padx=5)
        else:
            ttk.Label(llm_frame, text="No linked LLM analysis found for this trade.").pack()

        ttk.Button(main_frame, text="Close", command=self.destroy).pack(pady=10)