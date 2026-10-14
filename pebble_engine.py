import csv
import time
import logging
import re
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, Page, expect, TimeoutError as PlaywrightTimeoutError

def get_cached_urls(cache_csv: str) -> dict:
    urls = {}
    if Path(cache_csv).exists():
        with open(cache_csv, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['Page Title'] and row['URL']:
                    urls[row['Page Title']] = row['URL']
    return urls

def cache_urls(cache_csv: str, urls: dict):
    with open(cache_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Page Title', 'URL'])
        writer.writeheader()
        for title, url in urls.items():
            writer.writerow({'Page Title': title, 'URL': url})

def handle_auto_share_popup(page: Page):
    """Detects and acknowledges the pesky PebblePad Auto-share terms modal."""
    try:
        modal = page.locator('div[data-hook="pop-up-modal"]')
        if modal.is_visible(timeout=3000):
            logging.info("Auto-share popup detected. Acknowledging terms...")
            
            label = page.locator('label[for="agreeToTermsCheckbox"]')
            if label.is_visible():
                label.click()
            
            continue_btn = page.locator('button[data-hook="auto-submit-modal-confirm-btn"]')
            if continue_btn.is_visible():
                continue_btn.click()
                
            modal.wait_for(state='hidden', timeout=5000)
            logging.info("Popup cleared.")
    except Exception:
        pass

def map_and_cache_navigation(page: Page, cache_csv: str, remap: bool, valid_rows: list) -> dict:
    if not remap:
        cached_urls = get_cached_urls(cache_csv)
        if cached_urls:
            logging.info(f"Using {len(cached_urls)} cached navigation URLs from {cache_csv}")
            return cached_urls

    logging.info("Building navigation cache by actively mapping the Angular Menu...")
    final_template_urls = {}
    
    target_pages = set([row['Target Page'] for row in valid_rows if row.get('Target Page')])
    base_workbook_url = page.evaluate("window.location.href")
    
    for title in target_pages:
        logging.info(f"Locating menu item for: '{title}'")
        try:
            current_url = page.evaluate("window.location.href")
            if current_url != base_workbook_url:
                logging.info("Resetting view to root workbook page to expose sidebar menu...")
                page.goto(base_workbook_url, wait_until='networkidle')
                time.sleep(1.5) 
            
            # Clean the search string to handle custom naming in regex_rules.json
            search_term = re.sub(r'(?i)\s+log$', '', title).strip()
            
            # Target the exact inner span using its title attribute.
            menu_item = page.locator(f'span.navigation-item__title[title*="{search_term}" i]').first
            
            # Target the parent accordion using the reliable data-hook
            dropdown = page.locator('span[data-hook="navigation-item__edit-title"][title="Clinical Examinations Log"]')
            
            try:
                # Wait up to 2 seconds to see if the menu item is ALREADY visible
                menu_item.wait_for(state="visible", timeout=2000)
                
            except PlaywrightTimeoutError:
                # If it times out, the menu is likely closed. Let's open it.
                logging.info("Expanding 'Clinical Examinations Log' dropdown...")
                
                # Fallback in case PebblePad removed the data-hook
                if not dropdown.is_visible():
                    dropdown = page.locator('text="Clinical Examinations Log"').first
                
                dropdown.click()
                
                try:
                    # Dynamically wait for the inner menu item to render
                    menu_item.wait_for(state="visible", timeout=5000)
                except PlaywrightTimeoutError:
                    # Absolute Fallback if PebblePad changed their CSS classes again
                    menu_item = page.locator(f'text=/{search_term}/i').last
                    menu_item.wait_for(state="visible", timeout=5000)
                
            menu_item.scroll_into_view_if_needed()
            menu_item.click()
            page.wait_for_load_state('networkidle')
            
            # Target and click the template link
            template_link = page.locator('span').filter(has_text="Record your clinical examinations using this template:").get_by_role("link")
            template_link.wait_for(state="visible", timeout=10000)
            template_link.click()
            
            page.wait_for_load_state('networkidle')
            time.sleep(2) 
            
            handle_auto_share_popup(page)
            
            # Automatically save the blank template so PebblePad doesn't discard the URL
            save_btn = page.locator('button').filter(has_text="Save").first
            if save_btn.is_visible():
                logging.info(f"Saving newly instantiated template for '{title}'...")
                save_btn.click()
                time.sleep(2)
            
            final_template_urls[title] = page.evaluate("window.location.href")
            logging.info(f"Successfully cached data-entry URL for: {title}")
            
        except Exception as e:
            logging.warning(f"Skipping '{title}': Could not map navigation. ({type(e).__name__})")
            continue

    if final_template_urls:
        cache_urls(cache_csv, final_template_urls)
        logging.info(f"Navigation mapping complete. Cached {len(final_template_urls)} data-entry URLs.")
    else:
        logging.error("Failed to map any template URLs.")

    return final_template_urls

def dispatch_angular_text(target_row, col_idx, value):
    """Task 5.2: Use Native Playwright typing to reliably trigger Angular reactive forms."""
    cell = target_row.locator('.table-el__cell').nth(col_idx)
    input_el = cell.locator('input, textarea, [contenteditable="true"]').first
    
    input_el.click()
    input_el.fill(str(value))
    input_el.press('Tab')
    time.sleep(0.1) 

def inject_date_hack(target_row, date_string):
    """Task 5.4: Isolate scope hook for <table-cell-datepicker>"""
    date_cell = target_row.locator('.table-el__cell').nth(0) 
    
    date_cell.evaluate("""(cellElem, dateString) => {
        const parts = dateString.split('/');
        let year = parseInt(parts[2], 10);
        if (year < 100) year += 2000;
        const jsDate = new Date(year, parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
        
        const datePicker = cellElem.tagName.toLowerCase() === 'table-cell-datepicker' ? cellElem : cellElem.querySelector('table-cell-datepicker');
        if (!datePicker) throw new Error('Datepicker not found in cell');
        
        const ngEl = window.angular.element(datePicker);
        const isoScope = ngEl.isolateScope ? ngEl.isolateScope() : null;
        const ctrl = isoScope ? isoScope.$ctrl : (ngEl.scope() && ngEl.scope().$ctrl);
        
        if (ctrl && typeof ctrl.update === 'function') {
            const scope = ngEl.scope();
            if (scope && typeof scope.$applyAsync === 'function') {
                scope.$applyAsync(() => ctrl.update(jsDate));
            } else {
                ctrl.update(jsDate);
                try { scope.$apply(); } catch(e) {}
            }
        } else {
            throw new Error('Angular controller update function not found');
        }
    }""", date_string)

def execute_injection_phase(page: Page, valid_rows: list, cached_urls: dict, db_csv: str) -> int:
    """Phase 5: Execute Angular injections row by row, table by table."""
    total_injected_count = 0
    
    grouped = {}
    for row in valid_rows:
        key = (row['Target Page'], row['Target Table'])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(row)
        
    for (target_page, target_table), rows in grouped.items():
        if target_page not in cached_urls:
            logging.error(f"Cannot inject. '{target_page}' not found in cached URLs.")
            continue
            
        logging.info(f"Navigating to '{target_page}' to inject {len(rows)} record(s)...")
        page.goto(cached_urls[target_page], wait_until='networkidle')
        
        handle_auto_share_popup(page)
        
        table_section = page.locator(f'section[aria-label="{target_table}" i]')
        try:
            table_section.wait_for(state='visible', timeout=15000)
        except Exception:
            logging.error(f"Table section '{target_table}' never became visible on page '{target_page}'. Skipping.")
            continue
            
        table_loc = table_section.locator('.table-el-wrapper')
        
        pending_db_writes = []
        
        for row_data in rows:
            logging.info(f"Injecting NHI: {row_data['NHI number']} into '{target_table}'")
            
            input_rows = table_loc.locator('tr[data-hook="table-el__row"]:has(td[data-cell-type="date"])')
            
            try:
                input_rows.first.wait_for(state='attached', timeout=10000)
            except Exception:
                logging.error(f"Data rows in table '{target_table}' failed to render in time. Skipping.")
                break
                
            prev_count = input_rows.count()
            target_row = input_rows.nth(prev_count - 1)
            
            try:
                # 0: Date | 1: NHI | 2: Exam | 3: Indication | 4: Obs | 5: Assist | 6: Indep
                inject_date_hack(target_row, row_data['Date'])
                dispatch_angular_text(target_row, 1, row_data['NHI number'])
                dispatch_angular_text(target_row, 2, row_data['Examination Type'])
                dispatch_angular_text(target_row, 3, row_data['Clinical Indications'])
                
                matrix_vals = [row_data['Observed'], row_data['Performed Assisted'], row_data['Performed independently']]
                for offset, val in enumerate(matrix_vals):
                    if val == 1:
                        dispatch_angular_text(target_row, 4 + offset, "1")
                
                expect(input_rows).to_have_count(prev_count + 1, timeout=10000)
                
                pending_db_writes.append(row_data)
                total_injected_count += 1
                
            except Exception as e:
                logging.error(f"Failed to inject row {row_data['NHI number']}: {str(e)}")
                continue

        # Bulk Save & DB Write
        if pending_db_writes:
            save_btn = page.locator('button').filter(has_text="Save").first
            if save_btn.is_visible():
                logging.info(f"Bulk saving {len(pending_db_writes)} records to '{target_table}'...")
                save_btn.click()
                time.sleep(4) 
                
            file_exists = Path(db_csv).is_file()
            with open(db_csv, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(pending_db_writes[0].keys()))
                if not file_exists:
                    writer.writeheader()
                for pending_row in pending_db_writes:
                    writer.writerow(pending_row)

    return total_injected_count

def run_playwright_phase(login_url: str, cache_csv: str, db_csv: str, remap: bool, valid_rows: list) -> int:
    if not valid_rows:
        logging.info("No valid rows passed to Playwright engine. Exiting early.")
        return 0

    with sync_playwright() as p:
        logging.info("Initializing Playwright headed browser (System chrome)...")
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()
        page = context.new_page()

        page.goto(login_url)
        print("\n" + "="*60)
        print("⏸  AUTOMATION PAUSED - MANUAL AUTHENTICATION REQUIRED")
        print("="*60)
        print("1. Please log in via the browser window (SSO/Credentials).")
        print("2. Navigate to your target Clinical Logbook Workbook.")
        print("3. ONCE THE WORKBOOK HAS LOADED, press ENTER here in the terminal.")
        print("="*60 + "\n")
        
        input("Press ENTER to resume automation...")
        
        page = context.pages[-1]
        page.bring_to_front()
        
        logging.info("Resuming execution...")

        final_urls = map_and_cache_navigation(page, cache_csv, remap, valid_rows)
        
        if not final_urls:
            logging.error("No valid navigation URLs found. Aborting.")
            browser.close()
            return 0
            
        logging.info("Proceeding to Phase 5: Angular Grid Injection.")
        injected_count = execute_injection_phase(page, valid_rows, final_urls, db_csv)
        
        browser.close()
        return injected_count