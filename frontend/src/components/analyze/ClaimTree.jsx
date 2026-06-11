import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '../ui/badge.jsx';

/**
 * Claim dependency tree (UX_RESEARCH §4.1 + §5 #2 must-have).
 *
 * Vertical tree, color-coded by rejection status, mounted inside the left
 * (Input) pane between the OA text input and the redaction preview. The
 * design intent maps 1-to-1 onto the universally-validated ClaimMaster /
 * Patlytics / Solve pattern: roots = independent claims, branches indented
 * by dependency depth, nodes colored by whether the claim is rejected,
 * cascade-risk (its parent is rejected), or clean.
 *
 * Backend produces `claim_tree: list[ClaimNode]` on `AnalysisResponse`
 * (see backend/shared/models.py). Each node carries:
 *   { claim_no, depends_on, parents, text, is_independent, depth }
 *
 * Rendering rules:
 *   - Red    (rose-100/700) — claim_no ∈ ANY rejection.affected_claims.
 *                              Chip on the right shows the rejection_type.
 *   - Yellow (amber-100/700) — claim's parent (depends_on or any in parents)
 *                              is itself rejected → cascade risk. TIPO
 *                              practice: when an independent claim falls,
 *                              its dependents fall along with it unless
 *                              you separately argue dependent-only
 *                              patentability.
 *   - Green  (emerald-50/700) — clean.
 *   - Independent claims get a thick navy-500 left border so the eye
 *     instantly catches "this is a root".
 *   - The currently-active rejection's affected claims get a subtle
 *     navy ring so the cross-pane focus is visually connected.
 *
 * Click behaviour: if the row corresponds to a rejected claim, calling
 * `onClaimClick(claim_no)` lets the parent pivot the active rejection.
 * Clean / cascade rows are non-interactive.
 *
 * Edge cases handled:
 *   - `claimTree` is `undefined` or `[]` → render nothing (graceful no-op).
 *   - `rejections` is `undefined` → all claims rendered as clean.
 *   - A ClaimNode's `text` is empty → row still renders with the badge so
 *     numbering stays consistent.
 *   - depth is capped at 6 levels of visual indent (deeper still computes,
 *     just visually clamps so we don't run off the pane).
 */
export default function ClaimTree({
  claimTree = [],
  rejections = [],
  activeRejectionId = null,
  onClaimClick = null,
}) {
  const { t } = useTranslation();

  // Build a claim_no → rejection lookup so each row needs O(1) work.
  // Memoised because `rejections` is stable across drafts-pane tab switches
  // (changing `activeRejectionId` is what re-renders this component).
  const claimToRejection = useMemo(() => {
    const out = new Map();
    rejections.forEach((r) => {
      (r.affected_claims || []).forEach((cn) => {
        // First rejection wins for the chip label (the visual "tag");
        // a claim hit by multiple rejections is rare and the cascade
        // colour communicates "look closer at this claim" anyway.
        if (!out.has(cn)) out.set(cn, r);
      });
    });
    return out;
  }, [rejections]);

  // Pre-compute cascade risk for every claim by walking up its parent
  // chain. Cheap (<1ms for 50 claims) and avoids re-walking per render.
  const cascadeSet = useMemo(() => {
    const byNo = new Map(claimTree.map((n) => [n.claim_no, n]));
    const out = new Set();
    for (const node of claimTree) {
      if (claimToRejection.has(node.claim_no)) continue; // already red
      // Walk all parent links (including multi-parents), cap depth as a
      // belt-and-braces guard against any malformed cycle in the graph.
      const stack = [...(node.parents || [])];
      const seen = new Set();
      let hops = 0;
      while (stack.length && hops < 32) {
        hops += 1;
        const p = stack.pop();
        if (seen.has(p)) continue;
        seen.add(p);
        if (claimToRejection.has(p)) {
          out.add(node.claim_no);
          break;
        }
        const parentNode = byNo.get(p);
        if (parentNode) stack.push(...(parentNode.parents || []));
      }
    }
    return out;
  }, [claimTree, claimToRejection]);

  if (!claimTree || claimTree.length === 0) return null;

  const activeRejection =
    activeRejectionId && rejections.find((r) => r.rejection_id === activeRejectionId);
  const activeClaimNos = new Set(activeRejection?.affected_claims || []);

  // ASCII layout intent:
  //   [#1] independent  ──────────────  ▌  cooling system, comprising...   [§103]
  //     [#2] dep. 1     ────────────                  base plate copper    [§103]
  //       [#3] dep. 2   ──────────────────  embedded sensors               (clean)
  //   [#10] independent ─────────────  ▌  charging management system...
  //     [#11] dep. 10   ───────────                  ...                   (cascade)
  return (
    <div
      className="rounded-lg border bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
      data-testid="claim-tree"
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          {t('analyze.claim_tree.title', { defaultValue: '請求項依賴樹 / Claim tree' })}{' '}
          <span className="text-xs text-slate-500 dark:text-slate-400">
            ({claimTree.length} {t('analyze.claim_tree.claims', { defaultValue: 'claims' })})
          </span>
        </h3>
        <Legend t={t} />
      </div>
      <ul className="space-y-1">
        {claimTree.map((node) => {
          const rej = claimToRejection.get(node.claim_no) || null;
          const cascade = !rej && cascadeSet.has(node.claim_no);
          const active = activeClaimNos.has(node.claim_no);
          return (
            <ClaimRow
              key={node.claim_no}
              node={node}
              rejection={rej}
              cascade={cascade}
              active={active}
              onClaimClick={onClaimClick}
            />
          );
        })}
      </ul>
    </div>
  );
}

function ClaimRow({ node, rejection, cascade, active, onClaimClick }) {
  // Cap visual indent at 6 levels so very deep dependency chains don't
  // spill off the narrow Input pane. The actual depth is still in the
  // ClaimNode if a downstream consumer cares.
  const visualDepth = Math.min(node.depth || 0, 6);
  const indentPx = visualDepth * 12;

  // Tone palette — order matters: red beats cascade-yellow beats clean.
  // `badgeTone` maps to the shared STATUS_TONE keys (Badge component); the
  // row container keeps its own bg+hover classes because a Badge can't carry
  // the full-row hover affordance.
  let toneClasses =
    'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40';
  let badgeTone = 'success';
  let toneLabel = 'clean';
  if (rejection) {
    toneClasses =
      'bg-rose-50 dark:bg-rose-950/40 text-rose-900 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/40 cursor-pointer';
    badgeTone = 'error';
    toneLabel = 'rejected';
  } else if (cascade) {
    toneClasses =
      'bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40';
    badgeTone = 'warning';
    toneLabel = 'cascade';
  }

  const independentBorder = node.is_independent
    ? 'border-l-4 border-l-navy-500'
    : 'border-l-4 border-l-transparent';
  const activeRing = active ? 'ring-2 ring-navy-300 ring-offset-0' : '';

  const handleClick = () => {
    if (rejection && onClaimClick) {
      onClaimClick(node.claim_no, rejection.rejection_id);
    }
  };

  const preview = (node.text || '').slice(0, 40);
  const hasMore = (node.text || '').length > 40;

  return (
    <li>
      <div
        className={`flex items-center gap-2 rounded ${independentBorder} ${activeRing} ${toneClasses} px-2 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500`}
        style={{ marginLeft: indentPx }}
        onClick={handleClick}
        role={rejection ? 'button' : undefined}
        tabIndex={rejection ? 0 : undefined}
        onKeyDown={(e) => {
          if (rejection && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            handleClick();
          }
        }}
        data-tone={toneLabel}
        data-claim-no={node.claim_no}
      >
        <Badge
          tone={badgeTone}
          className="shrink-0 rounded px-1.5 py-0.5 font-mono text-3xs font-semibold ring-0"
        >
          #{node.claim_no}
        </Badge>
        {node.is_independent && (
          <Badge
            tone="brand"
            className="shrink-0 rounded px-1 py-0.5 text-3xs font-semibold uppercase tracking-wider ring-0"
          >
            indep
          </Badge>
        )}
        <span className="flex-1 truncate font-normal" title={node.text || ''}>
          {preview}
          {hasMore && '…'}
        </span>
        {rejection && <RejectionChip rejection={rejection} />}
      </div>
    </li>
  );
}

function RejectionChip({ rejection }) {
  // Compact rejection-type label. Backend gives strings like
  // "103_obviousness" / "antecedent_basis" — map to the short statute
  // citation the attorneys use day-to-day.
  const label = SHORT_LABEL[rejection.rejection_type] || rejection.rejection_type;
  return (
    <Badge
      tone="error"
      variant="solid"
      className="shrink-0 rounded px-1.5 py-0.5 font-mono text-3xs font-semibold uppercase ring-0"
    >
      {label}
    </Badge>
  );
}

const SHORT_LABEL = {
  '102_novelty': '§102',
  '103_obviousness': '§103',
  '112_indefiniteness': '§112',
  antecedent_basis: 'AB',
  '101_subject_matter': '§101',
  double_patenting: 'DP',
  other: 'OTHER',
};

function Legend({ t }) {
  return (
    <div className="flex gap-1.5 text-3xs">
      <Badge tone="error" className="rounded px-1.5 py-0.5 ring-0">
        {t('analyze.claim_tree.legend.rejected', { defaultValue: '駁回 / Rejected' })}
      </Badge>
      <Badge tone="warning" className="rounded px-1.5 py-0.5 ring-0">
        {t('analyze.claim_tree.legend.cascade', { defaultValue: '連帶 / Cascade' })}
      </Badge>
      <Badge tone="success" className="rounded px-1.5 py-0.5 ring-0">
        {t('analyze.claim_tree.legend.clean', { defaultValue: '無駁回 / Clean' })}
      </Badge>
    </div>
  );
}
