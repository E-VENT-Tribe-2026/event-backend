-- ============================================================
-- Migration: add_type_to_event_chats
-- Table: event_chats
-- Description: Adds a `type` enum column ('chat' | 'notification')
--              to distinguish user messages from system notifications.
--              sender_id is made nullable so system-generated notification
--              rows do not need a real user UUID.
-- ============================================================

-- 1. Create the enum type (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'chat_message_type') THEN
        CREATE TYPE chat_message_type AS ENUM ('chat', 'notification');
    END IF;
END;
$$;

-- 2. Add the type column (defaults to 'chat' so existing rows stay valid)
ALTER TABLE event_chats
    ADD COLUMN IF NOT EXISTS type chat_message_type NOT NULL DEFAULT 'chat';

-- 3. Make sender_id nullable so notification rows don't need a real user
ALTER TABLE event_chats
    ALTER COLUMN sender_id DROP NOT NULL;

-- 4. Allow the service role to insert notification rows (bypasses RLS).
--    Regular users are still governed by the existing "Participants can send
--    messages" policy which requires sender_id = auth.uid().
CREATE POLICY "Service role can insert notifications"
    ON event_chats
    FOR INSERT
    TO service_role
    WITH CHECK (type = 'notification');
