import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link2 } from 'lucide-react';
import EmptyState from '../EmptyState.jsx';
import ReferenceModal from './ReferenceModal.jsx';
import { Button } from '../ui/button.jsx';
import { Badge } from '../ui/badge.jsx';

/**
 * Right pane — cited prior art + grounded RAG retrieval hits.
 *
 * Filtered by the currently active rejection (UX_RESEARCH §4.4: active
 * rejection drives all three panes). Each ref opens a modal with full text.
 *
 * ★2 跨窗格連動：`selectedCitation`（由 DraftEditor 點 grounded pill 觸發）會讓
 * 對應的 reference card 捲到可視範圍並短暫高亮。
 */
export default function ReferencesPane({ result, activeRejectionId, selectedCitation }) {
  const { t } = useTranslation();
  const [modalRef, setModalRef] = useState(null);
  const [highlightKey, setHighlightKey] = useState(null);
  const cardRefs = useRef({});

  const rejections = result?.oa?.rejections || [];
  const activeRejection =
    rejections.find((r) => r.rejection_id === activeRejectionId) || rejections[0];
  const citedNos = activeRejection?.cited_prior_art || [];
  const hits = (result?.related_prior_art || []).filter((h) => citedNos.includes(h.patent_no));

  // React to a citation pill click: find the matching card, scroll + highlight.
  useEffect(() => {
    if (!selectedCitation || !selectedCitation.patentNo) return;
    const match = hits.findIndex((h) => h.patent_no === selectedCitation.patentNo);
    if (match === -1) return;
    const key = `${selectedCitation.patentNo}-${match}`;
    const el = cardRefs.current[key];
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setHighlightKey(key);
    const id = window.setTimeout(() => setHighlightKey((cur) => (cur === key ? null : cur)), 2200);
    return () => window.clearTimeout(id);
    // selectedCitation.nonce ensures repeat clicks on the same pill re-fire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCitation?.nonce, selectedCitation?.patentNo]);

  if (!result) {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader title={t('analyze.pane_refs', { defaultValue: '引證 / References' })} />
        <div className="flex-1 overflow-y-auto p-4">
          <EmptyState
            icon={<Link2 className="mx-auto h-10 w-10 text-slate-400 dark:text-slate-500" strokeWidth={1.5} aria-hidden="true" />}
            title={t('analyze.refs_empty_title', { defaultValue: '尚無引證' })}
            description={t('analyze.refs_empty_desc', {
              defaultValue: '分析完成後此處顯示 examiner 引證案 + RAG 命中的先前技術',
            })}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PaneHeader title={t('analyze.pane_refs', { defaultValue: '引證 / References' })}>
        {activeRejection && (
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            <span className="font-mono">{activeRejection.rejection_type}</span> · claims{' '}
            {activeRejection.affected_claims.join(', ')}
          </div>
        )}
      </PaneHeader>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {citedNos.length > 0 && (
          <section>
            <div className="mb-1 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
              引證案 / Cited prior art
            </div>
            <div className="flex flex-wrap gap-1">
              {citedNos.map((p) => (
                <Badge key={p} tone="neutral" className="rounded font-mono">
                  {p}
                </Badge>
              ))}
            </div>
          </section>
        )}

        <section>
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
            RAG retrieval (Q6, Q7, Q14 grounding)
          </div>
          {hits.length === 0 && (
            <div className="rounded border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/50 p-3 text-xs text-slate-500 dark:text-slate-400">
              {t('analyze.refs_no_hits', {
                defaultValue: '此 rejection 沒有對應的 RAG 命中。',
              })}
            </div>
          )}
          <div className="space-y-2">
            {hits.map((h, i) => {
              const key = `${h.patent_no}-${i}`;
              return (
                <ReferenceCard
                  key={key}
                  hit={h}
                  highlighted={highlightKey === key}
                  cardRef={(el) => (cardRefs.current[key] = el)}
                  onOpen={() => setModalRef(h)}
                />
              );
            })}
          </div>
        </section>
      </div>

      {modalRef && <ReferenceModal hit={modalRef} onClose={() => setModalRef(null)} />}
    </div>
  );
}

function PaneHeader({ title, children }) {
  return (
    <div className="sticky top-0 z-10 border-b dark:border-slate-700 bg-white/90 dark:bg-slate-900/90 px-4 py-2 backdrop-blur">
      <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h2>
      {children}
    </div>
  );
}

function ReferenceCard({ hit, onOpen, highlighted, cardRef }) {
  const excerpt = (hit.text || '').slice(0, 220);
  const truncated = (hit.text || '').length > 220;
  return (
    <div
      ref={cardRef}
      className={`rounded border dark:border-slate-700 bg-white dark:bg-slate-900 p-3 text-xs transition-colors ${
        highlighted ? 'border-navy-400 ring-2 ring-navy-300' : 'border-slate-200 dark:border-slate-700'
      }`}
    >
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <span className="font-mono font-medium text-slate-800 dark:text-slate-200">{hit.patent_no}</span>
          <span className="ml-1 text-slate-500 dark:text-slate-400">· {hit.section}</span>
        </div>
        <span className="font-mono text-slate-500 dark:text-slate-400">score {hit.score.toFixed(3)}</span>
      </div>
      <p className="mb-2 whitespace-pre-wrap text-slate-600 dark:text-slate-300">
        {excerpt}
        {truncated && '…'}
      </p>
      <Button type="button" variant="link" size="xs" onClick={onOpen} className="px-0">
        Open full text →
      </Button>
    </div>
  );
}
