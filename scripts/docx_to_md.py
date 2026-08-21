#!/usr/bin/env python3
"""Convert DOCX files to markdown text. Outputs to stdout.

Requires the python-docx package (``pip install python-docx``).

Limitations:
    - Only extracts paragraph text; tables, headers, and footers are not
      included in the output.
"""
import sys
from docx import Document

def docx_to_text(path):
    doc = Document(path)
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
        else:
            lines.append('')
    return '\n'.join(lines)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 docx_to_md.py <file.docx>", file=sys.stderr)
        sys.exit(1)
    print(docx_to_text(sys.argv[1]))
