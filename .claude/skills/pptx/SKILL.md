---
name: pptx
description: "PowerPoint presentation creation, editing, and analysis. Use when Claude needs to: (1) Create new presentations from scratch, (2) Edit existing PowerPoint files, (3) Analyze presentation content, or (4) Convert content to slide format"
license: Proprietary - from Anthropic skills repo
---

## Overview

This skill enables working with PowerPoint presentations (.pptx files) for creation, modification, and analysis tasks.

## Three Main Workflows

### 1. Reading & Analyzing Content
- Text extraction via markdown conversion
- Raw XML access for comments, speaker notes, layouts, and animations
- Unpack presentations to access internal structure

### 2. Creating New Presentations

**From scratch using python-pptx**:
```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RgbColor
from pptx.enum.text import PP_ALIGN

prs = Presentation()
prs.slide_width = Inches(13.333)  # 16:9 aspect ratio
prs.slide_height = Inches(7.5)

# Add title slide
title_layout = prs.slide_layouts[0]
slide = prs.slides.add_slide(title_layout)
title = slide.shapes.title
title.text = "Presentation Title"

prs.save('output.pptx')
```

**Using templates**:
- Extract template structure
- Analyze available layouts
- Duplicate/reorder slides
- Replace placeholder content

### 3. Editing Existing Presentations

Use Office Open XML (OOXML) format:
- Unpack .pptx files (they're ZIP archives)
- Edit XML content directly
- Validate changes
- Repack into .pptx

## Key Requirements

**Design Choices**:
- State design approach before writing code
- Use web-safe fonts only: Arial, Helvetica, Times New Roman, Georgia, Courier New, Verdana, Tahoma, Trebuchet MS, Impact
- For charts/tables, prefer two-column layouts over vertical stacking

**Validation**:
- Validate presentations immediately after edits
- Check all placeholder content was replaced
- Verify formatting is consistent

## Color Palettes for Financial Presentations

**Professional Blue**:
- Primary: #003366 (Dark Blue)
- Secondary: #0066CC (Medium Blue)
- Accent: #66B2FF (Light Blue)
- Background: #F0F5FF (Very Light Blue)

**Conservative Gray**:
- Primary: #333333 (Dark Gray)
- Secondary: #666666 (Medium Gray)
- Accent: #007ACC (Blue accent)
- Background: #F5F5F5 (Light Gray)

## Slide Layout Best Practices

**Title Slide**:
- Company name/logo
- Presentation title
- Date and presenter

**Section Headers**:
- Clean, minimal design
- Section title only

**Content Slides**:
- Maximum 6 bullet points
- Use visuals where possible
- Consistent margins (0.5" minimum)

**Chart/Table Slides**:
- One main visual per slide
- Clear titles and labels
- Source citations at bottom

## Dependencies
- python-pptx
- pillow (for image handling)
- openpyxl (for embedded charts)
