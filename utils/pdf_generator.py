import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_pdf(student_info, marks_list, qr_image_buffer=None):
    """
    Generates a PDF scorecard for a student and returns it as a bytes buffer.
    Optionally embeds a QR code image for verification if qr_image_buffer is provided.
    Displays SGPA and CGPA if present in student_info.
    """
    buffer = io.BytesIO()
    
    # Page setup
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    college_style = ParagraphStyle(
        'CollegeName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        alignment=1, # Center
        textColor=colors.HexColor('#4e54c8')
    )
    
    sub_college_style = ParagraphStyle(
        'CollegeSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=1, # Center
        textColor=colors.HexColor('#666666')
    )
    
    title_style = ParagraphStyle(
        'ScorecardTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        alignment=1, # Center
        textColor=colors.HexColor('#333333'),
        spaceAfter=15
    )
    
    label_style = ParagraphStyle(
        'InfoLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#333333')
    )
    
    value_style = ParagraphStyle(
        'InfoValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#555555')
    )
    
    th_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.white,
        alignment=0
    )
    
    td_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#333333')
    )
    
    footer_style = ParagraphStyle(
        'FooterText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#666666')
    )
    
    # 1. College Header
    story.append(Paragraph("Raje Ramrao Mahavidyalay, Jath", college_style))
    story.append(Paragraph("Approved by AICTE | Affiliated to Shivaji University<br/>Jath, Maharashtra – 416402", sub_college_style))
    story.append(Spacer(1, 10))
    
    # Line separator
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#dddddd'), spaceAfter=15))
    
    # 2. Title
    story.append(Paragraph("STUDENT RESULT SCORECARD", title_style))
    
    # 3. Student Details Table
    details_data = [
        [
            Paragraph("Roll No:", label_style), Paragraph(str(student_info['roll_no']), value_style),
            Paragraph("Course:", label_style), Paragraph(student_info['course'], value_style)
        ],
        [
            Paragraph("Name:", label_style), Paragraph(student_info['name'], value_style),
            Paragraph("Semester:", label_style), Paragraph(str(student_info['semester']), value_style)
        ]
    ]
    
    details_table = Table(details_data, colWidths=[80, 180, 80, 180])
    details_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 15))
    
    # 4. Marks Table
    marks_data = [[Paragraph("Subject Name", th_style), Paragraph("Marks Obtained", th_style)]]
    total_marks = 0
    
    for item in marks_list:
        sub_name = item['subject_name']
        marks_val = item['marks']
        total_marks += marks_val
        marks_data.append([
            Paragraph(sub_name, td_style),
            Paragraph(str(marks_val), td_style)
        ])
        
    marks_table = Table(marks_data, colWidths=[350, 170])
    marks_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4e54c8')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
    ]))
    story.append(marks_table)
    story.append(Spacer(1, 20))
    
    # 5. Summary Section
    num_subjects = len(marks_list)
    max_marks = num_subjects * 100
    percentage = (total_marks / max_marks * 100) if max_marks > 0 else 0
    
    if percentage >= 75:
        grade = "A"
    elif percentage >= 60:
        grade = "B"
    elif percentage >= 50:
        grade = "C"
    else:
        grade = "F"
        
    status = "PASS" if percentage >= 50 else "FAIL"
    status_color = colors.HexColor('#2e7d32') if status == 'PASS' else colors.HexColor('#c62828')
    
    status_style = ParagraphStyle(
        'StatusStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=status_color
    )
    
    summary_data = [
        [Paragraph("Total Marks:", label_style), Paragraph(f"{total_marks} / {max_marks}", value_style)],
        [Paragraph("Percentage:", label_style), Paragraph(f"{percentage:.2f}%", value_style)],
        [Paragraph("Grade:", label_style), Paragraph(grade, value_style)],
        [Paragraph("Status:", label_style), Paragraph(status, status_style)],
    ]
    
    # Add SGPA and CGPA rows if available in student_info
    sgpa = student_info.get('sgpa')
    cgpa = student_info.get('cgpa')
    if sgpa is not None:
        summary_data.append([Paragraph("SGPA:", label_style), Paragraph(f"{sgpa:.2f}", value_style)])
    if cgpa is not None:
        summary_data.append([Paragraph("CGPA:", label_style), Paragraph(f"{cgpa:.2f}", value_style)])
    
    summary_table = Table(summary_data, colWidths=[120, 400])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 30))
    
    # 6. QR Code Verification Block (if provided)
    if qr_image_buffer:
        try:
            qr_image_buffer.seek(0)
            qr_reader = ImageReader(qr_image_buffer)
            qr_img = Image(qr_reader, width=25*mm, height=25*mm)

            verify_label_style = ParagraphStyle(
                'VerifyLabel',
                parent=styles['Normal'],
                fontName='Helvetica',
                fontSize=8,
                leading=10,
                textColor=colors.HexColor('#888888'),
                alignment=0
            )

            qr_table_data = [[
                qr_img,
                Paragraph(
                    "Scan QR code to verify<br/>the authenticity of this<br/>scorecard online.",
                    verify_label_style
                )
            ]]

            qr_table = Table(qr_table_data, colWidths=[30*mm, 80*mm])
            qr_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (1, 0), (1, 0), 10),
            ]))
            story.append(qr_table)
            story.append(Spacer(1, 15))
        except Exception as e:
            # If QR embedding fails, continue without it
            print(f"Warning: Could not embed QR code in PDF: {e}")
    
    # 7. Footer (Date and Signatures)
    current_date = datetime.now().strftime("%d-%m-%Y")
    
    footer_data = [
        [
            Paragraph(f"Date: {current_date}", footer_style),
            Paragraph("Controller of Examinations<br/>(Signature)", ParagraphStyle('SignStyle', parent=footer_style, alignment=2))
        ]
    ]
    
    footer_table = Table(footer_data, colWidths=[260, 260])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(footer_table)
    
    # Build Document
    doc.build(story)
    
    buffer.seek(0)
    return buffer
