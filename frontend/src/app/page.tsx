"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type AgentEvent =
  | { kind: "tool_call"; tool: string; args: Record<string, unknown> }
  | { kind: "tool_result"; result: Record<string, unknown> }
  | { kind: "answer"; text: string };

type Turn =
  | { role: "user"; text: string }
  | { role: "agent"; events: AgentEvent[] };

// 尚书台排版：把模型的 Markdown 翻译成军报风格（金色强调 / 条目 / 描边表格）
const markdownComponents = {
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-2 leading-6 first:mt-0 last:mb-0">{children}</p>
  ),
  strong: ({ children }: { children?: ReactNode }) => (
    <b className="font-semibold text-[#e8c97a]">{children}</b>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h3
      className="mt-4 mb-2 border-l-2 border-[#c9a45c] pl-2 text-base font-semibold text-[#e8c97a]"
      style={{ fontFamily: "'KaiTi', 'STKaiti', serif" }}
    >
      {children}
    </h3>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h4 className="mt-3 mb-1.5 text-sm font-semibold text-[#e8c97a]">{children}</h4>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-2 list-disc space-y-1 pl-5 marker:text-[#c9a45c]">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-[#c9a45c]">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li className="leading-6">{children}</li>,
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="border border-[#8a6d3b]/60 bg-[#2b2214] px-2 py-1.5 text-left font-semibold text-[#e8c97a]">
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="border border-[#8a6d3b]/40 px-2 py-1.5 align-top text-[#e6d9bd]">
      {children}
    </td>
  ),
  hr: () => <hr className="my-3 border-[#8a6d3b]/40" />,
};

export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // 会话 id：本地持久化，同一浏览器始终同一存档槽
  useEffect(() => {
    let sid = localStorage.getItem("session_id");
    if (!sid) {
      sid = crypto.randomUUID();
      localStorage.setItem("session_id", sid);
    }
    setSessionId(sid);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function send() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: q }, { role: "agent", events: [] }]);

    const resp = await fetch("http://localhost:8000/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q, session_id: sessionId }),
    });

    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // 解析一条完整的 SSE 消息（event: + data: 行）
    function handleBlock(block: string) {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      const data = JSON.parse(dataLines.join("\n"));

      setTurns((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last.role !== "agent") return prev;
        if (event === "tool_call")
          last.events = [...last.events, { kind: "tool_call", tool: data.tool, args: data.args }];
        else if (event === "tool_result")
          last.events = [...last.events, { kind: "tool_result", result: data }];
        else if (event === "answer")
          last.events = [...last.events, { kind: "answer", text: data.text }];
        return next;
      });
    }

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop()!;            // ★ 不完整的尾巴留回 buffer
      blocks.forEach(handleBlock);
    }
    if (buffer.trim()) handleBlock(buffer);  // 流结束后的残余
    setBusy(false);
  }

  return (
    <main className="flex h-screen flex-col bg-[#161009]">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col p-6">
        {/* 标题：鎏金 + 楷体 */}
        <div className="mb-4 border-b border-[#8a6d3b]/40 pb-3 text-center">
          <h1
            className="text-2xl tracking-[0.35em] text-[#e8c97a]"
            style={{ fontFamily: "'KaiTi', 'STKaiti', 'SimSun', serif" }}
          >
            ❖ SLG 数值平衡军师 ❖
          </h1>

        <p className="mt-1">
          <span className="rounded-full border border-[#8a6d3b]/60 px-3 py-0.5 text-xs text-[#c9a45c]">
            <span
              className="rounded-full border border-[#8a6d3b]/60 px-3 py-0.5 text-xs text-[#c9a45c]"
              title={`存档槽：${sessionId}`}
            >
              兵符 · 军师已就位
            </span>
          </span>
        </p>


        </div>

        {/* 战报区 */}
        <div className="flex-1 space-y-4 overflow-y-auto rounded-lg border border-[#8a6d3b]/50 bg-[#1e1710] p-4">
          {turns.length === 0 && (
            <p className="text-sm text-[#8a7a5f]">
              试问：「张飞的骑兵打诸葛亮的器械谁赢，胜率多少」
            </p>
          )}
          {turns.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-lg border border-[#c9a45c]/70 bg-[#7d2a1e] px-4 py-2 text-sm text-[#f5e7c8]">
                  {turn.text}
                </div>
              </div>
            ) : (
              <div key={i} className="space-y-2">
                {turn.events.map((e, j) =>
                  e.kind === "tool_call" ? (
                    <div
                      key={j}
                      className="rounded border border-[#b08d3e]/60 bg-[#251c10] px-3 py-2 text-xs text-[#d9c089]"
                    >
                      ⚔ 调用军师之术 <b className="text-[#e8c97a]">{e.tool}</b>
                      <pre className="mt-1 whitespace-pre-wrap text-[11px] text-[#a8925f]">
                        {JSON.stringify(e.args, null, 2)}
                      </pre>
                    </div>
                  ) : e.kind === "tool_result" ? (
                    <details
                      key={j}
                      className="rounded border border-[#4f6b52] bg-[#1c2114] px-3 py-2 text-xs text-[#9fc0a8]"
                    >
                      <summary className="cursor-pointer font-medium">
                        📜 引擎军报（点开看原始数据）
                      </summary>
                      <pre className="mt-1 whitespace-pre-wrap text-[11px] text-[#8fae96]">
                        {JSON.stringify(e.result, null, 2)}
                      </pre>
                    </details>
                  ) : (
                    <div
                      key={j}
                      className="max-w-[90%] rounded-lg border border-[#6b5738] bg-[#2a2114] px-4 py-3 text-sm text-[#e6d9bd]"
                    >
                      <div
                        className="mb-2 flex items-center gap-2 border-b border-[#6b5738]/50 pb-1.5 text-xs text-[#c9a45c]"
                        style={{ fontFamily: "'KaiTi', 'STKaiti', serif" }}
                      >
                        📜 尚书台 · 军师回禀
                      </div>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {e.text}
                      </ReactMarkdown>
                    </div>
                  ),
                )}
              </div>
            ),
          )}
          {busy && <p className="animate-pulse text-xs text-[#c9a45c]">军师正在推演…</p>}
          <div ref={bottomRef} />
        </div>

        {/* 输入区 */}
        <div className="mt-4 flex gap-2">
          <input
            className="flex-1 rounded border border-[#8a6d3b]/60 bg-[#221a12] px-4 py-2 text-sm text-[#e6d9bd] outline-none placeholder:text-[#7a6a4f] focus:border-[#e8c97a]"
            value={input}
            placeholder="输入问题，如：张飞的骑兵打诸葛亮的器械谁赢"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            disabled={busy}
          />
          <button
            className="rounded border border-[#c9a45c] bg-[#7d2a1e] px-5 py-2 text-sm text-[#f5e7c8] hover:bg-[#963526] disabled:opacity-40"
            style={{ fontFamily: "'KaiTi', 'STKaiti', serif" }}
            onClick={send}
            disabled={busy}
          >
            出 兵
          </button>
        </div>
      </div>
    </main>
  );
}
