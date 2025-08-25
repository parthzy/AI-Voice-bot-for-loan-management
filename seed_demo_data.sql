USE loan_voice_bot;

-- Insert demo borrowers
INSERT INTO borrowers (name, phone_e164, email, loan_id, language_pref, consent_recorded_at) VALUES
('Rahul Kumar', '+919876543210', 'rahul.kumar@example.com', 'LOAN001', 'EN', NOW()),
('Priya Sharma', '+919876543211', 'priya.sharma@example.com', 'LOAN002', 'HI', NOW()),
('Amit Patel', '+919876543212', 'amit.patel@example.com', 'LOAN003', 'EN', NULL),
('Sunita Gupta', '+919876543213', 'sunita.gupta@example.com', 'LOAN004', 'HI', NOW()),
('Rajesh Singh', '+919876543214', 'rajesh.singh@example.com', 'LOAN005', 'EN', NOW());

-- Insert demo loans with different statuses
INSERT INTO loans (borrower_id, loan_id, principal, due_amount, due_date, status, days_past_due) VALUES
(1, 'LOAN001', 50000.00, 5200.00, DATE_SUB(CURDATE(), INTERVAL 10 DAY), 'OVERDUE', 10),
(2, 'LOAN002', 75000.00, 7800.00, DATE_SUB(CURDATE(), INTERVAL 30 DAY), 'OVERDUE', 30),
(3, 'LOAN003', 25000.00, 2600.00, DATE_ADD(CURDATE(), INTERVAL 5 DAY), 'CURRENT', 0),
(4, 'LOAN004', 100000.00, 10400.00, DATE_SUB(CURDATE(), INTERVAL 5 DAY), 'OVERDUE', 5),
(5, 'LOAN005', 60000.00, 6200.00, DATE_SUB(CURDATE(), INTERVAL 45 DAY), 'OVERDUE', 45);

-- Mark one borrower as DNC
UPDATE borrowers SET is_dnc = TRUE WHERE id = 5;
INSERT INTO dnc_requests (borrower_id, reason) VALUES (5, 'Customer requested no more calls');

-- Insert sample PTP promise
INSERT INTO ptp_promises (borrower_id, promise_date, amount) VALUES
(1, DATE_ADD(CURDATE(), INTERVAL 3 DAY), 2500.00);

-- Insert sample callback request
INSERT INTO callbacks (borrower_id, scheduled_at, reason) VALUES
(2, DATE_ADD(NOW(), INTERVAL 1 DAY), 'Customer requested callback tomorrow evening');