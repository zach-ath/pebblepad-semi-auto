import re
import csv
import json
import sys
import os
import json
from pathlib import Path
from typing import Optional, List, Dict
from pydantic import BaseModel, field_validator, model_validator, ValidationError
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class ExamRecord(BaseModel):
    date: str
    nhi_number: str
    examination_type: str
    clinical_indications: str
    role: str
    
    # Extended Headers
    dob: str = ""
    sex: str = ""
    
    # Computed Matrix & Data Fields
    observed: int = 0
    performed_assisted: int = 0
    performed_independently: int = 0
    age_at_exam: Optional[int] = None
    
    # Routing Fields
    target_page: Optional[str] = None
    target_table: Optional[str] = None

    @field_validator('nhi_number')
    def validate_nhi(cls, v):
        v_upper = v.strip().upper()
        if not re.match(r'^[A-Z]{3}(\d{4}|\d{2}[A-Z]{2})$', v_upper):
            raise ValueError(f"Invalid NHI format: {v}")
        return v_upper

    @field_validator('date')
    def validate_date(cls, v):
        v_clean = v.strip()
        # Clean off time artifacts if present (e.g. "30/09/2026 10:17")
        v_clean = v_clean.split(' ')[0]
        try:
            parsed_date = datetime.strptime(v_clean, '%d/%m/%Y')
        except ValueError:
            try:
                parsed_date = datetime.strptime(v_clean, '%d/%m/%y')
            except ValueError:
                raise ValueError(f"Date must be DD/MM/YY or DD/MM/YYYY format: {v}")
        return parsed_date.strftime('%d/%m/%y')

    @model_validator(mode='after')
    def parse_matrix_and_age(self):
        # 1. Parse A/I/O Matrix
        role_str = str(self.role).upper().strip()
        has_a = bool(re.search(r'\b(A|ASSISTED|ASSIST)\b', role_str))
        has_i = bool(re.search(r'\b(I|IND|INDEPENDENT|INDEPENDENTLY)\b', role_str))
        has_o = bool(re.search(r'\b(O|OBS|OBSERVED|OBSERVE)\b', role_str))

        matches = sum([has_a, has_i, has_o])
        if matches > 1:
            raise ValueError(f"Unresolvable A/I/O conflict in role: '{self.role}'")
        if matches == 0:
            raise ValueError(f"No valid A/I/O role found in: '{self.role}'")

        self.observed = 1 if has_o else 0
        self.performed_assisted = 1 if has_a else 0
        self.performed_independently = 1 if has_i else 0

        # 2. Parse DOB & Calculate Age at time of exam
        if self.dob and self.date:
            try:
                dob_clean = self.dob.strip().split(' ')[0]
                try:
                    dob_dt = datetime.strptime(dob_clean, '%d/%m/%Y')
                except ValueError:
                    dob_dt = datetime.strptime(dob_clean, '%d/%m/%y')
                
                exam_dt = datetime.strptime(self.date.strip(), '%d/%m/%y')
                self.age_at_exam = exam_dt.year - dob_dt.year - ((exam_dt.month, exam_dt.day) < (dob_dt.month, dob_dt.day))
            except ValueError:
                self.age_at_exam = None
                logging.warning(f"Could not calculate age for NHI {self.nhi_number}. DOB: {self.dob}")

        return self

def load_regex_rules(filepath: str) -> dict:
    if hasattr(sys, '_MEIPASS'):
        bundle_path = os.path.join(sys._MEIPASS, os.path.basename(filepath))
        if os.path.exists(bundle_path):
            filepath = bundle_path

    with open(filepath, 'r') as f:
        return json.load(f)

def categorize_record(record: ExamRecord, rules: dict) -> ExamRecord:
    # --- DYNAMIC PAEDIATRIC INTERCEPT ---
    if record.age_at_exam is not None and record.age_at_exam <= 16:
        record.target_page = "Paediatrics"
        if record.age_at_exam <= 2:
            record.target_table = "0-2 years old" 
        elif record.age_at_exam <= 5:
            record.target_table = "3 - 5 years"   
        else:
            record.target_table = "6 - 16 years"  
        return record
    
    # --- STANDARD ADULT REGEX ROUTING ---
    # Restricted search strictly to Examination Type to prevent clinical indication false positives
    text_to_search = f"{record.examination_type}".lower()
    for key, rule in rules.items():
        for keyword in rule['keywords']:
            if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', text_to_search):
                record.target_page = rule['page']
                record.target_table = rule['table_aria_label']
                return record
    return record

def save_to_csv(filepath: str, fieldnames: List[str], data: List[Dict]):
    file_exists = Path(filepath).is_file()
    with open(filepath, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        for row in data:
            writer.writerow(row)

def run_pipeline(input_csv: str, db_csv: str, rules_json: str, output_dir: str) -> dict:
    rules = load_regex_rules(rules_json)
    
    existing_records = set()
    if Path(db_csv).exists():
        with open(db_csv, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_records.add((row.get('NHI number'), row.get('Date'), row.get('Examination Type')))

    validation_errors = []
    duplicates = []
    uncategorised = []
    valid_categorized = []

    out_headers = [
        'Date', 'NHI number', 'Examination Type', 'Clinical Indications', 'Role', 
        'DOB', 'Sex', 'Age', 
        'Observed', 'Performed Assisted', 'Performed independently', 
        'Target Page', 'Target Table'
    ]

    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 1. Base Column Mapping (Supports multiple hospital export formats)
            norm_date = row.get('Serviced') or row.get('Service date') or row.get('Date of Service') or row.get('Date', '')
            norm_exam = row.get('Services') or row.get('Service/Examination Type') or row.get('Service Type/Examination Type') or row.get('Examination Type', '')
            norm_clin = row.get('Clinical Indications') or row.get('Clinical Indication', '')
            norm_role = row.get('A/I/O') or row.get('Role', '')
            
            norm_nhi = row.get('NHI') or row.get('NHI number', '')
            norm_dob = row.get('DOB', '')
            norm_sex = row.get('Sex', '')

            # 2. Aggressive String Extraction (For concatenated 'Patient' columns)
            patient_str = row.get('Patient', '')
            if patient_str:
                # Extract NHI (3 Letters, 4 Numbers OR 3 Letters, 2 Numbers, 2 Letters)
                nhi_match = re.search(r'\b[A-Z]{3}(\d{4}|\d{2}[A-Z]{2})\b', patient_str, re.IGNORECASE)
                if nhi_match and not norm_nhi:
                    norm_nhi = nhi_match.group(0).upper()
                    
                # Extract DOB (DD/MM/YYYY)
                dob_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', patient_str)
                if dob_match and not norm_dob:
                    norm_dob = dob_match.group(0)
                    
                # Extract Sex
                sex_match = re.search(r'\b(Male|Female|Other)\b', patient_str, re.IGNORECASE)
                if sex_match and not norm_sex:
                    norm_sex = sex_match.group(0)

            # Assemble finalized row
            norm_row = {
                'Date': norm_date,
                'NHI number': norm_nhi,
                'Examination Type': norm_exam,
                'Clinical Indications': norm_clin,
                'Role': norm_role,
                'DOB': norm_dob,
                'Sex': norm_sex
            }

            try:
                record = ExamRecord(
                    date=norm_row['Date'],
                    nhi_number=norm_row['NHI number'],
                    examination_type=norm_row['Examination Type'],
                    clinical_indications=norm_row['Clinical Indications'],
                    role=norm_row['Role'],
                    dob=norm_row['DOB'],
                    sex=norm_row['Sex']
                )
            except ValidationError as e:
                error_msg = str(e).replace('\n', ' | ')
                norm_row['Error'] = error_msg
                validation_errors.append(norm_row)
                continue
                
            row_dump = {
                'Date': record.date,
                'NHI number': record.nhi_number,
                'Examination Type': record.examination_type,
                'Clinical Indications': record.clinical_indications,
                'Role': record.role,
                'DOB': record.dob,
                'Sex': record.sex,
                'Age': record.age_at_exam,
                'Observed': record.observed,
                'Performed Assisted': record.performed_assisted,
                'Performed independently': record.performed_independently,
                'Target Page': record.target_page,
                'Target Table': record.target_table
            }

            record_key = (record.nhi_number, record.date, record.examination_type)
            if record_key in existing_records:
                duplicates.append(row_dump)
                continue
                
            categorized_record = categorize_record(record, rules)
            row_dump['Target Page'] = categorized_record.target_page
            row_dump['Target Table'] = categorized_record.target_table

            if not categorized_record.target_page or not categorized_record.target_table:
                uncategorised.append(row_dump)
            else:
                valid_categorized.append(row_dump)

    err_headers = ['Date', 'NHI number', 'Examination Type', 'Clinical Indications', 'Role', 'DOB', 'Sex', 'Age', 'Error']
    save_to_csv(f"{output_dir}/validation_errors.csv", err_headers, validation_errors)
    save_to_csv(f"{output_dir}/duplicates_skipped.csv", out_headers, duplicates)
    save_to_csv(f"{output_dir}/uncategorised-examinations.csv", out_headers, uncategorised)

    return {
        "categorized_count": len(valid_categorized),
        "duplicates": len(duplicates),
        "errors": len(validation_errors),
        "uncategorized": len(uncategorised),
        "valid_data": valid_categorized 
    }