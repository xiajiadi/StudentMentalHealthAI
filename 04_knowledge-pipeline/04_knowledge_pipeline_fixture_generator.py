"""Generate tiny public/synthetic PDF and DOCX fixtures for local evidence."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parent


def make_pdf(path: Path) -> None:
    font_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if font_path.is_file():
        pdfmetrics.registerFont(TTFont("SyntheticChinese", str(font_path)))
        font = "SyntheticChinese"
    else:
        font = "Helvetica"
    canvas = Canvas(str(path), pagesize=A4)
    canvas.setFont(font, 16)
    canvas.drawString(72, 770, "学校支持流程（PDF合成夹具）")
    canvas.setFont(font, 12)
    canvas.drawString(72, 730, "第一章 总则")
    canvas.drawString(72, 700, "第十二条 学校应提供尊重、非评判性的支持环境。")
    canvas.drawString(72, 670, "第十三条 教师应按照审核流程记录支持性沟通。")
    canvas.drawString(72, 620, "表1 资料状态")
    canvas.drawString(72, 590, "状态        含义")
    canvas.drawString(72, 565, "approved     可进入后续审核流程")
    canvas.save()


def make_docx(path: Path) -> None:
    document = Document()
    document.add_heading("学校支持流程（DOCX合成夹具）", level=1)
    document.add_heading("第一章 总则", level=2)
    document.add_paragraph("第十二条 学校应提供尊重、非评判性的支持环境。")
    document.add_heading("第二章 工作要求", level=2)
    document.add_paragraph("第十三条 教师应按照审核流程记录支持性沟通。")
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "状态"
    table.rows[0].cells[1].text = "含义"
    row = table.add_row().cells
    row[0].text = "approved"
    row[1].text = "可进入后续审核流程"
    document.save(path)


if __name__ == "__main__":
    make_pdf(ROOT / "fixtures" / "policy" / "docling_sample.pdf")
    make_docx(ROOT / "fixtures" / "policy" / "docling_sample.docx")
