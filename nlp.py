import json
import re
import logging
import httpx
from typing import Dict, Any
from anthropic import Anthropic
from config import settings
from utils import CallState, Intent, Sentiment

logger = logging.getLogger(__name__)

class NLPProcessor:
    def __init__(self):
        try:
            # Initialize Anthropic client with custom HTTP client to handle proxy issues
            http_client = httpx.Client(
                timeout=30.0,
                verify=True,  # SSL verification
                follow_redirects=True
            )
            
            self.client = Anthropic(
                api_key=settings.anthropic_api_key,
                http_client=http_client
            )
            
            # Test connection
            logger.info("Anthropic client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            self.client = None
        
        # Fallback regex patterns for intent detection
        self.intent_patterns = {
            Intent.MAKE_PAYMENT: [
                r'\b(pay|payment|paying)\b.*\b(now|today|immediately)\b',
                r'\bupi\b.*\blink\b',
                r'\bpaid?\b.*\bnow\b'
            ],
            Intent.PROMISE_TO_PAY: [
                r'\b(pay|payment)\b.*\b(tomorrow|friday|monday|next week|soon)\b',
                r'\bpromise\b.*\bpay\b',
                r'\bwill pay\b.*\b(on|by)\b'
            ],
            Intent.DISPUTE: [
                r'\bnot\s+(mine|my)\b',
                r'\bdispute\b',
                r'\bwrong\s+amount\b',
                r'\bneed\s+(statement|proof|details)\b'
            ],
            Intent.WRONG_NUMBER: [
                r'\bwrong\s+number\b',
                r'\bnot\s+(me|the|a)\s+(borrower|person)\b',
                r'\bdon\'?t\s+know\b.*\bloan\b'
            ],
            Intent.CALLBACK_LATER: [
                r'\bcall\s+back\b',
                r'\blater\b',
                r'\bnot\s+good\s+time\b',
                r'\bbusy\b.*\bnow\b'
            ],
            Intent.HARDSHIP: [
                r'\bhardship\b',
                r'\bfinancial\s+(difficulty|problem)\b',
                r'\bjob\s+loss\b',
                r'\bcan\'?t\s+afford\b'
            ],
            Intent.TRANSFER_AGENT: [
                r'\bagent\b',
                r'\bmanager\b',
                r'\bhuman\b',
                r'\btalk\s+to\s+someone\b'
            ],
            Intent.DO_NOT_CALL: [
                r'\bdo\s+not\s+call\b',
                r'\bstop\s+calling\b',
                r'\bdon\'?t\s+call\b',
                r'\bopt\s+out\b'
            ]
        }

    async def analyze_utterance(self, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze caller's speech and return structured response
        """
        # If Anthropic client failed to initialize, use fallback immediately
        if self.client is None:
            logger.warning("Anthropic client not available, using fallback analysis")
            return self._fallback_analysis(text, context)
            
        try:
            # Prepare context for Claude
            borrower_info = context.get('borrower', {})
            loan_info = context.get('loan', {})
            call_state = context.get('current_state', 'START')
            last_bot_message = context.get('last_bot_message', '')
            
            context_text = f"""
Current State: {call_state}
Last Bot Message: {last_bot_message}
Borrower Language Preference: {borrower_info.get('language_pref', 'EN')}
Due Amount: ₹{loan_info.get('due_amount', 0):,.2f}
Days Past Due: {loan_info.get('days_past_due', 0)}
Caller Said: "{text}"
"""

            # Read system prompt
            try:
                with open('prompts/system_prompt_collections.txt', 'r', encoding='utf-8') as f:
                    system_prompt = f.read().strip()
            except FileNotFoundError:
                logger.error("System prompt file not found, using fallback")
                return self._fallback_analysis(text, context)
            
            # Call Claude API with timeout and error handling
            try:
                message = self.client.messages.create(
                    model="claude-3-haiku-20240307",  # Use Haiku for faster responses
                    max_tokens=500,  # Reduced tokens for faster response
                    temperature=0.1,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": context_text}
                    ]
                )
                
                # Parse Claude's response
                response_text = message.content[0].text.strip()
                logger.debug(f"Claude raw response: {response_text}")
                
            except Exception as api_error:
                logger.error(f"Anthropic API call failed: {api_error}")
                return self._fallback_analysis(text, context)
            
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    response_json = json.loads(json_match.group())
                    
                    # Validate required fields
                    required_fields = ['intent', 'sentiment', 'slots', 'reply_text', 'next_state']
                    if all(field in response_json for field in required_fields):
                        # Ensure proper enum values
                        response_json['intent'] = self._normalize_intent(response_json['intent'])
                        response_json['sentiment'] = self._normalize_sentiment(response_json['sentiment'])
                        response_json['next_state'] = self._normalize_state(response_json['next_state'])
                        
                        logger.info(f"Successfully analyzed utterance: {response_json['intent']}")
                        return response_json
                        
                except json.JSONDecodeError as json_error:
                    logger.warning(f"Failed to parse Claude JSON response: {json_error}")
            
            # If we reach here, Claude response was malformed
            logger.warning(f"Malformed Claude response, using fallback: {response_text[:100]}...")
            return self._fallback_analysis(text, context)
            
        except Exception as e:
            logger.error(f"Error in analyze_utterance: {e}")
            return self._fallback_analysis(text, context)

    def _fallback_analysis(self, text: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simple rule-based fallback when Claude API fails
        """
        text_lower = text.lower()
        detected_intent = Intent.UNCLEAR
        confidence = 0.5
        
        # Check against regex patterns
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    detected_intent = intent
                    confidence = 0.7
                    break
            if detected_intent != Intent.UNCLEAR:
                break
        
        # Determine sentiment
        positive_words = ['yes', 'okay', 'sure', 'definitely', 'will pay', 'can pay']
        negative_words = ['no', 'can\'t', 'unable', 'won\'t', 'refuse', 'angry']
        
        sentiment = Sentiment.NEUTRAL
        if any(word in text_lower for word in positive_words):
            sentiment = Sentiment.POSITIVE
        elif any(word in text_lower for word in negative_words):
            sentiment = Sentiment.NEGATIVE
        
        # Extract basic slots
        slots = {}
        
        # Look for amounts
        amount_match = re.search(r'\b(\d+(?:,\d+)*)\s*(?:rupees?|rs\.?|₹)?\b', text_lower)
        if amount_match:
            slots['amount'] = amount_match.group(1).replace(',', '')
        
        # Look for dates
        date_patterns = [
            r'\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\bnext\s+(week|month)\b',
            r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                slots['date'] = match.group()
                break
        
        # Generate appropriate response
        current_state = context.get('current_state', 'START')
        if current_state == 'VERIFY_IDENTITY':
            next_state = CallState.MAIN_MENU if detected_intent == Intent.VERIFICATION else CallState.VERIFY_IDENTITY
            reply_text = "Thank you. Now, how can I help you with your loan today?"
        elif detected_intent == Intent.MAKE_PAYMENT:
            next_state = CallState.COLLECT_DETAILS
            reply_text = "Great! I'll help you make a payment. What amount would you like to pay?"
        elif detected_intent == Intent.PROMISE_TO_PAY:
            next_state = CallState.COLLECT_DETAILS  
            reply_text = "I understand. When would you be able to make the payment?"
        elif detected_intent == Intent.TRANSFER_AGENT:
            next_state = CallState.TRANSFER
            reply_text = "I'll transfer you to an agent. Please hold."
        elif detected_intent == Intent.DO_NOT_CALL:
            next_state = CallState.END_CALL
            reply_text = "I understand. I'll add you to our do-not-call list. Have a good day."
        else:
            next_state = CallState.MAIN_MENU
            reply_text = "I understand. Is there anything else I can help you with today?"
        
        return {
            'intent': detected_intent.value,
            'sentiment': sentiment.value,
            'slots': slots,
            'reply_text': reply_text,
            'next_state': next_state.value,
            'confidence': confidence,
            'fallback_used': True
        }

    def _normalize_intent(self, intent: str) -> str:
        """Normalize intent to valid enum value"""
        intent_map = {
            'MAKE_PAYMENT': Intent.MAKE_PAYMENT.value,
            'PROMISE_TO_PAY': Intent.PROMISE_TO_PAY.value,
            'DISPUTE': Intent.DISPUTE.value,
            'WRONG_NUMBER': Intent.WRONG_NUMBER.value,
            'CALLBACK_LATER': Intent.CALLBACK_LATER.value,
            'HARDSHIP': Intent.HARDSHIP.value,
            'TRANSFER_AGENT': Intent.TRANSFER_AGENT.value,
            'DO_NOT_CALL': Intent.DO_NOT_CALL.value,
            'VERIFICATION': Intent.VERIFICATION.value,
            'GREETING': Intent.GREETING.value
        }
        return intent_map.get(intent.upper(), Intent.UNCLEAR.value)

    def _normalize_sentiment(self, sentiment: str) -> str:
        """Normalize sentiment to valid enum value"""
        sentiment_map = {
            'POSITIVE': Sentiment.POSITIVE.value,
            'NEGATIVE': Sentiment.NEGATIVE.value,
            'NEUTRAL': Sentiment.NEUTRAL.value
        }
        return sentiment_map.get(sentiment.upper(), Sentiment.NEUTRAL.value)

    def _normalize_state(self, state: str) -> str:
        """Normalize state to valid enum value"""
        state_map = {
            'VERIFY_IDENTITY': CallState.VERIFY_IDENTITY.value,
            'MAIN_MENU': CallState.MAIN_MENU.value,
            'COLLECT_DETAILS': CallState.COLLECT_DETAILS.value,
            'WRAP_UP': CallState.WRAP_UP.value,
            'END_CALL': CallState.END_CALL.value,
            'TRANSFER': CallState.TRANSFER.value
        }
        return state_map.get(state.upper(), CallState.MAIN_MENU.value)

# Global instance
nlp_processor = NLPProcessor()