import mysql.connector
from mysql.connector import pooling
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List
import json

from config import settings

logger = logging.getLogger(__name__)

# Create connection pool
connection_pool = pooling.MySQLConnectionPool(
    pool_name="loan_voice_bot_pool",
    pool_size=10,
    pool_reset_session=True,
    host=settings.mysql_host,
    port=settings.mysql_port,
    database=settings.mysql_db,
    user=settings.mysql_user,
    password=settings.mysql_password,
    charset='utf8mb4',
    autocommit=False
)

def get_db_connection():
    """Get database connection from pool"""
    try:
        return connection_pool.get_connection()
    except Exception as e:
        logger.error(f"Error getting database connection: {e}")
        raise

def get_borrower_by_phone(conn, phone_e164: str) -> Optional[Dict[str, Any]]:
    """Get borrower information by phone number"""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT b.*, l.due_amount, l.days_past_due, l.due_date, l.status as loan_status
            FROM borrowers b
            LEFT JOIN loans l ON b.id = l.borrower_id
            WHERE b.phone_e164 = %s
        """, (phone_e164,))
        return cursor.fetchone()
    finally:
        cursor.close()

def create_call_session(conn, call_sid: str, borrower_id: int, direction: str) -> int:
    """Create a new call session"""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO call_sessions (call_sid, borrower_id, direction, started_at, status)
            VALUES (%s, %s, %s, NOW(), 'INITIATED')
        """, (call_sid, borrower_id, direction))
        
        session_id = cursor.lastrowid
        conn.commit()
        
        # Log audit trail
        log_audit(conn, 'call_sessions', session_id, 'CREATED', {
            'call_sid': call_sid,
            'borrower_id': borrower_id,
            'direction': direction
        })
        
        return session_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating call session: {e}")
        raise
    finally:
        cursor.close()

def update_call_session(conn, session_id: int, current_state: str, 
                       verification_state: str = None, outcome: str = None):
    """Update call session state"""
    cursor = conn.cursor()
    try:
        if verification_state and outcome:
            cursor.execute("""
                UPDATE call_sessions 
                SET current_state = %s, verification_state = %s, outcome = %s
                WHERE id = %s
            """, (current_state, verification_state, outcome, session_id))
        elif verification_state:
            cursor.execute("""
                UPDATE call_sessions 
                SET current_state = %s, verification_state = %s
                WHERE id = %s
            """, (current_state, verification_state, session_id))
        else:
            cursor.execute("""
                UPDATE call_sessions 
                SET current_state = %s
                WHERE id = %s
            """, (current_state, session_id))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating call session: {e}")
        raise
    finally:
        cursor.close()

def log_call_turn(conn, session_id: int, turn_no: int, role: str, text: str, 
                  intent: str = None, sentiment: str = None, slots: dict = None):
    """Log a conversation turn"""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO call_logs (call_session_id, turn_no, role, text, intent, sentiment, slots)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (session_id, turn_no, role, text, intent, sentiment, json.dumps(slots) if slots else None))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error logging call turn: {e}")
        raise
    finally:
        cursor.close()

def save_ptp_promise(conn, borrower_id: int, session_id: int, promise_date: str, amount: float):
    """Save a promise to pay"""
    cursor = conn.cursor()
    try:
        # Parse promise_date if it's a string like "Friday"
        parsed_date = parse_promise_date(promise_date)
        
        cursor.execute("""
            INSERT INTO ptp_promises (borrower_id, call_session_id, promise_date, amount)
            VALUES (%s, %s, %s, %s)
        """, (borrower_id, session_id, parsed_date, amount))
        
        ptp_id = cursor.lastrowid
        conn.commit()
        
        log_audit(conn, 'ptp_promises', ptp_id, 'CREATED', {
            'borrower_id': borrower_id,
            'promise_date': promise_date,
            'amount': amount
        })
        
        return ptp_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving PTP: {e}")
        raise
    finally:
        cursor.close()

def mark_borrower_dnc(conn, borrower_id: int, session_id: int = None, reason: str = None):
    """Mark borrower as do-not-call"""
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE borrowers SET is_dnc = TRUE WHERE id = %s", (borrower_id,))
        
        cursor.execute("""
            INSERT INTO dnc_requests (borrower_id, call_session_id, reason)
            VALUES (%s, %s, %s)
        """, (borrower_id, session_id, reason or 'Customer request'))
        
        conn.commit()
        
        log_audit(conn, 'borrowers', borrower_id, 'MARKED_DNC', {
            'reason': reason,
            'session_id': session_id
        })
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error marking DNC: {e}")
        raise
    finally:
        cursor.close()

def schedule_callback(conn, borrower_id: int, session_id: int, scheduled_at: datetime, reason: str = None):
    """Schedule a callback"""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO callbacks (borrower_id, call_session_id, scheduled_at, reason)
            VALUES (%s, %s, %s, %s)
        """, (borrower_id, session_id, scheduled_at, reason))
        
        callback_id = cursor.lastrowid
        conn.commit()
        
        log_audit(conn, 'callbacks', callback_id, 'SCHEDULED', {
            'borrower_id': borrower_id,
            'scheduled_at': scheduled_at.isoformat(),
            'reason': reason
        })
        
        return callback_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Error scheduling callback: {e}")
        raise
    finally:
        cursor.close()

def get_overdue_borrowers(conn, limit: int = 50) -> List[Dict[str, Any]]:
    """Get borrowers with overdue loans for outbound calling"""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT b.id, b.name, b.phone_e164, b.language_pref,
                   l.due_amount, l.days_past_due, l.due_date,
                   COUNT(cs.id) as call_count
            FROM borrowers b
            JOIN loans l ON b.id = l.borrower_id
            LEFT JOIN call_sessions cs ON b.id = cs.borrower_id 
                AND cs.created_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)
            WHERE l.status = 'OVERDUE'
                AND b.is_dnc = FALSE
                AND l.days_past_due > 0
            GROUP BY b.id
            HAVING call_count < %s
            ORDER BY l.days_past_due DESC, l.due_amount DESC
            LIMIT %s
        """, (settings.max_call_attempts, limit))
        
        return cursor.fetchall()
    finally:
        cursor.close()

def log_audit(conn, entity: str, entity_id: int, action: str, meta_data: dict = None):
    """Log audit trail"""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO audit (entity, entity_id, action, meta_json)
            VALUES (%s, %s, %s, %s)
        """, (entity, entity_id, action, json.dumps(meta_data) if meta_data else None))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error logging audit: {e}")
        # Don't raise here to avoid breaking main functionality
    finally:
        cursor.close()

def parse_promise_date(date_str: str) -> date:
    """Parse various date formats from speech"""
    from datetime import datetime, timedelta
    
    today = datetime.now().date()
    date_str_lower = date_str.lower()
    
    # Handle relative dates
    if 'today' in date_str_lower:
        return today
    elif 'tomorrow' in date_str_lower:
        return today + timedelta(days=1)
    elif 'monday' in date_str_lower:
        days_ahead = 0 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return today + timedelta(days=days_ahead)
    elif 'friday' in date_str_lower:
        days_ahead = 4 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return today + timedelta(days=days_ahead)
    elif 'next week' in date_str_lower:
        return today + timedelta(days=7)
    elif 'next month' in date_str_lower:
        return today + timedelta(days=30)
    else:
        # Default to tomorrow if we can't parse
        return today + timedelta(days=1)