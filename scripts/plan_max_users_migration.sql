-- Migration: Add max_users to budget_limits and normalize plan limits
ALTER TABLE budget_limits ADD COLUMN IF NOT EXISTS max_users INT DEFAULT 3;
UPDATE budget_limits SET max_users = 3 WHERE plan_type = 'start';
UPDATE budget_limits SET max_users = 5 WHERE plan_type = 'pro';
UPDATE budget_limits SET max_users = 10 WHERE plan_type = 'enterprise';
UPDATE budget_limits SET monthly_limit = 50 WHERE plan_type = 'start' AND monthly_limit = 10;
