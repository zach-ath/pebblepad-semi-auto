import argparse
import logging
import sys
from pipeline import run_pipeline
from pebble_engine import run_playwright_phase

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def print_summary_report(summary_dict: dict, injected_count: int = 0, is_dry_run: bool = False):
    """Task 6.1: Terminal Summary Reporting"""
    print("\n" + "="*45)
    print("      --- P3A Automation Summary ---")
    print("="*45)
    
    if is_dry_run:
        print("[MODE] DRY-RUN (Offline Pipeline Only)\n")
        print(f"Rows Ready for Injection: {summary_dict['categorized_count']}")
    else:
        print("[MODE] FULL EXECUTION\n")
        print(f"Total Rows Successfully Injected: {injected_count}")
        print(f"Total Rows Failed to Inject:      {summary_dict['categorized_count'] - injected_count}")
        
    print(f"Total Duplicates Skipped:         {summary_dict['duplicates']}")
    print(f"Total Validation Errors Caught:   {summary_dict['errors']}")
    print(f"Total Uncategorized Rows:         {summary_dict['uncategorized']}")
    print("=============================================\n")


def main():
    parser = argparse.ArgumentParser(description="P3A: PebblePad Python Playwright Automation")
    parser.add_argument('--test', action='store_true', help="Run in dry-run mode (offline pipeline only)")
    parser.add_argument('--remap', action='store_true', help="Invalidate navigation cache and remap URLs")
    args = parser.parse_args()

    input_csv = 'inputs/data.csv'
    db_csv = 'outputs/internal_database.csv'
    rules_json = 'regex_rules.json'
    output_dir = 'outputs'
    cache_csv = 'outputs/Workbook_log_pages.csv'
    
    # Update to your institution's specific PebblePad SSO login URL
    pebblepad_login_url = "https://v3.pebblepad.com.au/login/Login/ChooseInstall"

    try:
        logging.info("Running Offline Pipeline (Phases 1-3)...")
        summary = run_pipeline(
            input_csv=input_csv,
            db_csv=db_csv,
            rules_json=rules_json,
            output_dir=output_dir
        )
        
        if args.test:
            print_summary_report(summary, is_dry_run=True)
            logging.info("Dry-run complete. Output CSVs have been updated.")
            sys.exit(0)

        logging.info("Starting Browser Execution...")
        if args.remap:
            logging.info("--remap flag detected. URL Navigation cache will be refreshed.")
            
        injected_count = run_playwright_phase(
            login_url=pebblepad_login_url,
            cache_csv=cache_csv,
            db_csv=db_csv,
            remap=args.remap,
            valid_rows=summary['valid_data']
        )
        
        # Final Summary
        print_summary_report(summary, injected_count=injected_count)
        
    except Exception as e:
        logging.error(f"Fatal Automation Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()