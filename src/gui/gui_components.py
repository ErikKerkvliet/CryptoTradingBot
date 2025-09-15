"""Helper components for the GUI."""
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Any, List, Optional
import os

class DataTable:
    """Reusable data table component with sorting and filtering."""

    def __init__(self, parent, columns: List[str], column_widths: Optional[Dict[str, int]] = None):
        self.parent = parent
        self.columns = columns
        self.column_widths = column_widths or {}

        # Create treeview
        self.tree = ttk.Treeview(parent, columns=columns, show='headings')

        # Configure columns
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c))
            width = self.column_widths.get(col, 100)
            self.tree.column(col, width=width)

        # Scrollbars
        v_scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=self.tree.xview)

        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Pack elements
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')

        # Configure grid weights
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self.sort_reverse = {col: False for col in columns}

    def sort_column(self, col):
        """Sort the table by the specified column."""
        try:
            data = [(self.tree.set(item, col), item) for item in self.tree.get_children('')]

            # Try to sort numerically first, fallback to string
            try:
                data.sort(key=lambda x: float(x[0]) if x[0] and x[0] != '' else 0,
                          reverse=self.sort_reverse[col])
            except (ValueError, TypeError):
                data.sort(key=lambda x: str(x[0]).lower(), reverse=self.sort_reverse[col])

            # Rearrange items
            for index, (_, item) in enumerate(data):
                self.tree.move(item, '', index)

            # Toggle sort direction
            self.sort_reverse[col] = not self.sort_reverse[col]

            # Update column header to show sort direction
            direction = "↓" if self.sort_reverse[col] else "↑"
            self.tree.heading(col, text=f"{col} {direction}")

        except Exception as e:
            messagebox.showerror("Sort Error", f"Failed to sort column {col}: {e}")

    def clear(self):
        """Clear all data from the table."""
        for item in self.tree.get_children():
            self.tree.delete(item)

    def insert_data(self, data: List[List[Any]]):
        """Insert multiple rows of data."""
        self.clear()
        for row in data:
            self.tree.insert('', tk.END, values=row)

    def get_selected(self) -> Optional[Dict[str, Any]]:
        """Get the selected row as a dictionary."""
        selection = self.tree.selection()
        if not selection:
            return None

        item = selection[0]
        values = self.tree.item(item)['values']
        return dict(zip(self.columns, values))


class StatusBar:
    """Status bar component with multiple sections."""

    def __init__(self, parent):
        self.frame = ttk.Frame(parent, relief=tk.SUNKEN)
        self.frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Main status label
        self.status_label = tk.Label(self.frame, text="Ready", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Connection status
        self.connection_label = tk.Label(self.frame, text="●", fg="red", font=('Arial', 12))
        self.connection_label.pack(side=tk.RIGHT, padx=5)

        # Record count
        self.count_label = tk.Label(self.frame, text="Records: 0", anchor=tk.E)
        self.count_label.pack(side=tk.RIGHT, padx=10)

    def set_status(self, text: str):
        """Set the main status text."""
        self.status_label.config(text=text)

    def set_connection(self, connected: bool):
        """Set the connection status indicator."""
        color = "green" if connected else "red"
        self.connection_label.config(fg=color)

    def set_count(self, count: int, label: str = "Records"):
        """Set the record count."""
        self.count_label.config(text=f"{label}: {count}")


class FilterFrame:
    """Filter controls for tables."""

    def __init__(self, parent, filters: Dict[str, List[str]], callback=None):
        self.parent = parent
        self.callback = callback
        self.filters = {}

        self.frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, padx=5, pady=5)

        # Create filter controls
        for i, (filter_name, options) in enumerate(filters.items()):
            ttk.Label(self.frame, text=f"{filter_name}:").grid(row=0, column=i * 2, padx=5, sticky=tk.W)

            combo = ttk.Combobox(self.frame, values=['All'] + options, width=15)
            combo.set('All')
            combo.grid(row=0, column=i * 2 + 1, padx=5)
            combo.bind('<<ComboboxSelected>>', self._on_filter_change)

            self.filters[filter_name] = combo

        # Refresh button
        ttk.Button(self.frame, text="🔄 Refresh", command=self._on_refresh).grid(row=0, column=len(filters) * 2, padx=10)

    def _on_filter_change(self, event=None):
        """Handle filter change."""
        if self.callback:
            self.callback(self.get_filter_values())

    def _on_refresh(self):
        """Handle refresh button click."""
        if self.callback:
            self.callback(self.get_filter_values(), refresh=True)

    def get_filter_values(self) -> Dict[str, str]:
        """Get current filter values."""
        return {name: combo.get() for name, combo in self.filters.items()}

    def update_options(self, filter_name: str, options: List[str]):
        """Update options for a specific filter."""
        if filter_name in self.filters:
            current = self.filters[filter_name].get()
            self.filters[filter_name]['values'] = ['All'] + options
            if current not in ['All'] + options:
                self.filters[filter_name].set('All')


class LogViewer:
    """Log viewing component with auto-refresh and search."""

    def __init__(self, parent, log_file: str):
        self.parent = parent
        self.log_file = log_file
        self.auto_scroll = tk.BooleanVar(value=True)

        # Control frame
        control_frame = ttk.Frame(parent)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(control_frame, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Refresh", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(control_frame, text="Auto-scroll", variable=self.auto_scroll).pack(side=tk.LEFT, padx=5)

        # Search frame
        search_frame = ttk.Frame(control_frame)
        search_frame.pack(side=tk.RIGHT, padx=5)

        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=5)
        search_entry.bind('<Return>', self.search)
        ttk.Button(search_frame, text="🔍", command=self.search).pack(side=tk.LEFT)

        # Text widget with scrollbar
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.text_widget = tk.Text(text_frame, wrap=tk.WORD, font=('Consolas', 9))
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)

        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Load initial content
        self.refresh()

    def clear(self):
        """Clear the log display."""
        self.text_widget.delete(1.0, tk.END)

    def refresh(self):
        """Refresh log content from file."""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # Keep cursor position if not auto-scrolling
                if not self.auto_scroll.get():
                    current_pos = self.text_widget.index(tk.INSERT)

                self.clear()
                self.text_widget.insert(tk.END, content)

                if self.auto_scroll.get():
                    self.text_widget.see(tk.END)
                else:
                    self.text_widget.mark_set(tk.INSERT, current_pos)
                    self.text_widget.see(current_pos)

        except Exception as e:
            self.text_widget.insert(tk.END, f"Error loading log file: {e}\n")

    def search(self, event=None):
        """Search for text in the log."""
        search_term = self.search_var.get()
        if not search_term:
            return

        # Clear previous search highlights
        self.text_widget.tag_remove("search", "1.0", tk.END)

        # Find and highlight all occurrences
        start = "1.0"
        count = 0
        while True:
            pos = self.text_widget.search(search_term, start, tk.END, nocase=True)
            if not pos:
                break

            end = f"{pos}+{len(search_term)}c"
            self.text_widget.tag_add("search", pos, end)
            start = end
            count += 1

        # Configure search highlight
        self.text_widget.tag_config("search", background="yellow", foreground="black")

        # Jump to first occurrence
        if count > 0:
            first_pos = self.text_widget.search(search_term, "1.0", tk.END, nocase=True)
            self.text_widget.see(first_pos)

        # Show count in status (if parent has status)
        try:
            self.parent.master.status_bar.set_status(f"Found {count} occurrences of '{search_term}'")
        except:
            pass


class ConfigPanel:
    """Configuration panel for bot settings."""

    def __init__(self, parent):
        self.parent = parent
        self.vars = {}

        # Main frame
        self.frame = ttk.LabelFrame(parent, text="Configuration", padding=10)
        self.frame.pack(fill=tk.X, padx=5, pady=5)

        # Load current settings
        try:
            from config.settings import settings
            self.settings = settings
        except:
            self.settings = None
            ttk.Label(self.frame, text="⚠️ Could not load settings", foreground="red").pack()
            return

        self.create_config_widgets()

    def create_config_widgets(self):
        """Create configuration input widgets."""
        if not self.settings:
            return

        # Trading mode
        mode_frame = ttk.Frame(self.frame)
        mode_frame.pack(fill=tk.X, pady=2)
        ttk.Label(mode_frame, text="Trading Mode:", width=15).pack(side=tk.LEFT)
        mode_label = ttk.Label(mode_frame, text=f"{self.settings.TRADING_MODE} on {self.settings.EXCHANGE}")
        mode_label.pack(side=tk.LEFT)

        # Dry run status
        dry_run_frame = ttk.Frame(self.frame)
        dry_run_frame.pack(fill=tk.X, pady=2)
        ttk.Label(dry_run_frame, text="Dry Run:", width=15).pack(side=tk.LEFT)
        dry_run_color = "green" if self.settings.DRY_RUN else "red"
        dry_run_text = "ENABLED (Safe)" if self.settings.DRY_RUN else "DISABLED (Live)"
        ttk.Label(dry_run_frame, text=dry_run_text, foreground=dry_run_color).pack(side=tk.LEFT)

        # Max daily trades
        trades_frame = ttk.Frame(self.frame)
        trades_frame.pack(fill=tk.X, pady=2)
        ttk.Label(trades_frame, text="Max Daily Trades:", width=15).pack(side=tk.LEFT)
        ttk.Label(trades_frame, text=str(self.settings.MAX_DAILY_TRADES)).pack(side=tk.LEFT)

        # Confidence threshold
        conf_frame = ttk.Frame(self.frame)
        conf_frame.pack(fill=tk.X, pady=2)
        ttk.Label(conf_frame, text="Min Confidence:", width=15).pack(side=tk.LEFT)
        ttk.Label(conf_frame, text=f"{self.settings.MIN_CONFIDENCE_THRESHOLD}%").pack(side=tk.LEFT)

        # Position size
        size_frame = ttk.Frame(self.frame)
        size_frame.pack(fill=tk.X, pady=2)
        ttk.Label(size_frame, text="Max Position:", width=15).pack(side=tk.LEFT)
        if self.settings.ORDER_SIZE_USD > 0:
            ttk.Label(size_frame, text=f"${self.settings.ORDER_SIZE_USD} fixed").pack(side=tk.LEFT)
        else:
            ttk.Label(size_frame, text=f"{self.settings.MAX_POSITION_SIZE_PERCENT}% of balance").pack(side=tk.LEFT)


class RealTimeChart:
    """Simple real-time chart for displaying trading data."""

    def __init__(self, parent, title: str = "Chart"):
        self.parent = parent
        self.title = title
        self.data_points = []
        self.max_points = 100

        # Try to use matplotlib if available
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            import matplotlib.dates as mdates

            self.has_matplotlib = True

            # Create figure
            self.fig = Figure(figsize=(8, 4), dpi=100)
            self.ax = self.fig.add_subplot(111)
            self.ax.set_title(title)
            self.ax.set_xlabel("Time")
            self.ax.set_ylabel("Value")

            # Create canvas
            self.canvas = FigureCanvasTkAgg(self.fig, parent)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        except ImportError:
            self.has_matplotlib = False
            # Fallback to simple text display
            self.text_widget = tk.Text(parent, height=10, font=('Consolas', 9))
            self.text_widget.pack(fill=tk.BOTH, expand=True)
            self.text_widget.insert(tk.END, f"{title}\n" + "=" * 50 + "\n")
            self.text_widget.insert(tk.END, "Install matplotlib for charts: pip install matplotlib\n\n")

    def add_data_point(self, timestamp, value, label: str = ""):
        """Add a new data point to the chart."""
        self.data_points.append((timestamp, value, label))

        # Keep only recent points
        if len(self.data_points) > self.max_points:
            self.data_points = self.data_points[-self.max_points:]

        self.update_display()

    def update_display(self):
        """Update the chart display."""
        if self.has_matplotlib and self.data_points:
            try:
                timestamps, values, _ = zip(*self.data_points)

                self.ax.clear()
                self.ax.plot(timestamps, values, 'b-', linewidth=2)
                self.ax.set_title(self.title)
                self.ax.grid(True, alpha=0.3)

                # Format x-axis for time
                self.fig.autofmt_xdate()

                self.canvas.draw()

            except Exception as e:
                print(f"Chart update error: {e}")

        elif not self.has_matplotlib and self.data_points:
            # Update text display
            recent_points = self.data_points[-10:]  # Show last 10 points
            display_text = f"{self.title}\n" + "=" * 50 + "\n"

            for timestamp, value, label in recent_points:
                display_text += f"{timestamp}: {value:.6f} {label}\n"

            self.text_widget.delete(1.0, tk.END)
            self.text_widget.insert(tk.END, display_text)
            self.text_widget.see(tk.END)


class AlertSystem:
    """Simple alert system for important notifications."""

    def __init__(self, parent):
        self.parent = parent
        self.alerts = []
        self.max_alerts = 50

        # Alert frame
        self.frame = ttk.LabelFrame(parent, text="🚨 Alerts", padding=5)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Alert listbox
        self.listbox = tk.Listbox(self.frame, font=('Arial', 9))
        alert_scrollbar = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=alert_scrollbar.set)

        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        alert_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Clear button
        ttk.Button(self.frame, text="Clear", command=self.clear_alerts).pack(side=tk.BOTTOM, pady=2)

    def add_alert(self, message: str, alert_type: str = "info"):
        """Add an alert message."""
        import datetime

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        # Color coding
        colors = {
            "info": "black",
            "warning": "orange",
            "error": "red",
            "success": "green"
        }

        icons = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅"
        }

        alert_text = f"{timestamp} {icons.get(alert_type, 'ℹ️')} {message}"
        self.alerts.append((alert_text, alert_type))

        # Keep only recent alerts
        if len(self.alerts) > self.max_alerts:
            self.alerts = self.alerts[-self.max_alerts:]

        # Update display
        self.listbox.delete(0, tk.END)
        for alert, atype in self.alerts:
            self.listbox.insert(tk.END, alert)
            # Note: Listbox color setting is limited, would need custom widget for full color support

        # Auto-scroll to bottom
        self.listbox.see(tk.END)

        # Flash the window for important alerts
        if alert_type in ["error", "warning"]:
            try:
                self.parent.bell()  # System beep
            except:
                pass

    def clear_alerts(self):
        """Clear all alerts."""
        self.alerts.clear()
        self.listbox.delete(0, tk.END)