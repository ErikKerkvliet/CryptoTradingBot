"""Main GUI application for the trading bot with 4 tabs and live log monitoring."""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import time
import sys
import os
import subprocess
import logging
from typing import Dict, Any, List
from datetime import datetime
import httpx
import asyncio

# Add parent directory to path and fix imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)  # Insert at beginning to prioritize

# Change to project root directory so imports work correctly
original_cwd = os.getcwd()
os.chdir(project_root)

try:
    # Import from the project root level
    from config.settings import settings
    settings.validate_required_fields()  # This will catch any missing required fields

    if settings.DRY_RUN:
        from src.dry_run.database import DryRunDatabase as TradingDatabase
    else:
        from src.database import TradingDatabase

    SETTINGS_LOADED = True
    print(f"✅ Settings loaded successfully from {project_root}/.env")
    print(f"   MODE: {settings.TRADING_MODE}, EXCHANGE: {settings.EXCHANGE}, DRY_RUN: {settings.DRY_RUN}")

except Exception as e:
    print(f"❌ Could not load settings - {e}")
    print(f"   Looked for .env file in: {project_root}")
    print("   Make sure your .env file exists and has all required variables")
    settings = None
    TradingDatabase = None
    SETTINGS_LOADED = False
finally:
    # Restore original working directory but keep project_root in sys.path
    os.chdir(original_cwd)


class LogHandler(logging.Handler):
    """Custom logging handler that sends logs to the GUI."""

    def __init__(self, gui_queue):
        super().__init__()
        self.gui_queue = gui_queue

    def emit(self, record):
        try:
            # Format the log message
            message = self.format(record)
            # Send to GUI queue
            self.gui_queue.put(('log', message + '\n', record.levelname))
        except Exception:
            self.handleError(record)


class LogCapture:
    """Captures stdout/stderr and sends it to both GUI and original streams."""

    def __init__(self, gui_queue, original_stream=None):
        self.gui_queue = gui_queue
        self.original_stream = original_stream

        # Try to also write to log file
        try:
            self.log_file = open("trading_bot.log", "a", encoding="utf-8")
        except:
            self.log_file = None

    def write(self, message):
        if message.strip():  # Don't send empty lines
            # Send to GUI (without level since this is stdout/stderr)
            self.gui_queue.put(('log', message))

            # Also write to original stream (console)
            if self.original_stream:
                try:
                    self.original_stream.write(message)
                    self.original_stream.flush()
                except:
                    pass

            # Write to log file
            if self.log_file:
                try:
                    self.log_file.write(message)
                    self.log_file.flush()
                except:
                    pass

    def flush(self):
        if self.original_stream:
            try:
                self.original_stream.flush()
            except:
                pass
        if self.log_file:
            try:
                self.log_file.flush()
            except:
                pass

    def close(self):
        if self.log_file:
            try:
                self.log_file.close()
            except:
                pass


class TradingBotGUI:
    def __init__(self, root, run_bot=False):
        self.root = root
        self.run_bot = run_bot

        # Initialize database connection and type first
        self.db = None
        self.db_type = "none"
        self.settings_loaded = SETTINGS_LOADED
        self.bot_process = None
        self.bot_running = False
        self.loaded_wallet_tab = False

        if not self.settings_loaded:
            # Try to create a minimal database connection for read-only access
            try:
                # Try both database types
                import sqlite3
                # Define db paths relative to the project root to avoid ambiguity
                dry_run_db_path = os.path.join(project_root, "dry_run.db")
                live_db_path = os.path.join(project_root, "live_trading.db")

                if os.path.exists(dry_run_db_path):
                    self.db = self._create_simple_db_connection(dry_run_db_path)
                    self.db_type = "dry_run"
                    print(f"Found database at: {dry_run_db_path}")
                elif os.path.exists(live_db_path):
                    self.db = self._create_simple_db_connection(live_db_path)
                    self.db_type = "live"
                    print(f"Found database at: {live_db_path}")
                else:
                    print("No database files found in project root. GUI will show empty tables.")
                    self.db_type = "none"
            except Exception as e:
                print(f"Could not create database connection: {e}")
                self.db_type = "none"
        else:
            try:
                self.db = TradingDatabase() if TradingDatabase else None
                self.db_type = "dry_run" if settings.DRY_RUN else "live"
            except Exception as e:
                messagebox.showerror("Database Error", f"Failed to connect to database: {e}")
                self.db_type = "none"

        # Set title based on mode
        mode_text = "INTEGRATED BOT" if run_bot else f"{self.db_type.upper() if self.db_type != 'none' else 'NO DB'}"
        self.root.title(f"Trading Bot Monitor ({mode_text})")
        self.root.geometry("1200x800")

        # Queue for thread-safe GUI updates
        self.gui_queue = queue.Queue()

        # Log capture for integrated bot
        if run_bot:
            self.log_capture = None  # Will be initialized when bot starts

        # Create the main interface
        self.create_widgets()

        # Start the GUI update loop
        self.update_gui()

        # Start bot if requested
        if run_bot and SETTINGS_LOADED:
            self.start_integrated_bot()

        # Auto-refresh data more frequently
        self.auto_refresh_interval = 2000  # 2 seconds for live updates
        self.auto_refresh()

        # Live log monitoring (for non-integrated mode)
        if not self.run_bot:
            self.monitor_log_file()

    def monitor_log_file(self):
        """Monitor log file for changes and auto-update."""
        try:
            # Define log file path relative to project root
            log_file_path = os.path.join(project_root, "trading_bot.log")

            if os.path.exists(log_file_path):
                self.current_log_file = log_file_path
                self.last_log_size = os.path.getsize(log_file_path)
                print(f"📁 Monitoring log file: {log_file_path}")
            else:
                self.current_log_file = None
                self.last_log_size = 0
                print(f"📁 No log file found at {log_file_path} - will create when bot starts")

        except Exception as e:
            print(f"Error setting up log monitoring: {e}")

        # Schedule next check
        self.root.after(500, self.check_log_updates)  # Check every 0.5 seconds for faster updates

    def check_log_updates(self):
        """Check if log file has been updated."""
        try:
            # First check if log file was created (if it didn't exist before)
            if not self.current_log_file:
                # --- MODIFICATION START ---
                log_file_path = os.path.join(project_root, "trading_bot.log")
                if os.path.exists(log_file_path):
                    self.current_log_file = log_file_path
                    self.last_log_size = 0  # Start from beginning for new file
                    print(f"📁 Found new log file: {log_file_path}")
                    if hasattr(self, 'log_status_label'):
                        self.log_status_label.config(text="🟢")
                # --- MODIFICATION END ---

            if self.current_log_file and os.path.exists(self.current_log_file):
                current_size = os.path.getsize(self.current_log_file)
                if current_size > self.last_log_size:
                    # Log file has grown, read new content
                    with open(self.current_log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(self.last_log_size)  # Start from where we left off
                        new_content = f.read()
                        if new_content.strip():
                            # Add new content to the log display (only if not in integrated mode)
                            if not self.run_bot and self.show_live_var.get():
                                self.log_text.insert(tk.END, new_content)
                                if self.auto_scroll_var.get():
                                    self.log_text.see(tk.END)

                                # Keep log size manageable
                                lines = int(self.log_text.index('end-1c').split('.')[0])
                                if lines > 1000:
                                    self.log_text.delete('1.0', f'{lines-1000}.0')

                            # Update log status indicator
                            if hasattr(self, 'log_status_label'):
                                self.log_status_label.config(text="🟢")

                    self.last_log_size = current_size
                elif current_size < self.last_log_size:
                    # File was truncated or rotated, start over
                    self.last_log_size = 0

        except Exception as e:
            if hasattr(self, 'log_status_label'):
                self.log_status_label.config(text="🔴")

        # Schedule next check
        self.root.after(500, self.check_log_updates)

    def start_integrated_bot(self):
        """Start the trading bot in a separate thread."""
        def run_bot():
            # Initialize variables at the start to avoid UnboundLocalError
            import sys
            import asyncio
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            current_dir = os.getcwd()
            gui_handler = None

            try:
                print("🤖 Starting integrated trading bot...")

                # Make sure we're in the correct directory
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                os.chdir(project_root)

                # Make sure project root is in Python path
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                # Create log capture that writes to both GUI and file/console
                self.log_capture = LogCapture(self.gui_queue, original_stdout)
                log_capture_err = LogCapture(self.gui_queue, original_stderr)

                # Set up logging capture BEFORE importing main
                import logging

                # Clear any existing handlers to avoid duplicates
                root_logger = logging.getLogger()
                for handler in root_logger.handlers[:]:
                    root_logger.removeHandler(handler)

                # Create custom handler for GUI
                gui_handler = LogHandler(self.gui_queue)
                gui_handler.setLevel(logging.DEBUG)

                # Create formatter (same as in logger.py)
                formatter = logging.Formatter(
                    "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
                gui_handler.setFormatter(formatter)

                # Add our GUI handler to root logger
                root_logger.addHandler(gui_handler)
                root_logger.setLevel(logging.INFO)

                # Also redirect stdout/stderr (for any print statements)
                sys.stdout = self.log_capture
                sys.stderr = log_capture_err

                # Create and run the async bot function
                async def run_async_bot():
                    try:
                        # Import and create the bot inside the async context
                        from main import TradingApp
                        app = TradingApp()

                        self.bot_running = True
                        self.gui_queue.put(('status', 'Bot started successfully'))

                        # Run the bot's main loop
                        await app.run()

                    except ImportError as ie:
                        error_msg = f"Import error: {ie}. Make sure you're running from the correct directory."
                        self.gui_queue.put(('error', error_msg))
                        print(f"❌ {error_msg}")
                    except Exception as e:
                        error_msg = f"Bot runtime error: {e}"
                        self.gui_queue.put(('error', error_msg))
                        import traceback
                        traceback.print_exc()

                # Set up a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run the async bot function
                loop.run_until_complete(run_async_bot())

            except Exception as e:
                self.gui_queue.put(('error', f"Critical bot error: {e}"))
                import traceback
                self.gui_queue.put(('log', traceback.format_exc()))
            finally:
                # Clean up logging handlers
                try:
                    if gui_handler:
                        logging.getLogger().removeHandler(gui_handler)
                except Exception:
                    pass

                # Restore stdout/stderr and directory
                try:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
                except Exception:
                    pass

                try:
                    if hasattr(self, 'log_capture') and self.log_capture:
                        self.log_capture.close()
                except Exception:
                    pass

                try:
                    os.chdir(current_dir)
                except Exception:
                    pass

                # Close the event loop
                try:
                    if 'loop' in locals():
                        loop.close()
                except Exception:
                    pass

                self.bot_running = False
                self.gui_queue.put(('status', 'Bot stopped'))

        # Start bot in daemon thread
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()

    def _create_simple_db_connection(self, db_path):
        """Create a simple database connection for read-only access."""
        import sqlite3

        class SimpleDB:
            def __init__(self, db_path):
                self.conn = sqlite3.connect(db_path)
                self.cursor = self.conn.cursor()

            def get_trades(self):
                """Get all trades."""
                try:
                    self.cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")
                    columns = [description[0] for description in self.cursor.description]
                    return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
                except Exception as e:
                    print(f"Error getting trades: {e}")
                    return []

            def get_trades_by_channel(self, channel):
                """Get trades filtered by channel."""
                try:
                    self.cursor.execute("SELECT * FROM trades WHERE telegram_channel = ? ORDER BY timestamp DESC", (channel,))
                    columns = [description[0] for description in self.cursor.description]
                    return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
                except Exception as e:
                    print(f"Error getting trades by channel: {e}")
                    return []

            def get_balance(self):
                """Get wallet balance."""
                try:
                    self.cursor.execute("SELECT currency, balance FROM wallet")
                    return {row[0]: row[1] for row in self.cursor.fetchall()}
                except Exception:
                    return {}

            def close(self):
                """Close connection."""
                if hasattr(self, 'conn'):
                    self.conn.close()

        return SimpleDB(db_path)

    def create_widgets(self):
        """Create the main GUI widgets."""
        # Create notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Full Output (Logs)
        self.create_logs_tab()

        # Tab 2: Trades Table
        self.create_trades_tab()

        # Tab 3: Wallet Table
        self.create_wallet_tab()

        # Tab 4: LLM Responses Table
        self.create_llm_tab()

        # Status bar
        self.status_bar = tk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_logs_tab(self):
        """Create the logs/output tab."""
        logs_frame = ttk.Frame(self.notebook)
        self.notebook.add(logs_frame, text="📋 Full Output")

        # Control buttons
        control_frame = ttk.Frame(logs_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(control_frame, text="Clear Logs", command=self.clear_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Refresh", command=self.refresh_logs).pack(side=tk.LEFT, padx=5)

        # Auto-scroll checkbox
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(control_frame, text="Auto-scroll", variable=self.auto_scroll_var).pack(side=tk.LEFT, padx=5)

        # Show live logs checkbox
        self.show_live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(control_frame, text="Live logs", variable=self.show_live_var).pack(side=tk.LEFT, padx=5)

        # Live refresh indicator
        self.log_status_label = ttk.Label(control_frame, text="🔴", font=('Arial', 12))
        self.log_status_label.pack(side=tk.LEFT, padx=5)

        # Bot control buttons (only if integrated mode)
        if self.run_bot and SETTINGS_LOADED:
            separator = ttk.Separator(control_frame, orient=tk.VERTICAL)
            separator.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)

            self.bot_status_label = ttk.Label(control_frame, text="●", foreground="orange", font=('Arial', 12))
            self.bot_status_label.pack(side=tk.LEFT, padx=5)

            ttk.Label(control_frame, text="Bot Status").pack(side=tk.LEFT)

        # Log text area
        self.log_text = scrolledtext.ScrolledText(logs_frame, wrap=tk.WORD, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure text tags for colored output
        self.log_text.tag_configure("INFO", foreground="blue")
        self.log_text.tag_configure("WARNING", foreground="orange")
        self.log_text.tag_configure("ERROR", foreground="red")
        self.log_text.tag_configure("SUCCESS", foreground="green")
        self.log_text.tag_configure("TIMESTAMP", foreground="gray")

        # Load existing logs if not in integrated mode
        if not self.run_bot:
            self.load_log_file()

    def create_trades_tab(self):
        """Create the trades database table tab."""
        trades_frame = ttk.Frame(self.notebook)
        self.notebook.add(trades_frame, text="💼 Trades")

        # Control buttons
        control_frame = ttk.Frame(trades_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Live refresh indicator
        self.trades_status_label = ttk.Label(control_frame, text="🟢", font=('Arial', 10))
        self.trades_status_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(control_frame, text="Refresh", command=self.refresh_trades).pack(side=tk.LEFT, padx=5)
        ttk.Label(control_frame, text="Filter by channel:").pack(side=tk.LEFT, padx=5)

        self.channel_filter = ttk.Combobox(control_frame, width=20)
        self.channel_filter.pack(side=tk.LEFT, padx=5)
        self.channel_filter.bind('<<ComboboxSelected>>', self.filter_trades)

        # Trades treeview
        self.trades_tree = ttk.Treeview(trades_frame, show='headings')
        self.trades_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure trades columns
        trades_columns = ['ID', 'Timestamp', 'Channel', 'Pair', 'Side', 'Volume', 'Price', 'Status', 'Leverage']
        self.trades_tree['columns'] = trades_columns

        for col in trades_columns:
            self.trades_tree.heading(col, text=col)
            self.trades_tree.column(col, width=100)

        # Scrollbar for trades
        trades_scrollbar = ttk.Scrollbar(trades_frame, orient=tk.VERTICAL, command=self.trades_tree.yview)
        self.trades_tree.configure(yscrollcommand=trades_scrollbar.set)
        trades_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def create_wallet_tab(self):
        """Create the enhanced wallet table tab with channel support."""
        wallet_frame = ttk.Frame(self.notebook)
        self.notebook.add(wallet_frame, text="💰 Wallet")

        # Import and use the enhanced wallet tab
        try:
            from src.gui.enhanced_wallet_tab import EnhancedWalletTab
            self.enhanced_wallet = EnhancedWalletTab(
                wallet_frame,
                self.db,
                status_callback=lambda msg: self.status_bar.config(text=msg)
            )

        except ImportError:
            # Fallback to basic wallet tab if enhanced version not available
            self.create_basic_wallet_tab(wallet_frame)

    def create_basic_wallet_tab(self, wallet_frame):
        """Fallback basic wallet tab with channel column."""
        # Control buttons
        control_frame = ttk.Frame(wallet_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Live refresh indicator
        self.wallet_status_label = ttk.Label(control_frame, text="🟢", font=('Arial', 10))
        self.wallet_status_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(control_frame, text="Refresh", command=self.refresh_wallet_with_channels).pack(side=tk.LEFT, padx=5)

        # Channel filter
        ttk.Label(control_frame, text="Filter by channel:").pack(side=tk.LEFT, padx=5)
        self.wallet_channel_filter = ttk.Combobox(control_frame, width=20)
        self.wallet_channel_filter.pack(side=tk.LEFT, padx=5)
        self.wallet_channel_filter.bind('<<ComboboxSelected>>', self.filter_wallet_by_channel)

        # Total value label
        self.total_value_label = ttk.Label(control_frame, text="Total Value: Calculating...",
                                           font=('Arial', 10, 'bold'))
        self.total_value_label.pack(side=tk.RIGHT, padx=5)

        # Wallet treeview with channel column
        self.wallet_tree = ttk.Treeview(wallet_frame, show='headings')
        self.wallet_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure wallet columns with channel
        wallet_columns = ['Channel', 'Currency', 'Balance', 'USD Value (Est.)', 'P&L %']
        self.wallet_tree['columns'] = wallet_columns

        column_widths = {
            'Channel': 150,
            'Currency': 100,
            'Balance': 150,
            'USD Value (Est.)': 120,
            'P&L %': 100
        }

        for col in wallet_columns:
            self.wallet_tree.heading(col, text=col)
            self.wallet_tree.column(col, width=column_widths.get(col, 100))

        # Scrollbar for wallet
        wallet_scrollbar = ttk.Scrollbar(wallet_frame, orient=tk.VERTICAL, command=self.wallet_tree.yview)
        self.wallet_tree.configure(yscrollcommand=wallet_scrollbar.set)
        wallet_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_wallet_with_channels(self):
        """Enhanced wallet refresh with channel support."""
        if not self.db:
            self._show_wallet_error("No database connection")
            return

        try:
            self.wallet_status_label.config(text="🟡")

            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Get wallet data with channel information
            if hasattr(self.db, 'get_all_channel_balances'):
                wallet_data = self.db.get_all_channel_balances()
            else:
                # Fallback for basic database
                wallet_data = self._get_basic_wallet_data()

            # Update channel filter
            channels = set(['All'])
            for item in wallet_data:
                channels.add(item.get('channel', 'global'))

            self.wallet_channel_filter['values'] = sorted(list(channels))
            if not self.wallet_channel_filter.get():
                self.wallet_channel_filter.set('All')

            # Populate wallet
            total_usd_value = 0
            for item in wallet_data:
                if item['balance'] > 0:
                    channel = item.get('channel', 'global')
                    currency = item['currency']
                    balance = item['balance']

                    # Estimate USD value
                    usd_value = self._estimate_usd_value(currency, balance)
                    total_usd_value += usd_value

                    # Calculate P&L percentage
                    pnl_pct = self._calculate_channel_pnl(item, currency, balance)

                    values = [
                        channel,
                        currency,
                        f"{balance:.8f}",
                        f"${usd_value:.2f}",
                        f"{pnl_pct:.1f}%" if pnl_pct is not None else "-"
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            self.total_value_label.config(text=f"Total Value: ${total_usd_value:.2f} (Est.)")
            self.wallet_status_label.config(text="🟢")

        except Exception as e:
            self._show_wallet_error(f'Error: {e}')

    def filter_wallet_by_channel(self, event=None):
        """Filter wallet by selected channel."""
        if not self.db:
            return

        try:
            selected_channel = self.wallet_channel_filter.get()

            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Get and filter wallet data
            if hasattr(self.db, 'get_all_channel_balances'):
                all_wallet_data = self.db.get_all_channel_balances()
            else:
                all_wallet_data = self._get_basic_wallet_data()

            if selected_channel == 'All':
                filtered_data = all_wallet_data
            else:
                filtered_data = [item for item in all_wallet_data
                                 if item.get('channel', 'global') == selected_channel]

            # Populate filtered data
            for item in filtered_data:
                if item['balance'] > 0:
                    channel = item.get('channel', 'global')
                    currency = item['currency']
                    balance = item['balance']

                    usd_value = self._estimate_usd_value(currency, balance)
                    pnl_pct = self._calculate_channel_pnl(item, currency, balance)

                    values = [
                        channel,
                        currency,
                        f"{balance:.8f}",
                        f"${usd_value:.2f}",
                        f"{pnl_pct:.1f}%" if pnl_pct is not None else "-"
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            self.status_bar.config(text=f"Filtered wallet: {len(filtered_data)} records for {selected_channel}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to filter wallet: {e}")

    def _get_basic_wallet_data(self):
        """Get wallet data from basic database structure."""
        try:
            # Try to get channel-specific data first
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
            # Ultimate fallback
            balances = self.db.get_balance() if hasattr(self.db, 'get_balance') else {}
            return [{
                'currency': curr,
                'balance': bal,
                'channel': 'global',
                'start_amount': None,
                'start_currency': None
            } for curr, bal in balances.items()]

    def _estimate_usd_value(self, currency, balance):
        """Simple USD value estimation."""
        if currency in ['USD', 'USDT', 'USDC', 'BUSD', 'DAI']:
            return balance
        elif currency == 'EUR':
            return balance * 1.1
        elif currency == 'GBP':
            return balance * 1.25
        else:
            # Simple estimates for major cryptos
            rates = {
                'BTC': 43000, 'ETH': 2500, 'ADA': 0.45, 'XRP': 0.55,
                'LTC': 75, 'DOT': 7, 'LINK': 15, 'UNI': 6
            }
            return balance * rates.get(currency, 1.0)

    def _calculate_channel_pnl(self, item, currency, balance):
        """Calculate P&L percentage for channel."""
        try:
            if (item.get('start_currency') == currency and
                    item.get('start_amount') and
                    item.get('start_amount') > 0):
                start_amount = item['start_amount']
                pnl = balance - start_amount
                return (pnl / start_amount) * 100
            return None
        except:
            return None

    def _show_wallet_error(self, error_msg):
        """Show error in wallet table."""
        for item in self.wallet_tree.get_children():
            self.wallet_tree.delete(item)
        self.wallet_tree.insert('', tk.END, values=[error_msg, '', '', '', ''])
        self.wallet_status_label.config(text="🔴")

    # Add to the auto_refresh method:
    def auto_refresh(self):
        """Enhanced auto-refresh with channel support."""
        try:
            if self.db:
                self.refresh_trades()

                # Use enhanced wallet refresh if available
                if hasattr(self, 'enhanced_wallet'):
                    self.enhanced_wallet.refresh_wallet()
                else:
                    self.refresh_wallet_with_channels()

                self.refresh_llm()

            # Update status bar
            current_time = datetime.now().strftime("%H:%M:%S")
            connection_status = "🟢 LIVE" if self.bot_running else ("🟡 MONITORING" if self.db else "🔴 NO DATA")
            self.status_bar.config(text=f"Last refresh: {current_time} | Status: {connection_status}")

        except Exception as e:
            print(f"Auto-refresh error: {e}")

        # Schedule next auto-refresh
        self.root.after(self.auto_refresh_interval, self.auto_refresh)

    def refresh_wallet_with_real_prices(self):
        """Refresh wallet with real USD prices from market APIs."""

        def run_refresh():
            """Run the refresh using synchronous requests to avoid thread issues."""
            try:
                # Update button state
                self.root.after(0, lambda: self.usd_refresh_button.config(state='disabled', text="🔄 Loading..."))
                self.root.after(0, lambda: self.usd_status_label.config(text="Fetching prices...", foreground="orange"))

                # Get wallet data with thread-safe approach
                balances = {}
                if not self.db:
                    self.root.after(0, lambda: self.usd_status_label.config(text="No database connection",
                                                                            foreground="red"))
                    return

                try:
                    # Create a new database connection for this thread
                    import sqlite3
                    import os

                    # Determine database path
                    if self.db_type == "dry_run":
                        db_path = "dry_run.db"
                    elif self.db_type == "live":
                        db_path = "live_trading.db"
                    else:
                        # Try to use existing connection carefully
                        balances = self.db.get_balance()

                    if not balances and self.db_type in ["dry_run", "live"]:
                        if os.path.exists(db_path):
                            conn = sqlite3.connect(db_path)
                            cursor = conn.cursor()
                            cursor.execute("SELECT currency, balance FROM wallet")
                            balances = {row[0]: row[1] for row in cursor.fetchall()}
                            conn.close()
                        else:
                            self.root.after(0, lambda: self.usd_status_label.config(text="Database file not found",
                                                                                    foreground="red"))
                            return

                except Exception as db_error:
                    print(f"Database error: {db_error}")
                    self.root.after(0, lambda: self.usd_status_label.config(text="Database error", foreground="red"))
                    return

                if not balances:
                    self.root.after(0, lambda: self.usd_status_label.config(text="No balance data", foreground="red"))
                    return

                # Prepare data for price fetching
                crypto_prices = {}
                stablecoin_list = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDD']
                fiat_list = ['USD', 'EUR', 'GBP']

                # Get prices for cryptocurrencies (excluding stablecoins and fiat)
                crypto_symbols = [currency for currency in balances.keys()
                                  if currency not in stablecoin_list + fiat_list and balances[currency] > 0]

                if crypto_symbols:
                    crypto_prices = self._fetch_crypto_prices_sync(crypto_symbols)

                # Calculate total value and prepare display data
                total_usd_value = 0
                wallet_data = []

                for currency, balance in balances.items():
                    if balance > 0:  # Only show non-zero balances
                        # Determine USD price
                        if currency in stablecoin_list:
                            usd_price = 1.0
                            usd_value = balance
                        elif currency == 'USD':
                            usd_price = 1.0
                            usd_value = balance
                        elif currency == 'EUR':
                            usd_price = 1.1  # Rough EUR/USD rate
                            usd_value = balance * usd_price
                        elif currency == 'GBP':
                            usd_price = 1.25  # Rough GBP/USD rate
                            usd_value = balance * usd_price
                        else:
                            usd_price = crypto_prices.get(currency, 0)
                            usd_value = balance * usd_price

                        total_usd_value += usd_value

                        wallet_data.append({
                            'currency': currency,
                            'balance': balance,
                            'usd_value': usd_value,
                            'usd_price': usd_price
                        })

                result = {
                    'success': True,
                    'wallet_data': wallet_data,
                    'total_usd_value': total_usd_value,
                    'updated_count': len([p for p in crypto_prices.values() if p > 0])
                }

                # Update GUI with results
                self.root.after(0, lambda: self._update_wallet_display_with_prices(result))

            except Exception as e:
                error_msg = f"Error: {str(e)[:50]}..."
                self.root.after(0, lambda: self.usd_status_label.config(text=error_msg, foreground="red"))
                print(f"Error refreshing wallet with real prices: {e}")
            finally:
                # Re-enable button
                self.root.after(0, lambda: self.usd_refresh_button.config(state='normal', text="💲 Refresh USD"))

        # Run in a separate thread to avoid blocking the GUI
        import threading
        thread = threading.Thread(target=run_refresh, daemon=True)
        thread.start()

    def _fetch_crypto_prices_sync(self, symbols: list) -> Dict[str, float]:
        """Fetch cryptocurrency prices using synchronous requests."""
        if not symbols:
            return {}

        try:
            import requests

            # Convert symbols to CoinGecko IDs (simplified mapping)
            symbol_to_id = {
                'BTC': 'bitcoin',
                'ETH': 'ethereum',
                'ADA': 'cardano',
                'XRP': 'ripple',
                'LTC': 'litecoin',
                'DOT': 'polkadot',
                'LINK': 'chainlink',
                'BNB': 'binancecoin',
                'SOL': 'solana',
                'MATIC': 'matic-network',
                'AVAX': 'avalanche-2',
                'ATOM': 'cosmos',
                'UNI': 'uniswap',
                'DOGE': 'dogecoin',
                'SHIB': 'shiba-inu',
            }

            # Build the request
            coin_ids = []
            symbol_map = {}

            for symbol in symbols:
                coin_id = symbol_to_id.get(symbol.upper())
                if coin_id:
                    coin_ids.append(coin_id)
                    symbol_map[coin_id] = symbol.upper()

            if not coin_ids:
                return {}

            # Make the API request
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                'ids': ','.join(coin_ids),
                'vs_currencies': 'usd'
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Convert back to symbol-based prices
            prices = {}
            for coin_id, price_data in data.items():
                if coin_id in symbol_map and 'usd' in price_data:
                    symbol = symbol_map[coin_id]
                    prices[symbol] = float(price_data['usd'])

            return prices

        except Exception as e:
            print(f"Error fetching crypto prices: {e}")
            # Fallback to zero prices so function doesn't crash
            return {symbol: 0.0 for symbol in symbols}

    async def _refresh_wallet_with_prices_async(self):
        """Async function to fetch real USD prices for cryptocurrencies."""
        if not self.db:
            return {"error": "No database connection"}

        try:
            # Create a new database connection for this thread to avoid SQLite threading issues
            balances = {}
            if self.db_type == "dry_run":
                # Import and create new connection
                import sqlite3
                import os
                from config.settings import BASE_DIR
                db_path = os.path.join(BASE_DIR, "dry_run.db") if hasattr(self, 'BASE_DIR') else "dry_run.db"
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT currency, balance FROM wallet")
                    balances = {row[0]: row[1] for row in cursor.fetchall()}
                    conn.close()
            elif self.db_type == "live":
                # Import and create new connection
                import sqlite3
                import os
                from config.settings import BASE_DIR
                db_path = os.path.join(BASE_DIR, "live_trading.db") if hasattr(self, 'BASE_DIR') else "live_trading.db"
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT currency, balance FROM wallet")
                    balances = {row[0]: row[1] for row in cursor.fetchall()}
                    conn.close()
            else:
                # Fallback: try to get balances from the existing connection if possible
                try:
                    balances = self.db.get_balance()
                except Exception as db_error:
                    return {"error": f"Database access error: {str(db_error)}"}

            if not balances:
                return {"error": "No balance data"}

            # Prepare data for price fetching
            crypto_prices = {}
            stablecoin_list = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDD']
            fiat_list = ['USD', 'EUR', 'GBP']

            # Get prices for cryptocurrencies (excluding stablecoins and fiat)
            crypto_symbols = [currency for currency in balances.keys()
                              if currency not in stablecoin_list + fiat_list and balances[currency] > 0]

            if crypto_symbols:
                crypto_prices = await self._fetch_crypto_prices(crypto_symbols)

            # Calculate total value and prepare display data
            total_usd_value = 0
            wallet_data = []

            for currency, balance in balances.items():
                if balance > 0:  # Only show non-zero balances
                    # Determine USD price
                    if currency in stablecoin_list:
                        usd_price = 1.0
                        usd_value = balance
                    elif currency == 'USD':
                        usd_price = 1.0
                        usd_value = balance
                    elif currency == 'EUR':
                        usd_price = 1.1  # Rough EUR/USD rate - could be made dynamic
                        usd_value = balance * usd_price
                    elif currency == 'GBP':
                        usd_price = 1.25  # Rough GBP/USD rate - could be made dynamic
                        usd_value = balance * usd_price
                    else:
                        usd_price = crypto_prices.get(currency, 0)
                        usd_value = balance * usd_price

                    total_usd_value += usd_value

                    wallet_data.append({
                        'currency': currency,
                        'balance': balance,
                        'usd_value': usd_value,
                        'usd_price': usd_price
                    })

            return {
                'success': True,
                'wallet_data': wallet_data,
                'total_usd_value': total_usd_value,
                'updated_count': len(crypto_symbols)
            }

        except Exception as e:
            return {"error": str(e)}

    async def _fetch_crypto_prices(self, symbols: list) -> Dict[str, float]:
        """Fetch cryptocurrency prices from CoinGecko API."""
        if not symbols:
            return {}

        try:
            # Use CoinGecko API (free tier)
            async with httpx.AsyncClient(timeout=10) as client:
                # Convert symbols to CoinGecko IDs (simplified mapping)
                symbol_to_id = {
                    'BTC': 'bitcoin',
                    'ETH': 'ethereum',
                    'ADA': 'cardano',
                    'XRP': 'ripple',
                    'LTC': 'litecoin',
                    'DOT': 'polkadot',
                    'LINK': 'chainlink',
                    'BNB': 'binancecoin',
                    'SOL': 'solana',
                    'MATIC': 'matic-network',
                    'AVAX': 'avalanche-2',
                    'ATOM': 'cosmos',
                    'UNI': 'uniswap',
                    'DOGE': 'dogecoin',
                    'SHIB': 'shiba-inu',
                }

                # Build the request
                coin_ids = []
                symbol_map = {}

                for symbol in symbols:
                    coin_id = symbol_to_id.get(symbol.upper())
                    if coin_id:
                        coin_ids.append(coin_id)
                        symbol_map[coin_id] = symbol.upper()

                if not coin_ids:
                    return {}

                # Make the API request
                url = "https://api.coingecko.com/api/v3/simple/price"
                params = {
                    'ids': ','.join(coin_ids),
                    'vs_currencies': 'usd'
                }

                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                # Convert back to symbol-based prices
                prices = {}
                for coin_id, price_data in data.items():
                    if coin_id in symbol_map and 'usd' in price_data:
                        symbol = symbol_map[coin_id]
                        prices[symbol] = float(price_data['usd'])

                return prices

        except Exception as e:
            print(f"Error fetching crypto prices: {e}")
            # Return empty dict so the function doesn't crash
            return {}

    def _update_wallet_display_with_prices(self, result):
        """Update the wallet display with the fetched price data."""
        try:
            if 'error' in result:
                self.usd_status_label.config(text=f"Error: {result['error']}", foreground="red")
                return

            if not result.get('success'):
                self.usd_status_label.config(text="Failed to fetch prices", foreground="red")
                return

            # Update status indicator
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🟢")

            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Populate wallet with real prices (sorted by USD value)
            wallet_data = result['wallet_data']
            total_usd_value = result['total_usd_value']

            for item in wallet_data:
                # Color code the USD value based on whether we got a real price
                usd_value_text = f"${item['usd_value']:.2f}"
                if item['usd_price'] == 0 and item['currency'] not in ['USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD',
                                                                       'USDD']:
                    usd_value_text += " (est.)"  # Mark estimated values

                values = [
                    item['currency'],
                    f"{item['balance']:.8f}",
                    usd_value_text,
                    f"${item['usd_price']:.2f}" if item['usd_price'] > 0 else "N/A"
                ]
                self.wallet_tree.insert('', tk.END, values=values)

            # Update total value
            self.total_value_label.config(text=f"Total Value: ${total_usd_value:.2f}")

            # Update status with detailed information and data source
            updated_count = result.get('updated_count', 0)
            total_cryptos = result.get('total_cryptos', 0)
            failed_count = result.get('failed_count', 0)
            source = result.get('source', 'unknown')

            if total_cryptos > 0:
                if failed_count == 0:
                    status_text = f"✅ Updated all {updated_count} prices from {source}"
                    status_color = "green"
                elif updated_count > 0:
                    status_text = f"⚠️ Updated {updated_count}/{total_cryptos} prices from {source} ({failed_count} failed)"
                    status_color = "orange"
                else:
                    status_text = f"❌ Failed to get any prices from {source}"
                    status_color = "red"
            else:
                status_text = "Only stablecoins/fiat found"
                status_color = "gray"

            self.usd_status_label.config(text=status_text, foreground=status_color)

        except Exception as e:
            self.usd_status_label.config(text=f"Display error: {str(e)[:30]}...", foreground="red")
            print(f"Error updating wallet display: {e}")
            import traceback
            traceback.print_exc()

    def refresh_wallet(self):
        """Refresh the wallet table with basic estimated values."""
        if not self.db:
            # Show message in empty table
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)
            self.wallet_tree.insert('', tk.END, values=['No database', '0.00000000', '$0.00', 'N/A'])
            self.total_value_label.config(text="Total Value: $0.00")
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🔴")
            return

        try:
            # Update status indicator
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🟡")

            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Get wallet data
            balances = self.db.get_balance()

            total_usd_value = 0

            # Populate wallet with estimated values
            for currency, balance in balances.items():
                if balance > 0:  # Only show non-zero balances
                    # Estimate USD value (simplified)
                    if currency in ['USD', 'USDT', 'USDC', 'BUSD', 'DAI']:
                        usd_value = balance
                        usd_price = 1.0
                    else:
                        # Placeholder estimates for other currencies
                        placeholder_prices = {
                            'BTC': 43000.0, 'ETH': 2500.0, 'ADA': 0.45, 'XRP': 0.55,
                            'LTC': 75.0, 'DOT': 7.0, 'EUR': 1.1
                        }
                        usd_price = placeholder_prices.get(currency, 1.0)
                        usd_value = balance * usd_price

                    total_usd_value += usd_value

                    values = [
                        currency,
                        f"{balance:.8f}",
                        f"${usd_value:.2f}",
                        f"${usd_price:.2f}" if usd_price != 1.0 else "Est."
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            self.total_value_label.config(text=f"Total Value: ${total_usd_value:.2f} (Est.)")

            # Clear USD status
            if hasattr(self, 'usd_status_label'):
                self.usd_status_label.config(text="Use 💲 Refresh USD for real prices", foreground="gray")

            # Update status indicator
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🟢")

        except Exception as e:
            self.wallet_tree.insert('', tk.END, values=[f'Error: {e}', '0.00000000', '$0.00', 'N/A'])
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🔴")

    def create_llm_tab(self):
        """Create the LLM responses table tab with channel column."""
        llm_frame = ttk.Frame(self.notebook)
        self.notebook.add(llm_frame, text="🤖 LLM Responses")

        # Control buttons
        control_frame = ttk.Frame(llm_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Live refresh indicator
        self.llm_status_label = ttk.Label(control_frame, text="🟢", font=('Arial', 10))
        self.llm_status_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(control_frame, text="Refresh", command=self.refresh_llm).pack(side=tk.LEFT, padx=5)

        # Channel filter
        ttk.Label(control_frame, text="Filter by channel:").pack(side=tk.LEFT, padx=5)
        self.llm_channel_filter = ttk.Combobox(control_frame, width=20)
        self.llm_channel_filter.pack(side=tk.LEFT, padx=5)
        self.llm_channel_filter.bind('<<ComboboxSelected>>', self.filter_llm_responses)

        # LLM responses treeview
        self.llm_tree = ttk.Treeview(llm_frame, show='headings')
        self.llm_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure LLM columns - ADD CHANNEL COLUMN
        llm_columns = ['ID', 'Timestamp', 'Channel', 'Action', 'Pair', 'Confidence', 'Entry Range', 'Stop Loss',
                       'Take Profit', 'Leverage']
        self.llm_tree['columns'] = llm_columns

        # Set column widths
        column_widths = {
            'ID': 50,
            'Timestamp': 130,
            'Channel': 120,  # New channel column
            'Action': 60,
            'Pair': 80,
            'Confidence': 80,
            'Entry Range': 100,
            'Stop Loss': 80,
            'Take Profit': 120,
            'Leverage': 80
        }

        for col in llm_columns:
            self.llm_tree.heading(col, text=col)
            self.llm_tree.column(col, width=column_widths.get(col, 100))

        # Scrollbar for LLM
        llm_scrollbar = ttk.Scrollbar(llm_frame, orient=tk.VERTICAL, command=self.llm_tree.yview)
        self.llm_tree.configure(yscrollcommand=llm_scrollbar.set)
        llm_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def load_log_file(self):
        """Load existing log file content."""
        try:
            # Use absolute path to the log file in the project root
            log_file_path = os.path.join(project_root, "trading_bot.log")

            if os.path.exists(log_file_path):
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()
                self.log_text.insert(tk.END, f"=== Loading from {log_file_path} ===\n")
                self.log_text.insert(tk.END, log_content)
                if self.auto_scroll_var.get():
                    self.log_text.see(tk.END)
            else:
                self.log_text.insert(tk.END, f"No log file found at: {log_file_path}\n")
                self.log_text.insert(tk.END, "\nStart the trading bot to generate logs.\n")
        except Exception as e:
            self.log_text.insert(tk.END, f"Error loading log file: {e}\n")

    def clear_logs(self):
        """Clear the logs display."""
        self.log_text.delete(1.0, tk.END)

    def refresh_logs(self):
        """Refresh logs from file."""
        self.clear_logs()
        self.load_log_file()

    def refresh_trades(self):
        """Refresh the trades table."""
        if not self.db:
            # Show message in empty table
            self.trades_tree.insert('', tk.END, values=['', '', 'No database connection', '', '', '', '', '', ''])
            self.status_bar.config(text="No database connection")
            return

        try:
            # Clear existing items
            for item in self.trades_tree.get_children():
                self.trades_tree.delete(item)

            # Get trades from database
            trades = self.db.get_trades()

            # Update channel filter
            channels = set()
            for trade in trades:
                if trade.get('telegram_channel'):
                    channels.add(trade['telegram_channel'])

            self.channel_filter['values'] = ['All'] + sorted(list(channels))
            if not self.channel_filter.get():
                self.channel_filter.set('All')

            # Populate trades
            for trade in trades:
                pair = f"{trade.get('base_currency', '')}/{trade.get('quote_currency', '')}"
                values = [
                    trade.get('id', ''),
                    trade.get('timestamp', ''),
                    trade.get('telegram_channel', ''),
                    pair,
                    trade.get('side', ''),
                    f"{trade.get('volume', 0):.6f}",
                    f"{trade.get('price', 0):.6f}" if trade.get('price') else 'Market',
                    trade.get('status', ''),
                    trade.get('leverage', 0) if trade.get('leverage') else ''
                ]
                self.trades_tree.insert('', tk.END, values=values)

            self.status_bar.config(text=f"Trades refreshed: {len(trades)} records")
        except Exception as e:
            self.trades_tree.insert('', tk.END, values=['', '', f'Error: {e}', '', '', '', '', '', ''])
            self.status_bar.config(text=f"Error refreshing trades: {e}")

    def filter_trades(self, event=None):
        """Filter trades by selected channel."""
        if not self.db:
            return

        try:
            selected_channel = self.channel_filter.get()

            # Clear existing items
            for item in self.trades_tree.get_children():
                self.trades_tree.delete(item)

            # Get filtered trades
            if selected_channel == 'All':
                trades = self.db.get_trades()
            else:
                trades = self.db.get_trades_by_channel(selected_channel)

            # Populate filtered trades
            for trade in trades:
                pair = f"{trade.get('base_currency', '')}/{trade.get('quote_currency', '')}"
                values = [
                    trade.get('id', ''),
                    trade.get('timestamp', ''),
                    trade.get('telegram_channel', ''),
                    pair,
                    trade.get('side', ''),
                    f"{trade.get('volume', 0):.6f}",
                    f"{trade.get('price', 0):.6f}" if trade.get('price') else 'Market',
                    trade.get('status', ''),
                    trade.get('leverage', 0) if trade.get('leverage') else ''
                ]
                self.trades_tree.insert('', tk.END, values=values)

            self.status_bar.config(text=f"Filtered trades: {len(trades)} records")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to filter trades: {e}")

    def refresh_wallet(self):
        """Refresh the wallet table with basic estimated values."""
        if not self.db:
            # Show message in empty table
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)
            self.wallet_tree.insert('', tk.END, values=['No database', '', '', ''])
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🔴")
            return

        try:
            # Update status indicator
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🟡")

            # Clear existing items
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)

            # Get wallet data
            balances = self.db.get_balance()

            # Populate wallet with just balances, no price estimates
            for currency, balance in balances.items():
                if balance > 0:  # Only show non-zero balances
                    values = [
                        currency,
                        f"{balance:.8f}",
                        "",  # USD value is blank until "Refresh USD" is clicked
                        ""   # USD price is blank until "Refresh USD" is clicked
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            # Clear USD status
            if hasattr(self, 'usd_status_label'):
                self.usd_status_label.config(text="Use 💲 Refresh USD for real prices", foreground="gray")

            # Update status indicator
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🟢")

        except Exception as e:
            self.wallet_tree.insert('', tk.END, values=[f'Error: {e}', '', '', ''])
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🔴")

    def refresh_llm(self):
        """Refresh the LLM responses table."""
        if not self.db:
            # Show message in empty table
            for item in self.llm_tree.get_children():
                self.llm_tree.delete(item)
            self.llm_tree.insert('', tk.END, values=['', '', 'No database connection', '', '', '', '', '', ''])
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🔴")
            return

        try:
            # Update status indicator
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🟡")

            # Clear existing items
            for item in self.llm_tree.get_children():
                self.llm_tree.delete(item)

            # Get LLM responses
            if hasattr(self.db, 'cursor'):
                # Using simple DB connection
                try:
                    self.db.cursor.execute("SELECT * FROM llm_responses ORDER BY timestamp DESC")
                    columns = [description[0] for description in self.db.cursor.description]
                    responses = [dict(zip(columns, row)) for row in self.db.cursor.fetchall()]
                except Exception as e:
                    self.llm_tree.insert('', tk.END, values=['', '', f'Error: {e}', '', '', '', '', '', ''])
                    if hasattr(self, 'llm_status_label'):
                        self.llm_status_label.config(text="🔴")
                    return
            else:
                # Using full database object
                cursor = self.db.cursor
                cursor.execute("SELECT * FROM llm_responses ORDER BY timestamp DESC")
                columns = [description[0] for description in cursor.description]
                responses = [dict(zip(columns, row)) for row in cursor.fetchall()]

            # Populate LLM responses
            for response in responses:
                pair = f"{response.get('base_currency', '')}/{response.get('quote_currency', '')}"
                entry_range = response.get('entry_price_range', '')
                if entry_range and entry_range != 'null':
                    try:
                        import json
                        entry_range = json.loads(entry_range)
                        if isinstance(entry_range, list) and len(entry_range) >= 2:
                            entry_range = f"{entry_range[0]}-{entry_range[1]}"
                        else:
                            entry_range = str(entry_range)
                    except:
                        entry_range = str(entry_range)

                take_profit = response.get('take_profit_targets', '')
                if take_profit and take_profit != 'null':
                    try:
                        import json
                        take_profit = json.loads(take_profit)
                        if isinstance(take_profit, list):
                            take_profit = ', '.join(map(str, take_profit[:3]))  # Show first 3
                        else:
                            take_profit = str(take_profit)
                    except:
                        take_profit = str(take_profit)

                values = [
                    response.get('id', ''),
                    response.get('timestamp', ''),
                    response.get('action', ''),
                    pair,
                    response.get('confidence', ''),
                    entry_range,
                    response.get('stop_loss', ''),
                    take_profit,
                    response.get('leverage', '')
                ]
                self.llm_tree.insert('', tk.END, values=values)

            # Update status indicator
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🟢")

        except Exception as e:
            self.llm_tree.insert('', tk.END, values=['', '', f'Error: {e}', '', '', '', '', '', ''])
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🔴")
                self.llm_tree.insert('', tk.END, values=['', '', f'Error: {e}', '', '', '', '', '', ''])
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🔴")

    def refresh_llm(self):
        """Refresh the LLM responses table with channel information."""
        if not self.db:
            # Show message in empty table
            for item in self.llm_tree.get_children():
                self.llm_tree.delete(item)
            self.llm_tree.insert('', tk.END, values=['', '', 'No database connection', '', '', '', '', '', '', ''])
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🔴")
            return

        try:
            # Update status indicator
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🟡")

            # Clear existing items
            for item in self.llm_tree.get_children():
                self.llm_tree.delete(item)

            # Get LLM responses
            if hasattr(self.db, 'get_llm_responses'):
                # Use the new method if available
                responses = self.db.get_llm_responses()
            else:
                # Fallback to direct SQL query
                if hasattr(self.db, 'cursor'):
                    try:
                        self.db.cursor.execute("SELECT * FROM llm_responses ORDER BY timestamp DESC")
                        columns = [description[0] for description in self.db.cursor.description]
                        responses = [dict(zip(columns, row)) for row in self.db.cursor.fetchall()]
                    except Exception as e:
                        self.llm_tree.insert('', tk.END, values=['', '', '', f'Error: {e}', '', '', '', '', '', ''])
                        if hasattr(self, 'llm_status_label'):
                            self.llm_status_label.config(text="🔴")
                        return
                else:
                    # Using full database object
                    cursor = self.db.cursor
                    cursor.execute("SELECT * FROM llm_responses ORDER BY timestamp DESC")
                    columns = [description[0] for description in cursor.description]
                    responses = [dict(zip(columns, row)) for row in cursor.fetchall()]

            # Update channel filter
            channels = set()
            for response in responses:
                if response.get('channel'):
                    channels.add(response['channel'])

            if hasattr(self, 'llm_channel_filter'):
                self.llm_channel_filter['values'] = ['All'] + sorted(list(channels))
                if not self.llm_channel_filter.get():
                    self.llm_channel_filter.set('All')

            # Populate LLM responses
            for response in responses:
                pair = f"{response.get('base_currency', '')}/{response.get('quote_currency', '')}"
                entry_range = response.get('entry_price_range', '')
                if entry_range and entry_range != 'null':
                    try:
                        import json
                        entry_range = json.loads(entry_range)
                        if isinstance(entry_range, list) and len(entry_range) >= 2:
                            entry_range = f"{entry_range[0]}-{entry_range[1]}"
                        else:
                            entry_range = str(entry_range)
                    except:
                        entry_range = str(entry_range)

                take_profit = response.get('take_profit_targets', '')
                if take_profit and take_profit != 'null':
                    try:
                        import json
                        take_profit = json.loads(take_profit)
                        if isinstance(take_profit, list):
                            take_profit = ', '.join(map(str, take_profit[:3]))  # Show first 3
                        else:
                            take_profit = str(take_profit)
                    except:
                        take_profit = str(take_profit)

                # Format timestamp
                timestamp = response.get('timestamp', '')
                if timestamp:
                    try:
                        from datetime import datetime
                        if 'T' in timestamp:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        else:
                            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                        timestamp = dt.strftime('%m/%d %H:%M:%S')
                    except:
                        pass  # Keep original if parsing fails

                values = [
                    response.get('id', ''),
                    timestamp,
                    response.get('channel', 'Unknown'),  # Add channel value
                    response.get('action', ''),
                    pair,
                    response.get('confidence', ''),
                    entry_range,
                    response.get('stop_loss', ''),
                    take_profit,
                    response.get('leverage', '')
                ]
                self.llm_tree.insert('', tk.END, values=values)

            # Update status indicator
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🟢")

        except Exception as e:
            self.llm_tree.insert('', tk.END, values=['', '', '', f'Error: {e}', '', '', '', '', '', ''])
            if hasattr(self, 'llm_status_label'):
                self.llm_status_label.config(text="🔴")

    def filter_llm_responses(self, event=None):
        """Filter LLM responses by selected channel."""
        if not self.db or not hasattr(self, 'llm_channel_filter'):
            return

        try:
            selected_channel = self.llm_channel_filter.get()

            # Clear existing items
            for item in self.llm_tree.get_children():
                self.llm_tree.delete(item)

            # Get filtered responses
            if selected_channel == 'All':
                if hasattr(self.db, 'get_llm_responses'):
                    responses = self.db.get_llm_responses()
                else:
                    # Fallback to all responses
                    self.refresh_llm()
                    return
            else:
                if hasattr(self.db, 'get_llm_responses_by_channel'):
                    responses = self.db.get_llm_responses_by_channel(selected_channel)
                else:
                    # Fallback: filter in Python
                    if hasattr(self.db, 'cursor'):
                        self.db.cursor.execute("SELECT * FROM llm_responses WHERE channel = ? ORDER BY timestamp DESC",
                                               (selected_channel,))
                        columns = [description[0] for description in self.db.cursor.description]
                        responses = [dict(zip(columns, row)) for row in self.db.cursor.fetchall()]
                    else:
                        responses = []

            # Populate filtered responses (same logic as refresh_llm)
            for response in responses:
                pair = f"{response.get('base_currency', '')}/{response.get('quote_currency', '')}"
                entry_range = response.get('entry_price_range', '')
                if entry_range and entry_range != 'null':
                    try:
                        import json
                        entry_range = json.loads(entry_range)
                        if isinstance(entry_range, list) and len(entry_range) >= 2:
                            entry_range = f"{entry_range[0]}-{entry_range[1]}"
                        else:
                            entry_range = str(entry_range)
                    except:
                        entry_range = str(entry_range)

                take_profit = response.get('take_profit_targets', '')
                if take_profit and take_profit != 'null':
                    try:
                        import json
                        take_profit = json.loads(take_profit)
                        if isinstance(take_profit, list):
                            take_profit = ', '.join(map(str, take_profit[:3]))
                        else:
                            take_profit = str(take_profit)
                    except:
                        take_profit = str(take_profit)

                # Format timestamp
                timestamp = response.get('timestamp', '')
                if timestamp:
                    try:
                        from datetime import datetime
                        if 'T' in timestamp:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        else:
                            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                        timestamp = dt.strftime('%m/%d %H:%M:%S')
                    except:
                        pass

                values = [
                    response.get('id', ''),
                    timestamp,
                    response.get('channel', 'Unknown'),
                    response.get('action', ''),
                    pair,
                    response.get('confidence', ''),
                    entry_range,
                    response.get('stop_loss', ''),
                    take_profit,
                    response.get('leverage', '')
                ]
                self.llm_tree.insert('', tk.END, values=values)

            self.status_bar.config(text=f"Filtered LLM responses: {len(responses)} records")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to filter LLM responses: {e}")
            print(f"Error filtering LLM responses: {e}")
            import traceback
            traceback.print_exc()

    def update_gui(self):
        """Update GUI elements from queue."""
        try:
            while True:
                msg_data = self.gui_queue.get_nowait()

                # Handle different message formats
                if len(msg_data) == 2:
                    msg_type, content = msg_data
                    level = "INFO"
                elif len(msg_data) == 3:
                    msg_type, content, level = msg_data
                else:
                    continue

                if msg_type == 'log':
                    self.add_log_message(content, level)
                elif msg_type == 'status':
                    self.status_bar.config(text=content)
                    if hasattr(self, 'bot_status_label'):
                        color = "green" if "started" in content.lower() else "red"
                        self.bot_status_label.config(foreground=color)
                elif msg_type == 'error':
                    self.add_log_message(f"ERROR: {content}", "ERROR")
                    if hasattr(self, 'bot_status_label'):
                        self.bot_status_label.config(foreground="red")

        except queue.Empty:
            pass

        # Schedule next update
        self.root.after(100, self.update_gui)

    def add_log_message(self, message, level="INFO"):
        """Add a log message to the display with color coding."""
        if not self.show_live_var.get():
            return

        # Don't add timestamp if message already has one (from logging formatter)
        if message.strip().startswith("20") and " INFO " in message or " ERROR " in message or " WARNING " in message:
            # Message is already formatted by logging, use as-is
            formatted_message = message
            # Extract level from formatted message
            if " ERROR " in message:
                level = "ERROR"
            elif " WARNING " in message:
                level = "WARNING"
            elif " INFO " in message:
                level = "INFO"
        else:
            # Add timestamp for non-logging messages
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_message = f"{timestamp} {message.strip()}\n"

        # Determine display properties based on level
        if level == "ERROR" or "ERROR" in formatted_message:
            tag = "ERROR"
        elif level == "WARNING" or "WARNING" in formatted_message:
            tag = "WARNING"
        elif level == "SUCCESS" or "✅" in formatted_message:
            tag = "SUCCESS"
        elif level == "INFO" or "INFO" in formatted_message:
            tag = "INFO"
        else:
            tag = "INFO"

        # Insert with color coding
        self.log_text.insert(tk.END, formatted_message, tag)

        # Auto-scroll if enabled
        if self.auto_scroll_var.get():
            self.log_text.see(tk.END)

        # Limit log size (keep last 1000 lines)
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 1000:
            self.log_text.delete('1.0', f'{lines-1000}.0')

        # Update log status indicator
        if hasattr(self, 'log_status_label'):
            self.log_status_label.config(text="🟢")

    def auto_refresh(self):
        """Auto-refresh data continuously for live updates."""
        try:
            # Always refresh all tabs for live updates
            if self.db:
                self.refresh_trades()
                if not self.loaded_wallet_tab:
                    self.refresh_wallet()
                    self.loaded_wallet_tab = True
                self.refresh_llm()

            # Update status bar with current time
            current_time = datetime.now().strftime("%H:%M:%S")
            connection_status = "🟢 LIVE" if self.bot_running else ("🟡 MONITORING" if self.db else "🔴 NO DATA")
            self.status_bar.config(text=f"Last refresh: {current_time} | Status: {connection_status}")

        except Exception as e:
            print(f"Auto-refresh error: {e}")

        # Schedule next auto-refresh (2 seconds for live updates)
        self.root.after(self.auto_refresh_interval, self.auto_refresh)


def main(integrated_bot=False):
    """Main function to start the GUI."""
    root = tk.Tk()
    app = TradingBotGUI(root, run_bot=integrated_bot)

    def on_closing():
        """Handle window closing."""
        if hasattr(app, 'db') and app.db:
            try:
                app.db.close()
            except:
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("GUI closed by user")
    except Exception as e:
        print(f"GUI error: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Trading Bot GUI')
    parser.add_argument('--with-bot', action='store_true',
                       help='Run the trading bot integrated with the GUI')
    parser.add_argument('--monitor-only', action='store_true',
                       help='Only monitor existing bot (default)')

    args = parser.parse_args()

    if args.with_bot:
        print("🤖 Starting GUI with integrated trading bot...")
        main(integrated_bot=True)
    else:
        print("📊 Starting GUI in monitor-only mode...")
        main(integrated_bot=False)