"use client";

import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";

export interface VersionTagsMap {
  [versionId: string]: string | null;
}

interface MessageListProps {
  messages: ChatMessage[];
  sessionId: string;
  versionTags?: VersionTagsMap;
  /** version_id -> source; rerun versions do not require naming */
  versionSources?: Record<string, string>;
  onVersionTagged?: (versionId: string, tag: string) => void;
}

export function MessageList({
  messages,
  sessionId,
  versionTags = {},
  versionSources = {},
  onVersionTagged,
}: MessageListProps) {
  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          message={msg}
          sessionId={sessionId}
          versionTags={versionTags}
          versionSources={versionSources}
          onVersionTagged={onVersionTagged}
        />
      ))}
    </div>
  );
}
