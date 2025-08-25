-- Create database
CREATE DATABASE IF NOT EXISTS loan_voice_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE loan_voice_bot;

-- Borrowers table
CREATE TABLE borrowers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    phone_e164 VARCHAR(20) NOT NULL UNIQUE,
    email VARCHAR(100),
    loan_id VARCHAR(50) NOT NULL UNIQUE,
    language_pref ENUM('EN', 'HI') DEFAULT 'EN',
    consent_recorded_at DATETIME,
    is_dnc BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_phone (phone_e164),
    INDEX idx_loan_id (loan_id),
    INDEX idx_dnc (is_dnc)
);

-- Loans table
CREATE TABLE loans (
    id INT PRIMARY KEY AUTO_INCREMENT,
    borrower_id INT NOT NULL,
    loan_id VARCHAR(50) NOT NULL UNIQUE,
    principal DECIMAL(15,2) NOT NULL,
    due_amount DECIMAL(15,2) NOT NULL,
    due_date DATE NOT NULL,
    status ENUM('CURRENT', 'OVERDUE', 'SETTLED', 'WRITTEN_OFF') DEFAULT 'CURRENT',
    days_past_due INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
    INDEX idx_borrower_id (borrower_id),
    INDEX idx_status_due (status, due_date),
    INDEX idx_dpd (days_past_due)
);

-- Call sessions table
CREATE TABLE call_sessions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    call_sid VARCHAR(100) NOT NULL UNIQUE,
    borrower_id INT,
    direction ENUM('INBOUND', 'OUTBOUND') NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME,
    status ENUM('INITIATED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'NO_ANSWER') DEFAULT 'INITIATED',
    verification_state ENUM('PENDING', 'VERIFIED', 'FAILED') DEFAULT 'PENDING',
    current_state VARCHAR(50) DEFAULT 'START',
    transcript_json TEXT,
    outcome VARCHAR(100),
    duration_seconds INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
    INDEX idx_call_sid (call_sid),
    INDEX idx_borrower_status (borrower_id, status),
    INDEX idx_started_at (started_at)
);

-- Call logs table
CREATE TABLE call_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    call_session_id INT NOT NULL,
    turn_no INT NOT NULL,
    role ENUM('BOT', 'CALLER') NOT NULL,
    text TEXT,
    intent VARCHAR(50),
    sentiment ENUM('POSITIVE', 'NEUTRAL', 'NEGATIVE'),
    slots JSON,
    confidence_score DECIMAL(5,3),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (call_session_id) REFERENCES call_sessions(id),
    INDEX idx_session_turn (call_session_id, turn_no),
    INDEX idx_intent (intent),
    INDEX idx_created_at (created_at)
);

-- Promise to pay table
CREATE TABLE ptp_promises (
    id INT PRIMARY KEY AUTO_INCREMENT,
    borrower_id INT NOT NULL,
    call_session_id INT,
    promise_date DATE NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    channel ENUM('VOICE', 'SMS', 'EMAIL') DEFAULT 'VOICE',
    status ENUM('ACTIVE', 'FULFILLED', 'BROKEN') DEFAULT 'ACTIVE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
    FOREIGN KEY (call_session_id) REFERENCES call_sessions(id),
    INDEX idx_borrower_date (borrower_id, promise_date),
    INDEX idx_status (status)
);

-- Do not call requests
CREATE TABLE dnc_requests (
    id INT PRIMARY KEY AUTO_INCREMENT,
    borrower_id INT NOT NULL,
    call_session_id INT,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
    FOREIGN KEY (call_session_id) REFERENCES call_sessions(id),
    INDEX idx_borrower_id (borrower_id)
);

-- Callback requests
CREATE TABLE callbacks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    borrower_id INT NOT NULL,
    call_session_id INT,
    scheduled_at DATETIME NOT NULL,
    reason TEXT,
    status ENUM('SCHEDULED', 'COMPLETED', 'CANCELLED') DEFAULT 'SCHEDULED',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
    FOREIGN KEY (call_session_id) REFERENCES call_sessions(id),
    INDEX idx_borrower_scheduled (borrower_id, scheduled_at),
    INDEX idx_status (status)
);

-- Audit log
CREATE TABLE audit (
    id INT PRIMARY KEY AUTO_INCREMENT,
    entity VARCHAR(50) NOT NULL,
    entity_id INT NOT NULL,
    action VARCHAR(50) NOT NULL,
    meta_json JSON,
    user_agent TEXT,
    ip_address VARCHAR(45),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_entity (entity, entity_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
);