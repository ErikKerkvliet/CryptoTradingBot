#!/usr/bin/env python3
"""
Launch the GUI with different modes:
1. Monitor-only mode (default) - Just show existing data
2. Integrated bot mode - Run the trading bot inside the GUI
"""

import sys
import os
import argparse


def main():
    # Add project root to path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    sys.path.insert(0, project_root)

    parser = argparse.ArgumentParser(
        description='Trading Bot GUI Launcher',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python gui_with_bot.py                    # Monitor-only mode
  python gui_with_bot.py --integrated       # Run bot inside GUI
  python gui_with_bot.py --help            # Show this help
        """
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--integrated', action='store_true',
                       help='Run the trading bot integrated with the GUI (shows live logs)')
    group.add_argument('--monitor-only', action='store_true',
                       help='Only monitor existing data (default mode)')

    args = parser.parse_args()

    try:
        from src.gui.gui_main import main as gui_main

        if args.integrated:
            print("🤖 Starting GUI with INTEGRATED trading bot...")
            print("   • Live log output will appear in the GUI")
            print("   • Database updates in real-time")
            print("   • Bot runs in the same process")
            print()
            gui_main(integrated_bot=True)
        else:
            print("📊 Starting GUI in MONITOR-ONLY mode...")
            print("   • Views existing log files and databases")
            print("   • Read-only interface")
            print("   • Run your bot separately with: python main.py")
            print()
            gui_main(integrated_bot=False)

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("\nMake sure you're running this from the project root:")
        print(f"   cd {project_root}")
        print(f"   python src/gui/gui_with_bot.py")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()