import mailbox
import email
import json
import re
from email.utils import parsedate_to_datetime
from email.header import decode_header
import html2text

# CONFIGURATION
PERSONAL_EMAILS = {
    'emigodoy03@gmail.com',
    'milogs0320@gmail.com'
}

PERSONAL_NAMES = {
    'Emilio Godoy',
    'Emilio',
    'Godoy',
    'Enrique',
    'Sierra',
    'Emilio Enrique Godoy Sierra'
}



def ultra_clean_html(html_content):
    """ULTRA-AGGRESSIVE HTML cleaning - removes ALL tracking and formatting artifacts"""
    if not html_content:
        return ""
    
    # PHASE 1: Remove ALL scripts, styles, comments, meta tags
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<!--.*?-->', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<meta[^>]*>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<link[^>]*>', '', html_content, flags=re.IGNORECASE)
    
    # PHASE 2: Remove ALL tracking links and URLs with parameters
    html_content = re.sub(r'https?://[^\s<>"]+[=&][^\s<>"]+', '[TRACKING_LINK]', html_content)
    html_content = re.sub(r'href="[^"]*upn=[^"]*"', 'href="[TRACKING_LINK]"', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'href="[^"]*click[^"]*"', 'href="[TRACKING_LINK]"', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'href="[^"]*tracking[^"]*"', 'href="[TRACKING_LINK]"', html_content, flags=re.IGNORECASE)
    
    # PHASE 3: Remove invisible characters and zero-width spaces
    html_content = re.sub(r'[\u200B-\u200D\uFEFF\u00A0\u202F\u00AD]', ' ', html_content)
    html_content = re.sub(r'&nbsp;|&zwnj;|&shy;', ' ', html_content, flags=re.IGNORECASE)
    
    # PHASE 4: Remove specific tracking patterns
    html_content = re.sub(r'X[a-fA-F0-9]+', '', html_content)  # Tracking codes
    html_content = re.sub(r'upn=u001\.[^&\s]+', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'dgme8z[^&\s]*', '', html_content)  # Myprotein tracking
    
    # PHASE 5: Use html2text with aggressive settings
    h = html2text.HTML2Text()
    h.ignore_links = True  # Remove ALL links
    h.ignore_images = True
    h.ignore_emphasis = True  # Remove **bold** and _italic_
    h.body_width = 0
    h.single_line_break = True
    h.unicode_snob = True
    
    try:
        text = h.handle(html_content)
    except Exception as e:
        # Fallback: brutal tag removal
        text = re.sub(r'<[^>]+>', '', html_content)
    
    # PHASE 6: Post-processing cleanup
    # Remove markdown artifacts
    text = re.sub(r'\[.*?\]', '', text)  # Remove [text]
    text = re.sub(r'\*+', '', text)      # Remove ****
    text = re.sub(r'_{2,}', '', text)    # Remove ___
    text = re.sub(r'#+', '', text)       # Remove ###
    
    # Remove table artifacts and pipes
    text = re.sub(r'\n\s*[\|·•]\s*', '\n', text)
    text = re.sub(r'\s*[\|·•]\s*', ' ', text)
    
    # Remove horizontal lines and separators
    text = re.sub(r'-{3,}', '', text)
    text = re.sub(r'={3,}', '', text)
    text = re.sub(r'\*{3,}', '', text)
    
    # Remove email-specific artifacts
    text = re.sub(r'\[TRACKING_LINK\]', '', text)
    text = re.sub(r'\[image:[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\!\[[^\]]*\]\[[^\]]*\]', '', text)
    
    # Clean up whitespace aggressively
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Reduce multiple blank lines
    text = re.sub(r'[ \t]{2,}', ' ', text)         # Multiple spaces to single
    text = re.sub(r'\n[ \t]+', '\n', text)         # Spaces at line start
    
    return text.strip()

def decode_mime_header(header):
    """Decode MIME encoded headers"""
    if not header:
        return ""
    try:
        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                encoding = encoding or 'utf-8'
                try:
                    decoded_parts.append(part.decode(encoding))
                except:
                    decoded_parts.append(part.decode('utf-8', errors='ignore'))
            else:
                decoded_parts.append(part)
        return ' '.join(decoded_parts)
    except:
        return str(header)

def redact_personal_info(text, personal_emails, personal_names):
    """Redact personal information"""
    if not text:
        return ""
    
    # Redact emails
    for email in personal_emails:
        email_pattern = re.escape(email)
        text = re.sub(email_pattern, '[REDACTED_MY_EMAIL]', text, flags=re.IGNORECASE)
    
    # Redact names
    for name in personal_names:
        name_pattern = re.escape(name)
        text = re.sub(name_pattern, '[REDACTED_MY_NAME]', text, flags=re.IGNORECASE)
    
    # Redact credit cards
    card_patterns = [
        r'\b(?:\d{4}[- ]?){3}(\d{4})\b',
        r'\b[*#]{4,6}[\s-]*(\d{4})\b',
        r'\bending[:\s]*(\d{4})\b',
        r'\*\*[A-Z]+\*\*\s*\*\*(\d{4})\b',
    ]
    
    for pattern in card_patterns:
        text = re.sub(pattern, '[REDACTED_CARD_LAST4]', text)
    
    return text

def extract_clean_text_from_email(message):
    """Extract and ULTRA-clean text from email"""
    text_parts = []
    
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition', ''))
            
            if 'attachment' in content_disposition:
                continue
                
            payload = part.get_payload(decode=True)
            if not payload:
                continue
                
            try:
                decoded_payload = payload.decode('utf-8', errors='ignore')
                
                if content_type == 'text/plain':
                    # For plain text, just clean basic artifacts
                    clean_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', decoded_payload)
                    text_parts.append(clean_text)
                elif content_type == 'text/html':
                    # For HTML, use ULTRA aggressive cleaning
                    clean_text = ultra_clean_html(decoded_payload)
                    if clean_text and len(clean_text.strip()) > 20:
                        text_parts.append(clean_text)
                    
            except Exception:
                continue
    else:
        # Not multipart
        payload = message.get_payload(decode=True)
        if payload:
            try:
                decoded_payload = payload.decode('utf-8', errors='ignore')
                content_type = message.get_content_type()
                
                if content_type == 'text/html':
                    clean_text = ultra_clean_html(decoded_payload)
                    text_parts.append(clean_text)
                else:
                    clean_text = re.sub(r'[\u200B-\u200D\uFEFF]', '', decoded_payload)
                    text_parts.append(clean_text)
                    
            except Exception:
                pass
    
    # Combine and final cleanup
    full_text = '\n'.join(text_parts)
    return final_text_cleanup(full_text)

def final_text_cleanup(text):
    """Final aggressive cleanup of text"""
    if not text:
        return ""
    
    # Remove lines that are mostly artifacts
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        line = line.strip()
        
        # Skip lines that are:
        # - Too short
        # - Mostly special characters  
        # - Contain obvious tracking patterns
        if (len(line) > 15 and 
            re.search(r'[a-zA-Z]{3,}', line) and  # At least 3 consecutive letters
            not re.match(r'^[\s|*\-_=#•·~]{10,}$', line) and
            not re.search(r'(upn=|click|tracking|X[0-9a-fA-F]+)', line, re.IGNORECASE)):
            cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    
    # Final whitespace cleanup
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    
    return text.strip()

def parse_email_date(date_str):
    """Parse email date"""
    try:
        if date_str:
            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
    except:
        pass
    return date_str

def get_basic_category(from_addr, subject):
    """Simple categorization"""
    from_lower = (from_addr or "").lower()
    subject_lower = (subject or "").lower()
    
    if any(domain in from_lower for domain in ['@google.com', '@accounts.google.com']):
        if any(word in subject_lower for word in ['security', 'alert', 'alerta', 'recuperación']):
            return ["security"]
    
    if any(domain in from_lower for domain in ['@aliexpress.com', '@amazon.com', '@myprotein.com']):
        return ["shopping"]
    
    if any(domain in from_lower for domain in ['@lionbridge.com', '@appen.com']):
        return ["work"]
    
    if any(domain in from_lower for domain in ['@binance.com', '@uphold.com']):
        return ["crypto"]
    
    if any(domain in from_lower for domain in ['@surveoo.com']):
        return ["survey"]
    
    return []

def parse_gmail_takeout_ultra_clean(mbox_path, output_jsonl_path, personal_emails, personal_names):
    """Fast parsing with ULTRA aggressive HTML cleaning"""
    messages_processed = 0
    
    with open(output_jsonl_path, 'w', encoding='utf-8') as outfile:
        mbox = mailbox.mbox(mbox_path)
        
        for i, message in enumerate(mbox):
            try:
                # Basic info
                msg_id = str(i + 1)
                raw_subject = message.get('Subject', '')
                subject = decode_mime_header(raw_subject)
                from_addr = message.get('From', '')
                to_addr = message.get('To', '')
                date_str = message.get('Date', '')
                
                timestamp = parse_email_date(date_str)
                text_content = extract_clean_text_from_email(message)
                
                # Skip if text is too short after cleaning
                if not text_content or len(text_content.strip()) < 25:
                    continue
                
                # Simple categorization
                tags = get_basic_category(from_addr, subject)
                
                # Redact personal info
                subject_redacted = redact_personal_info(subject, personal_emails, personal_names)
                text_content_redacted = redact_personal_info(text_content, personal_emails, personal_names)
                
                # Redact from/to
                from_addr_redacted = from_addr
                to_addr_redacted = to_addr
                for email in personal_emails:
                    if email.lower() in from_addr.lower():
                        from_addr_redacted = '[REDACTED_MY_EMAIL]'
                    if email.lower() in to_addr.lower():
                        to_addr_redacted = '[REDACTED_MY_EMAIL]'
                
                message_data = {
                    "id": msg_id,
                    "source": "gmail",
                    "path": mbox_path,
                    "timestamp": timestamp,
                    "text": text_content_redacted,
                    "meta": {
                        "subject": subject_redacted,
                        "from": from_addr_redacted,
                        "to": to_addr_redacted
                    },
                    "tags": tags
                }
                
                outfile.write(json.dumps(message_data, ensure_ascii=False) + '\n')
                messages_processed += 1
                
                if messages_processed % 1000 == 0:
                    print(f"Processed {messages_processed} emails...")
                    
            except Exception as e:
                continue
    
    print(f"Completed! Processed {messages_processed} emails with ULTRA cleaning")
    return messages_processed

# Usage
if __name__ == "__main__":
    mbox_file = "takeout/1MAIL.mbox"
    output_file = "emails_ultra_clean.jsonl"
    
    parsed_count = parse_gmail_takeout_ultra_clean(mbox_file, output_file, PERSONAL_EMAILS, PERSONAL_NAMES)
    print(f"Parsed {parsed_count} emails - ULTRA CLEAN MODE")