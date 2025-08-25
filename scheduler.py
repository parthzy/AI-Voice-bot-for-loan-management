from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import requests
from datetime import datetime
import pytz

from config import settings
from db import get_db_connection, get_overdue_borrowers

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def start_scheduler():
    """Start the background scheduler"""
    # Schedule outbound calls during business hours
    scheduler.add_job(
        func=make_outbound_calls,
        trigger=CronTrigger(
            hour='9-18',  # 9 AM to 6 PM
            minute='*/30',  # Every 30 minutes
            timezone=settings.timezone
        ),
        id='outbound_calls',
        name='Make outbound collection calls',
        replace_existing=True
    )
    
    # Schedule daily cleanup
    scheduler.add_job(
        func=daily_cleanup,
        trigger=CronTrigger(
            hour=23,  # 11 PM
            minute=0,
            timezone=settings.timezone
        ),
        id='daily_cleanup',
        name='Daily cleanup tasks',
        replace_existing=True
    )
    
    # Schedule reminder SMS (stub)
    scheduler.add_job(
        func=send_reminder_sms,
        trigger=CronTrigger(
            hour=10,  # 10 AM
            minute=0,
            timezone=settings.timezone
        ),
        id='reminder_sms',
        name='Send daily reminder SMS',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Background scheduler started")

def stop_scheduler():
    """Stop the background scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped")

def make_outbound_calls():
    """Make outbound collection calls to overdue borrowers"""
    logger.info("Starting outbound calling job")
    
    # Check if within calling hours
    if not settings.is_calling_hours():
        logger.info("Outside calling hours, skipping outbound calls")
        return
    
    try:
        conn = get_db_connection()
        
        # Get borrowers to call (limit to 10 per batch)
        borrowers = get_overdue_borrowers(conn, limit=10)
        logger.info(f"Found {len(borrowers)} borrowers for outbound calling")
        
        for borrower in borrowers:
            try:
                # Make API call to initiate outbound call
                response = requests.post(
                    f"{settings.app_public_url}/voice/outbound",
                    json={"borrower_id": borrower['id']},
                    timeout=30
                )
                
                if response.status_code == 200:
                    logger.info(f"Initiated outbound call to borrower {borrower['id']}")
                else:
                    logger.warning(f"Failed to initiate call to borrower {borrower['id']}: {response.text}")
                    
            except Exception as e:
                logger.error(f"Error initiating call to borrower {borrower['id']}: {e}")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Error in outbound calling job: {e}")

def daily_cleanup():
    """Daily cleanup and maintenance tasks"""
    logger.info("Starting daily cleanup job")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Clean up old call logs (older than 90 days)
        cursor.execute("""
            DELETE FROM call_logs 
            WHERE created_at < DATE_SUB(NOW(), INTERVAL 90 DAY)
        """)
        deleted_logs = cursor.rowcount
        
        # Update loan statuses based on payment dates
        cursor.execute("""
            UPDATE loans 
            SET days_past_due = DATEDIFF(CURDATE(), due_date),
                status = CASE 
                    WHEN DATEDIFF(CURDATE(), due_date) > 0 THEN 'OVERDUE'
                    ELSE 'CURRENT'
                END
            WHERE status NOT IN ('SETTLED', 'WRITTEN_OFF')
        """)
        updated_loans = cursor.rowcount
        
        # Mark broken promises
        cursor.execute("""
            UPDATE ptp_promises 
            SET status = 'BROKEN'
            WHERE status = 'ACTIVE' 
                AND promise_date < CURDATE()
        """)
        broken_promises = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        logger.info(f"Daily cleanup completed: {deleted_logs} logs deleted, "
                   f"{updated_loans} loans updated, {broken_promises} promises marked broken")
        
    except Exception as e:
        logger.error(f"Error in daily cleanup job: {e}")

def send_reminder_sms():
    """Send reminder SMS to borrowers (stub implementation)"""
    logger.info("Starting reminder SMS job (stub)")
    
    try:
        conn = get_db_connection()
        
        # Get borrowers who need SMS reminders
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT b.name, b.phone_e164, l.due_amount, l.days_past_due
            FROM borrowers b
            JOIN loans l ON b.id = l.borrower_id
            WHERE l.status = 'OVERDUE'
                AND b.is_dnc = FALSE
                AND l.days_past_due BETWEEN 1 AND 30
            LIMIT 50
        """)
        
        borrowers = cursor.fetchall()
        
        for borrower in borrowers:
            # In a real implementation, you would send SMS via Twilio
            logger.info(f"Would send SMS reminder to {borrower['phone_e164']} "
                       f"for ₹{borrower['due_amount']:,.2f} ({borrower['days_past_due']} days overdue)")
        
        conn.close()
        logger.info(f"SMS reminder job completed for {len(borrowers)} borrowers")
        
    except Exception as e:
        logger.error(f"Error in SMS reminder job: {e}")