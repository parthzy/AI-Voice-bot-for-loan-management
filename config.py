import os
from datetime import datetime
import pytz
from typing import ClassVar
from pydantic import BaseModel

class Settings(BaseModel):
    # Twilio Configuration
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_calling_number: str = os.getenv("TWILIO_CALLING_NUMBER", "")

    # Anthropic Claude API
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # MySQL Database
    mysql_host: str = os.getenv("MYSQL_HOST", "localhost")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_db: str = os.getenv("MYSQL_DB", "loan_voice_bot")
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")

    # Application Settings
    app_public_url: str = os.getenv("APP_PUBLIC_URL", "http://localhost:8000")
    timezone: str = os.getenv("TIMEZONE", "Asia/Kolkata")

    # Fix for debug
    debug: ClassVar[bool] = os.getenv("DEBUG", "False").lower() == "true"

    # Collections Settings
    calling_hours_start: str = os.getenv("CALLING_HOURS_START", "09:00")
    calling_hours_end: str = os.getenv("CALLING_HOURS_END", "19:00")
    max_call_attempts: int = int(os.getenv("MAX_CALL_ATTEMPTS", "3"))

    def validate_required_settings(self):
        """Validate that all required settings are present"""
        required_settings = [
            'twilio_account_sid',
            'twilio_auth_token',
            'twilio_calling_number',
            'anthropic_api_key',
            'mysql_password'
        ]
        
        missing = []
        for setting in required_settings:
            if not getattr(self, setting):
                missing.append(setting.upper())
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    def get_current_time(self) -> datetime:
        """Get current time in the configured timezone"""
        tz = pytz.timezone(self.timezone)
        return datetime.now(tz)

    def is_calling_hours(self) -> bool:
        """Check if current time is within calling hours"""
        current_time = self.get_current_time()
        current_hour_minute = current_time.strftime("%H:%M")
        return self.calling_hours_start <= current_hour_minute <= self.calling_hours_end

settings = Settings()
