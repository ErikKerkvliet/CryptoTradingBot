"""Enhanced GUI wallet tab with channel-specific wallet support."""
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Any, List
import threading
from collections import defaultdict
from .performance_dialog import PerformanceDialog


class EnhancedWalletTab:
    """Enhanced wallet tab with channel filtering and management."""

    def __init__(self, parent_frame, db, status_callback=None):
        self.parent_frame = parent_frame
        self.db = db
        self.status_callback = status_callback
        self.loaded_wallet_tab = False

        # Create the enhanced wallet interface
        self.create_wallet_widgets()

    def create_wallet_widgets(self):
        """Create the enhanced wallet interface with channel support."""
        # Control frame
        control_frame = ttk.Frame(self.parent_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Status indicator
        self.wallet_status_label = ttk.Label(control_frame, text="🟢", font=('Arial', 10))
        self.wallet_status_label.pack(side=tk.LEFT, padx=2)

        # Refresh button
        ttk.Button(control_frame, text="Refresh", command=self.refresh_wallet_with_filter).pack(side=tk.LEFT, padx=5)

        # Channel filter
        ttk.Label(control_frame, text="Filter by channel:").pack(side=tk.LEFT, padx=5)
        self.channel_filter = ttk.Combobox(control_frame, width=20, values=['All', 'Global (Summary)'])
        self.channel_filter.pack(side=tk.LEFT, padx=5)
        self.channel_filter.bind('<<ComboboxSelected>>', self.filter_wallet)

        # Add new channel button
        ttk.Button(control_frame, text="➕ Add Channel",
                  command=self.show_add_channel_dialog).pack(side=tk.LEFT, padx=5)

        # Performance summary button
        ttk.Button(control_frame, text="📊 Performance",
                  command=self.open_performance_dialog).pack(side=tk.LEFT, padx=5)

        # USD value refresh button
        self.usd_refresh_button = ttk.Button(control_frame, text="💲 Refresh USD",
                                           command=self.refresh_wallet_with_real_prices)
        self.usd_refresh_button.pack(side=tk.LEFT, padx=5)

        # Total value label
        self.total_value_label = ttk.Label(control_frame, text="Total Value: Calculating...",
                                         font=('Arial', 10, 'bold'))
        self.total_value_label.pack(side=tk.RIGHT, padx=5)

        # Status label for USD refresh
        self.usd_status_label = ttk.Label(control_frame, text="", font=('Arial', 9), foreground="gray")
        self.usd_status_label.pack(side=tk.RIGHT, padx=5)

        # Wallet treeview with channel column
        tree_frame = ttk.Frame(self.parent_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.wallet_tree = ttk.Treeview(tree_frame, show='headings')

        # Enhanced columns including channel
        wallet_columns = ['Channel', 'Currency', 'Balance', 'USD Value (Est.)', 'USD Price', 'P&L %']
        self.wallet_tree['columns'] = wallet_columns

        column_widths = {
            'Channel': 150,
            'Currency': 80,
            'Balance': 120,
            'USD Value (Est.)': 100,
            'USD Price': 80,
            'P&L %': 80
        }

        for col in wallet_columns:
            self.wallet_tree.heading(col, text=col, command=lambda c=col: self.sort_wallet_column(c))
            self.wallet_tree.column(col, width=column_widths.get(col, 100))

        # Scrollbars for wallet
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.wallet_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.wallet_tree.xview)

        self.wallet_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Grid layout
        self.wallet_tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Initialize sort states
        self.sort_reverse = {col: False for col in wallet_columns}

    def sort_wallet_column(self, col):
        """Sort the wallet table by the specified column."""
        try:
            data = [(self.wallet_tree.set(item, col), item) for item in self.wallet_tree.get_children('')]

            # Try to sort numerically for numeric columns
            if col in ['Balance', 'USD Value (Est.)', 'USD Price', 'P&L %']:
                try:
                    data.sort(key=lambda x: float(x[0].replace('$', '').replace('%', '').replace(',', ''))
                             if x[0] and x[0] not in ['N/A', '', '-'] else 0,
                             reverse=self.sort_reverse[col])
                except (ValueError, TypeError):
                    data.sort(key=lambda x: str(x[0]).lower(), reverse=self.sort_reverse[col])
            else:
                data.sort(key=lambda x: str(x[0]).lower(), reverse=self.sort_reverse[col])

            # Rearrange items
            for index, (_, item) in enumerate(data):
                self.wallet_tree.move(item, '', index)

            # Toggle sort direction
            self.sort_reverse[col] = not self.sort_reverse[col]

            # Update column header
            direction = "↓" if self.sort_reverse[col] else "↑"
            self.wallet_tree.heading(col, text=f"{col} {direction}")

        except Exception as e:
            messagebox.showerror("Sort Error", f"Failed to sort column {col}: {e}")

    def refresh_wallet(self):
        """Refresh the wallet table with channel-specific data."""
        if not self.db:
            self._show_no_database_message()
            return

        try:
            self.wallet_status_label.config(text="🟡")

            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Get all channel balances
            if hasattr(self.db, 'get_all_channel_balances'):
                wallet_data = self.db.get_all_channel_balances()
            else:
                # Fallback for simple database connections
                wallet_data = self._get_wallet_data_fallback()

            # Filter out template/example data
            wallet_data = self._filter_template_data(wallet_data)

            # Update channel filter
            channels = {'All', 'Global (Summary)'}
            for item in wallet_data:
                channel_name = item.get('channel', 'global')
                # Skip template channels in filter
                if not self._is_template_channel(channel_name) and channel_name != 'global':
                    channels.add(channel_name)

            self.channel_filter['values'] = sorted(list(channels))
            if not self.channel_filter.get():
                self.channel_filter.set('All')

            # Populate wallet table (defaulting to 'All' view)
            total_usd_value = 0
            displayed_count = 0
            for item in wallet_data:
                # Skip the old 'global' entries if they exist
                if item.get('channel') == 'global':
                    continue

                if item['balance'] > 0:  # Only show non-zero balances
                    channel = item.get('channel')
                    currency = item['currency']
                    balance = item['balance']

                    if not channel or self._is_template_channel(channel):
                        continue

                    # Calculate basic USD estimate (simplified)
                    usd_value = self._estimate_usd_value(currency, balance)
                    total_usd_value += usd_value

                    # Calculate P&L if we have start amount
                    pnl_pct = self._calculate_pnl_percentage(item, currency, balance)

                    values = [
                        channel,
                        currency,
                        f"{balance:.8f}",
                        f"${usd_value:.2f}",
                        "Est.",  # Will be updated with real prices if refreshed
                        f"{pnl_pct:.1f}%" if pnl_pct is not None else "-"
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)
                    displayed_count += 1

            if displayed_count == 0:
                self.wallet_tree.insert('', tk.END, values=[
                    'No wallet data', 'Configure channels', 'in your .env file', '', '', ''
                ])

            self.total_value_label.config(text=f"Total Value: ${total_usd_value:.2f} (Est.)")
            self.usd_status_label.config(text="Use 💲 Refresh USD for real prices", foreground="gray")
            self.wallet_status_label.config(text="🟢")

        except Exception as e:
            self._show_error_in_tree(f'Error: {e}')
            self.wallet_status_label.config(text="🔴")

    def _filter_template_data(self, wallet_data):
        """Filter out template/example data."""
        filtered_data = []
        for item in wallet_data:
            channel = item.get('channel', 'global')

            # Skip template channels
            if self._is_template_channel(channel):
                continue

            # Skip if balance looks like a template value
            balance = item.get('balance', 0)
            if balance in [1000.0, 1500.0, 2000.0] and self._is_template_channel(channel):
                continue

            filtered_data.append(item)

        return filtered_data

    def _is_template_channel(self, channel_name):
        """Check if a channel name looks like a template."""
        if not channel_name or channel_name == 'global':
            return False

        template_patterns = [
            'test_channel',
            'example',
            'template',
            'demo'
        ]

        channel_lower = str(channel_name).lower()
        return any(pattern in channel_lower for pattern in template_patterns)

    def refresh_wallet_with_filter(self):
        """Refresh wallet while preserving current filter."""
        current_filter = self.channel_filter.get() if hasattr(self, 'channel_filter') else 'All'
        self.refresh_wallet()
        if current_filter:
            self.channel_filter.set(current_filter)
            self.filter_wallet()

    def filter_wallet(self, event=None):
        """Filter wallet by selected channel, with special handling for Global Summary."""
        if not self.db:
            return

        selected_channel = self.channel_filter.get()

        # Handle Global Summary view
        if selected_channel == 'Global (Summary)':
            self._populate_global_summary()
            return

        try:
            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Get wallet data
            if hasattr(self.db, 'get_all_channel_balances'):
                all_wallet_data = self.db.get_all_channel_balances()
            else:
                all_wallet_data = self._get_wallet_data_fallback()

            all_wallet_data = self._filter_template_data(all_wallet_data)

            # Filter by channel
            if selected_channel == 'All':
                filtered_data = [d for d in all_wallet_data if d.get('channel') != 'global']
            else:
                filtered_data = [item for item in all_wallet_data
                               if item.get('channel') == selected_channel]

            # Populate filtered data
            total_usd_value = 0
            for item in filtered_data:
                if item['balance'] > 0:
                    channel = item.get('channel')
                    currency = item['currency']
                    balance = item['balance']
                    usd_value = self._estimate_usd_value(currency, balance)
                    total_usd_value += usd_value
                    pnl_pct = self._calculate_pnl_percentage(item, currency, balance)

                    values = [
                        channel, currency, f"{balance:.8f}", f"${usd_value:.2f}",
                        "Est.", f"{pnl_pct:.1f}%" if pnl_pct is not None else "-"
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            if not filtered_data:
                self.wallet_tree.insert('', tk.END, values=[
                    f'No data for {selected_channel}', 'Check your', '.env configuration', '', '', ''
                ])

            self.total_value_label.config(text=f"Total Value: ${total_usd_value:.2f} (Filtered)")
            if self.status_callback:
                self.status_callback(f"Filtered wallet: {len(filtered_data)} records for {selected_channel}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to filter wallet: {e}")

    def _populate_global_summary(self, crypto_prices=None):
        """Calculate and display the aggregated global summary."""
        try:
            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            all_wallet_data = self.db.get_all_channel_balances()
            configs = self.db.get_channel_configs()

            # Aggregate balances from all channels
            global_balances = defaultdict(float)
            for item in all_wallet_data:
                if item.get('channel') != 'global':
                    global_balances[item['currency']] += item['balance']

            # Calculate total starting value (assuming all start in USDT for simplicity)
            total_start_value = sum(c.get('start_amount', 0) for c in configs if c.get('start_currency') == 'USDT')

            # Calculate total current value
            total_current_value = 0
            for currency, balance in global_balances.items():
                if crypto_prices:
                    price = self._get_real_usd_price(currency, crypto_prices)
                    total_current_value += balance * price
                else:
                    total_current_value += self._estimate_usd_value(currency, balance)

            # Calculate global P&L
            global_pnl_pct = 0
            if total_start_value > 0:
                pnl = total_current_value - total_start_value
                global_pnl_pct = (pnl / total_start_value) * 100

            # Populate tree with aggregated data
            for currency, balance in sorted(global_balances.items()):
                if balance > 0:
                    if crypto_prices:
                        price = self._get_real_usd_price(currency, crypto_prices)
                        usd_value = balance * price
                        price_str = f"${price:.2f}" if price > 0 else "N/A"
                    else:
                        usd_value = self._estimate_usd_value(currency, balance)
                        price_str = "Est."

                    values = [
                        "Global (Summary)", currency, f"{balance:.8f}", f"${usd_value:.2f}",
                        price_str, f"{global_pnl_pct:+.1f}%"
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            self.total_value_label.config(text=f"Total Value: ${total_current_value:.2f} (Global)")
            if self.status_callback:
                self.status_callback("Displayed global wallet summary")

        except Exception as e:
            self._show_error_in_tree(f'Global Summary Error: {e}')

    def show_add_channel_dialog(self):
        """Show dialog to add a new channel with starting balance."""
        dialog = tk.Toplevel(self.parent_frame)
        dialog.title("Add New Channel")
        dialog.geometry("400x350")
        dialog.transient(self.parent_frame)
        dialog.grab_set()

        # Instructions
        instruction_label = ttk.Label(dialog,
            text="Add a new channel with starting balance.\nThis creates an isolated wallet for the channel.",
            font=('Arial', 9))
        instruction_label.pack(pady=10)

        # Channel name
        ttk.Label(dialog, text="Channel Name:", font=('Arial', 10, 'bold')).pack(pady=5)
        ttk.Label(dialog, text="(without @ symbol, e.g. 'mychannelname')",
                 font=('Arial', 8), foreground='gray').pack()
        channel_var = tk.StringVar()
        channel_entry = ttk.Entry(dialog, textvariable=channel_var, width=30)
        channel_entry.pack(pady=5)

        # Starting currency
        ttk.Label(dialog, text="Starting Currency:", font=('Arial', 10, 'bold')).pack(pady=(15,5))
        currency_var = tk.StringVar(value="USDT")
        currency_combo = ttk.Combobox(dialog, textvariable=currency_var,
                                     values=["USDT", "USDC", "BTC", "ETH", "USD", "EUR"], width=27)
        currency_combo.pack(pady=5)

        # Starting amount
        ttk.Label(dialog, text="Starting Amount:", font=('Arial', 10, 'bold')).pack(pady=(15,5))
        amount_var = tk.StringVar(value="1000.0")
        amount_entry = ttk.Entry(dialog, textvariable=amount_var, width=30)
        amount_entry.pack(pady=5)

        # Warning label
        warning_label = ttk.Label(dialog,
            text="⚠️  Note: This creates a test wallet. For production use,\nadd channels to your .env CHANNEL_WALLET_CONFIGS",
            font=('Arial', 8), foreground='orange')
        warning_label.pack(pady=10)

        def add_channel():
            try:
                channel = channel_var.get().strip().lower().replace('@', '')
                currency = currency_var.get().strip().upper()
                amount = float(amount_var.get().strip())

                if not channel:
                    messagebox.showerror("Error", "Channel name is required")
                    return

                if amount <= 0:
                    messagebox.showerror("Error", "Amount must be positive")
                    return

                # Check if channel looks like template
                if self._is_template_channel(channel):
                    result = messagebox.askyesno("Template Channel",
                        f"'{channel}' looks like a template channel name.\n"
                        f"Are you sure you want to add it?")
                    if not result:
                        return

                # Initialize channel wallet
                if hasattr(self.db, 'initialize_channel_wallet'):
                    self.db.initialize_channel_wallet(channel, currency, amount)
                    messagebox.showinfo("Success",
                        f"✅ Added '{channel}' with {amount} {currency}\n\n"
                        f"💡 For permanent configuration, add this to your .env:\n"
                        f"CHANNEL_WALLET_CONFIGS={channel}:{currency}:{amount}")
                    dialog.destroy()
                    self.refresh_wallet()
                else:
                    messagebox.showerror("Error", "Database doesn't support channel wallets")

            except ValueError:
                messagebox.showerror("Error", "Invalid amount value - please enter a number")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add channel: {e}")

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20)

        ttk.Button(button_frame, text="Add Channel", command=add_channel).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

        # Focus on channel entry
        channel_entry.focus_set()

    def open_performance_dialog(self):
        """Open the performance summary dialog using the new dedicated class."""
        if not self.db:
            messagebox.showerror("Error", "Database connection not available.", parent=self.parent_frame)
            return
        try:
            # Instantiate and show the new dialog
            dialog = PerformanceDialog(self.parent_frame, self.db)
            dialog.show()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open performance dialog: {e}", parent=self.parent_frame)

    def refresh_wallet_with_real_prices(self):
        """Refresh wallet with real USD prices while preserving the current filter."""
        # Get the current filter before starting the background thread
        current_filter = self.channel_filter.get()

        def run_refresh(channel_filter_to_apply):
            try:
                # Use thread-safe GUI updates
                self.parent_frame.after(0, lambda: self.usd_refresh_button.config(state='disabled', text="🔄 Loading..."))
                self.parent_frame.after(0, lambda: self.usd_status_label.config(text="Fetching prices...",
                                                                                foreground="orange"))
                # Get all wallet data
                wallet_data = []
                try:
                    import sqlite3
                    from config.settings import BASE_DIR

                    # Determine database path
                    if hasattr(self.db, '__class__') and 'DryRun' in self.db.__class__.__name__:
                        db_path = BASE_DIR / "dry_run.db"
                    else:
                        db_path = BASE_DIR / "live_trading.db"

                    # Create thread-local database connection
                    if db_path.exists():
                        conn = sqlite3.connect(str(db_path))
                        cursor = conn.cursor()

                        # Get wallet data with thread-safe connection
                        cursor.execute("""
                            SELECT currency, balance, telegram_channel, 
                                   cc.start_amount, cc.start_currency
                            FROM wallet w
                            LEFT JOIN channel_configs cc ON w.telegram_channel = cc.channel_name
                            ORDER BY w.telegram_channel, w.currency
                        """)

                        for row in cursor.fetchall():
                            wallet_data.append({
                                'currency': row[0],
                                'balance': row[1],
                                'channel': row[2] or 'global',
                                'start_amount': row[3],
                                'start_currency': row[4]
                            })

                        conn.close()
                    else:
                        # Fallback: schedule UI update with error message
                        self.parent_frame.after(0, lambda: self.usd_status_label.config(text="Database not found",
                                                                                        foreground="red"))
                        return

                except Exception as db_error:
                    # Schedule UI update with error message
                    error_msg = f"Database error: {str(db_error)}"
                    self.parent_frame.after(0, lambda: self.usd_status_label.config(text=error_msg, foreground="red"))
                    return

                # Filter out template data
                wallet_data = self._filter_template_data(wallet_data)

                # Group by currency to minimize API calls
                currencies_to_fetch = set()
                for item in wallet_data:
                    if item['balance'] > 0:
                        currency = item['currency']
                        if currency not in ['USDT', 'USDC', 'USD', 'EUR', 'GBP']:
                            currencies_to_fetch.add(currency)

                # Fetch prices
                crypto_prices = {}
                if currencies_to_fetch:
                    crypto_prices = self._fetch_crypto_prices_sync(list(currencies_to_fetch))

                # Update display, passing the filter that was active when the button was clicked
                self.parent_frame.after(0, lambda: self._update_wallet_display_with_real_prices(wallet_data,
                                                                                                crypto_prices,
                                                                                                channel_filter_to_apply))

            except Exception as e:
                self.usd_status_label.config(text=f"Error: {str(e)[:50]}...", foreground="red")
            finally:
                self.parent_frame.after(0, lambda: self.usd_refresh_button.config(state='normal', text="💲 Refresh USD"))

        # Start the thread and pass the current filter value to it
        threading.Thread(target=run_refresh, args=(current_filter,), daemon=True).start()

    def _get_wallet_data_fallback(self):
        """Fallback method for simple database connections."""
        try:
            # Try to get channel-specific data
            self.db.cursor.execute("""
                SELECT currency, balance, telegram_channel 
                FROM wallet 
                ORDER BY telegram_channel, currency
            """)

            wallet_data = []
            for row in self.db.cursor.fetchall():
                wallet_data.append({
                    'currency': row[0],
                    'balance': row[1],
                    'channel': row[2] or 'global',
                    'start_amount': None,
                    'start_currency': None
                })
            return wallet_data
        except:
            # Ultimate fallback - just basic balance
            try:
                self.db.cursor.execute("SELECT currency, balance FROM wallet")
                wallet_data = []
                for row in self.db.cursor.fetchall():
                    wallet_data.append({
                        'currency': row[0],
                        'balance': row[1],
                        'channel': 'global',
                        'start_amount': None,
                        'start_currency': None
                    })
                return wallet_data
            except:
                return []

    def _estimate_usd_value(self, currency, balance):
        """Estimate USD value with simple rates."""
        if currency in ['USD', 'USDT', 'USDC', 'BUSD', 'DAI']:
            return balance
        elif currency == 'EUR':
            return balance * 1.1
        elif currency == 'GBP':
            return balance * 1.25
        else:
            # Placeholder estimates
            rates = {'BTC': 43000, 'ETH': 2500, 'ADA': 0.45, 'XRP': 0.55, 'LTC': 75}
            return balance * rates.get(currency, 1.0)

    def _calculate_pnl_percentage(self, item, currency, balance):
        """Calculate P&L percentage for a currency in a channel."""
        try:
            if item.get('start_currency') == currency and item.get('start_amount'):
                start_amount = item['start_amount']
                pnl = balance - start_amount
                return (pnl / start_amount) * 100 if start_amount > 0 else 0
            return None
        except:
            return None

    def _fetch_crypto_prices_sync(self, symbols):
        """Fetch crypto prices synchronously."""
        try:
            import requests

            symbol_to_id = {
                'BTC': 'bitcoin', 'ETH': 'ethereum', 'ADA': 'cardano',
                'XRP': 'ripple', 'LTC': 'litecoin', 'DOT': 'polkadot'
            }

            coin_ids = [symbol_to_id.get(s.upper()) for s in symbols if symbol_to_id.get(s.upper())]

            if not coin_ids:
                return {}

            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {'ids': ','.join(coin_ids), 'vs_currencies': 'usd'}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            prices = {}
            for coin_id, price_data in data.items():
                symbol = next((k for k, v in symbol_to_id.items() if v == coin_id), None)
                if symbol and 'usd' in price_data:
                    prices[symbol] = float(price_data['usd'])

            return prices

        except Exception as e:
            print(f"Error fetching prices: {e}")
            return {}

    def _get_real_usd_price(self, currency, crypto_prices):
        """Helper to get real USD price from a dictionary, with fallbacks."""
        if currency in ['USDT', 'USDC', 'USD', 'BUSD', 'DAI']:
            return 1.0
        elif currency == 'EUR':
            return 1.1
        elif currency == 'GBP':
            return 1.25
        else:
            return crypto_prices.get(currency, 0)

    def _update_wallet_display_with_real_prices(self, wallet_data, crypto_prices, channel_filter):
        """Update the wallet display with real prices and apply the specified filter."""
        try:
            # Clear the tree before repopulating
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            updated_count = len([p for p in crypto_prices.values() if p > 0])

            # Handle Global Summary or other filters
            if channel_filter == 'Global (Summary)':
                self._populate_global_summary(crypto_prices=crypto_prices)
            else:
                # Filter data for 'All' or a specific channel
                if channel_filter and channel_filter != 'All':
                    filtered_data = [item for item in wallet_data if item.get('channel', 'global') == channel_filter]
                else:
                    # 'All' view should not include 'global' entries from the DB
                    filtered_data = [d for d in wallet_data if d.get('channel') != 'global']

                total_usd_value = 0
                # Iterate over the FILTERED data to populate the tree
                for item in filtered_data:
                    if item['balance'] > 0:
                        channel = item.get('channel')
                        currency = item['currency']
                        balance = item['balance']
                        usd_price = self._get_real_usd_price(currency, crypto_prices)
                        usd_value = balance * usd_price
                        total_usd_value += usd_value
                        pnl_pct = self._calculate_pnl_percentage(item, currency, balance)

                        values = [
                            channel, currency, f"{balance:.8f}", f"${usd_value:.2f}",
                            f"${usd_price:.2f}" if usd_price > 0 else "N/A",
                            f"{pnl_pct:.1f}%" if pnl_pct is not None else "-"
                        ]
                        self.wallet_tree.insert('', tk.END, values=values)

                # Update total value label, noting if it's filtered
                label_text = f"Total Value: ${total_usd_value:.2f}"
                if channel_filter and channel_filter != 'All':
                    label_text += " (Filtered)"
                self.total_value_label.config(text=label_text)

            # This block will now run for ALL successful filters
            status_text = f"✅ Updated {updated_count} prices from CoinGecko"
            self.usd_status_label.config(text=status_text, foreground="green")

        except Exception as e:
            self.usd_status_label.config(text=f"Display error: {str(e)[:30]}...", foreground="red")

    def _show_no_database_message(self):
        """Show message when no database is available."""
        for item in self.wallet_tree.get_children():
            self.wallet_tree.delete(item)
        self.wallet_tree.insert('', tk.END, values=['No database', '', '', '', '', ''])
        self.total_value_label.config(text="Total Value: $0.00")
        self.wallet_status_label.config(text="🔴")

    def _show_error_in_tree(self, error_msg):
        """Show error message in the tree."""
        for item in self.wallet_tree.get_children():
            self.wallet_tree.delete(item)
        self.wallet_tree.insert('', tk.END, values=[error_msg, '', '', '', '', ''])