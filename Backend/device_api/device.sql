-- device.sql
DROP TABLE IF EXISTS device;

CREATE TABLE device (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    serial_number TEXT UNIQUE NOT NULL,
    user_id INTEGER,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- FOREIGN KEY (user_id) REFERENCES user(id) --You cannot register a device to a user until at least one user exists
);
