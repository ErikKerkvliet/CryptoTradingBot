"""
GUI component for the Historical Asset Allocation tab, featuring a
dynamic pie chart with a timeline slider and clear legend.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import requests

# Try to import matplotlib for charting capabilities
try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.patches
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# Try to import settings for API configuration
try:
    from config.settings import settings
    SETTINGS_AVAILABLE = True
except (ImportError, Exception):
    SETTINGS_AVAILABLE = False
    settings = None  # Define to avoid linting errors


class AssetAllocationTab:
    """Manages the 'Historical Asset Allocation' tab with a timeline slider and legend."""

    def __init__(self, parent_frame: ttk.Frame, db):
        self.parent_frame = parent_frame
        self.db = db
        self.channel_combo = None
        self.chart_frame = None
        self.legend_frame = None
        self.slider = None
        self.timestamp_label = None
        self.fig = None
        self.ax = None
        self.canvas = None
        self.history_data = []
        self.legend_items = []  # Store legend items for updates
        self.price_cache = {}  # Cache for current asset prices

        self.create_widgets()

    def _is_template_channel(self, channel_name: str) -> bool:
        """Check if a channel name looks like a template."""
        if not channel_name or channel_name == 'global':
            return False
        template_patterns = ['test_channel', 'example', 'template', 'demo']
        channel_lower = str(channel_name)
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

        # Main content frame (chart + legend side by side)
        content_frame = ttk.Frame(self.parent_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Legend frame (left side)
        self.legend_frame = ttk.LabelFrame(content_frame, text="Legend", padding=10)
        self.legend_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        # Chart frame (right side)
        self.chart_frame = ttk.Frame(content_frame, relief="sunken", borderwidth=1)
        self.chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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
            self._update_legend({})
            return

        try:
            # Fetch the full time-series data for the channel
            self.history_data = self.db.get_wallet_history_for_channel(channel)

            if not self.history_data:
                self.slider.config(state=tk.DISABLED, from_=0, to=0)
                self.slider.set(0)
                self.timestamp_label.config(text="Timestamp: No history for this channel")
                self._draw_pie_chart({}, "No History")
                self._update_legend({})
                return

            # Fetch current prices for all assets in the channel's history
            if SETTINGS_AVAILABLE:
                all_symbols = set()
                for snapshot in self.history_data:
                    all_symbols.update(snapshot.get("balances", {}).keys())
                
                non_stable_symbols = [
                    s.upper() for s in all_symbols
                    if s.upper() not in ['USDT', 'USDC', 'USD', 'BUSD', 'DAI', 'EUR']
                ]

                if non_stable_symbols:
                    self.price_cache = self._fetch_crypto_prices_sync(non_stable_symbols)

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
            self._update_legend(balances)

        except (ValueError, IndexError):
            # Ignore errors that can happen during rapid slider movement
            pass

    def _get_usd_price(self, currency: str) -> float:
        """Helper to get USD price from cache or estimate for stablecoins."""
        currency_upper = currency.upper()
        if currency_upper in ['USDT', 'USDC', 'USD', 'BUSD', 'DAI']:
            return 1.0
        if currency_upper == 'EUR':
            return 1.1  # Simple fallback
        # Use .get with a default of 0.0 to handle cases where price fetch fails
        return self.price_cache.get(currency_upper, 0.0)

    def _draw_pie_chart(self, balances: dict, timestamp: str):
        """Draws the pie chart based on the provided balance data and timestamp."""
        if not MATPLOTLIB_AVAILABLE:
            return

        # Convert balances to USD values
        usd_values = {
            currency: amount * self._get_usd_price(currency)
            for currency, amount in balances.items()
        }

        # Filter out zero or negligible values for a cleaner chart
        chart_data = {currency: value for currency, value in usd_values.items() if value > 1e-9}
        self.ax.clear()

        if not chart_data:
            self.ax.text(0.5, 0.5, "No assets held at this time.", ha='center', va='center')
        else:
            labels = list(chart_data.keys())
            sizes = list(chart_data.values())

            # Create pie chart with consistent colors
            colors = plt.cm.Set3(range(len(labels)))  # Use a consistent color scheme
            wedges, texts, autotexts = self.ax.pie(
                sizes,
                labels=None,  # <-- MODIFIED: Set to None to hide labels on the chart
                autopct='%1.1f%%',
                startangle=90,
                pctdistance=0.85,
                colors=colors
            )

            # Store the colors for the legend
            self.current_colors = {label: color for label, color in zip(labels, colors)}

            # Create a center circle for donut chart effect
            centre_circle = matplotlib.patches.Circle((0, 0), 0.70, fc='white')
            self.ax.add_artist(centre_circle)
            self.ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

        channel = self.channel_combo.get()
        self.ax.set_title(f"Asset Allocation for '{channel}'", pad=20)
        self.canvas.draw()

    def _update_legend(self, balances: dict):
        """Updates the legend panel with current asset information based on USD value."""
        # Clear existing legend items
        for widget in self.legend_frame.winfo_children():
            widget.destroy()

        # Convert balances to USD values for calculations
        usd_values = {
            currency: amount * self._get_usd_price(currency)
            for currency, amount in balances.items()
        }
        chart_data_usd = {currency: value for currency, value in usd_values.items() if value > 1e-9}

        if not chart_data_usd:
            ttk.Label(self.legend_frame, text="No assets to display",
                     font=("Arial", 9), foreground="gray").grid(row=0, column=0, columnspan=4)
            return

        # Corrected Header for the legend
        col_offset = 1  # Column 0 is for the color swatch
        ttk.Label(self.legend_frame, text="Asset", font=("Arial", 9, "bold")).grid(row=0, column=col_offset, sticky="w")
        ttk.Label(self.legend_frame, text="Amount", font=("Arial", 9, "bold")).grid(row=0, column=col_offset + 1, sticky="w", padx=5)
        ttk.Label(self.legend_frame, text="Value (%)", font=("Arial", 9, "bold")).grid(row=0, column=col_offset + 2, sticky="w", padx=5)
        ttk.Separator(self.legend_frame, orient='horizontal').grid(row=1, column=0, columnspan=4, sticky="ew", pady=5)

        total_value_usd = sum(chart_data_usd.values())

        # Add legend items with color indicators
        row = 2
        for currency, balance in sorted(balances.items()):
            usd_value = usd_values.get(currency, 0)
            if usd_value <= 1e-9:  # Filter out zero-value assets
                continue

            percentage = (usd_value / total_value_usd) * 100 if total_value_usd > 0 else 0

            # Color indicator
            color_frame = tk.Frame(self.legend_frame, width=15, height=15)
            color_frame.grid(row=row, column=0, sticky="w", padx=(0, 5), pady=2)
            if hasattr(self, 'current_colors') and currency in self.current_colors:
                import matplotlib.colors as mcolors
                hex_color = mcolors.to_hex(self.current_colors[currency])
                color_frame.configure(bg=hex_color)
            else:
                color_frame.configure(bg="lightgray")

            # Asset Name
            ttk.Label(self.legend_frame, text=currency, font=("Arial", 9)).grid(row=row, column=col_offset, sticky="w")

            # Amount
            balance_text = f"{balance:,.8f}".rstrip('0').rstrip('.') if balance < 1 else f"{balance:,.2f}"
            ttk.Label(self.legend_frame, text=balance_text, font=("Arial", 8)).grid(row=row, column=col_offset + 1, sticky="w", padx=5)

            # Value and Percentage
            value_text = f"${usd_value:,.2f} ({percentage:.1f}%)"
            ttk.Label(self.legend_frame, text=value_text, font=("Arial", 8), foreground="dark blue").grid(row=row, column=col_offset + 2, sticky="w", padx=5)

            row += 1

        # Add total value at the bottom
        if total_value_usd > 0:
            ttk.Separator(self.legend_frame, orient='horizontal').grid(row=row, column=0, columnspan=4, sticky="ew", pady=5)
            row += 1
            ttk.Label(self.legend_frame, text="Total Value (USD):", font=("Arial", 9, "bold")).grid(row=row, column=0, columnspan=2, sticky="e")
            total_text = f"${total_value_usd:,.2f}"
            ttk.Label(self.legend_frame, text=total_text, font=("Arial", 9, "bold"), foreground="dark green").grid(row=row, column=2, columnspan=2, sticky="w", padx=5)

    # --- Price Fetching Methods (from EnhancedWalletTab) ---

    def _fetch_crypto_prices_sync(self, symbols):
        """Fetch crypto prices synchronously from the configured exchange."""
        if not SETTINGS_AVAILABLE:
            return {}
        try:
            exchange = getattr(settings, 'EXCHANGE', 'MEXC').upper()
            if exchange == 'MEXC':
                return self._fetch_mexc_prices_sync(symbols)
            elif exchange == 'KRAKEN':
                return self._fetch_kraken_prices_sync(symbols)
            else:
                return self._fetch_coingecko_prices_sync(symbols)
        except Exception as e:
            print(f"Error fetching prices: {e}")
            return {}

    def _fetch_mexc_prices_sync(self, symbols):
        """Fetch prices from MEXC API."""
        prices = {}
        try:
            url = "https://api.mexc.com/api/v3/ticker/24hr"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            mexc_map = {s.upper() + 'USDT': s.upper() for s in symbols}
            for item in data:
                symbol = item.get('symbol', '')
                if symbol in mexc_map:
                    original_symbol = mexc_map[symbol]
                    prices[original_symbol] = float(item.get('lastPrice', 0))
            return prices
        except Exception as e:
            print(f"Error fetching MEXC prices: {e}")
            return prices

    def _fetch_kraken_prices_sync(self, symbols):
        """Fetch prices from Kraken API."""
        prices = {}
        try:
            kraken_mapping = {'BTC': 'XBT', 'ETH': 'XETH', 'DOGE': 'XDG'}
            reverse_mapping = {v: k for k, v in kraken_mapping.items()}
            
            kraken_pairs = []
            for s in symbols:
                kraken_s = kraken_mapping.get(s, s)
                kraken_pairs.append(kraken_s + 'USD')

            if not kraken_pairs: return {}

            url = "https://api.kraken.com/0/public/Ticker"
            params = {"pair": ",".join(kraken_pairs)}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get('result', {})

            for pair, price_data in data.items():
                base = pair.replace('USD', '')
                original_symbol = reverse_mapping.get(base, base)
                prices[original_symbol] = float(price_data["c"][0])
            return prices
        except Exception as e:
            print(f"Error fetching Kraken prices: {e}")
            return prices

    def _fetch_coingecko_prices_sync(self, symbols):
        """Fetch prices from CoinGecko API (fallback)."""
        prices = {}
        try:
            symbol_to_id = {s.lower(): s for s in symbols} # A simple map
            # A more robust map would be needed for production
            # For this context, we assume symbol matches coingecko id
            
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {'ids': ','.join(symbol_to_id.keys()), 'vs_currencies': 'usd'}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            for coin_id, price_data in data.items():
                symbol = symbol_to_id.get(coin_id)
                if symbol and 'usd' in price_data:
                    prices[symbol] = float(price_data['usd'])
            return prices
        except Exception as e:
            print(f"Error fetching CoinGecko prices: {e}")
            return prices