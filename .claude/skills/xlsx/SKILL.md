---
name: xlsx
description: "Comprehensive spreadsheet creation, editing, and analysis with support for formulas, formatting, data analysis, and visualization. When Claude needs to work with spreadsheets (.xlsx, .xlsm, .csv, .tsv, etc) for: (1) Creating new spreadsheets with formulas and formatting, (2) Reading or analyzing data, (3) Modify existing spreadsheets while preserving formulas, (4) Data analysis and visualization in spreadsheets, or (5) Recalculating formulas"
license: Proprietary - from Anthropic skills repo
---

## Requirements for Outputs

### All Excel files

**Zero Formula Errors**: Every Excel model must be delivered without formula errors (#REF!, #DIV/0!, #VALUE!, #N/A, #NAME?)

**Preserve Existing Templates**: When updating templates, match existing format, style, and conventions exactly. Never impose standardized formatting on files with established patterns.

### Financial models

**Color Coding Standards** (unless otherwise specified):
- Blue text (RGB: 0,0,255): Hardcoded inputs and user-changeable numbers
- Black text (RGB: 0,0,0): All formulas and calculations
- Green text (RGB: 0,128,0): Links from other worksheets
- Red text (RGB: 255,0,0): External file links
- Yellow background (RGB: 255,255,0): Key assumptions or cells needing updates

**Number Formatting Standards**:
- Years: Format as text strings ("2024" not "2,024")
- Currency: Use $#,##0 format with units in headers
- Zeros: Display as "-" using number formatting
- Percentages: Default 0.0% format
- Multiples: Format as 0.0x for valuation ratios
- Negative numbers: Use parentheses (123) not minus signs

**Formula Construction Rules**:
- Place all assumptions in separate cells
- Use cell references instead of hardcoded values
- Verify all references are correct
- Check for off-by-one errors
- Ensure consistent formulas across projection periods
- Test with edge cases
- Document hardcodes with sources and dates

## XLSX creation, editing, and analysis

### Overview
Users may request spreadsheet creation, editing, or analysis. Different tools serve different purposes.

### Reading and analyzing data

Use pandas for data analysis and basic operations:
```python
import pandas as pd
df = pd.read_excel('file.xlsx')
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)
```

## Critical: Use Formulas, Not Hardcoded Values

Always use Excel formulas instead of calculating in Python and hardcoding results. The spreadsheet must remain dynamic and updateable.

- WRONG: Calculating in Python and hardcoding
- CORRECT: Using Excel formulas like =SUM(B2:B9), =(C4-C2)/C2, =AVERAGE(D2:D19)

### Creating new Excel files

Use openpyxl for formulas and formatting:
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

wb = Workbook()
sheet = wb.active
sheet['A1'] = 'Hello'
sheet['B2'] = '=SUM(A1:A10)'
sheet['A1'].font = Font(bold=True, color='FF0000')
wb.save('output.xlsx')
```

### Editing existing Excel files

```python
from openpyxl import load_workbook

wb = load_workbook('existing.xlsx')
sheet = wb.active
sheet['A1'] = 'New Value'
sheet.insert_rows(2)
wb.save('modified.xlsx')
```

## Formula Verification Checklist

- Test 2-3 sample references before building full model
- Confirm Excel column mapping
- Remember Excel rows are 1-indexed
- Check for NaN values
- Verify no division by zero
- Validate all cell references
- Use correct format for cross-sheet references (Sheet1!A1)
- Test formulas on 2-3 cells before applying broadly
- Include zero, negative, and large values in testing

## Best Practices

**Library Selection**:
- pandas: Data analysis, bulk operations, simple export
- openpyxl: Complex formatting, formulas, Excel-specific features

**Working with openpyxl**:
- Cell indices are 1-based
- Use `data_only=True` to read calculated values only
- Warning: Saving with `data_only=True` replaces formulas permanently
- Formulas preserved but not evaluated

**Working with pandas**:
- Specify data types to avoid inference issues
- Read specific columns for large files
- Handle dates properly with `parse_dates`

## Code Style Guidelines

- Write minimal, concise Python code without unnecessary comments
- Avoid verbose variable names
- Avoid unnecessary print statements
- Add comments to cells with complex formulas
- Document data sources for hardcoded values
- Include notes for key calculations
