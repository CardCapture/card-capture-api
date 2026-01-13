#!/usr/bin/env python3
"""
Generate print-ready Universal Inquiry Card PDFs with sequential serial numbers.

Usage:
    python generate_inquiry_cards_pdf.py                    # Single card (0000001)
    python generate_inquiry_cards_pdf.py --count 100        # 100 cards (0000001-0000100)
    python generate_inquiry_cards_pdf.py --start 500 --count 50  # 50 cards starting at 0000500
"""

import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

# Card HTML template
CARD_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CardCapture Universal Inquiry Card</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        :root {{
            --primary-blue: #1977FF;
            --primary-dark: #1565D8;
            --text-dark: #1a1a2e;
            --text-muted: #64748b;
            --border-color: #cbd5e1;
            --background: #ffffff;
        }}

        @page {{
            size: 5.5in 8in;
            margin: 0;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--background);
        }}

        .card {{
            width: 5.5in;
            height: 8in;
            background: var(--background);
            padding: 0.4in 0.45in 0.35in 0.45in;
            page-break-after: always;
            page-break-inside: avoid;
        }}

        .card:last-child {{
            page-break-after: auto;
        }}

        /* Header */
        .header {{
            text-align: center;
            margin-bottom: 24px;
        }}

        .logo-container {{
            display: flex;
            justify-content: center;
            margin-bottom: 6px;
        }}

        .logo {{
            width: 48px;
            height: 48px;
        }}

        .brand-name {{
            font-size: 16px;
            font-weight: 600;
            color: var(--text-dark);
            margin-bottom: 2px;
            letter-spacing: -0.3px;
        }}

        .card-title {{
            font-size: 18px;
            font-weight: 700;
            color: var(--primary-blue);
            letter-spacing: -0.3px;
        }}

        /* Form Fields */
        .form-section {{
            margin-bottom: 14px;
        }}

        .field-row {{
            display: flex;
            gap: 14px;
            margin-bottom: 14px;
        }}

        .field {{
            flex: 1;
        }}

        .field.small {{
            flex: 0.6;
        }}

        .field.xsmall {{
            flex: 0.4;
        }}

        .field.large {{
            flex: 1.4;
        }}

        .field-input {{
            width: 100%;
            border: none;
            border-bottom: 1.5px solid var(--border-color);
            padding: 6px 0 5px 0;
            font-size: 13px;
            min-height: 28px;
            background: transparent;
        }}

        .field-label {{
            font-size: 10px;
            font-weight: 600;
            color: var(--primary-blue);
            text-transform: uppercase;
            letter-spacing: 0.3px;
            margin-top: 3px;
        }}

        .format-hint {{
            display: block;
            font-weight: 500;
            text-transform: none;
            color: var(--primary-blue);
            font-size: 8px;
            opacity: 0.7;
            margin-top: 1px;
        }}

        /* Checkbox Section */
        .checkbox-section {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            margin: 18px 0;
            padding: 10px 0;
        }}

        .checkbox-label {{
            font-size: 12px;
            font-weight: 600;
            color: var(--primary-blue);
        }}

        .checkbox-options {{
            display: flex;
            gap: 16px;
        }}

        .checkbox-option {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}

        .checkbox {{
            width: 16px;
            height: 16px;
            border: 2px solid var(--primary-blue);
            border-radius: 3px;
            display: inline-block;
        }}

        .checkbox-text {{
            font-size: 12px;
            font-weight: 600;
            color: var(--primary-blue);
        }}

        /* Card ID */
        .card-id {{
            text-align: center;
            margin-top: 20px;
            padding-top: 14px;
            border-top: 1px solid #e2e8f0;
        }}

        .card-id-label {{
            font-size: 14px;
            font-weight: 700;
            color: var(--primary-blue);
            letter-spacing: 0.5px;
        }}

        .serial-number {{
            font-family: 'Courier New', monospace;
            font-size: 16px;
            font-weight: 700;
            letter-spacing: 2px;
        }}
    </style>
</head>
<body>
{cards}
</body>
</html>'''

SINGLE_CARD = '''    <div class="card">
        <!-- Header with Logo -->
        <div class="header">
            <div class="logo-container">
                <svg class="logo" viewBox="0 0 305 299" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="69.8398" y="1.11149" width="235.415" height="233.903" rx="23" transform="rotate(6.8082 69.8398 1.11149)" fill="#1977FF" stroke="#1565D8" stroke-width="2"/>
                    <rect x="2.01948" y="50.5031" width="248.498" height="246.091" rx="22.5" transform="rotate(0.120216 2.01948 50.5031)" fill="#1977FF" stroke="#1565D8" stroke-width="3"/>
                    <path d="M39.5 177.25C39.5 168.75 40.8 161.2 43.4 154.6C46.1 148 49.75 142.45 54.35 137.95C58.95 133.35 64.25 129.85 70.25 127.45C76.25 125.05 82.6 123.85 89.3 123.85C95.7 123.85 101.6 124.85 107 126.85C112.5 128.75 117.7 131.6 122.6 135.4L110.45 151.45C107.35 149.05 104 147.15 100.4 145.75C96.8 144.25 92.95 143.5 88.85 143.5C83.65 143.5 78.9 144.75 74.6 147.25C70.4 149.75 67.05 153.55 64.55 158.65C62.05 163.65 60.8 169.85 60.8 177.25C60.8 184.65 62.05 190.9 64.55 196C67.05 201 70.45 204.75 74.75 207.25C79.05 209.75 83.8 211 89 211C93.3 211 97.25 210.25 100.85 208.75C104.55 207.15 107.95 204.95 111.05 202.15L123.5 217.9C118.6 222.1 113.4 225.3 107.9 227.5C102.4 229.6 96.3 230.65 89.6 230.65C82.8 230.65 76.35 229.45 70.25 227.05C64.25 224.65 58.95 221.2 54.35 216.7C49.75 212.1 46.1 206.5 43.4 199.9C40.8 193.3 39.5 185.75 39.5 177.25Z" fill="white"/>
                    <path d="M130.5 176.25C130.5 167.75 131.8 160.2 134.4 153.6C137.1 147 140.75 141.45 145.35 136.95C149.95 132.35 155.25 128.85 161.25 126.45C167.25 124.05 173.6 122.85 180.3 122.85C186.7 122.85 192.6 123.85 198 125.85C203.5 127.75 208.7 130.6 213.6 134.4L201.45 150.45C198.35 148.05 195 146.15 191.4 144.75C187.8 143.25 183.95 142.5 179.85 142.5C174.65 142.5 169.9 143.75 165.6 146.25C161.4 148.75 158.05 152.55 155.55 157.65C153.05 162.65 151.8 168.85 151.8 176.25C151.8 183.65 153.05 189.9 155.55 195C158.05 200 161.45 203.75 165.75 206.25C170.05 208.75 174.8 210 180 210C184.3 210 188.25 209.25 191.85 207.75C195.55 206.15 198.95 203.95 202.05 201.15L214.5 216.9C209.6 221.1 204.4 224.3 198.9 226.5C193.4 228.6 187.3 229.65 180.6 229.65C173.8 229.65 167.35 228.45 161.25 226.05C155.25 223.65 149.95 220.2 145.35 215.7C140.75 211.1 137.1 205.5 134.4 198.9C131.8 192.3 130.5 184.75 130.5 176.25Z" fill="white"/>
                </svg>
            </div>
            <div class="brand-name">CardCapture</div>
            <div class="card-title">Universal Inquiry Card</div>
        </div>

        <!-- Name Fields -->
        <div class="form-section">
            <div class="field-row">
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">First Name</div>
                </div>
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">Last Name</div>
                </div>
                <div class="field small">
                    <div class="field-input"></div>
                    <div class="field-label">Preferred Name</div>
                </div>
            </div>
        </div>

        <!-- Address -->
        <div class="form-section">
            <div class="field-row">
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">Address</div>
                </div>
            </div>
            <div class="field-row">
                <div class="field large">
                    <div class="field-input"></div>
                    <div class="field-label">City</div>
                </div>
                <div class="field small">
                    <div class="field-input"></div>
                    <div class="field-label">State</div>
                </div>
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">Zip Code</div>
                </div>
            </div>
        </div>

        <!-- Email -->
        <div class="form-section">
            <div class="field-row">
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">Email Address</div>
                </div>
            </div>
        </div>

        <!-- Phone, DOB, Grad Year -->
        <div class="form-section">
            <div class="field-row">
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">Cell Phone</div>
                </div>
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">Date of Birth<span class="format-hint">ex: 01/15/2008</span></div>
                </div>
                <div class="field small">
                    <div class="field-input"></div>
                    <div class="field-label">Grad Year<span class="format-hint">ex: 2026</span></div>
                </div>
            </div>
        </div>

        <!-- High School -->
        <div class="form-section">
            <div class="field-row">
                <div class="field">
                    <div class="field-input"></div>
                    <div class="field-label">High School</div>
                </div>
            </div>
        </div>

        <!-- Major & Academic Stats -->
        <div class="form-section">
            <div class="field-row">
                <div class="field large">
                    <div class="field-input"></div>
                    <div class="field-label">Potential Major</div>
                </div>
                <div class="field xsmall">
                    <div class="field-input"></div>
                    <div class="field-label">GPA</div>
                </div>
                <div class="field xsmall">
                    <div class="field-input"></div>
                    <div class="field-label">SAT</div>
                </div>
                <div class="field xsmall">
                    <div class="field-input"></div>
                    <div class="field-label">ACT</div>
                </div>
            </div>
        </div>

        <!-- Text Permission -->
        <div class="checkbox-section">
            <span class="checkbox-label">May schools text you?</span>
            <div class="checkbox-options">
                <div class="checkbox-option">
                    <span class="checkbox"></span>
                    <span class="checkbox-text">Yes</span>
                </div>
                <div class="checkbox-option">
                    <span class="checkbox"></span>
                    <span class="checkbox-text">No</span>
                </div>
            </div>
        </div>

        <!-- Card ID -->
        <div class="card-id">
            <div class="card-id-label">Card ID - <span class="serial-number">{serial}</span></div>
        </div>
    </div>'''


async def generate_pdf(start_number: int = 1, count: int = 1, output_path: str = None):
    """Generate a PDF with the specified number of cards."""

    # Generate all card HTML
    cards_html = []
    for i in range(count):
        serial = f"{start_number + i:07d}"
        cards_html.append(SINGLE_CARD.format(serial=serial))

    # Combine into full HTML
    full_html = CARD_TEMPLATE.format(cards="\n".join(cards_html))

    # Determine output filename
    if output_path is None:
        if count == 1:
            output_path = f"universal_inquiry_card_{start_number:07d}.pdf"
        else:
            end_number = start_number + count - 1
            output_path = f"universal_inquiry_cards_{start_number:07d}-{end_number:07d}.pdf"

    # Generate PDF using Playwright
    print(f"Generating {count} card(s)...")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Set content and wait for fonts to load
        await page.set_content(full_html)
        await page.wait_for_load_state("networkidle")

        # Generate PDF with print settings
        await page.pdf(
            path=output_path,
            width="5.5in",
            height="8in",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
            prefer_css_page_size=True
        )

        await browser.close()

    print(f"PDF saved to: {output_path}")
    print(f"Serial numbers: {start_number:07d}" + (f" - {start_number + count - 1:07d}" if count > 1 else ""))
    print(f"Card size: 5.5\" x 8\" (half letter)")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate print-ready Universal Inquiry Card PDFs")
    parser.add_argument("--start", type=int, default=1, help="Starting serial number (default: 1)")
    parser.add_argument("--count", type=int, default=1, help="Number of cards to generate (default: 1)")
    parser.add_argument("--output", type=str, help="Output PDF filename")

    args = parser.parse_args()

    asyncio.run(generate_pdf(start_number=args.start, count=args.count, output_path=args.output))


if __name__ == "__main__":
    main()
