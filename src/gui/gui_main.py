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
        
        if not self.settings_loaded:
            # Try to create a minimal database connection for read-only access
            try:
                # Try both database types
                import sqlite3
                if os.path.exists("dry_run.db"):
                    self.db = self._create_simple_db_connection("dry_run.db")
                    self.db_type = "dry_run"
                elif os.path.exists("live_trading.db"):
                    self.db = self._create_simple_db_connection("live_trading.db")
                    self.db_type = "live"
                else:
                    print("No database files found. GUI will show empty tables.")
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
            log_files = [
                "trading_bot.log",
                "../trading_bot.log", 
                "../../trading_bot.log",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trading_bot.log")
            ]
            
            # Find the log file and monitor it
            for log_file in log_files:
                if os.path.exists(log_file):
                    self.current_log_file = log_file
                    self.last_log_size = os.path.getsize(log_file)
                    print(f"📁 Monitoring log file: {log_file}")
                    break
            else:
                self.current_log_file = None
                self.last_log_size = 0
                print("📁 No existing log file found - will create when bot starts")
            
        except Exception as e:
            print(f"Error setting up log monitoring: {e}")
        
        # Schedule next check
        self.root.after(500, self.check_log_updates)  # Check every 0.5 seconds for faster updates
    
    def check_log_updates(self):
        """Check if log file has been updated."""
        try:
            # First check if log file was created (if it didn't exist before)
            if not self.current_log_file:
                log_files = [
                    "trading_bot.log",
                    "../trading_bot.log", 
                    "../../trading_bot.log",
                    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trading_bot.log")
                ]
                
                for log_file in log_files:
                    if os.path.exists(log_file):
                        self.current_log_file = log_file
                        self.last_log_size = 0  # Start from beginning for new file
                        print(f"📁 Found new log file: {log_file}")
                        # Update the log status indicator
                        if hasattr(self, 'log_status_label'):
                            self.log_status_label.config(text="🟢")
                        break
            
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
        """Create the wallet database table tab."""
        wallet_frame = ttk.Frame(self.notebook)
        self.notebook.add(wallet_frame, text="💰 Wallet")

        # Control buttons
        control_frame = ttk.Frame(wallet_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Live refresh indicator
        self.wallet_status_label = ttk.Label(control_frame, text="🟢", font=('Arial', 10))
        self.wallet_status_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(control_frame, text="Refresh", command=self.refresh_wallet).pack(side=tk.LEFT, padx=5)

        # Total value label
        self.total_value_label = ttk.Label(control_frame, text="Total Value: Calculating...", font=('Arial', 10, 'bold'))
        self.total_value_label.pack(side=tk.RIGHT, padx=5)

        # Wallet treeview
        self.wallet_tree = ttk.Treeview(wallet_frame, show='headings')
        self.wallet_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure wallet columns
        wallet_columns = ['Currency', 'Balance', 'USD Value (Est.)']
        self.wallet_tree['columns'] = wallet_columns

        for col in wallet_columns:
            self.wallet_tree.heading(col, text=col)
            self.wallet_tree.column(col, width=150)

        # Scrollbar for wallet
        wallet_scrollbar = ttk.Scrollbar(wallet_frame, orient=tk.VERTICAL, command=self.wallet_tree.yview)
        self.wallet_tree.configure(yscrollcommand=wallet_scrollbar.set)
        wallet_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def create_llm_tab(self):
        """Create the LLM responses table tab."""
        llm_frame = ttk.Frame(self.notebook)
        self.notebook.add(llm_frame, text="🤖 LLM Responses")

        # Control buttons
        control_frame = ttk.Frame(llm_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)

        # Live refresh indicator
        self.llm_status_label = ttk.Label(control_frame, text="🟢", font=('Arial', 10))
        self.llm_status_label.pack(side=tk.LEFT, padx=2)

        ttk.Button(control_frame, text="Refresh", command=self.refresh_llm).pack(side=tk.LEFT, padx=5)

        # LLM responses treeview
        self.llm_tree = ttk.Treeview(llm_frame, show='headings')
        self.llm_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure LLM columns
        llm_columns = ['ID', 'Timestamp', 'Action', 'Pair', 'Confidence', 'Entry Range', 'Stop Loss', 'Take Profit', 'Leverage']
        self.llm_tree['columns'] = llm_columns

        for col in llm_columns:
            self.llm_tree.heading(col, text=col)
            self.llm_tree.column(col, width=120)

        # Scrollbar for LLM
        llm_scrollbar = ttk.Scrollbar(llm_frame, orient=tk.VERTICAL, command=self.llm_tree.yview)
        self.llm_tree.configure(yscrollcommand=llm_scrollbar.set)
        llm_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def load_log_file(self):
        """Load existing log file content."""
        try:
            # Try multiple possible log file locations
            possible_logs = [
                "trading_bot.log",
                "../trading_bot.log",
                "../../trading_bot.log",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trading_bot.log")
            ]

            log_content = ""
            log_found = False

            for log_file in possible_logs:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        log_content = f.read()
                    log_found = True
                    self.log_text.insert(tk.END, f"=== Loading from {log_file} ===\n")
                    break

            if log_found:
                self.log_text.insert(tk.END, log_content)
                if self.auto_scroll_var.get():
                    self.log_text.see(tk.END)
            else:
                self.log_text.insert(tk.END, "No log file found. Checked locations:\n")
                for log_file in possible_logs:
                    self.log_text.insert(tk.END, f"  - {os.path.abspath(log_file)}\n")
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
        """Refresh the wallet table."""
        if not self.db:
            # Show message in empty table
            for item in self.wallet_tree.get_children():
                self.wallet_tree.delete(item)
            self.wallet_tree.insert('', tk.END, values=['No database', '0.00000000', '$0.00'])
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

            # Populate wallet
            for currency, balance in balances.items():
                if balance > 0:  # Only show non-zero balances
                    # Estimate USD value (simplified)
                    usd_value = balance if currency in ['USD', 'USDT', 'USDC'] else balance * 1.0  # Placeholder
                    total_usd_value += usd_value

                    values = [
                        currency,
                        f"{balance:.8f}",
                        f"${usd_value:.2f}"
                    ]
                    self.wallet_tree.insert('', tk.END, values=values)

            self.total_value_label.config(text=f"Total Value: ${total_usd_value:.2f}")

            # Update status indicator
            if hasattr(self, 'wallet_status_label'):
                self.wallet_status_label.config(text="🟢")

        except Exception as e:
            self.wallet_tree.insert('', tk.END, values=[f'Error: {e}', '0.00000000', '$0.00'])
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
                self.refresh_wallet() 
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