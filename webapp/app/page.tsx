"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type User = {
  id: string;
  login_name: string;
  display_name: string;
};

type ThreadItem = {
  thread_id: string;
  title: string | null;
  updated_at: string;
};

type MessageMetadata = {
  run_id?: string;
  agent_metadata?: Record<string, unknown>;
};

type MessageItem = {
  id: string;
  role: string;
  content_json: { text?: string };
  metadata_json?: MessageMetadata;
};

type RawMessageItem = {
  id: string;
  role: string;
  content_json?: { text?: string };
  content?: { text?: string };
  metadata_json?: MessageMetadata;
  metadata?: MessageMetadata;
};

type RawRunEvent = {
  id?: string;
  run_id?: string;
  event_type?: string;
  title?: string;
  summary?: string;
  status?: string;
  payload?: Record<string, unknown>;
  payload_json?: Record<string, unknown>;
};

type RunEvent = {
  id?: string;
  run_id?: string;
  event_type: string;
  title: string;
  summary: string;
  status: string;
  payload: Record<string, unknown>;
};

type RunEventBucket = {
  events: RunEvent[];
  loading: boolean;
  loaded: boolean;
  error: string;
  active: boolean;
};

type ArtifactItem = {
  id: string;
  title: string;
  mime_type: string;
  artifact_type?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:2026";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  return "请求失败，请稍后重试。";
}

function normalizeMessage(raw: RawMessageItem): MessageItem {
  const contentSource = raw.content_json || raw.content || {};
  const metadataSource = raw.metadata_json || raw.metadata || {};
  return {
    id: String(raw.id),
    role: String(raw.role),
    content_json: {
      text: typeof contentSource.text === "string" ? contentSource.text : ""
    },
    metadata_json: metadataSource
  };
}

function normalizeRunEvent(raw: RawRunEvent): RunEvent {
  const payloadSource = isRecord(raw.payload)
    ? raw.payload
    : isRecord(raw.payload_json)
      ? raw.payload_json
      : {};
  return {
    id: typeof raw.id === "string" ? raw.id : undefined,
    run_id: typeof raw.run_id === "string" ? raw.run_id : undefined,
    event_type: typeof raw.event_type === "string" ? raw.event_type : "process",
    title: typeof raw.title === "string" ? raw.title : "",
    summary: typeof raw.summary === "string" ? raw.summary : "",
    status: typeof raw.status === "string" ? raw.status : "info",
    payload: payloadSource
  };
}

function getRunKey(threadId: string, runId: string): string {
  return `${threadId}:${runId}`;
}

function isImageArtifact(artifact: ArtifactItem): boolean {
  if (artifact.mime_type.startsWith("image/")) return true;
  return /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(artifact.title);
}

function inferImageMimeType(artifact: ArtifactItem): string {
  if (artifact.mime_type.startsWith("image/")) {
    return artifact.mime_type;
  }
  const title = artifact.title.toLowerCase();
  if (title.endsWith(".png")) return "image/png";
  if (title.endsWith(".jpg") || title.endsWith(".jpeg")) return "image/jpeg";
  if (title.endsWith(".gif")) return "image/gif";
  if (title.endsWith(".webp")) return "image/webp";
  if (title.endsWith(".bmp")) return "image/bmp";
  if (title.endsWith(".svg")) return "image/svg+xml";
  return "image/png";
}

function formatRole(role: string): string {
  if (role === "user") return "你";
  if (role === "assistant") return "Fusion Agent";
  return role;
}

function formatRunStatus(status: string): string {
  if (status === "running") return "进行中";
  if (status === "completed") return "已完成";
  if (status === "error") return "失败";
  return "已记录";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    ...init
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [threads, setThreads] = useState<ThreadItem[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string>("");
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [runEventBuckets, setRunEventBuckets] = useState<Record<string, RunEventBucket>>({});
  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [artifactId, setArtifactId] = useState<string>("");
  const [artifactContentUrl, setArtifactContentUrl] = useState<string>("");
  const [artifactPreviewError, setArtifactPreviewError] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authForm, setAuthForm] = useState({
    login_name: "",
    password: "",
    display_name: ""
  });
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [authPending, setAuthPending] = useState(false);
  const [authError, setAuthError] = useState("");
  const [sendError, setSendError] = useState("");
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [artifactsLoading, setArtifactsLoading] = useState(false);

  const selectedThreadIdRef = useRef(selectedThreadId);
  const artifactIdRef = useRef(artifactId);
  const activeStreamThreadIdRef = useRef<string | null>(null);
  const messagesRequestIdRef = useRef(0);
  const artifactsRequestIdRef = useRef(0);
  const artifactObjectUrlRef = useRef("");

  const selectedThread = useMemo(
    () => threads.find((item) => item.thread_id === selectedThreadId) || null,
    [threads, selectedThreadId]
  );

  const selectedArtifact = useMemo(
    () => artifacts.find((item) => item.id === artifactId) || null,
    [artifacts, artifactId]
  );

  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  useEffect(() => {
    artifactIdRef.current = artifactId;
  }, [artifactId]);

  useEffect(() => {
    return () => {
      if (artifactObjectUrlRef.current) {
        URL.revokeObjectURL(artifactObjectUrlRef.current);
      }
    };
  }, []);

  useEffect(() => {
    api<{ user: User }>("/api/auth/me")
      .then((payload) => setUser(payload.user))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!user) return;
    void refreshThreads().catch(() => undefined);
  }, [user]);

  useEffect(() => {
    if (!selectedThreadId || !user) return;
    const keepLiveMessages = activeStreamThreadIdRef.current === selectedThreadId;
    setSendError("");
    clearArtifactPreview();
    setArtifacts([]);
    if (!keepLiveMessages) {
      setMessages([]);
      void refreshMessages(selectedThreadId).catch(() => undefined);
    }
    void refreshArtifacts(selectedThreadId).catch(() => undefined);
  }, [selectedThreadId, user]);

  function updateRunBucket(
    threadId: string,
    runId: string,
    updater: (bucket: RunEventBucket) => RunEventBucket
  ) {
    const key = getRunKey(threadId, runId);
    setRunEventBuckets((prev) => {
      const current = prev[key] || {
        events: [],
        loading: false,
        loaded: false,
        error: "",
        active: false
      };
      const next = updater(current);
      return { ...prev, [key]: next };
    });
  }

  function revokeArtifactObjectUrl() {
    if (!artifactObjectUrlRef.current) return;
    URL.revokeObjectURL(artifactObjectUrlRef.current);
    artifactObjectUrlRef.current = "";
  }

  function clearArtifactPreview() {
    revokeArtifactObjectUrl();
    setArtifactId("");
    setArtifactContentUrl("");
    setArtifactPreviewError("");
  }

  function upsertMessageByRunId(message: MessageItem, runId?: string) {
    setMessages((prev) => {
      const index = prev.findIndex(
        (item) => item.id === message.id || (runId ? item.metadata_json?.run_id === runId : false)
      );
      if (index === -1) {
        return [...prev, message];
      }
      const current = prev[index];
      const next = [...prev];
      next[index] = {
        ...current,
        ...message,
        content_json: message.content_json,
        metadata_json: {
          ...(current.metadata_json || {}),
          ...(message.metadata_json || {})
        }
      };
      return next;
    });
  }

  function appendAssistantChunk(runId: string, chunk: string) {
    setMessages((prev) => {
      const index = prev.findIndex((item) => item.metadata_json?.run_id === runId);
      if (index === -1) {
        return [
          ...prev,
          {
            id: `assistant-${runId}`,
            role: "assistant",
            content_json: { text: chunk },
            metadata_json: { run_id: runId }
          }
        ];
      }
      const current = prev[index];
      const next = [...prev];
      next[index] = {
        ...current,
        content_json: {
          text: `${current.content_json?.text || ""}${chunk}`
        },
        metadata_json: {
          ...(current.metadata_json || {}),
          run_id: runId
        }
      };
      return next;
    });
  }

  function startRun(threadId: string, runId: string, prompt: string) {
    const startEvent: RunEvent = {
      run_id: runId,
      event_type: "run_started",
      title: "开始执行",
      summary: prompt.slice(0, 120),
      status: "running",
      payload: {}
    };
    setExpandedThinking((prev) => ({
      ...prev,
      [getRunKey(threadId, runId)]: true
    }));
    updateRunBucket(threadId, runId, (bucket) => ({
      ...bucket,
      active: true,
      loaded: false,
      loading: false,
      error: "",
      events: bucket.events.some((event) => event.event_type === "run_started")
        ? bucket.events
        : [startEvent, ...bucket.events]
    }));
    upsertMessageByRunId(
      {
        id: `assistant-${runId}`,
        role: "assistant",
        content_json: { text: "" },
        metadata_json: { run_id: runId }
      },
      runId
    );
  }

  function appendRunEvent(threadId: string, runId: string, event: RunEvent) {
    updateRunBucket(threadId, runId, (bucket) => ({
      ...bucket,
      active: true,
      error: "",
      loading: false,
      events:
        event.id && bucket.events.some((item) => item.id === event.id)
          ? bucket.events
          : [...bucket.events, event]
    }));
  }

  function completeRun(threadId: string, runId: string, answerText: string) {
    const completeEvent: RunEvent = {
      run_id: runId,
      event_type: "message_completed",
      title: "回答完成",
      summary: answerText.slice(0, 120),
      status: "completed",
      payload: {}
    };
    updateRunBucket(threadId, runId, (bucket) => ({
      ...bucket,
      active: false,
      loaded: true,
      loading: false,
      error: "",
      events: bucket.events.some((event) => event.event_type === "message_completed")
        ? bucket.events
        : [...bucket.events, completeEvent]
    }));
  }

  async function refreshThreads() {
    const payload = await api<{ threads: ThreadItem[] }>("/api/threads");
    setThreads(payload.threads);
    setSelectedThreadId((current) => {
      if (current && payload.threads.some((thread) => thread.thread_id === current)) {
        return current;
      }
      return payload.threads[0]?.thread_id || "";
    });
  }

  async function refreshMessages(threadId: string) {
    const requestId = ++messagesRequestIdRef.current;
    setMessagesLoading(true);
    try {
      const payload = await api<{ messages: RawMessageItem[] }>(
        `/api/threads/${threadId}/messages`
      );
      if (
        selectedThreadIdRef.current !== threadId ||
        requestId !== messagesRequestIdRef.current ||
        activeStreamThreadIdRef.current === threadId
      ) {
        return;
      }
      setMessages(payload.messages.map(normalizeMessage));
    } finally {
      if (
        selectedThreadIdRef.current === threadId &&
        requestId === messagesRequestIdRef.current &&
        activeStreamThreadIdRef.current !== threadId
      ) {
        setMessagesLoading(false);
      }
    }
  }

  async function refreshArtifacts(threadId: string) {
    const requestId = ++artifactsRequestIdRef.current;
    setArtifactsLoading(true);
    try {
      const payload = await api<{ artifacts: ArtifactItem[] }>(
        `/api/threads/${threadId}/artifacts`
      );
      if (
        selectedThreadIdRef.current !== threadId ||
        requestId !== artifactsRequestIdRef.current
      ) {
        return;
      }
      setArtifacts(payload.artifacts);
      const currentArtifact = payload.artifacts.find(
        (item) => item.id === artifactIdRef.current
      );
      if (currentArtifact) {
        return;
      }
      if (payload.artifacts.length === 0) {
        clearArtifactPreview();
        return;
      }
      const previewArtifact =
        payload.artifacts.find((item) => isImageArtifact(item)) || payload.artifacts[0];
      await openArtifact(previewArtifact.id, previewArtifact);
    } finally {
      if (
        selectedThreadIdRef.current === threadId &&
        requestId === artifactsRequestIdRef.current
      ) {
        setArtifactsLoading(false);
      }
    }
  }

  async function ensureRunEventsLoaded(threadId: string, runId: string) {
    const key = getRunKey(threadId, runId);
    const existing = runEventBuckets[key];
    if (existing?.loading || existing?.loaded || existing?.active) return;
    updateRunBucket(threadId, runId, (bucket) => ({
      ...bucket,
      loading: true,
      error: ""
    }));
    try {
      const payload = await api<{ events: RawRunEvent[] }>(
        `/api/threads/${threadId}/runs/${runId}/events`
      );
      setRunEventBuckets((prev) => ({
        ...prev,
        [key]: {
          events: payload.events.map(normalizeRunEvent),
          loading: false,
          loaded: true,
          error: "",
          active: false
        }
      }));
    } catch (error) {
      updateRunBucket(threadId, runId, (bucket) => ({
        ...bucket,
        loading: false,
        error: getErrorMessage(error)
      }));
    }
  }

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthPending(true);
    setAuthError("");
    const path = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
    try {
      const payload = await api<{ user: User }>(path, {
        method: "POST",
        body: JSON.stringify(authForm)
      });
      setUser(payload.user);
    } catch (error) {
      setAuthError(getErrorMessage(error));
    } finally {
      setAuthPending(false);
    }
  }

  async function handleNewThread() {
    if (streaming) return null;
    setSendError("");
    setMessages([]);
    setArtifacts([]);
    clearArtifactPreview();
    return createThread();
  }

  async function createThread() {
    const payload = await api<{ thread: ThreadItem }>("/api/threads", {
      method: "POST",
      body: JSON.stringify({ title: "新会话" })
    });
    setThreads((prev) => [payload.thread, ...prev]);
    setSelectedThreadId(payload.thread.thread_id);
    return payload.thread;
  }

  async function handleSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!input.trim() || streaming) return;
    const messageText = input.trim();
    const optimisticUserMessage: MessageItem = {
      id: `local-${Date.now()}`,
      role: "user",
      content_json: { text: messageText }
    };

    let activeThreadId = selectedThreadId;
    let currentRunId = "";
    let hasRunStarted = false;

    setSendError("");
    setInput("");

    try {
      if (!activeThreadId) {
        setMessages([]);
        activeThreadId = (await createThread()).thread_id;
      }

      activeStreamThreadIdRef.current = activeThreadId;
      setStreaming(true);
      setMessages((prev) => [...prev, optimisticUserMessage]);

      const response = await fetch(`${API_BASE}/api/threads/${activeThreadId}/chat/stream`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: messageText })
      });

      if (!response.ok || !response.body) {
        throw new Error((await response.text()) || "流式请求失败");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const lines = chunk.split("\n");
          const eventLine = lines.find((line) => line.startsWith("event:"));
          const dataLine = lines.find((line) => line.startsWith("data:"));
          if (!eventLine || !dataLine) continue;

          const eventType = eventLine.replace("event:", "").trim();
          const data = JSON.parse(dataLine.replace("data:", "").trim()) as Record<
            string,
            unknown
          >;
          const eventRunId =
            typeof data.run_id === "string" && data.run_id ? data.run_id : currentRunId;

          if (eventRunId && !hasRunStarted) {
            currentRunId = eventRunId;
            hasRunStarted = true;
            startRun(activeThreadId, eventRunId, messageText);
          }

          if (eventType === "run_started") {
            if (eventRunId) {
              currentRunId = eventRunId;
              hasRunStarted = true;
              startRun(activeThreadId, eventRunId, messageText);
            }
            continue;
          }

          if (eventType === "message_chunk") {
            if (!eventRunId) continue;
            appendAssistantChunk(
              eventRunId,
              typeof data.content === "string" ? data.content : ""
            );
            continue;
          }

          if (eventType === "process") {
            if (!eventRunId) continue;
            appendRunEvent(
              activeThreadId,
              eventRunId,
              normalizeRunEvent({
                ...(data as RawRunEvent),
                run_id: eventRunId
              })
            );
            continue;
          }

          if (eventType === "message_completed") {
            if (!eventRunId) continue;
            const rawMessage = isRecord(data.message)
              ? (data.message as unknown as RawMessageItem)
              : null;
            const finalMessage = rawMessage ? normalizeMessage(rawMessage) : null;
            if (finalMessage) {
              upsertMessageByRunId(finalMessage, eventRunId);
              completeRun(activeThreadId, eventRunId, finalMessage.content_json?.text || "");
            } else {
              completeRun(activeThreadId, eventRunId, "");
            }
            activeStreamThreadIdRef.current = null;
            await Promise.all([
              refreshThreads(),
              refreshMessages(activeThreadId),
              refreshArtifacts(activeThreadId)
            ]);
          }
        }
      }
    } catch (error) {
      activeStreamThreadIdRef.current = null;
      setInput(messageText);
      setSendError(getErrorMessage(error));
      if (activeThreadId) {
        await Promise.all([
          refreshThreads().catch(() => undefined),
          refreshMessages(activeThreadId).catch(() => undefined),
          refreshArtifacts(activeThreadId).catch(() => undefined)
        ]);
      }
    } finally {
      activeStreamThreadIdRef.current = null;
      setStreaming(false);
    }
  }

  async function openArtifact(id: string, artifactOverride?: ArtifactItem) {
    const artifact = artifactOverride || artifacts.find((item) => item.id === id);
    if (!artifact) {
      clearArtifactPreview();
      return;
    }
    setArtifactId(id);
    setArtifactPreviewError("");
    if (!isImageArtifact(artifact)) {
      revokeArtifactObjectUrl();
      setArtifactContentUrl(`${API_BASE}/api/artifacts/${id}/content`);
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/artifacts/${id}/content`, {
        credentials: "include"
      });
      if (!response.ok) {
        throw new Error((await response.text()) || "产物预览加载失败");
      }
      const blob = await response.blob();
      const previewBlob = blob.type.startsWith("image/")
        ? blob
        : new Blob([blob], { type: inferImageMimeType(artifact) });
      revokeArtifactObjectUrl();
      const objectUrl = URL.createObjectURL(previewBlob);
      artifactObjectUrlRef.current = objectUrl;
      setArtifactContentUrl(objectUrl);
    } catch (error) {
      revokeArtifactObjectUrl();
      setArtifactContentUrl("");
      setArtifactPreviewError(getErrorMessage(error));
    }
  }

  if (!user) {
    return (
      <main className="auth-screen">
        <section className="auth-card panel">
          <h1>Fusion Agent</h1>
          <p className="muted">多用户 Agent、过程可视化、OpenSandbox Python 执行。</p>
          <form className="auth-form" onSubmit={handleAuthSubmit}>
            <input
              placeholder="登录名"
              value={authForm.login_name}
              onChange={(event) =>
                setAuthForm((prev) => ({
                  ...prev,
                  login_name: event.target.value
                }))
              }
            />
            {authMode === "register" ? (
              <input
                placeholder="显示名"
                value={authForm.display_name}
                onChange={(event) =>
                  setAuthForm((prev) => ({
                    ...prev,
                    display_name: event.target.value
                  }))
                }
              />
            ) : null}
            <input
              placeholder="密码"
              type="password"
              value={authForm.password}
              onChange={(event) =>
                setAuthForm((prev) => ({
                  ...prev,
                  password: event.target.value
                }))
              }
            />
            {authError ? <div className="inline-feedback error">{authError}</div> : null}
            <button type="submit" disabled={authPending}>
              {authPending
                ? "提交中..."
                : authMode === "login"
                  ? "登录"
                  : "注册"}
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={authPending}
              onClick={() =>
                setAuthMode((prev) => (prev === "login" ? "register" : "login"))
              }
            >
              {authMode === "login" ? "切换到注册" : "切换到登录"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar panel">
        <div className="panel-header">
          <div>
            <div className="muted">已登录</div>
            <strong>{user.display_name}</strong>
          </div>
          <button
            className="ghost-button"
            disabled={streaming}
            onClick={() => {
              void handleNewThread().catch((error) => setSendError(getErrorMessage(error)));
            }}
          >
            新建
          </button>
        </div>
        <div className="thread-list spaced-list">
          {threads.map((thread) => (
            <button
              key={thread.thread_id}
              type="button"
              disabled={streaming}
              className={`thread-item ${
                thread.thread_id === selectedThreadId ? "active" : ""
              }`}
              onClick={() => setSelectedThreadId(thread.thread_id)}
            >
              <div>{thread.title || "未命名会话"}</div>
              <div className="thread-time muted">
                {new Date(thread.updated_at).toLocaleString()}
              </div>
            </button>
          ))}
        </div>
      </aside>

      <section className="chat-panel panel">
        <header className="chat-header">
          <div>
            <div className="muted">产品聊天</div>
            <strong>{selectedThread?.title || "新会话"}</strong>
          </div>
          <div className="toolbar">
            <span className="status-badge">
              {streaming ? "Agent 正在思考" : messagesLoading ? "正在同步会话" : "准备就绪"}
            </span>
          </div>
        </header>

        <div className="messages">
          {!selectedThreadId && threads.length === 0 ? (
            <section className="empty-state">
              <strong>还没有会话</strong>
              <p className="muted">发送第一条消息后会自动创建新会话。</p>
            </section>
          ) : null}

          {messagesLoading && messages.length === 0 ? (
            <section className="empty-state">
              <p className="muted">正在加载消息...</p>
            </section>
          ) : null}

          {!messagesLoading && selectedThreadId && messages.length === 0 ? (
            <section className="empty-state">
              <strong>开始对话</strong>
              <p className="muted">提问后，Agent 会把关键过程折叠进对应回答里。</p>
            </section>
          ) : null}

          {messages.map((message) => {
            const runId = message.metadata_json?.run_id || "";
            const runKey = runId ? getRunKey(selectedThreadId, runId) : "";
            const bucket = runId ? runEventBuckets[runKey] : undefined;
            const thinkingOpen = runId
              ? (expandedThinking[runKey] ?? bucket?.active ?? false)
              : false;
            const visibleEvents = bucket?.events || [];
            const stepCount =
              visibleEvents.filter(
                (item) =>
                  item.event_type !== "run_started" &&
                  item.event_type !== "message_completed"
              ).length || visibleEvents.length;

            return (
              <article
                key={message.id}
                className={`message-card ${message.role === "user" ? "user" : "assistant"}`}
              >
                <div className="message-meta">{formatRole(message.role)}</div>

                {message.role === "assistant" && runId ? (
                  <details
                    className={`thinking-block ${bucket?.active ? "active" : ""}`}
                    open={thinkingOpen}
                    onToggle={(event) => {
                      const open = event.currentTarget.open;
                      setExpandedThinking((prev) => ({ ...prev, [runKey]: open }));
                      if (open) {
                        void ensureRunEventsLoaded(selectedThreadId, runId);
                      }
                    }}
                  >
                    <summary>
                      <span>思考过程</span>
                      <span className="thinking-summary">
                        {bucket?.loading
                          ? "加载中..."
                          : bucket?.active
                            ? "进行中"
                            : bucket?.error
                              ? "加载失败"
                              : stepCount > 0
                                ? `${stepCount} 条记录`
                                : "查看详情"}
                      </span>
                    </summary>

                    <div className="thinking-content">
                      {bucket?.loading ? (
                        <div className="muted">正在加载过程事件...</div>
                      ) : bucket?.error ? (
                        <div className="thinking-feedback">
                          <span className="inline-feedback error">{bucket.error}</span>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => {
                              void ensureRunEventsLoaded(selectedThreadId, runId);
                            }}
                          >
                            重试
                          </button>
                        </div>
                      ) : visibleEvents.length > 0 ? (
                        <div className="thinking-steps">
                          {visibleEvents.map((runEvent, index) => (
                            <article
                              key={runEvent.id || `${runEvent.event_type}-${index}`}
                              className="thinking-step"
                            >
                              <div className="thinking-step-head">
                                <strong>{runEvent.title || "过程事件"}</strong>
                                <span className="thinking-status">
                                  {formatRunStatus(runEvent.status)}
                                </span>
                              </div>
                              <div className="thinking-step-type">{runEvent.event_type}</div>
                              {runEvent.summary ? <p>{runEvent.summary}</p> : null}
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="muted">暂无过程事件。</div>
                      )}
                    </div>
                  </details>
                ) : null}

                {message.content_json?.text ? (
                  <div className="message-body">{message.content_json.text}</div>
                ) : message.role === "assistant" ? (
                  <div className="message-body assistant-placeholder">正在生成回答...</div>
                ) : null}
              </article>
            );
          })}
        </div>

        <footer className="composer">
          <form onSubmit={handleSendMessage}>
            {sendError ? <div className="inline-feedback error">{sendError}</div> : null}
            <textarea
              rows={4}
              disabled={streaming}
              placeholder="输入你的问题，让 Agent 规划步骤、调用工具、必要时编写 Python。"
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                if (sendError) setSendError("");
              }}
            />
            <button type="submit" disabled={streaming || !input.trim()}>
              {streaming ? "处理中..." : "发送"}
            </button>
          </form>
        </footer>
      </section>

      <aside className="artifact-panel panel">
        <div className="panel-header">
          <div>
            <div className="muted">Artifacts</div>
            <strong>{selectedArtifact?.title || "暂无预览"}</strong>
          </div>
        </div>

        <div className="artifact-list spaced-list">
          {artifactsLoading && artifacts.length === 0 ? (
            <div className="empty-state compact">
              <p className="muted">正在加载产物...</p>
            </div>
          ) : null}

          {!artifactsLoading && artifacts.length === 0 ? (
            <div className="empty-state compact">
              <p className="muted">当前会话还没有可预览的产物。</p>
            </div>
          ) : null}

          {artifacts.map((artifact) => (
            <button
              key={artifact.id}
              type="button"
              className="artifact-card"
              onClick={() => {
                void openArtifact(artifact.id);
              }}
            >
              <div>{artifact.title}</div>
              <div className="thread-time muted">{artifact.mime_type}</div>
            </button>
          ))}
        </div>

        {artifactPreviewError ? (
          <div className="inline-feedback error artifact-preview">{artifactPreviewError}</div>
        ) : null}

        {artifactContentUrl && selectedArtifact ? (
          <div className="artifact-preview">
            {isImageArtifact(selectedArtifact) ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={artifactContentUrl}
                alt={selectedArtifact.title}
                className="artifact-image"
              />
            ) : (
              <a href={artifactContentUrl} target="_blank" rel="noreferrer">
                打开文件
              </a>
            )}
          </div>
        ) : null}
      </aside>
    </main>
  );
}
