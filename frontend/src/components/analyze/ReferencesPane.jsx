import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import EmptyState from '../EmptyState.jsx';
import ReferenceModal from './ReferenceModal.jsx';

/**
 * Right pane — cited prior art + grounded RAG retrieval hits.
 *
 * Filtered by the currently active rejection (UX_RESEARCH §4.4: active
 * rejection drives all three panes). Each ref opens a modal with full text.
 */
export default function ReferencesPane({ result, activeRejectionId }) {
  const { t } = useTranslation();
  const [modalRef, setModalRef] = useState(null);

  if (!result) {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader title={t('analyze.pane_refs', { defaultValue: '引證 / References' })} />
        <div className="flex-1 overflow-y-auto p-4">
          <EmptyState
            icon="🔗"
            title={t('analyze.refs_empty_title', { defaultValue: '尚無引證' })}
            description={t('analyze.refs_empty_desc', {
              defaultValue: '分析完成後此處顯示 examiner 引證案 + RAG 命中的先前技術',
            })}
          />
        </div>
      </div>
    );
  }

  const rejections = result.oa.rejections || [];
  const activeRejection =
    rejections.find((r) => r.rejection_id === activeRejectionId) || rejections[0];

  const citedNos = activeRejection?.cited_prior_art || [];
  const hits = (result.related_prior_art || []).filter((h) => citedNos.includes(h.patent_no));

  return (
    <div className="flex h-full flex-col">
      <PaneHeader title={t('analyze.pane_refs', { defaultValue: '引證 / References' })}>
        {activeRejection && (
          <div className="mt-1 text-xs text-slate-500">
            <span className="font-mono">{activeRejection.rejection_type}</span> · claims{' '}
            {activeRejection.affected_claims.join(', ')}
          </div>
        )}
      </PaneHeader>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {citedNos.length > 0 && (
          <section>
            <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">
              引證案 / Cited prior art
            </div>
            <div className="flex flex-wrap gap-1">
              {citedNos.map((p) => (
                <span key={p} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs">
                  {p}
                </span>
              ))}
            </div>
          </section>
        )}

        <section>
          <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">
            RAG retrieval (Q6, Q7, Q14 grounding)
          </div>
          {hits.length === 0 && (
            <div className="rounded border border-dashed border-slate-300 bg-slate-50 p-3 text-xs text-slate-500">
              {t('analyze.refs_no_hits', {
                defaultValue: '此 rejection 沒有對應的 RAG 命中。',
              })}
            </div>
          )}
          <div className="space-y-2">
            {hits.map((h, i) => (
              <ReferenceCard key={`${h.patent_no}-${i}`} hit={h} onOpen={() => setModalRef(h)} />
            ))}
          </div>
        </section>
      </div>

      {modalRef && <ReferenceModal hit={modalRef} onClose={() => setModalRef(null)} />}
    </div>
  );
}

function PaneHeader({ title, children }) {
  return (
    <div className="sticky top-0 z-10 border-b bg-white/90 px-4 py-2 backdrop-blur">
      <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
      {children}
    </div>
  );
}

function ReferenceCard({ hit, onOpen }) {
  const excerpt = (hit.text || '').slice(0, 220);
  const truncated = (hit.text || '').length > 220;
  return (
    <div className="rounded border border-slate-200 bg-white p-3 text-xs">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <span className="font-mono font-medium text-slate-800">{hit.patent_no}</span>
          <span className="ml-1 text-slate-500">· {hit.section}</span>
        </div>
        <span className="font-mono text-slate-500">score {hit.score.toFixed(3)}</span>
      </div>
      <p className="mb-2 whitespace-pre-wrap text-slate-600">
        {excerpt}
        {truncated && '…'}
      </p>
      <button type="button" onClick={onOpen} className="text-indigo-600 hover:underline">
        Open full text →
      </button>
    </div>
  );
}
