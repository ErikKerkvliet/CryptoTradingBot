"""Dialog to display channel performance summary with charts."""
import tkinter as tk
from tkinter import ttk, messagebox
from .asset_allocation_tab import AssetAllocationTab


class PerformanceDialog:
    """A dialog window to show channel performance metrics and asset allocation."""

    def __init__(self, parent, db):
        self.parent = parent
        self.db = db
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Channel Performance Summary")
        self.dialog.geometry("1000x650")
        self.dialog.transient(parent)
        self.dialog.grab_set()

    def _is_template_channel(self, channel_name: str) -> bool:
        """Check if a channel name looks like a template."""
        if not channel_name or channel_name == 'global':
            return False
        template_patterns = ['test_channel', 'example', 'template', 'demo']
        channel_lower = str(channel_name).lower()
        return any(pattern in channel_lower for pattern in template_patterns)

    def show(self):
        """Create and display the performance dialog widgets."""
        header_label = ttk.Label(self.dialog, text="📊 Channel Performance Overview", font=('Arial', 12, 'bold'))
        header_label.pack(pady=10)

        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Performance Summary Table
        summary_frame = ttk.Frame(notebook)
        notebook.add(summary_frame, text="📈 Performance Summary")
        self.create_summary_tab(summary_frame)

        # Tab 2: Asset Allocation - now uses the dedicated class
        allocation_frame = ttk.Frame(notebook)
        notebook.add(allocation_frame, text="🥧 Historical Asset Allocation")
        AssetAllocationTab(allocation_frame, self.db)  # Instantiate the new class here

        ttk.Button(self.dialog, text="Close", command=self.dialog.destroy).pack(pady=10)

    def create_summary_tab(self, parent_frame: ttk.Frame):
        """Creates the tab with the performance data table."""
        tree_frame = ttk.Frame(parent_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        perf_tree = ttk.Treeview(tree_frame, show='headings')
        perf_columns = ['Channel', 'Start Amount', 'Current Amount', 'P&L', 'P&L %', 'Total Trades', 'Status']
        perf_tree['columns'] = perf_columns

        column_widths = {'Channel': 120, 'Start Amount': 100, 'Current Amount': 100,
                        'P&L': 80, 'P&L %': 80, 'Total Trades': 80, 'Status': 80}

        for col in perf_columns:
            perf_tree.heading(col, text=col)
            perf_tree.column(col, width=column_widths.get(col, 80))

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=perf_tree.yview)
        perf_tree.configure(yscrollcommand=scrollbar.set)
        perf_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        summary_text = self._populate_performance_data(perf_tree)
        summary_label = ttk.Label(parent_frame, text=summary_text, font=('Arial', 10, 'bold'))
        summary_label.pack(pady=5, side=tk.BOTTOM)

    def _populate_performance_data(self, perf_tree: ttk.Treeview) -> str:
        """Fetch and display performance data in the summary table."""
        try:
            if not hasattr(self.db, 'cursor'):
                perf_tree.insert('', tk.END, values=['DB not connected', '', '', '', '', '', '❌'])
                return "❌ Database not connected."

            self.db.cursor.execute("SELECT DISTINCT telegram_channel FROM wallet WHERE telegram_channel IS NOT NULL")
            channels = [row[0] for row in self.db.cursor.fetchall()]
            configs = self.db.get_channel_configs() if hasattr(self.db, 'get_channel_configs') else []

            total_channels, profitable_channels = 0, 0

            for channel in channels:
                if self._is_template_channel(channel):
                    continue

                start_amount, start_currency = 1000.0, "USDT"
                for config in configs:
                    if config.get('channel_name') == channel:
                        start_amount = config.get('start_amount', 1000.0)
                        start_currency = config.get('start_currency', 'USDT')
                        break

                current_balances = self.db.get_channel_balance(channel)
                current_amount = current_balances.get(start_currency, 0)

                pnl = current_amount - start_amount
                pnl_pct = (pnl / start_amount) * 100 if start_amount > 0 else 0

                self.db.cursor.execute("SELECT COUNT(*) FROM trades WHERE telegram_channel = ?", (channel,))
                trade_count = self.db.cursor.fetchone()[0]

                status = "✅ Profit" if pnl > 0 else ("❌ Loss" if pnl < 0 else "➖ Break-even")
                if pnl > 0: profitable_channels += 1

                values = [
                    channel, f"{start_amount:.2f} {start_currency}", f"{current_amount:.2f} {start_currency}",
                    f"{pnl:+.2f}", f"{pnl_pct:+.1f}%", str(trade_count), status
                ]
                perf_tree.insert('', tk.END, values=values)
                total_channels += 1

            if total_channels == 0:
                perf_tree.insert('', tk.END, values=['No channel data', '', '', '', '', '', '⚠️'])
                return "⚠️ No channel data found."

            summary_text = f"📈 Summary: {profitable_channels}/{total_channels} channels profitable"
            if total_channels > 0:
                summary_text += f" ({(profitable_channels / total_channels) * 100:.1f}%)"
            return summary_text

        except Exception as e:
            error_msg = f'Error: {str(e)[:50]}...'
            perf_tree.insert('', tk.END, values=[error_msg, '', '', '', '', '', '❌'])
            return "❌ Error loading performance data."