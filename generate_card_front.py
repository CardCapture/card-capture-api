#!/usr/bin/env python3
"""
Generate the front side of the Universal Inquiry Card with logo and QR code.
"""

import asyncio
import qrcode
import base64
from io import BytesIO
from playwright.async_api import async_playwright


def generate_qr_code_base64(url: str) -> str:
    """Generate a QR code and return it as a base64 data URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1977FF", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    base64_str = base64.b64encode(buffer.read()).decode('utf-8')
    return f"data:image/png;base64,{base64_str}"


FRONT_CARD_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CardCapture Universal Inquiry Card - Front</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        :root {{
            --primary-blue: #1977FF;
            --primary-dark: #1565D8;
            --text-dark: #1a1a2e;
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

        .card-front {{
            width: 5.5in;
            height: 8in;
            background: var(--background);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 0.5in;
        }}

        .logo-section {{
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-bottom: 48px;
        }}

        .logo {{
            width: 120px;
            height: 120px;
            margin-bottom: 20px;
        }}

        .brand-name {{
            font-size: 36px;
            font-weight: 700;
            color: var(--text-dark);
            letter-spacing: -0.5px;
        }}

        .tagline {{
            font-size: 16px;
            font-weight: 500;
            color: var(--primary-blue);
            margin-top: 8px;
            letter-spacing: 0.5px;
        }}

        .qr-section {{
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-top: 24px;
        }}

        .qr-code {{
            width: 160px;
            height: 160px;
            padding: 8px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(25, 119, 255, 0.15);
        }}

        .qr-label {{
            font-size: 13px;
            font-weight: 600;
            color: var(--primary-blue);
            margin-top: 16px;
            text-align: center;
        }}

        .qr-url {{
            font-size: 11px;
            font-weight: 500;
            color: var(--text-dark);
            margin-top: 4px;
            opacity: 0.7;
        }}

        .footer {{
            position: absolute;
            bottom: 0.4in;
            font-size: 10px;
            color: var(--text-dark);
            opacity: 0.5;
        }}
    </style>
</head>
<body>
    <div class="card-front">
        <div class="logo-section">
            <svg class="logo" viewBox="0 0 305 299" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="69.8398" y="1.11149" width="235.415" height="233.903" rx="23" transform="rotate(6.8082 69.8398 1.11149)" fill="#1977FF" stroke="#1565D8" stroke-width="2"/>
                <rect x="2.01948" y="50.5031" width="248.498" height="246.091" rx="22.5" transform="rotate(0.120216 2.01948 50.5031)" fill="#1977FF" stroke="#1565D8" stroke-width="3"/>
                <path d="M39.5 177.25C39.5 168.75 40.8 161.2 43.4 154.6C46.1 148 49.75 142.45 54.35 137.95C58.95 133.35 64.25 129.85 70.25 127.45C76.25 125.05 82.6 123.85 89.3 123.85C95.7 123.85 101.6 124.85 107 126.85C112.5 128.75 117.7 131.6 122.6 135.4L110.45 151.45C107.35 149.05 104 147.15 100.4 145.75C96.8 144.25 92.95 143.5 88.85 143.5C83.65 143.5 78.9 144.75 74.6 147.25C70.4 149.75 67.05 153.55 64.55 158.65C62.05 163.65 60.8 169.85 60.8 177.25C60.8 184.65 62.05 190.9 64.55 196C67.05 201 70.45 204.75 74.75 207.25C79.05 209.75 83.8 211 89 211C93.3 211 97.25 210.25 100.85 208.75C104.55 207.15 107.95 204.95 111.05 202.15L123.5 217.9C118.6 222.1 113.4 225.3 107.9 227.5C102.4 229.6 96.3 230.65 89.6 230.65C82.8 230.65 76.35 229.45 70.25 227.05C64.25 224.65 58.95 221.2 54.35 216.7C49.75 212.1 46.1 206.5 43.4 199.9C40.8 193.3 39.5 185.75 39.5 177.25Z" fill="white"/>
                <path d="M130.5 176.25C130.5 167.75 131.8 160.2 134.4 153.6C137.1 147 140.75 141.45 145.35 136.95C149.95 132.35 155.25 128.85 161.25 126.45C167.25 124.05 173.6 122.85 180.3 122.85C186.7 122.85 192.6 123.85 198 125.85C203.5 127.75 208.7 130.6 213.6 134.4L201.45 150.45C198.35 148.05 195 146.15 191.4 144.75C187.8 143.25 183.95 142.5 179.85 142.5C174.65 142.5 169.9 143.75 165.6 146.25C161.4 148.75 158.05 152.55 155.55 157.65C153.05 162.65 151.8 168.85 151.8 176.25C151.8 183.65 153.05 189.9 155.55 195C158.05 200 161.45 203.75 165.75 206.25C170.05 208.75 174.8 210 180 210C184.3 210 188.25 209.25 191.85 207.75C195.55 206.15 198.95 203.95 202.05 201.15L214.5 216.9C209.6 221.1 204.4 224.3 198.9 226.5C193.4 228.6 187.3 229.65 180.6 229.65C173.8 229.65 167.35 228.45 161.25 226.05C155.25 223.65 149.95 220.2 145.35 215.7C140.75 211.1 137.1 205.5 134.4 198.9C131.8 192.3 130.5 184.75 130.5 176.25Z" fill="white"/>
            </svg>
            <div class="brand-name">CardCapture</div>
            <div class="tagline">Universal Inquiry Card</div>
        </div>

        <div class="qr-section">
            <img class="qr-code" src="{qr_code}" alt="QR Code" />
            <div class="qr-label">Scan to Create Your Profile</div>
            <div class="qr-url">cardcapture.io/register</div>
        </div>
    </div>
</body>
</html>'''


async def generate_front_pdf(output_path: str = "cc_universal_inquiry_card_front.pdf"):
    """Generate the front side PDF."""

    # Generate QR code
    print("Generating QR code...")
    qr_base64 = generate_qr_code_base64("https://cardcapture.io/register")

    # Create HTML with QR code
    html_content = FRONT_CARD_TEMPLATE.format(qr_code=qr_base64)

    # Generate PDF
    print("Generating PDF...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        await page.set_content(html_content)
        await page.wait_for_load_state("networkidle")

        await page.pdf(
            path=output_path,
            width="5.5in",
            height="8in",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
            prefer_css_page_size=True
        )

        await browser.close()

    print(f"Front card PDF saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    asyncio.run(generate_front_pdf())
