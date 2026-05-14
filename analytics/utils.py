import pandas as pd
import json
from io import StringIO
from .models import Student, Subject, Result, SemesterResult, Backlog, NBAMetric


# ── Grade calculation (VTU scheme) ──────────────────────────────────────────
GRADE_SCALE = [
    (90, 'O',  10),
    (85, 'A+',  9),
    (80, 'A',   8),
    (75, 'B+',  7),
    (70, 'B',   6),
    (60, 'C',   5),
    (50, 'D',   4),
    (40, 'P',   4),   # Pass with less marks
    (0,  'F',   0),
]

def get_grade(total_marks):
    """Return (grade_letter, grade_point) based on total marks."""
    try:
        marks = float(total_marks)
    except (TypeError, ValueError):
        return ('F', 0)
    for threshold, grade, gp in GRADE_SCALE:
        if marks >= threshold:
            return (grade, gp)
    return ('F', 0)


def get_pass_fail(total_marks, see_marks=None):
    """
    Pass criteria (VTU):
    - Total >= 40
    - SEE >= 35 (if provided)
    """
    try:
        total = float(total_marks)
    except (TypeError, ValueError):
        return 'F'
    if total < 40:
        return 'F'
    if see_marks is not None:
        try:
            see = float(see_marks)
            if see < 35:
                return 'F'
        except (TypeError, ValueError):
            pass
    return 'P'

REQUIRED_COLUMNS = [
    'USN', 'Name', 'Branch', 'Semester', 'Batch',
    'Subject_Code', 'Subject_Name', 'Credits',
    'CIE', 'SEE', 'Total', 'Grade', 'Grade_Point', 'Pass_Fail'
]

OPTIONAL_COLUMNS = [
    'Section', 'Gender', 'Admission_Quota', 'Admission_Type',
    'Actual_Category', 'Seat_Category_Claimed', 'Seat_Category_Alloted',
    'Domicile_State', 'Domicile_Place', 'CET_Rank', 'Achievements',
    'Academic_Year'
]


def validate_columns(df):
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    return missing


def parse_csv(file_content):
    """
    Parse CSV content, validate, and return:
    {
        'total': int,
        'valid': [...],
        'invalid': [...errors with row numbers...],
        'df': DataFrame or None
    }
    """
    try:
        if isinstance(file_content, bytes):
            file_content = file_content.decode('utf-8', errors='replace')
        df = pd.read_csv(StringIO(file_content))
        df.columns = [c.strip() for c in df.columns]
    except Exception as e:
        return {'total': 0, 'valid': [], 'invalid': [{'row': 0, 'errors': [f'File parse error: {str(e)}']}], 'df': None}

    missing_cols = validate_columns(df)
    if missing_cols:
        return {
            'total': 0, 'valid': [], 'df': None,
            'invalid': [{'row': 0, 'errors': [f'Missing required columns: {", ".join(missing_cols)}']}]
        }

    valid_rows = []
    invalid_rows = []

    for idx, row in df.iterrows():
        row_num = idx + 2  # 1-indexed + header
        errors = []

        # Required field checks
        usn = str(row.get('USN', '')).strip()
        name = str(row.get('Name', '')).strip()
        branch = str(row.get('Branch', '')).strip()
        subject_code = str(row.get('Subject_Code', '')).strip()
        subject_name = str(row.get('Subject_Name', '')).strip()
        pass_fail = str(row.get('Pass_Fail', '')).strip().upper()

        if not usn or usn == 'nan':
            errors.append('USN is required')
        if not name or name == 'nan':
            errors.append('Name is required')
        if not branch or branch == 'nan':
            errors.append('Branch is required')
        if not subject_code or subject_code == 'nan':
            errors.append('Subject_Code is required')
        if not subject_name or subject_name == 'nan':
            errors.append('Subject_Name is required')

        try:
            sem = int(row.get('Semester', 0))
            if sem < 1 or sem > 8:
                errors.append('Semester must be between 1 and 8')
        except (ValueError, TypeError):
            errors.append('Semester must be a valid number')

        try:
            credits = float(row.get('Credits', 0))
            if credits <= 0:
                errors.append('Credits must be > 0')
        except (ValueError, TypeError):
            errors.append('Credits must be a valid number')

        try:
            gp_val = row.get('Grade_Point')
            if pd.notna(gp_val):
                gp = float(gp_val)
                if gp < 0 or gp > 10:
                    errors.append('Grade_Point must be between 0 and 10')
        except (ValueError, TypeError):
            errors.append('Grade_Point must be a valid number')

        if pass_fail not in ['P', 'F', 'A', 'W', 'PASS', 'FAIL', 'ABSENT', 'WITHHELD']:
            errors.append(f'Pass_Fail must be P/F/A/W (got: {pass_fail})')

        if errors:
            invalid_rows.append({'row': row_num, 'errors': errors, 'usn': usn, 'subject': subject_code})
        else:
            valid_rows.append(row.to_dict())

    return {
        'total': len(df),
        'valid': valid_rows,
        'invalid': invalid_rows,
        'df': df
    }


def save_valid_rows(valid_rows):
    saved = 0
    for row in valid_rows:
        try:
            usn = str(row.get('USN', '')).strip()
            branch = str(row.get('Branch', '')).strip()
            batch = str(row.get('Batch', '')).strip()
            semester = int(row.get('Semester', 1))
            credits = float(row.get('Credits', 4))
            academic_year = str(row.get('Academic_Year', '')).strip() if pd.notna(row.get('Academic_Year')) else ''

            cie   = float(row.get('CIE', 0))   if pd.notna(row.get('CIE'))   else None
            see   = float(row.get('SEE', 0))   if pd.notna(row.get('SEE'))   else None
            total = float(row.get('Total', 0)) if pd.notna(row.get('Total')) else None

            # ── Auto-calculate grade / grade_point / pass_fail from Total ──
            if total is not None:
                auto_grade, auto_gp = get_grade(total)
                auto_pf = get_pass_fail(total, see)
            else:
                auto_grade, auto_gp, auto_pf = 'F', 0.0, 'F'

            # Use CSV values if provided; fall back to auto-calculated
            grade_raw = str(row.get('Grade', '')).strip()
            grade = grade_raw if grade_raw and grade_raw.lower() not in ('', 'nan') else auto_grade

            gp_raw = row.get('Grade_Point')
            grade_point = float(gp_raw) if (gp_raw is not None and pd.notna(gp_raw) and str(gp_raw).strip() not in ('', 'nan')) else float(auto_gp)

            pf_raw = str(row.get('Pass_Fail', '')).strip().upper()
            pf_map = {'PASS': 'P', 'FAIL': 'F', 'ABSENT': 'A', 'WITHHELD': 'W', 'P': 'P', 'F': 'F', 'A': 'A', 'W': 'W'}
            pass_fail = pf_map.get(pf_raw, auto_pf) if pf_raw and pf_raw not in ('', 'NAN') else auto_pf

            # Upsert student
            student_defaults = {
                'name': str(row.get('Name', '')).strip(),
                'branch': branch,
                'batch': batch,
            }
            for opt_field, model_field in [
                ('Section', 'section'), ('Gender', 'gender'), ('Admission_Quota', 'admission_quota'),
                ('Admission_Type', 'admission_type'), ('Actual_Category', 'actual_category'),
                ('Seat_Category_Claimed', 'seat_category_claimed'), ('Seat_Category_Alloted', 'seat_category_alloted'),
                ('Domicile_State', 'domicile_state'), ('Domicile_Place', 'domicile_place'),
                ('CET_Rank', 'cet_rank'), ('Achievements', 'achievements')
            ]:
                val = row.get(opt_field)
                if val is not None and str(val).strip() not in ('', 'nan'):
                    student_defaults[model_field] = str(val).strip()

            student, _ = Student.objects.update_or_create(usn=usn, defaults=student_defaults)

            # Upsert subject
            subject_code = str(row.get('Subject_Code', '')).strip()
            subject, _ = Subject.objects.update_or_create(
                code=subject_code,
                defaults={
                    'name': str(row.get('Subject_Name', '')).strip(),
                    'credits': credits,
                    'branch': branch,
                    'semester': semester,
                }
            )

            # Upsert result
            Result.objects.update_or_create(
                student=student, subject=subject, semester=semester,
                academic_year=academic_year or None,
                defaults={
                    'cie_marks': cie, 'see_marks': see, 'total_marks': total,
                    'grade': grade, 'grade_point': grade_point, 'pass_fail': pass_fail,
                }
            )

            # Handle backlog
            if pass_fail == 'F':
                Backlog.objects.update_or_create(
                    student=student, subject=subject, semester=semester,
                    defaults={'academic_year': academic_year or None, 'cleared': False}
                )

            saved += 1
        except Exception:
            continue

    # Recalculate SGPA for all affected students
    recalculate_semester_results()
    return saved


def recalculate_semester_results():
    from django.db.models import Q
    students = Student.objects.prefetch_related('result_set__subject').all()
    for student in students:
        results = Result.objects.filter(student=student).select_related('subject')
        semesters = results.values_list('semester', 'academic_year').distinct()
        for sem, acad_year in semesters:
            sem_results = results.filter(semester=sem, academic_year=acad_year)
            total_credits = sum(r.subject.credits for r in sem_results if r.subject.credits)
            earned_credits = sum(r.subject.credits for r in sem_results if r.pass_fail == 'P' and r.subject.credits)
            weighted_gp = sum((r.grade_point or 0) * r.subject.credits for r in sem_results if r.subject.credits)
            sgpa = round(weighted_gp / total_credits, 2) if total_credits else 0.0
            has_fail = sem_results.filter(pass_fail='F').exists()
            SemesterResult.objects.update_or_create(
                student=student, semester=sem, academic_year=acad_year,
                defaults={
                    'sgpa': sgpa, 'total_credits': total_credits,
                    'credits_earned': earned_credits, 'pass_fail': 'F' if has_fail else 'P'
                }
            )


def calculate_si(pass_count, total_students):
    """Success Index = (Pass / Total) * 100"""
    if total_students == 0:
        return 0.0
    return round((pass_count / total_students) * 100, 2)


def calculate_api(avg_sgpa, total_students, pass_count):
    """Academic Performance Index = SI * avg_SGPA / 10"""
    si = calculate_si(pass_count, total_students)
    return round((si * avg_sgpa) / 10, 2) if avg_sgpa else 0.0


def compute_nba_metrics():
    from django.db.models import Avg, Count, Q
    branches = Student.objects.values_list('branch', flat=True).distinct()
    for branch in branches:
        sem_results = SemesterResult.objects.filter(student__branch=branch)
        semesters_years = sem_results.values_list('semester', 'academic_year').distinct()
        for sem, acad_year in semesters_years:
            sr = sem_results.filter(semester=sem, academic_year=acad_year)
            total = sr.count()
            passes = sr.filter(pass_fail='P').count()
            avg_sgpa_val = sr.aggregate(a=Avg('sgpa'))['a'] or 0.0
            si = calculate_si(passes, total)
            api = calculate_api(avg_sgpa_val, total, passes)
            NBAMetric.objects.update_or_create(
                branch=branch, semester=sem, academic_year=acad_year or '',
                defaults={
                    'total_students': total, 'pass_count': passes,
                    'avg_sgpa': round(avg_sgpa_val, 2),
                    'success_index': si, 'academic_performance_index': api
                }
            )


def get_sample_csv_content():
    return """USN,Name,Branch,Semester,Batch,Section,Gender,Admission_Quota,Admission_Type,Actual_Category,Seat_Category_Claimed,Seat_Category_Alloted,Domicile_State,Domicile_Place,CET_Rank,Achievements,Subject_Code,Subject_Name,Credits,CIE,SEE,Total,Grade,Grade_Point,Pass_Fail,Academic_Year
1RV21CS001,Aditya Kumar,Computer Science,3,2021-25,A,M,GOV,REGULAR,GM,GM,GM,Karnataka,Bangalore,12345,,21CS31,Data Structures and Algorithms,4,38,52,90,O,10,P,2022-23
1RV21CS001,Aditya Kumar,Computer Science,3,2021-25,A,M,GOV,REGULAR,GM,GM,GM,Karnataka,Bangalore,12345,,21CS32,Design and Analysis of Algorithms,3,35,48,83,A,9,P,2022-23
1RV21CS001,Aditya Kumar,Computer Science,3,2021-25,A,M,GOV,REGULAR,GM,GM,GM,Karnataka,Bangalore,12345,,21CS33,Computer Organization,3,30,42,72,B,8,P,2022-23
1RV21CS002,Priya Sharma,Computer Science,3,2021-25,A,F,GOV,REGULAR,SC,SC,SC,Karnataka,Mysore,45678,Best Outgoing Student 2022,21CS31,Data Structures and Algorithms,4,40,55,95,O,10,P,2022-23
1RV21CS002,Priya Sharma,Computer Science,3,2021-25,A,F,GOV,REGULAR,SC,SC,SC,Karnataka,Mysore,45678,Best Outgoing Student 2022,21CS32,Design and Analysis of Algorithms,3,28,35,63,C,7,P,2022-23
1RV21EC001,Rahul Verma,Electronics,3,2021-25,B,M,MGMT,REGULAR,GM,GM,GM,Karnataka,Hubli,23456,,21EC31,Analog Circuits,4,25,30,55,D,6,P,2022-23
1RV21EC001,Rahul Verma,Electronics,3,2021-25,B,M,MGMT,REGULAR,GM,GM,GM,Karnataka,Hubli,23456,,21EC32,Signals and Systems,3,20,25,45,F,0,F,2022-23
1RV21ME001,Sneha Patel,Mechanical,3,2021-25,A,F,GOV,LATERAL,OBC,OBC,OBC,Maharashtra,Pune,34567,Sports Captain,21ME31,Fluid Mechanics,4,35,45,80,A,9,P,2022-23
1RV21ME001,Sneha Patel,Mechanical,3,2021-25,A,F,GOV,LATERAL,OBC,OBC,OBC,Maharashtra,Pune,34567,Sports Captain,21ME32,Thermodynamics,3,32,40,72,B,8,P,2022-23
"""
