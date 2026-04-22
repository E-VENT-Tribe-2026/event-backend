-- ============================================================
-- Migration: create_event_chats_table
-- Table: event_chats
-- Description: Stores chat messages scoped to an event.
--              Each message belongs to one event and one sender.
-- ============================================================

CREATE TABLE IF NOT EXISTS event_chats (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id    UUID        NOT NULL REFERENCES events(id)   ON DELETE CASCADE,
    sender_id   UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ──────────────────────────────────────────────────────────────────
-- Speed up the common query: fetch all messages for an event ordered by time
CREATE INDEX IF NOT EXISTS idx_event_chats_event_id_created_at
    ON event_chats (event_id, created_at ASC);

-- ── Row-Level Security ────────────────────────────────────────────────────────
ALTER TABLE event_chats ENABLE ROW LEVEL SECURITY;

-- Only event participants may read messages
CREATE POLICY "Participants can read event chat"
    ON event_chats
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1
            FROM event_participants ep
            WHERE ep.event_id = event_chats.event_id
              AND ep.user_id  = auth.uid()
        )
    );

-- Only event participants may send messages
CREATE POLICY "Participants can send messages"
    ON event_chats
    FOR INSERT
    WITH CHECK (
        sender_id = auth.uid()
        AND EXISTS (
            SELECT 1
            FROM event_participants ep
            WHERE ep.event_id = event_chats.event_id
              AND ep.user_id  = auth.uid()
        )
    );

-- Only the original sender may edit their own message
CREATE POLICY "Sender can edit own message"
    ON event_chats
    FOR UPDATE
    USING (sender_id = auth.uid())
    WITH CHECK (sender_id = auth.uid());

-- Only the original sender may delete their own message
CREATE POLICY "Sender can delete own message"
    ON event_chats
    FOR DELETE
    USING (sender_id = auth.uid());
