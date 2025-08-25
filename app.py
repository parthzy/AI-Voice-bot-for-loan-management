from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import logging
from contextlib import asynccontextmanager

from config import settings
from telephony import router as telephony_router
from scheduler import start_scheduler, stop_scheduler
import pytz

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown"""
    # Startup
    logger.info("Starting Loan Voice Bot application...")
    
    # Set timezone
    timezone = pytz.timezone(settings.timezone)
    logger.info(f"Using timezone: {settings.timezone}")
    
    # Start scheduler for outbound calls
    start_scheduler()
    logger.info("Scheduler started for outbound calls")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    stop_scheduler()

# Create FastAPI app
app = FastAPI(
    title="AI Voice Bot for Loan Collections",
    description="Voice-enabled loan management and collections system",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include telephony routes
app.include_router(telephony_router, prefix="/voice", tags=["telephony"])

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "AI Voice Bot for Loan Collections",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        from db import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {e}"
    
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": settings.get_current_time().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=settings.debug)