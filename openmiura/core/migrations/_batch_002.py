"""Migration batch 002 of 2.

Auto-generated split of openmiura/core/migrations.py.
Imported by openmiura/core/migrations/__init__.py and
concatenated into the public ``MIGRATIONS`` tuple.
"""

from __future__ import annotations

from openmiura.core.migrations._migration import Migration


BATCH_002_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        11,
        "voice_runtime_base",
        (
            """
            CREATE TABLE IF NOT EXISTS voice_sessions (
                voice_session_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT 'voice',
                user_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                locale TEXT NOT NULL DEFAULT 'es-ES',
                stt_provider TEXT NOT NULL DEFAULT 'simulated-stt',
                tts_provider TEXT NOT NULL DEFAULT 'simulated-tts',
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                closed_at REAL,
                last_transcript_text TEXT NOT NULL DEFAULT '',
                last_output_text TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_sessions_scope ON voice_sessions(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_sessions_status ON voice_sessions(status, updated_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voice_session_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'stt',
                text TEXT NOT NULL,
                confidence REAL,
                language TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_transcripts_session ON voice_transcripts(voice_session_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_voice_transcripts_scope ON voice_transcripts(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_outputs (
                output_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',
                voice_name TEXT NOT NULL DEFAULT 'assistant',
                audio_ref TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_outputs_session ON voice_outputs(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_outputs_scope ON voice_outputs(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_commands (
                command_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                command_name TEXT NOT NULL,
                command_payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'detected',
                requires_confirmation INTEGER NOT NULL DEFAULT 0,
                confirmed_by TEXT,
                confirmed_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_commands_session ON voice_commands(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_commands_status ON voice_commands(status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_commands_scope ON voice_commands(tenant_id, workspace_id, environment, updated_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS voice_sessions (
                voice_session_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT 'voice',
                user_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                locale TEXT NOT NULL DEFAULT 'es-ES',
                stt_provider TEXT NOT NULL DEFAULT 'simulated-stt',
                tts_provider TEXT NOT NULL DEFAULT 'simulated-tts',
                started_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                closed_at DOUBLE PRECISION,
                last_transcript_text TEXT NOT NULL DEFAULT '',
                last_output_text TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_sessions_scope ON voice_sessions(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_sessions_status ON voice_sessions(status, updated_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_transcripts (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'stt',
                text TEXT NOT NULL,
                confidence DOUBLE PRECISION,
                language TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_transcripts_session ON voice_transcripts(voice_session_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_voice_transcripts_scope ON voice_transcripts(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_outputs (
                output_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',
                voice_name TEXT NOT NULL DEFAULT 'assistant',
                audio_ref TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_outputs_session ON voice_outputs(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_outputs_scope ON voice_outputs(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_commands (
                command_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                command_name TEXT NOT NULL,
                command_payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'detected',
                requires_confirmation INTEGER NOT NULL DEFAULT 0,
                confirmed_by TEXT,
                confirmed_at DOUBLE PRECISION,
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_commands_session ON voice_commands(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_commands_status ON voice_commands(status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_commands_scope ON voice_commands(tenant_id, workspace_id, environment, updated_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS voice_commands",
            "DROP TABLE IF EXISTS voice_outputs",
            "DROP TABLE IF EXISTS voice_transcripts",
            "DROP TABLE IF EXISTS voice_sessions",
        ),
        (
            "DROP TABLE IF EXISTS voice_commands",
            "DROP TABLE IF EXISTS voice_outputs",
            "DROP TABLE IF EXISTS voice_transcripts",
            "DROP TABLE IF EXISTS voice_sessions",
        ),
    ),
    Migration(
        12,
        "pwa_foundation_operativa",
        (
            """
            CREATE TABLE IF NOT EXISTS app_installations (
                installation_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT 'pwa',
                device_label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                push_capable INTEGER NOT NULL DEFAULT 0,
                notification_permission TEXT NOT NULL DEFAULT 'default',
                deep_link_base TEXT NOT NULL DEFAULT '/ui/',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_seen_at REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_app_installations_scope ON app_installations(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_installations_status ON app_installations(status, updated_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS app_notifications (
                notification_id TEXT PRIMARY KEY,
                installation_id TEXT,
                category TEXT NOT NULL DEFAULT 'operator',
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                target_path TEXT NOT NULL DEFAULT '/ui/?tab=operator',
                status TEXT NOT NULL DEFAULT 'ready',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                delivered_at REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_app_notifications_installation ON app_notifications(installation_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_notifications_scope ON app_notifications(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS app_deep_links (
                link_token TEXT PRIMARY KEY,
                view TEXT NOT NULL DEFAULT 'operator',
                target_type TEXT NOT NULL DEFAULT 'record',
                target_id TEXT NOT NULL DEFAULT '',
                target_params_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                resolved_at REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_app_deep_links_scope ON app_deep_links(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_deep_links_status ON app_deep_links(status, updated_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS app_installations (
                installation_id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT 'pwa',
                device_label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                push_capable INTEGER NOT NULL DEFAULT 0,
                notification_permission TEXT NOT NULL DEFAULT 'default',
                deep_link_base TEXT NOT NULL DEFAULT '/ui/',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                last_seen_at DOUBLE PRECISION,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_app_installations_scope ON app_installations(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_installations_status ON app_installations(status, updated_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS app_notifications (
                notification_id TEXT PRIMARY KEY,
                installation_id TEXT,
                category TEXT NOT NULL DEFAULT 'operator',
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                target_path TEXT NOT NULL DEFAULT '/ui/?tab=operator',
                status TEXT NOT NULL DEFAULT 'ready',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                delivered_at DOUBLE PRECISION,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_app_notifications_installation ON app_notifications(installation_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_notifications_scope ON app_notifications(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS app_deep_links (
                link_token TEXT PRIMARY KEY,
                view TEXT NOT NULL DEFAULT 'operator',
                target_type TEXT NOT NULL DEFAULT 'record',
                target_id TEXT NOT NULL DEFAULT '',
                target_params_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                expires_at DOUBLE PRECISION,
                resolved_at DOUBLE PRECISION,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_app_deep_links_scope ON app_deep_links(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_deep_links_status ON app_deep_links(status, updated_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS app_deep_links",
            "DROP TABLE IF EXISTS app_notifications",
            "DROP TABLE IF EXISTS app_installations",
        ),
        (
            "DROP TABLE IF EXISTS app_deep_links",
            "DROP TABLE IF EXISTS app_notifications",
            "DROP TABLE IF EXISTS app_installations",
        ),
    ),
Migration(
    13,
    "live_canvas_core",
    (
        """
        CREATE TABLE IF NOT EXISTS canvas_documents (
            canvas_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_documents_scope ON canvas_documents(tenant_id, workspace_id, environment, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_documents_status ON canvas_documents(status, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_nodes (
            node_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            node_type TEXT NOT NULL DEFAULT 'note',
            label TEXT NOT NULL DEFAULT '',
            position_x REAL NOT NULL DEFAULT 0,
            position_y REAL NOT NULL DEFAULT 0,
            width REAL NOT NULL DEFAULT 240,
            height REAL NOT NULL DEFAULT 120,
            data_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_nodes_canvas ON canvas_nodes(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_nodes_scope ON canvas_nodes(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_edges (
            edge_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            edge_type TEXT NOT NULL DEFAULT 'default',
            data_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_edges_canvas ON canvas_edges(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_edges_scope ON canvas_edges(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_views (
            view_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT 'Default',
            layout_json TEXT NOT NULL DEFAULT '{}',
            filters_json TEXT NOT NULL DEFAULT '{}',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_views_canvas ON canvas_views(canvas_id, is_default DESC, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_views_scope ON canvas_views(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_presence (
            presence_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            user_key TEXT NOT NULL,
            cursor_x REAL NOT NULL DEFAULT 0,
            cursor_y REAL NOT NULL DEFAULT 0,
            selected_node_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_canvas ON canvas_presence(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_scope ON canvas_presence(tenant_id, workspace_id, environment, updated_at DESC)",
    ),
    (
        """
        CREATE TABLE IF NOT EXISTS canvas_documents (
            canvas_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_documents_scope ON canvas_documents(tenant_id, workspace_id, environment, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_documents_status ON canvas_documents(status, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_nodes (
            node_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            node_type TEXT NOT NULL DEFAULT 'note',
            label TEXT NOT NULL DEFAULT '',
            position_x DOUBLE PRECISION NOT NULL DEFAULT 0,
            position_y DOUBLE PRECISION NOT NULL DEFAULT 0,
            width DOUBLE PRECISION NOT NULL DEFAULT 240,
            height DOUBLE PRECISION NOT NULL DEFAULT 120,
            data_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_nodes_canvas ON canvas_nodes(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_nodes_scope ON canvas_nodes(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_edges (
            edge_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            edge_type TEXT NOT NULL DEFAULT 'default',
            data_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_edges_canvas ON canvas_edges(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_edges_scope ON canvas_edges(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_views (
            view_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT 'Default',
            layout_json TEXT NOT NULL DEFAULT '{}',
            filters_json TEXT NOT NULL DEFAULT '{}',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_views_canvas ON canvas_views(canvas_id, is_default DESC, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_views_scope ON canvas_views(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_presence (
            presence_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            user_key TEXT NOT NULL,
            cursor_x DOUBLE PRECISION NOT NULL DEFAULT 0,
            cursor_y DOUBLE PRECISION NOT NULL DEFAULT 0,
            selected_node_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_canvas ON canvas_presence(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_scope ON canvas_presence(tenant_id, workspace_id, environment, updated_at DESC)",
    ),
    (
        "DROP TABLE IF EXISTS canvas_presence",
        "DROP TABLE IF EXISTS canvas_views",
        "DROP TABLE IF EXISTS canvas_edges",
        "DROP TABLE IF EXISTS canvas_nodes",
        "DROP TABLE IF EXISTS canvas_documents",
    ),
    (
        "DROP TABLE IF EXISTS canvas_presence",
        "DROP TABLE IF EXISTS canvas_views",
        "DROP TABLE IF EXISTS canvas_edges",
        "DROP TABLE IF EXISTS canvas_nodes",
        "DROP TABLE IF EXISTS canvas_documents",
    ),
),
Migration(
    14,
    "canvas_operational_overlays",
    (
        """
        CREATE TABLE IF NOT EXISTS canvas_overlay_states (
            overlay_state_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            state_key TEXT NOT NULL DEFAULT 'default',
            toggles_json TEXT NOT NULL DEFAULT '{}',
            inspector_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_canvas_overlay_states_key ON canvas_overlay_states(canvas_id, state_key)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_overlay_states_scope ON canvas_overlay_states(tenant_id, workspace_id, environment, updated_at DESC)",
    ),
    (
        """
        CREATE TABLE IF NOT EXISTS canvas_overlay_states (
            overlay_state_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            state_key TEXT NOT NULL DEFAULT 'default',
            toggles_json TEXT NOT NULL DEFAULT '{}',
            inspector_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_canvas_overlay_states_key ON canvas_overlay_states(canvas_id, state_key)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_overlay_states_scope ON canvas_overlay_states(tenant_id, workspace_id, environment, updated_at DESC)",
    ),
    (
        "DROP TABLE IF EXISTS canvas_overlay_states",
    ),
    (
        "DROP TABLE IF EXISTS canvas_overlay_states",
    ),
),
Migration(
    15,
    "canvas_collaboration_shared_experience",
    (
        """
        CREATE TABLE IF NOT EXISTS canvas_comments (
            comment_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            node_id TEXT,
            body TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_comments_canvas ON canvas_comments(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_comments_scope ON canvas_comments(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            snapshot_kind TEXT NOT NULL DEFAULT 'manual',
            label TEXT NOT NULL DEFAULT '',
            view_id TEXT,
            share_token TEXT,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_snapshots_canvas ON canvas_snapshots(canvas_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_snapshots_scope ON canvas_snapshots(tenant_id, workspace_id, environment, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_presence_events (
            presence_event_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            user_key TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'presence',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_events_canvas ON canvas_presence_events(canvas_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_events_scope ON canvas_presence_events(tenant_id, workspace_id, environment, created_at DESC)",
    ),
    (
        """
        CREATE TABLE IF NOT EXISTS canvas_comments (
            comment_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            node_id TEXT,
            body TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_comments_canvas ON canvas_comments(canvas_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_comments_scope ON canvas_comments(tenant_id, workspace_id, environment, updated_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            snapshot_kind TEXT NOT NULL DEFAULT 'manual',
            label TEXT NOT NULL DEFAULT '',
            view_id TEXT,
            share_token TEXT,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_snapshots_canvas ON canvas_snapshots(canvas_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_snapshots_scope ON canvas_snapshots(tenant_id, workspace_id, environment, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS canvas_presence_events (
            presence_event_id TEXT PRIMARY KEY,
            canvas_id TEXT NOT NULL,
            user_key TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'presence',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at DOUBLE PRECISION NOT NULL,
            tenant_id TEXT,
            workspace_id TEXT,
            environment TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_events_canvas ON canvas_presence_events(canvas_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_canvas_presence_events_scope ON canvas_presence_events(tenant_id, workspace_id, environment, created_at DESC)",
    ),
    (
        "DROP TABLE IF EXISTS canvas_presence_events",
        "DROP TABLE IF EXISTS canvas_snapshots",
        "DROP TABLE IF EXISTS canvas_comments",
    ),
    (
        "DROP TABLE IF EXISTS canvas_presence_events",
        "DROP TABLE IF EXISTS canvas_snapshots",
        "DROP TABLE IF EXISTS canvas_comments",
    ),
),
    Migration(
        16,
        "phase8_packaging_builds",
        (
            """
            CREATE TABLE IF NOT EXISTS package_builds (
                build_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                label TEXT NOT NULL,
                version TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_package_builds_scope_created ON package_builds(tenant_id, workspace_id, environment, created_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS package_builds (
                build_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                label TEXT NOT NULL,
                version TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_package_builds_scope_created ON package_builds(tenant_id, workspace_id, environment, created_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS package_builds",
        ),
        (
            "DROP TABLE IF EXISTS package_builds",
        ),
    ),
    Migration(
        17,
        "phase9_operational_hardening",
        (
            """
            CREATE TABLE IF NOT EXISTS voice_audio_assets (
                asset_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                asset_kind TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                sample_rate_hz INTEGER NOT NULL DEFAULT 0,
                byte_count INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                storage_ref TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_audio_assets_session ON voice_audio_assets(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_audio_assets_scope ON voice_audio_assets(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_provider_calls (
                provider_call_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                provider_kind TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                latency_ms REAL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_provider_calls_session ON voice_provider_calls(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_provider_calls_scope ON voice_provider_calls(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS release_routing_decisions (
                decision_id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                canary_id TEXT NOT NULL DEFAULT '',
                baseline_release_id TEXT NOT NULL DEFAULT '',
                target_environment TEXT NOT NULL DEFAULT '',
                routing_key_hash TEXT NOT NULL,
                bucket REAL NOT NULL,
                selected_release_id TEXT NOT NULL,
                selected_version TEXT NOT NULL DEFAULT '',
                route_kind TEXT NOT NULL,
                success INTEGER,
                latency_ms REAL,
                cost_estimate REAL,
                observation_json TEXT NOT NULL DEFAULT '{}',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                tenant_id TEXT,
                workspace_id TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_release_routing_decisions_release ON release_routing_decisions(release_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_release_routing_decisions_scope ON release_routing_decisions(tenant_id, workspace_id, target_environment, created_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS voice_audio_assets (
                asset_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                asset_kind TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                sample_rate_hz INTEGER NOT NULL DEFAULT 0,
                byte_count INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                storage_ref TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_audio_assets_session ON voice_audio_assets(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_audio_assets_scope ON voice_audio_assets(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS voice_provider_calls (
                provider_call_id TEXT PRIMARY KEY,
                voice_session_id TEXT NOT NULL,
                provider_kind TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                latency_ms DOUBLE PRECISION,
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_voice_provider_calls_session ON voice_provider_calls(voice_session_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_voice_provider_calls_scope ON voice_provider_calls(tenant_id, workspace_id, environment, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS release_routing_decisions (
                decision_id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                canary_id TEXT NOT NULL DEFAULT '',
                baseline_release_id TEXT NOT NULL DEFAULT '',
                target_environment TEXT NOT NULL DEFAULT '',
                routing_key_hash TEXT NOT NULL,
                bucket DOUBLE PRECISION NOT NULL,
                selected_release_id TEXT NOT NULL,
                selected_version TEXT NOT NULL DEFAULT '',
                route_kind TEXT NOT NULL,
                success INTEGER,
                latency_ms DOUBLE PRECISION,
                cost_estimate DOUBLE PRECISION,
                observation_json TEXT NOT NULL DEFAULT '{}',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                completed_at DOUBLE PRECISION,
                tenant_id TEXT,
                workspace_id TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_release_routing_decisions_release ON release_routing_decisions(release_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_release_routing_decisions_scope ON release_routing_decisions(tenant_id, workspace_id, target_environment, created_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS release_routing_decisions",
            "DROP TABLE IF EXISTS voice_provider_calls",
            "DROP TABLE IF EXISTS voice_audio_assets",
        ),
        (
            "DROP TABLE IF EXISTS release_routing_decisions",
            "DROP TABLE IF EXISTS voice_provider_calls",
            "DROP TABLE IF EXISTS voice_audio_assets",
        ),
    ),
    Migration(
        18,
        "openclaw_adapter_v1",
        (
            """
            CREATE TABLE IF NOT EXISTS openclaw_runtimes (
                runtime_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                transport TEXT NOT NULL DEFAULT 'http',
                auth_secret_ref TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'registered',
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                allowed_agents_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                last_health_at REAL,
                last_health_status TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_openclaw_runtimes_scope_updated ON openclaw_runtimes(tenant_id, workspace_id, environment, updated_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS openclaw_dispatches (
                dispatch_id TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL,
                action TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                secret_ref TEXT NOT NULL DEFAULT '',
                latency_ms REAL,
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_openclaw_dispatches_runtime_created ON openclaw_dispatches(runtime_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_openclaw_dispatches_scope_created ON openclaw_dispatches(tenant_id, workspace_id, environment, created_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS openclaw_runtimes (
                runtime_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                transport TEXT NOT NULL DEFAULT 'http',
                auth_secret_ref TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'registered',
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                allowed_agents_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                last_health_at DOUBLE PRECISION,
                last_health_status TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_openclaw_runtimes_scope_updated ON openclaw_runtimes(tenant_id, workspace_id, environment, updated_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS openclaw_dispatches (
                dispatch_id TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL,
                action TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                secret_ref TEXT NOT NULL DEFAULT '',
                latency_ms DOUBLE PRECISION,
                created_by TEXT NOT NULL DEFAULT '',
                created_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_openclaw_dispatches_runtime_created ON openclaw_dispatches(runtime_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_openclaw_dispatches_scope_created ON openclaw_dispatches(tenant_id, workspace_id, environment, created_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS openclaw_dispatches",
            "DROP TABLE IF EXISTS openclaw_runtimes",
        ),
        (
            "DROP TABLE IF EXISTS openclaw_dispatches",
            "DROP TABLE IF EXISTS openclaw_runtimes",
        ),
    ),
    Migration(
        19,
        "openclaw_worker_concurrency",
        (
            """
            CREATE TABLE IF NOT EXISTS worker_leases (
                lease_key TEXT PRIMARY KEY,
                holder_id TEXT NOT NULL,
                lease_until REAL NOT NULL,
                heartbeat_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_worker_leases_scope_until ON worker_leases(tenant_id, workspace_id, environment, lease_until)",
            """
            CREATE TABLE IF NOT EXISTS idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                scope_kind TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'in_progress',
                holder_id TEXT NOT NULL DEFAULT '',
                expires_at REAL,
                result_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_idempotency_records_scope_expires ON idempotency_records(scope_kind, tenant_id, workspace_id, environment, expires_at)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS worker_leases (
                lease_key TEXT PRIMARY KEY,
                holder_id TEXT NOT NULL,
                lease_until DOUBLE PRECISION NOT NULL,
                heartbeat_at DOUBLE PRECISION NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_worker_leases_scope_until ON worker_leases(tenant_id, workspace_id, environment, lease_until)",
            """
            CREATE TABLE IF NOT EXISTS idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                scope_kind TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'in_progress',
                holder_id TEXT NOT NULL DEFAULT '',
                expires_at DOUBLE PRECISION,
                result_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_idempotency_records_scope_expires ON idempotency_records(scope_kind, tenant_id, workspace_id, environment, expires_at)",
        ),
        (
            "DROP TABLE IF EXISTS idempotency_records",
            "DROP TABLE IF EXISTS worker_leases",
        ),
        (
            "DROP TABLE IF EXISTS idempotency_records",
            "DROP TABLE IF EXISTS worker_leases",
        ),
    ),
    Migration(
        20,
        "openclaw_alert_workflows",
        (
            """
            CREATE TABLE IF NOT EXISTS runtime_alert_states (
                alert_key TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL,
                alert_code TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT '',
                workflow_status TEXT NOT NULL DEFAULT 'open',
                acked_by TEXT NOT NULL DEFAULT '',
                acked_at REAL,
                silence_until REAL,
                silenced_by TEXT NOT NULL DEFAULT '',
                silence_reason TEXT NOT NULL DEFAULT '',
                escalation_level INTEGER NOT NULL DEFAULT 0,
                escalation_target TEXT NOT NULL DEFAULT '',
                escalated_by TEXT NOT NULL DEFAULT '',
                escalated_at REAL,
                state_json TEXT NOT NULL DEFAULT '{}',
                observed_at REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_states_runtime ON runtime_alert_states(runtime_id, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_states_scope ON runtime_alert_states(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_states_status ON runtime_alert_states(workflow_status, updated_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS runtime_alert_states (
                alert_key TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL,
                alert_code TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT '',
                workflow_status TEXT NOT NULL DEFAULT 'open',
                acked_by TEXT NOT NULL DEFAULT '',
                acked_at DOUBLE PRECISION,
                silence_until DOUBLE PRECISION,
                silenced_by TEXT NOT NULL DEFAULT '',
                silence_reason TEXT NOT NULL DEFAULT '',
                escalation_level INTEGER NOT NULL DEFAULT 0,
                escalation_target TEXT NOT NULL DEFAULT '',
                escalated_by TEXT NOT NULL DEFAULT '',
                escalated_at DOUBLE PRECISION,
                state_json TEXT NOT NULL DEFAULT '{}',
                observed_at DOUBLE PRECISION NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_states_runtime ON runtime_alert_states(runtime_id, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_states_scope ON runtime_alert_states(tenant_id, workspace_id, environment, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_states_status ON runtime_alert_states(workflow_status, updated_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS runtime_alert_states",
        ),
        (
            "DROP TABLE IF EXISTS runtime_alert_states",
        ),
    ),
    Migration(
        21,
        "openclaw_alert_notification_dispatches",
        (
            """
            CREATE TABLE IF NOT EXISTS runtime_alert_notification_dispatches (
                notification_dispatch_id TEXT PRIMARY KEY,
                alert_key TEXT NOT NULL,
                runtime_id TEXT NOT NULL,
                alert_code TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                workflow_action TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT '',
                escalation_level INTEGER NOT NULL DEFAULT 0,
                delivery_status TEXT NOT NULL DEFAULT 'queued',
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                delivered_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_runtime ON runtime_alert_notification_dispatches(runtime_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_alert ON runtime_alert_notification_dispatches(alert_key, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_status ON runtime_alert_notification_dispatches(delivery_status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_scope ON runtime_alert_notification_dispatches(tenant_id, workspace_id, environment, created_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS runtime_alert_notification_dispatches (
                notification_dispatch_id TEXT PRIMARY KEY,
                alert_key TEXT NOT NULL,
                runtime_id TEXT NOT NULL,
                alert_code TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                workflow_action TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT '',
                escalation_level INTEGER NOT NULL DEFAULT 0,
                delivery_status TEXT NOT NULL DEFAULT 'queued',
                request_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                delivered_at DOUBLE PRECISION,
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_runtime ON runtime_alert_notification_dispatches(runtime_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_alert ON runtime_alert_notification_dispatches(alert_key, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_status ON runtime_alert_notification_dispatches(delivery_status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_alert_notification_dispatches_scope ON runtime_alert_notification_dispatches(tenant_id, workspace_id, environment, created_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS runtime_alert_notification_dispatches",
        ),
        (
            "DROP TABLE IF EXISTS runtime_alert_notification_dispatches",
        ),
    ),
    Migration(
        22,
        "runtime_governance_policy_versions",
        (
            """
            CREATE TABLE IF NOT EXISTS runtime_governance_policy_versions (
                version_id TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL,
                policy_kind TEXT NOT NULL DEFAULT 'alert_governance',
                version_no INTEGER NOT NULL DEFAULT 1,
                version_label TEXT NOT NULL DEFAULT '',
                change_kind TEXT NOT NULL DEFAULT 'activation',
                status TEXT NOT NULL DEFAULT 'active',
                based_on_version_id TEXT NOT NULL DEFAULT '',
                rollback_of_version_id TEXT NOT NULL DEFAULT '',
                activated_by TEXT NOT NULL DEFAULT '',
                activation_reason TEXT NOT NULL DEFAULT '',
                policy_json TEXT NOT NULL DEFAULT '{}',
                previous_policy_json TEXT NOT NULL DEFAULT '{}',
                diff_json TEXT NOT NULL DEFAULT '{}',
                simulation_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                activated_at REAL,
                updated_at REAL NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runtime_governance_policy_versions_runtime ON runtime_governance_policy_versions(runtime_id, policy_kind, version_no DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_governance_policy_versions_status ON runtime_governance_policy_versions(status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_governance_policy_versions_scope ON runtime_governance_policy_versions(tenant_id, workspace_id, environment, updated_at DESC)",
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS runtime_governance_policy_versions (
                version_id TEXT PRIMARY KEY,
                runtime_id TEXT NOT NULL,
                policy_kind TEXT NOT NULL DEFAULT 'alert_governance',
                version_no INTEGER NOT NULL DEFAULT 1,
                version_label TEXT NOT NULL DEFAULT '',
                change_kind TEXT NOT NULL DEFAULT 'activation',
                status TEXT NOT NULL DEFAULT 'active',
                based_on_version_id TEXT NOT NULL DEFAULT '',
                rollback_of_version_id TEXT NOT NULL DEFAULT '',
                activated_by TEXT NOT NULL DEFAULT '',
                activation_reason TEXT NOT NULL DEFAULT '',
                policy_json TEXT NOT NULL DEFAULT '{}',
                previous_policy_json TEXT NOT NULL DEFAULT '{}',
                diff_json TEXT NOT NULL DEFAULT '{}',
                simulation_json TEXT NOT NULL DEFAULT '{}',
                created_at DOUBLE PRECISION NOT NULL,
                activated_at DOUBLE PRECISION,
                updated_at DOUBLE PRECISION NOT NULL,
                tenant_id TEXT,
                workspace_id TEXT,
                environment TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_runtime_governance_policy_versions_runtime ON runtime_governance_policy_versions(runtime_id, policy_kind, version_no DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_governance_policy_versions_status ON runtime_governance_policy_versions(status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_runtime_governance_policy_versions_scope ON runtime_governance_policy_versions(tenant_id, workspace_id, environment, updated_at DESC)",
        ),
        (
            "DROP TABLE IF EXISTS runtime_governance_policy_versions",
        ),
        (
            "DROP TABLE IF EXISTS runtime_governance_policy_versions",
        ),
    ),
)
