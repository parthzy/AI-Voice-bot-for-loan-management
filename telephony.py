from fastapi import APIRouter, Form, Request, HTTPException, Depends
from twilio.twiml.voice_response import VoiceResponse

from twilio.rest import Client
import logging
from datetime import datetime
from typing import Optional

from config import settings
from db import get_db_connection, get_borrower_by_phone, create_call_session, update_call_session, log_call_turn
from nlp import nlp_processor
from utils import CallState, get_current_time, format_currency

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize Twilio client
twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

@router.post("/voice/incoming")
async def handle_incoming_call(
    request: Request,
    From: str = Form(...),
    CallSid: str = Form(...),
    CallStatus: str = Form(...)
):
    """Handle incoming calls - initial greeting and verification"""
    logger.info(f"Incoming call from {From}, CallSid: {CallSid}")
    
    response = VoiceResponse()
    
    try:
        # Look up borrower by phone number
        conn = get_db_connection()
        borrower = get_borrower_by_phone(conn, From)
        
        if not borrower:
            # Unknown caller
            response.say(
                "Thank you for calling. I'm sorry, but I don't have your information in our system. "
                "Please contact our customer service team. Goodbye.",
                voice='alice', language='en-IN'
            )
            response.hangup()
            return str(response)
        
        # Check if borrower is on DNC list
        if borrower.get('is_dnc'):
            response.say(
                "I apologize, but you've requested not to receive calls. "
                "If you need assistance, please contact our customer service team. Goodbye.",
                voice='alice', language='en-IN'
            )
            response.hangup()
            return str(response)
        
        # Create call session
        session_id = create_call_session(conn, CallSid, borrower['id'], 'INBOUND')
        
        # Record consent line
        consent_text = (
            "Hello, this call may be recorded for quality and training purposes. "
            f"Am I speaking with {borrower['name']}?"
        )
        
        # Choose language based on borrower preference
        language = 'hi-IN' if borrower.get('language_pref') == 'HI' else 'en-IN'
        voice = 'alice'  # Twilio supports multiple voices
        
        response.say(consent_text, voice=voice, language=language)
        
        # Gather verification response
        gather = response.gather(
            input='speech',
            timeout=5,
            speech_timeout='auto',
            language=language,
            action=f"{settings.app_public_url}/voice/continue?session_id={session_id}&borrower_id={borrower['id']}&state=VERIFY_IDENTITY"
        )
        
        # Fallback if no speech detected
        response.say("I didn't hear anything. Please call back when you're ready to speak. Goodbye.")
        response.hangup()
        
        # Log the bot's message
        log_call_turn(conn, session_id, 1, 'BOT', consent_text, None, None, {})
        
        conn.close()
        return str(response)
        
    except Exception as e:
        logger.error(f"Error handling incoming call: {e}")
        response.say("I'm experiencing technical difficulties. Please try calling back later. Goodbye.")
        response.hangup()
        return str(response)

@router.post("/voice/continue")
async def handle_speech_result(
    request: Request,
    session_id: int,
    borrower_id: int,
    state: str,
    SpeechResult: Optional[str] = Form(None),
    CallSid: str = Form(...),
    Confidence: Optional[float] = Form(None)
):
    """Handle speech recognition results and continue conversation"""
    logger.info(f"Speech result: {SpeechResult}, Confidence: {Confidence}, State: {state}")
    
    response = VoiceResponse()
    
    try:
        conn = get_db_connection()
        
        # Get borrower and loan info
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT b.*, l.due_amount, l.days_past_due, l.due_date, l.loan_id as loan_number
            FROM borrowers b 
            LEFT JOIN loans l ON b.id = l.borrower_id 
            WHERE b.id = %s
        """, (borrower_id,))
        borrower_data = cursor.fetchone()
        
        if not borrower_data:
            response.say("Sorry, I can't find your information. Please contact customer service.")
            response.hangup()
            return str(response)
        
        # Get current turn number
        cursor.execute("SELECT MAX(turn_no) as max_turn FROM call_logs WHERE call_session_id = %s", (session_id,))
        turn_result = cursor.fetchone()
        current_turn = (turn_result['max_turn'] or 0) + 1
        
        # Get last bot message for context
        cursor.execute("""
            SELECT text FROM call_logs 
            WHERE call_session_id = %s AND role = 'BOT' 
            ORDER BY turn_no DESC LIMIT 1
        """, (session_id,))
        last_bot = cursor.fetchone()
        last_bot_message = last_bot['text'] if last_bot else ""
        
        speech_text = SpeechResult or "No speech detected"
        
        # Log caller's speech
        log_call_turn(conn, session_id, current_turn, 'CALLER', speech_text, None, None, {'confidence': Confidence})
        
        # Prepare context for NLP analysis
        context = {
            'borrower': borrower_data,
            'loan': borrower_data,
            'current_state': state,
            'last_bot_message': last_bot_message,
            'turn_number': current_turn
        }
        
        # Analyze speech with NLP
        analysis = await nlp_processor.analyze_utterance(speech_text, context)
        
        # Log analysis results
        log_call_turn(conn, session_id, current_turn + 1, 'BOT', analysis['reply_text'], 
                     analysis['intent'], analysis['sentiment'], analysis['slots'])
        
        # Handle specific intents
        next_action = await handle_intent(conn, session_id, borrower_data, analysis)
        
        # Update call session state
        update_call_session(conn, session_id, analysis['next_state'], 
                          analysis.get('verification_state', 'PENDING'))
        
        # Generate TwiML response
        language = 'hi-IN' if borrower_data.get('language_pref') == 'HI' else 'en-IN'
        
        response.say(analysis['reply_text'], voice='alice', language=language)
        
        # Determine next action
        if analysis['next_state'] == 'END_CALL':
            response.hangup()
        elif analysis['next_state'] == 'TRANSFER':
            response.say("Please hold while I transfer you.", voice='alice', language=language)
            # In production, you'd dial to an agent queue
            response.dial(settings.agent_transfer_number if hasattr(settings, 'agent_transfer_number') else '+1234567890')
        else:
            # Continue conversation
            gather = response.gather(
                input='speech',
                timeout=10,
                speech_timeout='auto',
                language=language,
                action=f"{settings.app_public_url}/voice/continue?session_id={session_id}&borrower_id={borrower_id}&state={analysis['next_state']}"
            )
            
            # Timeout fallback
            response.say("I didn't hear you. Let me transfer you to an agent.", voice='alice', language=language)
            response.hangup()
        
        conn.close()
        return str(response)
        
    except Exception as e:
        logger.error(f"Error in handle_speech_result: {e}")
        response.say("I'm having technical difficulties. Please contact our customer service team.")
        response.hangup()
        return str(response)

async def handle_intent(conn, session_id: int, borrower_data: dict, analysis: dict) -> dict:
    """Handle specific intents and update database accordingly"""
    intent = analysis['intent']
    slots = analysis.get('slots', {})
    
    try:
        cursor = conn.cursor()
        
        if intent == 'PROMISE_TO_PAY':
            # Save promise to pay
            promise_date = slots.get('date', 'unspecified')
            amount = float(slots.get('amount', 0)) if slots.get('amount') else borrower_data['due_amount']
            
            cursor.execute("""
                INSERT INTO ptp_promises (borrower_id, call_session_id, promise_date, amount)
                VALUES (%s, %s, %s, %s)
            """, (borrower_data['id'], session_id, promise_date, amount))
            
        elif intent == 'DO_NOT_CALL':
            # Mark borrower as DNC
            cursor.execute("UPDATE borrowers SET is_dnc = TRUE WHERE id = %s", (borrower_data['id'],))
            cursor.execute("""
                INSERT INTO dnc_requests (borrower_id, call_session_id, reason)
                VALUES (%s, %s, %s)
            """, (borrower_data['id'], session_id, slots.get('reason', 'Customer request')))
            
        elif intent == 'CALLBACK_LATER':
            # Schedule callback
            from datetime import datetime, timedelta
            callback_time = datetime.now() + timedelta(hours=24)  # Default to 24 hours
            
            cursor.execute("""
                INSERT INTO callbacks (borrower_id, call_session_id, scheduled_at, reason)
                VALUES (%s, %s, %s, %s)
            """, (borrower_data['id'], session_id, callback_time, slots.get('reason', 'Customer requested callback')))
        
        conn.commit()
        return {'status': 'success'}
        
    except Exception as e:
        logger.error(f"Error handling intent {intent}: {e}")
        conn.rollback()
        return {'status': 'error', 'message': str(e)}

@router.post("/voice/status")
async def handle_call_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[str] = Form(None)
):
    """Handle Twilio call status callbacks"""
    logger.info(f"Call status update: {CallSid} - {CallStatus}")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update call session
        cursor.execute("""
            UPDATE call_sessions 
            SET status = %s, ended_at = NOW(), duration_seconds = %s
            WHERE call_sid = %s
        """, (CallStatus.upper(), CallDuration, CallSid))
        
        conn.commit()
        conn.close()
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error updating call status: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/voice/outbound")
async def initiate_outbound_call(borrower_id: int):
    """Initiate outbound call to a borrower"""
    logger.info(f"Initiating outbound call to borrower {borrower_id}")
    
    try:
        conn = get_db_connection()
        borrower = get_borrower_by_phone_id(conn, borrower_id)
        
        if not borrower:
            raise HTTPException(status_code=404, detail="Borrower not found")
        
        if borrower.get('is_dnc'):
            raise HTTPException(status_code=400, detail="Borrower is on do-not-call list")
        
        # Create call session first
        session_id = create_call_session(conn, f"OUTBOUND_{borrower_id}_{datetime.now().timestamp()}", 
                                       borrower_id, 'OUTBOUND')
        
        # Make the call using Twilio
        call = twilio_client.calls.create(
            to=borrower['phone_e164'],
            from_=settings.twilio_calling_number,
            url=f"{settings.app_public_url}/voice/outbound/greeting?session_id={session_id}&borrower_id={borrower_id}",
            status_callback=f"{settings.app_public_url}/voice/status",
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            status_callback_method='POST'
        )
        
        # Update session with actual Twilio CallSid
        cursor = conn.cursor()
        cursor.execute("UPDATE call_sessions SET call_sid = %s WHERE id = %s", (call.sid, session_id))
        conn.commit()
        conn.close()
        
        logger.info(f"Outbound call initiated: {call.sid}")
        return {"status": "success", "call_sid": call.sid, "session_id": session_id}
        
    except Exception as e:
        logger.error(f"Error initiating outbound call: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/voice/outbound/greeting")
async def handle_outbound_greeting(
    request: Request,
    session_id: int,
    borrower_id: int,
    CallSid: str = Form(...),
    CallStatus: str = Form(...)
):
    """Handle outbound call greeting"""
    response = VoiceResponse()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get borrower info
        cursor.execute("SELECT * FROM borrowers WHERE id = %s", (borrower_id,))
        borrower = cursor.fetchone()
        
        if not borrower:
            response.say("I'm sorry, there was an error. Goodbye.")
            response.hangup()
            return str(response)
        
        # Outbound greeting with compliance
        language = 'hi-IN' if borrower.get('language_pref') == 'HI' else 'en-IN'
        greeting_text = (
            f"Hello, this is a call from your loan service provider. "
            f"This call may be recorded. Am I speaking with {borrower['name']}? "
            f"I'm calling regarding your loan account."
        )
        
        response.say(greeting_text, voice='alice', language=language)
        
        # Gather response
        gather = response.gather(
            input='speech',
            timeout=5,
            speech_timeout='auto',
            language=language,
            action=f"{settings.app_public_url}/voice/continue?session_id={session_id}&borrower_id={borrower_id}&state=VERIFY_IDENTITY"
        )
        
        # Timeout fallback
        response.say("I'll call you back later. Goodbye.")
        response.hangup()
        
        # Log the greeting
        log_call_turn(conn, session_id, 1, 'BOT', greeting_text, None, None, {})
        
        conn.close()
        return str(response)
        
    except Exception as e:
        logger.error(f"Error in outbound greeting: {e}")
        response.say("I'm experiencing technical difficulties. Goodbye.")
        response.hangup()
        return str(response)

def get_borrower_by_phone_id(conn, borrower_id: int):
    """Helper to get borrower by ID"""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM borrowers WHERE id = %s", (borrower_id,))
    return cursor.fetchone()