from enum import Enum
from datetime import datetime
import pytz
import re
import logging
from config import settings

logger = logging.getLogger(__name__)

class CallState(Enum):
    """Call conversation states"""
    START = "START"
    CONSENT = "CONSENT"
    VERIFY_IDENTITY = "VERIFY_IDENTITY"
    MAIN_MENU = "MAIN_MENU"
    COLLECT_DETAILS = "COLLECT_DETAILS"
    WRAP_UP = "WRAP_UP"
    END_CALL = "END_CALL"
    TRANSFER = "TRANSFER"

class Intent(Enum):
    """Conversation intents"""
    GREETING = "GREETING"
    VERIFICATION = "VERIFICATION"
    MAKE_PAYMENT = "MAKE_PAYMENT"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    DISPUTE = "DISPUTE"
    WRONG_NUMBER = "WRONG_NUMBER"
    CALLBACK_LATER = "CALLBACK_LATER"
    HARDSHIP = "HARDSHIP"
    TRANSFER_AGENT = "TRANSFER_AGENT"
    DO_NOT_CALL = "DO_NOT_CALL"
    UNCLEAR = "UNCLEAR"

class Sentiment(Enum):
    """Conversation sentiment"""
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"

def get_current_time() -> datetime:
    """Get current time in configured timezone"""
    tz = pytz.timezone(settings.timezone)
    return datetime.now(tz)

def format_currency(amount: float, currency: str = "₹") -> str:
    """Format currency for Indian locale"""
    return f"{currency}{amount:,.2f}"

def format_date_indian(date_obj: datetime) -> str:
    """Format date in Indian format"""
    return date_obj.strftime("%d/%m/%Y")

def sanitize_phone_number(phone: str) -> str:
    """Sanitize and format phone number to E.164"""
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)
    
    # Handle Indian numbers
    if len(digits) == 10 and digits.startswith(('6', '7', '8', '9')):
        return f"+91{digits}"
    elif len(digits) == 12 and digits.startswith('91'):
        return f"+{digits}"
    elif len(digits) == 13 and digits.startswith('+91'):
        return digits
    
    return phone  # Return as-is if can't parse

def extract_amount_from_text(text: str) -> float:
    """Extract monetary amounts from text"""
    # Look for patterns like "2000", "two thousand", "₹1500"
    patterns = [
        r'₹\s*(\d+(?:,\d+)*(?:\.\d{2})?)',  # ₹2,500.00
        r'(\d+(?:,\d+)*(?:\.\d{2})?)\s*(?:rupees?|rs\.?)',  # 2500 rupees
        r'\b(\d+(?:,\d+)*(?:\.\d{2})?)\b'  # Just numbers
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '')
            try:
                return float(amount_str)
            except ValueError:
                continue
    
    return 0.0

def safe_log_pii(data: dict) -> dict:
    """Safely log data by masking PII"""
    safe_data = data.copy()
    
    # Mask sensitive fields
    if 'phone_e164' in safe_data:
        phone = safe_data['phone_e164']
        safe_data['phone_e164'] = phone[:3] + "****" + phone[-4:] if len(phone) > 7 else "****"
    
    if 'name' in safe_data:
        name = safe_data['name']
        safe_data['name'] = name[0] + "*" * (len(name) - 2) + name[-1] if len(name) > 2 else "****"
    
    return safe_data

def validate_indian_time_slot(hour: int, minute: int = 0) -> bool:
    """Validate if given time is within Indian business hours"""
    time_str = f"{hour:02d}:{minute:02d}"
    return settings.calling_hours_start <= time_str <= settings.calling_hours_end

def text_to_speech_optimized(text: str, max_length: int = 200) -> str:
    """Optimize text for text-to-speech (TTS)"""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    
    # Truncate if too long
    if len(text) > max_length:
        # Try to truncate at sentence boundary
        sentences = text.split('. ')
        truncated = ""
        for sentence in sentences:
            if len(truncated + sentence) <= max_length - 3:
                truncated += sentence + ". "
            else:
                break
        text = truncated.strip()
        if len(text) > max_length:
            text = text[:max_length-3] + "..."
    
    # Replace abbreviations for better pronunciation
    replacements = {
        'EMI': 'E.M.I.',
        'KYC': 'K.Y.C.',
        'PAN': 'P.A.N.',
        'UPI': 'U.P.I.',
        'NBFC': 'N.B.F.C.',
        'Rs.': 'rupees',
        '₹': 'rupees '
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text

class CallLogger:
    """Specialized logger for call events"""
    
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self.logger = logging.getLogger(f"call.{call_sid}")
    
    def info(self, message: str, extra_data: dict = None):
        log_data = {'call_sid': self.call_sid}
        if extra_data:
            log_data.update(safe_log_pii(extra_data))
        self.logger.info(message, extra=log_data)
    
    def error(self, message: str, extra_data: dict = None):
        log_data = {'call_sid': self.call_sid}
        if extra_data:
            log_data.update(safe_log_pii(extra_data))
        self.logger.error(message, extra=log_data)

def get_language_voice_settings(language_pref: str) -> dict:
    """Get Twilio voice settings based on language preference"""
    if language_pref == 'HI':
        return {
            'voice': 'alice',
            'language': 'hi-IN'
        }
    else:
        return {
            'voice': 'alice',
            'language': 'en-IN'
        }

def parse_twilio_duration(duration_str: str) -> int:
    """Parse Twilio duration string to seconds"""
    try:
        return int(duration_str) if duration_str else 0
    except (ValueError, TypeError):
        return 0

# Response templates for different scenarios
RESPONSE_TEMPLATES = {
    'verification_failed': {
        'EN': "I couldn't verify your identity. Let me transfer you to an agent for assistance.",
        'HI': "मैं आपकी पहचान सत्यापित नहीं कर सका। मैं आपको सहायता के लिए एजेंट के पास स्थानांतरित कर देता हूं।"
    },
    'payment_confirmation': {
        'EN': "Thank you for your payment commitment. You'll receive a confirmation shortly.",
        'HI': "आपकी भुगतान प्रतिबद्धता के लिए धन्यवाद। आपको शीघ्र ही पुष्टि प्राप्त होगी।"
    },
    'callback_scheduled': {
        'EN': "I've scheduled a callback as requested. Thank you for your time.",
        'HI': "मैंने अनुरोध के अनुसार कॉलबैक निर्धारित किया है। आपके समय के लिए धन्यवाद।"
    },
    'dnc_confirmed': {
        'EN': "I've added you to our do-not-call list. You won't receive further collection calls.",
        'HI': "मैंने आपको हमारी डू-नॉट-कॉल सूची में जोड़ दिया है। आपको आगे कलेक्शन कॉल नहीं आएंगे।"
    }
}

def get_response_template(template_key: str, language: str = 'EN') -> str:
    """Get response template in specified language"""
    return RESPONSE_TEMPLATES.get(template_key, {}).get(language, 
           RESPONSE_TEMPLATES.get(template_key, {}).get('EN', ''))