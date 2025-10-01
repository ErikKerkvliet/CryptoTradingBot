import tkinter as tk
from tkinter import ttk, messagebox
import json
from datetime import datetime, timezone

class TradeDetailDialog(tk.Toplevel):
    """Dialog to show detailed info about a single trade and its LLM response."""

    def __init__(self, parent, db, trade_id):
        super().__init__(parent)
        self.db = db
        self.trade_id = trade_id

        self.title(f"Details for Trade #{self.trade_id}")
        self.geometry("550x650")
        self.transient(parent)
        self.grab_set()

        self.data = self.db.get_trade_and_llm_response(self.trade_id)
        if not self.data:
            messagebox.showerror("Error", f"Could not find data for Trade ID {self.trade_id}", parent=self)
            self.destroy()
            return

        self.create_widgets()

    def format_utc_to_local(self, utc_str: str) -> str:
        """Converts a UTC timestamp string from the DB to a local time string for display."""
        if not utc_str:
            return ""
        try:
            utc_dt = datetime.strptime(utc_str, '%Y-%m-%d %H:%M:%S')
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
            local_dt = utc_dt.astimezone(None)
            return local_dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return utc_str

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
            "Status": self.data.get('status', ''),
            "Timestamp": self.format_utc_to_local(self.data.get('trade_timestamp', '')), # <-- MODIFIED
            "Channel": self.data.get('telegram_channel', ''),
            "Volume": f"{self.data.get('volume', 0):.8f}",
            "Entry Price": f"{self.data.get('price', 0):.8f}",
            "Leverage": self.data.get('leverage', 'N/A'),
            "Stop Loss": self.data.get('trade_stop_loss', 'N/A'),
        }

        if self.data.get('status') == 'closed':
            close_price = self.data.get('close_price')
            profit_pct = self.data.get('profit_pct')

            details["Close Price"] = f"{close_price:.8f}" if close_price is not None else "N/A"
            details["Profit"] = f"{profit_pct:+.2f}%" if profit_pct is not None else "N/A"

        for i, (label, value) in enumerate(details.items()):
            ttk.Label(trade_frame, text=f"{label}:", font=('Arial', 9, 'bold')).grid(row=i, column=0, sticky="w",
                                                                                     padx=5, pady=2)
            value_label = ttk.Label(trade_frame, text=str(value))
            value_label.grid(row=i, column=1, sticky="w", padx=5)

            if label == "Status":
                status = self.data.get('status', '').lower()
                if 'closed' in status:
                    value_label.config(foreground="blue")
                elif 'open' in status:
                    value_label.config(foreground="green")

            if label == "Profit":
                profit_pct = self.data.get('profit_pct')
                if profit_pct is not None:
                    if profit_pct > 0:
                        value_label.config(foreground="green")
                    elif profit_pct < 0:
                        value_label.config(foreground="red")

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
                    targets_tree.insert('', tk.END, text="No valid targets found")
            except (json.JSONDecodeError, TypeError):
                targets_tree.insert('', tk.END, text="Invalid target format")
        else:
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