import React, { useEffect, useState } from 'react';

/**
 * Q16: 逐句律師標記。
 * - 每行顯示為 AI line（淡紫底）或 attorney line（淡綠底）。
 * - 律師可點 "Accept"（保留 AI 句、標記簽核）或 "Edit"（改寫，立刻翻成 attorney line）。
 * - 系統紀錄 each line 的 provenance：
 *     { source: 'ai'|'attorney', edited_from: <orig if edited>, accepted: bool, ts }
 *
 * 律師簽核時，他知道自己 endorse 了哪些 AI 句、改寫了哪些。這就是責任界線。
 */
export default function DraftEditor({ initialDraft, citationLookup, onAccept }) {
  const [lines, setLines] = useState(() => splitIntoLines(initialDraft));
  const [editingIdx, setEditingIdx] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [signed, setSigned] = useState(false);

  useEffect(() => { setLines(splitIntoLines(initialDraft)); setSigned(false); }, [initialDraft]);

  const allDecided = lines.every(l => l.accepted || l.source === 'attorney');

  function accept(i) {
    setLines(ls => ls.map((l, idx) => idx === i ? { ...l, accepted: true, ts: new Date().toISOString() } : l));
  }
  function startEdit(i) {
    setEditingIdx(i);
    setEditValue(lines[i].text);
  }
  function commitEdit() {
    setLines(ls => ls.map((l, idx) => idx === editingIdx ? {
      ...l,
      source: 'attorney',
      edited_from: l.source === 'ai' ? l.text : l.edited_from,
      text: editValue,
      accepted: true,
      ts: new Date().toISOString(),
    } : l));
    setEditingIdx(null);
  }
  function sign() {
    if (!allDecided) {
      alert('每一句都要先 Accept 或 Edit 才能簽核（Q16 律師責任界線）');
      return;
    }
    setSigned(true);
    onAccept && onAccept(lines);
  }

  return (
    <div className="space-y-2">
      <div className="text-xs text-slate-500 mb-2 flex gap-3">
        <span className="ai-line px-1">AI 生成</span>
        <span className="attorney-line px-1">律師改寫</span>
        <span className="ml-auto">
          {lines.filter(l => l.accepted || l.source === 'attorney').length}/{lines.length} 已決定
        </span>
      </div>

      {lines.map((l, i) => (
        <div key={i} className="group flex gap-2 items-start">
          <div className="w-6 text-xs text-slate-400 pt-1.5">{i + 1}.</div>
          {editingIdx === i ? (
            <div className="flex-1">
              <textarea
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                className="w-full border border-emerald-300 rounded p-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-300"
                rows={3}
              />
              <div className="mt-1 flex gap-2">
                <button onClick={commitEdit} className="text-xs px-2 py-1 bg-emerald-600 text-white rounded">儲存改寫</button>
                <button onClick={() => setEditingIdx(null)} className="text-xs px-2 py-1 bg-slate-200 rounded">取消</button>
              </div>
            </div>
          ) : (
            <>
              <div className={`flex-1 ${l.source === 'attorney' ? 'attorney-line' : 'ai-line'} ${l.accepted ? 'opacity-100' : 'opacity-90'} px-1 leading-7`}>
                <CitationHighlighter text={l.text} citationLookup={citationLookup} />
                {l.accepted && (
                  <span className="ml-2 text-xs text-emerald-600">
                    ✓ {l.source === 'attorney' ? '改寫' : '律師接受'}
                  </span>
                )}
              </div>
              <div className="opacity-0 group-hover:opacity-100 flex gap-1 transition">
                {!l.accepted && l.source === 'ai' && (
                  <button onClick={() => accept(i)} className="text-xs px-2 py-1 bg-indigo-600 text-white rounded">接受</button>
                )}
                <button onClick={() => startEdit(i)} className="text-xs px-2 py-1 bg-slate-200 rounded">改寫</button>
              </div>
            </>
          )}
        </div>
      ))}

      <div className="mt-4 pt-3 border-t flex justify-between items-center">
        <div className="text-xs text-slate-500">
          {signed ? '✅ 已簽核：律師確認所有句子的責任歸屬' : '簽核後此 draft 即可匯出（POC 不接 export）'}
        </div>
        <button
          disabled={!allDecided || signed}
          onClick={sign}
          className="px-4 py-2 rounded bg-emerald-600 text-white text-sm font-medium disabled:bg-slate-300"
        >
          {signed ? '已簽核' : '律師簽核'}
        </button>
      </div>
    </div>
  );
}

function splitIntoLines(text) {
  if (!text) return [];
  return text
    .split(/(?<=[.。！？!?])\s+/)
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => ({ text: s, source: 'ai', accepted: false, ts: null }));
}

/** Q14: render [GROUNDED_REF_N] as hover-able citation pill linking to source. */
function CitationHighlighter({ text, citationLookup }) {
  const parts = text.split(/(\[GROUNDED_REF_\d+\]|\[CITATION_REMOVED\])/g);
  return (
    <span>
      {parts.map((p, i) => {
        if (/^\[GROUNDED_REF_\d+\]$/.test(p)) {
          const hit = citationLookup?.[p];
          return (
            <span
              key={i}
              title={hit ? `${hit.patent_no} / ${hit.section}\n\n${hit.text}` : p}
              className="inline-block mx-0.5 px-1.5 py-0.5 rounded bg-indigo-100 border border-indigo-300 text-xs font-mono text-indigo-800 cursor-help"
            >
              {p}
            </span>
          );
        }
        if (p === '[CITATION_REMOVED]') {
          return (
            <span key={i} className="inline-block mx-0.5 px-1.5 py-0.5 rounded bg-rose-100 border border-rose-300 text-xs font-mono text-rose-800">
              CITATION_REMOVED
            </span>
          );
        }
        return <span key={i}>{p}</span>;
      })}
    </span>
  );
}
