"""
GUI component for the Historical Asset Allocation tab, featuring a
dynamic pie chart with a timeline slider.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# Try to import matplotlib for charting capabilities
try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.patches
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class AssetAllocationTab:
    """Manages the 'Historical Asset Allocation' tab with a timeline slider."""

    def __init__(self, parent_frame: ttk.Frame, db):
        self.parent_frame = parent_frame
        self.db = db
        self.channel_combo = None
        self.chart_frame = None
        self.slider = None
        self.timestamp_label = None
        self.fig = None
        self.ax = None
        self.canvas = None
        self.history_data = []

        self.create_widgets()

    def _is_template_channel(self, channel_name: str) -> bool:
        """Check if a channel name looks like a template."""
        if not channel_name or channel_name == 'global':
            return False
        template_patterns = ['test_channel', 'example', 'template', 'demo']
        channel_lower = str(channel_name).lower()
        return any(pattern in channel_lower for pattern in template_patterns)

    def create_widgets(self):
        """Creates the widgets for the asset allocation tab."""
        # Top control frame for channel selection
        control_frame = ttk.Frame(self.parent_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(control_frame, text="Select Channel:").pack(side=tk.LEFT)
        self.channel_combo = ttk.Combobox(control_frame, width=30, state="readonly")
        self.channel_combo.pack(side=tk.LEFT, padx=5)
        self.channel_combo.bind("<<ComboboxSelected>>", self.on_channel_select)

        # Main frame for the chart
        self.chart_frame = ttk.Frame(self.parent_frame, relief="sunken", borderwidth=1)
        self.chart_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Bottom frame for the slider and timestamp
        timeline_frame = ttk.Frame(self.parent_frame)
        timeline_frame.pack(fill=tk.X, padx=5, pady=(0, 10))
        self.timestamp_label = ttk.Label(timeline_frame, text="Timestamp: N/A", font=("Arial", 9))
        self.timestamp_label.pack(pady=(0, 2))
        self.slider = ttk.Scale(timeline_frame, from_=0, to=0, orient=tk.HORIZONTAL, command=self.on_slider_move)
        self.slider.pack(fill=tk.X, expand=True)

        self._populate_channel_dropdown()

        # Initialize chart or show message if matplotlib is missing
        if MATPLOTLIB_AVAILABLE:
            self.fig = Figure(figsize=(6, 4), dpi=100)
            self.ax = self.fig.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            self.on_channel_select()  # Draw initial chart
        else:
            msg = "Matplotlib not found.\nPlease install it for charting features:\n\npip install matplotlib"
            ttk.Label(self.chart_frame, text=msg, justify=tk.CENTER).pack(expand=True)

    def _populate_channel_dropdown(self):
        """Fetches and populates the channel dropdown list."""
        try:
            self.db.cursor.execute("SELECT DISTINCT channel_name FROM wallet_history WHERE channel_name IS NOT NULL")
            channels = [row[0] for row in self.db.cursor.fetchall() if not self._is_template_channel(row[0])]
            if channels:
                self.channel_combo['values'] = sorted(channels)
                self.channel_combo.set(channels[0])
            else:
                self.channel_combo['values'] = ["No channel history found"]
                self.channel_combo.set("No channel history found")
        except Exception as e:
            messagebox.showerror("Error", f"Could not fetch channels: {e}", parent=self.parent_frame)

    def on_channel_select(self, event=None):
        """Callback when a new channel is selected. Loads data for the slider and chart."""
        channel = self.channel_combo.get()
        if not channel or "No channel" in channel:
            self.history_data = []
            self.slider.config(state=tk.DISABLED)
            self._draw_pie_chart({}, "No Data")
            return

        try:
            # Fetch the full time-series data for the channel
            self.history_data = self.db.get_wallet_history_for_channel(channel)

            if not self.history_data:
                self.slider.config(state=tk.DISABLED, from_=0, to=0)
                self.slider.set(0)
                self.timestamp_label.config(text="Timestamp: No history for this channel")
                self._draw_pie_chart({}, "No History")
                return

            # Configure the slider
            num_snapshots = len(self.history_data)
            self.slider.config(state=tk.NORMAL, from_=0, to=num_snapshots - 1)
            self.slider.set(num_snapshots - 1)  # Default to the most recent snapshot

            # Trigger the chart update with the latest data
            self.on_slider_move(num_snapshots - 1)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load history for {channel}: {e}", parent=self.parent_frame)

    def on_slider_move(self, value):
        """Callback when the slider is moved. Updates the chart and timestamp."""
        try:
            index = int(float(value))
            if not self.history_data or not (0 <= index < len(self.history_data)):
                return

            snapshot = self.history_data[index]
            balances = snapshot.get("balances", {})
            timestamp_str = snapshot.get("timestamp", "Unknown time")

            # Format the timestamp for display
            try:
                dt_object = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                formatted_time = dt_object.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                # Fallback for different possible formats
                try:
                    dt_object = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    formatted_time = dt_object.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    formatted_time = timestamp_str

            self.timestamp_label.config(text=f"Timestamp: {formatted_time}")
            self._draw_pie_chart(balances, formatted_time)

        except (ValueError, IndexError):
            # Ignore errors that can happen during rapid slider movement
            pass

    def _draw_pie_chart(self, balances: dict, timestamp: str):
        """Draws the pie chart based on the provided balance data and timestamp."""
        if not MATPLOTLIB_AVAILABLE:
            return

        # Filter out zero or negligible balances for a cleaner chart
        chart_data = {currency: balance for currency, balance in balances.items() if balance > 1e-9}
        self.ax.clear()

        if not chart_data:
            self.ax.text(0.5, 0.5, "No assets held at this time.", ha='center', va='center')
        else:
            labels = chart_data.keys()
            sizes = chart_data.values()
            self.ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, pctdistance=0.85)
            centre_circle = matplotlib.patches.Circle((0, 0), 0.70, fc='white')
            self.ax.add_artist(centre_circle)
            self.ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

        channel = self.channel_combo.get()
        self.ax.set_title(f"Asset Allocation for '{channel}'", pad=20)
        self.canvas.draw()